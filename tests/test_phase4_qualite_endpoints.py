"""Tests Phase 4 — Vue Qualite backend endpoints (spec 10).

Endpoints testes :
    - quality/get_films_by_tier("reject", limit=8)
    - library/get_incomplete_sagas()
    - library/get_films_by_decade(filters)
    - quality/get_history(period_days)
    - quality/recompute_all_scores() + get_recompute_job_status(job_id)

Cf docs/internal/design/refonte_2026_05_17/screens/10-qualite.md
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from cinesort.ui.api.library_audit_support import (
    _decade_from_year,
    compute_by_decade,
    get_films_by_decade,
    get_incomplete_sagas,
)
from cinesort.ui.api.quality_audit_support import (
    _RECOMPUTE_JOBS,
    _RECOMPUTE_JOBS_LOCK,
    get_films_by_tier,
    get_history,
    get_recompute_job_status,
    recompute_all_scores,
)


def _build_mock_api(rows=None, runs=None, perceptual_trend=None, tier_counts=None, plan_rows=None):
    """Construit un mock CineSortApi pour les tests."""
    api = MagicMock()
    api.settings.get_settings.return_value = {"state_dir": "/tmp/test"}

    store = MagicMock()
    api._get_or_create_infra.return_value = (store, None)
    store.run.list_runs.return_value = runs if runs is not None else [{"run_id": "run-test-1"}]
    store.perceptual.get_global_score_v2_trend.return_value = perceptual_trend or []
    store.perceptual.count_v2_tier_since.return_value = (tier_counts or {}).get("default", 0)

    # Plan mock
    if plan_rows is not None:
        api.run.get_plan.return_value = {"ok": True, "rows": plan_rows}
    else:
        api.run.get_plan.return_value = {"ok": True, "rows": rows or []}

    return api, store


# ---------------------------------------------------------------------------
# get_films_by_tier
# ---------------------------------------------------------------------------


class GetFilmsByTierTests(unittest.TestCase):
    def test_invalid_tier_returns_error(self):
        api, _ = _build_mock_api()
        result = get_films_by_tier(api, "INVALID_TIER")
        self.assertFalse(result["ok"])

    def test_no_run_returns_empty(self):
        api, _ = _build_mock_api(runs=[])
        result = get_films_by_tier(api, "reject")
        self.assertTrue(result["ok"])
        self.assertEqual(result["films"], [])
        self.assertEqual(result["total"], 0)
        self.assertIsNone(result["run_id"])

    @patch("cinesort.ui.api.library_support._build_library_rows")
    def test_reject_sorted_by_score_ascending(self, mock_build):
        api, _ = _build_mock_api()
        mock_build.return_value = [
            {
                "row_id": "r1",
                "title": "Mediocre",
                "year": 2000,
                "tier_v2": "reject",
                "score_v2": 35,
                "poster_url": "p1",
                "warnings": [],
            },
            {
                "row_id": "r2",
                "title": "Tres mauvais",
                "year": 1995,
                "tier_v2": "reject",
                "score_v2": 12,
                "poster_url": "p2",
                "warnings": ["dnr_partial"],
            },
            {
                "row_id": "r3",
                "title": "Bon film",
                "year": 2010,
                "tier_v2": "gold",
                "score_v2": 88,
                "poster_url": "p3",
                "warnings": [],
            },
            {
                "row_id": "r4",
                "title": "Mauvais",
                "year": 1980,
                "tier_v2": "reject",
                "score_v2": 28,
                "poster_url": "p4",
                "warnings": [],
            },
        ]
        result = get_films_by_tier(api, "reject", limit=8)
        self.assertTrue(result["ok"])
        self.assertEqual(result["tier"], "reject")
        self.assertEqual(len(result["films"]), 3)  # 3 reject films
        # Ordre asc : le pire (12) en premier
        self.assertEqual(result["films"][0]["score_v2"], 12)
        self.assertEqual(result["films"][1]["score_v2"], 28)
        self.assertEqual(result["films"][2]["score_v2"], 35)
        # Champs presents
        for f in result["films"]:
            self.assertIn("row_id", f)
            self.assertIn("title", f)
            self.assertIn("year", f)
            self.assertIn("score_v2", f)
            self.assertIn("tier", f)
            self.assertIn("poster_url", f)
            self.assertIn("warnings", f)

    @patch("cinesort.ui.api.library_support._build_library_rows")
    def test_limit_caps_results_at_8(self, mock_build):
        api, _ = _build_mock_api()
        # 15 films reject
        mock_build.return_value = [
            {
                "row_id": f"r{i}",
                "title": f"Film{i}",
                "year": 2000,
                "tier_v2": "reject",
                "score_v2": i,
                "poster_url": None,
                "warnings": [],
            }
            for i in range(15)
        ]
        result = get_films_by_tier(api, "reject", limit=8)
        self.assertEqual(len(result["films"]), 8)
        self.assertEqual(result["total"], 15)  # total non-paginated

    @patch("cinesort.ui.api.library_support._build_library_rows")
    def test_platinum_sorted_descending(self, mock_build):
        api, _ = _build_mock_api()
        mock_build.return_value = [
            {
                "row_id": "r1",
                "title": "A",
                "year": 2020,
                "tier_v2": "platinum",
                "score_v2": 92,
                "poster_url": None,
                "warnings": [],
            },
            {
                "row_id": "r2",
                "title": "B",
                "year": 2021,
                "tier_v2": "platinum",
                "score_v2": 98,
                "poster_url": None,
                "warnings": [],
            },
        ]
        result = get_films_by_tier(api, "platinum", limit=5)
        self.assertEqual(result["films"][0]["score_v2"], 98)
        self.assertEqual(result["films"][1]["score_v2"], 92)


# ---------------------------------------------------------------------------
# get_films_by_decade
# ---------------------------------------------------------------------------


class DecadeFromYearTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_decade_from_year(1995), "1990")
        self.assertEqual(_decade_from_year(2024), "2020")
        self.assertEqual(_decade_from_year(2000), "2000")

    def test_invalid(self):
        self.assertIsNone(_decade_from_year(0))
        self.assertIsNone(_decade_from_year(1500))
        self.assertIsNone(_decade_from_year(2200))


class GetFilmsByDecadeTests(unittest.TestCase):
    def test_no_run_returns_empty(self):
        api, _ = _build_mock_api(runs=[])
        result = get_films_by_decade(api)
        self.assertTrue(result["ok"])
        self.assertEqual(result["by_decade"], {})
        self.assertEqual(result["total"], 0)

    @patch("cinesort.ui.api.library_support._build_library_rows")
    def test_distribution_basic(self, mock_build):
        api, _ = _build_mock_api()
        mock_build.return_value = [
            {"row_id": "r1", "year": 1995, "title": "A", "tier_v2": "gold"},
            {"row_id": "r2", "year": 1996, "title": "B", "tier_v2": "silver"},
            {"row_id": "r3", "year": 2024, "title": "C", "tier_v2": "platinum"},
            {"row_id": "r4", "year": 2023, "title": "D", "tier_v2": "gold"},
            {"row_id": "r5", "year": 1985, "title": "E", "tier_v2": "bronze"},
            {"row_id": "r6", "year": 0, "title": "F", "tier_v2": "unknown"},  # ignored
        ]
        result = get_films_by_decade(api)
        self.assertTrue(result["ok"])
        self.assertEqual(result["by_decade"]["1980"], 1)
        self.assertEqual(result["by_decade"]["1990"], 2)
        self.assertEqual(result["by_decade"]["2020"], 2)
        self.assertEqual(result["total"], 5)

    @patch("cinesort.ui.api.library_support._build_library_rows")
    def test_compute_by_decade_helper(self, mock_build):
        api, _ = _build_mock_api()
        mock_build.return_value = [
            {"row_id": "r1", "year": 1995, "title": "A"},
            {"row_id": "r2", "year": 2010, "title": "B"},
        ]
        dist = compute_by_decade(api)
        self.assertEqual(dist, {"1990": 1, "2010": 1})


# ---------------------------------------------------------------------------
# get_incomplete_sagas
# ---------------------------------------------------------------------------


class GetIncompleteSagasTests(unittest.TestCase):
    def test_no_run_returns_empty(self):
        api, _ = _build_mock_api(runs=[])
        result = get_incomplete_sagas(api)
        self.assertTrue(result["ok"])
        self.assertEqual(result["sagas"], [])
        self.assertEqual(result["total"], 0)

    @patch("cinesort.ui.api.library_audit_support._fetch_collection_parts")
    def test_incomplete_saga_detected(self, mock_parts):
        api, _ = _build_mock_api(
            plan_rows=[
                {
                    "row_id": "r1",
                    "proposed_title": "Die Hard",
                    "proposed_year": 1988,
                    "tmdb_id": 562,
                    "tmdb_collection_id": 1570,
                    "tmdb_collection_name": "Die Hard Collection",
                },
                {
                    "row_id": "r2",
                    "proposed_title": "Die Hard 2",
                    "proposed_year": 1990,
                    "tmdb_id": 1573,
                    "tmdb_collection_id": 1570,
                    "tmdb_collection_name": "Die Hard Collection",
                },
            ]
        )
        # TMDb collection contient 5 films, on en possede 2
        mock_parts.return_value = [
            {"tmdb_id": 562, "title": "Die Hard", "year": 1988},
            {"tmdb_id": 1573, "title": "Die Hard 2", "year": 1990},
            {"tmdb_id": 1571, "title": "Die Hard with a Vengeance", "year": 1995},
            {"tmdb_id": 1572, "title": "Live Free or Die Hard", "year": 2007},
            {"tmdb_id": 1574, "title": "A Good Day to Die Hard", "year": 2013},
        ]
        result = get_incomplete_sagas(api)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["sagas"]), 1)
        saga = result["sagas"][0]
        self.assertEqual(saga["collection_id"], 1570)
        self.assertEqual(saga["name"], "Die Hard Collection")
        self.assertEqual(saga["total_films_in_collection"], 5)
        self.assertEqual(saga["owned_count"], 2)
        self.assertEqual(saga["missing_count"], 3)
        self.assertEqual(len(saga["missing_films"]), 3)
        missing_ids = {f["tmdb_id"] for f in saga["missing_films"]}
        self.assertIn(1571, missing_ids)

    @patch("cinesort.ui.api.library_audit_support._fetch_collection_parts")
    def test_complete_saga_not_returned(self, mock_parts):
        api, _ = _build_mock_api(
            plan_rows=[
                {
                    "row_id": "r1",
                    "proposed_title": "A",
                    "proposed_year": 2000,
                    "tmdb_id": 1,
                    "tmdb_collection_id": 100,
                    "tmdb_collection_name": "X Collection",
                },
                {
                    "row_id": "r2",
                    "proposed_title": "B",
                    "proposed_year": 2002,
                    "tmdb_id": 2,
                    "tmdb_collection_id": 100,
                    "tmdb_collection_name": "X Collection",
                },
            ]
        )
        mock_parts.return_value = [
            {"tmdb_id": 1, "title": "A", "year": 2000},
            {"tmdb_id": 2, "title": "B", "year": 2002},
        ]
        result = get_incomplete_sagas(api)
        self.assertEqual(result["sagas"], [])

    @patch("cinesort.ui.api.library_audit_support._fetch_collection_parts")
    def test_tmdb_fetch_failure_skipped(self, mock_parts):
        api, _ = _build_mock_api(
            plan_rows=[
                {
                    "row_id": "r1",
                    "proposed_title": "A",
                    "proposed_year": 2000,
                    "tmdb_id": 1,
                    "tmdb_collection_id": 100,
                    "tmdb_collection_name": "X",
                },
            ]
        )
        mock_parts.return_value = None  # echec reseau
        result = get_incomplete_sagas(api)
        self.assertEqual(result["sagas"], [])

    def test_film_without_collection_ignored(self):
        api, _ = _build_mock_api(
            plan_rows=[
                {
                    "row_id": "r1",
                    "proposed_title": "Stand-alone",
                    "proposed_year": 2020,
                    "tmdb_id": 999,
                    "tmdb_collection_id": None,
                    "tmdb_collection_name": None,
                },
            ]
        )
        result = get_incomplete_sagas(api)
        self.assertEqual(result["sagas"], [])


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------


class GetHistoryTests(unittest.TestCase):
    def test_30_days_returns_31_points(self):
        # period_days=30 -> 31 points (jour 0 .. jour 30)
        api, _ = _build_mock_api(perceptual_trend=[])
        result = get_history(api, period_days=30)
        self.assertTrue(result["ok"])
        self.assertEqual(result["period_days"], 30)
        self.assertEqual(len(result["points"]), 31)

    def test_7_days_returns_8_points(self):
        api, _ = _build_mock_api(perceptual_trend=[])
        result = get_history(api, period_days=7)
        self.assertEqual(len(result["points"]), 8)

    def test_point_structure(self):
        api, _ = _build_mock_api(perceptual_trend=[])
        result = get_history(api, period_days=5)
        for point in result["points"]:
            self.assertIn("date", point)
            self.assertIn("avg_score", point)
            self.assertIn("count_films", point)
            self.assertIn("count_reject", point)
            self.assertIn("count_subs_missing", point)

    def test_with_data_calculates_deltas(self):
        # Construire des points pour les 30 derniers jours :
        # Moitie ancienne avg=50, moitie recente avg=70 -> delta_score = +20
        today = time.time()
        trend_data = []
        for i in range(30):
            ts = today - (29 - i) * 86400
            date_str = time.strftime("%Y-%m-%d", time.localtime(ts))
            avg = 50.0 if i < 15 else 70.0
            trend_data.append({"date": date_str, "avg_score": avg, "count": 10})

        api, _ = _build_mock_api(perceptual_trend=trend_data)
        result = get_history(api, period_days=29)
        self.assertTrue(result["ok"])
        # Delta doit etre positif (recent meilleur que older)
        self.assertGreater(result["delta_score"], 0)

    def test_period_clamped_when_zero(self):
        api, _ = _build_mock_api(perceptual_trend=[])
        result = get_history(api, period_days=0)
        # 0 = all -> traduit en 365j
        self.assertEqual(result["period_days"], 365)

    def test_delta_films_nul_sur_activite_parfaitement_stable(self):
        """Audit 2026-08-08 — les deux moities comparees doivent avoir la MEME taille.

        `points` compte `period + 1` entrees (bornes incluses), donc un nombre
        IMPAIR des que `period` est pair — c'est le cas des boutons « 30j » et
        « 90j », dont le premier est le defaut. `points[half:]` prenait alors 16
        jours contre 15 pour `points[:half]`, et `delta_films` est une SOMME, pas
        une moyenne : sur une bibliotheque ou l'on ajoute exactement le meme
        nombre de films chaque jour, l'ecart affiche valait un jour d'ajouts
        entier. L'UI (`qualite.js`) le rend en 📈, donc une hausse permanente qui
        ne mesurait que l'asymetrie de la coupe.

        Le score, lui, est une MOYENNE : il ne portait pas ce biais. C'est
        `count_films` qui revele le defaut, d'ou ce cas dedie.
        """
        today = time.time()
        # 31 jours de donnees identiques : meme score, meme nombre de films.
        trend_data = [
            {
                "date": time.strftime("%Y-%m-%d", time.localtime(today - day * 86400)),
                "avg_score": 60.0,
                "count": 10,
            }
            for day in range(31)
        ]
        api, _ = _build_mock_api(perceptual_trend=trend_data)
        result = get_history(api, period_days=30)

        self.assertEqual(len(result["points"]), 31, "le contrat de l'endpoint ne change pas")
        self.assertEqual(
            result["delta_films"],
            0,
            "activite strictement constante -> aucune tendance ; valait +10 (un jour d'ajouts) "
            "quand la moitie recente comptait 16 jours contre 15",
        )
        self.assertEqual(result["delta_score"], 0.0)


# ---------------------------------------------------------------------------
# recompute_all_scores + get_recompute_job_status
# ---------------------------------------------------------------------------


class RecomputeAllScoresTests(unittest.TestCase):
    def setUp(self):
        # Nettoyer le registry global entre tests
        with _RECOMPUTE_JOBS_LOCK:
            _RECOMPUTE_JOBS.clear()

    def test_no_run_returns_error(self):
        api, _ = _build_mock_api(runs=[])
        result = recompute_all_scores(api)
        self.assertFalse(result["ok"])

    def test_launches_job_with_id(self):
        api, _ = _build_mock_api(
            plan_rows=[
                {"row_id": "r1", "proposed_title": "A", "proposed_year": 2000},
                {"row_id": "r2", "proposed_title": "B", "proposed_year": 2001},
                {"row_id": "r3", "proposed_title": "C", "proposed_year": 2002},
            ]
        )
        # Mock le call quality pour eviter la vraie execution
        api.quality.get_quality_report.return_value = {"ok": True, "score": 50, "tier": "silver"}

        result = recompute_all_scores(api)
        self.assertTrue(result["ok"])
        self.assertIn("job_id", result)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["run_id"], "run-test-1")
        self.assertTrue(result["job_id"].startswith("recompute_"))

    def test_empty_plan_returns_error(self):
        api, _ = _build_mock_api(plan_rows=[])
        result = recompute_all_scores(api)
        self.assertFalse(result["ok"])

    def test_get_status_unknown_job(self):
        api, _ = _build_mock_api()
        result = get_recompute_job_status(api, "unknown_job_xyz")
        self.assertFalse(result["ok"])

    def test_get_status_empty_job_id(self):
        api, _ = _build_mock_api()
        result = get_recompute_job_status(api, "")
        self.assertFalse(result["ok"])

    def test_job_lifecycle(self):
        """Lance un job, polle son status, attend completion."""
        api, _ = _build_mock_api(
            plan_rows=[
                {"row_id": "r1", "proposed_title": "A", "proposed_year": 2000},
            ]
        )
        api.quality.get_quality_report.return_value = {"ok": True, "score": 50, "tier": "silver"}

        result = recompute_all_scores(api)
        self.assertTrue(result["ok"])
        job_id = result["job_id"]

        # Polling : attendre que le job termine (max 5s)
        deadline = time.time() + 5.0
        final_status = None
        while time.time() < deadline:
            status = get_recompute_job_status(api, job_id)
            self.assertTrue(status["ok"])
            self.assertEqual(status["job_id"], job_id)
            if status.get("status") in ("done", "failed", "cancelled"):
                final_status = status
                break
            time.sleep(0.05)

        self.assertIsNotNone(final_status, "Job didn't finish in time")
        self.assertEqual(final_status["status"], "done")
        self.assertEqual(final_status["progress"], 1)
        self.assertEqual(final_status["total"], 1)


if __name__ == "__main__":
    unittest.main()
