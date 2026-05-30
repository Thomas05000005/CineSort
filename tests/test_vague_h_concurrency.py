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
from unittest import mock
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
        """Fix audit 2026-05-26 (v1.5.6) Vague L : test reecrit pour etre
        non-vacuous via stress test sous mutation multi-etapes.

        Ancien test : observait juste que les Path lus etaient dans
        {initial, path_a, path_b}. Comme set d'attribut Python est atomique
        sous le GIL, ce test passait MEME si _get_state_dir() lisait
        self._state_dir directement sans lock — VACUOUS.

        Nouveau test : on substitue _state_dir par un descriptor cooperatif
        qui simule une mutation multi-etapes (set en deux temps avec un
        time.sleep au milieu). Sous mutation, un read sans lock peut
        observer un etat intermediaire (mutation_in_progress=True) ou un
        Path different de la valeur ENGINEUR finale. Le helper
        _get_state_dir, qui prend le lock, doit observer un etat coherent.

        Mutation proof : si _get_state_dir() lisait directement
        self._state_dir sans prendre _state_dir_lock, le reader observerait
        l'etat partiel et le test casserait sur l'invariant de coherence.
        """
        import time as _time

        api = CineSortApi()
        initial = api._state_dir
        path_a = Path(tempfile.gettempdir()) / "state_dir_a_sig_AAAA"
        path_b = Path(tempfile.gettempdir()) / "state_dir_b_sig_BBBB"

        stop = threading.Event()
        errors: list[Exception] = []
        intermediate_observed = {"flag": False}
        coherence_violations: list[str] = []
        # On garde un marker partage indiquant si une mutation est en cours.
        # Le mutator le set avant de commencer la sequence multi-etapes,
        # le reader verifie qu'il n'observe pas un etat partiel.
        mutation_in_progress = {"flag": False, "target_signature": ""}

        # Stocker l'etat reel a part. La mutation cooperative consiste a
        # mettre _state_dir a un Path temporaire ("transition_XYZ"), dormir
        # un peu, puis le mettre a la valeur finale. Sans lock, un reader
        # observerait le transition_XYZ.
        transition_path = Path(tempfile.gettempdir()) / "TRANSITION_DO_NOT_OBSERVE"

        barrier = threading.Barrier(3)

        def reader() -> None:
            try:
                barrier.wait()
                local_count = 0
                while not stop.is_set() and local_count < 50000:
                    local_count += 1
                    p = api._get_state_dir()
                    # Invariant 1 : le path observe ne doit jamais etre la
                    # valeur de transition (qui n'est jamais l'etat final).
                    if p == transition_path:
                        intermediate_observed["flag"] = True
                        coherence_violations.append(f"observed transition_path: {p}")
                    # Invariant 2 : si une mutation est annoncee comme
                    # terminee (mutation_in_progress=False), le path doit
                    # etre la cible attendue. Si une mutation est en cours,
                    # le path doit etre la PRECEDENTE valeur ou la cible
                    # (jamais la transition).
                    sig = mutation_in_progress["target_signature"]
                    if sig and not mutation_in_progress["flag"]:
                        # Mutation marquee terminee : on doit voir la cible.
                        if sig == "A" and p not in (path_a, initial, path_b):
                            coherence_violations.append(
                                f"after A-set, observed unexpected: {p}"
                            )
                        if sig == "B" and p not in (path_a, initial, path_b):
                            coherence_violations.append(
                                f"after B-set, observed unexpected: {p}"
                            )
            except Exception as exc:
                errors.append(exc)

        def writer() -> None:
            try:
                barrier.wait()
                _time.sleep(0.005)
                for cycle in range(150):
                    # Mutation cooperative en deux temps : transition -> final.
                    # Le LOCK est PRIS pour la sequence COMPLETE : entre
                    # transition et final, le lock est tenu donc aucun reader
                    # ne peut observer la transition (s'il prend lui aussi
                    # le lock dans _get_state_dir).
                    with api._state_dir_lock:
                        mutation_in_progress["flag"] = True
                        mutation_in_progress["target_signature"] = "A"
                        api._state_dir = transition_path
                        # Pause volontaire pendant que le state_dir est en
                        # transition. Un reader sans lock observerait ce path.
                        _time.sleep(0.0005)
                        api._state_dir = path_a
                        mutation_in_progress["flag"] = False
                    _time.sleep(0.0002)
                    with api._state_dir_lock:
                        mutation_in_progress["flag"] = True
                        mutation_in_progress["target_signature"] = "B"
                        api._state_dir = transition_path
                        _time.sleep(0.0005)
                        api._state_dir = path_b
                        mutation_in_progress["flag"] = False
                    _time.sleep(0.0002)
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

        self.assertEqual(errors, [], f"Threads ont leve : {errors}")
        # ASSERT NON-VACUOUS : le reader, qui passe par _get_state_dir
        # (lequel prend _state_dir_lock), ne doit JAMAIS observer la
        # transition_path. Si _get_state_dir() lisait directement
        # self._state_dir sans lock, le reader verrait transition_path au
        # moins une fois pendant les ~150 mutations.
        self.assertFalse(
            intermediate_observed["flag"],
            "_get_state_dir() a observe la transition_path — preuve qu'il "
            "lit self._state_dir SANS prendre _state_dir_lock (race condition).",
        )
        self.assertEqual(
            coherence_violations,
            [],
            f"Violations de coherence observees : {coherence_violations[:5]}",
        )


