"""Tests de regression - audit 2026-05-25 (v1.5.3) Vague H concurrence.

Couvre les 3 bugs de concurrence backend du fichier
``cinesort/ui/api/cinesort_api.py`` :

- **FIX 1** : ``RunState.log`` ecrivait dans ``ui_log.txt`` SANS lock,
  produisant des lignes interleavees en multi-thread.
- **FIX 2** : lectures de ``self._state_dir`` non-protegees par
  ``_state_dir_lock`` — une lecture pouvait observer un Path mid-mutation.
- **FIX 3** : ``_acquire_apply_slot`` sans context manager — un crash du
  caller laissait le slot bloque indefiniment.
"""

from __future__ import annotations

import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from cinesort.infra.state import RunPaths
from cinesort.ui.api.cinesort_api import CineSortApi, RunState


def _make_runstate(tmp_dir: Path) -> RunState:
    """Construit un RunState minimal pour tester ``log()``."""
    run_dir = tmp_dir / "run_test"
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = RunPaths(
        run_id="test_run",
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )
    # On bypass __init__ pour eviter de construire un Config/Runner/Store reel.
    rs = RunState.__new__(RunState)
    rs.paths = paths
    rs.cfg = MagicMock()
    rs.runner = MagicMock()
    rs.store = MagicMock()
    rs.lock = threading.Lock()
    rs._file_log_lock = threading.Lock()
    rs.running = False
    rs.done = False
    rs.error = None
    rs.idx = 0
    rs.total = 0
    rs.current_folder = ""
    rs.started_ts = 0.0
    rs.progress_samples = []
    rs.speed_ewma = 0.0
    rs.logs = []
    rs.rows = []
    rs.stats = None
    return rs


class LogFileAppendLockedTests(unittest.TestCase):
    """FIX 1 : multi-thread log() ne doit pas interleaver les lignes."""

    def test_log_file_append_locked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rs = _make_runstate(tmp_path)

            # Stress test : 20 threads, 50 logs chacun = 1000 lignes
            n_threads = 20
            n_logs_per_thread = 50

            def worker(thread_id: int) -> None:
                for i in range(n_logs_per_thread):
                    # Message volontairement long pour augmenter la fenetre
                    # d'interleaving si le lock n'est pas pris.
                    rs.log("INFO", f"thread_{thread_id:02d}_msg_{i:03d}_" + "X" * 200)

            threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()

            # Verifier que toutes les lignes du fichier commencent par [HH:MM:SS]
            log_path = rs.paths.ui_log_txt
            self.assertTrue(log_path.exists(), "ui_log.txt doit avoir ete cree")
            content = log_path.read_text(encoding="utf-8")
            lines = [ln for ln in content.split("\n") if ln]

            # Le format attendu : "[HH:MM:SS] LEVEL: message"
            ts_re = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] [A-Z]+: ")
            bad_lines = [ln for ln in lines if not ts_re.match(ln)]
            self.assertEqual(
                bad_lines,
                [],
                f"Toutes les lignes doivent commencer par [HH:MM:SS] LEVEL: — "
                f"{len(bad_lines)} ligne(s) interleavee(s) detectee(s).",
            )

            # Le total doit etre exact (pas de lignes perdues OU dupliquees)
            self.assertEqual(
                len(lines),
                n_threads * n_logs_per_thread,
                f"Attendu {n_threads * n_logs_per_thread} lignes, vu {len(lines)}",
            )


