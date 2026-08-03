"""Unicite du run_id : generateur, validateurs, base et dossier de run.

Le defaut d'origine : `time.strftime("%Y%m%d_%H%M%S") + f"_{ms % 1000:03d}"`
sans aucune garde d'unicite -> 1997 collisions mesurees sur 2000 appels en
rafale. Ce fichier verrouille les quatre etages du correctif :

1. le GENERATEUR (rafale, concurrence, largeur fixe, ordre lexicographique) ;
2. les deux VALIDATEURS (`infra.run_id.RUN_ID_PATTERN` et
   `ui.api.cinesort_api.RUN_ID_RE`) et la compat ascendante ;
3. la BASE (`insert_run_pending` echoue fort et typé, sans jamais absorber) ;
4. le DOSSIER (`runs/tri_films_<run_id>` reserve atomiquement, jamais reutilise
   en silence quand il est peuple).
"""

from __future__ import annotations

import itertools
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import cinesort.infra.state as state
from cinesort.app.job_runner import JobRunner
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from cinesort.infra.db.repositories.run import RunIdConflictError
from cinesort.infra.run_id import RUN_ID_PATTERN, generate_run_id, normalize_or_generate_run_id
from cinesort.ui.api import runtime_support
from cinesort.ui.api.cinesort_api import RUN_ID_RE, CineSortApi
from tests._helpers import wait_run_done

# Valeurs sentinelles reservees : le front envoie `run_id: "latest"`, le backend
# traite "", "latest" et "dernier" comme « dernier run ». Le generateur ne doit
# jamais pouvoir les produire, et le validateur doit continuer a les accepter.
_RESERVED_SENTINELS = ("", "latest", "dernier")


class RunIdGeneratorTests(unittest.TestCase):
    def test_burst_generation_has_zero_duplicate(self) -> None:
        """Scenario exact de la mesure : 2000 appels en rafale, zero doublon."""
        ids = [generate_run_id() for _ in range(2000)]
        duplicates = len(ids) - len(set(ids))
        self.assertEqual(duplicates, 0, f"{duplicates} collisions sur {len(ids)} generations en rafale")

    def test_concurrent_generation_has_zero_duplicate(self) -> None:
        """Meme exigence sous 8 threads : le compteur doit etre sous verrou."""
        produced: List[List[str]] = []
        produced_lock = threading.Lock()
        barrier = threading.Barrier(8)

        def worker() -> None:
            barrier.wait()
            local = [generate_run_id() for _ in range(400)]
            with produced_lock:
                produced.append(local)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        flat = [rid for chunk in produced for rid in chunk]
        self.assertEqual(len(flat), 3200)
        self.assertEqual(len(set(flat)), len(flat))

    def test_ids_are_fixed_width_and_lexicographically_ordered(self) -> None:
        """Garde-fou `clean_old_runs` : il trie les dossiers par NOM et rmtree
        au-dela de keep_last. Une largeur variable ferait supprimer les mauvais
        runs (perte de donnees)."""
        ids = [generate_run_id() for _ in range(500)]
        self.assertEqual(len({len(rid) for rid in ids}), 1, "largeur du run_id non constante")
        self.assertEqual(ids, sorted(ids), "ordre lexicographique != ordre de generation")

    def test_generated_id_satisfies_both_validators(self) -> None:
        """Les deux motifs du depot doivent accepter ce que le producteur emet."""
        for _ in range(50):
            run_id = generate_run_id()
            self.assertTrue(RUN_ID_PATTERN.match(run_id), f"RUN_ID_PATTERN rejette {run_id}")
            self.assertTrue(RUN_ID_RE.fullmatch(run_id), f"RUN_ID_RE rejette {run_id}")

    def test_generated_id_survives_normalization_unchanged(self) -> None:
        """Sinon le suffixe d'unicite serait detruit par
        `normalize_or_generate_run_id` : correctif no-op silencieux."""
        for _ in range(50):
            run_id = generate_run_id()
            self.assertEqual(normalize_or_generate_run_id(run_id), run_id)

    def test_generated_id_is_ntfs_safe_and_within_api_length_budget(self) -> None:
        run_id = generate_run_id()
        self.assertFalse(set(run_id) & set('<>:"/\\|?*'), "caractere interdit par NTFS")
        self.assertLessEqual(len(run_id), 80, "au-dela de 80 tous les endpoints decores repondent 'run_id invalide'")

    def test_generator_never_emits_reserved_sentinels(self) -> None:
        produced = {generate_run_id() for _ in range(200)}
        for sentinel in _RESERVED_SENTINELS:
            self.assertNotIn(sentinel, produced)

    def test_reserved_sentinels_still_accepted_by_api_validator(self) -> None:
        """Un resserrement du validateur casserait dashboard + banniere de scan."""
        for sentinel in ("latest", "dernier"):
            self.assertTrue(RUN_ID_RE.fullmatch(sentinel), f"sentinelle {sentinel} rejetee")