class GetOrCreateInfraConcurrencyTests(unittest.TestCase):
    """Fix audit 2026-05-26 (v1.5.6) Vague L (conc-4) : get_or_create_infra
    doit garantir UN SEUL appel a SQLiteStore.initialize() par state_dir,
    meme sous appels paralleles avec un cache vide.

    Avant le fix : build du store + initialize() etait HORS du _runs_lock ;
    recheck dans le lock mais initialize() avait deja tourne -> backup
    pre_migration ecrit DEUX fois, integrity_check execute DEUX fois.

    Apres le fix : pattern Event "init in progress" : un seul thread fait
    le build/initialize, les autres attendent puis recuperent le cache.
    """

    def test_parallel_get_or_create_infra_calls_initialize_once(self) -> None:
        import threading as _threading
        import tempfile as _tempfile
        from pathlib import Path as _Path

        from cinesort.ui.api import runtime_support

        # On reset le cache de reconciliation pour partir clean.
        runtime_support.reset_reconciliation_cache_for_tests()

        with _tempfile.TemporaryDirectory() as tmp:
            state_dir = _Path(tmp) / "state"
            state_dir.mkdir(parents=True, exist_ok=True)

            # Compteur partage des appels a initialize().
            init_calls = {"count": 0}
            init_lock = _threading.Lock()
            original_init = None

            api = CineSortApi()

            # Patch SQLiteStore.initialize pour compter et ajouter un sleep
            # qui maximise la fenetre de race.
            from cinesort.infra.db import SQLiteStore

            original_init = SQLiteStore.initialize

            def counting_initialize(self):
                with init_lock:
                    init_calls["count"] += 1
                # Pause volontaire pour maximiser la fenetre de race entre
                # 2 builders paralleles (sans fix, 2 threads passeraient ici).
                import time as _time

                _time.sleep(0.05)
                return original_init(self)

            results = []
            errors = []

            def caller():
                try:
                    res = runtime_support.get_or_create_infra(
                        api, state_dir, env_truthy_fn=lambda _name: False
                    )
                    results.append(res)
                except Exception as exc:
                    errors.append(exc)

            try:
                with mock.patch.object(SQLiteStore, "initialize", counting_initialize):
                    # Lance 5 threads en parallele pour le meme state_dir.
                    threads = [_threading.Thread(target=caller) for _ in range(5)]
                    for th in threads:
                        th.start()
                    for th in threads:
                        th.join()
            finally:
                runtime_support.reset_reconciliation_cache_for_tests()

            self.assertEqual(errors, [], f"Erreurs dans les threads : {errors}")
            self.assertEqual(
                init_calls["count"],
                1,
                f"SQLiteStore.initialize() a ete appele {init_calls['count']} fois "
                f"(attendu : 1). Preuve d'une double initialisation = double backup pre_migration.",
            )
            # Tous les threads doivent recevoir le MEME store (instance).
            stores = [r[0] for r in results]
            store_ids = {id(s) for s in stores}
            self.assertEqual(
                len(store_ids),
                1,
                f"Les threads ont recu des stores differents : {store_ids}",
            )


