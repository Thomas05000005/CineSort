"""Non-regression AUDIT ULTRA 2026-07-13 — HIGH-17 / HIGH-18 / HIGH-19.

HIGH-17 + HIGH-19 (meme racine) : `RunState.rows` (snapshot memoire, PREFERE au
fichier par get_plan / run_context_for_apply / dashboard) n'etait jamais
resynchronise apres une reecriture de plan.jsonl (re-match TMDb d'un rescan,
enrichissement tmdb_id) -> l'UI reaffichait l'ancien match, l'apply renommait le
dossier sur disque avec l'ANCIEN titre/annee, et le cache dashboard (signature
calculee sur plan.jsonl) etait empoisonne avec des rows perimees.

HIGH-18 : deux stores d'ecriture pour le marquage suppression (bulk ->
deletion_marks.json purement additif ; modal -> table DB film_marked_for_deletion)
mais UN SEUL store d'annulation (la DB) -> un marquage de masse etait irrevocable
et invisible dans l'UI, et l'apply sortait les dossiers de la bibliotheque.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import cinesort.domain.core as core
from cinesort.infra import state
from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir
from cinesort.ui.api import apply_support, library_actions_support, library_support
from cinesort.ui.api.run_data_support import load_rows_from_plan_jsonl

RUN_ID = "r1"


def _run_paths(state_dir: Path, run_id: str = RUN_ID, *, ensure_exists: bool = True) -> state.RunPaths:
    # Fidele a runtime_support.run_paths_for : le mkdir n'a lieu que si
    # ensure_exists (sinon un chemin de LECTURE recreerait des runs fantomes).
    run_dir = state_dir / "runs" / f"tri_films_{run_id}"
    if ensure_exists:
        run_dir.mkdir(parents=True, exist_ok=True)
    return state.RunPaths(
        run_id=run_id,
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )


def _plan_row(**over: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "row_id": "f1",
        "kind": "single",
        "folder": "",
        "video": "movie.mkv",
        "proposed_title": "ANCIEN TITRE",
        "proposed_year": 2010,
        "proposed_source": "name",
        "confidence": 40,
        "confidence_label": "low",
        "candidates": [],
        "edition": None,
    }
    row.update(over)
    return row


class _StubRunState:
    """RunState minimal : memes attributs que cinesort.ui.api._run_state.RunState."""

    def __init__(self, paths: state.RunPaths, rows: List[core.PlanRow], store: Any) -> None:
        self.paths = paths
        self.rows = rows
        self.lock = threading.Lock()
        self.cfg = SimpleNamespace(root=Path("."))
        self.store = store
        self.done = True
        self.log = lambda _lvl, _msg: None


class _StubApi:
    """Surface API reellement utilisee par _rematch_tmdb_and_update_plan,
    enrich_tmdb_ids_by_title et run_context_for_apply."""

    def __init__(self, state_dir: Path, run_state: Optional[_StubRunState], store: Any) -> None:
        self._state_dir = state_dir
        self._run_state = run_state
        self._store = store
        self.settings = SimpleNamespace(get_settings=lambda: dict(self._settings))
        self._settings = {"state_dir": str(state_dir), "tmdb_api_key": ""}

    # -- settings / paths
    def _internal_settings(self) -> Dict[str, Any]:
        return dict(self._settings)

    def _run_paths_for(self, state_dir: Path, run_id: str, *, ensure_exists: bool) -> state.RunPaths:
        return _run_paths(Path(state_dir), run_id, ensure_exists=ensure_exists)

    # -- runs
    def _get_run(self, run_id: str) -> Optional[_StubRunState]:
        return self._run_state if str(run_id) == RUN_ID else None

    def _find_run_row(self, run_id: str) -> None:
        return None

    def _load_rows_from_plan_jsonl(self, run_paths: state.RunPaths) -> List[core.PlanRow]:
        return load_rows_from_plan_jsonl(run_paths)

    # -- infra
    def _get_or_create_infra(self, state_dir: Path):
        return self._store, None

    def _dashboard_cache_path(self, run_paths: state.RunPaths) -> Path:
        return run_paths.run_dir / "dashboard_cache.json"


# ---------------------------------------------------------------------------
# HIGH-17 / HIGH-19 : resync du snapshot memoire a chaque reecriture du plan
# ---------------------------------------------------------------------------


class PlanRewriteResyncTests(unittest.TestCase):
    def _setup(self, tmp: Path):
        films = tmp / "films" / "Ancien Titre (2010)"
        films.mkdir(parents=True, exist_ok=True)
        (films / "movie.mkv").write_bytes(b"x")

        paths = _run_paths(tmp)
        stale_json = _plan_row(folder=str(films))
        paths.plan_jsonl.write_text(json.dumps(stale_json) + "\n", encoding="utf-8")

        stale_rows = load_rows_from_plan_jsonl(paths)
        store = SimpleNamespace(field_locks=None)
        run_state = _StubRunState(paths, stale_rows, store)
        api = _StubApi(tmp, run_state, store)

        # Cache dashboard "chaud" : sa signature est calculee sur plan.jsonl, donc
        # il doit disparaitre des que le plan est reecrit (sinon empoisonnement).
        (paths.run_dir / "dashboard_cache.json").write_text("{}", encoding="utf-8")
        return api, run_state, paths, films

    def test_rematch_tmdb_resyncs_memory_and_purges_dashboard_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, run_state, paths, films = self._setup(tmp)

            fresh = core.PlanRow(
                row_id="ignore-moi",  # re-estampille par _rematch avec le vrai row_id
                kind="single",
                folder=str(films),
                video="movie.mkv",
                proposed_title="NOUVEAU TITRE",
                proposed_year=2011,
                proposed_source="tmdb",
                confidence=95,
                confidence_label="high",
                candidates=[],
                edition="Director's Cut",
            )

            with patch("cinesort.app.plan_support.replan_single_row", return_value=fresh):
                out = library_actions_support._rematch_tmdb_and_update_plan(api, RUN_ID, "f1")

            self.assertIsNotNone(out)
            # 1. plan.jsonl (disque) a bien le nouveau match
            on_disk = json.loads(paths.plan_jsonl.read_text(encoding="utf-8").strip())
            self.assertEqual(on_disk["proposed_title"], "NOUVEAU TITRE")

            # 2. snapshot memoire resynchronise (avant le fix : "ANCIEN TITRE")
            self.assertEqual(run_state.rows[0].proposed_title, "NOUVEAU TITRE")
            self.assertEqual(run_state.rows[0].proposed_year, 2011)
            self.assertEqual(run_state.rows[0].edition, "Director's Cut")

            # 3. l'APPLY (qui prefere la memoire au fichier) renomme avec le BON titre
            ctx = apply_support.run_context_for_apply(api, RUN_ID)
            self.assertIsNotNone(ctx)
            rows_for_apply = ctx[2]
            self.assertEqual(rows_for_apply[0].proposed_title, "NOUVEAU TITRE")
            self.assertEqual(rows_for_apply[0].proposed_year, 2011)

            # 4. cache dashboard purge (sa signature suit plan.jsonl -> sinon fige)
            self.assertFalse((paths.run_dir / "dashboard_cache.json").exists())

    def test_enrich_tmdb_ids_resyncs_memory_and_purges_dashboard_cache(self) -> None:
        from cinesort.ui.api import tmdb_support

        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, run_state, paths, films = self._setup(tmp)

            # Snapshot memoire perime (l'app tourne depuis le scan).
            run_state.rows[0].proposed_title = "TITRE PERIME"

            fake_tmdb = SimpleNamespace(
                search_movie=lambda title, year=None: [SimpleNamespace(id=27205, poster_path="/p.jpg")],
                flush=lambda: None,
            )
            with patch.object(tmdb_support, "_build_tmdb_client", return_value=(fake_tmdb, None)):
                res = tmdb_support.enrich_tmdb_ids_by_title(api, RUN_ID, ["f1"])

            self.assertTrue(res["ok"], res)
            self.assertEqual(res["resolved"], 1)
            # plan.jsonl reecrit avec le tmdb_id...
            on_disk = json.loads(paths.plan_jsonl.read_text(encoding="utf-8").strip())
            self.assertEqual(on_disk["tmdb_id"], 27205)
            # ... donc la memoire doit repartir du fichier (avant le fix : "TITRE PERIME")
            self.assertEqual(run_state.rows[0].proposed_title, "ANCIEN TITRE")
            self.assertFalse((paths.run_dir / "dashboard_cache.json").exists())


# ---------------------------------------------------------------------------
# HIGH-18 : un seul store de marquage suppression (table DB), annulable
# ---------------------------------------------------------------------------


class _DeletionApi(_StubApi):
    """StubApi + api.run.get_plan (utilise pour resoudre les source_path)."""

    def __init__(self, state_dir: Path, store: Any, rows: List[Dict[str, Any]]) -> None:
        super().__init__(state_dir, None, store)
        self.run = SimpleNamespace(get_plan=lambda run_id: {"ok": True, "rows": list(rows)})


class DeletionMarksSingleStoreTests(unittest.TestCase):
    def _api(self, tmp: Path):
        store = SQLiteStore(db_path_for_state_dir(tmp))
        store.initialize()
        rows = [
            {"row_id": "f1", "folder": str(tmp / "films" / "A")},
            {"row_id": "f2", "folder": str(tmp / "films" / "B")},
            {"row_id": "f3", "folder": str(tmp / "films" / "C")},
        ]
        _run_paths(tmp)  # cree le run_dir
        return _DeletionApi(tmp, store, rows), store

    def test_bulk_mark_is_unmarkable_and_visible(self) -> None:
        """Le marquage bulk doit atterrir dans le MEME store que le modal :
        is_marked_for_deletion le voit, unmark_for_deletion peut l'annuler."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, store = self._api(tmp)

            res = library_actions_support.mark_for_deletion_bulk(api, ["f1", "f2", "f3"], run_id=RUN_ID)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["count"], 3)

            # Avant le fix : le bulk ecrivait dans deletion_marks.json -> False.
            self.assertTrue(store.film_modal.is_marked_for_deletion(run_id=RUN_ID, row_id="f2"))

            # L'utilisateur change d'avis sur f2 depuis le modal Film.
            out = library_support.unmark_for_deletion(api, RUN_ID, "f2")
            self.assertTrue(out["ok"], out)
            self.assertTrue(out["removed"])
            self.assertFalse(store.film_modal.is_marked_for_deletion(run_id=RUN_ID, row_id="f2"))

            # ... et l'apply ne doit PLUS sortir f2 de la bibliotheque.
            marked = {m["row_id"] for m in store.film_modal.list_marked_for_deletion(run_id=RUN_ID)}
            marked |= set(library_actions_support.migrate_legacy_deletion_marks(api, RUN_ID))
            self.assertEqual(marked, {"f1", "f3"})

    def test_bulk_no_longer_writes_legacy_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, _store = self._api(tmp)
            library_actions_support.mark_for_deletion_bulk(api, ["f1"], run_id=RUN_ID)
            legacy = _run_paths(tmp).run_dir / "deletion_marks.json"
            self.assertFalse(legacy.exists())

    def test_bulk_idempotent_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, _store = self._api(tmp)
            self.assertEqual(library_actions_support.mark_for_deletion_bulk(api, ["f1"], run_id=RUN_ID)["count"], 1)
            self.assertEqual(library_actions_support.mark_for_deletion_bulk(api, ["f1"], run_id=RUN_ID)["count"], 0)

    def test_legacy_json_marks_are_migrated_and_unmarkable(self) -> None:
        """Retro-compat : les marques deja dans deletion_marks.json sont migrees
        a la lecture vers la DB, donc annulables (et le fichier disparait)."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, store = self._api(tmp)
            legacy = _run_paths(tmp).run_dir / "deletion_marks.json"
            legacy.write_text(
                json.dumps({"row_ids": ["f1", "f3"], "marked_ts": {"f1": 1.0, "f3": 2.0}}),
                encoding="utf-8",
            )

            # Chemin de lecture (vue Bibliotheque / apply / unmark) -> migration.
            out = library_support.unmark_for_deletion(api, RUN_ID, "f3")
            self.assertTrue(out["ok"], out)
            self.assertTrue(out["removed"])  # avant le fix : rien a supprimer en DB

            self.assertFalse(legacy.exists())  # fichier draine
            self.assertTrue(store.film_modal.is_marked_for_deletion(run_id=RUN_ID, row_id="f1"))
            self.assertFalse(store.film_modal.is_marked_for_deletion(run_id=RUN_ID, row_id="f3"))

            # L'apply ne ressuscite pas f3 depuis le JSON (il n'existe plus).
            marked = {m["row_id"] for m in store.film_modal.list_marked_for_deletion(run_id=RUN_ID)}
            marked |= set(library_actions_support.migrate_legacy_deletion_marks(api, RUN_ID))
            self.assertEqual(marked, {"f1"})

    def test_legacy_json_kept_when_db_unavailable(self) -> None:
        """Filet : store DB indisponible -> aucune perte, le JSON reste honore."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, _store = self._api(tmp)
            legacy = _run_paths(tmp).run_dir / "deletion_marks.json"
            legacy.write_text(json.dumps({"row_ids": ["f1"], "marked_ts": {}}), encoding="utf-8")

            with patch.object(library_actions_support, "_film_modal_repo", return_value=None):
                ids = library_actions_support.migrate_legacy_deletion_marks(api, RUN_ID)
            self.assertEqual(ids, ["f1"])
            self.assertTrue(legacy.exists())

    def test_unknown_row_id_not_marked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, store = self._api(tmp)
            res = library_actions_support.mark_for_deletion_bulk(api, ["f1", "nope"], run_id=RUN_ID)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["count"], 1)
            self.assertIn("nope", res["failed"])
            self.assertFalse(store.film_modal.is_marked_for_deletion(run_id=RUN_ID, row_id="nope"))