class RunIdCompatibilityTests(unittest.TestCase):
    def test_legacy_three_group_run_id_is_preserved(self) -> None:
        """Compat ascendante : un run_id deja sur le disque de l'utilisateur
        doit traverser la normalisation INCHANGE, sinon une reprise repart sous
        une nouvelle identite et orpheline sa ligne runs + son dossier."""
        for legacy in ("20260218_150500_321", "20260612_234833_444"):
            self.assertTrue(RUN_ID_PATTERN.match(legacy))
            self.assertEqual(normalize_or_generate_run_id(legacy), legacy)

    def test_invalid_input_falls_back_to_a_canonical_unique_id(self) -> None:
        """Le repli n'est plus un uuid4 : il doit etre valide pour les DEUX
        motifs (sinon il est re-detruit au passage suivant) et rester triable."""
        first = normalize_or_generate_run_id("invalid")
        second = normalize_or_generate_run_id("invalid")
        self.assertNotEqual(first, second)
        for fallback in (first, second):
            self.assertTrue(RUN_ID_PATTERN.match(fallback), f"repli {fallback} rejete par RUN_ID_PATTERN")
            self.assertTrue(RUN_ID_RE.fullmatch(fallback), f"repli {fallback} rejete par RUN_ID_RE")
            self.assertEqual(normalize_or_generate_run_id(fallback), fallback)

    def test_none_input_falls_back_to_a_fresh_id_each_time(self) -> None:
        ids = {normalize_or_generate_run_id(None) for _ in range(200)}
        self.assertEqual(len(ids), 200)


class RunIdSingleProducerTests(unittest.TestCase):
    def test_ui_layer_reuses_the_infra_producer(self) -> None:
        """Deux copies divergent : il ne doit exister qu'UN producteur."""
        self.assertIs(runtime_support.generate_run_id, generate_run_id)

    def test_job_runner_has_no_private_generator_left(self) -> None:
        self.assertFalse(hasattr(JobRunner, "_generate_current_format_run_id"))


class InsertRunPendingConflictTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_runid_db_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir), busy_timeout_ms=8000)
        self.store.initialize()

    def _insert(self, run_id: str, root: str) -> None:
        self.store.run.insert_run_pending(
            run_id=run_id,
            root=root,
            state_dir=str(self.state_dir),
            config={},
        )

    def test_duplicate_insert_raises_typed_error_naming_the_run_id(self) -> None:
        run_id = generate_run_id()
        self._insert(run_id, r"D:\Films")

        with self.assertRaises(RunIdConflictError) as ctx:
            self._insert(run_id, r"E:\Autre")

        self.assertIn(run_id, str(ctx.exception))
        self.assertEqual(getattr(ctx.exception, "run_id", None), run_id)

    def test_typed_error_stays_catchable_as_sqlite_integrity_error(self) -> None:
        """Backward compat des appelants : start_job filtre sqlite3.IntegrityError,
        demo_support filtre sqlite3.Error."""
        self.assertTrue(issubclass(RunIdConflictError, sqlite3.IntegrityError))
        self.assertTrue(issubclass(RunIdConflictError, sqlite3.Error))

    def test_duplicate_insert_never_becomes_a_silent_success(self) -> None:
        """Ni OR IGNORE (run sans ligne) ni OR REPLACE (ecrasement + CASCADE)."""
        run_id = generate_run_id()
        self._insert(run_id, r"D:\Films")

        with self.assertRaises(sqlite3.IntegrityError):
            self._insert(run_id, r"E:\Ecrase")

        rows = [r for r in self.store.run.list_runs(limit=50) if r.get("run_id") == run_id]
        self.assertEqual(len(rows), 1, "la table runs ne doit contenir qu'une ligne pour ce run_id")
        row = self.store.run.get_run(run_id)
        assert row is not None
        self.assertEqual(str(row.get("root")), r"D:\Films", "le run d'origine a ete ecrase")


class RunDirectoryReservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_runid_dir_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def test_exclusive_creation_refuses_an_existing_directory(self) -> None:
        run_id = generate_run_id()
        first = state.new_run(self.state_dir, run_id, exclusive=True)
        self.assertTrue(first.run_dir.is_dir())

        with self.assertRaises(state.RunDirectoryConflictError):
            state.new_run(self.state_dir, run_id, exclusive=True)

    def test_run_directory_conflict_is_an_oserror(self) -> None:
        """Les boundaries existantes filtrent OSError : la nouvelle erreur doit
        y rester attrapable (demo_support, start_plan)."""
        self.assertTrue(issubclass(state.RunDirectoryConflictError, FileExistsError))
        self.assertTrue(issubclass(state.RunDirectoryConflictError, OSError))

    def test_populated_directory_is_never_reused_silently(self) -> None:
        run_id = generate_run_id()
        paths = state.new_run(self.state_dir, run_id)
        paths.plan_jsonl.write_text('{"row_id": "row-1"}\n', encoding="utf-8")

        with self.assertRaises(state.RunDirectoryConflictError):
            state.new_run(self.state_dir, run_id)

        self.assertEqual(paths.plan_jsonl.read_text(encoding="utf-8"), '{"row_id": "row-1"}\n')

    def test_run_paths_for_exclusive_refuses_an_existing_directory(self) -> None:
        run_id = generate_run_id()
        runtime_support.run_paths_for(self.state_dir, run_id, ensure_exists=True, exclusive=True)
        with self.assertRaises(state.RunDirectoryConflictError):
            runtime_support.run_paths_for(self.state_dir, run_id, ensure_exists=True, exclusive=True)

    def test_run_paths_for_non_exclusive_still_reopens_an_existing_run(self) -> None:
        """Compat : apply / diagnostics / historique rouvrent un run EXISTANT."""
        run_id = generate_run_id()
        paths = runtime_support.run_paths_for(self.state_dir, run_id, ensure_exists=True)
        paths.plan_jsonl.write_text("x\n", encoding="utf-8")
        again = runtime_support.run_paths_for(self.state_dir, run_id, ensure_exists=True)
        self.assertEqual(again.run_dir, paths.run_dir)
        self.assertEqual(again.plan_jsonl.read_text(encoding="utf-8"), "x\n")


class _FakeRunStore:
    """Store minimal : seule `run.get_run` est consultee par la reservation."""

    def __init__(self, known: Dict[str, Any]) -> None:
        self.run = self
        self._known = known

    def get_run(self, run_id: str) -> Any:
        return self._known.get(run_id)


class ReserveUniqueRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_reserve_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = mock.MagicMock()
        self.api._runs = {}
        self.api._runs_lock = threading.RLock()

    def test_reservation_creates_the_directory_atomically(self) -> None:
        store = _FakeRunStore({})
        run_id, run_paths = runtime_support.reserve_unique_run(self.api, store, self.state_dir)
        self.assertTrue(run_paths.run_dir.is_dir())
        self.assertEqual(run_paths.run_dir.name, f"tri_films_{run_id}")
        self.assertTrue(RUN_ID_PATTERN.match(run_id))

    def test_reservation_skips_a_run_id_whose_directory_already_exists(self) -> None:
        """C'est le point que la garde en base ne couvrait PAS : le dossier est
        cree avant l'insert, donc un id libre en base pouvait quand meme
        atterrir dans un dossier deja peuple."""
        taken = generate_run_id()
        free = generate_run_id()
        taken_dir = self.state_dir / "runs" / f"tri_films_{taken}"
        taken_dir.mkdir(parents=True)
        (taken_dir / "plan.jsonl").write_text("ancien plan\n", encoding="utf-8")

        store = _FakeRunStore({})
        with mock.patch.object(runtime_support, "generate_run_id", side_effect=[taken, free]):
            run_id, run_paths = runtime_support.reserve_unique_run(self.api, store, self.state_dir)

        self.assertEqual(run_id, free)
        self.assertEqual(run_paths.run_dir.name, f"tri_films_{free}")
        self.assertEqual((taken_dir / "plan.jsonl").read_text(encoding="utf-8"), "ancien plan\n")

    def test_reservation_skips_a_run_id_already_present_in_db(self) -> None:
        taken = generate_run_id()
        free = generate_run_id()
        store = _FakeRunStore({taken: {"run_id": taken}})
        with mock.patch.object(runtime_support, "generate_run_id", side_effect=[taken, free]):
            run_id, _paths = runtime_support.reserve_unique_run(self.api, store, self.state_dir)
        self.assertEqual(run_id, free)

    def test_unique_id_helper_fallback_stays_a_valid_run_id(self) -> None:
        """Le repli historique `<id>-<hex8>` etait detruit par la normalisation."""
        busy = _FakeRunStore({})
        busy.get_run = lambda _run_id: {"run_id": _run_id}  # type: ignore[assignment]
        fallback = runtime_support.generate_unique_run_id(self.api, busy)
        self.assertTrue(RUN_ID_PATTERN.match(fallback), f"repli {fallback} detruit par la normalisation")
        self.assertEqual(normalize_or_generate_run_id(fallback), fallback)


class StartJobHintCollisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_startjob_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir), busy_timeout_ms=8000)
        self.store.initialize()
        self.runner = JobRunner(self.store)

    def test_colliding_hint_is_refused_before_any_thread_starts(self) -> None:
        """Sans ce refus, start_job substituait l'id ET demarrait quand meme le
        thread : start_plan retournait une erreur alors qu'un scan fantome
        ecrivait dans le dossier de l'ancien id (run non pilotable)."""
        taken = generate_run_id()
        self.store.run.insert_run_pending(
            run_id=taken,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={},
        )
        self.store.run.mark_run_done(taken, stats={}, ended_ts=0.0)

        entered = threading.Event()

        def job_fn(_should_cancel: Any) -> None:
            entered.set()

        with self.assertRaises(RuntimeError) as ctx:
            self.runner.start_job(
                job_fn=job_fn,
                root=r"D:\Films",
                state_dir=str(self.state_dir),
                config={},
                run_id_hint=taken,
            )

        self.assertIn(taken, str(ctx.exception))
        self.assertFalse(entered.wait(timeout=0.5), "un worker fantome a demarre malgre le refus")
        row = self.store.run.get_run(taken)
        assert row is not None
        self.assertEqual(str(row.get("status")), "DONE", "le run existant a ete ecrase")

    def test_free_hint_is_returned_unchanged(self) -> None:
        """Invariant de conception : l'id rendu ne doit jamais diverger du hint,
        sinon le dossier et le RunState deja crees pointent ailleurs."""
        hint = generate_run_id()
        done = threading.Event()

        def job_fn(_should_cancel: Any) -> None:
            done.set()

        started = self.runner.start_job(
            job_fn=job_fn,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={},
            run_id_hint=hint,
        )
        self.assertEqual(started, hint)
        self.assertTrue(done.wait(timeout=5.0))

        # Windows : joindre le worker AVANT le cleanup du tmpdir, sinon la
        # connexion SQLite encore ouverte fait echouer le rmtree (WinError 32).
        worker = self.runner._runs[started].thread
        assert worker is not None
        worker.join(timeout=10.0)
        self.assertFalse(worker.is_alive())


class StartPlanReservationTests(unittest.TestCase):
    """Cablage bout-en-bout : start_plan doit consommer la reservation.

    Sans ce test, la reservation pourrait etre correcte en isolation tout en
    n'etant pas branchee sur le seul chemin qui cree reellement un dossier de
    run.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_startplan_")
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.root = base / "films"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir = base / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def test_start_plan_never_reuses_a_populated_run_directory(self) -> None:
        taken = generate_run_id()
        free = generate_run_id()
        taken_dir = self.state_dir / "runs" / f"tri_films_{taken}"
        taken_dir.mkdir(parents=True)
        (taken_dir / "plan.jsonl").write_text("plan du run precedent\n", encoding="utf-8")

        real_generate = generate_run_id
        candidates = itertools.chain([taken, free], iter(real_generate, None))

        api = CineSortApi()
        with mock.patch.object(runtime_support, "generate_run_id", side_effect=candidates):
            start = api.run.start_plan(
                {
                    "root": str(self.root),
                    "state_dir": str(self.state_dir),
                    "tmdb_enabled": False,
                }
            )

        self.assertTrue(start.get("ok"), start)
        self.assertEqual(start.get("run_id"), free, "start_plan a reutilise un dossier de run deja peuple")
        self.assertEqual(Path(str(start.get("run_dir"))).name, f"tri_films_{free}")
        self.assertEqual(
            (taken_dir / "plan.jsonl").read_text(encoding="utf-8"),
            "plan du run precedent\n",
            "le plan.jsonl du run precedent a ete ecrase",
        )

        # Attendre la fin du worker : sinon le rmtree du tmpdir echoue sous
        # Windows (connexion SQLite encore ouverte).
        wait_run_done(api, free, timeout_s=30.0)


if __name__ == "__main__":
    unittest.main()
