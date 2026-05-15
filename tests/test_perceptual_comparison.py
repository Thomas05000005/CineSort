"""Tests comparaison perceptuelle profonde — Phase VII (item 9.24).

Couvre :
- compute_pixel_diff : frames identiques, differentes
- compare_histograms : identiques, differents, detail winner
- compare_criterion : higher/lower is better, tie
- compare_per_frame : structure retournee
- build_comparison_report : gagnant, recommendation, criteria_summary
- endpoint compare_perceptual expose
"""

from __future__ import annotations

import unittest

from cinesort.domain.perceptual.comparison import (
    build_comparison_report,
    compare_criterion,
    compare_histograms,
    compare_per_frame,
    compute_pixel_diff,
)


# ---------------------------------------------------------------------------
# compute_pixel_diff (2 tests)
# ---------------------------------------------------------------------------


class PixelDiffTests(unittest.TestCase):
    """Tests de la difference pixel-a-pixel."""

    def test_identical_frames_zero(self) -> None:
        """Frames identiques → mean_diff = 0."""
        pixels = [100, 150, 200, 50]
        result = compute_pixel_diff(pixels, pixels)
        self.assertIsNotNone(result)
        self.assertEqual(result["mean_diff"], 0.0)
        self.assertEqual(result["max_diff"], 0)

    def test_different_frames_positive(self) -> None:
        """Frames differentes → mean_diff > 0."""
        a = [0, 0, 0, 0]
        b = [50, 100, 150, 200]
        result = compute_pixel_diff(a, b)
        self.assertIsNotNone(result)
        self.assertEqual(result["mean_diff"], 125.0)
        self.assertEqual(result["max_diff"], 200)


# ---------------------------------------------------------------------------
# compare_histograms (2 tests)
# ---------------------------------------------------------------------------


class CompareHistogramsTests(unittest.TestCase):
    """Tests de la comparaison d'histogrammes."""

    def test_identical_histograms_zero_divergence(self) -> None:
        """Histogrammes identiques → divergence = 0."""
        hist = [100] * 256
        result = compare_histograms(hist, hist)
        self.assertAlmostEqual(result["divergence"], 0.0, places=3)

    def test_different_histograms_positive_divergence(self) -> None:
        """Histogrammes differents → divergence > 0."""
        hist_a = [0] * 256
        hist_a[100] = 1000  # Un seul pic
        hist_b = [10] * 256  # Distribution uniforme
        result = compare_histograms(hist_a, hist_b)
        self.assertGreater(result["divergence"], 0.0)

    def test_detail_winner_more_levels(self) -> None:
        """Plus de niveaux distincts = plus de detail."""
        hist_a = [100] * 256  # 256 niveaux
        hist_b = [0] * 256
        for i in range(0, 256, 4):
            hist_b[i] = 400  # 64 niveaux
        result = compare_histograms(hist_a, hist_b)
        self.assertEqual(result["detail_winner"], "a")
        self.assertGreater(result["levels_a"], result["levels_b"])


# ---------------------------------------------------------------------------
# compare_criterion (3 tests)
# ---------------------------------------------------------------------------


class CompareCriterionTests(unittest.TestCase):
    """Tests de la comparaison de criteres."""

    def test_higher_is_better_a_wins(self) -> None:
        """A > B avec higher_is_better → A gagne."""
        result = compare_criterion(80.0, 60.0, "LRA", higher_is_better=True)
        self.assertEqual(result["winner"], "a")
        self.assertAlmostEqual(result["delta"], 20.0)

    def test_lower_is_better_a_wins(self) -> None:
        """A < B avec higher_is_better=False → A gagne."""
        result = compare_criterion(10.0, 30.0, "Blockiness", higher_is_better=False)
        self.assertEqual(result["winner"], "a")

    def test_tie_when_delta_small(self) -> None:
        """Delta < 5% du max → tie."""
        result = compare_criterion(100.0, 98.0, "Score", higher_is_better=True)
        self.assertEqual(result["winner"], "tie")
        self.assertLess(result["delta_pct"], 5.0)


# ---------------------------------------------------------------------------
# compare_per_frame (1 test)
# ---------------------------------------------------------------------------


