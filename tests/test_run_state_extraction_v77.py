"""M-07 (Vague M) — Tests d'extraction de la classe ``RunState``.

L'extraction (cinesort_api.py L118-L282 -> cinesort/ui/api/_run_state.py) doit
preserver :

1. **Import direct** : ``from cinesort.ui.api._run_state import RunState``
   fonctionne et retourne bien une classe.

2. **Back-compat re-export** : l'import historique
   ``from cinesort.ui.api.cinesort_api import RunState`` (utilise par tests
   apply_progress, vague_h_concurrency, ...) reste fonctionnel.

3. **Identite de classe** : les deux imports pointent sur la MEME classe
   (sinon ``isinstance`` casse cote callers existants).

4. **Thread-safety progress()** : appels concurrents protected par
   ``self.lock`` (smoke test multi-thread).

5. **Transitions apply_begin / apply_progress / apply_end** : machine d'etat
   coherente (running -> progress -> done).

6. **Locks separes** : ``self.lock`` et ``self._file_log_lock`` sont deux
   instances distinctes (regression check post-extraction).
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core


def _make_runpaths(run_dir: Path) -> mock.MagicMock:
    """RunPaths minimal — seule ui_log_txt et run_dir sont touches."""
    paths = mock.MagicMock()
    paths.run_dir = run_dir
    paths.ui_log_txt = run_dir / "ui_log.txt"
    paths.run_id = "test_run_id"
    return paths


def _make_run_state(tmpdir: Path):
    """Construit un RunState reel — import dynamique pour ne pas dependre du
    chemin d'import dans les helpers."""
    from cinesort.ui.api._run_state import RunState

    run_dir = tmpdir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = _make_runpaths(run_dir)
    cfg = core.Config(root=tmpdir)
    runner = mock.MagicMock()
    store = mock.MagicMock()
    return RunState(paths, cfg, runner=runner, store=store)


class RunStateImportTests(unittest.TestCase):
    """Verifie que les deux chemins d'import fonctionnent et pointent sur la
    meme classe (back-compat)."""

    def test_import_from_new_module(self) -> None:
        from cinesort.ui.api._run_state import RunState

        self.assertTrue(callable(RunState))
        self.assertEqual(RunState.__module__, "cinesort.ui.api._run_state")

    def test_import_back_compat_from_cinesort_api(self) -> None:
        """Les callers historiques (apply_support, run_flow_support, tests
        apply_progress, vague_h_concurrency) doivent continuer a fonctionner
        via le re-export ``from cinesort.ui.api.cinesort_api import RunState``."""
        from cinesort.ui.api.cinesort_api import RunState

        self.assertTrue(callable(RunState))

    def test_both_imports_point_to_same_class(self) -> None:
        """Critique : si les deux imports etaient des classes differentes,
        ``isinstance(rs, RunState)`` casserait dans les callers."""
        from cinesort.ui.api._run_state import RunState as RS_direct
        from cinesort.ui.api.cinesort_api import RunState as RS_compat

        self.assertIs(RS_direct, RS_compat)

    def test_max_run_log_items_exported(self) -> None:
        """La constante MAX_RUN_LOG_ITEMS doit etre accessible depuis le
        nouveau module (et reste alignee avec celle de cinesort_api.py)."""
        from cinesort.ui.api._run_state import MAX_RUN_LOG_ITEMS as MAX_NEW
        from cinesort.ui.api.cinesort_api import MAX_RUN_LOG_ITEMS as MAX_OLD

        self.assertEqual(MAX_NEW, MAX_OLD)
        self.assertGreater(MAX_NEW, 0)


