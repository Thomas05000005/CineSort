"""Tests Vague 6 v7.6.0 — Settings refonte 9 groupes."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class SettingsV5ViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "views" / "settings-v5.js").read_text(encoding="utf-8")

    def test_es_module_exports(self) -> None:
        # V5bis-05 : port IIFE -> ES module. Plus de window.SettingsV5.
        self.assertNotIn("window.SettingsV5", self.js)
        self.assertIn('from "./_v5_helpers.js"', self.js)

    def test_api_methods(self) -> None:
        # V5bis-05 : exports nommes (initSettings + unmountSettings + goToCategory).
        self.assertIn("export async function initSettings", self.js)
        self.assertIn("export function unmountSettings", self.js)
        self.assertIn("export function goToCategory", self.js)

    def test_9_groups_defined(self) -> None:
        for group in (
            "sources",
            "analyse",
            "nommage",
            "bibliotheque",
            "integrations",
            "notifications",
            "serveur",
            "apparence",
            "avance",
        ):
            self.assertIn(f'id: "{group}"', self.js)

    def test_field_types_supported(self) -> None:
        # 7 types : toggle, number, text, path, select, api-key, multi-path
        for t in ("toggle", "number", "text", "path", "select", "api-key", "multi-path"):
            self.assertIn(f'type: "{t}"', self.js)

    def test_integrations_includes_4_services(self) -> None:
        # tmdb, jellyfin, plex, radarr sections in integrations group
        for k in ("tmdb_api_key", "jellyfin_url", "plex_token", "radarr_api_key"):
            self.assertIn(k, self.js)

    def test_sources_includes_roots_watch_watchlist(self) -> None:
        for k in (
            "roots",
            "watch_enabled",
            "watch_interval_minutes",
            "watchlist_letterboxd_path",
            "watchlist_imdb_path",
        ):
            self.assertIn(k, self.js)

    def test_analyse_includes_perceptual_v7_5(self) -> None:
        # Les 14 sections perceptuelles v7.5 doivent avoir leurs toggles
        for k in (
            "perceptual_audio_fingerprint_enabled",  # §3
            "perceptual_audio_spectral_enabled",  # §9
            "perceptual_audio_mel_enabled",  # §12
            "perceptual_ssim_self_ref_enabled",  # §13
            "perceptual_hdr10_plus_detection_enabled",  # §5
            "perceptual_grain_intelligence_enabled",  # §15
            "perceptual_lpips_enabled",
        ):  # §11
            self.assertIn(k, self.js)

    def test_apparence_theme_has_4_options(self) -> None:
        for theme in ("studio", "cinema", "luxe", "neon"):
            self.assertIn(f'v:"{theme}"', self.js)

    def test_apparence_density_livePreview(self) -> None:
        self.assertIn("livePreview", self.js)
        self.assertIn('"density"', self.js)
        self.assertIn('"theme"', self.js)
        self.assertIn('"naming"', self.js)

    def test_search_fuzzy_on_labels(self) -> None:
        self.assertIn("_searchMatch", self.js)
        self.assertIn("_sectionMatchesQuery", self.js)
        self.assertIn("toLowerCase", self.js)

    def test_badge_configure_partial_none(self) -> None:
        self.assertIn('"full"', self.js)
        self.assertIn('"partial"', self.js)
        self.assertIn("_sectionStatus", self.js)

    def test_reset_per_section(self) -> None:
        self.assertIn("data-reset-section", self.js)

    def test_api_key_toggle_visibility(self) -> None:
        self.assertIn("data-api-key-toggle", self.js)

    def test_auto_save_debounce(self) -> None:
        self.assertIn("_scheduleSave", self.js)
        self.assertIn("save_settings", self.js)

    def test_uses_backend_endpoints(self) -> None:
        self.assertIn("get_settings", self.js)
        self.assertIn("save_settings", self.js)


class RouterSettingsV5Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "core" / "router.js").read_text(encoding="utf-8")

    def test_settings_v5_route_detected(self) -> None:
        self.assertIn('view.startsWith("settings-v5")', self.js)

    def test_navigate_to_settings_v5_helper(self) -> None:
        self.assertIn("_navigateToSettingsV5", self.js)
        self.assertIn("_hideSettingsV5Overlay", self.js)

    def test_settings_v5_overlay_ensure(self) -> None:
        self.assertIn("_ensureSettingsV5Overlay", self.js)
        self.assertIn("settings-v5-overlay", self.js)

    def test_settings_v5_hidden_on_other_views(self) -> None:
        self.assertIn("_hideSettingsV5Overlay()", self.js)

    def test_film_and_processing_and_settings_mutually_exclusive(self) -> None:
        # Tous les overlays s'excluent les uns les autres
        self.assertRegex(self.js, r"_navigateToSettingsV5[\s\S]*?_hideProcessingOverlay")
        self.assertRegex(self.js, r"_navigateToSettingsV5[\s\S]*?_hideFilmDetailOverlay")


class CssVague6Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")

    def test_settings_shell_classes(self) -> None:
        for cls in (
            ".v5-settings-overlay",
            ".v5-settings-shell",
            ".v5-settings-sidebar",
            ".v5-settings-main",
            ".v5-settings-content",
            ".v5-settings-header",
        ):
            self.assertIn(cls, self.css)

    def test_settings_cat_classes(self) -> None:
        for cls in (
            ".v5-settings-cat",
            ".v5-settings-cat.is-active",
            ".v5-settings-cat-icon",
            ".v5-settings-cat-label",
            ".v5-settings-cat-dot",
        ):
            self.assertIn(cls, self.css)

    def test_settings_cat_dot_variants(self) -> None:
        for v in ("full", "partial"):
            self.assertIn(f".v5-settings-cat-dot--{v}", self.css)

    def test_settings_section_classes(self) -> None:
        for cls in (
            ".v5-settings-section",
            ".v5-settings-section-header",
            ".v5-settings-section-title",
            ".v5-settings-section-body",
        ):
            self.assertIn(cls, self.css)

    def test_settings_badge_variants(self) -> None:
        for v in ("full", "partial"):
            self.assertIn(f".v5-settings-badge--{v}", self.css)

    def test_settings_field_classes(self) -> None:
        for cls in (
            ".v5-settings-field",
            ".v5-settings-field--toggle",
            ".v5-settings-field-label",
            ".v5-settings-field-hint",
            ".v5-settings-api-key-wrap",
        ):
            self.assertIn(cls, self.css)

    def test_overlay_active_state(self) -> None:
        self.assertIn(".v5-settings-overlay.is-active", self.css)


class IntegrationVague6Tests(unittest.TestCase):
    def test_index_html_loads_settings_v5_script(self) -> None:
        html = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("settings-v5.js", html)


if __name__ == "__main__":
    unittest.main()
