"""Tests Vague 4 v7.6.0 — Page Film standalone.

Couvre :
- Backend : film_support.get_film_full (run resolve + plan row + probe + perceptual + history + poster)
- Endpoint : cinesort_api.get_film_full expose la fonction
- Composant desktop : film-detail.js (hero + 4 tabs + event binding)
- Router : route /film/:row_id + overlay plein-ecran
- CSS : .v5-film-* classes
- Integration index.html (script charge)
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]


def _make_mock_api():
    # Issue #84 PR 10 : les helpers backend appellent maintenant via les facades
    # (api.settings.get_settings, api.run.get_plan, api.integrations.get_tmdb_posters).
    # On configure les mocks via les facades correspondantes.
    api = MagicMock()
    api.settings.get_settings.return_value = {"state_dir": None, "tmdb_api_key": ""}
    api.run.get_plan.return_value = {
        "ok": True,
        "rows": [
            {
                "row_id": "r1",
                "proposed_title": "Dune",
                "proposed_year": 2021,
                "source_path": "D:/Films/Dune (2021).mkv",
                "size_bytes": 8_000_000_000,
                "candidates": [{"tmdb_id": 438631, "confidence_label": "High"}],
                "edition": None,
            }
        ],
    }
    store = MagicMock()
    store.list_runs.return_value = [{"run_id": "run_1"}]
    store.get_perceptual_report.return_value = {
        "run_id": "run_1",
        "row_id": "r1",
        "global_score": 92,
        "global_tier": "premium",
        "global_score_v2": 92.5,
        "global_tier_v2": "platinum",
        "global_score_v2_payload": {
            "global_score": 92.5,
            "global_tier": "platinum",
            "warnings": ["Dolby Vision Profile 5"],
        },
    }
    store.get_quality_report.return_value = {
        "run_id": "run_1",
        "row_id": "r1",
        "metrics": {
            "video": {"codec": "hevc", "width": 3840, "height": 2160, "has_hdr10": True},
            "audio": [{"codec": "truehd", "channels": 7, "language": "en"}],
            "subtitles": [{"language": "fr", "format": "srt", "external": True}],
            "duration_s": 9330,
            "container_format": "mkv",
        },
    }
    api._get_or_create_infra.return_value = (store, None)
    api.integrations.get_tmdb_posters.return_value = {"ok": True, "posters": {}}
    return api, store


class FilmSupportBackendTests(unittest.TestCase):
    def test_get_film_full_returns_complete_payload(self) -> None:
        from cinesort.ui.api import film_support

        api, _ = _make_mock_api()
        result = film_support.get_film_full(api, "run_1", "r1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["run_id"], "run_1")
        self.assertEqual(result["row_id"], "r1")
        self.assertIn("row", result)
        self.assertIn("probe", result)
        self.assertIn("perceptual", result)
        self.assertIn("history", result)
        self.assertIn("poster_url", result)
        self.assertIn("tmdb_id", result)

    def test_get_film_full_row_details(self) -> None:
        from cinesort.ui.api import film_support

        api, _ = _make_mock_api()
        result = film_support.get_film_full(api, "run_1", "r1")
        self.assertEqual(result["row"]["proposed_title"], "Dune")
        self.assertEqual(result["row"]["proposed_year"], 2021)
        self.assertEqual(result["tmdb_id"], 438631)

    def test_get_film_full_probe_present(self) -> None:
        from cinesort.ui.api import film_support

        api, _ = _make_mock_api()
        result = film_support.get_film_full(api, "run_1", "r1")
        probe = result["probe"]
        self.assertIsNotNone(probe)
        self.assertEqual(probe["video"]["codec"], "hevc")
        self.assertEqual(probe["video"]["width"], 3840)

    def test_get_film_full_perceptual_includes_v2_payload(self) -> None:
        from cinesort.ui.api import film_support

        api, _ = _make_mock_api()
        result = film_support.get_film_full(api, "run_1", "r1")
        perc = result["perceptual"]
        self.assertIsNotNone(perc)
        self.assertIn("global_score_v2", perc)
        gv2 = perc["global_score_v2"]
        self.assertEqual(gv2.get("global_tier"), "platinum")

    def test_get_film_full_unknown_row(self) -> None:
        from cinesort.ui.api import film_support

        api, _ = _make_mock_api()
        result = film_support.get_film_full(api, "run_1", "unknown_row")
        self.assertFalse(result["ok"])
        self.assertIn("introuvable", result.get("message", "").lower())

    def test_get_film_full_no_run(self) -> None:
        from cinesort.ui.api import film_support

        api = MagicMock()
        api.settings.get_settings.return_value = {"state_dir": None}
        store = MagicMock()
        store.list_runs.return_value = []
        api._get_or_create_infra.return_value = (store, None)
        result = film_support.get_film_full(api, None, "r1")
        self.assertFalse(result["ok"])

    def test_get_film_full_resolves_run_id_when_none(self) -> None:
        from cinesort.ui.api import film_support

        api, _ = _make_mock_api()
        result = film_support.get_film_full(api, None, "r1")
        # Le mock doit renvoyer le dernier run
        self.assertTrue(result["ok"])
        self.assertEqual(result["run_id"], "run_1")


class TrifilmsApiEndpointTests(unittest.TestCase):
    def test_get_film_full_endpoint_exposed(self) -> None:
        """Issue #84 PR 10 : get_film_full est sur la LibraryFacade (private impl)."""
        src = (_ROOT / "cinesort" / "ui" / "api" / "cinesort_api.py").read_text(encoding="utf-8")
        # La methode est privatisee : `def _get_film_full_impl(self,...)`
        self.assertIn("def _get_film_full_impl", src)
        self.assertIn("film_support.get_film_full", src)

    def test_film_support_module_imported(self) -> None:
        src = (_ROOT / "cinesort" / "ui" / "api" / "cinesort_api.py").read_text(encoding="utf-8")
        self.assertIn("film_support", src)


class FilmDetailDesktopViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "views" / "film-detail.js").read_text(encoding="utf-8")

    def test_window_film_detail_global(self) -> None:
        # V5bis-06 : la vue est portee en ES module — plus de window.FilmDetail.
        # On verifie a la place les exports ES module attendus.
        self.assertIn("export async function initFilmDetail", self.js)
        self.assertIn("export function mountFilmDetailDrawer", self.js)

    def test_mount_and_unmount_exposed(self) -> None:
        self.assertIn("function mount", self.js)
        self.assertIn("function unmount", self.js)

    def test_uses_get_film_full_endpoint(self) -> None:
        self.assertIn("get_film_full", self.js)

    def test_4_tabs_defined(self) -> None:
        for tab_id in ("overview", "analysis", "history", "comparison"):
            self.assertIn(f'"{tab_id}"', self.js)

    def test_hero_uses_score_v2_if_available(self) -> None:
        self.assertIn("window.ScoreV2", self.js)
        self.assertIn("scoreCircleHtml", self.js)

    def test_analysis_tab_uses_renderScoreV2Container(self) -> None:
        self.assertIn("renderScoreV2Container", self.js)
        self.assertIn("bindScoreV2Events", self.js)

    def test_hero_has_back_button(self) -> None:
        self.assertIn("data-v5-film-back", self.js)

    def test_keyboard_arrow_navigation_between_tabs(self) -> None:
        self.assertIn("ArrowRight", self.js)
        self.assertIn("ArrowLeft", self.js)

    def test_rescan_action_binding(self) -> None:
        self.assertIn("analyze_perceptual_single", self.js)
        self.assertIn("data-v5-film-rescan", self.js)


class RouterFilmRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "core" / "router.js").read_text(encoding="utf-8")

    def test_film_route_prefix_detected(self) -> None:
        self.assertIn('view.startsWith("film/")', self.js)

    def test_navigate_to_film_helper(self) -> None:
        self.assertIn("_navigateToFilm", self.js)
        self.assertIn("_hideFilmDetailOverlay", self.js)

    def test_film_overlay_ensure(self) -> None:
        self.assertIn("_ensureFilmDetailOverlay", self.js)
        self.assertIn("film-detail-overlay", self.js)

    def test_film_overlay_hidden_on_other_views(self) -> None:
        # Appel _hideFilmDetailOverlay() dans navigateTo pour nettoyer l'overlay
        self.assertIn("_hideFilmDetailOverlay()", self.js)

    def test_film_mount_calls_film_detail(self) -> None:
        self.assertIn("window.FilmDetail", self.js)
        self.assertIn("FilmDetail.mount", self.js)


class CssVague4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")

    def test_film_overlay_classes(self) -> None:
        self.assertIn(".v5-film-overlay", self.css)
        self.assertIn(".v5-film-overlay.is-active", self.css)

    def test_film_hero_classes(self) -> None:
        for cls in (
            ".v5-film-hero",
            ".v5-film-hero-backdrop",
            ".v5-film-hero-body",
            ".v5-film-poster",
            ".v5-film-title",
            ".v5-film-year",
            ".v5-film-meta-row",
            ".v5-film-hero-actions",
            ".v5-film-back",
        ):
            self.assertIn(cls, self.css)

    def test_film_tabs_classes(self) -> None:
        for cls in (
            ".v5-film-tabs",
            ".v5-film-tab",
            ".v5-film-tab.is-active",
            ".v5-film-tab-panel",
            ".v5-film-tabs-wrap",
        ):
            self.assertIn(cls, self.css)

    def test_film_overview_classes(self) -> None:
        for cls in (".v5-film-overview", ".v5-film-section", ".v5-film-section-title", ".v5-film-data-list"):
            self.assertIn(cls, self.css)

    def test_film_timeline_classes(self) -> None:
        for cls in (
            ".v5-film-timeline",
            ".v5-film-timeline-event",
            ".v5-film-timeline-dot",
            ".v5-film-timeline-content",
        ):
            self.assertIn(cls, self.css)

    def test_film_timeline_dot_types(self) -> None:
        for t in ("scan", "score", "apply", "error"):
            self.assertIn(f".v5-film-timeline-dot--{t}", self.css)

    def test_backdrop_blur_effect(self) -> None:
        # Hero backdrop : blur + scale
        self.assertIn("filter: blur", self.css)


class IntegrationVague4Tests(unittest.TestCase):
    def test_index_html_loads_film_detail_script(self) -> None:
        html = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("film-detail.js", html)


if __name__ == "__main__":
    unittest.main()
