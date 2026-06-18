"""V5bis-06 — Vérifie film-detail.js porté en ES module."""

from __future__ import annotations

import unittest
from pathlib import Path

# R8-053/054/055 (F5, D1) : la vue standalone views/film-detail.js a été SUPPRIMÉE
# (jumeau buggé). Le composant components/film-detail.js (API renderFilmDetail, modes
# A/B/C) est désormais la fiche film canonique. Ce test vérifiait les exports SPÉCIFIQUES
# du port ES de la vue (initFilmDetail / mountFilmDetailDrawer), absents du composant ->
# on skippe (convention codebase : skip quand le fichier legacy est retiré).
if not Path("web/dashboard/views/film-detail.js").exists():
    raise unittest.SkipTest(
        "views/film-detail.js supprimée (R8 D1) ; fiche film canonique = "
        "components/film-detail.js (API renderFilmDetail différente)."
    )


class FilmDetailV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/dashboard/views/film-detail.js").read_text(encoding="utf-8")

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
