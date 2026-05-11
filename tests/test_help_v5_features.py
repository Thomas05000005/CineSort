"""V5A-08 — Verifie help.js v5 contient V1-14 + V3-13 + V3-08."""

from __future__ import annotations

import unittest
from pathlib import Path


class HelpV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/help.js").read_text(encoding="utf-8")

    def test_v1_14_faq_glossaire(self):
        self.assertIn("FAQ", self.src)
        self.assertTrue(
            "glossaire" in self.src.lower() or "Glossaire" in self.src,
            "Section glossaire absente",
        )

    def test_v3_13_support_section(self):
        self.assertIn("help-support", self.src)
        self.assertIn("btnOpenLogs", self.src)
        self.assertIn("btnCopyLogPath", self.src)

    def test_v3_13_endpoints(self):
        self.assertIn("get_log_paths", self.src)
        self.assertIn("open_logs_folder", self.src)

    def test_v3_13_github_issues_link(self):
        self.assertIn("github.com", self.src)
        self.assertIn("/issues", self.src)

    def test_v3_08_shortcuts(self):
        self.assertIn("shortcuts-table", self.src)
        self.assertGreaterEqual(self.src.count("<kbd>"), 15)

    def test_v3_08_shortcut_categories(self):
        # 3 categories attendues : Navigation / Actions globales / Validation
        self.assertIn("Navigation", self.src)
        self.assertIn("Actions globales", self.src)
        self.assertIn("Validation", self.src)
        # Au moins un Alt+N pour la nav
        self.assertIn("Alt+1", self.src)


if __name__ == "__main__":
    unittest.main()
