"""Tests Phase 4 — Backend Run Control endpoints (spec 08 Traitement §5).

4 endpoints testes :
- run.pause_run(run_id)           : PAUSED
- run.resume_run(run_id)          : RUNNING
- run.save_for_later(run_id)      : SAVED
- run.list_pending_runs()         : PAUSED + SAVED + AWAITING_VALIDATION
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from cinesort.app.job_runner import JobRunner
from cinesort.domain.run_models import RunStatus
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from cinesort.ui.api import run_control_support
from cinesort.ui.api.cinesort_api import CineSortApi


# ---------- helpers DB ----------


def _make_store(state_dir: Path) -> SQLiteStore:
    db_path = db_path_for_state_dir(state_dir)
    store = SQLiteStore(db_path, busy_timeout_ms=8000)
    store.initialize()
    return store


def _insert_run(store: SQLiteStore, run_id: str, *, status: str = "RUNNING") -> None:
    """Helper : insere un run avec un statut arbitraire (bypass enum-only)."""
    now = time.time()
    store.run.insert_run_pending(
        run_id=run_id,
        root="C:\\Films",
        state_dir="C:\\state",
        config={"dry_run": True},
        created_ts=now,
    )
    # Bascule vers le statut cible via UPDATE direct (les markers ne couvrent
    # pas tous les etats).
    if status != "PENDING":
        with store._managed_conn() as conn:
            conn.execute("UPDATE runs SET status=?, started_ts=? WHERE run_id=?", (status, now, run_id))


# ---------- migration 023 (schema) ----------


class MigrationSchemaTests(unittest.TestCase):
    """V8-01 : la migration 023 doit etendre la CHECK + ajouter paused_at."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_mig023_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = _make_store(self.state_dir)

    def test_user_version_at_least_23(self) -> None:
        with self.store._managed_conn() as conn:
            cur = conn.execute("PRAGMA user_version")
            row = cur.fetchone()
            version = int(row[0]) if row else 0
        self.assertGreaterEqual(version, 23)

    def test_runs_has_paused_at_column(self) -> None:
        with self.store._managed_conn() as conn:
            cur = conn.execute("PRAGMA table_info(runs)")
            cols = {row["name"] for row in cur.fetchall()}
        self.assertIn("paused_at", cols)

    def test_runs_status_check_accepts_new_states(self) -> None:
        """L'INSERT direct doit etre autorise pour les 3 nouveaux statuts."""
        for status in ("PAUSED", "SAVED", "AWAITING_VALIDATION"):
            with self.store._managed_conn() as conn:
                conn.execute(
                    "INSERT INTO runs (run_id, status, created_ts, root, state_dir, config_json)"
                    " VALUES (?, ?, ?, '', '', '{}')",
                    (f"check_{status}", status, time.time()),
                )


# ---------- RunRepository.mark_run_paused / mark_run_resumed ----------


class RunRepositoryPauseResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_repo_pause_")
        self.addCleanup(self._tmp.cleanup)
        self.store = _make_store(Path(self._tmp.name))

    def test_mark_run_paused_from_running(self) -> None:
        _insert_run(self.store, "rid_1", status="RUNNING")
        ok = self.store.run.mark_run_paused("rid_1")
        self.assertTrue(ok)
        row = self.store.run.get_run("rid_1")
        assert row is not None
        self.assertEqual(row["status"], "PAUSED")
        self.assertIsNotNone(row["paused_at"])

    def test_mark_run_paused_saved_flag(self) -> None:
        _insert_run(self.store, "rid_save", status="RUNNING")
        ok = self.store.run.mark_run_paused("rid_save", saved=True)
        self.assertTrue(ok)
        row = self.store.run.get_run("rid_save")
        assert row is not None
        self.assertEqual(row["status"], "SAVED")

    def test_mark_run_paused_rejects_terminal(self) -> None:
        _insert_run(self.store, "rid_done", status="DONE")
        ok = self.store.run.mark_run_paused("rid_done")
        self.assertFalse(ok)
        row = self.store.run.get_run("rid_done")
        assert row is not None
        self.assertEqual(row["status"], "DONE")

    def test_mark_run_resumed_from_paused(self) -> None:
        _insert_run(self.store, "rid_resume", status="PAUSED")
        ok = self.store.run.mark_run_resumed("rid_resume")
        self.assertTrue(ok)
        row = self.store.run.get_run("rid_resume")
        assert row is not None
        self.assertEqual(row["status"], "RUNNING")
        self.assertIsNone(row["paused_at"])

    def test_mark_run_resumed_rejects_terminal(self) -> None:
        _insert_run(self.store, "rid_cancelled", status="CANCELLED")
        ok = self.store.run.mark_run_resumed("rid_cancelled")
        self.assertFalse(ok)


