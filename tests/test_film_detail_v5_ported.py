"""V5bis-06 — Vérifie film-detail.js porté en ES module."""

from __future__ import annotations
import unittest
from pathlib import Path


class FilmDetailV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/film-detail.js").read_text(encoding="utf-8")

    def test_es_module_init(self):
        self.assertIn("export async function initFilmDetail", self.src)

    def test_es_module_drawer_export(self):
        self.assertIn("export function mountFilmDetailDrawer", self.src)

    def test_no_iife(self):
        self.assertNotIn("window.FilmDetail", self.src)

    def test_no_pywebview_api(self):
        self.assertNotIn("window.pywebview.api", self.src)

    def test_helpers_imported(self):
        self.assertIn('from "./_v5_helpers.js"', self.src)

    def test_get_film_full_used(self):
        self.assertIn("get_film_full", self.src)

    def test_v2_04_allsettled(self):
        self.assertIn("Promise.allSettled", self.src)

    def test_4_tabs_preserved(self):
        # Référence aux 4 tabs (Aperçu / Analyse V2 / Historique / Comparaison)
        for tab in ["overview", "analysis", "history", "comparison"]:
            self.assertIn(tab, self.src.lower(), f"Tab manquant: {tab}")


if __name__ == "__main__":
    unittest.main()
