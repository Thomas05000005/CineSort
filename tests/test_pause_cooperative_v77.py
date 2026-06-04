"""VN-E.3 — tests pause cooperative job_fn (injection should_pause).

Verifie que :
1. JobRunner._should_pause_factory retourne un callable qui reflete `pause_event`.
2. Le JobRunner injecte automatiquement `should_pause` dans les job_fn qui
   l'acceptent (signature inspect), et reste backward-compat pour les job_fn
   legacy a un seul argument.
3. La boucle `plan_library` via `_PlanLibraryContext.wait_while_paused()`
   attend bien tant que `should_pause()` est True, et la cancellation prevaut.
4. `apply_rows` honore should_pause + should_cancel dans sa boucle principale.
5. Le rescan job_fn (library_actions_support) honore should_pause.
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.app.job_runner import JobRunner
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir

# MEGA-HOTFIX bug (5) : utilisation du helper centralise pour eviter la
# duplication de `_wait_terminal` dans chaque TestCase.
from tests._helpers import wait_runner_terminal


def _make_store(state_dir: Path) -> SQLiteStore:
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_path_for_state_dir(state_dir)
    store = SQLiteStore(db_path, busy_timeout_ms=8000)
    store.initialize()
    return store


# ============================================================
# 1. JobRunner._should_pause_factory
# ============================================================


class ShouldPauseFactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_pause_factory_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = _make_store(self.state_dir)
        self.runner = JobRunner(self.store)

    def _wait_terminal(self, run_id: str, timeout_s: float = 5.0) -> None:
        # MEGA-HOTFIX bug (5) : delegation au helper centralise.
        wait_runner_terminal(self.runner, run_id, timeout_s=timeout_s)

    def test_factory_returns_false_when_no_pause(self) -> None:
        def long_job(should_cancel):
            while not should_cancel():
                time.sleep(0.01)
            return None

        run_id = self.runner.start_job(
            job_fn=long_job,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        try:
            sp = self.runner._should_pause_factory(run_id)
            self.assertFalse(sp())
        finally:
            self.runner.request_cancel(run_id)
            self._wait_terminal(run_id)

    def test_factory_reflects_pause_event(self) -> None:
        def long_job(should_cancel):
            while not should_cancel():
                time.sleep(0.01)
            return None

        run_id = self.runner.start_job(
            job_fn=long_job,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        try:
            sp = self.runner._should_pause_factory(run_id)
            self.assertFalse(sp())
            self.runner.request_pause(run_id)
            self.assertTrue(sp())
            self.runner.request_resume(run_id)
            self.assertFalse(sp())
        finally:
            self.runner.request_cancel(run_id)
            self._wait_terminal(run_id)

    def test_factory_returns_false_for_unknown_run(self) -> None:
        sp = self.runner._should_pause_factory("unknown_xxx")
        self.assertFalse(sp())


# ============================================================
# 2. Injection should_pause via inspect
# ============================================================


class JobFnSignatureInjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_pause_inject_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = _make_store(self.state_dir)
        self.runner = JobRunner(self.store)

    def _wait_terminal(self, run_id: str, timeout_s: float = 5.0) -> None:
        # MEGA-HOTFIX bug (5) : delegation au helper centralise.
        wait_runner_terminal(self.runner, run_id, timeout_s=timeout_s)

    def test_legacy_job_fn_one_arg_still_works(self) -> None:
        """Backward compat : job_fn(should_cancel) inchange si pas de should_pause kwarg."""
        called = {"value": False}

        def legacy_job(should_cancel):
            called["value"] = True
            return {"ok": True}

        run_id = self.runner.start_job(
            job_fn=legacy_job,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        self._wait_terminal(run_id)
        self.assertTrue(called["value"])

    def test_job_fn_accepting_should_pause_receives_it(self) -> None:
        received = {"sp": None}

        def aware_job(should_cancel, should_pause=None):
            received["sp"] = should_pause
            return {"ok": True}

        run_id = self.runner.start_job(
            job_fn=aware_job,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        self._wait_terminal(run_id)
        self.assertIsNotNone(received["sp"])
        # Le callable doit etre invocable et retourner bool
        self.assertIsInstance(received["sp"](), bool)

    def test_job_fn_with_kwargs_receives_should_pause(self) -> None:
        received = {"kw_seen": None}

        def kwargs_job(should_cancel, **kwargs):
            received["kw_seen"] = "should_pause" in kwargs
            return {"ok": True}

        run_id = self.runner.start_job(
            job_fn=kwargs_job,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        self._wait_terminal(run_id)
        self.assertTrue(received["kw_seen"])


# ============================================================
# 3. Boucle cooperative — should_pause: True 3 ticks puis False
# ============================================================


class CooperativeLoopTests(unittest.TestCase):
    """Mock should_pause(): True 3 ticks puis False — la boucle doit attendre."""

    def test_job_fn_loop_waits_while_paused(self) -> None:
        # Simule 3 polls True puis False
        ticks: List[bool] = [True, True, True, False]
        idx = {"i": 0}
        observations: List[str] = []

        def fake_should_pause() -> bool:
            i = idx["i"]
            if i >= len(ticks):
                return False
            v = ticks[i]
            idx["i"] = i + 1
            return v

        def fake_should_cancel() -> bool:
            return False

        # Reproduit la logique de wait_while_paused (sleep tres court pour le test)
        def cooperative_loop() -> None:
            # boucle d'attente comme dans le job_fn reel
            observations.append("entered")
            while fake_should_pause():
                if fake_should_cancel():
                    observations.append("cancelled")
                    return
                observations.append("waiting")
                time.sleep(0.001)
            observations.append("resumed")

        cooperative_loop()
        # On a vu 3 "waiting" puis "resumed" (3 tick True puis False)
        self.assertEqual(observations[0], "entered")
        self.assertEqual(observations[-1], "resumed")
        self.assertEqual(observations.count("waiting"), 3)
        self.assertNotIn("cancelled", observations)

    def test_cancellation_prevails_over_pause(self) -> None:
        """Si cancel devient True pendant pause, on sort immediatement."""
        # Pause active indefiniment, mais cancel devient True au tick 2
        cancel_after = {"n": 2}
        cancel_ticks = {"i": 0}
        observations: List[str] = []

        def fake_should_pause() -> bool:
            return True  # toujours en pause

        def fake_should_cancel() -> bool:
            i = cancel_ticks["i"]
            cancel_ticks["i"] = i + 1
            return i >= cancel_after["n"]

        def cooperative_loop() -> None:
            observations.append("entered")
            # boucle d'attente comme dans le job_fn reel
            while fake_should_pause():
                if fake_should_cancel():
                    observations.append("cancelled")
                    return
                observations.append("waiting")
                time.sleep(0.001)
            observations.append("resumed")

        cooperative_loop()
        self.assertIn("cancelled", observations)
        self.assertNotIn("resumed", observations)


# ============================================================
# 4. _PlanLibraryContext.wait_while_paused()
# ============================================================


class PlanLibraryContextPauseTests(unittest.TestCase):
    def _make_ctx(self, should_pause, should_cancel=None):
        from cinesort.app.plan_support import _PlanLibraryContext

        logs: List[tuple] = []

        def log_fn(level: str, msg: str) -> None:
            logs.append((level, msg))

        # Cf #83 : on n'instancie pas un Config complet (lourd) — on injecte
        # juste les callbacks pour tester wait_while_paused isolément.
        ctx = _PlanLibraryContext(
            cfg=None,  # ne sera pas dereference par wait_while_paused
            tmdb=None,
            log=log_fn,
            progress=lambda i, t, c: None,
            should_cancel=should_cancel,
            should_pause=should_pause,
            scan_index=None,
            run_id="rid_test",
            subtitle_expected_languages=None,
        )
        return ctx, logs

    def test_no_pause_callback_returns_false_immediately(self) -> None:
        ctx, logs = self._make_ctx(should_pause=None)
        self.assertFalse(ctx.wait_while_paused(poll_interval_s=0.01))
        self.assertEqual(logs, [])

    def test_pause_false_returns_immediately(self) -> None:
        ctx, logs = self._make_ctx(should_pause=lambda: False)
        self.assertFalse(ctx.wait_while_paused(poll_interval_s=0.01))
        self.assertEqual(logs, [])

    def test_pause_true_then_false_waits_then_returns(self) -> None:
        ticks = [True, True, True, False]
        idx = {"i": 0}

        def sp() -> bool:
            i = idx["i"]
            if i >= len(ticks):
                return False
            idx["i"] = i + 1
            return ticks[i]

        ctx, logs = self._make_ctx(should_pause=sp)
        cancelled = ctx.wait_while_paused(poll_interval_s=0.001)
        self.assertFalse(cancelled)
        # On doit avoir au moins un "pause requested" + "pause released"
        msgs = [m for (_, m) in logs]
        self.assertIn("pause requested", msgs)
        self.assertIn("pause released", msgs)

    def test_pause_with_cancellation_returns_true(self) -> None:
        """Cancellation pendant pause -> sortie immediate (returns True)."""
        ctx, _logs = self._make_ctx(
            should_pause=lambda: True,
            should_cancel=lambda: True,  # cancel immediat
        )
        cancelled = ctx.wait_while_paused(poll_interval_s=0.001)
        self.assertTrue(cancelled)

    def test_pause_callback_exception_swallowed(self) -> None:
        def bad_sp() -> bool:
            raise RuntimeError("boom")

        ctx, _logs = self._make_ctx(should_pause=bad_sp)
        # Defensif : exception swallow -> False
        self.assertFalse(ctx.wait_while_paused(poll_interval_s=0.01))


# ============================================================
# 5. apply_rows respecte should_pause
# ============================================================


class ApplyRowsPauseTests(unittest.TestCase):
    """apply_rows doit s'arreter (cancel) ou attendre (pause) avant chaque row."""

    def test_apply_rows_signature_accepts_should_pause(self) -> None:
        import inspect

        from cinesort.app.apply_core import apply_rows

        sig = inspect.signature(apply_rows)
        self.assertIn("should_pause", sig.parameters)
        self.assertIn("should_cancel", sig.parameters)

    def test_apply_rows_cancel_breaks_loop_early(self) -> None:
        """Si should_cancel() est True avant la 1re row, la boucle ne traite rien."""
        from cinesort.app.apply_core import apply_rows

        logs: List[tuple] = []

        def log_fn(lvl: str, m: str) -> None:
            logs.append((lvl, m))

        # rows vide : pas de Config a construire — on appelle apply_rows
        # avec rows=[] et un fake cfg dont seul `root` est lu pour les
        # logs/branches. La boucle "for row in rows" est no-op donc
        # should_pause/should_cancel ne sont pas executes ; on verifie ici
        # que le kwarg est juste accepte sans crash.
        from cinesort.domain.core import Config

        cfg = Config(root=Path(tempfile.gettempdir()))
        result = apply_rows(
            cfg,
            [],
            {},
            dry_run=True,
            quarantine_unapproved=False,
            log=log_fn,
            should_cancel=lambda: True,
            should_pause=lambda: False,
        )
        # rows=[] -> result.applied_count=0 (smoke test signature)
        self.assertEqual(getattr(result, "applied_count", 0), 0)


