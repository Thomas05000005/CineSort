"""Unicite du run_id : generateur, validateurs, base et dossier de run.

Le defaut d'origine : `time.strftime("%Y%m%d_%H%M%S") + f"_{ms % 1000:03d}"`
sans aucune garde d'unicite -> 1997 collisions mesurees sur 2000 appels en
rafale. Ce fichier verrouille les quatre etages du correctif :

1. le GENERATEUR (rafale, concurrence, largeur fixe, ordre lexicographique,
   et les trois gardes internes de `_MonotonicSlots` a HORLOGE INJECTEE) ;
2. les deux VALIDATEURS (`infra.run_id.RUN_ID_PATTERN` et
   `ui.api.cinesort_api.RUN_ID_RE`) et la compat ascendante ;
3. la BASE (`insert_run_pending` echoue fort et typé, sans jamais absorber) ;
4. le DOSSIER (`runs/tri_films_<run_id>` reserve atomiquement, jamais reutilise
   en silence quand il est peuple) ;
5. l'EXHAUSTIVITE des producteurs (le mode demo etait le cinquieme, hors format,
   et faisait purger de vrais runs par `clean_old_runs`) ;
6. les CHIFFRES du schema cites par les docstrings porteuses d'arbitrage.
"""

from __future__ import annotations

import itertools
import shutil
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
from cinesort.infra.run_id import (
    _COUNTER_MODULO,
    RUN_ID_PATTERN,
    _format_run_id,
    _MonotonicSlots,
    generate_run_id,
    normalize_or_generate_run_id,
)
from cinesort.ui.api import demo_support, runtime_support
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
        """Meme exigence sous 8 threads reels.

        Ce que ce test prouve exactement : 3200 identifiants produits en
        parallele restent tous distincts. Ce qu'il NE prouve PAS : la presence
        du verrou. Mesure — remplacer `with self._lock:` par `if True:` laisse
        ce test vert 5 fois sur 5, et meme a `sys.setswitchinterval(1e-9)` avec
        32000 identifiants ; sous CPython le GIL masque la fenetre. C'est
        `test_slot_allocation_is_mutually_exclusive` qui verrouille le verrou.
        """
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


class MonotonicSlotsClockTests(unittest.TestCase):
    """Les trois gardes internes de `_MonotonicSlots`, une par test.

    La PR vend le recul d'horloge et la saturation du compteur comme « une
    GARANTIE, pas une probabilite ». Mesure faite avant ce fichier : les
    NEUTRALISER TOUTES LES DEUX laissait la batterie entierement verte, alors
    que chacune produit de vrais doublons. Une rafale reelle ne peut ni faire
    reculer l'horloge du systeme ni garantir 1001 appels dans la meme
    milliseconde : seule une horloge INJECTEE rend ces gardes observables.

    Chaque test isole UNE garde : neutraliser l'une doit faire rougir son test
    dedie sans dependre de l'autre.
    """

    # Base choisie avec `% 1000 == 0` : la milliseconde virtuelle de la
    # saturation (index 1000) se lit alors directement dans le champ <mmm>.
    _BASE_MS = 1_800_000_000_000

    def test_clock_rewind_never_re_emits_an_identifier(self) -> None:
        """Garde 1 — recul d'horloge (NTP, changement d'heure).

        Sequence 999 / 1000 / 999 : le 3e appel voit une horloge REVENUE en
        arriere. Le code doit rester sur la derniere milliseconde emise et
        incrementer. Avec `!=` au lieu de `>`, le 3e identifiant est le CLONE
        du premier (mesure : 1 doublon).
        """
        ticks = iter([self._BASE_MS + 999, self._BASE_MS + 1000, self._BASE_MS + 999])
        slots = _MonotonicSlots(lambda: next(ticks))

        pairs = [slots.next_slot() for _ in range(3)]
        ids = [_format_run_id(epoch_ms, counter) for epoch_ms, counter in pairs]

        self.assertEqual(len(set(ids)), 3, f"recul d'horloge : identifiant re-emis, {ids}")
        self.assertEqual(ids, sorted(ids), f"recul d'horloge : ordre lexicographique rompu, {ids}")
        self.assertEqual(pairs, sorted(pairs), f"couples (epoch_ms, compteur) non strictement croissants : {pairs}")

    def test_counter_saturation_advances_one_virtual_millisecond(self) -> None:
        """Garde 2 — saturation du compteur a horloge FIGEE.

        `_COUNTER_MODULO` identifiants tiennent dans une milliseconde ; le
        suivant doit basculer sur une milliseconde VIRTUELLE. Sans ce
        rattrapage, le compteur repasse a 000 via le modulo du formatage et
        l'identifiant n^1001 est le clone du premier (mesure : ids[0] ==
        ids[1000]).
        """
        slots = _MonotonicSlots(lambda: self._BASE_MS)

        pairs = [slots.next_slot() for _ in range(_COUNTER_MODULO + 1)]
        ids = [_format_run_id(epoch_ms, counter) for epoch_ms, counter in pairs]

        duplicates = len(ids) - len(set(ids))
        self.assertEqual(duplicates, 0, f"{duplicates} doublon(s) a horloge figee sur {len(ids)} identifiants")
        self.assertEqual(ids, sorted(ids), "saturation : ordre lexicographique rompu")
        self.assertEqual(pairs[0], (self._BASE_MS, 0))
        self.assertEqual(pairs[_COUNTER_MODULO - 1], (self._BASE_MS, _COUNTER_MODULO - 1))
        self.assertEqual(
            pairs[_COUNTER_MODULO],
            (self._BASE_MS + 1, 0),
            "la saturation doit avancer d'une milliseconde VIRTUELLE, pas re-boucler",
        )

    def test_slot_allocation_is_mutually_exclusive(self) -> None:
        """Garde 3 — le verrou, prouve sans dependre d'une course chanceuse.

        L'horloge injectee bloque sur une `Barrier(2)` PENDANT qu'elle est
        appelee, c'est-a-dire au coeur de la section critique. Si la section
        est bien exclusive, le second thread ne peut pas atteindre la barriere
        et celle-ci CASSE sur timeout — c'est l'observation, deterministe.
        Sans verrou, les deux threads y arrivent ensemble, la barriere passe et
        les deux lisent le meme couple : `broken` reste False et les
        identifiants sont identiques.
        """
        barrier = threading.Barrier(2, timeout=0.5)
        frozen_ms = self._BASE_MS

        def clock() -> int:
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return frozen_ms

        slots = _MonotonicSlots(clock)
        produced: List[Any] = []
        produced_lock = threading.Lock()

        def worker() -> None:
            pair = slots.next_slot()
            with produced_lock:
                produced.append(pair)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
        for t in threads:
            self.assertFalse(t.is_alive(), "un thread est reste bloque dans next_slot")

        self.assertTrue(
            barrier.broken,
            "les deux threads ont ete simultanement DANS la section critique : le verrou ne protege plus rien",
        )
        self.assertEqual(len(produced), 2)
        self.assertEqual(len(set(produced)), 2, f"deux threads ont recu le meme couple : {produced}")


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


