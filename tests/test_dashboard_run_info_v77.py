"""GATE AUDIT 2026-06-14 (R7-7) — progression scan exposee par get_dashboard.

accueil.js _extractScanProgress lit payload.run_info (total_rows/current_index/
phase/status) mais get_dashboard ne produisait jamais run_info -> "Scan en cours
sur 0 films (0/0)" barre figee. Ajout d'un bloc run_info depuis le RunState actif.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_DASH = Path(__file__).resolve().parents[1] / "cinesort" / "ui" / "api" / "dashboard_support.py"


class DashboardRunInfoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _DASH.read_text(encoding="utf-8")

    def test_helper_exists(self):
        self.assertIn("def _active_run_info(api", self.src)
        self.assertIn('"current_index": int(getattr(rs, "idx", 0)', self.src)
        self.assertIn('"total_rows": int(getattr(rs, "total", 0)', self.src)

    def test_both_returns_expose_run_info(self):
        self.assertEqual(self.src.count('"run_info": _active_run_info(api)'), 2)


if __name__ == "__main__":
    unittest.main()
