"""Tests score perceptuel composite + verdicts croises — Phase V (item 9.24).

Couvre :
- compute_visual_score : tout excellent, tout mauvais
- compute_audio_score : pondere, pas de piste
- compute_global_score : ratio 60/40, pas d'audio
- determine_tier : 5 tiers
- detect_cross_verdicts : DNR+upscale, mastering reference, audio ecrase, non declenche
- build_perceptual_result : orchestration complete
"""

from __future__ import annotations

import unittest

from cinesort.domain.perceptual.composite_score import (
    build_perceptual_result,
    compute_audio_score,
    compute_global_score,
    compute_visual_score,
    detect_cross_verdicts,
    determine_tier,
)
from cinesort.domain.perceptual.models import (
    AudioPerceptual,
    GrainAnalysis,
    VideoPerceptual,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _excellent_video() -> VideoPerceptual:
    """VideoPerceptual avec toutes les metriques excellentes."""
    return VideoPerceptual(
        blockiness_mean=5.0,  # < BLOCK_NONE (10)
        blur_mean=0.005,  # < BLUR_SHARP (0.01)
        banding_mean=2.0,  # < BANDING_NONE (5)
        effective_bits_mean=9.8,  # > EFFECTIVE_BITS_EXCELLENT (9.5)
        temporal_stddev=5.0,  # < TEMPORAL_CONSISTENCY_GOOD (15)
        resolution_height=2160,
        bit_depth_nominal=10,
    )


def _poor_video() -> VideoPerceptual:
    """VideoPerceptual avec toutes les metriques mauvaises."""
    return VideoPerceptual(
        blockiness_mean=80.0,  # > BLOCK_SEVERE (75)
        blur_mean=0.15,  # > BLUR_VERY_SOFT (0.10)
        banding_mean=60.0,  # > BANDING_SEVERE (50)
        effective_bits_mean=5.0,  # < EFFECTIVE_BITS_POOR (6.5)
        temporal_stddev=50.0,  # > TEMPORAL_CONSISTENCY_POOR (35)
        resolution_height=1080,
        bit_depth_nominal=8,
    )


def _excellent_grain() -> GrainAnalysis:
    return GrainAnalysis(score=85)


def _poor_grain() -> GrainAnalysis:
    return GrainAnalysis(score=20)


def _excellent_audio() -> AudioPerceptual:
    return AudioPerceptual(
        track_index=0,
        track_codec="truehd",
        track_channels=8,
        integrated_loudness=-24.0,
        loudness_range=18.0,
        true_peak=-3.0,
        noise_floor=-75.0,
        dynamic_range=65.0,
        crest_factor=22.0,
        clipping_pct=0.0,
        audio_score=92,
        audio_tier="reference",
    )


# ---------------------------------------------------------------------------
# compute_visual_score (2 tests)
# ---------------------------------------------------------------------------


class VisualScoreTests(unittest.TestCase):
    """Tests du score visuel composite."""

    def test_all_excellent(self) -> None:
        """Toutes metriques excellentes → score tres haut."""
        score = compute_visual_score(_excellent_video(), _excellent_grain())
        self.assertGreaterEqual(score, 88)

    def test_all_poor(self) -> None:
        """Toutes metriques mauvaises → score tres bas."""
        score = compute_visual_score(_poor_video(), _poor_grain())
        self.assertLess(score, 25)


# ---------------------------------------------------------------------------
# compute_audio_score (2 tests)
# ---------------------------------------------------------------------------


class AudioScoreTests(unittest.TestCase):
    """Tests du score audio."""

    def test_audio_score_from_model(self) -> None:
        """Le score est reutilise depuis AudioPerceptual.audio_score."""
        audio = AudioPerceptual(track_index=0, audio_score=82)
        self.assertEqual(compute_audio_score(audio), 82)

    def test_no_track_returns_zero(self) -> None:
        """Pas de piste audio → 0."""
        self.assertEqual(compute_audio_score(None), 0)
        empty = AudioPerceptual()  # track_index = -1
        self.assertEqual(compute_audio_score(empty), 0)


# ---------------------------------------------------------------------------
# compute_global_score (2 tests)
# ---------------------------------------------------------------------------


class GlobalScoreTests(unittest.TestCase):
    """Tests du score global."""

    def test_60_40_ratio(self) -> None:
        """Le ratio 60/40 est respecte."""
        # visual=100, audio=0 avec piste → 100*60 + 0*40 = 60
        score = compute_global_score(100, 50)
        # 100*60 + 50*40 = 6000 + 2000 = 8000 / 100 = 80
        self.assertEqual(score, 80)

    def test_no_audio_100_percent_video(self) -> None:
        """Pas d'audio (score 0) → 100% video."""
        score = compute_global_score(75, 0)
        self.assertEqual(score, 75)


# ---------------------------------------------------------------------------
# determine_tier (5 tests)
# ---------------------------------------------------------------------------


class TierTests(unittest.TestCase):
    """Tests des tiers perceptuels."""

    def test_reference(self) -> None:
        self.assertEqual(determine_tier(95), "reference")
        self.assertEqual(determine_tier(90), "reference")

    def test_excellent(self) -> None:
        self.assertEqual(determine_tier(85), "excellent")
        self.assertEqual(determine_tier(75), "excellent")

    def test_bon(self) -> None:
        self.assertEqual(determine_tier(70), "bon")
        self.assertEqual(determine_tier(60), "bon")

    def test_mediocre(self) -> None:
        self.assertEqual(determine_tier(55), "mediocre")
        self.assertEqual(determine_tier(40), "mediocre")

    def test_degrade(self) -> None:
        self.assertEqual(determine_tier(30), "degrade")
        self.assertEqual(determine_tier(0), "degrade")


# ---------------------------------------------------------------------------
# detect_cross_verdicts (4 tests)
# ---------------------------------------------------------------------------


class CrossVerdictsTests(unittest.TestCase):
    """Tests des verdicts croises inter-metriques."""

    def test_dnr_upscale_combo(self) -> None:
        """Blur eleve + upscale flag → verdict error."""
        video = VideoPerceptual(
            blur_mean=0.06,
            blockiness_mean=20.0,
            banding_mean=10.0,
            effective_bits_mean=8.0,
            resolution_height=2160,
            bit_depth_nominal=10,
        )
        verdicts = detect_cross_verdicts(video, None, None, encode_warnings=["upscale_suspect"])
        ids = [v["id"] for v in verdicts]
        self.assertIn("dnr_upscale_combo", ids)
        match = [v for v in verdicts if v["id"] == "dnr_upscale_combo"][0]
        self.assertEqual(match["severity"], "error")

    def test_mastering_reference(self) -> None:
        """Tout propre → verdict positif mastering."""
        video = _excellent_video()
        verdicts = detect_cross_verdicts(video, None, None)
        ids = [v["id"] for v in verdicts]
        self.assertIn("excellent_mastering", ids)
        match = [v for v in verdicts if v["id"] == "excellent_mastering"][0]
        self.assertEqual(match["severity"], "positive")

    def test_audio_crushed(self) -> None:
        """LRA < 5 → verdict audio ecrase."""
        video = VideoPerceptual(
            blockiness_mean=15.0, blur_mean=0.02, banding_mean=5.0, effective_bits_mean=8.5, bit_depth_nominal=10
        )
        audio = AudioPerceptual(track_index=0, loudness_range=3.5)
        verdicts = detect_cross_verdicts(video, None, audio)
        ids = [v["id"] for v in verdicts]
        self.assertIn("audio_crushed", ids)

    def test_no_verdicts_when_conditions_not_met(self) -> None:
        """Conditions pas remplies → liste vide."""
        # Video correcte, pas de flags, audio OK
        video = VideoPerceptual(
            blockiness_mean=15.0,
            blur_mean=0.02,
            banding_mean=5.0,
            effective_bits_mean=8.5,
            resolution_height=1080,
            bit_depth_nominal=10,
        )
        audio = AudioPerceptual(track_index=0, loudness_range=14.0)
        verdicts = detect_cross_verdicts(video, GrainAnalysis(tmdb_year=2020), audio)
        # Pas de condition remplie pour les verdicts negatifs
        error_verdicts = [v for v in verdicts if v["severity"] in ("error", "warning")]
        self.assertEqual(len(error_verdicts), 0)


# ---------------------------------------------------------------------------
# build_perceptual_result (2 tests)
# ---------------------------------------------------------------------------


class BuildResultTests(unittest.TestCase):
    """Tests de l'orchestrateur final."""

    def test_full_result(self) -> None:
        """Resultat complet avec video + grain + audio."""
        video = _excellent_video()
        grain = _excellent_grain()
        audio = _excellent_audio()
        result = build_perceptual_result(video, grain, audio, {"frames_count": 10})
        self.assertGreater(result.visual_score, 0)
        self.assertGreater(result.audio_score, 0)
        self.assertGreater(result.global_score, 0)
        self.assertIn(result.global_tier, ("reference", "excellent", "bon", "mediocre", "degrade"))
        self.assertEqual(result.settings_used["frames_count"], 10)
        self.assertIsNotNone(result.video)
        self.assertIsNotNone(result.grain)
        self.assertIsNotNone(result.audio)

    def test_video_only_no_audio(self) -> None:
        """Video seule sans audio → global = visual, tier correct."""
        video = _excellent_video()
        grain = _excellent_grain()
        result = build_perceptual_result(video, grain, None)
        self.assertEqual(result.audio_score, 0)
        # Global = visual car pas d'audio
        self.assertEqual(result.global_score, result.visual_score)


if __name__ == "__main__":
    unittest.main()