# ===========================================================================
# REVUE ADVERSAIRE 2026-07-13 du fix HIGH-17/18/19 — 7 defauts
# ===========================================================================


class _LockedRepo:
    """Repo film_modal dont chaque acces leve sqlite3.OperationalError.

    Pas de `_managed_conn` / `_ensure_tables` : force le chemin de repli
    unitaire (le meme qu'un repo stub), donc les except des helpers sont bien
    exerces sur `mark_for_deletion`.
    """

    def mark_for_deletion(self, **_kw: Any) -> Dict[str, Any]:
        raise sqlite3.OperationalError("database is locked")

    def is_marked_for_deletion(self, **_kw: Any) -> bool:
        raise sqlite3.OperationalError("database is locked")

    def list_marked_for_deletion(self, **_kw: Any) -> List[Dict[str, Any]]:
        raise sqlite3.OperationalError("database is locked")

    def unmark_for_deletion(self, **_kw: Any) -> Dict[str, Any]:
        raise sqlite3.OperationalError("database is locked")


class MultiRootReplanTests(unittest.TestCase):
    """DEFAUT 1 (destructif) : `replan_single_row` ne renseigne jamais
    `source_root` (pose par plan_multi_roots, pas par _plan_item). Avec le resync
    memoire du fix HIGH-17, le `source_root: null` du rescan n'est plus confine a
    plan.jsonl : il repart en memoire, et l'apply — qui groupe par
    `row.source_root or cfg.root` (apply_support.py:1602, cfg.root = roots[0]) —
    deplacerait un film du ROOT2 dans le ROOT1."""

    def _setup_multi_root(self, tmp: Path):
        root2 = tmp / "root2"
        films = root2 / "Ancien Titre (2010)"
        films.mkdir(parents=True, exist_ok=True)
        (films / "movie.mkv").write_bytes(b"x")

        paths = _run_paths(tmp)
        paths.plan_jsonl.write_text(
            json.dumps(_plan_row(folder=str(films), source_root=str(root2))) + "\n",
            encoding="utf-8",
        )
        rows = load_rows_from_plan_jsonl(paths)
        store = SimpleNamespace(field_locks=None)
        run_state = _StubRunState(paths, rows, store)
        # cfg.root = roots[0] (ROOT1), comme en multi-root reel.
        run_state.cfg = SimpleNamespace(root=tmp / "root1")
        api = _StubApi(tmp, run_state, store)
        return api, run_state, paths, films, root2

    def _fresh_row(self, films: Path) -> core.PlanRow:
        # Ce que renvoie reellement replan_single_row : source_root=None (defaut
        # du dataclass, jamais renseigne par _plan_item).
        return core.PlanRow(
            row_id="ignore-moi",
            kind="single",
            folder=str(films),
            video="movie.mkv",
            proposed_title="NOUVEAU TITRE",
            proposed_year=2011,
            proposed_source="tmdb",
            confidence=95,
            confidence_label="high",
            candidates=[],
        )

    def test_replan_preserves_source_root_on_disk_and_in_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, run_state, paths, films, root2 = self._setup_multi_root(tmp)

            with patch(
                "cinesort.app.plan_support.replan_single_row",
                return_value=self._fresh_row(films),
            ):
                out = library_actions_support._rematch_tmdb_and_update_plan(api, RUN_ID, "f1")

            self.assertIsNotNone(out)
            self.assertEqual(out["proposed_title"], "NOUVEAU TITRE")  # le replan a bien eu lieu

            # 1. plan.jsonl ne doit PAS avoir perdu la racine du scan.
            on_disk = json.loads(paths.plan_jsonl.read_text(encoding="utf-8").strip())
            self.assertEqual(on_disk["source_root"], str(root2))

            # 2. snapshot memoire (resynchronise depuis le plan) idem.
            self.assertEqual(run_state.rows[0].source_root, str(root2))

            # 3. la cle de groupement de l'apply reste ROOT2 (et pas cfg.root=ROOT1).
            rows_for_apply = apply_support.run_context_for_apply(api, RUN_ID)[2]
            group_key = getattr(rows_for_apply[0], "source_root", None) or str(run_state.cfg.root)
            self.assertEqual(group_key, str(root2))

    def test_replan_receives_subtitle_expected_languages(self) -> None:
        """Sans cet argument, _apply_subtitle_detection sort par sa garde `is None`
        et le rescan EFFACE subtitle_count / languages / missing_langs."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, _rs, _paths, films, _root2 = self._setup_multi_root(tmp)
            api._settings["subtitle_expected_languages"] = ["FR", "en"]

            seen: Dict[str, Any] = {}

            def _capture(*args: Any, **kwargs: Any) -> core.PlanRow:
                seen.update(kwargs)
                return self._fresh_row(films)

            with patch("cinesort.app.plan_support.replan_single_row", side_effect=_capture):
                library_actions_support._rematch_tmdb_and_update_plan(api, RUN_ID, "f1")

            self.assertEqual(seen.get("subtitle_expected_languages"), ["fr", "en"])

    def test_tv_episode_row_is_not_replanned_as_a_movie(self) -> None:
        """replan_single_row ne sait produire que des rows FILM : rejouer le match
        sur un episode ecraserait kind + tv_* -> l'apply le classerait en film."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, _rs, paths, films, root2 = self._setup_multi_root(tmp)
            paths.plan_jsonl.write_text(
                json.dumps(
                    _plan_row(
                        folder=str(films),
                        source_root=str(root2),
                        kind="tv_episode",
                        tv_series_name="Ma Serie",
                        tv_season=2,
                        tv_episode=5,
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            with patch(
                "cinesort.app.plan_support.replan_single_row",
                return_value=self._fresh_row(films),
            ):
                out = library_actions_support._rematch_tmdb_and_update_plan(api, RUN_ID, "f1")

            self.assertIsNone(out)
            on_disk = json.loads(paths.plan_jsonl.read_text(encoding="utf-8").strip())
            self.assertEqual(on_disk["kind"], "tv_episode")
            self.assertEqual(on_disk["tv_series_name"], "Ma Serie")


class DeletionMarksBatchTests(unittest.TestCase):
    """DEFAUT 2 : 2 appels repo PAR FILM (chacun ouvrant sa connexion +
    _ensure_tables) sur un endpoint SYNCHRONE = 9,6 s pour 500 films (UI gelee)."""

    def test_bulk_marks_in_a_constant_number_of_connections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            store = SQLiteStore(db_path_for_state_dir(tmp))
            store.initialize()
            rows = [{"row_id": f"f{i}", "folder": str(tmp / "films" / f"F{i}")} for i in range(50)]
            _run_paths(tmp)
            api = _DeletionApi(tmp, store, rows)

            opened: List[int] = []
            real_managed_conn = store._managed_conn

            def _counting_managed_conn():
                opened.append(1)
                return real_managed_conn()

            store._managed_conn = _counting_managed_conn  # type: ignore[method-assign]
            try:
                res = library_actions_support.mark_for_deletion_bulk(api, [r["row_id"] for r in rows], run_id=RUN_ID)
            finally:
                del store._managed_conn

            self.assertTrue(res["ok"], res)
            self.assertEqual(res["count"], 50)
            self.assertEqual(res["failed"], [])
            # Avant le fix : >= 100 connexions (2 par film). Apres : 1 lecture
            # (list_marked_for_deletion) + 1 executemany, + marge schema.
            self.assertLessEqual(
                len(opened),
                8,
                f"marquage bulk non batche : {len(opened)} connexions SQLite pour 50 films",
            )
            self.assertEqual(
                len(store.film_modal.list_marked_for_deletion(run_id=RUN_ID)),
                50,
            )

    def test_duplicate_row_ids_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            store = SQLiteStore(db_path_for_state_dir(tmp))
            store.initialize()
            _run_paths(tmp)
            api = _DeletionApi(tmp, store, [{"row_id": "f1", "folder": str(tmp / "A")}])
            res = library_actions_support.mark_for_deletion_bulk(api, ["f1", "f1"], run_id=RUN_ID)
            self.assertEqual(res["count"], 1)


class DeletionMarksLockedDbTests(unittest.TestCase):
    """DEFAUTS 3 + 4 : `sqlite3.Error` N'HERITE PAS d'OSError. Une
    sqlite3.OperationalError("database is locked") traversait les except des
    nouveaux helpers et faisait CRASHER l'apply, la vue Bibliotheque et unmark —
    alors que ces helpers sont des filets best-effort "sans perte"."""

    def _api(self, tmp: Path):
        store = SQLiteStore(db_path_for_state_dir(tmp))
        store.initialize()
        _run_paths(tmp)
        return _DeletionApi(tmp, store, [{"row_id": "f1", "folder": str(tmp / "films" / "A")}]), store

    def _legacy(self, tmp: Path) -> Path:
        legacy = _run_paths(tmp).run_dir / "deletion_marks.json"
        legacy.write_text(json.dumps({"row_ids": ["f1"], "marked_ts": {}}), encoding="utf-8")
        return legacy

    def test_locked_db_keeps_legacy_json_and_still_returns_row_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, _store = self._api(tmp)
            legacy = self._legacy(tmp)

            with patch.object(library_actions_support, "_film_modal_repo", return_value=_LockedRepo()):
                # Ne doit PAS lever (avant le fix : sqlite3.OperationalError).
                ids = library_actions_support.migrate_legacy_deletion_marks(api, RUN_ID)

            self.assertEqual(ids, ["f1"])  # l'apply honore encore le JSON
            self.assertTrue(legacy.exists())  # aucune perte de marquage

    def test_locked_db_bulk_reports_failure_instead_of_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, _store = self._api(tmp)

            with patch.object(library_actions_support, "_film_modal_repo", return_value=_LockedRepo()):
                res = library_actions_support.mark_for_deletion_bulk(api, ["f1"], run_id=RUN_ID)

            self.assertTrue(res["ok"], res)
            self.assertEqual(res["count"], 0)
            self.assertEqual(res["failed"], ["f1"])

    def test_locked_db_does_not_break_library_view_nor_unmark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, _store = self._api(tmp)
            self._legacy(tmp)

            with patch.object(
                library_actions_support,
                "migrate_legacy_deletion_marks",
                side_effect=sqlite3.OperationalError("database is locked"),
            ):
                rows = library_support._build_library_rows(api, RUN_ID)  # ne doit pas lever
                out = library_support.unmark_for_deletion(api, RUN_ID, "f1")  # ne doit pas lever

            self.assertIsInstance(rows, list)
            self.assertIsInstance(out, dict)

    def test_locked_db_does_not_crash_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, store = self._api(tmp)
            paths = _run_paths(tmp)
            root = tmp / "films"
            root.mkdir(parents=True, exist_ok=True)
            cfg = core.Config(root=root)

            with patch.object(
                library_actions_support,
                "migrate_legacy_deletion_marks",
                side_effect=sqlite3.OperationalError("database is locked"),
            ):
                result, batch_id, _n = apply_support._execute_apply(
                    cfg,
                    [],
                    {},
                    None,
                    dry_run=True,
                    quarantine_unapproved=False,
                    log_fn=lambda _lvl, _msg: None,
                    run_paths=paths,
                    store=store,
                    api=api,
                    run_id=RUN_ID,
                    batch_state=[None, 0],
                )
            self.assertIsNotNone(result)
            self.assertIsNone(batch_id)  # dry_run


class DeletionMarksMiscTests(unittest.TestCase):
    def test_no_misleading_reader_named_function(self) -> None:
        """DEFAUT 5 : `list_deletion_marks_row_ids` avait un nom de LECTEUR mais
        ecrivait en DB et SUPPRIMAIT le JSON. Le drain s'appelle desormais
        explicitement `migrate_legacy_deletion_marks`."""
        self.assertFalse(hasattr(library_actions_support, "list_deletion_marks_row_ids"))
        self.assertTrue(hasattr(library_actions_support, "migrate_legacy_deletion_marks"))

    def test_read_path_does_not_recreate_run_dir(self) -> None:
        """DEFAUT 6 : _deletion_marks_path resolvait le run avec ensure_exists=True
        -> chaque affichage de la Bibliotheque RECREAIT runs/tri_films_<id>/."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            store = SQLiteStore(db_path_for_state_dir(tmp))
            store.initialize()
            api = _DeletionApi(tmp, store, [{"row_id": "f1", "folder": str(tmp / "A")}])

            run_dir = tmp / "runs" / f"tri_films_{RUN_ID}"
            self.assertFalse(run_dir.exists())

            library_actions_support.migrate_legacy_deletion_marks(api, RUN_ID)
            self.assertFalse(run_dir.exists(), "dossier de run fantome recree par un chemin de LECTURE")

            library_support._build_library_rows(api, RUN_ID)
            self.assertFalse(run_dir.exists(), "dossier de run fantome recree par la vue Bibliotheque")


# ===========================================================================
# REVUE ADVERSAIRE R3 2026-07-13 du fix des 7 defauts — 5 nouveaux defauts
# ===========================================================================


class ReplanExtraRowTests(unittest.TestCase):
    """R3 DEFAUT 1 (DESTRUCTIF — CRIT-1 rouvert par une autre porte) : la garde du
    replan etait une liste NOIRE (tv_episode seul) et laissait passer kind="extra"
    (video bonus d'un dossier PARTAGE, plan_support_core.py:773). La row retombait
    en kind="single" (replan_single_row:875 renormalise tout kind hors
    {single, collection}), plan.jsonl etait reecrit ET recharge en memoire par le
    resync — or apply_core traite kind="single" comme "dossier dedie"
    (apply_core.py:1282) : marquer ce bonus pour suppression emportait de nouveau
    TOUT le dossier (film principal compris)."""

    def _setup(self, tmp: Path, **row_over: Any):
        films = tmp / "root2" / "Star Wars (1977)"
        films.mkdir(parents=True, exist_ok=True)
        (films / "movie.mkv").write_bytes(b"x")
        (films / "making-of.mkv").write_bytes(b"x")

        paths = _run_paths(tmp)
        paths.plan_jsonl.write_text(
            json.dumps(_plan_row(folder=str(films), video="making-of.mkv", **row_over)) + "\n",
            encoding="utf-8",
        )
        store = SimpleNamespace(field_locks=None)
        run_state = _StubRunState(paths, load_rows_from_plan_jsonl(paths), store)
        return _StubApi(tmp, run_state, store), run_state, paths, films

    def _fresh_single(self, films: Path) -> core.PlanRow:
        # Ce que replan_single_row renverrait : une row FILM ordinaire.
        return core.PlanRow(
            row_id="ignore-moi",
            kind="single",
            folder=str(films),
            video="making-of.mkv",
            proposed_title="NOUVEAU TITRE",
            proposed_year=2011,
            proposed_source="tmdb",
            confidence=95,
            confidence_label="high",
            candidates=[],
        )

    def test_extra_bonus_row_is_not_replanned_as_a_single(self) -> None:
        """AVANT le fix : kind "extra" -> "single" sur disque ET en memoire, donc
        l'apply aurait quarantaine le DOSSIER ENTIER au lieu du seul bonus."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, run_state, paths, films = self._setup(tmp, kind="extra", warning_flags=["bonus_video"])

            with patch(
                "cinesort.app.plan_support.replan_single_row",
                return_value=self._fresh_single(films),
            ):
                out = library_actions_support._rematch_tmdb_and_update_plan(api, RUN_ID, "f1")

            self.assertIsNone(out, "une row 'extra' ne doit pas etre replanifiee")

            # 1. plan.jsonl intact : kind + flag bonus preserves.
            on_disk = json.loads(paths.plan_jsonl.read_text(encoding="utf-8").strip())
            self.assertEqual(on_disk["kind"], "extra")
            self.assertIn("bonus_video", on_disk["warning_flags"])

            # 2. snapshot memoire intact (c'est lui que l'apply prefere).
            self.assertEqual(run_state.rows[0].kind, "extra")

            # 3. granularite de l'apply preservee : kind != "single" => on ne
            #    deplace que la video marquee, pas le dossier partage.
            rows_for_apply = apply_support.run_context_for_apply(api, RUN_ID)[2]
            self.assertNotEqual(
                rows_for_apply[0].kind,
                "single",
                "kind='single' => apply_core quarantine le DOSSIER ENTIER (film principal inclus)",
            )

    def test_unknown_future_kind_is_refused_not_renormalized(self) -> None:
        """Liste BLANCHE : tout kind inconnu doit etre refuse, jamais renormalise
        en 'single' (c'est exactement ce qui a rouvert le bug destructif)."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, _rs, paths, films = self._setup(tmp, kind="kind_du_futur")

            with patch(
                "cinesort.app.plan_support.replan_single_row",
                return_value=self._fresh_single(films),
            ):
                out = library_actions_support._rematch_tmdb_and_update_plan(api, RUN_ID, "f1")

            self.assertIsNone(out)
            on_disk = json.loads(paths.plan_jsonl.read_text(encoding="utf-8").strip())
            self.assertEqual(on_disk["kind"], "kind_du_futur")

    def test_single_and_collection_still_replanned(self) -> None:
        """Non-regression : les 2 kinds legitimes restent replanifiables, et le
        kind d'origine n'est pas ecrase (collection ne devient pas single)."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            for kind in ("single", "collection"):
                api, _rs, paths, films = self._setup(tmp, kind=kind)
                fresh = self._fresh_single(films)
                fresh.kind = kind
                with patch("cinesort.app.plan_support.replan_single_row", return_value=fresh):
                    out = library_actions_support._rematch_tmdb_and_update_plan(api, RUN_ID, "f1")
                self.assertIsNotNone(out, f"kind={kind} doit rester replanifiable")
                on_disk = json.loads(paths.plan_jsonl.read_text(encoding="utf-8").strip())
                self.assertEqual(on_disk["kind"], kind)
                self.assertEqual(on_disk["proposed_title"], "NOUVEAU TITRE")


class ReplanScanOnlyFlagsTests(unittest.TestCase):
    """R3 DEFAUT 2 (effacement de donnees) : le scan pose APRES _plan_item des
    warning_flags/notes que le replan ne peut pas reconstruire (root_level_source,
    duplicate_cross_root + note "Aussi dans:"). Un rescan les EFFACAIT."""

    def test_rescan_preserves_scan_only_flags_and_cross_root_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            root2 = tmp / "root2"
            films = root2 / "Film (2010)"
            films.mkdir(parents=True, exist_ok=True)
            (films / "movie.mkv").write_bytes(b"x")

            paths = _run_paths(tmp)
            paths.plan_jsonl.write_text(
                json.dumps(
                    _plan_row(
                        folder=str(films),
                        source_root=str(root2),
                        warning_flags=["root_level_source", "duplicate_cross_root"],
                        notes="note scan | Aussi dans: D:\\Films2",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            store = SimpleNamespace(field_locks=None)
            run_state = _StubRunState(paths, load_rows_from_plan_jsonl(paths), store)
            api = _StubApi(tmp, run_state, store)

            # replan_single_row ne voit qu'un fichier isole : aucun de ces flags.
            fresh = core.PlanRow(
                row_id="ignore-moi",
                kind="single",
                folder=str(films),
                video="movie.mkv",
                proposed_title="NOUVEAU TITRE",
                proposed_year=2011,
                proposed_source="tmdb",
                confidence=95,
                confidence_label="high",
                candidates=[],
                warning_flags=["subtitle_missing"],
                notes="",
            )
            with patch("cinesort.app.plan_support.replan_single_row", return_value=fresh):
                out = library_actions_support._rematch_tmdb_and_update_plan(api, RUN_ID, "f1")

            self.assertIsNotNone(out)
            on_disk = json.loads(paths.plan_jsonl.read_text(encoding="utf-8").strip())

            # Flags du scan reportes (avant le fix : effaces).
            self.assertIn("root_level_source", on_disk["warning_flags"])
            self.assertIn("duplicate_cross_root", on_disk["warning_flags"])
            # ... sans perdre ceux que le replan vient de recalculer.
            self.assertIn("subtitle_missing", on_disk["warning_flags"])
            # Note cross-root reportee : sans elle le badge doublon ne dit plus OU.
            self.assertIn("Aussi dans: D:\\Films2", on_disk["notes"])
            # Le replan a bien eu lieu par ailleurs.
            self.assertEqual(on_disk["proposed_title"], "NOUVEAU TITRE")
            # Et en memoire (c'est ce que lit l'UI/l'apply).
            self.assertIn("root_level_source", run_state.rows[0].warning_flags)

    def test_no_duplicate_flag_when_replan_already_set_it(self) -> None:
        target = {"warning_flags": ["root_level_source"], "notes": ""}
        new_row = {"warning_flags": ["root_level_source"], "notes": ""}
        library_actions_support._carry_over_scan_only_fields(target, new_row)
        self.assertEqual(new_row["warning_flags"], ["root_level_source"])


class UnmarkLegacyDrainTests(unittest.TestCase):
    """R3 DEFAUTS 3 + 4 : unmark sur une install portant encore un
    deletion_marks.json."""

    def _api(self, tmp: Path):
        store = SQLiteStore(db_path_for_state_dir(tmp))
        store.initialize()
        _run_paths(tmp)
        return _DeletionApi(tmp, store, [{"row_id": "f1", "folder": str(tmp / "films" / "A")}]), store

    def test_unmark_does_not_lie_when_legacy_drain_failed(self) -> None:
        """DEFAUT 4 : drain KO (DB verrouillee au moment du drain) -> le JSON est
        CONSERVE par design. Avant le fix, unmark repondait ok:True/"demarque"
        alors que l'apply (union DB + legacy) rebucketisait le film."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, store = self._api(tmp)
            legacy = _run_paths(tmp).run_dir / "deletion_marks.json"
            legacy.write_text(json.dumps({"row_ids": ["f1"], "marked_ts": {}}), encoding="utf-8")

            # Drain en echec : la marque n'atteint jamais la DB, le JSON reste.
            with patch.object(library_actions_support, "_film_modal_repo", return_value=_LockedRepo()):
                out = library_support.unmark_for_deletion(api, RUN_ID, "f1")

            # L'utilisateur a demande le demarquage : il ne doit RESTER aucune
            # marque honoree par l'apply (ni en DB, ni dans le JSON legacy).
            marked = {m["row_id"] for m in store.film_modal.list_marked_for_deletion(run_id=RUN_ID)}
            marked |= set(library_actions_support.migrate_legacy_deletion_marks(api, RUN_ID))
            self.assertEqual(
                marked,
                set(),
                "unmark a repondu sans retirer la marque legacy -> l'apply bucketise quand meme",
            )
            self.assertTrue(out["ok"], out)

    def test_unmark_surfaces_failure_when_legacy_cannot_be_cleared(self) -> None:
        """Si la marque legacy ne peut PAS etre retiree, l'endpoint ne doit pas
        pretendre que le demarquage a reussi."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, _store = self._api(tmp)

            with patch.object(library_actions_support, "remove_legacy_deletion_mark", return_value=False):
                out = library_support.unmark_for_deletion(api, RUN_ID, "f1")

            self.assertFalse(out.get("ok"), out)

    def test_unmark_survives_locked_db_on_the_real_delete(self) -> None:
        """DEFAUT 3 : l'except du drain couvrait sqlite3.Error, mais pas l'appel
        REEL store.film_modal.unmark_for_deletion (sqlite3.Error n'herite pas
        d'OSError) -> DB verrouillee = HTTP 500."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, store = self._api(tmp)
            store.film_modal = _LockedRepo()  # type: ignore[assignment]

            out = library_support.unmark_for_deletion(api, RUN_ID, "f1")  # ne doit pas lever

            self.assertIsInstance(out, dict)
            self.assertFalse(out.get("ok"), out)

    def test_legacy_removal_keeps_other_row_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            api, _store = self._api(tmp)
            legacy = _run_paths(tmp).run_dir / "deletion_marks.json"
            legacy.write_text(
                json.dumps({"row_ids": ["f1", "f2"], "marked_ts": {"f1": 1.0, "f2": 2.0}}),
                encoding="utf-8",
            )

            ok = library_actions_support.remove_legacy_deletion_mark(api, RUN_ID, "f1")
            self.assertTrue(ok)
            data = json.loads(legacy.read_text(encoding="utf-8"))
            self.assertEqual(data["row_ids"], ["f2"])
            self.assertNotIn("f1", data["marked_ts"])


class FilmModalLegacyMarkTests(unittest.TestCase):
    """R3 DEFAUT 5 : `is_marked_for_deletion` (seul producteur du flag lu par le
    modal Film) etait le seul chemin de lecture des marques SANS le drain legacy.
    Sur une install portant encore un deletion_marks.json, la fiche film proposait
    "Marquer pour suppression" pour un film qui SERA bucketise a l'apply."""

    def _api(self, tmp: Path):
        from cinesort.ui.api import film_support

        store = SQLiteStore(db_path_for_state_dir(tmp))
        store.initialize()
        films = tmp / "films" / "A"
        films.mkdir(parents=True, exist_ok=True)
        (films / "movie.mkv").write_bytes(b"x")

        paths = _run_paths(tmp)
        row = _plan_row(folder=str(films))
        paths.plan_jsonl.write_text(json.dumps(row) + "\n", encoding="utf-8")
        api = _DeletionApi(tmp, store, [row])
        api._run_state = _StubRunState(paths, load_rows_from_plan_jsonl(paths), store)
        return film_support, api, store

    def test_film_modal_sees_legacy_mark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            film_support, api, store = self._api(tmp)
            legacy = _run_paths(tmp).run_dir / "deletion_marks.json"
            legacy.write_text(json.dumps({"row_ids": ["f1"], "marked_ts": {}}), encoding="utf-8")

            res = film_support.get_film_full(api, RUN_ID, "f1")

            self.assertTrue(res.get("ok"), res)
            self.assertTrue(
                res.get("is_marked_for_deletion"),
                "fiche film aveugle a la marque legacy -> l'UI propose de marquer un film deja marque",
            )
            # Le drain a aussi unifie le store (la marque est desormais annulable).
            self.assertTrue(store.film_modal.is_marked_for_deletion(run_id=RUN_ID, row_id="f1"))

    def test_film_modal_sees_legacy_mark_even_if_db_drain_fails(self) -> None:
        """DB verrouillee : le drain echoue et CONSERVE le JSON (que l'apply honore)
        -> le flag doit venir de l'UNION, et l'ouverture de la fiche ne doit pas
        remonter une sqlite3.Error."""
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            film_support, api, _store = self._api(tmp)
            legacy = _run_paths(tmp).run_dir / "deletion_marks.json"
            legacy.write_text(json.dumps({"row_ids": ["f1"], "marked_ts": {}}), encoding="utf-8")

            with patch.object(library_actions_support, "_film_modal_repo", return_value=_LockedRepo()):
                res = film_support.get_film_full(api, RUN_ID, "f1")

            self.assertTrue(res.get("ok"), res)
            self.assertTrue(res.get("is_marked_for_deletion"))
            self.assertTrue(legacy.exists())  # aucune perte de marquage


if __name__ == "__main__":
    unittest.main()
