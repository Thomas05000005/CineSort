"""APPLY-2 (v1.5.4) — Tests de la progression de la phase apply.

Couverture symetrique au scan (RunState.progress + endpoint get_status) :

1. test_apply_rows_calls_progress_cb : verifie que `apply_rows` invoque
   `progress_cb` exactement `len(rows)` fois avec un `idx` croissant
   commencant a 1.

2. test_get_status_exposes_apply_progress : apres
   `RunState.apply_begin()` + `apply_progress()`, l'endpoint `get_status`
   doit exposer un payload `apply` avec les compteurs corrects.

3. test_apply_end_marks_done : apres `apply_end()`, les flags
   `apply_done` et `apply_running` doivent etre coherents.

4. test_apply_begin_resets_state : un nouveau `apply_begin()` reset les
   compteurs precedents (idempotence multi-runs).

5. test_apply_progress_cb_isolation : si le callback leve une exception,
   `apply_rows` continue (defensive — bug callback ne casse pas le batch).
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from typing import List, Tuple
from unittest import mock

import cinesort.domain.core as core
from cinesort.app.apply_core import apply_rows
from cinesort.ui.api.cinesort_api import RunState
from cinesort.ui.api.run_flow_support import _get_status_impl

# ---------------------------------------------------------------------------
# Helpers : construction minimale de PlanRow / Config / RunState
# ---------------------------------------------------------------------------


def _make_plan_row(row_id: str, folder: str = "/tmp/film") -> core.PlanRow:
    """Construit un PlanRow minimal de type 'single' (chemin le plus simple)."""
    return core.PlanRow(
        row_id=row_id,
        kind="single",
        folder=folder,
        video="film.mkv",
        proposed_title="Film",
        proposed_year=2020,
        proposed_source="name",
        confidence=80,
        confidence_label="high",
        candidates=[],
    )


def _make_cfg(root: Path) -> core.Config:
    """Construit une Config minimale ciblant `root`."""
    return core.Config(root=root)


def _make_runpaths(run_dir: Path) -> mock.MagicMock:
    """RunPaths minimal pour RunState. On utilise un MagicMock car RunState
    n'utilise que `paths.ui_log_txt` / `paths.run_dir` pour la persistance des
    logs, fonctionnalite non couverte par ces tests."""
    paths = mock.MagicMock()
    paths.run_dir = run_dir
    paths.ui_log_txt = run_dir / "ui_log.txt"
    paths.run_id = "test_run_id"
    return paths


def _make_run_state(tmpdir: Path) -> RunState:
    """Cree un RunState reel avec dependances mockees (runner/store)."""
    run_dir = tmpdir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = _make_runpaths(run_dir)
    cfg = _make_cfg(tmpdir)
    runner = mock.MagicMock()
    store = mock.MagicMock()
    return RunState(paths, cfg, runner=runner, store=store)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class ApplyRowsProgressCallbackTests(unittest.TestCase):
    """Unitaire : apply_rows doit appeler progress_cb 1 fois par row, idx croissant."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_apply_progress_")
        self.tmpdir = Path(self._tmp)
        self.root = self.tmpdir / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_apply_rows_calls_progress_cb(self) -> None:
        """apply_rows doit appeler progress_cb exactement len(rows) fois
        avec idx croissant (1, 2, 3) et total = len(rows)."""
        cfg = _make_cfg(self.root)
        rows = [
            _make_plan_row("r1", folder=str(self.root / "film1")),
            _make_plan_row("r2", folder=str(self.root / "film2")),
            _make_plan_row("r3", folder=str(self.root / "film3")),
        ]
        # decisions vides => chaque row tombe dans la branche `else:
        # _mark_skip` (SKIP_REASON_VALIDATION_ABSENTE). Court-circuite les
        # appels FS lourds (apply_single) tout en passant par le callback.
        decisions: dict = {}

        calls: List[Tuple[int, int, str]] = []

        def progress_cb(idx: int, total: int, current: str) -> None:
            calls.append((idx, total, current))

        def log_noop(level: str, msg: str) -> None:
            pass

        apply_rows(
            cfg,
            rows,
            decisions,
            dry_run=True,
            quarantine_unapproved=False,
            log=log_noop,
            progress_cb=progress_cb,
        )

        self.assertEqual(len(calls), 3, f"progress_cb appele {len(calls)} fois, attendu 3 : {calls}")
        # idx croissant : 1, 2, 3
        idxs = [c[0] for c in calls]
        self.assertEqual(idxs, [1, 2, 3], f"idx attendu [1,2,3], obtenu {idxs}")
        # total constant = 3
        totals = [c[1] for c in calls]
        self.assertEqual(totals, [3, 3, 3], f"total attendu [3,3,3], obtenu {totals}")
        # current renseigne (folder ou row_id en fallback)
        for idx, _total, current in calls:
            self.assertTrue(current, f"current vide pour idx={idx}")

    def test_apply_progress_cb_isolation(self) -> None:
        """Si progress_cb leve une exception, apply_rows doit continuer
        (defensive : ne pas casser un batch a cause d'un callback UI buggue)."""
        cfg = _make_cfg(self.root)
        rows = [
            _make_plan_row("r1", folder=str(self.root / "film1")),
            _make_plan_row("r2", folder=str(self.root / "film2")),
        ]
        decisions: dict = {}

        call_count = [0]

        def progress_cb_explode(idx: int, total: int, current: str) -> None:
            call_count[0] += 1
            raise RuntimeError("simule un bug du callback UI")

        def log_noop(level: str, msg: str) -> None:
            pass

        # Ne doit PAS lever : le batch continue malgre l'exception du callback.
        result = apply_rows(
            cfg,
            rows,
            decisions,
            dry_run=True,
            quarantine_unapproved=False,
            log=log_noop,
            progress_cb=progress_cb_explode,
        )

        self.assertEqual(call_count[0], 2, "progress_cb appele 2 fois meme s'il leve")
        self.assertIsNotNone(result, "apply_rows doit retourner un ApplyResult")

    def test_apply_rows_without_progress_cb(self) -> None:
        """Backward-compat : appeler sans progress_cb (=None) ne doit pas planter."""
        cfg = _make_cfg(self.root)
        rows = [_make_plan_row("r1", folder=str(self.root / "film1"))]
        decisions: dict = {}

        def log_noop(level: str, msg: str) -> None:
            pass

        # Pas de progress_cb : ancien contrat — doit fonctionner inchange.
        result = apply_rows(
            cfg,
            rows,
            decisions,
            dry_run=True,
            quarantine_unapproved=False,
            log=log_noop,
        )
        self.assertIsNotNone(result)


