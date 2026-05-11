"""Tests contrat pour les ajouts parite desktop (HTTPS, test email, profil qualite, skeleton, kpi-card, event polling)."""

from __future__ import annotations

import unittest
from pathlib import Path


class ParityAdditionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.html = (cls.root / "web" / "index.html").read_text(encoding="utf-8")
        cls.settings_js = (cls.root / "web" / "views" / "settings.js").read_text(encoding="utf-8")
        cls.quality_js = (cls.root / "web" / "views" / "quality.js").read_text(encoding="utf-8")
        cls.execution_js = (cls.root / "web" / "views" / "execution.js").read_text(encoding="utf-8")
        cls.app_js = (cls.root / "web" / "app.js").read_text(encoding="utf-8")
        cls.state_js = (cls.root / "web" / "core" / "state.js").read_text(encoding="utf-8")
        cls.skeleton = cls.root / "web" / "components" / "skeleton.js"
        cls.kpi_card = cls.root / "web" / "components" / "kpi-card.js"
        cls.api_py = (cls.root / "cinesort" / "ui" / "api" / "cinesort_api.py").read_text(encoding="utf-8")

    # --- Lot 1.1 : HTTPS settings ---
    def test_https_checkbox_present(self):
        self.assertIn('id="ckRestHttpsEnabled"', self.html)

    def test_https_cert_input_present(self):
        self.assertIn('id="inRestCertPath"', self.html)
        self.assertIn('id="inRestKeyPath"', self.html)

    def test_https_load_save_in_settings_js(self):
        self.assertIn("rest_api_https_enabled", self.settings_js)
        self.assertIn("rest_api_cert_path", self.settings_js)
        self.assertIn("rest_api_key_path", self.settings_js)

    # --- Lot 1.2 : test email button ---
    def test_email_test_button_present(self):
        self.assertIn('id="btnTestEmail"', self.html)
        self.assertIn('id="msgTestEmail"', self.html)

    def test_email_test_handler(self):
        self.assertIn("test_email_report", self.settings_js)

    # --- Lot 1.3 : quality profile buttons ---
    def test_quality_export_button(self):
        self.assertIn('id="btnQualityExportProfile"', self.html)

    def test_quality_import_button(self):
        self.assertIn('id="btnQualityImportProfile"', self.html)
        self.assertIn('id="qualityImportInput"', self.html)

    def test_quality_reset_button(self):
        self.assertIn('id="btnQualityResetProfile"', self.html)

    def test_quality_handlers(self):
        self.assertIn("export_quality_profile", self.quality_js)
        self.assertIn("import_quality_profile", self.quality_js)
        self.assertIn("reset_quality_profile", self.quality_js)

    # --- Lot 2.1 : skeleton component ---
    def test_skeleton_js_exists(self):
        self.assertTrue(self.skeleton.exists(), "components/skeleton.js doit exister")
        content = self.skeleton.read_text(encoding="utf-8")
        self.assertIn("skeletonLinesHtml", content)
        self.assertIn("skeletonKpiGridHtml", content)
        self.assertIn("skeletonViewHtml", content)

    def test_skeleton_script_loaded(self):
        self.assertIn("components/skeleton.js", self.html)

    def test_skeleton_css_present(self):
        css = (self.root / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".skeleton", css)
        self.assertIn("skeleton-shimmer", css)

    # --- Lot 2.2 : kpi-card component ---
    def test_kpi_card_js_exists(self):
        self.assertTrue(self.kpi_card.exists(), "components/kpi-card.js doit exister")
        content = self.kpi_card.read_text(encoding="utf-8")
        self.assertIn("kpiCardHtml", content)
        self.assertIn("kpiGridHtml", content)
        self.assertIn("window.kpiCardHtml", content)

    def test_kpi_card_script_loaded(self):
        self.assertIn("components/kpi-card.js", self.html)

    # --- Lot 3.1 : event-driven polling ---
    def test_event_ts_backend_endpoint(self):
        self.assertIn("def get_event_ts", self.api_py)

    def test_state_js_has_check_event_changed(self):
        self.assertIn("checkEventChanged", self.state_js)
        self.assertIn("lastEventTs", self.state_js)

    def test_app_js_has_idle_polling(self):
        self.assertIn("get_event_ts", self.app_js)
        self.assertIn("setupEventDrivenPolling", self.app_js)

    # --- Lot 3.2 : compare_perceptual ---
    def test_compare_perceptual_in_execution(self):
        self.assertIn("compare_perceptual", self.execution_js)
        self.assertIn("btnPerceptualCompare", self.execution_js)


if __name__ == "__main__":
    unittest.main()
