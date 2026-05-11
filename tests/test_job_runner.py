from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from typing import Callable

from cinesort.app.job_runner import JobRunner
from cinesort.domain.run_models import RunStatus
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir


class JobRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_job_runner_")
        self.addCleanup(self._tmp.cleanup)

        self.state_dir = Path(self._tmp.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = db_path_for_state_dir(self.state_dir)
        self.store = SQLiteStore(self.db_path, busy_timeout_ms=8000)
        self.store.initialize()
        self.runner = JobRunner(self.store)

    def wait_until(
        self, predicate: Callable[[], bool], timeout_s: float = 4.0, poll_s: float = 0.02, message: str = "Timeout"
    ) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(poll_s)
        self.fail(message)

    def wait_terminal(self, run_id: str, timeout_s: float = 5.0):
        def _is_terminal() -> bool:
            snap = self.runner.get_status(run_id)
            return bool(snap and snap.done)

        self.wait_until(
            _is_terminal, timeout_s=timeout_s, poll_s=0.02, message=f"Run {run_id} did not reach terminal state in time"
        )
        snap = self.runner.get_status(run_id)
        self.assertIsNotNone(snap)
        return snap

    def test_start_done_transitions(self) -> None:
        def short_job(_should_cancel):
            return {"planned_rows": 1}

        run_id = self.runner.start_job(
            job_fn=short_job,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={"dry_run": True},
        )
        snap = self.wait_terminal(run_id)
        assert snap is not None
        self.assertEqual(snap.status, RunStatus.DONE)
        self.assertTrue(snap.done)
        self.assertFalse(snap.running)

        row = self.store.get_run(run_id)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], "DONE")
        self.assertIsNotNone(row["started_ts"])
        self.assertIsNotNone(row["ended_ts"])

    def test_cancel_transitions(self) -> None:
        def long_job(should_cancel):
            i = 0
            while i < 10000:
                if should_cancel():
                    return {"stopped_at": i}
                time.sleep(0.01)
                i += 1
            return {"stopped_at": i}

        run_id = self.runner.start_job(
            job_fn=long_job,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={"dry_run": True},
        )

        # cancel should work whether run is still PENDING or already RUNNING
        self.assertTrue(self.runner.request_cancel(run_id))
        snap = self.wait_terminal(run_id, timeout_s=6.0)
        assert snap is not None
        self.assertEqual(snap.status, RunStatus.CANCELLED)
        self.assertTrue(snap.cancel_requested)

        row = self.store.get_run(run_id)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], "CANCELLED")
        self.assertEqual(int(row["cancel_requested"]), 1)

    def test_refuse_second_run_while_running(self) -> None:
        started = {"value": False}

        def long_job(should_cancel):
            started["value"] = True
            i = 0
            while i < 10000:
                if should_cancel():
                    return {"i": i}
                time.sleep(0.01)
                i += 1
            return {"i": i}

        run_id = self.runner.start_job(
            job_fn=long_job,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={},
        )

        self.wait_until(
            lambda: bool(
                self.runner.get_status(run_id)
                and self.runner.get_status(run_id).status == RunStatus.RUNNING
                and started["value"]
            ),
            timeout_s=3.0,
            poll_s=0.02,
            message="First run did not enter RUNNING state",
        )

        with self.assertRaisesRegex(RuntimeError, "deja en cours"):
            self.runner.start_job(
                job_fn=long_job,
                root=r"D:\Films",
                state_dir=str(self.state_dir),
                config={},
            )

        self.assertTrue(self.runner.request_cancel(run_id))
        snap = self.wait_terminal(run_id)
        assert snap is not None
        self.assertEqual(snap.status, RunStatus.CANCELLED)

    def test_failed_job_writes_error_row(self) -> None:
        def failing_job(_should_cancel):
            raise ValueError("boom")

        run_id = self.runner.start_job(
            job_fn=failing_job,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={},
        )
        snap = self.wait_terminal(run_id)
        assert snap is not None
        self.assertEqual(snap.status, RunStatus.FAILED)
        self.assertIn("boom", snap.error or "")

        row = self.store.get_run(run_id)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], "FAILED")
        self.assertIn("boom", row["error_message"] or "")

        errs = self.store.list_errors(run_id)
        self.assertGreaterEqual(len(errs), 1)
        self.assertEqual(errs[0]["code"], "ValueError")
        self.assertEqual(errs[0]["step"], "job_runner")

    def test_active_run_released_after_cancel_or_failure(self) -> None:
        def long_job(should_cancel):
            i = 0
            while i < 10000:
                if should_cancel():
                    return {"i": i}
                time.sleep(0.01)
                i += 1
            return {"i": i}

        run_cancel = self.runner.start_job(
            job_fn=long_job,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={},
        )
        self.assertTrue(self.runner.request_cancel(run_cancel))
        snap_cancel = self.wait_terminal(run_cancel)
        assert snap_cancel is not None
        self.assertEqual(snap_cancel.status, RunStatus.CANCELLED)

        def short_job(_should_cancel):
            return {"ok": True}

        run_after_cancel = self.runner.start_job(
            job_fn=short_job,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={},
        )
        snap_after_cancel = self.wait_terminal(run_after_cancel)
        assert snap_after_cancel is not None
        self.assertEqual(snap_after_cancel.status, RunStatus.DONE)

        def fail_job(_should_cancel):
            raise RuntimeError("fail-fast")

        run_fail = self.runner.start_job(
            job_fn=fail_job,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={},
        )
        snap_fail = self.wait_terminal(run_fail)
        assert snap_fail is not None
        self.assertEqual(snap_fail.status, RunStatus.FAILED)

        run_after_fail = self.runner.start_job(
            job_fn=short_job,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={},
        )
        snap_after_fail = self.wait_terminal(run_after_fail)
        assert snap_after_fail is not None
        self.assertEqual(snap_after_fail.status, RunStatus.DONE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
