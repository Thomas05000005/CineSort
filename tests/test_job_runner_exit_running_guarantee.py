"""Issue #515 — un run doit TOUJOURS quitter RUNNING, meme si le gestionnaire
d'echec echoue lui-meme.

Sequence du defaut, dans `JobRunner._run_worker` :

1. `job_fn` leve  -> on entre dans le `except Exception`.
2. `mark_run_failed` leve a son tour (DB verrouillee par un antivirus Windows,
   disque plein, schema corrompu).
3. L'exception secondaire se propage AVANT `_set_snapshot(FAILED)`.
4. Le `finally` libere le slot actif mais ne corrige NI la ligne `runs`, NI le
   snapshot memoire : `get_status` continue de repondre RUNNING / done=False.

L'utilisateur voit alors un traitement eternellement en cours, sans aucun moyen
de le terminer : `request_cancel` refuse (le run n'est pas terminal, mais plus
aucun thread ne lit le `cancel_event`).

La garantie testee ici est celle du `finally` : quoi qu'il arrive, le run quitte
RUNNING. Elle ne doit PAS ecraser un etat sous controle operateur (PAUSED /
SAVED / AWAITING_VALIDATION), sinon elle casserait la protection C4.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Callable, List, Optional

from cinesort.app.job_runner import JobRunner
from cinesort.domain.run_models import RunStatus
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from tests._helpers import wait_runner_terminal


def _make_store(state_dir: Path) -> SQLiteStore:
    state_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path_for_state_dir(state_dir), busy_timeout_ms=8000)
    store.initialize()
    return store


class _SecondaryFailureCollector:
    """Capture les exceptions qui tuent le thread worker.

    Le filet de securite ne SUPPRIME pas l'exception secondaire (masquer un
    echec DB serait exactement le « succes silencieux » proscrit) : il repare
    l'etat. Ce collecteur sert donc a prouver que le chemin teste est bien
    emprunte — sans lui, un test vert ne dirait pas si `mark_run_failed` a
    reellement leve.
    """

    def __init__(self) -> None:
        self.exceptions: List[BaseException] = []
        self._previous: Optional[Callable[[Any], None]] = None

    def __enter__(self) -> _SecondaryFailureCollector:
        self._previous = threading.excepthook

        def _hook(args: Any) -> None:
            if args.exc_value is not None:
                self.exceptions.append(args.exc_value)

        threading.excepthook = _hook  # type: ignore[assignment]
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self._previous is not None:
            threading.excepthook = self._previous  # type: ignore[assignment]


def _boom(should_cancel: Callable[[], bool]) -> None:
    raise RuntimeError("job explose")


class RunAlwaysLeavesRunningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_jr_515_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = _make_store(self.state_dir)
        self.runner = JobRunner(self.store)
        self.mark_failed_calls = 0

    def _join_worker(self, run_id: str) -> None:
        """Attend la FIN du thread worker.

        Necessaire pour les scenarios ou le run ne devient jamais terminal (run
        laisse en pause) : un simple delai laisserait l'exception secondaire
        remonter APRES la restauration de `threading.excepthook`, d'ou un
        `PytestUnhandledThreadExceptionWarning` non deterministe.
        """
        with self.runner._lock:
            rt = self.runner._runs.get(run_id)
            thread = rt.thread if rt else None
        if thread is not None:
            thread.join(timeout=5.0)
            self.assertFalse(thread.is_alive(), "le thread worker ne s'est pas termine")

    def _start(self) -> str:
        return self.runner.start_job(
            job_fn=_boom,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )

    def _always_raising_mark_failed(self) -> None:
        real = self.store.run.mark_run_failed

        def _raise(run_id: str, **kwargs: Any) -> None:
            self.mark_failed_calls += 1
            raise sqlite3.OperationalError("database is locked")

        self.store.run.mark_run_failed = _raise  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(self.store.run, "mark_run_failed", real))

    def test_snapshot_quitte_running_quand_mark_run_failed_leve_toujours(self) -> None:
        """ROUGE sans le filet : le snapshot reste RUNNING / done=False a vie."""
        self._always_raising_mark_failed()

        with _SecondaryFailureCollector() as collector:
            run_id = self._start()
            reached = wait_runner_terminal(self.runner, run_id, timeout_s=6.0)

        self.assertTrue(reached, "le run n'a jamais quitte l'etat non-terminal")
        snap = self.runner.get_status(run_id)
        assert snap is not None
        self.assertEqual(snap.status, RunStatus.FAILED)
        self.assertFalse(snap.running)
        self.assertTrue(snap.done)
        self.assertTrue(snap.error, "le message d'erreur d'origine doit etre conserve")
        self.assertGreaterEqual(
            self.mark_failed_calls,
            2,
            "le filet doit RETENTER la transition DB, pas seulement corriger la memoire",
        )
        self.assertTrue(
            any(isinstance(exc, sqlite3.OperationalError) for exc in collector.exceptions),
            "l'echec DB doit rester visible (pas de succes silencieux)",
        )

    def test_un_echec_db_transitoire_est_rattrape_en_base(self) -> None:
        """Cas reel (verrou antivirus) : la 2e tentative passe -> la DB dit FAILED."""
        real = self.store.run.mark_run_failed

        def _raise_once(run_id: str, **kwargs: Any) -> None:
            self.mark_failed_calls += 1
            if self.mark_failed_calls == 1:
                raise sqlite3.OperationalError("database is locked")
            real(run_id, **kwargs)

        self.store.run.mark_run_failed = _raise_once  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(self.store.run, "mark_run_failed", real))

        with _SecondaryFailureCollector():
            run_id = self._start()
            reached = wait_runner_terminal(self.runner, run_id, timeout_s=6.0)

        self.assertTrue(reached)
        row = self.store.run.get_run(run_id)
        assert row is not None
        self.assertEqual(row.get("status"), "FAILED", "la ligne runs doit avoir ete reparee")
        self.assertIsNotNone(row.get("ended_ts"))

    def test_un_second_run_reste_lancable_apres_la_panne(self) -> None:
        """Enchainement reel : apres la panne DB, l'app doit rester utilisable.

        Le slot actif est deja rendu par le `finally` historique ; ce qui manque
        sans le filet, c'est l'etat terminal du premier run — il reste affiche
        « en cours » a cote du suivant.
        """
        self._always_raising_mark_failed()

        with _SecondaryFailureCollector():
            first = self._start()
            self.assertTrue(wait_runner_terminal(self.runner, first, timeout_s=6.0))

        done = threading.Event()

        def _ok(should_cancel: Callable[[], bool]) -> None:
            done.set()

        second = self.runner.start_job(
            job_fn=_ok,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        self.assertTrue(wait_runner_terminal(self.runner, second, timeout_s=6.0))
        self.assertTrue(done.is_set())

    def test_insert_error_qui_leve_ne_laisse_pas_le_snapshot_en_running(self) -> None:
        """Variante de #515 : la DB a bien transite, seul le snapshot est en retard.

        `mark_run_failed` passe, puis `insert_error` leve : l'exception secondaire
        se propage avant `_set_snapshot(FAILED)`. Le filet doit s'ALIGNER sur la
        DB (FAILED deja ecrit) et surtout ne pas re-ecrire la ligne `runs`.
        """
        real_mark = self.store.run.mark_run_failed
        marks: List[float] = []

        def _count_mark(run_id: str, **kwargs: Any) -> None:
            marks.append(float(kwargs.get("ended_ts") or 0.0))
            real_mark(run_id, **kwargs)

        def _raise_insert(**kwargs: Any) -> None:
            raise sqlite3.OperationalError("errors table locked")

        real_insert = self.store.run.insert_error
        self.store.run.mark_run_failed = _count_mark  # type: ignore[method-assign]
        self.store.run.insert_error = _raise_insert  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(self.store.run, "insert_error", real_insert))
        self.addCleanup(lambda: setattr(self.store.run, "mark_run_failed", real_mark))

        with _SecondaryFailureCollector():
            run_id = self._start()
            reached = wait_runner_terminal(self.runner, run_id, timeout_s=6.0)

        self.assertTrue(reached, "le snapshot est reste non-terminal alors que la DB disait FAILED")
        snap = self.runner.get_status(run_id)
        assert snap is not None
        self.assertEqual(snap.status, RunStatus.FAILED)
        self.assertEqual(len(marks), 1, "la ligne runs ne doit pas etre re-ecrite : elle etait deja FAILED")

    def test_pause_persistee_en_base_mais_pas_encore_en_memoire(self) -> None:
        """Fenetre de course de `pause_run` : la DB dit PAUSED, le snapshot RUNNING.

        `RunControlSupport.pause_run` persiste la pause AVANT de la signaler au
        runner. Un crash du job dans cet intervalle amene le filet avec un
        snapshot encore RUNNING : c'est la garde qui lit la BASE qui doit alors
        empecher d'ecraser la pause operateur.
        """
        entered = threading.Event()
        release = threading.Event()

        def _job(should_cancel: Callable[[], bool]) -> None:
            entered.set()
            release.wait(timeout=5.0)
            raise RuntimeError("le job explose pendant la fenetre de pause")

        run_id = self.runner.start_job(
            job_fn=_job,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        self.assertTrue(entered.wait(timeout=5.0))
        # Pause persistee, mais volontairement PAS signalee au runner : le
        # snapshot memoire reste sur RUNNING.
        self.assertTrue(self.store.run.mark_run_paused(run_id))
        snap_before = self.runner.get_status(run_id)
        assert snap_before is not None
        self.assertEqual(snap_before.status, RunStatus.RUNNING, "pre-condition du test")
        release.set()
        self._join_worker(run_id)

        row = self.store.run.get_run(run_id)
        assert row is not None
        self.assertEqual(row.get("status"), "PAUSED", "le filet a ecrase une pause persistee en base")

    def test_db_illisible_et_run_en_pause_nest_pas_force_en_failed(self) -> None:
        """La garde memoire vaut seule : si `get_run` leve, le PAUSED tient quand meme."""
        entered = threading.Event()
        release = threading.Event()

        def _job(should_cancel: Callable[[], bool]) -> None:
            entered.set()
            release.wait(timeout=5.0)
            raise RuntimeError("le job explose APRES la mise en pause")

        real_mark = self.store.run.mark_run_failed

        def _raise_mark(run_id: str, **kwargs: Any) -> None:
            self.mark_failed_calls += 1
            raise sqlite3.OperationalError("database is locked")

        self.store.run.mark_run_failed = _raise_mark  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(self.store.run, "mark_run_failed", real_mark))

        with _SecondaryFailureCollector():
            run_id = self.runner.start_job(
                job_fn=_job,
                root=str(self.state_dir),
                state_dir=str(self.state_dir),
                config={},
            )
            self.assertTrue(entered.wait(timeout=5.0))
            self.assertTrue(self.store.run.mark_run_paused(run_id))
            self.runner.request_pause(run_id)

            real_get = self.store.run.get_run

            def _raise_get(_run_id: str) -> Any:
                raise sqlite3.OperationalError("runs table unreadable")

            self.store.run.get_run = _raise_get  # type: ignore[method-assign]
            self.addCleanup(lambda: setattr(self.store.run, "get_run", real_get))
            release.set()
            self._join_worker(run_id)

        snap = self.runner.get_status(run_id)
        assert snap is not None
        self.assertEqual(snap.status, RunStatus.PAUSED, "le filet a ecrase une pause operateur")
        # Une seule tentative : celle du chemin `except` historique, qui ne voit
        # plus la DB et ne peut donc pas savoir que le run est en pause. Le filet
        # n'en ajoute PAS une seconde — c'est le snapshot memoire qui l'arrete.
        self.assertEqual(self.mark_failed_calls, 1)

    def test_un_filet_defaillant_ne_masque_pas_la_cause_dorigine(self) -> None:
        """Le filet vit dans un `finally` : s'il levait, son exception REMPLACERAIT
        celle qui se propage — la panne DB disparaitrait du diagnostic, et la
        suite du `finally` (liberation du slot, ContextVar) serait sautee.
        """
        self._always_raising_mark_failed()

        def _broken_net(*_args: Any, **_kwargs: Any) -> None:
            raise ValueError("filet casse")

        self.runner._ensure_run_left_running = _broken_net  # type: ignore[method-assign]

        with _SecondaryFailureCollector() as collector:
            run_id = self._start()
            self._join_worker(run_id)

        self.assertTrue(collector.exceptions, "aucune exception observee : le test ne prouve rien")
        self.assertTrue(
            any(isinstance(exc, sqlite3.OperationalError) for exc in collector.exceptions),
            f"la cause d'origine a ete masquee par le filet : {collector.exceptions}",
        )
        self.assertFalse(
            any(isinstance(exc, ValueError) for exc in collector.exceptions),
            "l'echec du filet a remplace l'exception en cours de propagation",
        )

    # ---- non-regression : le filet ne doit RIEN ecraser ----

    def test_un_run_reussi_nest_pas_touche(self) -> None:
        real = self.store.run.mark_run_failed

        def _count(run_id: str, **kwargs: Any) -> None:
            self.mark_failed_calls += 1
            real(run_id, **kwargs)

        self.store.run.mark_run_failed = _count  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(self.store.run, "mark_run_failed", real))

        def _ok(should_cancel: Callable[[], bool]) -> dict:
            return {"processed": 1}

        run_id = self.runner.start_job(
            job_fn=_ok,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        self.assertTrue(wait_runner_terminal(self.runner, run_id, timeout_s=6.0))

        snap = self.runner.get_status(run_id)
        assert snap is not None
        self.assertEqual(snap.status, RunStatus.DONE)
        self.assertEqual(self.mark_failed_calls, 0, "aucun run sain ne doit passer par le filet")
        row = self.store.run.get_run(run_id)
        assert row is not None
        self.assertEqual(row.get("status"), "DONE")

    def test_un_run_reussi_survit_a_une_db_devenue_illisible(self) -> None:
        """Le NAS tombe juste apres la fin du scan : DONE ne doit pas virer FAILED.

        Le filet ne consulte la base que s'il a une raison de le faire. Un
        snapshot deja terminal en est la garde : sans elle, une lecture DB
        infructueuse (statut inconnu) suffirait a requalifier un succes en echec.
        """
        real_mark = self.store.run.mark_run_failed

        def _count_mark(run_id: str, **kwargs: Any) -> None:
            self.mark_failed_calls += 1
            real_mark(run_id, **kwargs)

        self.store.run.mark_run_failed = _count_mark  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(self.store.run, "mark_run_failed", real_mark))

        real_get = self.store.run.get_run
        unreadable = threading.Event()

        def _get(run_id: str) -> Any:
            if unreadable.is_set():
                raise sqlite3.OperationalError("runs table unreadable")
            return real_get(run_id)

        self.store.run.get_run = _get  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(self.store.run, "get_run", real_get))

        def _ok(should_cancel: Callable[[], bool]) -> dict:
            unreadable.set()
            return {"processed": 1}

        run_id = self.runner.start_job(
            job_fn=_ok,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={},
        )
        self.assertTrue(wait_runner_terminal(self.runner, run_id, timeout_s=6.0))

        snap = self.runner.get_status(run_id)
        assert snap is not None
        self.assertEqual(snap.status, RunStatus.DONE, "un run reussi a ete requalifie en echec")
        self.assertEqual(self.mark_failed_calls, 0)
        unreadable.clear()
        row = self.store.run.get_run(run_id)
        assert row is not None
        self.assertEqual(row.get("status"), "DONE")

    def test_le_filet_nefface_pas_un_etat_sous_controle_operateur(self) -> None:
        """C4 : un run pose en PAUSED par l'API ne doit pas devenir FAILED."""
        entered = threading.Event()
        release = threading.Event()

        def _job(should_cancel: Callable[[], bool]) -> None:
            entered.set()
            release.wait(timeout=5.0)
            raise RuntimeError("le job explose APRES la mise en pause")

        real = self.store.run.mark_run_failed

        def _raise(run_id: str, **kwargs: Any) -> None:
            self.mark_failed_calls += 1
            raise sqlite3.OperationalError("database is locked")

        self.store.run.mark_run_failed = _raise  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(self.store.run, "mark_run_failed", real))

        with _SecondaryFailureCollector():
            run_id = self.runner.start_job(
                job_fn=_job,
                root=str(self.state_dir),
                state_dir=str(self.state_dir),
                config={},
            )
            self.assertTrue(entered.wait(timeout=5.0))
            self.assertTrue(self.store.run.mark_run_paused(run_id))
            self.runner.request_pause(run_id)
            release.set()
            # Laisser le worker terminer sa sortie (le run ne devient PAS terminal).
            self._join_worker(run_id)

        row = self.store.run.get_run(run_id)
        assert row is not None
        self.assertEqual(row.get("status"), "PAUSED", "le filet a ecrase un etat operateur")
        snap = self.runner.get_status(run_id)
        assert snap is not None
        self.assertEqual(snap.status, RunStatus.PAUSED)
        self.assertEqual(self.mark_failed_calls, 0, "aucune tentative FAILED sur un run PAUSED")


if __name__ == "__main__":
    unittest.main()
