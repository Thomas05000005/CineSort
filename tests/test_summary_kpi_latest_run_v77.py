"""GATE AUDIT 2026-06-14 (R7-5) — summary KPI = dernier run (complement R6-F).

total_films/avg_score/premium_pct etaient cumules sur lim runs (defaut 20) ->
un film present dans N scans compte N fois. On les scope au dernier run.
"""
from __future__ import annotations
import unittest
from pathlib import Path

_DASH = Path(__file__).resolve().parents[1] / "cinesort" / "ui" / "api" / "dashboard_support.py"


class SummaryKpiLatestRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _DASH.read_text(encoding="utf-8")

    def test_total_films_from_latest_run(self) -> None:
        self.assertIn("latest_summary.get(\"total_rows\", 0)) if latest_summary", self.src)

    def test_scores_from_latest_qc(self) -> None:
        self.assertIn("latest_qc = quality_counts.get(latest_rid, {})", self.src)
        self.assertIn("avg_score = float(latest_qc.get(\"score_avg\"", self.src)

    def test_no_longer_sums_all_runs(self) -> None:
        self.assertNotIn("total_films = sum(r.get(\"total_rows\", 0) for r in runs_summary)", self.src)


if __name__ == "__main__":
    unittest.main()