# ---------- RunRepository.list_pending_runs ----------


class ListPendingRunsRepoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_list_pending_")
        self.addCleanup(self._tmp.cleanup)
        self.store = _make_store(Path(self._tmp.name))

    def test_returns_only_paused_saved_awaiting(self) -> None:
        _insert_run(self.store, "rid_running", status="RUNNING")
        _insert_run(self.store, "rid_done", status="DONE")
        _insert_run(self.store, "rid_paused", status="PAUSED")
        _insert_run(self.store, "rid_saved", status="SAVED")
        _insert_run(self.store, "rid_await", status="AWAITING_VALIDATION")
        _insert_run(self.store, "rid_cancelled", status="CANCELLED")

        rows = self.store.run.list_pending_runs()
        ids = {r["run_id"] for r in rows}
        self.assertEqual(ids, {"rid_paused", "rid_saved", "rid_await"})

    def test_row_shape_contains_required_keys(self) -> None:
        _insert_run(self.store, "rid_paused", status="PAUSED")
        self.store.run.mark_run_paused("rid_paused")
        rows = self.store.run.list_pending_runs()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(
            set(row.keys()),
            {"run_id", "status", "created_at", "total_rows", "last_activity_at"},
        )

    def test_empty_list_when_no_pending(self) -> None:
        _insert_run(self.store, "rid_done", status="DONE")
        rows = self.store.run.list_pending_runs()
        self.assertEqual(rows, [])


# ---------- JobRunner.request_pause / request_resume / is_paused ----------


class JobRunnerPauseResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_runner_pause_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = _make_store(self.state_dir)
        self.runner = JobRunner(self.store)

    def _wait_terminal(self, run_id: str, timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            snap = self.runner.get_status(run_id)
            if snap and snap.done:
                return
            time.sleep(0.02)

    def _start_long_job(self) -> str:
        def long_job(should_cancel):
            i = 0
            while i < 1000:
                if should_cancel():
                    return {"stopped_at": i}
                time.sleep(0.005)
                i += 1
            return {"stopped_at": i}

        return self.runner.start_job(
            job_fn=long_job,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={"dry_run": True},
        )

    def test_request_pause_sets_flag(self) -> None:
        run_id = self._start_long_job()
        try:
            self.assertFalse(self.runner.is_paused(run_id))
            ok = self.runner.request_pause(run_id)
            self.assertTrue(ok)
            self.assertTrue(self.runner.is_paused(run_id))
        finally:
            self.runner.request_cancel(run_id)
            self._wait_terminal(run_id)

    def test_request_resume_clears_flag(self) -> None:
        run_id = self._start_long_job()
        try:
            self.runner.request_pause(run_id)
            self.assertTrue(self.runner.is_paused(run_id))
            ok = self.runner.request_resume(run_id)
            self.assertTrue(ok)
            self.assertFalse(self.runner.is_paused(run_id))
        finally:
            self.runner.request_cancel(run_id)
            self._wait_terminal(run_id)

    def test_request_pause_unknown_run(self) -> None:
        self.assertFalse(self.runner.request_pause("unknown_id"))

    def test_is_paused_unknown_run(self) -> None:
        self.assertFalse(self.runner.is_paused("unknown_id"))


# ---------- run_control_support API-level ----------


class _StubApi:
    """Minimal CineSortApi stub for support-layer unit tests."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store
        # Lock structures suffisantes pour run_control_support.list_pending_runs
        import threading

        self._runs_lock = threading.Lock()
        self._infra_by_state_dir = {"k": (store, None)}
        self._state_dir = Path(".")
        self._runs = {}

    def _is_valid_run_id(self, run_id: str) -> bool:
        return bool(run_id) and isinstance(run_id, str) and len(run_id) >= 3

    def _find_run_row(self, run_id: str):
        row = self._store.run.get_run(run_id)
        if row:
            return row, self._store
        return None

    def _get_run(self, run_id: str):
        return None

    def _get_or_create_infra(self, state_dir):
        return self._store, None


class RunControlSupportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_rc_support_")
        self.addCleanup(self._tmp.cleanup)
        self.store = _make_store(Path(self._tmp.name))
        self.api = _StubApi(self.store)

    def test_pause_run_changes_status(self) -> None:
        _insert_run(self.store, "rid_pause_ep", status="RUNNING")
        result = run_control_support.pause_run(self.api, "rid_pause_ep")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "PAUSED")
        self.assertEqual(result["run_id"], "rid_pause_ep")
        row = self.store.run.get_run("rid_pause_ep")
        assert row is not None
        self.assertEqual(row["status"], "PAUSED")

    def test_pause_run_invalid_id(self) -> None:
        result = run_control_support.pause_run(self.api, "")
        self.assertFalse(result["ok"])

    def test_pause_run_unknown(self) -> None:
        result = run_control_support.pause_run(self.api, "nonexistent_id")
        self.assertFalse(result["ok"])

    def test_pause_run_already_done_refused(self) -> None:
        _insert_run(self.store, "rid_done_ep", status="DONE")
        result = run_control_support.pause_run(self.api, "rid_done_ep")
        self.assertFalse(result["ok"])

    def test_resume_run_brings_back_to_running(self) -> None:
        _insert_run(self.store, "rid_resume_ep", status="PAUSED")
        result = run_control_support.resume_run(self.api, "rid_resume_ep")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "RUNNING")
        row = self.store.run.get_run("rid_resume_ep")
        assert row is not None
        self.assertEqual(row["status"], "RUNNING")

    def test_resume_run_refused_on_running(self) -> None:
        _insert_run(self.store, "rid_already_running", status="RUNNING")
        result = run_control_support.resume_run(self.api, "rid_already_running")
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("status"), "RUNNING")

    def test_save_for_later_flags_saved(self) -> None:
        _insert_run(self.store, "rid_save_ep", status="RUNNING")
        result = run_control_support.save_for_later(self.api, "rid_save_ep")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "SAVED")
        row = self.store.run.get_run("rid_save_ep")
        assert row is not None
        self.assertEqual(row["status"], "SAVED")

    def test_list_pending_runs_only_target_states(self) -> None:
        _insert_run(self.store, "rid_p", status="PAUSED")
        _insert_run(self.store, "rid_s", status="SAVED")
        _insert_run(self.store, "rid_a", status="AWAITING_VALIDATION")
        _insert_run(self.store, "rid_r", status="RUNNING")
        _insert_run(self.store, "rid_d", status="DONE")

        result = run_control_support.list_pending_runs(self.api)
        self.assertTrue(result["ok"])
        ids = {r["run_id"] for r in result["runs"]}
        self.assertEqual(ids, {"rid_p", "rid_s", "rid_a"})

    def test_list_pending_runs_empty(self) -> None:
        _insert_run(self.store, "rid_only_running", status="RUNNING")
        result = run_control_support.list_pending_runs(self.api)
        self.assertTrue(result["ok"])
        self.assertEqual(result["runs"], [])

    def test_list_pending_runs_row_keys(self) -> None:
        _insert_run(self.store, "rid_x", status="PAUSED")
        result = run_control_support.list_pending_runs(self.api)
        self.assertTrue(result["runs"])
        row = result["runs"][0]
        self.assertEqual(
            set(row.keys()),
            {"run_id", "status", "created_at", "total_rows", "last_activity_at"},
        )


# ---------- RunFacade integration (api.run.X) ----------


class RunFacadeIntegrationTests(unittest.TestCase):
    """V8-01 : les 4 endpoints exposes via api.run.X delegent vers les *_impl.

    Pour eviter de toucher la DB utilisateur (%LOCALAPPDATA%\\CineSort), on
    pointe le state_dir vers un repertoire temporaire avant l'instanciation.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_facade_run_")
        self.addCleanup(self._tmp.cleanup)
        self.api = CineSortApi()
        # Override du state_dir pour isolation des tests.
        self.api._state_dir = Path(self._tmp.name)

    def test_facade_pause_run_exists_and_validates(self) -> None:
        result = self.api.run.pause_run("")
        self.assertFalse(result["ok"])

    def test_facade_resume_run_exists_and_validates(self) -> None:
        result = self.api.run.resume_run("")
        self.assertFalse(result["ok"])

    def test_facade_save_for_later_exists_and_validates(self) -> None:
        result = self.api.run.save_for_later("")
        self.assertFalse(result["ok"])

    def test_facade_list_pending_runs_exists(self) -> None:
        result = self.api.run.list_pending_runs()
        self.assertIn("ok", result)
        if result.get("ok"):
            self.assertIn("runs", result)
            self.assertIsInstance(result["runs"], list)


# ---------- RunStatus enum ----------


class RunStatusEnumTests(unittest.TestCase):
    def test_new_states_present(self) -> None:
        values = {s.value for s in RunStatus}
        self.assertIn("PAUSED", values)
        self.assertIn("SAVED", values)
        self.assertIn("AWAITING_VALIDATION", values)


if __name__ == "__main__":
    unittest.main(verbosity=2)
