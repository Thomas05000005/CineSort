"""GATE AUDIT 2026-06-14 (R7-1) — KPI header Qualite/QIJ.

get_global_stats niche total_films/avg_score/premium_pct/trend sous summary.* ;
le front les lisait a la racine -> KPI toujours 0 et fleche toujours '→'.
summary.trend est deja un glyphe (↑/↓/→), pas 'up'/'down'.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_QIJ = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "qij.js"
_DASH = Path(__file__).resolve().parents[1] / "cinesort" / "ui" / "api" / "dashboard_support.py"


class QijKpiSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qij = _QIJ.read_text(encoding="utf-8")
        cls.dash = _DASH.read_text(encoding="utf-8")

    def test_backend_nests_under_summary(self) -> None:
        # Garde-fou : la structure attendue par le front existe cote backend.
        self.assertIn('"summary": {', self.dash)
        self.assertIn('"total_films": total_films', self.dash)

    def test_front_reads_summary(self) -> None:
        self.assertIn("const s = stats.summary || {}", self.qij)
        self.assertIn("s.avg_score", self.qij)
        self.assertIn("s.premium_pct", self.qij)
        self.assertIn("s.total_films", self.qij)

    def test_front_trend_is_glyph(self) -> None:
        self.assertIn('const trendArrow = s.trend || "→"', self.qij)
        self.assertNotIn('stats.trend === "up"', self.qij)


if __name__ == "__main__":
    unittest.main()
