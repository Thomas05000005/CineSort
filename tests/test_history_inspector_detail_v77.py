"""GATE AUDIT 2026-06-14 (R7-6) — Inspecteur Historique : films + doublons.

_get_history_stats_impl ne renvoyait ni films, ni duplicates_decided/skipped ->
onglets "Films"/"Doublons" vides ("detail non disponible") et recherche par titre
inerte. On enrichit le dict run depuis quality_reports + plan + decisions.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_H = Path(__file__).resolve().parents[1] / "cinesort" / "ui" / "api" / "history_support.py"


class HistoryInspectorDetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _H.read_text(encoding="utf-8")

    def test_re_imported(self):
        self.assertIn("\nimport re\n", self.src)

    def test_films_built_from_quality_and_plan(self):
        self.assertIn("films: List[Dict[str, Any]] = []", self.src)
        self.assertIn("api.run.get_plan(run_id)", self.src)
        self.assertIn('"film_id": rid', self.src)

    def test_duplicates_from_decisions(self):
        self.assertIn("list_duplicate_decisions(run_id=run_id)", self.src)
        self.assertIn('"duplicates_decided": duplicates_decided', self.src)

    def test_keys_in_run_dict(self):
        self.assertIn('"films": films', self.src)
        self.assertIn('"duplicates_skipped": []', self.src)


if __name__ == "__main__":
    unittest.main()
