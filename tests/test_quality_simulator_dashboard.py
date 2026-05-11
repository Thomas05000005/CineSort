"""Tests contrat pour la parite dashboard G5 (simulateur de preset)."""

from __future__ import annotations

import unittest
from pathlib import Path


class DashboardSimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.js_path = cls.root / "web" / "dashboard" / "views" / "quality-simulator.js"
        cls.css_path = cls.root / "web" / "dashboard" / "styles.css"
        cls.quality_path = cls.root / "web" / "dashboard" / "views" / "quality.js"

    def test_file_exists(self):
        self.assertTrue(self.js_path.exists(), "quality-simulator.js dashboard doit exister")

    def test_exports_open_function(self):
        js = self.js_path.read_text(encoding="utf-8")
        self.assertIn("export function openQualitySimulator", js)

    def test_imports_api_post(self):
        js = self.js_path.read_text(encoding="utf-8")
        self.assertIn('from "../core/api.js"', js)
        self.assertIn("apiPost", js)
        self.assertNotIn("window.pywebview", js)

    def test_uses_show_modal(self):
        js = self.js_path.read_text(encoding="utf-8")
        self.assertIn("showModal", js)

    def test_all_preset_cards_present(self):
        js = self.js_path.read_text(encoding="utf-8")
        for pid in ("equilibre", "remux_strict", "light"):
            self.assertIn(pid, js, f"preset {pid} attendu dans le JS")

    def test_calls_simulate_endpoint(self):
        js = self.js_path.read_text(encoding="utf-8")
        self.assertIn("simulate_quality_preset", js)

    def test_calls_save_custom_endpoint(self):
        js = self.js_path.read_text(encoding="utf-8")
        self.assertIn("save_custom_quality_preset", js)

    def test_has_tabs_simple_and_advanced(self):
        js = self.js_path.read_text(encoding="utf-8")
        self.assertIn('data-qsim-tab="simple"', js)
        self.assertIn('data-qsim-tab="advanced"', js)

    def test_has_sliders_weights_and_tiers(self):
        js = self.js_path.read_text(encoding="utf-8")
        self.assertIn('data-qsim-weight="video"', js)
        self.assertIn('data-qsim-weight="audio"', js)
        self.assertIn('data-qsim-weight="extras"', js)
        self.assertIn('data-qsim-tier="premium"', js)

    @unittest.skip("V5C-01: dashboard/views/quality.js supprime — bouton simulateur desormais dans qij-v5 (couvert par tests v5)")
    def test_quality_view_has_simulate_button(self):
        js = self.quality_path.read_text(encoding="utf-8")
        self.assertIn("btnQualitySimulate", js)
        self.assertIn("openQualitySimulator", js)
        self.assertIn('from "./quality-simulator.js"', js)

    def test_css_has_qsim_preset_card(self):
        css = self.css_path.read_text(encoding="utf-8")
        self.assertIn(".qsim-preset-card", css)

    def test_css_has_qsim_before_after(self):
        css = self.css_path.read_text(encoding="utf-8")
        self.assertIn(".qsim-before-after", css)

    def test_css_has_qsim_delta(self):
        css = self.css_path.read_text(encoding="utf-8")
        self.assertIn(".qsim-delta--positive", css)
        self.assertIn(".qsim-delta--negative", css)

    def test_css_has_qsim_fieldset(self):
        css = self.css_path.read_text(encoding="utf-8")
        self.assertIn(".qsim-fieldset", css)

    def test_js_has_render_functions(self):
        js = self.js_path.read_text(encoding="utf-8")
        for fn in ("_renderResults", "_renderTiersChart", "_renderStatsPills", "_renderImpacted", "_renderBreakdown"):
            self.assertIn(fn, js, f"{fn} attendu dans le JS")


if __name__ == "__main__":
    unittest.main()