class RunsSchemaDocumentationTests(unittest.TestCase):
    """Les chiffres de schema cites par les docstrings PORTEUSES d'arbitrage.

    `RunIdConflictError` justifie le refus de `INSERT OR REPLACE` par les FK
    `ON DELETE CASCADE` qui pointent sur `runs(run_id)`. Sa docstring annoncait
    SIX ; la mesure (`PRAGMA foreign_key_list` sur une base reellement
    initialisee) en donne TROIS. Le « six » venait du compte des tables PORTANT
    une colonne `run_id` — ce n'est pas la meme chose, et trois d'entre elles
    n'ont aucune cascade.

    Un chiffre faux sur l'argument central n'est pas un defaut de redaction :
    il sera cite plus tard comme s'il avait ete verifie. Ce test le MESURE et
    exige que la docstring dise ce que le schema fait — si une 4e cascade est
    ajoutee un jour, il rougit et force la mise a jour.
    """

    _NUMBER_WORDS = {1: "une", 2: "deux", 3: "trois", 4: "quatre", 5: "cinq", 6: "six", 7: "sept", 8: "huit"}

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_schema_")
        self.addCleanup(self._tmp.cleanup)
        state_dir = Path(self._tmp.name) / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(db_path_for_state_dir(state_dir), busy_timeout_ms=8000)
        self.store.initialize()

    def _table_names(self, conn: sqlite3.Connection) -> List[str]:
        return [str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]

    def _cascading_tables(self) -> Dict[str, str]:
        """{table: colonne} des FK ON DELETE CASCADE qui pointent sur `runs`."""
        found: Dict[str, str] = {}
        with self.store._managed_conn() as conn:
            for table in self._table_names(conn):
                for row in conn.execute(f"PRAGMA foreign_key_list('{table}')"):
                    if str(row["table"]) == "runs" and str(row["on_delete"]).upper() == "CASCADE":
                        found[table] = str(row["from"])
        return found

    def test_cascade_targets_are_exactly_the_three_documented_tables(self) -> None:
        self.assertEqual(
            self._cascading_tables(),
            {"errors": "run_id", "quality_reports": "run_id", "anomalies": "run_id"},
            "l'arbitrage 'pas de OR REPLACE' repose sur ce jeu exact de cascades",
        )

    def test_conflict_docstring_states_the_measured_cascade_count(self) -> None:
        cascading = self._cascading_tables()
        doc = RunIdConflictError.__doc__ or ""
        word = self._NUMBER_WORDS.get(len(cascading), str(len(cascading)))
        self.assertIn(
            f"les {word} FK",
            doc,
            f"{len(cascading)} FK cascade mesurees, la docstring en annonce un autre nombre",
        )
        for table in sorted(cascading):
            self.assertIn(
                f"`{table}`",
                doc,
                f"la table {table} cascade reellement mais n'est pas nommee dans la docstring",
            )

    def test_run_id_is_a_primary_key_component_of_three_other_tables(self) -> None:
        """L'autre chiffre du meme lot : `infra/run_id.py` annoncait « six
        autres tables » en composante de cle. La mesure en donne TROIS ; les
        autres portent `run_id` comme simple colonne de rattachement."""
        in_primary_key: List[str] = []
        carrying: List[str] = []
        with self.store._managed_conn() as conn:
            for table in self._table_names(conn):
                columns = list(conn.execute(f"PRAGMA table_info('{table}')"))
                names = [str(c["name"]) for c in columns]
                if "run_id" not in names:
                    continue
                carrying.append(table)
                if any(str(c["name"]) == "run_id" and int(c["pk"]) > 0 for c in columns):
                    in_primary_key.append(table)

        self.assertEqual(
            sorted(t for t in in_primary_key if t != "runs"),
            ["duplicate_decisions", "perceptual_reports", "quality_reports"],
            "le jeu des tables dont run_id est composante de PRIMARY KEY a change",
        )
        others = sorted(t for t in carrying if t != "runs")
        self.assertEqual(
            len(others),
            11,
            f"11 tables autres que `runs` portent run_id (3 en PK + 8 en rattachement), mesure : {others}",
        )


