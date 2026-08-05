"""GATE AUDIT 2026-06-14 (R7-16) — vignettes secondaires : fallback image cassée.

Le fix R6-H n'avait couvert que le poster principal + cartes Bibliotheque. Les
vignettes candidats TMDb, recherche manuelle, cartes/inspecteur Doublons et
grille Reject Qualite affichaient l'icone d'image cassee (URLs TMDb 404-ables).

Verif totale 2026-07 (LOTC-C1) : la CSP `script-src 'self'` bloque les handlers
`onerror=` INLINE -> ils ont ete remplaces par un listener 'error' DELEGUE en
phase capture (`addEventListener("error", _onPosterError, true)`). Ce test
verifie desormais ce contrat CSP-compliant.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class ThumbnailsOnErrorTests(unittest.TestCase):
    def _assert_delegated_error_listener(self, rel: str) -> None:
        js = (_ROOT / rel).read_text(encoding="utf-8")
        self.assertIn(
            'addEventListener("error", _onPosterError, true)',
            js,
            f"{rel} : listener 'error' delegue (capture) attendu (LOTC-C1, CSP).",
        )
        # Plus aucun handler inline (bloque par la CSP).
        self.assertNotIn("onerror=", js, f"{rel} : plus d'onerror inline (CSP).")

    def test_film_detail_thumbs(self):
        self._assert_delegated_error_listener("web/dashboard/components/film-detail.js")

    def test_doublons_thumbs(self):
        self._assert_delegated_error_listener("web/dashboard/views/doublons.js")

    def test_qualite_thumb(self):
        self._assert_delegated_error_listener("web/dashboard/views/qualite.js")


if __name__ == "__main__":
    unittest.main()
