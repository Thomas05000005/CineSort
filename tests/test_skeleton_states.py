"""V2-08 — verifie que les vues critiques ont un skeleton state."""

from pathlib import Path
import unittest


class SkeletonStatesTests(unittest.TestCase):
    # V5C-01 : retire library/, runs.js, review.js, quality.js (vues v4 supprimees).
    # Les vues v5 (library-v5, processing, qij-v5) sont couvertes par les tests v5
    # dedies (test_v5b_activation, test_processing_v5_ported, etc.).
    EXPECTED_VIEWS_WITH_SKELETON = [
        "web/dashboard/views/jellyfin.js",
        "web/dashboard/views/plex.js",
        "web/dashboard/views/radarr.js",
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
