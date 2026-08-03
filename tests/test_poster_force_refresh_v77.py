"""GATE AUDIT 2026-06-14 (R7-8) — "Recuperer jaquettes" re-telecharge vraiment.

Le proxy /api/poster sert un cache disque immuable (Cache-Control 30j) -> un
refresh ne changeait rien (toast "N recuperees" trompeur). Desormais :
- posterProxyUrl(id, size, bust) ajoute force=1&v=<bust> ;
- le proxy honore force -> supprime le cache disque (id,size) avant re-fetch ;
- la biblio pose row._posterBust apres refresh.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class PosterForceRefreshTests(unittest.TestCase):
    def test_dom_posterproxy_bust(self):
        js = (_ROOT / "web/dashboard/core/dom.js").read_text(encoding="utf-8")
        self.assertIn("export function posterProxyUrl(tmdbId, size, bust)", js)
        self.assertIn("&force=1&v=", js)

    def test_proxy_honors_force(self):
        py = (_ROOT / "cinesort/infra/integrations/poster_proxy.py").read_text(encoding="utf-8")
        self.assertIn('query.get("force")', py)
        self.assertIn('.glob(f"{tmdb_id}.*")', py)

    def test_biblio_sets_bust(self):
        js = (_ROOT / "web/dashboard/views/bibliotheque.js").read_text(encoding="utf-8")
        self.assertIn("row._posterBust", js)
        self.assertGreaterEqual(js.count("_posterBust = Date.now()"), 2)


if __name__ == "__main__":
    unittest.main()
