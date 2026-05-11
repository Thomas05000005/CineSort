"""V5A-05 — Verifie processing.js v5 enrichi avec 5 features V1-V4.

Tests structurels (lecture du fichier source) — pas d'execution JS.
"""

from __future__ import annotations

import unittest
from pathlib import Path


class ProcessingV5FeaturesTests(unittest.TestCase):
    """Couvre les 5 features V1-V4 portees dans web/views/processing.js."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = Path("web/views/processing.js").read_text(encoding="utf-8")

    def test_v2_04_promise_allsettled(self) -> None:
        """V2-04 : Promise.allSettled present pour la resilience reseau."""
        self.assertIn("Promise.allSettled", self.src)

    def test_v2_08_skeleton(self) -> None:
        """V2-08 : skeleton states pour les 3 steps (scan/review/apply)."""
        self.assertIn("v5-skeleton", self.src)
        self.assertIn("_renderSkeleton", self.src)

    def test_v2_07_emptystate_imported(self) -> None:
        """V2-07 : composant EmptyState integre."""
        self.assertIn("buildEmptyState", self.src)

    def test_v2_03_draft_auto(self) -> None:
        """V2-03 : draft auto validation avec localStorage + restore banner."""
        self.assertIn("DRAFT_KEY_PREFIX", self.src)
        self.assertIn("_scheduleDraftSave", self.src)
        self.assertIn("_loadDraft", self.src)
        self.assertIn("localStorage", self.src)
        self.assertIn("_checkAndOfferRestore", self.src)

    def test_v3_06_drawer_mobile(self) -> None:
        """V3-06 : drawer mobile inspector pour les ecrans < 768px."""
        self.assertIn("v5ProcessingInspectorDrawer", self.src)
        self.assertIn("v5-drawer", self.src)
        self.assertIn("min-width: 768px", self.src)


if __name__ == "__main__":
    unittest.main()
