"""Tests §16 v7.5.0 — Score composite V2."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from cinesort.domain.perceptual.composite_score_v2 import (
    apply_contextual_adjustments,
    build_audio_subscores,
    build_coherence_subscores,
    build_video_subscores,
    collect_warnings,
    compute_category,
    compute_global_score_v2,
    determine_tier_v2,
    weighted_score_with_confidence,
)
from cinesort.domain.perceptual.constants import (
    AUDIO_WEIGHT_CHROMAPRINT,
    AUDIO_WEIGHT_DRC,
    AUDIO_WEIGHT_PERCEPTUAL_V2,
    AUDIO_WEIGHT_RESERVE,
    AUDIO_WEIGHT_SPECTRAL,
    COHERENCE_WEIGHT_NFO,
    COHERENCE_WEIGHT_RUNTIME,
    GLOBAL_WEIGHT_AUDIO_V2,
    GLOBAL_WEIGHT_COHERENCE_V2,
    GLOBAL_WEIGHT_VIDEO_V2,
    VIDEO_WEIGHT_HDR,
    VIDEO_WEIGHT_LPIPS,
    VIDEO_WEIGHT_PERCEPTUAL,
    VIDEO_WEIGHT_RESOLUTION,
)
from cinesort.domain.perceptual.models import (
    AudioPerceptual,
    CategoryScore,
    GrainAnalysis,
    SubScore,
    VideoPerceptual,
)


# ---------------------------------------------------------------------------
# Weights sum to 100
# ---------------------------------------------------------------------------


class TestWeightsSumTo100(unittest.TestCase):
    def test_global_weights(self):
        self.assertEqual(GLOBAL_WEIGHT_VIDEO_V2 + GLOBAL_WEIGHT_AUDIO_V2 + GLOBAL_WEIGHT_COHERENCE_V2, 100)

    def test_video_weights(self):
        self.assertEqual(VIDEO_WEIGHT_PERCEPTUAL + VIDEO_WEIGHT_RESOLUTION + VIDEO_WEIGHT_HDR + VIDEO_WEIGHT_LPIPS, 100)

    def test_audio_weights(self):
        self.assertEqual(
            AUDIO_WEIGHT_PERCEPTUAL_V2
            + AUDIO_WEIGHT_SPECTRAL
            + AUDIO_WEIGHT_DRC
            + AUDIO_WEIGHT_CHROMAPRINT
            + AUDIO_WEIGHT_RESERVE,
            100,
        )

    def test_coherence_weights(self):
        self.assertEqual(COHERENCE_WEIGHT_RUNTIME + COHERENCE_WEIGHT_NFO, 100)


# ---------------------------------------------------------------------------
# determine_tier_v2
# ---------------------------------------------------------------------------


class TestDetermineTierV2(unittest.TestCase):
    def test_platinum_95(self):
        self.assertEqual(determine_tier_v2(95), "platinum")

    def test_platinum_90_boundary(self):
        self.assertEqual(determine_tier_v2(90), "platinum")

    def test_gold_85(self):
        self.assertEqual(determine_tier_v2(85), "gold")

    def test_gold_80_boundary(self):
        self.assertEqual(determine_tier_v2(80), "gold")

    def test_silver_70(self):
        self.assertEqual(determine_tier_v2(70), "silver")

    def test_silver_65_boundary(self):
        self.assertEqual(determine_tier_v2(65), "silver")

    def test_bronze_55(self):
        self.assertEqual(determine_tier_v2(55), "bronze")

    def test_bronze_50_boundary(self):
        self.assertEqual(determine_tier_v2(50), "bronze")

    def test_reject_45(self):
        self.assertEqual(determine_tier_v2(45), "reject")

    def test_reject_0(self):
        self.assertEqual(determine_tier_v2(0), "reject")


# ---------------------------------------------------------------------------
# weighted_score_with_confidence
# ---------------------------------------------------------------------------


class TestWeightedScoreWithConfidence(unittest.TestCase):
    def test_empty_returns_neutral(self):
        s, c = weighted_score_with_confidence([])
        self.assertEqual(s, 50.0)
        self.assertEqual(c, 0.0)

    def test_all_confidence_1_returns_weighted_mean(self):
        # 80 × 50 + 60 × 50 = 70
        s, c = weighted_score_with_confidence([(80, 50, 1.0), (60, 50, 1.0)])
        self.assertAlmostEqual(s, 70.0, places=2)
        self.assertAlmostEqual(c, 1.0, places=2)

    def test_confidence_0_excludes_from_score(self):
        # L'item confidence=0 n'affecte pas le score final
        s, _ = weighted_score_with_confidence([(80, 50, 1.0), (0, 50, 0.0)])
        self.assertAlmostEqual(s, 80.0, places=2)

    def test_all_confidence_0_returns_neutral(self):
        s, c = weighted_score_with_confidence([(80, 50, 0.0), (60, 50, 0.0)])
        self.assertEqual(s, 50.0)
        self.assertEqual(c, 0.0)

    def test_partial_confidence_weights_proportionally(self):
        # 100 × 50 × 1.0 + 50 × 50 × 0.5 = 5000 + 1250 = 6250
        # effective weights = 50 + 25 = 75
        # score = 6250 / 75 ≈ 83.33
        s, _ = weighted_score_with_confidence([(100, 50, 1.0), (50, 50, 0.5)])
        self.assertAlmostEqual(s, 83.33, places=1)


# ---------------------------------------------------------------------------
# build_video_subscores
# ---------------------------------------------------------------------------


class TestBuildVideoSubscores(unittest.TestCase):
    def test_contains_3_subscores_without_lpips(self):
        v = VideoPerceptual(visual_score=70, resolution_width=1920, resolution_height=1080, frames_analyzed=10)
        subs, _ = build_video_subscores(v, None, None, None)
        self.assertEqual(len(subs), 3)
        self.assertEqual({s.name for s in subs}, {"perceptual_visual", "resolution", "hdr_validation"})

    def test_lpips_adds_4th_subscore(self):
        v = VideoPerceptual(visual_score=70, resolution_width=1920, resolution_height=1080, frames_analyzed=10)
        lpips = SimpleNamespace(distance_median=0.1)
        subs, _ = build_video_subscores(v, None, None, lpips)
        self.assertEqual(len(subs), 4)
        self.assertIn("lpips_distance", {s.name for s in subs})

    def test_4k_resolution_platinum(self):
        v = VideoPerceptual(visual_score=70, resolution_width=3840, resolution_height=2160, frames_analyzed=10)
        subs, _ = build_video_subscores(v, None, None, None)
        res_sub = next(s for s in subs if s.name == "resolution")
        self.assertEqual(res_sub.tier, "platinum")

    def test_fake_4k_downgrades_to_reject(self):
        v = VideoPerceptual(
            visual_score=70,
            resolution_width=3840,
            resolution_height=2160,
            frames_analyzed=10,
            fake_4k_verdict_combined="fake_4k_confirmed",
        )
        subs, _ = build_video_subscores(v, None, None, None)
        res_sub = next(s for s in subs if s.name == "resolution")
        self.assertEqual(res_sub.tier, "reject")

    def test_dv_profile_5_flag(self):
        v = VideoPerceptual(visual_score=70, resolution_width=1920, resolution_height=1080, frames_analyzed=10)
        probe = {"video": {"has_dv": True, "dv_profile": "5"}}
        _, flags = build_video_subscores(v, None, probe, None)
        self.assertIn("dv_profile_5", flags)

    def test_hdr10_without_maxcll_flag(self):
        v = VideoPerceptual(visual_score=70, resolution_width=1920, resolution_height=1080, frames_analyzed=10)
        probe = {"video": {"has_hdr10": True, "max_cll": None, "max_fall": None}}
        _, flags = build_video_subscores(v, None, probe, None)
        self.assertIn("hdr_metadata_missing", flags)

    def test_labels_fr_present(self):
        v = VideoPerceptual(visual_score=70, resolution_width=1920, resolution_height=1080, frames_analyzed=10)
        subs, _ = build_video_subscores(v, None, None, None)
        for s in subs:
            self.assertTrue(s.label_fr)
            self.assertNotEqual(s.label_fr, "")


# ---------------------------------------------------------------------------
# build_audio_subscores
# ---------------------------------------------------------------------------


class TestBuildAudioSubscores(unittest.TestCase):
    def test_returns_5_subscores_with_reserve(self):
        a = AudioPerceptual(audio_score=80)
        subs = build_audio_subscores(a)
        self.assertEqual(len(subs), 5)
        names = {s.name for s in subs}
        self.assertEqual(
            names,
            {"perceptual_audio", "spectral_cutoff", "drc_category", "chromaprint", "reserve"},
        )

    def test_reserve_has_zero_confidence(self):
        a = AudioPerceptual(audio_score=80)
        subs = build_audio_subscores(a)
        reserve = next(s for s in subs if s.name == "reserve")
        self.assertEqual(reserve.confidence, 0.0)

    def test_lossless_spectral_platinum(self):
        a = AudioPerceptual(lossy_verdict="lossless", lossy_confidence=0.95)
        subs = build_audio_subscores(a)
        spec = next(s for s in subs if s.name == "spectral_cutoff")
        self.assertEqual(spec.tier, "platinum")

    def test_low_bitrate_lossy_bronze(self):
        a = AudioPerceptual(lossy_verdict="low_bitrate_lossy", lossy_confidence=0.85)
        subs = build_audio_subscores(a)
        spec = next(s for s in subs if s.name == "spectral_cutoff")
        self.assertEqual(spec.tier, "bronze")

    def test_drc_cinema_highest(self):
        a = AudioPerceptual(drc_category="cinema", drc_confidence=0.9)
        subs = build_audio_subscores(a)
        drc = next(s for s in subs if s.name == "drc_category")
        self.assertEqual(drc.value, 100.0)

    def test_fingerprint_fpcalc_high(self):
        a = AudioPerceptual(fingerprint_source="fpcalc")
        subs = build_audio_subscores(a)
        fp = next(s for s in subs if s.name == "chromaprint")
        self.assertEqual(fp.value, 100.0)


# ---------------------------------------------------------------------------
# build_coherence_subscores
# ---------------------------------------------------------------------------


class TestBuildCoherenceSubscores(unittest.TestCase):
    def test_runtime_match_100(self):
        subs = build_coherence_subscores("match", None)
        rt = next(s for s in subs if s.name == "runtime_match")
        self.assertEqual(rt.value, 100.0)

    def test_runtime_mismatch_40(self):
        subs = build_coherence_subscores("mismatch", None)
        rt = next(s for s in subs if s.name == "runtime_match")
        self.assertEqual(rt.value, 40.0)

    def test_nfo_consistent_with_tmdb(self):
        subs = build_coherence_subscores(None, {"consistent": True, "has_tmdb_id": True})
        nfo = next(s for s in subs if s.name == "nfo_consistency")
        self.assertEqual(nfo.value, 100.0)

    def test_nfo_inconsistent(self):
        subs = build_coherence_subscores(None, {"consistent": False})
        nfo = next(s for s in subs if s.name == "nfo_consistency")
        self.assertEqual(nfo.value, 40.0)


# ---------------------------------------------------------------------------
# apply_contextual_adjustments
# ---------------------------------------------------------------------------


def _v_subs(base_val: float = 70.0) -> list:
    return [
        SubScore(name="perceptual_visual", value=base_val, weight=50, confidence=1.0, label_fr="L"),
        SubScore(name="resolution", value=base_val, weight=20, confidence=1.0, label_fr="L"),
        SubScore(name="hdr_validation", value=base_val, weight=15, confidence=1.0, label_fr="L"),
    ]


def _a_subs(base_val: float = 70.0) -> list:
    return [
        SubScore(name="perceptual_audio", value=base_val, weight=50, confidence=1.0, label_fr="L"),
        SubScore(name="spectral_cutoff", value=base_val, weight=20, confidence=1.0, label_fr="L"),
        SubScore(name="drc_category", value=base_val, weight=15, confidence=1.0, label_fr="L"),
    ]


class TestContextualAdjustments(unittest.TestCase):
    def test_rule1_film_grain_bonus(self):
        grain = GrainAnalysis(grain_nature="film_grain", is_animation=False, film_era_v2="blu_ray_digital")
        v, _, trace = apply_contextual_adjustments(
            _v_subs(70),
            _a_subs(70),
            grain,
            None,
            None,
            None,
            [],
            False,
            "blu_ray_digital",
        )
        vs = next(s for s in v if s.name == "perceptual_visual")
        self.assertEqual(vs.value, 80.0)  # +10
        self.assertTrue(any("grain_film_authentic" in t for t in trace))

    def test_rule1_partial_dnr_malus(self):
        grain = GrainAnalysis(is_partial_dnr=True, is_animation=False)
        v, _, trace = apply_contextual_adjustments(
            _v_subs(80),
            _a_subs(70),
            grain,
            None,
            None,
            None,
            [],
            False,
            "blu_ray_digital",
        )
        vs = next(s for s in v if s.name == "perceptual_visual")
        self.assertEqual(vs.value, 65.0)  # -15
        self.assertTrue(any("dnr_partial" in t for t in trace))

    def test_rule1_encode_noise_malus(self):
        grain = GrainAnalysis(grain_nature="encode_noise", is_animation=False)
        v, _, _ = apply_contextual_adjustments(
            _v_subs(70),
            _a_subs(70),
            grain,
            None,
            None,
            None,
            [],
            False,
            "blu_ray_digital",
        )
        vs = next(s for s in v if s.name == "perceptual_visual")
        self.assertEqual(vs.value, 62.0)  # -8

    def test_rule2_av1_afgs1_bonus(self):
        grain = GrainAnalysis(av1_afgs1_present=True, is_animation=False)
        v, _, trace = apply_contextual_adjustments(
            _v_subs(70),
            _a_subs(70),
            grain,
            None,
            None,
            None,
            [],
            False,
            "blu_ray_digital",
        )
        vs = next(s for s in v if s.name == "perceptual_visual")
        self.assertEqual(vs.value, 85.0)  # +15
        self.assertTrue(any("av1_afgs1" in t for t in trace))

    def test_rule3_dv_profile_5_malus(self):
        v, _, trace = apply_contextual_adjustments(
            _v_subs(80),
            _a_subs(70),
            None,
            None,
            None,
            None,
            ["dv_profile_5"],
            False,
            "blu_ray_digital",
        )
        vs = next(s for s in v if s.name == "hdr_validation")
        self.assertEqual(vs.value, 72.0)  # -8
        self.assertTrue(any("dv_profile_5" in t for t in trace))

    def test_rule4_hdr_metadata_missing_malus(self):
        v, _, _ = apply_contextual_adjustments(
            _v_subs(80),
            _a_subs(70),
            None,
            None,
            None,
            None,
            ["hdr_metadata_missing"],
            False,
            "blu_ray_digital",
        )
        vs = next(s for s in v if s.name == "hdr_validation")
        self.assertEqual(vs.value, 70.0)  # -10

    def test_rule5_imax_expansion_bonus(self):
        imax = SimpleNamespace(is_imax=True, imax_type="expansion")
        v, _, trace = apply_contextual_adjustments(
            _v_subs(80),
            _a_subs(70),
            None,
            None,
            None,
            imax,
            [],
            False,
            "blu_ray_digital",
        )
        vs = next(s for s in v if s.name == "resolution")
        self.assertEqual(vs.value, 95.0)  # +15
        self.assertTrue(any("imax_expansion" in t for t in trace))

    def test_rule5_imax_typed_bonus(self):
        imax = SimpleNamespace(is_imax=True, imax_type="full_frame_143")
        v, _, _ = apply_contextual_adjustments(
            _v_subs(80),
            _a_subs(70),
            None,
            None,
            None,
            imax,
            [],
            False,
            "blu_ray_digital",
        )
        vs = next(s for s in v if s.name == "resolution")
        self.assertEqual(vs.value, 90.0)  # +10

    def test_rule6_fake_lossless_malus(self):
        audio_subs = _a_subs(70)
        # Force spectral_cutoff en dessous de 60 pour déclencher la règle
        audio_subs[1] = SubScore(
            name="spectral_cutoff",
            value=55,
            weight=20,
            confidence=0.8,
            label_fr="L",
        )
        probe = {"audio": [{"codec": "flac"}]}
        _, a, trace = apply_contextual_adjustments(
            _v_subs(70),
            audio_subs,
            None,
            probe,
            None,
            None,
            [],
            False,
            "blu_ray_digital",
        )
        spec = next(s for s in a if s.name == "spectral_cutoff")
        self.assertEqual(spec.value, 45.0)  # -10
        self.assertTrue(any("fake_lossless" in t for t in trace))

    def test_rule8_animation_skips_grain_penalties(self):
        grain = GrainAnalysis(is_partial_dnr=True, is_animation=True)
        v, _, trace = apply_contextual_adjustments(
            _v_subs(80),
            _a_subs(70),
            grain,
            None,
            None,
            None,
            [],
            True,
            "blu_ray_digital",
        )
        vs = next(s for s in v if s.name == "perceptual_visual")
        self.assertEqual(vs.value, 80.0)  # pas touche
        self.assertTrue(any("skip_grain_rules" in t for t in trace))

    def test_rule9_vintage_reduces_grain_bonus(self):
        grain = GrainAnalysis(grain_nature="film_grain", is_animation=False, film_era_v2="16mm_era")
        v, _, trace = apply_contextual_adjustments(
            _v_subs(70),
            _a_subs(70),
            grain,
            None,
            None,
            None,
            [],
            False,
            "16mm_era",
        )
        vs = next(s for s in v if s.name == "perceptual_visual")
        # Bonus reduced from 10 to 7 (int(10 * 0.7))
        self.assertEqual(vs.value, 77.0)
        self.assertTrue(any("vintage_master_tolerance" in t for t in trace))


# ---------------------------------------------------------------------------
# compute_category + orchestrator
# ---------------------------------------------------------------------------


class TestOrchestrator(unittest.TestCase):
    def test_compute_category_from_subs(self):
        subs = [
            SubScore(name="a", value=100, weight=50, confidence=1.0, label_fr="A"),
            SubScore(name="b", value=50, weight=50, confidence=1.0, label_fr="B"),
        ]
        cat = compute_category("test", subs, 60)
        self.assertAlmostEqual(cat.value, 75.0, places=1)
        self.assertEqual(cat.weight, 60)
        self.assertEqual(len(cat.sub_scores), 2)

    def test_compute_global_perfect_uhd_hdr_platinum(self):
        v = VideoPerceptual(
            visual_score=95,
            frames_analyzed=15,
            resolution_width=3840,
            resolution_height=2160,
        )
        a = AudioPerceptual(
            audio_score=95,
            lossy_verdict="lossless",
            lossy_confidence=0.95,
            drc_category="cinema",
            drc_confidence=0.9,
            fingerprint_source="fpcalc",
        )
        g = GrainAnalysis(
            is_animation=False,
            film_era_v2="uhd_native_dolby_vision",
            grain_nature="film_grain",
        )
        probe = {"video": {"has_hdr10": True, "max_cll": 1000, "max_fall": 400}, "audio": [{"codec": "truehd"}]}
        r = compute_global_score_v2(
            v,
            a,
            g,
            probe,
            runtime_vs_tmdb_flag="match",
            nfo_consistency={"consistent": True, "has_tmdb_id": True},
            duration_s=7200,
        )
        self.assertEqual(r.global_tier, "platinum")
        self.assertGreaterEqual(r.global_score, 90)

    def test_compute_global_fake_4k_reject(self):
        v = VideoPerceptual(
            visual_score=55,
            frames_analyzed=15,
            resolution_width=3840,
            resolution_height=2160,
            fake_4k_verdict_combined="fake_4k_confirmed",
        )
        a = AudioPerceptual(audio_score=55, lossy_verdict="low_bitrate_lossy", lossy_confidence=0.9)
        g = GrainAnalysis(is_animation=False, grain_nature="encode_noise")
        r = compute_global_score_v2(v, a, g, None, duration_s=7200)
        # Video subscores penalises lourdement, audio aussi
        self.assertLess(r.global_score, 65)
        self.assertIn(r.global_tier, ("bronze", "reject", "silver"))

    def test_compute_global_empty_confidence_fallback(self):
        # Tous les objets vides → fallback neutre
        v = VideoPerceptual()
        a = AudioPerceptual()
        g = GrainAnalysis()
        r = compute_global_score_v2(v, a, g, None, duration_s=0)
        # Score non negatif, tier toujours determine
        self.assertGreaterEqual(r.global_score, 0)
        self.assertIn(r.global_tier, ("reject", "bronze", "silver", "gold", "platinum"))

    def test_compute_global_animation_ignores_grain_penalty(self):
        v = VideoPerceptual(visual_score=80, frames_analyzed=15, resolution_width=1920, resolution_height=1080)
        a = AudioPerceptual(audio_score=80, lossy_verdict="lossless", lossy_confidence=0.9)
        # Grain is_partial_dnr TRUE mais animation = TRUE → skip
        g = GrainAnalysis(is_animation=True, is_partial_dnr=True, grain_nature="encode_noise")
        r = compute_global_score_v2(v, a, g, None, duration_s=7200)
        self.assertTrue(any("skip_grain_rules" in t for t in r.adjustments_applied))

    def test_lpips_included_when_provided(self):
        v = VideoPerceptual(visual_score=80, frames_analyzed=15, resolution_width=1920, resolution_height=1080)
        a = AudioPerceptual(audio_score=80)
        g = GrainAnalysis()
        lpips = SimpleNamespace(distance_median=0.05)
        r = compute_global_score_v2(v, a, g, None, lpips_result=lpips, duration_s=7200)
        video_cat = next(c for c in r.category_scores if c.name == "video")
        self.assertIn("lpips_distance", {s.name for s in video_cat.sub_scores})


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


class TestCollectWarnings(unittest.TestCase):
    def _cats(self, video_val: float = 80, audio_val: float = 80) -> list:
        return [
            CategoryScore(name="video", value=video_val, weight=60, confidence=1.0, tier="gold", sub_scores=[]),
            CategoryScore(name="audio", value=audio_val, weight=35, confidence=1.0, tier="gold", sub_scores=[]),
            CategoryScore(name="coherence", value=80, weight=5, confidence=1.0, tier="gold", sub_scores=[]),
        ]

    def test_runtime_mismatch_warning(self):
        warns = collect_warnings(
            self._cats(),
            0.9,
            7200,
            [],
            "mismatch",
            {"video": {"duration_s": 8700}},
            False,
        )
        self.assertTrue(any("Theatrical" in w or "Extended" in w for w in warns))

    def test_dv_profile_5_warning(self):
        warns = collect_warnings(self._cats(), 0.9, 7200, ["dv_profile_5"], None, None, False)
        self.assertTrue(any("Dolby Vision Profile 5" in w for w in warns))

    def test_low_confidence_warning(self):
        warns = collect_warnings(self._cats(), 0.40, 7200, [], None, None, False)
        self.assertTrue(any("Analyse partielle" in w for w in warns))

    def test_short_file_warning(self):
        warns = collect_warnings(self._cats(), 0.9, 60, [], None, None, False)
        self.assertTrue(any("court" in w.lower() for w in warns))

    def test_imbalance_warning(self):
        warns = collect_warnings(self._cats(video_val=90, audio_val=40), 0.9, 7200, [], None, None, False)
        self.assertTrue(any("esequilibre" in w.lower() for w in warns))

    def test_no_warnings_perfect_file(self):
        warns = collect_warnings(self._cats(), 1.0, 7200, [], "match", None, False)
        self.assertEqual(warns, [])

    def test_fake_lossless_warning(self):
        warns = collect_warnings(self._cats(), 0.9, 7200, [], "match", None, True)
        self.assertTrue(any("lossless" in w.lower() for w in warns))


# ---------------------------------------------------------------------------
# GlobalScoreResult to_dict
# ---------------------------------------------------------------------------


class TestSerialization(unittest.TestCase):
    def test_global_score_result_to_dict(self):
        v = VideoPerceptual(visual_score=70, frames_analyzed=10, resolution_width=1920, resolution_height=1080)
        a = AudioPerceptual(audio_score=70)
        g = GrainAnalysis()
        r = compute_global_score_v2(v, a, g, None, duration_s=7200)
        d = r.to_dict()
        self.assertIn("global_score", d)
        self.assertIn("global_tier", d)
        self.assertIn("global_confidence", d)
        self.assertIn("category_scores", d)
        self.assertEqual(len(d["category_scores"]), 3)
        self.assertIn("warnings", d)
        self.assertIn("adjustments_applied", d)


if __name__ == "__main__":
    unittest.main()
