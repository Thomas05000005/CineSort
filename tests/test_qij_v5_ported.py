"""V5bis-03 — Verifie qij-v5.js porte (IIFE -> ES module + apiPost)."""

from __future__ import annotations

import unittest
from pathlib import Path


class QijV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/qij-v5.js").read_text(encoding="utf-8")

    def test_es_module_exports(self):
        self.assertIn("export async function initQuality", self.src)
        self.assertIn("export async function initIntegrations", self.src)
        self.assertIn("export async function initJournal", self.src)
        self.assertIn("export async function initQij", self.src)

    def test_no_iife_globals(self):
        for g in ["window.QualityV5", "window.IntegrationsV5", "window.JournalV5"]:
            self.assertNotIn(g, self.src, f"Global encore present: {g}")

    def test_no_pywebview_api(self):
        self.assertNotIn("window.pywebview.api", self.src)

    def test_helpers_imported(self):
        self.assertIn('from "./_v5_helpers.js"', self.src)
        self.assertIn("glossaryTooltip", self.src)
        self.assertIn("buildEmptyState", self.src)

    def test_v1_05_empty_state(self):
        self.assertIn("buildEmptyState", self.src)
        self.assertIn("Lancer un scan", self.src)

    def test_v3_03_glossary(self):
        self.assertGreaterEqual(self.src.count("glossaryTooltip("), 5)


if __name__ == "__main__":
    unittest.main()
