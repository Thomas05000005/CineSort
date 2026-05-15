"""Tests §15 v7.5.0 — Grain Intelligence v2 (section phare)."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from cinesort.domain.perceptual.av1_grain_metadata import (
    extract_av1_film_grain_params,
    has_afgs1_in_side_data,
)
from cinesort.domain.perceptual.grain_classifier import (
    classify_grain_nature,
    compute_cross_color_correlation,
    compute_spatial_autocorr_8dir,
    compute_temporal_correlation,
    detect_partial_dnr,
    find_flat_zones,
)
from cinesort.domain.perceptual.grain_signatures import (
    classify_film_era_v2,
    detect_film_format_hint,
    get_expected_grain_signature,
)


def _fake_completed(stdout: str = "", returncode: int = 0) -> MagicMock:
    cp = MagicMock()
    cp.stdout = stdout
    cp.stderr = ""
    cp.returncode = returncode
    return cp


# ---------------------------------------------------------------------------
# grain_signatures
# ---------------------------------------------------------------------------


class TestClassifyFilmEraV2(unittest.TestCase):
    def test_1975_is_16mm_era(self):
        self.assertEqual(classify_film_era_v2(1975), "16mm_era")

    def test_1985_is_35mm_classic(self):
        self.assertEqual(classify_film_era_v2(1985), "35mm_classic")

    def test_2003_is_late_film(self):
        self.assertEqual(classify_film_era_v2(2003), "late_film")

    def test_2010_is_transition(self):
        self.assertEqual(classify_film_era_v2(2010), "transition")

    def test_2018_is_digital_modern(self):
        self.assertEqual(classify_film_era_v2(2018), "digital_modern")

    def test_2023_is_digital_hdr_era(self):
        self.assertEqual(classify_film_era_v2(2023), "digital_hdr_era")

    def test_unknown_year_zero(self):
        self.assertEqual(classify_film_era_v2(0), "unknown")

    def test_unknown_year_negative(self):
        self.assertEqual(classify_film_era_v2(-10), "unknown")

    def test_70mm_format_override(self):
        self.assertEqual(classify_film_era_v2(2023, film_format="70mm"), "large_format_classic")


class TestDetectFilmFormatHint(unittest.TestCase):
    def test_keyword_70mm(self):
        self.assertEqual(detect_film_format_hint(2160, 120, ["70mm", "Drama"], 2020), "70mm")

    def test_keyword_imax_film(self):
        self.assertEqual(detect_film_format_hint(2160, 120, ["IMAX Film"], 2015), "70mm")

    def test_res_8k_pre_2000(self):
        self.assertEqual(detect_film_format_hint(4500, 120, [], 1985), "70mm")

    def test_runtime_long_pre_1990(self):
        self.assertEqual(detect_film_format_hint(1080, 180, [], 1970), "70mm")

    def test_modern_high_res_returns_none(self):
        self.assertIsNone(detect_film_format_hint(2160, 120, [], 2020))

    def test_none_returns_none(self):
        self.assertIsNone(detect_film_format_hint(1080, 90, [], 2015))


class TestGetExpectedGrainSignature(unittest.TestCase):
    def test_animation_aplats(self):
        sig = get_expected_grain_signature(
            era="digital_modern",
            genres=["Animation", "Adventure"],
            budget=100_000_000,
        )
        self.assertEqual(sig["label"], "animation_aplats")
        self.assertEqual(sig["level_mean"], 0.0)

    def test_pixar_animation_studio(self):
        # Pixar matche avant la regle animation generique ? Non : animation vient
        # en premier. Mais Pixar avec genre "Family" seul matche pixar rule.
        sig = get_expected_grain_signature(
            era="digital_modern",
            genres=["Family"],
            companies=["Pixar"],
        )
        self.assertEqual(sig["label"], "major_animation_studio")

    def test_nolan_syncopy_digital(self):
        sig = get_expected_grain_signature(
            era="digital_modern",
            genres=["Drama"],
            companies=["Syncopy"],
        )
        self.assertEqual(sig["label"], "nolan_intentional_grain")

    def test_nolan_syncopy_hdr_era(self):
        sig = get_expected_grain_signature(
            era="digital_hdr_era",
            companies=["Syncopy"],
        )
        self.assertEqual(sig["label"], "nolan_intentional_grain")

    def test_a24_digital_modern(self):
        sig = get_expected_grain_signature(
            era="digital_modern",
            genres=["Drama"],
            companies=["A24"],
        )
        self.assertEqual(sig["label"], "a24_filmic_aesthetic")

    def test_16mm_horror(self):
        sig = get_expected_grain_signature(
            era="16mm_era",
            genres=["Horror"],
        )
        self.assertEqual(sig["label"], "16mm_horror_grain")

    def test_fallback_era_profile(self):
        sig = get_expected_grain_signature(
            era="35mm_classic",
            genres=["Drama"],
            companies=["Unknown Studio"],
        )
        self.assertEqual(sig["label"], "default_35mm_classic_profile")
        self.assertEqual(sig["level_mean"], 3.0)

    def test_fallback_unknown_era(self):
        sig = get_expected_grain_signature(era="unknown", genres=["Drama"])
        self.assertIn("default_", sig["label"])


# ---------------------------------------------------------------------------
# av1_grain_metadata
# ---------------------------------------------------------------------------


class TestHasAfgs1InSideData(unittest.TestCase):
    def test_itut_t35_aomedia_pattern(self):
        side = [{"itu_t_t35_country_code": 181, "itu_t_t35_provider_code": 22672}]
        self.assertTrue(has_afgs1_in_side_data(side))

    def test_string_marker(self):
        side = [{"side_data_type": "AOMedia Film Grain Synthesis v1"}]
        self.assertTrue(has_afgs1_in_side_data(side))

    def test_no_afgs1(self):
        side = [{"side_data_type": "Something else"}]
        self.assertFalse(has_afgs1_in_side_data(side))

    def test_empty(self):
        self.assertFalse(has_afgs1_in_side_data([]))


class TestExtractAv1FilmGrainParams(unittest.TestCase):
    def test_av1_with_afgs1(self):
        payload = {
            "streams": [
                {
                    "codec_name": "av1",
                    "profile": "Main",
                    "side_data_list": [{"itu_t_t35_country_code": 181, "itu_t_t35_provider_code": 22672}],
                }
            ]
        }
        with patch(
            "cinesort.domain.perceptual.av1_grain_metadata.tracked_run",
            return_value=_fake_completed(stdout=json.dumps(payload)),
        ):
            info = extract_av1_film_grain_params("ffprobe", "x.mkv")
        self.assertIsNotNone(info)
        self.assertTrue(info.present)
        self.assertTrue(info.has_afgs1_t35)

    def test_av1_without_afgs1(self):
        payload = {"streams": [{"codec_name": "av1", "side_data_list": []}]}
        with patch(
            "cinesort.domain.perceptual.av1_grain_metadata.tracked_run",
            return_value=_fake_completed(stdout=json.dumps(payload)),
        ):
            info = extract_av1_film_grain_params("ffprobe", "x.mkv")
        self.assertIsNone(info)

    def test_hevc_codec_returns_none(self):
        payload = {"streams": [{"codec_name": "hevc"}]}
        with patch(
            "cinesort.domain.perceptual.av1_grain_metadata.tracked_run",
            return_value=_fake_completed(stdout=json.dumps(payload)),
        ):
            self.assertIsNone(extract_av1_film_grain_params("ffprobe", "x.mkv"))

    def test_ffprobe_error(self):
        with patch(
            "cinesort.domain.perceptual.av1_grain_metadata.tracked_run",
            return_value=_fake_completed(returncode=1),
        ):
            self.assertIsNone(extract_av1_film_grain_params("ffprobe", "x.mkv"))

    def test_timeout(self):
        with patch(
            "cinesort.domain.perceptual.av1_grain_metadata.tracked_run",
            side_effect=subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=10),
        ):
            self.assertIsNone(extract_av1_film_grain_params("ffprobe", "x.mkv"))

    def test_missing_path(self):
        self.assertIsNone(extract_av1_film_grain_params("", "x.mkv"))


# ---------------------------------------------------------------------------
# grain_classifier
# ---------------------------------------------------------------------------


def _uniform_frame(h: int, w: int, value: float = 128.0) -> np.ndarray:
    return np.full((h, w), value, dtype=np.float64)


def _noisy_frame(h: int, w: int, std: float = 5.0, seed: int = 0, base: float = 128.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (base + rng.normal(0, std, (h, w))).astype(np.float64)


def _blocky_frame(h: int, w: int, block_size: int = 8, seed: int = 0) -> np.ndarray:
    """Frame avec blocs 8x8 uniformes (simule artefact DCT)."""
    rng = np.random.default_rng(seed)
    small = rng.normal(128, 20, (h // block_size, w // block_size))
    return np.repeat(np.repeat(small, block_size, axis=0), block_size, axis=1)[:h, :w]


class TestFindFlatZones(unittest.TestCase):
    def test_uniform_frame_many_zones(self):
        frame = _uniform_frame(64, 64)
        zones = find_flat_zones(frame, block_size=16, max_zones=20)
        self.assertGreater(len(zones), 0)

    def test_noisy_frame_fewer_flat(self):
        frame = _noisy_frame(64, 64, std=20.0)
        zones_noisy = find_flat_zones(frame, block_size=16, flat_threshold=50.0)
        # Haute variance -> peu ou pas de zones plates
        self.assertLess(len(zones_noisy), 4)

    def test_respects_max_zones(self):
        frame = _uniform_frame(128, 128)
        zones = find_flat_zones(frame, block_size=16, max_zones=5)
        self.assertLessEqual(len(zones), 5)

    def test_small_frame_empty(self):
        frame = _uniform_frame(8, 8)
        zones = find_flat_zones(frame, block_size=16)
        self.assertEqual(zones, [])


class TestComputeTemporalCorrelation(unittest.TestCase):
    def test_identical_frames_high(self):
        frame = _noisy_frame(64, 64, std=3.0, seed=1)
        zones = find_flat_zones(frame, flat_threshold=200.0)
        frames = [frame, frame.copy(), frame.copy()]
        zones_per = [zones, zones, zones]
        corr = compute_temporal_correlation(frames, zones_per)
        # Identiques -> corr elevee
        self.assertGreater(corr, 0.8)

    def test_random_noise_low_corr(self):
        frames = [_noisy_frame(64, 64, std=3.0, seed=i) for i in range(3)]
        zones_per = [find_flat_zones(f, flat_threshold=200.0) for f in frames]
        corr = compute_temporal_correlation(frames, zones_per)
        # Bruits independants -> corr basse
        self.assertLess(corr, 0.35)

    def test_single_frame_returns_zero(self):
        frame = _uniform_frame(32, 32)
        self.assertEqual(compute_temporal_correlation([frame], [[]]), 0.0)

    def test_empty_returns_zero(self):
        self.assertEqual(compute_temporal_correlation([], []), 0.0)


class TestComputeSpatialAutocorr8dir(unittest.TestCase):
    def test_white_noise_low_correlations(self):
        frame = _noisy_frame(64, 64, std=5.0, seed=42)
        zones = [(0, 0, 64, 64)]
        corrs = compute_spatial_autocorr_8dir(frame, zones, lags=[1, 8, 16])
        # Bruit blanc -> pas de structure, corrs faibles
        self.assertLess(corrs[1], 0.5)

    def test_block_8x8_peak_at_lag_8(self):
        frame = _blocky_frame(64, 64, block_size=8, seed=1)
        zones = [(0, 0, 64, 64)]
        corrs = compute_spatial_autocorr_8dir(frame, zones, lags=[1, 8])
        # Motif 8x8 : correlation forte a lag 8 (blocs identiques a distance 8)
        self.assertGreater(corrs[8], 0.3)

    def test_empty_zones(self):
        frame = _uniform_frame(64, 64)
        corrs = compute_spatial_autocorr_8dir(frame, [], lags=[1, 8])
        self.assertEqual(corrs[1], 0.0)
        self.assertEqual(corrs[8], 0.0)


class TestComputeCrossColorCorrelation(unittest.TestCase):
    def test_frames_rgb_none(self):
        self.assertIsNone(compute_cross_color_correlation(None, [[]]))

    def test_empty_rgb(self):
        self.assertIsNone(compute_cross_color_correlation([], []))

    def test_correlated_noise_high(self):
        # Meme bruit applique aux 3 canaux -> correlation parfaite
        rng = np.random.default_rng(0)
        noise = rng.normal(0, 5, (32, 32))
        rgb = np.stack([128 + noise, 128 + noise, 128 + noise], axis=-1)
        zones = [(0, 0, 32, 32)]
        corr = compute_cross_color_correlation([rgb], [zones])
        self.assertIsNotNone(corr)
        self.assertGreater(corr, 0.9)

    def test_decorrelated_noise_low(self):
        rng = np.random.default_rng(0)
        r = 128 + rng.normal(0, 5, (32, 32))
        g = 128 + rng.normal(0, 5, (32, 32))
        b = 128 + rng.normal(0, 5, (32, 32))
        rgb = np.stack([r, g, b], axis=-1)
        zones = [(0, 0, 32, 32)]
        corr = compute_cross_color_correlation([rgb], [zones])
        self.assertIsNotNone(corr)
        self.assertLess(corr, 0.3)


class TestClassifyGrainNature(unittest.TestCase):
    def test_insufficient_frames_unknown(self):
        v = classify_grain_nature([_uniform_frame(64, 64)])
        self.assertEqual(v.nature, "unknown")

    def test_film_grain_verdict(self):
        # Grain argentique simule : bruit independant par frame (correlation temporelle faible)
        frames = [_noisy_frame(128, 128, std=4.0, seed=i, base=128.0) for i in range(4)]
        v = classify_grain_nature(frames, frames_rgb=None)
        # Bruit random + faible correlation temporelle -> film_grain
        self.assertIn(v.nature, ("film_grain", "ambiguous"))
        self.assertGreater(v.confidence, 0.0)

    def test_encode_noise_verdict(self):
        # Encode noise : meme bruit dans les 4 frames (correlation temporelle = 1)
        rng = np.random.default_rng(42)
        shared_noise = rng.normal(0, 3, (128, 128))
        frames = [128 + shared_noise for _ in range(4)]
        v = classify_grain_nature(frames, frames_rgb=None)
        # Correlation temporelle elevee -> encode_noise
        self.assertIn(v.nature, ("encode_noise", "ambiguous"))
        self.assertGreater(v.temporal_corr, 0.5)


class TestDetectPartialDnr(unittest.TestCase):
    def test_normal_texture_not_dnr(self):
        frames = [_noisy_frame(64, 64, std=10.0, seed=i) for i in range(3)]
        v = detect_partial_dnr(frames, grain_level=1.0, texture_variance_baseline=80.0)
        # Texture normale -> pas DNR
        self.assertFalse(v.is_partial_dnr)

    def test_low_texture_low_grain_is_dnr(self):
        # Frames avec texture faible (variance ~16-25, dans la zone texture 10-500)
        # mais loin du baseline attendu (250) -> DNR partiel probable
        frames = [_noisy_frame(64, 64, std=4.0, seed=i) for i in range(3)]
        v = detect_partial_dnr(frames, grain_level=0.3, texture_variance_baseline=250.0)
        self.assertTrue(v.is_partial_dnr)
        self.assertIn("DNR", v.detail_fr)
        self.assertGreater(v.texture_loss_ratio, 0.0)

    def test_low_texture_high_grain_not_dnr(self):
        # Grain mesure eleve meme si texture baisse -> pas DNR (grain present)
        frames = [_noisy_frame(64, 64, std=2.0, seed=i) for i in range(3)]
        v = detect_partial_dnr(frames, grain_level=3.0, texture_variance_baseline=200.0)
        self.assertFalse(v.is_partial_dnr)

    def test_no_frames_insufficient(self):
        v = detect_partial_dnr([], grain_level=1.0, texture_variance_baseline=150.0)
        self.assertFalse(v.is_partial_dnr)
        self.assertIn("insuffisantes", v.detail_fr)


# ---------------------------------------------------------------------------
# Model serialization
# ---------------------------------------------------------------------------


class TestGrainAnalysisSerialization(unittest.TestCase):
    def test_to_dict_contains_grain_intelligence_block(self):
        from cinesort.domain.perceptual.models import GrainAnalysis

        g = GrainAnalysis()
        g.film_era_v2 = "digital_modern"
        g.grain_nature = "film_grain"
        g.grain_nature_confidence = 0.85
        g.temporal_correlation = 0.15
        g.is_partial_dnr = True
        g.texture_loss_ratio = 0.35
        g.av1_afgs1_present = True
        g.historical_context_fr = "Test context"
        d = g.to_dict()
        self.assertIn("grain_intelligence", d)
        self.assertEqual(d["grain_intelligence"]["film_era_v2"], "digital_modern")
        self.assertEqual(d["grain_intelligence"]["nature"], "film_grain")
        self.assertAlmostEqual(d["grain_intelligence"]["nature_confidence"], 0.85)
        self.assertTrue(d["grain_intelligence"]["dnr_partial"]["is_partial_dnr"])
        self.assertTrue(d["grain_intelligence"]["av1_afgs1_present"])


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestSettings(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile

        import cinesort.ui.api.cinesort_api as backend

        self._tmp = tempfile.mkdtemp(prefix="cinesort_grain_")
        self._root = Path(self._tmp) / "root"
        self._sd = Path(self._tmp) / "state"
        self._root.mkdir()
        self._sd.mkdir()
        self.api = backend.CineSortApi()
        self.api._state_dir = self._sd
        self._shutil = shutil

    def tearDown(self):
        self._shutil.rmtree(self._tmp, ignore_errors=True)

    def test_default_enabled(self):
        s = self.api.settings.get_settings()
        self.assertTrue(s.get("perceptual_grain_intelligence_enabled"))

    def test_roundtrip_false(self):
        self.api.settings.save_settings(
            {
                "root": str(self._root),
                "state_dir": str(self._sd),
                "perceptual_grain_intelligence_enabled": False,
            }
        )
        s = self.api.settings.get_settings()
        self.assertFalse(s.get("perceptual_grain_intelligence_enabled"))


class TestSpecContainsGrainModules(unittest.TestCase):
    def test_hiddenimports(self):
        spec = (Path(__file__).resolve().parents[1] / "CineSort.spec").read_text(encoding="utf-8")
        self.assertIn("cinesort.domain.perceptual.grain_signatures", spec)
        self.assertIn("cinesort.domain.perceptual.av1_grain_metadata", spec)
        self.assertIn("cinesort.domain.perceptual.grain_classifier", spec)


if __name__ == "__main__":
    unittest.main()