class ApplySlotGuardTests(unittest.TestCase):
    """FIX 3 : ``_apply_slot_guard`` doit liberer le slot meme en cas
    d'exception."""

    def test_apply_slot_guard_releases_on_exception(self) -> None:
        api = CineSortApi()
        run_id = "test_run_abc"

        # Avant : slot libre
        self.assertNotIn(run_id, api._apply_inflight_run_ids)

        # On simule un caller qui crash dans le `with`
        class _Boom(RuntimeError):
            pass

        with self.assertRaises(_Boom):
            with api._apply_slot_guard(run_id) as acquired:
                self.assertTrue(acquired, "Le premier acquire doit reussir")
                # Pendant le `with`, le slot est occupe
                self.assertIn(run_id, api._apply_inflight_run_ids)
                raise _Boom("crash simule du caller apply")

        # Apres l'exception : le slot DOIT etre libere (sinon le run est
        # bloque pour toute la duree du process).
        self.assertNotIn(
            run_id,
            api._apply_inflight_run_ids,
            "Le slot doit etre libere meme apres une exception du caller",
        )

    def test_apply_slot_guard_releases_on_success(self) -> None:
        api = CineSortApi()
        run_id = "test_run_xyz"

        with api._apply_slot_guard(run_id) as acquired:
            self.assertTrue(acquired)
            self.assertIn(run_id, api._apply_inflight_run_ids)
            # Pas d'exception : sortie normale

        # Slot libere
        self.assertNotIn(run_id, api._apply_inflight_run_ids)

    def test_apply_slot_guard_blocks_concurrent_acquire(self) -> None:
        """Si un run est deja in-flight, un deuxieme acquire doit echouer
        (acquired=False) et le `with` ne doit PAS toucher au set."""
        api = CineSortApi()
        run_id = "test_run_concurrent"

        with api._apply_slot_guard(run_id) as first:
            self.assertTrue(first)
            # Deuxieme guard pour le meme run_id
            with api._apply_slot_guard(run_id) as second:
                self.assertFalse(second, "Le deuxieme acquire doit echouer")
                # Le slot reste occupe par le premier
                self.assertIn(run_id, api._apply_inflight_run_ids)
            # Sortie du second `with` : ne doit PAS avoir liberer le slot
            # (puisqu'il n'avait pas acquis)
            self.assertIn(run_id, api._apply_inflight_run_ids)
        # Sortie du premier `with` : slot libere
        self.assertNotIn(run_id, api._apply_inflight_run_ids)


class StateDirHelperTests(unittest.TestCase):
    """FIX 2 : ``_get_state_dir`` doit retourner un Path atomique sous
    ``_state_dir_lock``."""

    def test_get_state_dir_returns_current_value(self) -> None:
        api = CineSortApi()
        original = api._state_dir
        self.assertEqual(api._get_state_dir(), original)

    def test_get_state_dir_is_thread_safe(self) -> None:
        """Pas de race entre _save_settings (mutation) et _get_state_dir
        (lecture) : les lectures ne doivent observer que des Path complets
        (initial OU path_a OU path_b), jamais d'etat partiel/corrompu.
        """
        import time as _time

        api = CineSortApi()
        initial = api._state_dir
        path_a = Path(tempfile.gettempdir()) / "state_dir_a"
        path_b = Path(tempfile.gettempdir()) / "state_dir_b"

        stop = threading.Event()
        observed: set[Path] = set()  # set pour eviter de stocker 500k entries
        observed_lock = threading.Lock()
        errors: list[Exception] = []
        # Barrier pour synchroniser le demarrage : tous les threads attendent
        # avant de commencer leur boucle, pour que le reader voie l'initial
        # avant la premiere mutation.
        barrier = threading.Barrier(3)

        def reader() -> None:
            try:
                barrier.wait()
                while not stop.is_set():
                    p = api._get_state_dir()
                    with observed_lock:
                        observed.add(p)
            except Exception as exc:
                errors.append(exc)

        def writer() -> None:
            try:
                barrier.wait()
                # Pause initiale pour que le reader observe l'initial.
                _time.sleep(0.01)
                for _ in range(200):
                    with api._state_dir_lock:
                        api._state_dir = path_a
                    _time.sleep(0.0001)  # cede le GIL au reader
                    with api._state_dir_lock:
                        api._state_dir = path_b
                    _time.sleep(0.0001)
            except Exception as exc:
                errors.append(exc)
            finally:
                stop.set()

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        self.assertEqual(errors, [], f"Lectures/ecritures concurrentes ont leve : {errors}")
        # Toutes les Path observees doivent etre dans le set des valeurs
        # valides. Une race produirait un Path corrompu ou un AttributeError
        # (capture dans errors).
        valid = {initial, path_a, path_b}
        invalid = observed - valid
        self.assertEqual(invalid, set(), f"Path invalide(s) observe(s) : {invalid}")
        # Le reader doit avoir observe au moins 2 valeurs differentes
        # (preuve que les lectures ne sont pas figees a une snapshot stale).
        self.assertGreaterEqual(
            len(observed), 2, f"Le reader n'a observe qu'une seule valeur ({observed}) — race non testee"
        )


if __name__ == "__main__":
    unittest.main()
