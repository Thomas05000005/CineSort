"""V2-08 — verifie que les vues critiques ont un skeleton state."""

import unittest
from pathlib import Path


class SkeletonStatesTests(unittest.TestCase):
    # Phase 5 (purge verif totale) : jellyfin/plex/radarr.js supprimes (vues
    # mortes). On verifie desormais les VUES VIVANTES critiques (chargement > 1s).
    EXPECTED_VIEWS_WITH_SKELETON = [
        "web/dashboard/views/bibliotheque.js",
        "web/dashboard/views/processing.js",
        "web/dashboard/views/qualite.js",
    ]

    def test_views_have_skeleton_or_aria_busy(self):
        root = Path(__file__).resolve().parent.parent
        for rel in self.EXPECTED_VIEWS_WITH_SKELETON:
            src = (root / rel).read_text(encoding="utf-8")
            has_skeleton = "skeleton" in src.lower() or "aria-busy" in src
            self.assertTrue(has_skeleton, f"{rel} : ni skeleton ni aria-busy trouve")

    def test_css_skeleton_classes_defined(self):
        root = Path(__file__).resolve().parent.parent
        css_files = list(root.glob("web/**/*.css"))
        found = False
        for f in css_files:
            if ".skeleton" in f.read_text(encoding="utf-8"):
                found = True
                break
        self.assertTrue(found, "CSS .skeleton non trouve")


if __name__ == "__main__":
    unittest.main()
