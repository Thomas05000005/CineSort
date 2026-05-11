"""Tests contrat pour la vue Library (hub workflow 5 etapes desktop, parite dashboard)."""

from __future__ import annotations

import unittest
from pathlib import Path


class LibraryViewContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.html = (cls.root / "web" / "index.html").read_text(encoding="utf-8")
        cls.js = (cls.root / "web" / "views" / "library.js").read_text(encoding="utf-8")
        cls.css = (cls.root / "web" / "styles.css").read_text(encoding="utf-8")
        cls.router = (cls.root / "web" / "core" / "router.js").read_text(encoding="utf-8")

    def test_library_nav_button_present(self):
        self.assertIn('data-view="library"', self.html)
        self.assertIn('id="tab-library"', self.html)

    def test_library_view_section(self):
        self.assertIn('id="view-library"', self.html)
        self.assertIn('aria-labelledby="tab-library"', self.html)

    def test_workflow_header_and_steps(self):
        self.assertIn("workflow-header", self.html)
        self.assertIn("workflow-steps", self.html)
        self.assertIn('id="libRunLabel"', self.html)
        self.assertIn('id="ckLibAdvanced"', self.html)

    def test_five_steps_present(self):
        for i in range(1, 6):
            self.assertIn(f'data-lib-step="{i}"', self.html)
        self.assertIn('data-testid="lib-step-analyse"', self.html)
        self.assertIn('data-testid="lib-step-verification"', self.html)
        self.assertIn('data-testid="lib-step-validation"', self.html)
        self.assertIn('data-testid="lib-step-doublons"', self.html)
        self.assertIn('data-testid="lib-step-application"', self.html)

    def test_five_sections_present(self):
        for section in ("analyse", "verification", "validation", "doublons", "application"):
            self.assertIn(f'data-lib-section="{section}"', self.html)

    def test_kpi_containers(self):
        self.assertIn('id="libAnalyseKpis"', self.html)
        self.assertIn('id="libVerificationKpis"', self.html)
        self.assertIn('id="libValidationKpis"', self.html)
        self.assertIn('id="libDuplicatesKpis"', self.html)
        self.assertIn('id="libApplyKpis"', self.html)

    def test_goto_buttons(self):
        for target in ("home", "validation", "execution", "quality", "history", "settings"):
            self.assertIn(f'data-lib-goto="{target}"', self.html)

    def test_js_exposes_refresh_function(self):
        self.assertIn("refreshLibraryView", self.js)
        self.assertIn("window.refreshLibraryView", self.js)

    def test_js_uses_pywebview_api(self):
        self.assertIn("window.pywebview.api.get_dashboard", self.js)

    def test_router_registers_library(self):
        self.assertIn("library:", self.router)
        self.assertIn("Bibliothèque", self.router)
        self.assertIn("refreshLibraryView", self.router)

    def test_css_has_workflow_steps(self):
        self.assertIn(".workflow-header", self.css)
        self.assertIn(".workflow-steps", self.css)
        self.assertIn(".workflow-steps .step", self.css)
        self.assertIn(".lib-section", self.css)

    def test_script_loaded_in_index(self):
        self.assertIn("views/library.js", self.html)


if __name__ == "__main__":
    unittest.main()
