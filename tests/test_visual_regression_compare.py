"""Phase 4 v7.8.0 - tests unitaires de la fonction _compare_screenshots.

Le test E2E `test_09_visual_regression.py` ne tourne qu'avec Playwright +
serveur REST + dashboard live, donc en pratique jamais en CI. On ajoute
ici des tests unitaires PURS sur la fonction de comparaison pixel pour
verifier qu'elle detecte bien les regressions (et ne flag pas les images
identiques).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Charge le module e2e sans demarrer Playwright
_e2e_dir = Path(__file__).resolve().parent / "e2e"
if str(_e2e_dir) not in sys.path:
    sys.path.insert(0, str(_e2e_dir))


def _compare_screenshots(*args, **kwargs):
    # Lazy import to skip cleanly if PIL absent
    from tests.e2e.test_09_visual_regression import _compare_screenshots as _fn

    return _fn(*args, **kwargs)


try:
    from PIL import Image  # type: ignore[import-untyped]

    _PIL_OK = True
except ImportError:
    _PIL_OK = False


@unittest.skipUnless(_PIL_OK, "Pillow non installe")
class CompareScreenshotsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_visual_"))

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_identical_images_pass(self) -> None:
        img = Image.new("RGB", (100, 100), (200, 100, 50))
        a = self._tmp / "a.png"
        b = self._tmp / "b.png"
        img.save(a)
        img.save(b)
        ok, msg = _compare_screenshots(a, b)
        self.assertTrue(ok, msg=f"images identiques devraient passer: {msg}")

    def test_size_mismatch_fails(self) -> None:
        Image.new("RGB", (100, 100), (0, 0, 0)).save(self._tmp / "small.png")
        Image.new("RGB", (200, 200), (0, 0, 0)).save(self._tmp / "big.png")
        ok, msg = _compare_screenshots(self._tmp / "small.png", self._tmp / "big.png")
        self.assertFalse(ok)
        self.assertIn("size mismatch", msg)

    def test_minor_diff_within_tolerance(self) -> None:
        """Une difference < 2% des pixels doit passer."""
        img_a = Image.new("RGB", (100, 100), (200, 100, 50))
        img_b = img_a.copy()
        # Modifie 100 pixels sur 10000 (1%) -> sous le seuil 2%
        pixels = img_b.load()
        for i in range(100):
            pixels[i % 100, i // 100] = (0, 0, 0)
        a = self._tmp / "a.png"
        b = self._tmp / "b.png"
        img_a.save(a)
        img_b.save(b)
        ok, _ = _compare_screenshots(a, b)
        self.assertTrue(ok)

    def test_major_diff_fails(self) -> None:
        """Une difference > 2% des pixels doit etre detectee."""
        img_a = Image.new("RGB", (100, 100), (200, 100, 50))
        # img_b totalement different
        img_b = Image.new("RGB", (100, 100), (0, 0, 0))
        a = self._tmp / "a.png"
        b = self._tmp / "b.png"
        img_a.save(a)
        img_b.save(b)
        ok, msg = _compare_screenshots(a, b)
        self.assertFalse(ok)
        self.assertIn("diff", msg.lower())


if __name__ == "__main__":
    unittest.main()
