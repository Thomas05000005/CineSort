"""Tests Vague 3 v7.6.0 — Library / Explorer.

Couvre :
- Backend : library_support (filtrage, sort, pagination, smart playlists)
- Endpoints : get_library_filtered, get_smart_playlists, save_smart_playlist, delete_smart_playlist
- Composants desktop IIFE : library-components.js (4 renderers + FILTER_DIMENSIONS)
- Version ES module dashboard equivalente
- CSS Vague 3 (library shell, filters, poster grid, smart playlists)
- Integration index.html + router
- view library-v5.js (orchestrateur)
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]


def _make_mock_api_with_rows():
    """Mock api avec 5 films couvrant differents tiers / codecs / HDR."""
    api = MagicMock()
    rows = [
        {"row_id": "f1", "proposed_title": "Dune", "proposed_year": 2021, "mtime": 1700000000},
        {"row_id": "f2", "proposed_title": "Tenet", "proposed_year": 2020, "mtime": 1700000000},
        {"row_id": "f3", "proposed_title": "Inception", "proposed_year": 2010, "mtime": 1700000000},
        {"row_id": "f4", "proposed_title": "Matrix", "proposed_year": 1999, "mtime": 1700000000},
        {"row_id": "f5", "proposed_title": "Old Movie", "proposed_year": 1995, "mtime": 1700000000},
    ]
    api.get_plan.return_value = {"ok": True, "rows": rows}
    api.get_settings.return_value = {"state_dir": None, "smart_playlists": []}

    # Mock store + _get_or_create_infra
    store = MagicMock()
    store.list_perceptual_reports.return_value = [
        {
            "row_id": "f1",
            "global_tier_v2": "platinum",
            "global_score_v2": 92,
            "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
        },
        {
            "row_id": "f2",
            "global_tier_v2": "gold",
            "global_score_v2": 85,
            "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
        },
        {
            "row_id": "f3",
            "global_tier_v2": "gold",
            "global_score_v2": 82,
            "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
        },
        {
            "row_id": "f4",
            "global_tier_v2": "silver",
            "global_score_v2": 70,
            "global_score_v2_payload": {"warnings": [], "adjustments_applied": ["dnr_partial"]},
        },
        {
            "row_id": "f5",
            "global_tier_v2": "reject",
            "global_score_v2": 40,
            "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
        },
    ]
    store.list_quality_reports.return_value = [
        {
            "row_id": "f1",
            "metrics": {
                "video": {
                    "codec": "hevc",
                    "width": 3840,
                    "height": 2160,
                    "has_hdr10": True,
                    "has_dv": True,
                    "dv_profile": "8.1",
                },
                "audio": [],
                "duration_s": 9000,
            },
        },
        {
            "row_id": "f2",
            "metrics": {
                "video": {"codec": "av1", "width": 3840, "height": 2160, "has_hdr10_plus": True},
                "audio": [],
                "duration_s": 9100,
            },
        },
        {
            "row_id": "f3",
            "metrics": {
                "video": {"codec": "hevc", "width": 1920, "height": 1080},
                "audio": [],
                "duration_s": 8500,
            },
        },
        {
            "row_id": "f4",
            "metrics": {
                "video": {"codec": "h264", "width": 1920, "height": 1080},
                "audio": [],
                "duration_s": 8200,
            },
        },
        {
            "row_id": "f5",
            "metrics": {
                "video": {"codec": "mpeg2", "width": 720, "height": 480},
                "audio": [],
                "duration_s": 7000,
            },
        },
    ]
    store.list_runs.return_value = [{"run_id": "r1"}]
    api._get_or_create_infra.return_value = (store, None)
    return api


class LibrarySupportFilteringTests(unittest.TestCase):
    def test_get_library_filtered_returns_all_rows_no_filter(self) -> None:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows()
        res = library_support.get_library_filtered(api, run_id="r1")
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 5)
        self.assertEqual(len(res["rows"]), 5)

    def test_filter_by_tier_v2(self) -> None:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows()
        res = library_support.get_library_filtered(api, "r1", {"tier_v2": ["gold"]})
        self.assertEqual(res["total"], 2)
        for r in res["rows"]:
            self.assertEqual(r["tier_v2"], "gold")

    def test_filter_by_codec(self) -> None:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows()
        res = library_support.get_library_filtered(api, "r1", {"codec": ["hevc"]})
        self.assertEqual(res["total"], 2)

    def test_filter_by_resolution(self) -> None:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows()
        res = library_support.get_library_filtered(api, "r1", {"resolution": ["4k"]})
        self.assertEqual(res["total"], 2)

    def test_filter_by_hdr(self) -> None:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows()
        res = library_support.get_library_filtered(api, "r1", {"hdr": ["hdr10_plus"]})
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["rows"][0]["row_id"], "f2")

    def test_filter_by_warnings_dnr_partial(self) -> None:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows()
        res = library_support.get_library_filtered(api, "r1", {"warnings": ["dnr_partial"]})
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["rows"][0]["row_id"], "f4")

    def test_filter_search_text(self) -> None:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows()
        res = library_support.get_library_filtered(api, "r1", {"search": "dune"})
        self.assertEqual(res["total"], 1)

    def test_filter_year_range(self) -> None:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows()
        res = library_support.get_library_filtered(api, "r1", {"year_min": 2015, "year_max": 2025})
        self.assertEqual(res["total"], 2)  # Dune 2021 + Tenet 2020

    def test_sort_score_desc(self) -> None:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows()
        res = library_support.get_library_filtered(api, "r1", sort="score_desc")
        scores = [r["score_v2"] for r in res["rows"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_sort_title_ascending(self) -> None:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows()
        res = library_support.get_library_filtered(api, "r1", sort="title")
        titles = [r["title"].lower() for r in res["rows"]]
        self.assertEqual(titles, sorted(titles))

    def test_pagination(self) -> None:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows()
        res = library_support.get_library_filtered(api, "r1", page=1, page_size=2)
        self.assertEqual(len(res["rows"]), 2)
        self.assertEqual(res["pages"], 3)
        self.assertEqual(res["total"], 5)

    def test_stats_by_tier_returned(self) -> None:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows()
        res = library_support.get_library_filtered(api, "r1")
        by_tier = res["stats"]["by_tier"]
        self.assertEqual(by_tier.get("platinum"), 1)
        self.assertEqual(by_tier.get("gold"), 2)
        self.assertEqual(by_tier.get("silver"), 1)
        self.assertEqual(by_tier.get("reject"), 1)


class SmartPlaylistsTests(unittest.TestCase):
    def test_get_smart_playlists_includes_presets(self) -> None:
        from cinesort.ui.api import library_support

        api = MagicMock()
        api.get_settings.return_value = {"smart_playlists": []}
        res = library_support.get_smart_playlists(api)
        self.assertTrue(res["ok"])
        ids = [p["id"] for p in res["playlists"]]
        self.assertIn("_preset_reject", ids)
        self.assertIn("_preset_dnr", ids)
        self.assertIn("_preset_platinum", ids)

    def test_save_smart_playlist_creates_new(self) -> None:
        from cinesort.ui.api import library_support

        api = MagicMock()
        api.get_settings.return_value = {"smart_playlists": []}
        api.save_settings.return_value = {"ok": True}
        res = library_support.save_smart_playlist(api, "Ma liste", {"tier_v2": ["gold"]})
        self.assertTrue(res["ok"])
        self.assertTrue(res["playlist_id"].startswith("sp_"))

    def test_save_smart_playlist_empty_name(self) -> None:
        from cinesort.ui.api import library_support

        api = MagicMock()
        res = library_support.save_smart_playlist(api, "", {})
        self.assertFalse(res["ok"])

    def test_delete_smart_playlist_custom(self) -> None:
        from cinesort.ui.api import library_support

        api = MagicMock()
        api.get_settings.return_value = {
            "smart_playlists": [
                {"id": "sp_abc", "name": "Test", "filters": {}},
            ]
        }
        api.save_settings.return_value = {"ok": True}
        res = library_support.delete_smart_playlist(api, "sp_abc")
        self.assertTrue(res["ok"])

    def test_delete_smart_playlist_preset_protected(self) -> None:
        from cinesort.ui.api import library_support

        api = MagicMock()
        res = library_support.delete_smart_playlist(api, "_preset_reject")
        self.assertFalse(res["ok"])
        self.assertIn("protegee", res.get("message", "").lower())


class LibraryComponentsDesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "components" / "library-components.js").read_text(encoding="utf-8")

    def test_window_library_components_global(self) -> None:
        self.assertIn("window.LibraryComponents", self.js)

    def test_api_methods(self) -> None:
        for fn in ("renderFilterSidebar", "renderLibraryTable", "renderPosterGrid", "renderSmartPlaylists"):
            self.assertIn(fn, self.js)

    def test_filter_dimensions_7_categories(self) -> None:
        for k in ("tier_v2", "codec", "resolution", "hdr", "warnings", "grain_era_v2", "grain_nature"):
            self.assertIn(f"{k}:", self.js)

    def test_tier_options_include_5_tiers(self) -> None:
        for t in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f'"{t}"', self.js)

    def test_warning_short_labels(self) -> None:
        # Les 9 types de warnings ont un label court
        for w in (
            "dv_profile_5",
            "hdr_metadata_missing",
            "runtime_mismatch",
            "short_file",
            "low_confidence",
            "dnr_partial",
            "fake_4k_confirmed",
        ):
            self.assertIn(w, self.js)

    def test_sort_change_callback(self) -> None:
        self.assertIn("onSortChange", self.js)

    def test_accessibility(self) -> None:
        self.assertIn('role="list"', self.js)
        self.assertIn("aria-pressed", self.js)
        self.assertIn("tabindex", self.js)


class LibraryComponentsDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "dashboard" / "components" / "library-components.js").read_text(encoding="utf-8")

    def test_es_module_exports(self) -> None:
        for exp in (
            "export function renderFilterSidebar",
            "export function renderLibraryTable",
            "export function renderPosterGrid",
            "export function renderSmartPlaylists",
            "export const FILTER_DIMENSIONS",
        ):
            self.assertIn(exp, self.js)

    def test_imports_escapeHtml(self) -> None:
        self.assertIn('import { escapeHtml } from "../core/dom.js"', self.js)

    def test_filter_dimensions_parity(self) -> None:
        for k in ("tier_v2", "codec", "resolution", "hdr", "warnings", "grain_era_v2", "grain_nature"):
            self.assertIn(f"{k}:", self.js)


class LibraryV5ViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "views" / "library-v5.js").read_text(encoding="utf-8")

    def test_es_module_export(self) -> None:
        # V5bis-02 : la vue est portee en ES module, plus d'IIFE/window global.
        self.assertIn("export async function initLibrary", self.js)
        self.assertNotIn("window.LibraryV5", self.js)

    def test_api_methods(self) -> None:
        # V5bis-02 : initLibrary (init) + refresh exportes en ES module.
        self.assertIn("export async function initLibrary", self.js)
        self.assertIn("export async function refresh", self.js)

    def test_uses_get_library_filtered_endpoint(self) -> None:
        self.assertIn("get_library_filtered", self.js)
        self.assertIn("get_smart_playlists", self.js)
        self.assertIn("save_smart_playlist", self.js)
        self.assertIn("delete_smart_playlist", self.js)

    def test_persists_state_localStorage(self) -> None:
        self.assertIn("cinesort.library.viewMode", self.js)
        self.assertIn("cinesort.library.filters", self.js)
        self.assertIn("cinesort.library.sort", self.js)

    def test_uses_library_components(self) -> None:
        self.assertIn("LibraryComponents", self.js)
        self.assertIn("renderFilterSidebar", self.js)
        self.assertIn("renderLibraryTable", self.js)
        self.assertIn("renderPosterGrid", self.js)
        self.assertIn("renderSmartPlaylists", self.js)

    def test_view_mode_toggle(self) -> None:
        self.assertIn('"table"', self.js)
        self.assertIn('"grid"', self.js)

    def test_pagination_support(self) -> None:
        self.assertIn("page", self.js)
        self.assertIn("prev", self.js)
        self.assertIn("next", self.js)


class CssVague3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")

    def test_library_shell_classes(self) -> None:
        for cls in (
            ".v5-library-shell",
            ".v5-library-side",
            ".v5-library-main",
            ".v5-library-header",
            ".v5-library-body",
            ".v5-library-footer",
        ):
            self.assertIn(cls, self.css)

    def test_library_table_classes(self) -> None:
        for cls in (
            ".v5-library-table",
            ".v5-library-table-wrap",
            ".v5-library-title",
            ".v5-library-score-mini",
            ".v5-library-warns",
            ".v5-library-warn",
        ):
            self.assertIn(cls, self.css)

    def test_library_score_tier_variants(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f".v5-library-score-mini--{tier}", self.css)

    def test_view_toggle_classes(self) -> None:
        for cls in (".v5-library-view-toggle", ".v5-library-view-btn"):
            self.assertIn(cls, self.css)

    def test_poster_grid_classes(self) -> None:
        for cls in (".v5-poster-grid", ".v5-poster-card--library", ".v5-poster-score-overlay"):
            self.assertIn(cls, self.css)

    def test_filter_sidebar_classes(self) -> None:
        for cls in (
            ".v5-filter-sidebar",
            ".v5-filter-section",
            ".v5-filter-chip",
            ".v5-filter-chip.is-active",
            ".v5-filter-chip-count",
            ".v5-filter-range",
        ):
            self.assertIn(cls, self.css)

    def test_playlists_classes(self) -> None:
        for cls in (
            ".v5-playlists-wrap",
            ".v5-playlists-header",
            ".v5-playlists-title",
            ".v5-playlist-item",
            ".v5-playlist-item.is-active",
            ".v5-playlist-name",
            ".v5-playlist-preset-badge",
        ):
            self.assertIn(cls, self.css)


class IntegrationVague3Tests(unittest.TestCase):
    def test_index_html_loads_vague3_scripts(self) -> None:
        html = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("library-components.js", html)
        self.assertIn("library-v5.js", html)

    def test_router_integrates_library_v5(self) -> None:
        js = (_ROOT / "web" / "core" / "router.js").read_text(encoding="utf-8")
        self.assertIn("LibraryV5", js)
        self.assertIn("library-v5-root", js)
        self.assertIn("mount", js)

    def test_cinesort_api_exposes_new_endpoints(self) -> None:
        py = (_ROOT / "cinesort" / "ui" / "api" / "cinesort_api.py").read_text(encoding="utf-8")
        self.assertIn("def get_library_filtered", py)
        self.assertIn("def get_smart_playlists", py)
        self.assertIn("def save_smart_playlist", py)
        self.assertIn("def delete_smart_playlist", py)


class DashboardSmokeTests(unittest.TestCase):
    def test_dashboard_module_imports_cleanly(self) -> None:
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node indisponible")
        result = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                "import('./web/dashboard/components/library-components.js').then(m => {"
                "console.log('EXPORTS:' + Object.keys(m).sort().join(','));"
                "})",
            ],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("FILTER_DIMENSIONS", result.stdout)
        self.assertIn("renderFilterSidebar", result.stdout)
        self.assertIn("renderLibraryTable", result.stdout)
        self.assertIn("renderPosterGrid", result.stdout)
        self.assertIn("renderSmartPlaylists", result.stdout)


if __name__ == "__main__":
    unittest.main()
