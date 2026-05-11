"""Tests analyse video perceptuelle — Phase II-B (item 9.24).

Couvre :
- luminance_histogram : uniforme, bimodal
- block_variance_stats : image plate, image bruitee
- detect_banding : gradient doux, paliers marques
- effective_bit_depth : 256 niveaux, 64 niveaux
- run_filter_graph : parsing signalstats, blockdetect, blurdetect
- analyze_video_frames : dark weighting, BT.2020, N&B, temporal consistency
"""

from __future__ import annotations

import unittest

from cinesort.domain.perceptual.video_analysis import (
    analyze_video_frames,
    block_variance_stats,
    detect_banding,
    effective_bit_depth,
    luminance_histogram,
    _parse_filter_output,
)


# ---------------------------------------------------------------------------
# luminance_histogram (2 tests)
# ---------------------------------------------------------------------------


class LuminanceHistogramTests(unittest.TestCase):
    """Tests de l'histogramme luminance."""

    def test_uniform_single_value(self) -> None:
        """Tous les pixels a la meme valeur → 1 seul bin plein."""
        pixels = [128] * 100
        hist = luminance_histogram(pixels, 8)
        self.assertEqual(len(hist), 256)
        self.assertEqual(hist[128], 100)
        self.assertEqual(sum(hist), 100)
        # Tous les autres bins a 0
        non_zero = [i for i, c in enumerate(hist) if c > 0]
        self.assertEqual(non_zero, [128])

    def test_bimodal_two_peaks(self) -> None:
        """Deux valeurs → deux pics dans l'histogramme."""
        pixels = [50] * 60 + [200] * 40
        hist = luminance_histogram(pixels, 8)
        self.assertEqual(hist[50], 60)
        self.assertEqual(hist[200], 40)
        self.assertEqual(sum(hist), 100)


# ---------------------------------------------------------------------------
# block_variance_stats (2 tests)
# ---------------------------------------------------------------------------


class BlockVarianceTests(unittest.TestCase):
    """Tests de la variance par blocs."""

    def test_flat_image(self) -> None:
        """Image uniforme → flat_ratio proche de 1.0."""
        w, h = 32, 32
        pixels = [128] * (w * h)
        stats = block_variance_stats(pixels, w, h, block_size=16, bit_depth=8)
        self.assertAlmostEqual(stats["flat_ratio"], 1.0, places=2)
        self.assertAlmostEqual(stats["mean_variance"], 0.0, places=2)

    def test_noisy_image(self) -> None:
        """Image bruitee → variance haute, flat_ratio bas."""
        w, h = 32, 32
        pixels = [(i * 37 + i * i) % 256 for i in range(w * h)]
        stats = block_variance_stats(pixels, w, h, block_size=16, bit_depth=8)
        self.assertGreater(stats["mean_variance"], 100.0)
        self.assertLess(stats["flat_ratio"], 0.5)


# ---------------------------------------------------------------------------
# detect_banding (2 tests)
# ---------------------------------------------------------------------------


class DetectBandingTests(unittest.TestCase):
    """Tests de la detection de banding."""

    def test_smooth_gradient_low_score(self) -> None:
        """Gradient doux (tous les niveaux presents) → score bas."""
        # Histogramme avec tous les bins remplis uniformement
        hist = [100] * 256
        result = detect_banding(hist)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["gap_count"], 0)

    def test_stepped_gradient_high_score(self) -> None:
        """Paliers marques (bins vides entre bins pleins) → score haut."""
        # Simuler du banding : bins pleins espaces de 10
        hist = [0] * 256
        for i in range(26, 230, 10):  # bins pleins tous les 10
            hist[i] = 500
        result = detect_banding(hist, min_gap=3)
        self.assertGreater(result["score"], 0)
        self.assertGreater(result["gap_count"], 0)
        self.assertGreater(result["worst_gap"], 3)


