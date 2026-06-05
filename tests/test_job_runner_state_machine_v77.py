"""MEGA-HOTFIX bug (3) : couverture state machine job_runner (C2 + C4 + H15 + H16).

Verifie les transitions critiques de `JobRunner` autour des etats sous
controle operateur (PAUSED / SAVED / AWAITING_VALIDATION) :

- C2 : PENDING -> CANCEL (run annule avant que le worker n'ait pu appeler
  mark_run_running) doit produire started_ts = ended_ts > 0 (duree 0s
  documentee, snapshot.status = CANCELLED).
- C4 : si le DB est passe en PAUSED pendant l'execution du job_fn, le
  worker NE DOIT PAS ecraser le DB avec DONE/CANCELLED/FAILED.
- H15 : un run PAUSED detient toujours le slot actif - `start_job` doit
  refuser un second run en parallele.
- H16 : `request_cancel` sur un run PAUSED doit effacer `pause_event`
  pour debloquer le worker cooperatif.

Les job_fn sont synchrones et minimaux : pas de threading complexe, le
worker JobRunner pilote la transition en interne.
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Optional

from cinesort.app.job_runner import JobRunner
from cinesort.domain.run_models import RunStatus
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from tests._helpers import wait_runner_status, wait_runner_terminal


def _make_store(state_dir: Path) -> SQLiteStore:
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_path_for_state_dir(state_dir)
    store = SQLiteStore(db_path, busy_timeout_ms=8000)
    store.initialize()
    return store


# ============================================================
# C2 : PENDING -> CANCEL doit forcer started_ts = ended_ts
# ============================================================


class PendingToCancelTransitionTests(unittest.TestCase):
    """C2 fix (hotfix2) : un run annule avant mark_run_running doit etre
    persiste CANCELLED avec started_ts = ended_ts (duree 0s).
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_jr_state_c2_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = _make_store(self.state_dir)
        self.runner = JobRunner(self.store)

    def test_cancel_before_worker_starts(self) -> None:
        """Lorsque cancel_event est pose avant le run du job_fn, le worker
        court-circuite la phase RUNNING mais persiste tout de meme un
        started_ts != None.
        """
        worker_called = threading.Event()
        worker_proceed = threading.Event()

        def slow_job(should_cancel):
            worker_called.set()
            worker_proceed.wait(timeout=2.0)
            return None

        # On bloque l'API run pour annuler avant que worker_called.set()
        # ne se declenche : impossible en synchrone, donc on fait une variante
        # plus directe : on annule juste apres start, puis on libere proceed.
        # NB : la C2 condition `cancelled_before_run` ne se declenche que si
        # cancel_event etait set AVANT que le worker n'atteigne ce check, ce
        # qui est tres rapide. On exploite la latence du dispatch thread.
        run_id = self.runner.start_job(
            job_fn=slow_job,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        # On ne peut pas garantir 100% que le check passe avant le start du
        # job_fn (race window tres etroite). On verifie le comportement final
        # robuste : le run termine en CANCELLED avec started_ts non-None.
        self.runner.request_cancel(run_id)
        worker_proceed.set()
        wait_runner_terminal(self.runner, run_id, timeout_s=5.0)

        snap = self.runner.get_status(run_id)
        self.assertIsNotNone(snap)
        self.assertTrue(snap.done)
        # started_ts doit etre defini : invariant metier C2 fix.
        self.assertIsNotNone(snap.started_ts, "started_ts doit etre non-None apres CANCEL")
        # ended_ts doit etre >= started_ts.
        self.assertIsNotNone(snap.ended_ts)
        self.assertGreaterEqual(snap.ended_ts, snap.started_ts)
        self.assertEqual(snap.status, RunStatus.CANCELLED)


# ============================================================
# C4 : PAUSED desync - worker ne doit pas ecraser le DB
# ============================================================


class PausedDesyncWorkerTransitionTests(unittest.TestCase):
    """C4 fix : si le DB est en PAUSED/SAVED/AWAITING quand le worker
    termine son job_fn, il NE DOIT PAS ecraser le statut DB.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_jr_state_c4_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = _make_store(self.state_dir)
        self.runner = JobRunner(self.store)

    def test_db_paused_skips_terminal_transition(self) -> None:
        """Quand `_is_user_held_state(db_status)` est True, le worker doit
        court-circuiter le mark_run_done et conserver le statut PAUSED.
        """
        proceed = threading.Event()

        def short_job(should_cancel):
            proceed.wait(timeout=3.0)
            return {"ok": True}

        run_id = self.runner.start_job(
            job_fn=short_job,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        # Attend que le worker passe en RUNNING.
        self.assertTrue(wait_runner_status(self.runner, run_id, RunStatus.RUNNING, timeout_s=3.0))

        # On marque PAUSED en DB directement (simule l'API qui pose pause).
        self.runner.request_pause(run_id)
        # Le pause_event est pose. On simule le call API mark_run_paused.
        self.store.run.mark_run_paused(run_id)

        # On libere le job_fn (qui retourne immediatement).
        proceed.set()
        # Le worker va detecter db_status=PAUSED et ne PAS marquer DONE.
        time.sleep(0.3)

        row = self.store.run.get_run(run_id)
        self.assertIsNotNone(row)
        self.assertEqual(
            str(row.get("status") or ""),
            RunStatus.PAUSED.value,
            "DB doit rester PAUSED (worker ne doit pas ecraser)",
        )

        # Nettoyage : on resume puis cancel pour terminer proprement.
        self.runner.request_resume(run_id)
        self.runner.request_cancel(run_id)
        wait_runner_terminal(self.runner, run_id, timeout_s=3.0)


# ============================================================
# H15 : run PAUSED detient toujours le slot actif
# ============================================================


class PausedHoldsActiveSlotTests(unittest.TestCase):
    """H15 fix : `_active_run_locked` doit considerer PAUSED, SAVED,
    AWAITING_VALIDATION comme actifs reserves -> start_job refuse un
    second run en parallele.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_jr_state_h15_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = _make_store(self.state_dir)
        self.runner = JobRunner(self.store)

    def test_paused_run_blocks_new_start_job(self) -> None:
        proceed = threading.Event()

        def long_job(should_cancel, **kwargs):
            proceed.wait(timeout=5.0)
            return None

        run_id = self.runner.start_job(
            job_fn=long_job,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        try:
            self.assertTrue(wait_runner_status(self.runner, run_id, RunStatus.RUNNING, timeout_s=3.0))
            # Met le run en PAUSED.
            self.runner.request_pause(run_id)
            self.assertTrue(wait_runner_status(self.runner, run_id, RunStatus.PAUSED, timeout_s=3.0))

            # Tentative de lancer un deuxieme job_fn -> doit lever.
            def second_job(should_cancel):
                return None

            with self.assertRaises(RuntimeError):
                self.runner.start_job(
                    job_fn=second_job,
                    root=str(self.state_dir),
                    state_dir=str(self.state_dir),
                    config={},
                )
        finally:
            self.runner.request_resume(run_id)
            self.runner.request_cancel(run_id)
            proceed.set()
            wait_runner_terminal(self.runner, run_id, timeout_s=3.0)


# ============================================================
# H16 : request_cancel sur PAUSED doit clear pause_event
# ============================================================


class CancelClearsPauseEventTests(unittest.TestCase):
    """H16 fix : `request_cancel` sur un run PAUSED doit effacer le
    pause_event pour debloquer le worker cooperatif.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_jr_state_h16_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = _make_store(self.state_dir)
        self.runner = JobRunner(self.store)

    def test_cancel_paused_clears_pause_event(self) -> None:
        proceed = threading.Event()

        def long_job(should_cancel):
            while not should_cancel():
                time.sleep(0.02)
            proceed.set()
            return None

        run_id = self.runner.start_job(
            job_fn=long_job,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        try:
            self.assertTrue(wait_runner_status(self.runner, run_id, RunStatus.RUNNING, timeout_s=3.0))
            self.runner.request_pause(run_id)
            self.assertTrue(self.runner.is_paused(run_id), "Doit etre en pause apres request_pause")

            # Cancel sur PAUSED doit clear pause_event + set cancel_event.
            self.assertTrue(self.runner.request_cancel(run_id))
            self.assertFalse(
                self.runner.is_paused(run_id),
                "pause_event doit etre clear apres request_cancel (H16)",
            )

            # Le worker doit se debloquer et terminer.
            wait_runner_terminal(self.runner, run_id, timeout_s=5.0)
            self.assertTrue(proceed.is_set(), "Le worker doit avoir vu cancel et termine")
        finally:
            if not self.runner.get_status(run_id).done:
                self.runner.request_resume(run_id)
                self.runner.request_cancel(run_id)
                wait_runner_terminal(self.runner, run_id, timeout_s=3.0)

    def test_cancel_running_does_not_touch_pause_event(self) -> None:
        """Cancel sur un run RUNNING (pas en pause) doit etre idempotent
        sur pause_event (pas de clear inutile).
        """
        def long_job(should_cancel):
            while not should_cancel():
                time.sleep(0.02)
            return None

        run_id = self.runner.start_job(
            job_fn=long_job,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        try:
            self.assertTrue(wait_runner_status(self.runner, run_id, RunStatus.RUNNING, timeout_s=3.0))
            self.assertFalse(self.runner.is_paused(run_id))
            self.assertTrue(self.runner.request_cancel(run_id))
            self.assertFalse(self.runner.is_paused(run_id))
        finally:
            wait_runner_terminal(self.runner, run_id, timeout_s=3.0)


# ============================================================
# WHERE clauses : _is_user_held_state semantique
# ============================================================


class IsUserHeldStateTests(unittest.TestCase):
    """`_is_user_held_state` doit etre True sur PAUSED, SAVED,
    AWAITING_VALIDATION et False sinon.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_jr_state_userheld_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = _make_store(self.state_dir)
        self.runner = JobRunner(self.store)

    def test_user_held_states(self) -> None:
        self.assertTrue(self.runner._is_user_held_state("PAUSED"))
        self.assertTrue(self.runner._is_user_held_state("SAVED"))
        self.assertTrue(self.runner._is_user_held_state("AWAITING_VALIDATION"))

    def test_non_user_held_states(self) -> None:
        self.assertFalse(self.runner._is_user_held_state("PENDING"))
        self.assertFalse(self.runner._is_user_held_state("RUNNING"))
        self.assertFalse(self.runner._is_user_held_state("DONE"))
        self.assertFalse(self.runner._is_user_held_state("FAILED"))
        self.assertFalse(self.runner._is_user_held_state("CANCELLED"))

    def test_falsy_inputs(self) -> None:
        self.assertFalse(self.runner._is_user_held_state(None))
        self.assertFalse(self.runner._is_user_held_state(""))


# ============================================================
# request_cancel return False sur run inconnu
# ============================================================


class RequestCancelEdgeCasesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_jr_state_edge_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = _make_store(self.state_dir)
        self.runner = JobRunner(self.store)

    def test_cancel_unknown_returns_false(self) -> None:
        self.assertFalse(self.runner.request_cancel("does_not_exist"))

    def test_pause_unknown_returns_false(self) -> None:
        self.assertFalse(self.runner.request_pause("does_not_exist"))

    def test_resume_unknown_returns_false(self) -> None:
        self.assertFalse(self.runner.request_resume("does_not_exist"))


if __name__ == "__main__":
    unittest.main()
