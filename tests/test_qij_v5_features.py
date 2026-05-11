"""V5A-06 — Vérifie qij-v5 enrichi avec V1-05 + V3-03 + V2-08."""

from __future__ import annotations

import unittest
from pathlib import Path


class QijV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/qij-v5.js").read_text(encoding="utf-8")

    def test_v1_05_empty_state_quality(self):
        self.assertIn("buildEmptyState", self.src)
        self.assertIn("Lancer un scan", self.src)
        self.assertIn("_renderQualityEmpty", self.src)

    def test_v3_03_glossary_tooltips(self):
        self.assertIn("glossaryTooltip", self.src)
        # Au moins 5 occurrences (définition + appels)
        self.assertGreaterEqual(self.src.count("glossaryTooltip("), 5)

    def test_v2_08_skeleton_complete(self):
        # V5bis-03 : _renderSkeleton renomme en _renderQualitySkeleton (port ES module).
        self.assertIn("_renderQualitySkeleton", self.src)
        self.assertIn("v5-qij-skeleton", self.src)
        # Skeleton appelé au boot
        self.assertRegex(self.src, r"_renderQualitySkeleton\(.*?\)")


if __name__ == "__main__":
    unittest.main()
