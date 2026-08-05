"""GATE AUDIT 2026-06-14 (R7-1) — KPI header Qualite (ex-QIJ).

get_global_stats niche total_films/avg_score/premium_pct/trend sous summary.* ;
le front les lisait a la racine -> KPI toujours 0 et fleche toujours '→'.

Lot C (verif totale 2026-07) : la vue qij.js a ete supprimee (R8) — le
consommateur actuel de summary.* est views/qualite.js. Test repointe ; la
partie trend-glyphe reste verifiee cote backend (dashboard_support produit
directement des glyphes, jamais 'up'/'down').
"""

from __future__ import annotations

import unittest
from pathlib import Path

_QUALITE = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "qualite.js"
_DASH = Path(__file__).resolve().parents[1] / "cinesort" / "ui" / "api" / "dashboard_support.py"


class QijKpiSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qualite = _QUALITE.read_text(encoding="utf-8")
        cls.dash = _DASH.read_text(encoding="utf-8")

    def test_backend_nests_under_summary(self) -> None:
        # Garde-fou : la structure attendue par le front existe cote backend.
        self.assertIn('"summary": {', self.dash)
        self.assertIn('"total_films": total_films', self.dash)

    def test_front_reads_summary(self) -> None:
        self.assertIn("stats.summary.avg_score", self.qualite)
        self.assertIn("stats.summary.total_films", self.qualite)
        # Regression R7-1 : plus aucune lecture racine des KPI.
        self.assertNotIn("stats.avg_score", self.qualite)
        self.assertNotIn("stats.total_films", self.qualite)

    def test_backend_trend_is_glyph(self) -> None:
        # summary.trend est un glyphe pret a afficher, pas 'up'/'down'.
        self.assertIn('"trend": "→"', self.dash)
        self.assertNotIn('"trend": "up"', self.dash)


if __name__ == "__main__":
    unittest.main()
