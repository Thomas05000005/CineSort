"""Tests §11 v7.5.0 — LPIPS (distance perceptuelle ONNX)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from cinesort.domain.perceptual.lpips_compare import (
    LpipsResult,
    _resize_bilinear,
    classify_lpips_verdict,
    compute_lpips_comparison,
    compute_lpips_distance_pair,
    preprocess_frame_for_lpips,
    reset_session_cache,
)


# ---------------------------------------------------------------------------
# classify_lpips_verdict
# ---------------------------------------------------------------------------


class TestClassifyVerdict(unittest.TestCase):
    def test_none_insufficient(self):
        self.assertEqual(classify_lpips_verdict(None), "insufficient_data")

    def test_identical(self):
        self.assertEqual(classify_lpips_verdict(0.0), "identical")
        self.assertEqual(classify_lpips_verdict(0.04), "identical")

    def test_very_similar(self):
        self.assertEqual(classify_lpips_verdict(0.05), "very_similar")
        self.assertEqual(classify_lpips_verdict(0.14), "very_similar")

    def test_similar(self):
        self.assertEqual(classify_lpips_verdict(0.15), "similar")
        self.assertEqual(classify_lpips_verdict(0.29), "similar")

    def test_different(self):
        self.assertEqual(classify_lpips_verdict(0.30), "different")
        self.assertEqual(classify_lpips_verdict(0.49), "different")

    def test_very_different(self):
        self.assertEqual(classify_lpips_verdict(0.50), "very_different")
        self.assertEqual(classify_lpips_verdict(1.0), "very_different")


# ---------------------------------------------------------------------------
# preprocess_frame_for_lpips
# ---------------------------------------------------------------------------


class TestPreprocessFrame(unittest.TestCase):
    def test_returns_shape_1_3_256_256(self):
        pixels = [128] * (64 * 64)
        out = preprocess_frame_for_lpips(pixels, 64, 64, target_size=256)
        self.assertIsNotNone(out)
        self.assertEqual(out.shape, (1, 3, 256, 256))

    def test_normalization_range_minus1_plus1(self):
        pixels = [0, 255] * (32 * 32 // 2)
        out = preprocess_frame_for_lpips(pixels, 32, 32)
        self.assertIsNotNone(out)
        self.assertGreaterEqual(float(out.min()), -1.001)
        self.assertLessEqual(float(out.max()), 1.001)

    def test_rgb_channels_identical(self):
        pixels = [50] * (16 * 16)
        out = preprocess_frame_for_lpips(pixels, 16, 16, target_size=16)
        self.assertIsNotNone(out)
        np.testing.assert_array_equal(out[0, 0], out[0, 1])
        np.testing.assert_array_equal(out[0, 1], out[0, 2])

    def test_dtype_float32(self):
        pixels = [100] * (8 * 8)
        out = preprocess_frame_for_lpips(pixels, 8, 8, target_size=16)
        self.assertEqual(out.dtype, np.float32)

    def test_empty_pixels(self):
        self.assertIsNone(preprocess_frame_for_lpips([], 0, 0))

    def test_mismatched_size(self):
        # 100 pixels annonces pour 10x10 mais seulement 50 fournis
        self.assertIsNone(preprocess_frame_for_lpips([0] * 50, 10, 10))

    def test_invalid_dimensions(self):
        self.assertIsNone(preprocess_frame_for_lpips([0] * 100, -1, 10))
        self.assertIsNone(preprocess_frame_for_lpips([0] * 100, 10, 0))


# ---------------------------------------------------------------------------
# _resize_bilinear
# ---------------------------------------------------------------------------


class TestResizeBilinear(unittest.TestCase):
    def test_identity_when_same_size(self):
        img = np.arange(16, dtype=np.float32).reshape(4, 4)
        out = _resize_bilinear(img, 4)
        np.testing.assert_array_almost_equal(out, img)

    def test_upscale_doubles_dimensions(self):
        img = np.array([[0, 100], [100, 200]], dtype=np.float32)
        out = _resize_bilinear(img, 4)
        self.assertEqual(out.shape, (4, 4))

    def test_downscale_halves(self):
        img = np.arange(64, dtype=np.float32).reshape(8, 8)
        out = _resize_bilinear(img, 4)
        self.assertEqual(out.shape, (4, 4))


# ---------------------------------------------------------------------------
# compute_lpips_distance_pair (onnxruntime absent → None gracieux)
# ---------------------------------------------------------------------------


class TestDistancePair(unittest.TestCase):
    def setUp(self):
        reset_session_cache()

    def test_none_when_shapes_differ(self):
        a = np.zeros((1, 3, 256, 256), dtype=np.float32)
        b = np.zeros((1, 3, 128, 128), dtype=np.float32)
        self.assertIsNone(compute_lpips_distance_pair(a, b))

    def test_none_when_input_none(self):
        a = np.zeros((1, 3, 256, 256), dtype=np.float32)
        self.assertIsNone(compute_lpips_distance_pair(None, a))
        self.assertIsNone(compute_lpips_distance_pair(a, None))

    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=False)
    def test_none_when_ort_absent(self, _mock):
        a = np.zeros((1, 3, 256, 256), dtype=np.float32)
        self.assertIsNone(compute_lpips_distance_pair(a, a))


# ---------------------------------------------------------------------------
# compute_lpips_comparison (orchestrateur)
# ---------------------------------------------------------------------------


class TestComparison(unittest.TestCase):
    def setUp(self):
        reset_session_cache()

    def test_empty_aligned_returns_insufficient(self):
        r = compute_lpips_comparison([])
        self.assertIsNone(r.distance_median)
        self.assertEqual(r.verdict, "insufficient_data")
        self.assertEqual(r.n_pairs_evaluated, 0)

    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=False)
    def test_ort_absent_returns_insufficient(self, _mock):
        aligned = [{"pixels_a": [50] * 64, "pixels_b": [50] * 64, "width": 8, "height": 8, "timestamp": 0.0}] * 3
        r = compute_lpips_comparison(aligned)
        self.assertIsNone(r.distance_median)
        self.assertEqual(r.verdict, "insufficient_data")

    @patch("cinesort.domain.perceptual.lpips_compare._resolve_model_path", return_value=None)
    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=True)
    def test_missing_model_returns_insufficient(self, _mock_ort, _mock_path):
        aligned = [{"pixels_a": [50] * 64, "pixels_b": [50] * 64, "width": 8, "height": 8}]
        r = compute_lpips_comparison(aligned)
        self.assertIsNone(r.distance_median)
        self.assertEqual(r.verdict, "insufficient_data")

    @patch("cinesort.domain.perceptual.lpips_compare.compute_lpips_distance_pair")
    @patch("cinesort.domain.perceptual.lpips_compare._resolve_model_path")
    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=True)
    def test_median_of_5_pairs(self, _ort, _path, mock_dist):
        _path.return_value = "fake/path.onnx"
        # Distances : 0.1, 0.2, 0.3, 0.4, 0.5 → mediane = 0.3 (similar)
        mock_dist.side_effect = [0.1, 0.2, 0.3, 0.4, 0.5]
        aligned = [{"pixels_a": [100] * 64, "pixels_b": [120] * 64, "width": 8, "height": 8}] * 5
        r = compute_lpips_comparison(aligned, max_pairs=5)
        self.assertEqual(r.n_pairs_evaluated, 5)
        self.assertAlmostEqual(r.distance_median, 0.3, places=3)
        self.assertEqual(r.verdict, "different")

    @patch("cinesort.domain.perceptual.lpips_compare.compute_lpips_distance_pair")
    @patch("cinesort.domain.perceptual.lpips_compare._resolve_model_path")
    @patch("cinesort.domain.perceptual.lpips_compare._is_ort_available", return_value=True)
    def test_limits_to_max_pairs(self, _ort, _path, mock_dist):
        _path.return_value = "fake/path.onnx"
        mock_dist.return_value = 0.1
        aligned = [{"pixels_a": [100] * 64, "pixels_b": [100] * 64, "width": 8, "height": 8}] * 10
        r = compute_lpips_comparison(aligned, max_pairs=3)
        self.assertEqual(r.n_pairs_evaluated, 3)
        self.assertEqual(mock_dist.call_count, 3)


# ---------------------------------------------------------------------------
# LpipsResult dataclass
# ---------------------------------------------------------------------------


class TestLpipsResult(unittest.TestCase):
    def test_frozen_dataclass(self):
        r = LpipsResult(distance_median=0.1, distances_per_pair=[0.1], verdict="very_similar", n_pairs_evaluated=1)
        with self.assertRaises(Exception):
            r.verdict = "identical"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Integration : build_comparison_report avec lpips_result
# ---------------------------------------------------------------------------


class TestComparisonReportIntegration(unittest.TestCase):
    def _min_perceptual(self) -> dict:
        return {
            "video_perceptual": {
                "blockiness": {"mean": 0},
                "blur": {"mean": 0},
                "banding": {"mean_score": 0},
                "effective_bit_depth": {"mean_bits": 8},
                "local_variance": {"mean_variance": 0},
            },
            "audio_perceptual": {
                "ebu_r128": {"loudness_range": 0},
                "astats": {"noise_floor": 0},
                "clipping": {"clipping_pct": 0},
            },
            "global_score": 50,
        }

    def test_without_lpips_result(self):
        from cinesort.domain.perceptual.comparison import build_comparison_report

        r = build_comparison_report(
            self._min_perceptual(),
            self._min_perceptual(),
            [],
            "a.mkv",
            "b.mkv",
            lpips_result=None,
        )
        lpips_criteria = [c for c in r["criteria"] if "LPIPS" in c["criterion"]]
        self.assertEqual(lpips_criteria, [])

    def test_with_lpips_result_adds_criterion(self):
        from cinesort.domain.perceptual.comparison import build_comparison_report

        lr = LpipsResult(
            distance_median=0.12,
            distances_per_pair=[0.1, 0.12, 0.14],
            verdict="very_similar",
            n_pairs_evaluated=3,
        )
        r = build_comparison_report(
            self._min_perceptual(),
            self._min_perceptual(),
            [],
            "a.mkv",
            "b.mkv",
            lpips_result=lr,
        )
        lpips_criteria = [c for c in r["criteria"] if "LPIPS" in c["criterion"]]
        self.assertEqual(len(lpips_criteria), 1)
        c = lpips_criteria[0]
        self.assertEqual(c["winner"], "tie")
        self.assertIn("very_similar", c["value_b"])
        self.assertIn("similaires", c["detail_fr"].lower())
        self.assertEqual(c["n_pairs"], 3)

    def test_with_lpips_insufficient_no_criterion(self):
        from cinesort.domain.perceptual.comparison import build_comparison_report

        lr = LpipsResult(
            distance_median=None,
            distances_per_pair=[],
            verdict="insufficient_data",
            n_pairs_evaluated=0,
        )
        r = build_comparison_report(
            self._min_perceptual(),
            self._min_perceptual(),
            [],
            "a.mkv",
            "b.mkv",
            lpips_result=lr,
        )
        lpips_criteria = [c for c in r["criteria"] if "LPIPS" in c["criterion"]]
        self.assertEqual(lpips_criteria, [])


if __name__ == "__main__":
    unittest.main()
