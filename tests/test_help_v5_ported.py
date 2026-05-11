"""V5bis-07 — Verifie help.js v5 porte (ES module + apiPost + sections preservees)."""

from __future__ import annotations

import unittest
from pathlib import Path


class HelpV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/help.js").read_text(encoding="utf-8")

    def test_es_module_export(self):
        self.assertIn("export async function initHelp", self.src)

    def test_no_iife(self):
        self.assertNotIn("window.HelpView", self.src)

    def test_no_pywebview_api(self):
        self.assertNotIn("window.pywebview.api", self.src)

    def test_helpers_imported(self):
        self.assertIn('from "./_v5_helpers.js"', self.src)

    def test_v1_14_faq_glossaire(self):
        self.assertIn("FAQ", self.src)
        self.assertIn("glossaire", self.src.lower())

    def test_v3_08_shortcuts_enriched(self):
        self.assertIn("shortcuts-table", self.src)
        self.assertGreaterEqual(self.src.count("<kbd>"), 15)

    def test_v3_13_support_section(self):
        self.assertIn("help-support", self.src)
        self.assertIn("btnOpenLogs", self.src)
        self.assertIn("btnCopyLogPath", self.src)
        self.assertIn("get_log_paths", self.src)
        self.assertIn("open_logs_folder", self.src)


if __name__ == "__main__":
    unittest.main()
