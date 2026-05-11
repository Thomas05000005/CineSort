"""V4-05 — Garantit que les scores Lighthouse ne regressent pas.

Skip si `audit/results/lighthouse/summary.json` est absent (CI sans Node.js,
ou audit pas encore lance). Pour generer le summary :

    .venv313/Scripts/python.exe scripts/run_lighthouse.py <token>
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


# Seuils baseline (inferieurs aux scores observes pour servir de garde-fou
# anti-regression). V4-09 a corrige les a11y/BP differes (aria-current,
# nav-badge role, topbarAvatar mismatch, favicon SVG inline, CSP frame-ancestors
# en HTTP header).
# Baseline 2026-05-02 : perf 62, a11y 96, BP 100.
# Cible perf en V5 : minifier CSS/JS pour passer >= 80.
THRESHOLDS = {
    "performance": 60,  # baseline 62 — bundle CSS/JS non-minifie
    "accessibility": 90,  # baseline 96 (V4-09 fixes)
    "best-practices": 95,  # baseline 100 (V4-09 fixes)
}


class LighthouseBaselineTests(unittest.TestCase):
    SUMMARY_PATH = Path("audit/results/lighthouse/summary.json")

    @classmethod
    def setUpClass(cls):
        if not cls.SUMMARY_PATH.is_file():
            raise unittest.SkipTest(
                f"Lighthouse summary missing ({cls.SUMMARY_PATH}). Lancer d'abord : python scripts/run_lighthouse.py"
            )
        cls.scores = json.loads(cls.SUMMARY_PATH.read_text(encoding="utf-8"))

    def test_performance(self):
        score = self.scores.get("performance", 0)
        self.assertGreaterEqual(
            score,
            THRESHOLDS["performance"],
            f"Performance {score} < {THRESHOLDS['performance']} (baseline V4-05)",
        )

    def test_accessibility(self):
        score = self.scores.get("accessibility", 0)
        self.assertGreaterEqual(
            score,
            THRESHOLDS["accessibility"],
            f"Accessibility {score} < {THRESHOLDS['accessibility']} (baseline V4-05)",
        )

    def test_best_practices(self):
        score = self.scores.get("best-practices", 0)
        self.assertGreaterEqual(
            score,
            THRESHOLDS["best-practices"],
            f"Best Practices {score} < {THRESHOLDS['best-practices']} (baseline V4-05)",
        )


if __name__ == "__main__":
    unittest.main()