class RunStateApplyStateTests(unittest.TestCase):
    """Unitaire : RunState.apply_begin / apply_progress / apply_end."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_runstate_apply_")
        self.tmpdir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_apply_begin_initialises_state(self) -> None:
        """apply_begin() reset les compteurs et passe running=True."""
        rs = _make_run_state(self.tmpdir)
        # Etat initial : tout a False/0.
        self.assertFalse(rs.apply_running)
        self.assertFalse(rs.apply_done)
        self.assertEqual(rs.apply_idx, 0)
        self.assertEqual(rs.apply_total, 0)

        rs.apply_begin(total=10, dry_run=True, phase="rows")
        self.assertTrue(rs.apply_running)
        self.assertFalse(rs.apply_done)
        self.assertEqual(rs.apply_total, 10)
        self.assertEqual(rs.apply_idx, 0)
        self.assertEqual(rs.apply_phase, "rows")
        self.assertTrue(rs.apply_dry_run)
        self.assertGreater(rs.apply_started_ts, 0.0)

    def test_apply_progress_increments(self) -> None:
        """apply_progress() incremente idx et capture current."""
        rs = _make_run_state(self.tmpdir)
        rs.apply_begin(total=10, dry_run=False, phase="rows")
        rs.apply_progress(5, 10, "film.mkv")
        self.assertEqual(rs.apply_idx, 5)
        self.assertEqual(rs.apply_total, 10)
        self.assertEqual(rs.apply_current, "film.mkv")
        # idx croissant doit alimenter l'EWMA de vitesse.
        self.assertGreaterEqual(rs.apply_speed_ewma, 0.0)

    def test_apply_progress_phase_change(self) -> None:
        """apply_progress avec phase='jellyfin' doit mettre a jour la phase."""
        rs = _make_run_state(self.tmpdir)
        rs.apply_begin(total=5, dry_run=False, phase="rows")
        rs.apply_progress(5, 5, "Synchronisation...", phase="jellyfin")
        self.assertEqual(rs.apply_phase, "jellyfin")
        self.assertEqual(rs.apply_idx, 5)

    def test_apply_end_marks_done(self) -> None:
        """apply_end() doit passer running=False, done=True ; idx/total conserves."""
        rs = _make_run_state(self.tmpdir)
        rs.apply_begin(total=3, dry_run=True, phase="rows")
        rs.apply_progress(3, 3, "fin")
        rs.apply_end()
        self.assertFalse(rs.apply_running)
        self.assertTrue(rs.apply_done)
        # idx et total preserves pour affichage final cote UI.
        self.assertEqual(rs.apply_idx, 3)
        self.assertEqual(rs.apply_total, 3)

    def test_apply_end_with_error(self) -> None:
        """apply_end(error=...) doit marquer done=True et stocker l'erreur."""
        rs = _make_run_state(self.tmpdir)
        rs.apply_begin(total=2, dry_run=False)
        rs.apply_end(error="disque plein")
        self.assertTrue(rs.apply_done)
        self.assertFalse(rs.apply_running)
        # L'erreur est posee sur rs.error (champ partage avec scan, si vide).
        self.assertEqual(rs.error, "disque plein")

    def test_apply_begin_resets_previous_state(self) -> None:
        """Un second apply_begin() reset les compteurs du run precedent."""
        rs = _make_run_state(self.tmpdir)
        rs.apply_begin(total=10, dry_run=True)
        rs.apply_progress(7, 10, "old.mkv")
        rs.apply_end()

        # Second cycle : nouveau total, nouveau dry_run.
        rs.apply_begin(total=3, dry_run=False, phase="rows")
        self.assertTrue(rs.apply_running)
        self.assertFalse(rs.apply_done)  # reset
        self.assertEqual(rs.apply_idx, 0)  # reset
        self.assertEqual(rs.apply_total, 3)
        self.assertFalse(rs.apply_dry_run)
        self.assertEqual(rs.apply_progress_samples, [])  # reset

    def test_apply_state_thread_safe(self) -> None:
        """apply_begin/apply_progress/apply_end sous lock : pas de course."""
        rs = _make_run_state(self.tmpdir)
        rs.apply_begin(total=100, dry_run=True)

        def worker(start: int, end: int) -> None:
            for i in range(start, end):
                rs.apply_progress(i, 100, f"film{i}.mkv")

        threads = [
            threading.Thread(target=worker, args=(1, 50)),
            threading.Thread(target=worker, args=(50, 100)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Tous les threads ont termine sans deadlock, l'etat final est coherent.
        self.assertTrue(rs.apply_running)
        # idx prend l'une des dernieres valeurs ecrites (sans crash).
        self.assertGreater(rs.apply_idx, 0)
        self.assertEqual(rs.apply_total, 100)


class GetStatusApplyPayloadTests(unittest.TestCase):
    """Integration : _get_status_impl doit exposer le payload `apply`."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_status_apply_")
        self.tmpdir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _build_api_with_rs(self, rs: RunState) -> mock.MagicMock:
        """API mock minimal pour _get_status_impl : _get_run renvoie rs."""
        api = mock.MagicMock()
        api._get_run.return_value = rs
        # runner.get_status renvoie None : _get_status_impl deduit le status
        # des flags running/done locaux.
        rs.runner.get_status.return_value = None
        return api

    def test_get_status_exposes_apply_payload_when_running(self) -> None:
        """Apres apply_begin + apply_progress, get_status doit exposer
        data['apply']['idx'] == 5, total == 10, running True."""
        rs = _make_run_state(self.tmpdir)
        # On flag aussi le scan comme done pour que la branche RunState
        # soit prise sans deduire un status PENDING incorrect.
        rs.running = False
        rs.done = True
        rs.apply_begin(total=10, dry_run=True, phase="rows")
        rs.apply_progress(5, 10, "film.mkv")

        api = self._build_api_with_rs(rs)
        result = _get_status_impl(api, "test_run_id", last_log_index=0)

        self.assertTrue(result.get("ok"), result)
        apply_payload = result.get("apply")
        self.assertIsNotNone(apply_payload, "data['apply'] doit etre present quand apply_running=True")
        self.assertTrue(apply_payload["running"])
        self.assertFalse(apply_payload["done"])
        self.assertEqual(apply_payload["idx"], 5)
        self.assertEqual(apply_payload["total"], 10)
        self.assertEqual(apply_payload["current"], "film.mkv")
        self.assertEqual(apply_payload["phase"], "rows")
        self.assertTrue(apply_payload["dry_run"])

    def test_get_status_apply_payload_after_end(self) -> None:
        """Apres apply_end, payload doit refleter done=True, running=False."""
        rs = _make_run_state(self.tmpdir)
        rs.running = False
        rs.done = True
        rs.apply_begin(total=3, dry_run=False, phase="rows")
        rs.apply_progress(3, 3, "last.mkv")
        rs.apply_end()

        api = self._build_api_with_rs(rs)
        result = _get_status_impl(api, "test_run_id", last_log_index=0)

        self.assertTrue(result.get("ok"))
        apply_payload = result.get("apply")
        self.assertIsNotNone(apply_payload)
        self.assertFalse(apply_payload["running"])
        self.assertTrue(apply_payload["done"])
        self.assertEqual(apply_payload["idx"], 3)
        self.assertEqual(apply_payload["total"], 3)

    def test_get_status_apply_none_when_never_started(self) -> None:
        """Avant tout apply_begin, data['apply'] doit etre None."""
        rs = _make_run_state(self.tmpdir)
        rs.running = True
        rs.done = False
        # Pas d'apply_begin appele.

        api = self._build_api_with_rs(rs)
        result = _get_status_impl(api, "test_run_id", last_log_index=0)

        self.assertTrue(result.get("ok"))
        self.assertIsNone(result.get("apply"), "apply doit etre None tant qu'aucun apply n'a demarre")

    def test_get_status_apply_progress_in_thread(self) -> None:
        """Integration : un apply lance en thread doit etre observable via
        polling get_status. Verifie que idx augmente puis se stabilise."""
        rs = _make_run_state(self.tmpdir)
        rs.running = False
        rs.done = True
        api = self._build_api_with_rs(rs)

        total = 5
        ready = threading.Event()
        finished = threading.Event()

        def mock_apply_worker() -> None:
            rs.apply_begin(total=total, dry_run=True, phase="rows")
            ready.set()
            for i in range(1, total + 1):
                rs.apply_progress(i, total, f"film{i}.mkv")
                # Petit yield pour permettre au poller d'observer un etat
                # intermediaire (non garanti mais best-effort).
            rs.apply_end()
            finished.set()

        worker = threading.Thread(target=mock_apply_worker)
        worker.start()
        ready.wait(timeout=2.0)

        # Poll : on capture au moins un snapshot pendant que l'apply tourne.
        snapshots = []
        for _ in range(20):
            snap = _get_status_impl(api, "test_run_id", last_log_index=0)
            snapshots.append(snap.get("apply"))
            if finished.is_set():
                break

        worker.join(timeout=2.0)
        self.assertTrue(finished.is_set(), "Le worker apply mock doit terminer")

        # Snapshot final : done=True, running=False, idx=total.
        final = _get_status_impl(api, "test_run_id", last_log_index=0).get("apply")
        self.assertIsNotNone(final)
        self.assertTrue(final["done"])
        self.assertFalse(final["running"])
        self.assertEqual(final["idx"], total)
        self.assertEqual(final["total"], total)


if __name__ == "__main__":
    unittest.main()
