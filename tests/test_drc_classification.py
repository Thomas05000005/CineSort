"""Tests §14 v7.5.0 — DRC classification (compression dynamique)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cinesort.domain.perceptual.audio_perceptual import analyze_audio_perceptual, classify_drc


class TestClassifyDrc(unittest.TestCase):
    def test_cinema_high_confidence(self):
        # crest 20 (+2) + LRA 22 (+2) = 4 -> cinema 0.95
        v, c = classify_drc(crest_factor=20.0, lra=22.0)
        self.assertEqual(v, "cinema")
        self.assertAlmostEqual(c, 0.95)

    def test_cinema_high_combined_3(self):
        # crest 16 (+2) + LRA 12 (+1) = 3 -> cinema 0.95
        v, c = classify_drc(crest_factor=16.0, lra=12.0)
        self.assertEqual(v, "cinema")
        self.assertAlmostEqual(c, 0.95)

    def test_cinema_combined_2_via_crest(self):
        # crest 16 (+2) + LRA 8 (0) = 2 -> cinema 0.75
        v, c = classify_drc(crest_factor=16.0, lra=8.0)
        self.assertEqual(v, "cinema")
        self.assertAlmostEqual(c, 0.75)

    def test_cinema_combined_2_via_lra(self):
        # crest 8 (0) + LRA 20 (+2) = 2 -> cinema 0.75
        v, c = classify_drc(crest_factor=8.0, lra=20.0)
        self.assertEqual(v, "cinema")
        self.assertAlmostEqual(c, 0.75)

    def test_standard(self):
        # crest 12 (+1) + LRA 8 (0) = 1 -> standard 0.80
        v, c = classify_drc(crest_factor=12.0, lra=8.0)
        self.assertEqual(v, "standard")
        self.assertAlmostEqual(c, 0.80)

    def test_broadcast_compressed(self):
        v, c = classify_drc(crest_factor=6.0, lra=5.0)
        self.assertEqual(v, "broadcast_compressed")
        self.assertAlmostEqual(c, 0.85)

    def test_crest_only_cinema(self):
        v, c = classify_drc(crest_factor=18.0, lra=None)
        self.assertEqual(v, "cinema")
        self.assertAlmostEqual(c, 0.75)  # seul crest +2 = combined 2

    def test_lra_only_cinema(self):
        v, c = classify_drc(crest_factor=None, lra=22.0)
        self.assertEqual(v, "cinema")
        self.assertAlmostEqual(c, 0.75)

    def test_both_none_unknown(self):
        v, c = classify_drc(crest_factor=None, lra=None)
        self.assertEqual(v, "unknown")
        self.assertAlmostEqual(c, 0.0)

    def test_edge_crest_exactly_cinema_threshold(self):
        # crest 15 -> +2, LRA 18 -> +2, combined 4
        v, _ = classify_drc(crest_factor=15.0, lra=18.0)
        self.assertEqual(v, "cinema")

    def test_edge_crest_just_below_standard(self):
        # crest 9.99 (0) + LRA None -> unknown? non : lra None seul gere le None total
        v, _ = classify_drc(crest_factor=9.99, lra=None)
        # lra None mais crest present -> score_lra 0, score_crest 0, combined 0 -> broadcast
        self.assertEqual(v, "broadcast_compressed")

    def test_low_values_broadcast(self):
        v, _ = classify_drc(crest_factor=4.0, lra=3.0)
        self.assertEqual(v, "broadcast_compressed")


class TestIntegrationInAudioPerceptual(unittest.TestCase):
    """Verifie que classify_drc est appele dans analyze_audio_perceptual."""

    def test_drc_fields_populated(self):
        tracks = [{"index": 0, "codec": "truehd", "channels": 8, "language": "eng"}]
        with (
            patch(
                "cinesort.domain.perceptual.audio_perceptual.analyze_loudnorm",
                return_value={"integrated_loudness": -23.0, "loudness_range": 22.0, "true_peak": -1.0},
            ),
            patch(
                "cinesort.domain.perceptual.audio_perceptual.analyze_astats",
                return_value={
                    "rms_level": -20,
                    "peak_level": -1,
                    "noise_floor": -60,
                    "crest_factor": 18,
                    "dynamic_range": 50,
                },
            ),
            patch(
                "cinesort.domain.perceptual.audio_perceptual.analyze_clipping_segments",
                return_value={"total_segments": 10, "clipping_segments": 0, "clipping_pct": 0.0},
            ),
            patch(
                "cinesort.domain.perceptual.audio_fingerprint.resolve_fpcalc_path",
                return_value=None,
            ),
        ):
            result = analyze_audio_perceptual(
                "/tmp/ffmpeg",
                "/tmp/movie.mkv",
                tracks,
                enable_fingerprint=False,
                enable_spectral=False,
                duration_s=7200.0,
            )
        self.assertEqual(result.drc_category, "cinema")
        self.assertGreater(result.drc_confidence, 0.0)

    def test_drc_none_when_astats_loudnorm_both_fail(self):
        tracks = [{"index": 0, "codec": "aac", "channels": 2, "language": "eng"}]
        with (
            patch(
                "cinesort.domain.perceptual.audio_perceptual.analyze_loudnorm",
                return_value=None,
            ),
            patch(
                "cinesort.domain.perceptual.audio_perceptual.analyze_astats",
                return_value=None,
            ),
            patch(
                "cinesort.domain.perceptual.audio_perceptual.analyze_clipping_segments",
                return_value={"total_segments": 0, "clipping_segments": 0, "clipping_pct": 0.0},
            ),
        ):
            result = analyze_audio_perceptual(
                "/tmp/ffmpeg",
                "/tmp/movie.mkv",
                tracks,
                enable_fingerprint=False,
                enable_spectral=False,
                duration_s=7200.0,
            )
        self.assertEqual(result.drc_category, "unknown")


class TestAudioPerceptualSerialization(unittest.TestCase):
    def test_to_dict_contains_drc_block(self):
        from cinesort.domain.perceptual.models import AudioPerceptual

        ap = AudioPerceptual()
        ap.drc_category = "cinema"
        ap.drc_confidence = 0.95
        d = ap.to_dict()
        self.assertIn("drc", d)
        self.assertEqual(d["drc"]["category"], "cinema")
        self.assertAlmostEqual(d["drc"]["confidence"], 0.95)


if __name__ == "__main__":
    unittest.main()
