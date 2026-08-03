"""GATE AUDIT 2026-06-14 (R6-H) — "Recuperer jaquettes" devient effectif.

Cause racine rendu : le rendu d'une carte calcule
posterSrc = posterProxyUrl(row.tmdb_id) || row.poster_url -> le proxy prime. Or
_bulkRefreshPosters ne patchait QUE r.poster_url, jamais r.tmdb_id ; et le
backend enrich persistait le tmdb_id sans le renvoyer. Resultat : pour les films
NFO resolus, la jaquette n'apparaissait pas (r.tmdb_id restait vide).

Fix : enrich_tmdb_ids_by_title renvoie ids:{row_id:tmdb_id} ; le client patche
r.tmdb_id -> le rendu passe par le proxy /api/poster. Plus message precis quand
la cle TMDb est absente (reason tmdb_not_configured).
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TMDB = _ROOT / "cinesort" / "ui" / "api" / "tmdb_support.py"
_BIB = _ROOT / "web" / "dashboard" / "views" / "bibliotheque.js"


class EnrichReturnsTmdbIdsTests(unittest.TestCase):
    def test_backend_enrich_returns_ids_map(self) -> None:
        src = _TMDB.read_text(encoding="utf-8")
        self.assertIn("resolved_ids[rid] = tid", src, "enrich doit collecter les tmdb_id resolus.")
        self.assertIn('"ids": resolved_ids', src, "enrich doit renvoyer le map ids:{row_id:tmdb_id}.")

    def test_frontend_patches_tmdb_id(self) -> None:
        src = _BIB.read_text(encoding="utf-8")
        self.assertIn("d.ids", src, "le client doit lire d.ids renvoye par enrich.")
        self.assertIn("r.tmdb_id = idMap[rid]", src, "le client doit patcher r.tmdb_id en memoire.")

    def test_frontend_precise_not_configured_message(self) -> None:
        src = _BIB.read_text(encoding="utf-8")
        self.assertIn('d.reason === "tmdb_not_configured"', src)
        self.assertIn("Clé TMDb non configurée", src)


if __name__ == "__main__":
    unittest.main()
