"""V5A-07 — Verifie library-v5 + film-detail enrichis avec V2-04 + V2-08 + V3-06."""

from __future__ import annotations

import unittest
from pathlib import Path


class LibraryV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/library-v5.js").read_text(encoding="utf-8")

    def test_v2_04_promise_allsettled(self):
        self.assertIn("Promise.allSettled", self.src)

    def test_v2_08_skeleton(self):
        # V5bis-02 : le skeleton est rendu via renderSkeleton(container, "grid")
        # du helper partage _v5_helpers.js (plus de _renderLibrarySkeleton inline).
        self.assertIn("renderSkeleton", self.src)
        self.assertIn('"grid"', self.src)


class FilmDetailV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/film-detail.js").read_text(encoding="utf-8")

    def test_v2_04_promise_allsettled(self):
        self.assertIn("Promise.allSettled", self.src)

    def test_v2_08_skeleton(self):
        self.assertIn("_renderFilmDetailSkeleton", self.src)
        self.assertIn("v5-film-detail-skeleton", self.src)

    def test_v3_06_drawer_mode(self):
        self.assertIn("v5-film-drawer", self.src)
        self.assertIn("max-width: 767px", self.src)
        self.assertIn("mountFilmDetailDrawer", self.src)


if __name__ == "__main__":
    unittest.main()