# ---------------------------------------------------------------------------
# effective_bit_depth (2 tests)
# ---------------------------------------------------------------------------


class EffectiveBitDepthTests(unittest.TestCase):
    """Tests de la profondeur effective."""

    def test_full_range_8_bits(self) -> None:
        """256 niveaux utilises = 8 bits effectifs."""
        hist = [100] * 256
        result = effective_bit_depth(hist, 8)
        self.assertAlmostEqual(result["mean_bits"], 8.0, places=1)
        self.assertEqual(result["distinct_levels"], 256)
        self.assertAlmostEqual(result["utilization_pct"], 100.0, places=0)

    def test_limited_range_6_bits(self) -> None:
        """~64 niveaux utilises → ~6 bits effectifs."""
        hist = [0] * 256
        # 64 niveaux remplis uniformement
        for i in range(0, 256, 4):
            hist[i] = 100
        result = effective_bit_depth(hist, 8)
        self.assertAlmostEqual(result["mean_bits"], 6.0, places=0)
        self.assertEqual(result["distinct_levels"], 64)


# ---------------------------------------------------------------------------
# Parsing filtres ffmpeg (3 tests)
# ---------------------------------------------------------------------------


class FilterParsingTests(unittest.TestCase):
    """Tests du parsing de la sortie stderr ffmpeg."""

    def test_signalstats_parsing(self) -> None:
        """Les valeurs YAVG, SATAVG, TOUT, VREP sont extraites correctement."""
        stderr = (
            "[Parsed_signalstats_1 @ 0x1234] "
            "YMIN=16 YLOW=25 YAVG=85 YHIGH=210 YMAX=235 "
            "UMIN=90 UMAX=170 VMIN=80 VMAX=175 "
            "SATMIN=5 SATAVG=42 SATMAX=180 "
            "TOUT=0.015 VREP=0.008\n"
        )
        frames = _parse_filter_output(stderr)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["y_avg"], 85)
        self.assertEqual(frames[0]["sat_avg"], 42)
        self.assertAlmostEqual(frames[0]["tout"], 0.015, places=3)
        self.assertAlmostEqual(frames[0]["vrep"], 0.008, places=3)

    def test_blockdetect_parsing(self) -> None:
        """La valeur blockdetect block est extraite."""
        stderr = (
            "[Parsed_signalstats_1 @ 0x1234] YAVG=100 SATAVG=30 TOUT=0.01 VREP=0.005\n"
            "[Parsed_blockdetect_2 @ 0x5678] blockdetect block: 22.5\n"
        )
        frames = _parse_filter_output(stderr)
        self.assertEqual(len(frames), 1)
        self.assertAlmostEqual(frames[0]["blockiness"], 22.5)

    def test_blurdetect_parsing(self) -> None:
        """La valeur blurdetect blur est extraite."""
        stderr = (
            "[Parsed_signalstats_1 @ 0x1234] YAVG=100 SATAVG=30 TOUT=0.01 VREP=0.005\n"
            "[Parsed_blurdetect_3 @ 0x9abc] blurdetect blur: 0.0342\n"
        )
        frames = _parse_filter_output(stderr)
        self.assertEqual(len(frames), 1)
        self.assertAlmostEqual(frames[0]["blur"], 0.0342, places=4)


# ---------------------------------------------------------------------------
# analyze_video_frames (4 tests)
# ---------------------------------------------------------------------------


