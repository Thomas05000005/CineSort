"""GATE AUDIT 2026-06-14 (R7-17) — refresh poster fiche film : message cle absente.

get_tmdb_posters renvoie ok:true + reason:"tmdb_not_configured" quand la cle
manque ; _refreshPosterUnit ne testait que data.ok===false -> throw generique
"Reessayer ?". Desormais message precis.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_FD = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "components" / "film-detail.js"


class FilmDetailPosterNotConfiguredTests(unittest.TestCase):
    def test_reason_handled(self):
        js = _FD.read_text(encoding="utf-8")
        self.assertIn('data.reason === "tmdb_not_configured"', js)
        self.assertIn("Clé TMDb non configurée", js)


if __name__ == "__main__":
    unittest.main()
