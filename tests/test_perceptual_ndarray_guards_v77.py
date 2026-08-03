"""GATE AUDIT 2026-06-10 (CRITICAL) — les fonctions d'analyse pixel acceptent un
np.ndarray sans lever ValueError ("truth value of an array... is ambiguous").

Depuis le refactor B3, frame_extraction.parse_raw_frame retourne un np.ndarray.
Les fonctions typees List[int] faisaient `if not pixels:` / `if pixels:` ->
ValueError sur ndarray multi-elements -> toute l'analyse video perceptuelle
(grain, banding, variance, deep-compare) plantait silencieusement.
"""

from __future__ import annotations

import unittest

import numpy as np

from cinesort.domain.perceptual.grain_analysis import analyze_grain, estimate_grain
from cinesort.domain.perceptual.video_analysis import (
    _aggregate_pixel_metrics,
    block_variance_stats,
    luminance_histogram,
)


def _frame_ndarray(w: int = 64, h: int = 64, value: int = 100) -> np.ndarray:
    return np.full(w * h, value, dtype=np.int64)


class PerceptualNdarrayGuardTests(unittest.TestCase):
    def test_luminance_histogram_accepts_ndarray(self) -> None:
        arr = _frame_ndarray()
        hist = luminance_histogram(arr, bit_depth=8)  # ne doit PAS lever
        self.assertEqual(len(hist), 256)
        self.assertEqual(hist[100], 64 * 64)

    def test_luminance_histogram_empty_ndarray(self) -> None:
        hist = luminance_histogram(np.array([], dtype=np.int64), bit_depth=8)
        self.assertEqual(sum(hist), 0)

    def test_block_variance_accepts_ndarray(self) -> None:
        arr = _frame_ndarray(64, 64, 100)
        out = block_variance_stats(arr, 64, 64, bit_depth=8)  # ne doit PAS lever
        self.assertIn("mean_variance", out)

    def test_estimate_grain_accepts_ndarray(self) -> None:
        arr = _frame_ndarray(64, 64, 100)
        out = estimate_grain(arr, 64, 64, bit_depth=8)  # ne doit PAS lever
        self.assertIn("grain_level", out)

    def test_aggregate_pixel_metrics_with_ndarray(self) -> None:
        # C'est le site exact du crash (video_analysis.py _aggregate_pixel_metrics
        # `if pixels:` sur ndarray).
        frames = [{"pixels": _frame_ndarray(64, 64, 80), "width": 64, "height": 64, "y_avg": 80.0}]
        out = _aggregate_pixel_metrics(frames, 8, 64, 64, 1.5)  # ne doit PAS lever
        self.assertEqual(len(out["variances"]), 1)

    def test_analyze_grain_with_ndarray_pixels(self) -> None:
        frames = [{"pixels": _frame_ndarray(64, 64, 80), "width": 64, "height": 64}]
        result = analyze_grain(frames, bit_depth=8)  # ne doit PAS lever
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
