"""GATE AUDIT 2026-06-14 (R6-I) — "Confiance moyenne" de l'accueil.

L'accueil lisait latestRun.avg_confidence_pct, champ absent de runs_history ->
affichait toujours "—". Le backend calcule desormais confidence_avg (moyenne
des PlanRow.confidence) et l'expose dans kpis ; l'accueil lit kpis.confidence_avg.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DASH = _ROOT / "cinesort" / "ui" / "api" / "dashboard_support.py"
_ACCUEIL = _ROOT / "web" / "dashboard" / "views" / "accueil.js"


class DashboardConfidenceAvgTests(unittest.TestCase):
    def test_backend_computes_and_exposes_confidence_avg(self) -> None:
        src = _DASH.read_text(encoding="utf-8")
        self.assertIn('getattr(r, "confidence"', src, "confidence_avg doit etre calcule depuis PlanRow.confidence.")
        self.assertIn('"confidence_avg": confidence_avg', src, "confidence_avg doit etre expose dans kpis.")

    def test_frontend_reads_kpis_confidence_avg(self) -> None:
        src = _ACCUEIL.read_text(encoding="utf-8")
        self.assertIn("kpis.confidence_avg", src, "L'accueil doit lire kpis.confidence_avg.")


if __name__ == "__main__":
    unittest.main()