class RunStateConstructionTests(unittest.TestCase):
    """Verifie que la construction initialise correctement les champs scan +
    apply."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_m07_")
        self.tmpdir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_construction_initializes_scan_fields(self) -> None:
        rs = _make_run_state(self.tmpdir)
        self.assertFalse(rs.running)
        self.assertFalse(rs.done)
        self.assertIsNone(rs.error)
        self.assertEqual(rs.idx, 0)
        self.assertEqual(rs.total, 0)
        self.assertEqual(rs.current_folder, "")
        self.assertEqual(rs.speed_ewma, 0.0)
        self.assertEqual(rs.logs, [])
        self.assertEqual(rs.rows, [])

    def test_construction_initializes_apply_fields(self) -> None:
        rs = _make_run_state(self.tmpdir)
        self.assertFalse(rs.apply_running)
        self.assertFalse(rs.apply_done)
        self.assertEqual(rs.apply_phase, "")
        self.assertEqual(rs.apply_idx, 0)
        self.assertEqual(rs.apply_total, 0)
        self.assertEqual(rs.apply_current, "")
        self.assertFalse(rs.apply_dry_run)

    def test_locks_are_distinct_instances(self) -> None:
        """Vague H : ``self.lock`` (mutation memoire) et
        ``self._file_log_lock`` (I/O fichier) doivent etre deux locks
        differents pour ne pas bloquer mutuellement."""
        rs = _make_run_state(self.tmpdir)
        self.assertIsNot(rs.lock, rs._file_log_lock)


class RunStateProgressThreadSafetyTests(unittest.TestCase):
    """Smoke test multi-thread : N writers appelant progress() en parallele
    ne corrompent pas la liste ``progress_samples`` (verifie que self.lock
    serialise bien les ecritures)."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_m07_tsafe_")
        self.tmpdir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_progress_concurrent_writers_dont_corrupt_state(self) -> None:
        rs = _make_run_state(self.tmpdir)

        N_THREADS = 8
        N_CALLS = 50

        def _worker(thread_idx: int) -> None:
            for i in range(N_CALLS):
                rs.progress(thread_idx * N_CALLS + i + 1, N_THREADS * N_CALLS, f"t{thread_idx}-{i}")

        threads = [threading.Thread(target=_worker, args=(t,)) for t in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # progress_samples est capable de grandir jusqu'a 400 entries (window
        # de smoothing). On verifie surtout l'absence de corruption (chaque
        # entry est bien (float, int) et la window n'a pas explose).
        self.assertLessEqual(len(rs.progress_samples), 400)
        for sample in rs.progress_samples:
            self.assertEqual(len(sample), 2)
            self.assertIsInstance(sample[0], float)
            self.assertIsInstance(sample[1], int)


class RunStateApplyTransitionsTests(unittest.TestCase):
    """Machine d'etat apply : begin -> progress -> end."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_m07_apply_")
        self.tmpdir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_apply_begin_sets_running_resets_counters(self) -> None:
        rs = _make_run_state(self.tmpdir)
        # Salissons des compteurs precedents pour verifier le reset.
        rs.apply_idx = 42
        rs.apply_total = 999
        rs.apply_done = True

        rs.apply_begin(total=10, dry_run=True, phase="rows")

        self.assertTrue(rs.apply_running)
        self.assertFalse(rs.apply_done)
        self.assertEqual(rs.apply_idx, 0)
        self.assertEqual(rs.apply_total, 10)
        self.assertEqual(rs.apply_phase, "rows")
        self.assertTrue(rs.apply_dry_run)
        self.assertGreater(rs.apply_started_ts, 0.0)

    def test_apply_progress_updates_counters(self) -> None:
        rs = _make_run_state(self.tmpdir)
        rs.apply_begin(total=10, dry_run=False, phase="rows")
        rs.apply_progress(idx=3, total=10, current="film.mkv", phase="rows")

        self.assertEqual(rs.apply_idx, 3)
        self.assertEqual(rs.apply_total, 10)
        self.assertEqual(rs.apply_current, "film.mkv")
        self.assertEqual(rs.apply_phase, "rows")
        self.assertTrue(rs.apply_running)

    def test_apply_progress_phase_change(self) -> None:
        """Le parametre phase=None ne touche pas la phase courante ; une
        valeur explicite la change (rows -> jellyfin)."""
        rs = _make_run_state(self.tmpdir)
        rs.apply_begin(total=10, dry_run=False, phase="rows")
        rs.apply_progress(idx=5, total=10, current="x", phase=None)
        self.assertEqual(rs.apply_phase, "rows")

        rs.apply_progress(idx=6, total=10, current="y", phase="jellyfin")
        self.assertEqual(rs.apply_phase, "jellyfin")

    def test_apply_end_marks_done_keeps_counters(self) -> None:
        rs = _make_run_state(self.tmpdir)
        rs.apply_begin(total=10, dry_run=False, phase="rows")
        rs.apply_progress(idx=7, total=10, current="x", phase="rows")
        rs.apply_end()

        self.assertFalse(rs.apply_running)
        self.assertTrue(rs.apply_done)
        # Conservation des compteurs pour affichage final.
        self.assertEqual(rs.apply_idx, 7)
        self.assertEqual(rs.apply_total, 10)

    def test_apply_end_with_error_stores_error_if_none(self) -> None:
        rs = _make_run_state(self.tmpdir)
        rs.apply_begin(total=10, dry_run=False, phase="rows")
        rs.apply_end(error="boom")

        self.assertTrue(rs.apply_done)
        self.assertEqual(rs.error, "boom")

    def test_apply_end_with_error_does_not_overwrite_scan_error(self) -> None:
        """Si self.error contient deja une erreur scan, apply_end ne la
        surcharge pas (le frontend lit apply.done + run.error separement)."""
        rs = _make_run_state(self.tmpdir)
        rs.error = "scan_error"
        rs.apply_begin(total=10, dry_run=False, phase="rows")
        rs.apply_end(error="apply_error")

        self.assertEqual(rs.error, "scan_error")
        self.assertTrue(rs.apply_done)


class RunStateLogFileLockTests(unittest.TestCase):
    """Smoke test : log() peut etre appele en multi-thread sans crasher et
    persiste bien les lignes dans ui_log.txt (lock _file_log_lock actif)."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_m07_log_")
        self.tmpdir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_log_multithread_no_crash(self) -> None:
        rs = _make_run_state(self.tmpdir)
        N_THREADS = 4
        N_CALLS = 20

        def _worker(idx: int) -> None:
            for i in range(N_CALLS):
                rs.log("INFO", f"thread-{idx}-msg-{i}")

        threads = [threading.Thread(target=_worker, args=(t,)) for t in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Tous les logs in-memory doivent etre presents.
        self.assertEqual(len(rs.logs), N_THREADS * N_CALLS)
        # ui_log.txt doit avoir ete cree et contenir des lignes.
        self.assertTrue(rs.paths.ui_log_txt.exists())
        content = rs.paths.ui_log_txt.read_text(encoding="utf-8")
        # Sans interleaving : chaque ligne commence par "[HH:MM:SS] INFO: thread-..."
        for line in content.splitlines():
            self.assertTrue(line.startswith("["), f"Bad line: {line!r}")


if __name__ == "__main__":
    unittest.main()