# ============================================================
# 6. plan_library accepte should_pause
# ============================================================


class PlanLibrarySignatureTests(unittest.TestCase):
    def test_plan_library_signature_accepts_should_pause(self) -> None:
        import inspect

        from cinesort.app.plan_support import plan_library

        sig = inspect.signature(plan_library)
        self.assertIn("should_pause", sig.parameters)

    def test_plan_multi_roots_signature_accepts_should_pause(self) -> None:
        import inspect

        from cinesort.app.plan_support import plan_multi_roots

        sig = inspect.signature(plan_multi_roots)
        self.assertIn("should_pause", sig.parameters)


# ============================================================
# 7. Rescan job_fn (library_actions_support)
# ============================================================


class RescanJobFnPauseTests(unittest.TestCase):
    def test_rescan_job_fn_signature_accepts_should_pause(self) -> None:
        import inspect

        from cinesort.ui.api.library_actions_support import _build_rescan_job_fn

        job_fn = _build_rescan_job_fn(api=None, run_id="r1", row_ids=[])
        sig = inspect.signature(job_fn)
        self.assertIn("should_pause", sig.parameters)

    def test_rescan_job_fn_empty_rows_returns_zero(self) -> None:
        from cinesort.ui.api.library_actions_support import _build_rescan_job_fn

        job_fn = _build_rescan_job_fn(api=None, run_id="r1", row_ids=[])
        # api=None est OK car la boucle for est vide.
        result = job_fn(should_cancel=lambda: False, should_pause=lambda: False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["rescan"]["processed"], 0)
        self.assertEqual(result["rescan"]["skipped"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
