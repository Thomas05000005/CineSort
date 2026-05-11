"""UI preview contract tests — v2 architecture.

These tests verify the preview system still works with the new modular architecture.
The preview system was not modified in v2 and may need adaptation.
"""

from __future__ import annotations

import unittest
from pathlib import Path


class UiPreviewContractsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.root = root
        cls.index_html = (root / "web" / "index.html").read_text(encoding="utf-8")
        cls.app_js = (root / "web" / "app.js").read_text(encoding="utf-8")
        cls.preview_dir = root / "web" / "preview"

    def test_index_html_loads_app_js(self) -> None:
        self.assertIn('src="./app.js"', self.index_html)

    def test_app_bridge_exposes_navigation_and_state(self) -> None:
        self.assertIn("window.CineSortBridge = {", self.app_js)
        self.assertIn("getStateSnapshot()", self.app_js)

    def test_preview_directory_exists(self) -> None:
        self.assertTrue(self.preview_dir.exists(), "web/preview/ directory should exist")

    def test_index_html_has_view_sections(self) -> None:
        # Sidebar restauree : workflow (home/validation/execution/quality) + integrations
        # (jellyfin/plex/radarr) + general (history/settings)
        for view in ["home", "validation", "execution", "quality", "jellyfin", "plex", "radarr", "history", "settings"]:
            self.assertIn(f'id="view-{view}"', self.index_html)

    def test_core_modules_are_loaded(self) -> None:
        self.assertIn('src="./core/dom.js"', self.index_html)
        self.assertIn('src="./core/state.js"', self.index_html)
        self.assertIn('src="./core/api.js"', self.index_html)
        self.assertIn('src="./core/router.js"', self.index_html)
        self.assertIn('src="./core/keyboard.js"', self.index_html)
        self.assertIn('src="./core/drop.js"', self.index_html)

    def test_component_modules_are_loaded(self) -> None:
        self.assertIn('src="./components/status.js"', self.index_html)
        self.assertIn('src="./components/modal.js"', self.index_html)
        self.assertIn('src="./components/table.js"', self.index_html)

    def test_view_modules_are_loaded(self) -> None:
        # Vues principales (workflow)
        for view in ["home", "validation", "execution", "quality", "history", "settings"]:
            self.assertIn(f'src="./views/{view}.js"', self.index_html)
        # Vues integrations dediees
        for view_file in ["jellyfin-view", "plex-view", "radarr-view"]:
            self.assertIn(f'src="./views/{view_file}.js"', self.index_html)

    def test_bootstrap_uses_pywebviewready(self) -> None:
        self.assertIn("pywebviewready", self.app_js)

    def test_bootstrap_has_dom_fallback(self) -> None:
        self.assertIn("DOMContentLoaded", self.app_js)

    def test_stable_ui_embeds_local_font(self) -> None:
        # V3-02 (v7.7.0) : police partagee dans web/shared/fonts/
        css = (self.root / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("shared/fonts/Manrope-Variable.ttf", css)

    def test_design_system_has_tokens(self) -> None:
        css = (self.root / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("--bg-base", css)
        self.assertIn("--accent", css)
        self.assertIn("body.light", css)


if __name__ == "__main__":
    unittest.main()
