"""Tests Phase 4 — endpoints backend du Modal Film (spec 06).

Couvre :
- library/set_film_tmdb_candidate : change confidence + proposed_path
- library/mark_for_deletion : flag pose sur plan_row + DB
- library/mark_alert_ignored : insert en DB
- run/rescan_row : relance pipeline + retourne nouveau score
- library/get_film_full : contient runtime + director
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cinesort.infra.db.sqlite_store import SQLiteStore


def _make_real_store() -> tuple[SQLiteStore, Path]:
    """Cree un SQLiteStore vrai sur un fichier temporaire (migration 023 incluse)."""
    tmp = Path(tempfile.mkdtemp(prefix="cinesort_phase4_"))
    store = SQLiteStore(tmp / "test.sqlite", busy_timeout_ms=5000)
    store.initialize()
    return store, tmp


def _wire_plan(api: MagicMock, rows: list) -> None:
    """Cable le plan du run sur le chemin de lecture reellement emprunte.

    PERF (ultra-audit 2026-08) : `film_support._find_plan_row` ne demande plus
    le plan ENTIER via `api.run.get_plan` (qui serialisait et enrichissait les N
    rows pour n'en garder qu'une) ; il passe par `history_support.get_plan_row`,
    donc par `api._get_run` + `api._serialize_rows_for_payload`. On cable les
    deux pour que le stub reste valable quel que soit le consommateur.
    """
    api.run.get_plan.return_value = {"ok": True, "rows": rows}
    api._get_run.return_value = SimpleNamespace(done=True, rows=rows, paths=None)
    api._serialize_rows_for_payload = lambda rs: [dict(r) for r in rs]


def _make_api_with_store(store: SQLiteStore) -> MagicMock:
    """Construit un MagicMock CineSortApi cable sur un vrai SQLiteStore.

    Les facades (api.settings, api.run, api.integrations) sont mockees au cas
    par cas dans les tests. Le store est expose via _get_or_create_infra()
    (pattern utilise par toute la couche ui/api/*_support.py).
    """
    api = MagicMock()
    api.settings.get_settings.return_value = {"state_dir": None, "tmdb_api_key": ""}
    api._get_or_create_infra.return_value = (store, None)
    api._normalize_user_path = lambda p, default: default
    # Plan par defaut (peut etre override dans chaque test)
    _wire_plan(
        api,
        [
            {
                "row_id": "r1",
                "proposed_title": "Inception",
                "proposed_year": 2010,
                "confidence": 80,
                "confidence_label": "med",
                "source_path": "D:/Films/Inception (2010).mkv",
                "folder": "D:/Films/Inception (2010)",
                "candidates": [
                    {"tmdb_id": 27205, "title": "Inception", "year": 2010, "score": 0.95},
                    {"tmdb_id": 999, "title": "Inception (Alt)", "year": 2011, "score": 0.55},
                ],
                "edition": None,
            }
        ],
    )
    # Note : on utilise le vrai store SQLite (.run / .film_modal etc.), inutile
    # de mocker store.run.list_runs().
    return api


# ---------------------------------------------------------------------------
# Repository : FilmModalRepository (lecture/ecriture DB pure)
# ---------------------------------------------------------------------------


class FilmModalRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store, self._tmp = _make_real_store()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_insert_ignored_alert_first_time(self) -> None:
        res = self.store.film_modal.insert_ignored_alert("r1", "subtitle_missing_fr")
        self.assertTrue(res["ok"])
        self.assertTrue(res["inserted"])

    def test_insert_ignored_alert_idempotent(self) -> None:
        self.store.film_modal.insert_ignored_alert("r1", "alert_x")
        res = self.store.film_modal.insert_ignored_alert("r1", "alert_x")
        self.assertTrue(res["ok"])
        # Le second insert ne fait rien (UNIQUE constraint)
        self.assertFalse(res["inserted"])

    def test_list_ignored_alerts(self) -> None:
        self.store.film_modal.insert_ignored_alert("r1", "a")
        self.store.film_modal.insert_ignored_alert("r1", "b")
        self.store.film_modal.insert_ignored_alert("r2", "a")
        alerts_r1 = self.store.film_modal.list_ignored_alerts("r1")
        self.assertEqual(sorted(alerts_r1), ["a", "b"])

    def test_is_alert_ignored(self) -> None:
        self.assertFalse(self.store.film_modal.is_alert_ignored("r1", "x"))
        self.store.film_modal.insert_ignored_alert("r1", "x")
        self.assertTrue(self.store.film_modal.is_alert_ignored("r1", "x"))

    def test_mark_and_unmark_for_deletion(self) -> None:
        self.assertFalse(self.store.film_modal.is_marked_for_deletion(run_id="run1", row_id="r1"))
        res = self.store.film_modal.mark_for_deletion(run_id="run1", row_id="r1", source_path="D:/src")
        self.assertTrue(res["ok"])
        self.assertTrue(self.store.film_modal.is_marked_for_deletion(run_id="run1", row_id="r1"))

        marked_list = self.store.film_modal.list_marked_for_deletion(run_id="run1")
        self.assertEqual(len(marked_list), 1)
        self.assertEqual(marked_list[0]["row_id"], "r1")
        self.assertEqual(marked_list[0]["source_path"], "D:/src")

        # Undo
        undo = self.store.film_modal.unmark_for_deletion(run_id="run1", row_id="r1")
        self.assertTrue(undo["removed"])
        self.assertFalse(self.store.film_modal.is_marked_for_deletion(run_id="run1", row_id="r1"))

    def test_tmdb_override_upsert_and_get(self) -> None:
        self.assertIsNone(self.store.film_modal.get_tmdb_override(run_id="run1", row_id="r1"))
        self.store.film_modal.upsert_tmdb_override(
            run_id="run1",
            row_id="r1",
            tmdb_id=12345,
            new_confidence=72,
            proposed_title="Movie",
            proposed_year=2020,
        )
        got = self.store.film_modal.get_tmdb_override(run_id="run1", row_id="r1")
        self.assertIsNotNone(got)
        self.assertEqual(got["tmdb_id"], 12345)
        self.assertEqual(got["new_confidence"], 72)

        # Upsert nouveau choix
        self.store.film_modal.upsert_tmdb_override(
            run_id="run1",
            row_id="r1",
            tmdb_id=99,
            new_confidence=50,
            proposed_title="Other",
            proposed_year=2021,
        )
        got2 = self.store.film_modal.get_tmdb_override(run_id="run1", row_id="r1")
        self.assertEqual(got2["tmdb_id"], 99)


# ---------------------------------------------------------------------------
# library/set_film_tmdb_candidate
# ---------------------------------------------------------------------------


class SetFilmTmdbCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store, self._tmp = _make_real_store()
        self.api = _make_api_with_store(self.store)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_changes_confidence_and_proposed_path(self) -> None:
        from cinesort.ui.api import library_support

        res = library_support.set_film_tmdb_candidate(self.api, "run_test", "r1", 999)
        self.assertTrue(res["ok"])
        self.assertEqual(res["tmdb_id"], 999)
        # score 0.55 -> 55 confidence, label "low"
        self.assertEqual(res["new_confidence"], 55)
        self.assertEqual(res["new_confidence_label"], "low")
        self.assertEqual(res["proposed_title"], "Inception (Alt)")
        self.assertEqual(res["proposed_year"], 2011)
        # Nouveau proposed_path doit contenir le titre + annee
        self.assertIn("Inception", res["new_proposed_path"])
        self.assertIn("2011", res["new_proposed_path"])

    def test_persists_override_in_db(self) -> None:
        from cinesort.ui.api import library_support

        library_support.set_film_tmdb_candidate(self.api, "run_test", "r1", 999)
        stored = self.store.film_modal.get_tmdb_override(run_id="run_test", row_id="r1")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["tmdb_id"], 999)
        self.assertEqual(stored["proposed_title"], "Inception (Alt)")

    def test_unknown_tmdb_id(self) -> None:
        from cinesort.ui.api import library_support

        res = library_support.set_film_tmdb_candidate(self.api, "run_test", "r1", 88888)
        self.assertFalse(res["ok"])
        self.assertIn("introuvable", res["message"].lower())

    def test_invalid_tmdb_id(self) -> None:
        from cinesort.ui.api import library_support

        res = library_support.set_film_tmdb_candidate(self.api, "run_test", "r1", 0)
        self.assertFalse(res["ok"])

    def test_unknown_row_id(self) -> None:
        from cinesort.ui.api import library_support

        res = library_support.set_film_tmdb_candidate(self.api, "run_test", "unknown_row", 27205)
        self.assertFalse(res["ok"])


# ---------------------------------------------------------------------------
# library/mark_for_deletion
# ---------------------------------------------------------------------------


class MarkForDeletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store, self._tmp = _make_real_store()
        self.api = _make_api_with_store(self.store)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_flag_set_on_plan_row_db(self) -> None:
        from cinesort.ui.api import library_support

        res = library_support.mark_for_deletion(self.api, "run_test", "r1")
        self.assertTrue(res["ok"])
        self.assertTrue(res["marked"])
        self.assertEqual(res["row_id"], "r1")
        # Verifier persistance DB
        self.assertTrue(self.store.film_modal.is_marked_for_deletion(run_id="run_test", row_id="r1"))

    def test_source_path_persisted(self) -> None:
        from cinesort.ui.api import library_support

        res = library_support.mark_for_deletion(self.api, "run_test", "r1")
        self.assertEqual(res["source_path"], "D:/Films/Inception (2010).mkv")
        listed = self.store.film_modal.list_marked_for_deletion(run_id="run_test")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["source_path"], "D:/Films/Inception (2010).mkv")

    def test_unknown_row_returns_error(self) -> None:
        from cinesort.ui.api import library_support

        res = library_support.mark_for_deletion(self.api, "run_test", "ghost")
        self.assertFalse(res["ok"])


# ---------------------------------------------------------------------------
# library/mark_alert_ignored
# ---------------------------------------------------------------------------


class MarkAlertIgnoredTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store, self._tmp = _make_real_store()
        self.api = _make_api_with_store(self.store)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_insert_in_db(self) -> None:
        from cinesort.ui.api import library_support

        res = library_support.mark_alert_ignored(self.api, "r1", "subtitle_missing_fr")
        self.assertTrue(res["ok"])
        self.assertTrue(res["ignored"])
        self.assertFalse(res["already_ignored"])
        self.assertTrue(self.store.film_modal.is_alert_ignored("r1", "subtitle_missing_fr"))

    def test_idempotent_second_call(self) -> None:
        from cinesort.ui.api import library_support

        library_support.mark_alert_ignored(self.api, "r1", "code_x")
        res2 = library_support.mark_alert_ignored(self.api, "r1", "code_x")
        self.assertTrue(res2["ok"])
        self.assertTrue(res2["already_ignored"])

    def test_missing_row_id(self) -> None:
        from cinesort.ui.api import library_support

        res = library_support.mark_alert_ignored(self.api, "", "code")
        self.assertFalse(res["ok"])

    def test_missing_alert_code(self) -> None:
        from cinesort.ui.api import library_support

        res = library_support.mark_alert_ignored(self.api, "r1", "")
        self.assertFalse(res["ok"])


# ---------------------------------------------------------------------------
# run/rescan_row
# ---------------------------------------------------------------------------


class RescanRowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store, self._tmp = _make_real_store()
        self.api = _make_api_with_store(self.store)
        # Configurer _find_run_row (utilise par rescan_row)
        self.api._find_run_row.return_value = (
            {"run_id": "run_test", "state_dir": str(self._tmp)},
            self.store,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_invalidates_cache_and_returns_plan_row(self) -> None:
        from cinesort.ui.api import run_flow_support

        # Mock pour eviter d'executer reellement le probe+perceptual
        # (qui necessite ffmpeg + un vrai fichier video)
        with patch.object(
            run_flow_support,
            "quality_report_support",
            create=True,
        ):
            with (
                patch("cinesort.ui.api.quality_report_support.get_quality_report") as mock_qr,
                patch("cinesort.ui.api.perceptual_support.get_perceptual_report") as mock_pr,
            ):
                mock_qr.return_value = {"ok": True, "score": 72, "tier": "silver"}
                mock_pr.return_value = {
                    "ok": True,
                    "perceptual": {
                        "global_score_v2": 68.4,
                        "global_tier_v2": "silver",
                    },
                }
                res = run_flow_support.rescan_row(self.api, "run_test", "r1")
        self.assertTrue(res["ok"])
        self.assertEqual(res["row_id"], "r1")
        self.assertIsNotNone(res.get("plan_row"))
        self.assertEqual(res["quality"]["score"], 72)
        self.assertEqual(res["perceptual"]["global_score_v2"], 68.4)

    def test_missing_row_id(self) -> None:
        from cinesort.ui.api import run_flow_support

        res = run_flow_support.rescan_row(self.api, "run_test", "")
        self.assertFalse(res["ok"])


# ---------------------------------------------------------------------------
# library/get_film_full enriched (spec 06 §3.1)
# ---------------------------------------------------------------------------


class GetFilmFullEnrichedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store, self._tmp = _make_real_store()
        self.api = _make_api_with_store(self.store)
        # Configuration store.run.list_runs() necessaire pour _resolve_run_id
        # quand run_id=None. On accepte qu'il puisse echouer (la facade
        # store.run.list_runs n'est pas un MagicMock ici).

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_payload_contains_runtime_director_overview_keys(self) -> None:
        from cinesort.ui.api import film_support

        # Mock _fetch_tmdb_extras pour eviter un appel reseau (pas de cle TMDb)
        with patch.object(film_support, "_fetch_tmdb_extras") as mock_extras:
            mock_extras.return_value = {
                "runtime": 148,
                "director": "Christopher Nolan",
                "overview": "Un voleur experimente...",
            }
            res = film_support.get_film_full(self.api, "run_test", "r1")
        self.assertTrue(res["ok"])
        # Spec 06 §3.1 : champs top-level pour le hero du Modal Film
        self.assertIn("runtime", res)
        self.assertIn("director", res)
        self.assertIn("overview", res)
        self.assertEqual(res["runtime"], 148)
        self.assertEqual(res["director"], "Christopher Nolan")

    def test_poster_url_uses_w500_size(self) -> None:
        from cinesort.ui.api import film_support

        captured_size: list = []

        def _capture(tmdb_ids, size):
            captured_size.append(size)
            return {"ok": True, "posters": {str(tmdb_ids[0]): f"http://img/{size}/test.jpg"}}

        self.api.integrations.get_tmdb_posters.side_effect = _capture
        with patch.object(film_support, "_fetch_tmdb_extras") as mock_extras:
            mock_extras.return_value = {"runtime": None, "director": None, "overview": None}
            res = film_support.get_film_full(self.api, "run_test", "r1")
        self.assertTrue(res["ok"])
        # Spec 06 §3.1 : poster TMDb taille w500
        self.assertIn("w500", captured_size)
        self.assertIsNotNone(res["poster_url"])

    def test_no_tmdb_id_skips_extras(self) -> None:
        from cinesort.ui.api import film_support

        # Plan sans candidat -> tmdb_id=0 -> pas d'enrichissement
        _wire_plan(
            self.api,
            [
                {
                    "row_id": "r1",
                    "proposed_title": "Mystery Movie",
                    "proposed_year": 2020,
                    "candidates": [],
                }
            ],
        )
        res = film_support.get_film_full(self.api, "run_test", "r1")
        self.assertTrue(res["ok"])
        self.assertEqual(res["tmdb_id"], 0)
        self.assertIsNone(res["runtime"])
        self.assertIsNone(res["director"])


# ---------------------------------------------------------------------------
# Endpoint exposure : Facades + private impl
# ---------------------------------------------------------------------------


class FacadeExposureTests(unittest.TestCase):
    """Verifie que les 4 endpoints sont exposes via les facades."""

    def test_library_facade_methods_exist(self) -> None:
        from cinesort.ui.api.facades.library_facade import LibraryFacade

        self.assertTrue(hasattr(LibraryFacade, "set_film_tmdb_candidate"))
        self.assertTrue(hasattr(LibraryFacade, "mark_for_deletion"))
        self.assertTrue(hasattr(LibraryFacade, "mark_alert_ignored"))

    def test_run_facade_method_exists(self) -> None:
        from cinesort.ui.api.facades.run_facade import RunFacade

        self.assertTrue(hasattr(RunFacade, "rescan_row"))

    def test_cinesort_api_impl_methods_exist(self) -> None:
        from cinesort.ui.api.cinesort_api import CineSortApi

        self.assertTrue(hasattr(CineSortApi, "_set_film_tmdb_candidate_impl"))
        self.assertTrue(hasattr(CineSortApi, "_mark_for_deletion_impl"))
        self.assertTrue(hasattr(CineSortApi, "_mark_alert_ignored_impl"))
        self.assertTrue(hasattr(CineSortApi, "_rescan_row_impl"))


if __name__ == "__main__":
    unittest.main()