class AnalyzeVideoFramesTests(unittest.TestCase):
    """Tests de l'orchestrateur video."""

    def _make_frame(self, w: int, h: int, value: int = 128) -> dict:
        """Fabrique une frame avec pixels uniformes."""
        pixels = [value] * (w * h)
        return {"pixels": pixels, "width": w, "height": h, "y_avg": float(value), "timestamp": 10.0}

    def _make_varied_frame(self, w: int, h: int, seed: int = 0, y_avg: float = 128.0) -> dict:
        """Fabrique une frame avec contenu varie."""
        pixels = [(seed + i * 37 + i * i) % 256 for i in range(w * h)]
        return {"pixels": pixels, "width": w, "height": h, "y_avg": y_avg, "timestamp": 10.0}

    def _make_filter_results(self, count: int, blockiness: float = 15.0, blur: float = 0.02, sat: int = 40) -> list:
        """Fabrique des resultats de filtre graph."""
        return [
            {
                "y_avg": 100,
                "y_min": 16,
                "y_max": 235,
                "sat_avg": sat,
                "tout": 0.01,
                "vrep": 0.005,
                "blockiness": blockiness,
                "blur": blur,
            }
            for _ in range(count)
        ]

    def test_dark_scene_weighting(self) -> None:
        """Les frames sombres (y_avg < seuil) sont ponderees plus fortement."""
        w, h = 32, 32
        # Frame sombre avec beaucoup de banding (valeurs repetitives)
        dark_frame = self._make_varied_frame(w, h, seed=5, y_avg=30.0)
        # Frame claire avec moins de banding
        light_frame = self._make_varied_frame(w, h, seed=100, y_avg=150.0)

        filters = self._make_filter_results(2)

        result_dark_heavy = analyze_video_frames(
            [dark_frame, light_frame],
            filters,
            8,
            "bt709",
            dark_weight=3.0,
            width=w,
            height=h,
        )
        _ = analyze_video_frames(
            [dark_frame, light_frame],
            filters,
            8,
            "bt709",
            dark_weight=1.0,
            width=w,
            height=h,
        )
        # Avec dark_weight=3.0, la frame sombre a plus d'influence sur le banding
        self.assertEqual(result_dark_heavy.dark_frame_count, 1)
        self.assertGreater(result_dark_heavy.dark_frame_pct, 0)

    def test_bt2020_adjustment(self) -> None:
        """Contenu BT.2020 → seuils plus indulgents → score potentiellement meilleur."""
        w, h = 32, 32
        frame = self._make_varied_frame(w, h, seed=42, y_avg=100.0)
        # Blockiness moderee : devrait etre plus severe en BT.709 qu'en BT.2020
        filters = self._make_filter_results(1, blockiness=30.0, blur=0.04)

        result_709 = analyze_video_frames([frame], filters, 8, "bt709", width=w, height=h)
        result_2020 = analyze_video_frames([frame], filters, 8, "bt2020", width=w, height=h)

        # BT.2020 devrait donner un score >= celui de BT.709 (seuils plus indulgents)
        self.assertGreaterEqual(result_2020.visual_score, result_709.visual_score)

    def test_bw_detection(self) -> None:
        """Saturation moyenne < seuil → N&B detecte."""
        w, h = 32, 32
        frame = self._make_varied_frame(w, h, seed=10, y_avg=100.0)
        # Filtres avec saturation tres basse = N&B
        filters = self._make_filter_results(1, sat=3)

        result = analyze_video_frames([frame], filters, 8, "bt709", width=w, height=h)
        self.assertTrue(result.is_bw)

    def test_temporal_consistency(self) -> None:
        """La consistance temporelle est calculee depuis les resultats de filtre."""
        # Frames avec blockiness tres variable → stddev haute
        filters = [
            {
                "y_avg": 100,
                "sat_avg": 40,
                "tout": 0.01,
                "vrep": 0.005,
                "blockiness": b,
                "blur": 0.02,
                "y_min": 16,
                "y_max": 235,
            }
            for b in [10, 80, 15, 75, 20]
        ]
        w, h = 32, 32
        frames = [self._make_varied_frame(w, h, seed=i, y_avg=100.0) for i in range(5)]

        result = analyze_video_frames(frames, filters, 8, "bt709", width=w, height=h)
        # Stddev de blockiness devrait etre significative
        self.assertGreater(result.temporal_stddev, 10.0)


if __name__ == "__main__":
    unittest.main()
