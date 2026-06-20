"""GATE AUDIT 2026-06-14 (R7-16) — vignettes secondaires avec onerror.

Le fix R6-H n'avait couvert que le poster principal + cartes Bibliotheque. Les
vignettes candidats TMDb, recherche manuelle, cartes/inspecteur Doublons et
grille Reject Qualite affichaient l'icone d'image cassee (URLs TMDb 404-ables).
"""
from __future__ import annotations
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class ThumbnailsOnErrorTests(unittest.TestCase):
    def test_film_detail_thumbs(self):
        js = (_ROOT / "web/dashboard/components/film-detail.js").read_text(encoding="utf-8")
        self.assertGreaterEqual(js.count("this.style.display='none'"), 2)

    def test_doublons_thumbs(self):
        js = (_ROOT / "web/dashboard/views/doublons.js").read_text(encoding="utf-8")
        self.assertGreaterEqual(js.count("this.style.display='none'"), 2)

    def test_qualite_thumb(self):
        js = (_ROOT / "web/dashboard/views/qualite.js").read_text(encoding="utf-8")
        self.assertIn("onerror=\"this.onerror=null;this.style.display='none'\"", js)


if __name__ == "__main__":
    unittest.main()
