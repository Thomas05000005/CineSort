"""GATE AUDIT 2026-06-14 (R6-F) — Qualité/Accueil = distribution du DERNIER run.

Avant : get_global_stats agrégeait la distribution sur 20 runs (cumul) et
qualite.js préférait la V2 perceptuelle (partielle) -> page Qualité fausse
("~1249 films, 100% Bronze, Santé 0%") alors que la Biblio (V1 dernier run)
montrait la vraie répartition (Platinum 49 / Gold 102 / Silver 326 / Bronze /
Reject). Vérifié sur la vraie base : limit_runs=1 -> 965 films (= Biblio) ;
limit_runs=20 -> 3050 (cumul de 3 runs).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DASH = _ROOT / "cinesort" / "ui" / "api" / "dashboard_support.py"
_QUALITE = _ROOT / "web" / "dashboard" / "views" / "qualite.js"


class QualiteDistributionLatestRunTests(unittest.TestCase):
    def test_backend_v1_distribution_latest_run_only(self) -> None:
        src = _DASH.read_text(encoding="utf-8")
        self.assertIn(
            "get_global_tier_distribution(limit_runs=1)", src,
            "La distribution V1 'etat courant' doit cibler le dernier run (limit_runs=1).",
        )

    def test_backend_v2_distribution_latest_run_only(self) -> None:
        src = _DASH.read_text(encoding="utf-8")
        self.assertIn(
            "_compute_v2_tier_distribution(store, run_ids[:1])", src,
            "La distribution V2 doit cibler le dernier run (run_ids[:1]), pas le cumul.",
        )

    def test_frontend_prefers_v1_complete(self) -> None:
        src = _QUALITE.read_text(encoding="utf-8")
        m = re.search(r"function _resolveTierDist\(stats\)\s*\{(.+?)\n\}", src, re.DOTALL)
        self.assertIsNotNone(m, "_resolveTierDist introuvable")
        body = m.group(1)
        # La V1 (tier_distribution) doit etre testee AVANT la V2.
        idx_v1 = body.find("tier_distribution")
        idx_v2 = body.find("v2_tier_distribution")
        self.assertGreaterEqual(idx_v1, 0)
        self.assertGreaterEqual(idx_v2, 0)
        self.assertLess(idx_v1, idx_v2, "La V1 complete doit etre preferee a la V2 partielle.")


if __name__ == "__main__":
    unittest.main()
