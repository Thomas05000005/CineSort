"""Tests contrat UI pour l'editeur de regles custom (G6)."""

from __future__ import annotations

import unittest
from pathlib import Path


class CustomRulesUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.html_path = cls.root / "web" / "index.html"
        cls.desktop_js = cls.root / "web" / "views" / "custom-rules-editor.js"
        cls.dashboard_js = cls.root / "web" / "dashboard" / "views" / "custom-rules-editor.js"
        cls.desktop_css = cls.root / "web" / "styles.css"
        cls.dashboard_css = cls.root / "web" / "dashboard" / "styles.css"
        cls.dashboard_quality = cls.root / "web" / "dashboard" / "views" / "quality.js"
        cls.desktop_quality_sim = cls.root / "web" / "views" / "quality-simulator.js"
        cls.dashboard_quality_sim = cls.root / "web" / "dashboard" / "views" / "quality-simulator.js"

    def test_files_exist(self):
        self.assertTrue(self.desktop_js.exists(), "custom-rules-editor.js desktop doit exister")
        self.assertTrue(self.dashboard_js.exists(), "custom-rules-editor.js dashboard doit exister")

    def test_index_html_has_custom_rules_card(self):
        html = self.html_path.read_text(encoding="utf-8")
        self.assertIn('id="customRulesCard"', html)
        self.assertIn('id="customRulesList"', html)
        self.assertIn('id="btnRuleAdd"', html)
        self.assertIn('id="btnRulesSave"', html)

    def test_index_html_has_template_buttons(self):
        html = self.html_path.read_text(encoding="utf-8")
        self.assertIn('data-rule-template="trash_like"', html)
        self.assertIn('data-rule-template="purist"', html)
        self.assertIn('data-rule-template="casual"', html)

    def test_index_html_loads_editor_script(self):
        html = self.html_path.read_text(encoding="utf-8")
        self.assertIn("custom-rules-editor.js", html)

    def test_desktop_exports_open_function(self):
        js = self.desktop_js.read_text(encoding="utf-8")
        self.assertIn("openCustomRulesEditor", js)
        self.assertIn("window.openCustomRulesEditor", js)

    def test_dashboard_exports_open_function(self):
        js = self.dashboard_js.read_text(encoding="utf-8")
        self.assertIn("export async function openCustomRulesEditor", js)

    def test_dashboard_uses_apipost(self):
        js = self.dashboard_js.read_text(encoding="utf-8")
        self.assertIn('from "../core/api.js"', js)
        self.assertIn("apiPost", js)
        self.assertNotIn("window.pywebview", js)

    def test_desktop_uses_pywebview(self):
        js = self.desktop_js.read_text(encoding="utf-8")
        self.assertIn("window.pywebview.api", js)

    def test_desktop_js_has_all_17_fields(self):
        js = self.desktop_js.read_text(encoding="utf-8")
        for f in (
            "video_codec",
            "audio_codec",
            "resolution",
            "resolution_rank",
            "year",
            "bitrate_kbps",
            "audio_channels",
            "has_hdr10",
            "has_hdr10p",
            "has_dv",
            "subtitle_count",
            "subtitle_langs",
            "warning_flags",
            "edition",
            "tier_before",
            "score_before",
            "file_size_gb",
            "duration_s",
            "tmdb_in_collection",
        ):
            self.assertIn(f, js, f"Field {f} manquant dans l'editeur desktop")

    def test_desktop_js_has_all_11_operators(self):
        js = self.desktop_js.read_text(encoding="utf-8")
        # Rechercher les valeurs d'option
        for op in (
            '"="',
            '"!="',
            '"<"',
            '"<="',
            '">"',
            '">="',
            '"in"',
            '"not_in"',
            '"contains"',
            '"not_contains"',
            '"between"',
        ):
            self.assertIn(op, js, f"Operator {op} manquant")

    def test_desktop_js_has_all_7_actions(self):
        js = self.desktop_js.read_text(encoding="utf-8")
        for act in (
            "score_delta",
            "score_multiplier",
            "force_score",
            "force_tier",
            "cap_max",
            "cap_min",
            "flag_warning",
        ):
            self.assertIn(act, js, f"Action {act} manquante")

    def test_dashboard_js_has_all_17_fields(self):
        js = self.dashboard_js.read_text(encoding="utf-8")
        for f in (
            "video_codec",
            "audio_codec",
            "resolution",
            "resolution_rank",
            "year",
            "bitrate_kbps",
            "audio_channels",
            "has_hdr10",
            "has_hdr10p",
            "has_dv",
            "subtitle_count",
            "subtitle_langs",
            "warning_flags",
            "edition",
            "tier_before",
            "score_before",
            "file_size_gb",
            "duration_s",
            "tmdb_in_collection",
        ):
            self.assertIn(f, js, f"Field {f} manquant dans l'editeur dashboard")

    def test_desktop_css_has_rule_card(self):
        css = self.desktop_css.read_text(encoding="utf-8")
        self.assertIn(".rule-card", css)
        self.assertIn(".rule-condition", css)
        self.assertIn(".rule-action", css)
        self.assertIn(".rule-kw", css)

    def test_dashboard_css_has_rule_card(self):
        css = self.dashboard_css.read_text(encoding="utf-8")
        self.assertIn(".rule-card", css)
        self.assertIn(".rule-condition", css)
        self.assertIn(".rule-action", css)
        self.assertIn(".rule-kw", css)

    @unittest.skip("V5C-01: dashboard/views/quality.js supprime — editeur custom-rules desormais accessible via qij-v5")
    def test_dashboard_quality_imports_editor(self):
        js = self.dashboard_quality.read_text(encoding="utf-8")
        self.assertIn('from "./custom-rules-editor.js"', js)
        self.assertIn("btnCustomRulesEditor", js)
        self.assertIn("openCustomRulesEditor", js)

    def test_simulator_accepts_overrides(self):
        js_d = self.desktop_quality_sim.read_text(encoding="utf-8")
        self.assertIn("pendingOverrides", js_d)
        self.assertIn("custom_rules", js_d)
        js_w = self.dashboard_quality_sim.read_text(encoding="utf-8")
        self.assertIn("pendingOverrides", js_w)
        self.assertIn("custom_rules", js_w)

    def test_desktop_has_import_export(self):
        js = self.desktop_js.read_text(encoding="utf-8")
        self.assertIn("_exportJson", js)
        self.assertIn("_importJson", js)

    def test_dashboard_has_import_export(self):
        js = self.dashboard_js.read_text(encoding="utf-8")
        self.assertIn("_exportJson", js)
        self.assertIn("_importJson", js)


if __name__ == "__main__":
    unittest.main()
