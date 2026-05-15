"""Tests Vague 7 v7.6.0 — Qualite / Integrations / Journal refondues."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]


class ScoringRollupBackendTests(unittest.TestCase):
    def _make_api(self):
        api = MagicMock()
        api.settings.get_settings.return_value = {"state_dir": None}
        api.run.get_plan.return_value = {
            "ok": True,
            "rows": [
                {
                    "row_id": "f1",
                    "proposed_title": "Dune",
                    "proposed_year": 2021,
                    "tmdb_collection_name": "Dune Saga",
                    "mtime": 0,
                },
                {
                    "row_id": "f2",
                    "proposed_title": "Dune Part Two",
                    "proposed_year": 2024,
                    "tmdb_collection_name": "Dune Saga",
                    "mtime": 0,
                },
                {
                    "row_id": "f3",
                    "proposed_title": "Blade Runner 2049",
                    "proposed_year": 2017,
                    "tmdb_collection_name": "Blade Runner",
                    "mtime": 0,
                },
                {"row_id": "f4", "proposed_title": "Tenet", "proposed_year": 2020, "mtime": 0},
            ],
        }
        store = MagicMock()
        store.list_runs.return_value = [{"run_id": "r1"}]
        store.list_perceptual_reports.return_value = [
            {
                "row_id": "f1",
                "global_tier_v2": "platinum",
                "global_score_v2": 92,
                "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
            },
            {
                "row_id": "f2",
                "global_tier_v2": "platinum",
                "global_score_v2": 94,
                "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
            },
            {
                "row_id": "f3",
                "global_tier_v2": "gold",
                "global_score_v2": 85,
                "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
            },
            {
                "row_id": "f4",
                "global_tier_v2": "gold",
                "global_score_v2": 80,
                "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
            },
        ]
        store.list_quality_reports.return_value = [
            {
                "row_id": "f1",
                "metrics": {"video": {"codec": "hevc", "width": 3840, "height": 2160}, "audio": [], "duration_s": 9000},
            },
            {
                "row_id": "f2",
                "metrics": {"video": {"codec": "hevc", "width": 3840, "height": 2160}, "audio": [], "duration_s": 9600},
            },
            {
                "row_id": "f3",
                "metrics": {"video": {"codec": "av1", "width": 3840, "height": 2160}, "audio": [], "duration_s": 9900},
            },
            {
                "row_id": "f4",
                "metrics": {"video": {"codec": "hevc", "width": 1920, "height": 1080}, "audio": [], "duration_s": 9100},
            },
        ]
        api._get_or_create_infra.return_value = (store, None)
        return api

    def test_rollup_by_franchise(self) -> None:
        from cinesort.ui.api import library_support

        api = self._make_api()
        result = library_support.get_scoring_rollup(api, by="franchise", run_id="r1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["by"], "franchise")
        names = [g["group_name"] for g in result["groups"]]
        self.assertIn("Dune Saga", names)
        self.assertIn("Blade Runner", names)

    def test_rollup_by_decade(self) -> None:
        from cinesort.ui.api import library_support

        api = self._make_api()
        result = library_support.get_scoring_rollup(api, by="decade", run_id="r1")
        names = [g["group_name"] for g in result["groups"]]
        # Dune 2021 + 2024 = 2020s, Blade Runner 2017 + Tenet 2020 = 2010s + 2020s
        self.assertIn("2020s", names)
        self.assertIn("2010s", names)

    def test_rollup_by_codec(self) -> None:
        from cinesort.ui.api import library_support

        api = self._make_api()
        result = library_support.get_scoring_rollup(api, by="codec", run_id="r1")
        names = [g["group_name"] for g in result["groups"]]
        self.assertIn("HEVC", names)
        self.assertIn("AV1", names)

    def test_rollup_aggregates_avg_score_and_tier_distribution(self) -> None:
        from cinesort.ui.api import library_support

        api = self._make_api()
        result = library_support.get_scoring_rollup(api, by="franchise", run_id="r1")
        dune = next((g for g in result["groups"] if g["group_name"] == "Dune Saga"), None)
        self.assertIsNotNone(dune)
        self.assertEqual(dune["count"], 2)
        self.assertEqual(dune["tier_distribution"]["platinum"], 2)
        # Moyenne des scores : (92 + 94) / 2 = 93
        self.assertAlmostEqual(dune["avg_score"], 93.0, places=0)

    def test_rollup_limits(self) -> None:
        from cinesort.ui.api import library_support

        api = self._make_api()
        result = library_support.get_scoring_rollup(api, by="franchise", run_id="r1", limit=1)
        self.assertLessEqual(len(result["groups"]), 1)

    def test_rollup_no_run(self) -> None:
        from cinesort.ui.api import library_support

        api = MagicMock()
        store = MagicMock()
        store.list_runs.return_value = []
        api.settings.get_settings.return_value = {"state_dir": None}
        api._get_or_create_infra.return_value = (store, None)
        result = library_support.get_scoring_rollup(api, by="franchise")
        self.assertEqual(result["groups"], [])


class TrifilmsApiRollupEndpointTests(unittest.TestCase):
    def test_get_scoring_rollup_endpoint_exposed(self) -> None:
        src = (_ROOT / "cinesort" / "ui" / "api" / "cinesort_api.py").read_text(encoding="utf-8")
        self.assertIn("def _get_scoring_rollup_impl", src)
        self.assertIn("library_support.get_scoring_rollup", src)


class QIJViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "views" / "qij-v5.js").read_text(encoding="utf-8")

    def test_three_global_views(self) -> None:
        # V5bis-03 : IIFE globals retires, remplaces par ES module exports.
        self.assertIn("export async function initQuality", self.js)
        self.assertIn("export async function initIntegrations", self.js)
        self.assertIn("export async function initJournal", self.js)

    def test_each_view_has_mount_unmount(self) -> None:
        # V5bis-03 : conventions ES module (initX / unmountX).
        for fn in (
            "initQuality",
            "unmountQuality",
            "initIntegrations",
            "unmountIntegrations",
            "initJournal",
            "unmountJournal",
        ):
            self.assertIn(fn, self.js)

    def test_quality_uses_charts_components(self) -> None:
        self.assertIn("window.HomeCharts", self.js)
        self.assertIn("renderDonut", self.js)
        self.assertIn("renderLine", self.js)

    def test_quality_rollup_5_dimensions(self) -> None:
        for d in ("franchise", "decade", "codec", "era_grain", "resolution"):
            self.assertIn(f'"{d}"', self.js)

    def test_integrations_4_services(self) -> None:
        for svc in ("jellyfin", "plex", "radarr", "tmdb"):
            self.assertIn(f'id: "{svc}"', self.js)

    def test_integration_test_methods(self) -> None:
        for m in ("test_jellyfin_connection", "test_plex_connection", "test_radarr_connection"):
            self.assertIn(m, self.js)

    def test_journal_uses_export_run_report(self) -> None:
        self.assertIn("export_run_report", self.js)

    def test_journal_status_classes(self) -> None:
        for s in ("is-done", "is-error", "is-cancelled", "is-running"):
            self.assertIn(s, self.js)

    def test_quality_uses_get_scoring_rollup(self) -> None:
        self.assertIn("get_scoring_rollup", self.js)


class RouterQIJTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "core" / "router.js").read_text(encoding="utf-8")

    def test_aliases_empty(self) -> None:
        # Les alias transitoires ont ete retires
        self.assertIn("ROUTE_ALIASES = {}", self.js)

    def test_qij_routes_detected(self) -> None:
        for route in ("quality-v5", "integrations-v5", "journal-v5", "integrations", "journal"):
            self.assertIn(f'"{route}"', self.js)

    def test_navigate_to_qij_helper(self) -> None:
        self.assertIn("_navigateToQIJ", self.js)
        self.assertIn("_hideQIJOverlay", self.js)
        self.assertIn("_ensureQIJOverlay", self.js)

    def test_qij_overlay_id(self) -> None:
        self.assertIn("qij-v5-overlay", self.js)

    def test_mutual_exclusion_with_other_overlays(self) -> None:
        # Navigate to QIJ doit masquer les autres
        self.assertRegex(self.js, r"_navigateToQIJ[\s\S]*?_hideSettingsV5Overlay")
        self.assertRegex(self.js, r"_navigateToQIJ[\s\S]*?_hideProcessingOverlay")


class CssVague7Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")

    def test_qij_shell_classes(self) -> None:
        for cls in (".v5-qij-overlay", ".v5-qij-shell", ".v5-qij-header", ".v5-qij-title", ".v5-qij-section-title"):
            self.assertIn(cls, self.css)

    def test_qij_charts_classes(self) -> None:
        for cls in (".v5-qij-charts", ".v5-qij-chart-wrap"):
            self.assertIn(cls, self.css)

    def test_qij_rollup_classes(self) -> None:
        for cls in (
            ".v5-qij-rollup",
            ".v5-qij-rollup-header",
            ".v5-qij-rollup-wrap",
            ".v5-qij-dist-bar",
            ".v5-qij-dist-seg",
        ):
            self.assertIn(cls, self.css)

    def test_qij_dist_tier_variants(self) -> None:
        for t in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f".v5-qij-dist-seg--{t}", self.css)

    def test_integ_card_classes(self) -> None:
        for cls in (
            ".v5-integ-grid",
            ".v5-integ-card",
            ".v5-integ-card-header",
            ".v5-integ-card-status",
            ".v5-integ-card-footer",
        ):
            self.assertIn(cls, self.css)

    def test_integ_card_state_variants(self) -> None:
        for state in ("is-connected", "is-error", "is-ready", "is-disabled"):
            self.assertIn(f".v5-integ-card.{state}", self.css)

    def test_journal_classes(self) -> None:
        for cls in (
            ".v5-qij-journal-list",
            ".v5-qij-journal-card",
            ".v5-qij-journal-header",
            ".v5-qij-journal-id",
            ".v5-qij-journal-kpis",
            ".v5-qij-journal-actions",
        ):
            self.assertIn(cls, self.css)


class IntegrationVague7Tests(unittest.TestCase):
    def test_index_html_loads_qij_script(self) -> None:
        html = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("qij-v5.js", html)


if __name__ == "__main__":
    unittest.main()
