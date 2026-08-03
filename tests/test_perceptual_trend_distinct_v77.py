"""GATE AUDIT 2026-06-14 (R7-15) — compteurs trend/insight perceptuels DISTINCT.

get_global_score_v2_trend et count_v2_tier_since utilisaient COUNT(*) ->
re-scanner la meme biblio (nouveau run_id, memes row_id) comptait chaque film
plusieurs fois. Passe a COUNT(DISTINCT row_id).
"""

from __future__ import annotations

import unittest
from pathlib import Path

_PERC = Path(__file__).resolve().parents[1] / "cinesort" / "infra" / "db" / "repositories" / "perceptual.py"


class PerceptualTrendDistinctTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _PERC.read_text(encoding="utf-8")

    def test_trend_distinct(self):
        self.assertIn("COUNT(DISTINCT row_id) as n", self.src)

    def test_tier_since_distinct(self):
        self.assertIn("SELECT COUNT(DISTINCT row_id) FROM perceptual_reports", self.src)


if __name__ == "__main__":
    unittest.main()
