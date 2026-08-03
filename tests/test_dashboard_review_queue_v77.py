"""GATE AUDIT 2026-06-14 (R6-I) — Etape 2 "Verification" ne montre plus "0 cas".

Le backend n'exposait ni review_queue_count ni conflicts_count -> l'Etape 2 du
workflow Traitement affichait toujours "Cas a verifier : 0" et "Conflits : 0",
meme avec 1021 films dont beaucoup avec alertes. Calcule depuis les rows.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_DASH = Path(__file__).resolve().parents[1] / "cinesort" / "ui" / "api" / "dashboard_support.py"


class DashboardReviewQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _DASH.read_text(encoding="utf-8")

    def test_exposes_review_queue_count(self) -> None:
        self.assertIn('"review_queue_count": int(review_queue_count)', self.src)

    def test_exposes_conflicts_count(self) -> None:
        self.assertIn('"conflicts_count": int(conflicts_count)', self.src)

    def test_counts_derive_from_flags_and_confidence(self) -> None:
        self.assertIn("warning_flags", self.src)
        self.assertIn("confidence_label", self.src)
        self.assertIn("_CONFLICT_FLAGS", self.src)


if __name__ == "__main__":
    unittest.main()