class MigrationSelfHealingTests(unittest.TestCase):
    """Fix audit 2026-05-26 (v1.5.6) Vague L (mig-2) : self-healing migration 023.

    Avant : migration 026 ne corrigeait que uv<26. Une DB avec uv=26 mais
    tables 023 manquantes (cas observe en prod) restait cassee.

    Apres : (a) migration 027 idempotente re-cree les 3 tables si elles
    manquent quand uv<27, (b) REQUIRED_SCHEMA_TABLES inclut maintenant les
    3 tables 023, et (c) _bootstrap_schema_latest tolere les erreurs
    idempotentes (savepoint+_is_idempotent_error). Sur une DB partielle,
    _ensure_required_schema rejoue le bootstrap qui recree les tables
    manquantes sans crasher sur les ALTER TABLE des migrations precedentes.
    """

    def _make_tempdir(self) -> Path:
        """Tempdir manuel avec cleanup en addCleanup pour gerer le lock SQLite Windows."""
        import shutil as _shutil
        import tempfile as _tempfile

        tmp = _tempfile.mkdtemp(prefix="cinesort_mig2_")

        def _cleanup() -> None:
            # Retries pour le lock SQLite Windows.
            import gc as _gc
            import time as _time

            _gc.collect()
            for _ in range(5):
                try:
                    _shutil.rmtree(tmp, ignore_errors=False)
                    return
                except (OSError, PermissionError):
                    _time.sleep(0.2)
                    _gc.collect()
            _shutil.rmtree(tmp, ignore_errors=True)

        self.addCleanup(_cleanup)
        return Path(tmp)

    def test_db_uv_high_but_023_tables_missing_self_heals(self) -> None:
        """DB avec uv=25 (avant 026) et tables 023 manquantes : initialize
        doit recreer les tables via la migration 026/027 + filet bootstrap.
        """
        import sqlite3 as _sqlite3

        from cinesort.infra.db import SQLiteStore

        tmp = self._make_tempdir()
        db_path = tmp / "db" / "cinesort.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Etape 1 : DB initiale ok (boot normal).
        store = SQLiteStore(db_path)
        v0 = store.initialize()
        self.assertGreaterEqual(v0, 23)

        # Etape 2 : on simule le bug "tables 023 manquantes, uv pourtant=25".
        # On drop les 3 tables et on remet uv=25 (avant 026, pour que la 026
        # se replay et recree les tables).
        conn = _sqlite3.connect(str(db_path))
        try:
            conn.execute("DROP TABLE IF EXISTS ignored_alerts")
            conn.execute("DROP TABLE IF EXISTS film_marked_for_deletion")
            conn.execute("DROP TABLE IF EXISTS film_tmdb_overrides")
            conn.execute("PRAGMA user_version = 25")
            conn.commit()
        finally:
            conn.close()

        # Etape 3 : nouveau initialize() doit detecter et reparer.
        store2 = SQLiteStore(db_path)
        v1 = store2.initialize()
        self.assertGreaterEqual(v1, 26, f"user_version doit etre remonte, got {v1}")

        conn = _sqlite3.connect(str(db_path))
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertIn("ignored_alerts", tables, f"tables : {sorted(tables)}")
        self.assertIn("film_marked_for_deletion", tables)
        self.assertIn("film_tmdb_overrides", tables)

    def test_db_uv_at_latest_but_023_tables_missing_self_heals(self) -> None:
        """Cas pathologique : uv au max (>= 27) mais tables 023 manquantes.
        Le filet _ensure_required_schema doit detecter et rejouer le
        bootstrap (qui IF NOT EXISTS toutes les CREATE TABLE).

        C'est le scenario que le fix audit 2026-05-26 (v1.5.6) Vague L
        (mig-2) cible : detection independante de user_version.
        """
        import sqlite3 as _sqlite3

        from cinesort.infra.db import SQLiteStore

        tmp = self._make_tempdir()
        db_path = tmp / "db" / "cinesort.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Boot initial pour creer un schema complet.
        store = SQLiteStore(db_path)
        v0 = store.initialize()

        # Drop les 3 tables 023 SANS toucher a uv (il reste au max).
        conn = _sqlite3.connect(str(db_path))
        try:
            conn.execute("DROP TABLE IF EXISTS ignored_alerts")
            conn.execute("DROP TABLE IF EXISTS film_marked_for_deletion")
            conn.execute("DROP TABLE IF EXISTS film_tmdb_overrides")
            conn.commit()
            uv_after_drop = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(uv_after_drop, v0, "uv doit rester au max")

        # Nouveau initialize() doit detecter via REQUIRED_SCHEMA_TABLES
        # et rejouer le bootstrap pour recreer les tables.
        store2 = SQLiteStore(db_path)
        v1 = store2.initialize()
        self.assertEqual(v1, v0, "uv doit rester identique post-self-heal")

        conn = _sqlite3.connect(str(db_path))
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertIn(
            "ignored_alerts",
            tables,
            f"Filet self-healing inactif : tables : {sorted(tables)}",
        )
        self.assertIn("film_marked_for_deletion", tables)
        self.assertIn("film_tmdb_overrides", tables)


if __name__ == "__main__":
    unittest.main()
