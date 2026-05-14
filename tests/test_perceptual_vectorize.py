"""Tests/benchmarks pour la vectorisation perceptual (issue #74).

Verifie :
1. Equivalence numerique avec la version pure Python (sur petites tailles).
2. Performance : la version numpy doit etre dramatiquement plus rapide sur
   les tailles realistes (1920x1080) — borne lache pour eviter les flakies.
"""

from __future__ import annotations

import math
import random
import time
import unittest

import numpy as np

from cinesort.domain.perceptual.comparison import compute_pixel_diff
from cinesort.domain.perceptual.frame_extraction import is_valid_frame
from cinesort.domain.perceptual.grain_analysis import estimate_grain
from cinesort.domain.perceptual.grain_classifier import find_flat_zones


def _pure_py_is_valid_frame(pixels, width, height, bit_depth=8):
    """Reference pure Python (pre-#74)."""
    from cinesort.domain.perceptual.constants import (
        FRAME_MIN_VARIANCE_8BIT,
        FRAME_MIN_VARIANCE_10BIT,
    )

    expected_count = int(width) * int(height)
    if len(pixels) < int(expected_count * 0.9):
        return False
    if not pixels:
        return False
    n = len(pixels)
    mean = sum(pixels) / n
    variance = sum((p - mean) ** 2 for p in pixels) / n
    threshold = FRAME_MIN_VARIANCE_10BIT if bit_depth >= 10 else FRAME_MIN_VARIANCE_8BIT
    return variance >= threshold


def _pure_py_compute_pixel_diff(pixels_a, pixels_b):
    if len(pixels_a) != len(pixels_b) or not pixels_a:
        return None
    diffs = [abs(a - b) for a, b in zip(pixels_a, pixels_b)]
    n = len(diffs)
    mean_d = sum(diffs) / n
    max_d = max(diffs)
    sorted_d = sorted(diffs)
    median_d = sorted_d[n // 2]
    stddev_d = math.sqrt(sum((d - mean_d) ** 2 for d in diffs) / n) if n > 1 else 0.0
    return {
        "mean_diff": round(mean_d, 2),
        "stddev_diff": round(stddev_d, 2),
        "max_diff": max_d,
        "median_diff": median_d,
    }


class NumericalEquivalenceTests(unittest.TestCase):
    """Verifie que la version numpy retourne les MEMES valeurs que la version pure Python."""

    def test_is_valid_frame_matches_pure_python(self) -> None:
        random.seed(42)
        w, h = 100, 100
        pixels = [random.randint(0, 255) for _ in range(w * h)]
        self.assertEqual(is_valid_frame(pixels, w, h), _pure_py_is_valid_frame(pixels, w, h))

    def test_is_valid_frame_low_variance(self) -> None:
        # Frame quasi-uniforme → invalide
        w, h = 50, 50
        pixels = [128] * (w * h)
        self.assertFalse(is_valid_frame(pixels, w, h))
        self.assertEqual(is_valid_frame(pixels, w, h), _pure_py_is_valid_frame(pixels, w, h))

    def test_compute_pixel_diff_matches_pure_python(self) -> None:
        random.seed(123)
        a = [random.randint(0, 255) for _ in range(10_000)]
        b = [random.randint(0, 255) for _ in range(10_000)]
        out_numpy = compute_pixel_diff(a, b)
        out_python = _pure_py_compute_pixel_diff(a, b)
        self.assertIsNotNone(out_numpy)
        self.assertIsNotNone(out_python)
        # Tolerance flottante 0.01 (round 2 decimales sur les 2 cotes)
        self.assertAlmostEqual(out_numpy["mean_diff"], out_python["mean_diff"], places=2)
        self.assertAlmostEqual(out_numpy["stddev_diff"], out_python["stddev_diff"], places=2)
        self.assertEqual(out_numpy["max_diff"], out_python["max_diff"])
        self.assertEqual(out_numpy["median_diff"], out_python["median_diff"])

    def test_compute_pixel_diff_empty(self) -> None:
        self.assertIsNone(compute_pixel_diff([], []))
        self.assertIsNone(compute_pixel_diff([1, 2, 3], [1, 2]))

    def test_estimate_grain_returns_dict_with_expected_keys(self) -> None:
        random.seed(7)
        w, h = 64, 64  # 16 blocs 16x16
        pixels = [random.randint(0, 255) for _ in range(w * h)]
        out = estimate_grain(pixels, w, h, block_size=16)
        self.assertIn("grain_level", out)
        self.assertIn("grain_uniformity", out)
        self.assertIn("flat_zone_count", out)
        self.assertIsInstance(out["flat_zone_count"], int)

    def test_estimate_grain_uniform_frame_no_flat(self) -> None:
        # Frame parfaitement uniforme : variance = 0, donc < flat_thresh → 16 flat zones
        # Toutes ont stddev = 0 → mean_std = 0 → grain_level = 0
        w, h = 64, 64
        pixels = [200] * (w * h)
        out = estimate_grain(pixels, w, h, block_size=16)
        self.assertEqual(out["grain_level"], 0.0)
        self.assertEqual(out["grain_uniformity"], 1.0)
        self.assertEqual(out["flat_zone_count"], 16)

    def test_estimate_grain_returns_zero_for_too_small_frame(self) -> None:
        out = estimate_grain([1, 2, 3], 1, 3, block_size=16)
        self.assertEqual(out["grain_level"], 0.0)
        self.assertEqual(out["flat_zone_count"], 0)

    def test_find_flat_zones_uniform_frame(self) -> None:
        # Frame uniforme → toutes les zones sont plates, max_zones limite le retour
        frame = np.full((64, 64), 100.0, dtype=np.float64)
        zones = find_flat_zones(frame, block_size=16, flat_threshold=10.0, max_zones=4)
        self.assertEqual(len(zones), 4)
        # Verifie le format (y, x, h, w) avec h = w = block_size
        for y, x, hh, ww in zones:
            self.assertEqual(hh, 16)
            self.assertEqual(ww, 16)
            self.assertTrue(0 <= y < 64)
            self.assertTrue(0 <= x < 64)

    def test_find_flat_zones_no_flat(self) -> None:
        # Frame avec haute variance partout → aucune zone plate
        rng = np.random.default_rng(99)
        frame = rng.integers(0, 256, size=(64, 64)).astype(np.float64)
        zones = find_flat_zones(frame, block_size=16, flat_threshold=0.5, max_zones=10)
        self.assertEqual(zones, [])


class PerformanceSanityTests(unittest.TestCase):
    """Test de sanity perf : verifie que la version numpy n'est pas plus lente.

    Borne lache (factor 2 mini) pour ne pas etre flaky sur CI Windows. Sur un PC
    moderne le gain reel est 20-50x.
    """

    def test_is_valid_frame_numpy_faster_than_naive(self) -> None:
        random.seed(0)
        w, h = 320, 240  # 76800 pixels
        pixels = [random.randint(0, 255) for _ in range(w * h)]

        # Version numpy (actuelle)
        t0 = time.perf_counter()
        for _ in range(20):
            is_valid_frame(pixels, w, h)
        t_numpy = time.perf_counter() - t0

        # Version pure Python (de reference)
        t0 = time.perf_counter()
        for _ in range(20):
            _pure_py_is_valid_frame(pixels, w, h)
        t_python = time.perf_counter() - t0

        # Au moins 2x plus rapide. Sur 1920x1080 le ratio reel est 30x+.
        self.assertLess(
            t_numpy * 2, t_python, f"numpy={t_numpy:.3f}s python={t_python:.3f}s ratio={t_python / t_numpy:.1f}x"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