class DemoRunIdProducerTests(unittest.TestCase):
    """Le CINQUIEME producteur de run_id : le mode demo.

    Il rendait `demo_<epoch>_<hex6>`, hors format canonique, et le chemin est
    joignable depuis l'interface (`web/dashboard/views/demo-wizard.js` ->
    `runtime/start_demo_mode`) : chaque clic emettait un id neuf hors format.
    Consequence mesuree : `tri_films_demo_…` trie AVANT tout `tri_films_2026…`
    en ordre decroissant, donc `clean_old_runs` classait eternellement les
    dossiers demo « les plus recents » et purgeait de VRAIS runs a leur place.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_demo_runid_")
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = CineSortApi()
        saved = self.api.settings.save_settings(
            {
                "root": str(Path(self._tmp) / "fake_root"),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.assertTrue(saved.get("ok"), saved)

    def _start_demo(self) -> str:
        result = self.api.runtime.start_demo_mode()
        self.assertTrue(result.get("ok"), result)
        return str(result["run_id"])

    def test_demo_run_id_comes_from_the_single_canonical_producer(self) -> None:
        run_id = self._start_demo()
        self.assertTrue(RUN_ID_PATTERN.match(run_id), f"run_id demo hors format : {run_id!r}")
        self.assertTrue(RUN_ID_RE.fullmatch(run_id), f"run_id demo rejete par RUN_ID_RE : {run_id!r}")
        self.assertEqual(normalize_or_generate_run_id(run_id), run_id)

    def test_demo_run_stays_identified_by_its_config_not_by_a_prefix(self) -> None:
        """Le prefixe `demo_` n'a jamais servi a rien : `_is_demo_run` et
        `stop_demo_mode` resolvent par `config_json['is_demo']`. Le cycle de vie
        complet doit donc rester intact avec un id canonique."""
        run_id = self._start_demo()
        self.assertTrue(self.api.runtime.is_demo_mode_active().get("active"))
        self.assertEqual(demo_support._list_demo_run_ids(self.api._get_or_create_infra(self.state_dir)[0]), [run_id])

        stop = self.api.runtime.stop_demo_mode()
        self.assertTrue(stop.get("ok"), stop)
        self.assertFalse(self.api.runtime.is_demo_mode_active().get("active"))
        self.assertFalse((self.state_dir / "runs" / f"tri_films_{run_id}").exists())

    def test_demo_run_directory_no_longer_purges_a_real_run(self) -> None:
        """Le scenario de perte de donnees, mesure de bout en bout."""
        demo_run_id = self._start_demo()
        runs_dir = self.state_dir / "runs"
        self.assertTrue((runs_dir / f"tri_films_{demo_run_id}").is_dir())

        # 10 runs REELS crees APRES le run demo : avec keep_last=10, c'est le
        # run demo — le plus ancien — qui doit etre purge, et lui seul.
        canonical = []
        for _ in range(10):
            rid = generate_run_id()
            canonical.append(rid)
            (runs_dir / f"tri_films_{rid}").mkdir(parents=True)

        state.clean_old_runs(self.state_dir, keep_last=10)
        survivors = {p.name for p in runs_dir.iterdir() if p.is_dir()}

        purged_real = [rid for rid in canonical if f"tri_films_{rid}" not in survivors]
        self.assertEqual(purged_real, [], f"{len(purged_real)} run(s) REEL(S) purge(s) a la place du run demo")
        self.assertNotIn(
            f"tri_films_{demo_run_id}",
            survivors,
            "le dossier demo, le plus ancien, a survecu a la retention : il trie encore hors chronologie",
        )


if __name__ == "__main__":
    unittest.main()