class ComparePerFrameTests(unittest.TestCase):
    """Tests de la comparaison per-frame."""

    def test_structure(self) -> None:
        """Chaque frame retournee a la bonne structure."""
        w, h = 32, 32
        pa = [(i * 37) % 256 for i in range(w * h)]
        pb = [(i * 41 + 10) % 256 for i in range(w * h)]
        frames = [{"timestamp": 10.0, "pixels_a": pa, "pixels_b": pb, "width": w, "height": h}]
        results = compare_per_frame(frames, bit_depth=8)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["timestamp"], 10.0)
        self.assertIn("pixel_diff", r)
        self.assertIn("histogram", r)
        self.assertIn("variance_a", r)
        self.assertIn("banding_a", r)


# ---------------------------------------------------------------------------
# build_comparison_report (3 tests)
# ---------------------------------------------------------------------------


class BuildComparisonReportTests(unittest.TestCase):
    """Tests du rapport de comparaison complet."""

    def _make_perceptual_dict(
        self,
        global_score: int,
        block: float = 15.0,
        blur: float = 0.02,
        banding: float = 5.0,
        bits: float = 8.5,
        variance: float = 500.0,
        lra: float = 14.0,
        noise: float = -65.0,
        clip: float = 0.0,
    ) -> dict:
        return {
            "global_score": global_score,
            "video_perceptual": {
                "blockiness": {"mean": block},
                "blur": {"mean": blur},
                "banding": {"mean_score": banding},
                "effective_bit_depth": {"mean_bits": bits},
                "local_variance": {"mean_variance": variance},
            },
            "audio_perceptual": {
                "ebu_r128": {"loudness_range": lra},
                "astats": {"noise_floor": noise},
                "clipping": {"clipping_pct": clip},
            },
        }

    def test_a_wins(self) -> None:
        """Fichier A nettement meilleur → winner='a', recommendation non vide."""
        pa = self._make_perceptual_dict(85, block=8, blur=0.01, bits=9.8, lra=18)
        pb = self._make_perceptual_dict(60, block=40, blur=0.06, bits=7.5, lra=6)
        report = build_comparison_report(pa, pb, [], "remux.mkv", "encode.mkv")
        self.assertEqual(report["winner"], "a")
        self.assertIn("superieur", report["recommendation"])
        self.assertGreater(report["score_delta"], 0)
        self.assertGreater(len(report["criteria_summary"]), 0)

    def test_tie(self) -> None:
        """Fichiers quasi-identiques → tie."""
        pa = self._make_perceptual_dict(80)
        pb = self._make_perceptual_dict(78)
        report = build_comparison_report(pa, pb, [], "a.mkv", "b.mkv")
        self.assertEqual(report["winner"], "tie")
        self.assertIn("equivalente", report["recommendation"])

    def test_criteria_summary_complete(self) -> None:
        """Tous les criteres sont presents dans le summary."""
        pa = self._make_perceptual_dict(80)
        pb = self._make_perceptual_dict(70)
        report = build_comparison_report(pa, pb, [], "a.mkv", "b.mkv")
        criteria_names = [c["criterion"] for c in report["criteria_summary"]]
        self.assertIn("Artefacts (blockiness)", criteria_names)
        self.assertIn("Nettete (blur)", criteria_names)
        self.assertIn("Banding", criteria_names)
        self.assertIn("Profondeur effective", criteria_names)
        self.assertIn("Dynamique audio (LRA)", criteria_names)
        self.assertIn("Clipping", criteria_names)
        self.assertEqual(len(criteria_names), 8)  # 5 video + 3 audio


# ---------------------------------------------------------------------------
# Endpoint expose (1 test)
# ---------------------------------------------------------------------------


class EndpointTests(unittest.TestCase):
    """Tests que l'endpoint est dans CineSortApi."""

    def test_compare_perceptual_exists(self) -> None:
        """Issue #84 PR 10 : compare_perceptual est sur QualityFacade."""
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        self.assertTrue(hasattr(api.quality, "compare_perceptual"))


if __name__ == "__main__":
    unittest.main()
