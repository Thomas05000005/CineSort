"""Tests §6 v7.5.0 — Dolby Vision profile classification."""

from __future__ import annotations

import unittest

from cinesort.domain.perceptual.hdr_analysis import (
    DolbyVisionInfo,
    analyze_dv_from_frame_data,
    classify_dv_profile,
    compute_dv_quality_score,
    detect_invalid_dv,
    extract_dv_configuration,
)


# ---------------------------------------------------------------------------
# extract_dv_configuration
# ---------------------------------------------------------------------------


class TestExtractDvConfiguration(unittest.TestCase):
    def test_finds_dovi_in_side_data(self):
        side = [
            {"side_data_type": "Mastering display metadata"},
            {
                "side_data_type": "DOVI configuration record",
                "dv_profile": 8,
                "dv_bl_signal_compatibility_id": 1,
                "rpu_present_flag": 1,
                "el_present_flag": 0,
                "bl_present_flag": 1,
            },
        ]
        config = extract_dv_configuration(side)
        self.assertIsNotNone(config)
        self.assertEqual(config["dv_profile"], 8)
        self.assertEqual(config["compat_id"], 1)
        self.assertTrue(config["rpu_present"])
        self.assertFalse(config["el_present"])
        self.assertTrue(config["bl_present"])

    def test_no_dovi_returns_none(self):
        side = [{"side_data_type": "Mastering display metadata"}]
        self.assertIsNone(extract_dv_configuration(side))

    def test_empty_list_returns_none(self):
        self.assertIsNone(extract_dv_configuration([]))

    def test_none_input_returns_none(self):
        self.assertIsNone(extract_dv_configuration(None))  # type: ignore[arg-type]

    def test_malformed_side_data(self):
        side = [{"side_data_type": "DOVI configuration record"}]  # aucun champ DV
        config = extract_dv_configuration(side)
        self.assertIsNotNone(config)
        self.assertEqual(config["dv_profile"], 0)
        self.assertEqual(config["compat_id"], 0)

    def test_flags_as_strings(self):
        side = [
            {
                "side_data_type": "DOVI configuration record",
                "dv_profile": "7",
                "rpu_present_flag": "1",
                "el_present_flag": "true",
            }
        ]
        config = extract_dv_configuration(side)
        self.assertEqual(config["dv_profile"], 7)
        self.assertTrue(config["rpu_present"])
        self.assertTrue(config["el_present"])


# ---------------------------------------------------------------------------
# classify_dv_profile
# ---------------------------------------------------------------------------


class TestClassifyDvProfile(unittest.TestCase):
    def test_profile_5(self):
        info = classify_dv_profile(dv_profile=5, compat_id=0, el_present=False, rpu_present=True)
        self.assertEqual(info.profile, "5")
        self.assertEqual(info.compatibility, "none")
        self.assertIsNotNone(info.warning)
        self.assertEqual(info.quality_score, 80)

    def test_profile_7_via_profile_flag(self):
        info = classify_dv_profile(dv_profile=7, compat_id=0, el_present=True, rpu_present=True)
        self.assertEqual(info.profile, "7")
        self.assertEqual(info.compatibility, "hdr10_partial")
        self.assertEqual(info.quality_score, 95)

    def test_profile_7_via_el_flag(self):
        # Certains rips ont dv_profile=0 mais el_present=1 -> quand meme profile 7
        info = classify_dv_profile(dv_profile=0, compat_id=0, el_present=True, rpu_present=True)
        self.assertEqual(info.profile, "7")

    def test_profile_8_1_hdr10_full(self):
        info = classify_dv_profile(dv_profile=8, compat_id=1, el_present=False, rpu_present=True)
        self.assertEqual(info.profile, "8.1")
        self.assertEqual(info.compatibility, "hdr10_full")
        self.assertIsNone(info.warning)
        self.assertEqual(info.quality_score, 100)

    def test_profile_8_2_sdr(self):
        info = classify_dv_profile(dv_profile=8, compat_id=2, el_present=False, rpu_present=True)
        self.assertEqual(info.profile, "8.2")
        self.assertEqual(info.compatibility, "sdr")
        self.assertEqual(info.quality_score, 82)

    def test_profile_8_4_hlg(self):
        info = classify_dv_profile(dv_profile=8, compat_id=4, el_present=False, rpu_present=True)
        self.assertEqual(info.profile, "8.4")
        self.assertEqual(info.compatibility, "hlg")
        self.assertEqual(info.quality_score, 88)

    def test_profile_8_unknown_compat(self):
        # profile=8, compat=3 -> inconnu (pas defini par Dolby)
        info = classify_dv_profile(dv_profile=8, compat_id=3, el_present=False, rpu_present=True)
        self.assertEqual(info.profile, "unknown")
        self.assertEqual(info.compatibility, "none")

    def test_unknown_profile(self):
        info = classify_dv_profile(dv_profile=9, compat_id=0, el_present=False, rpu_present=False)
        self.assertEqual(info.profile, "unknown")
        self.assertIsNotNone(info.warning)


# ---------------------------------------------------------------------------
# detect_invalid_dv
# ---------------------------------------------------------------------------


class TestDetectInvalidDv(unittest.TestCase):
    def test_not_present_returns_none(self):
        info = DolbyVisionInfo(
            present=False,
            profile="none",
            compatibility="none",
            el_present=False,
            rpu_present=False,
            warning=None,
            quality_score=0,
        )
        self.assertIsNone(detect_invalid_dv(info))

    def test_no_rpu_invalid(self):
        info = DolbyVisionInfo(
            present=True,
            profile="8.1",
            compatibility="hdr10_full",
            el_present=False,
            rpu_present=False,
            warning=None,
            quality_score=100,
        )
        self.assertEqual(detect_invalid_dv(info), "dv_invalid_no_rpu")

    def test_profile_7_el_missing(self):
        info = DolbyVisionInfo(
            present=True,
            profile="7",
            compatibility="hdr10_partial",
            el_present=False,
            rpu_present=True,
            warning=None,
            quality_score=95,
        )
        self.assertEqual(detect_invalid_dv(info), "dv_el_expected_missing")

    def test_profile_7_el_present_valid(self):
        info = DolbyVisionInfo(
            present=True,
            profile="7",
            compatibility="hdr10_partial",
            el_present=True,
            rpu_present=True,
            warning=None,
            quality_score=95,
        )
        self.assertIsNone(detect_invalid_dv(info))

    def test_valid_returns_none(self):
        info = DolbyVisionInfo(
            present=True,
            profile="8.1",
            compatibility="hdr10_full",
            el_present=False,
            rpu_present=True,
            warning=None,
            quality_score=100,
        )
        self.assertIsNone(detect_invalid_dv(info))


# ---------------------------------------------------------------------------
# compute_dv_quality_score
# ---------------------------------------------------------------------------


class TestComputeDvQualityScore(unittest.TestCase):
    def test_not_present_returns_0(self):
        info = DolbyVisionInfo(
            present=False,
            profile="none",
            compatibility="none",
            el_present=False,
            rpu_present=False,
            warning=None,
            quality_score=999,
        )
        self.assertEqual(compute_dv_quality_score(info), 0)

    def test_profile_8_1_top(self):
        info = DolbyVisionInfo(
            present=True,
            profile="8.1",
            compatibility="hdr10_full",
            el_present=False,
            rpu_present=True,
            warning=None,
            quality_score=0,
        )
        self.assertEqual(compute_dv_quality_score(info), 100)

    def test_profile_7(self):
        info = DolbyVisionInfo(
            present=True,
            profile="7",
            compatibility="hdr10_partial",
            el_present=True,
            rpu_present=True,
            warning=None,
            quality_score=0,
        )
        self.assertEqual(compute_dv_quality_score(info), 95)

    def test_profile_5_penalized(self):
        info = DolbyVisionInfo(
            present=True,
            profile="5",
            compatibility="none",
            el_present=False,
            rpu_present=True,
            warning=None,
            quality_score=0,
        )
        self.assertEqual(compute_dv_quality_score(info), 80)


# ---------------------------------------------------------------------------
# analyze_dv_from_frame_data
# ---------------------------------------------------------------------------


class TestAnalyzeDvFromFrameData(unittest.TestCase):
    def test_sdr_no_dv(self):
        stream = {"color_primaries": "bt709"}
        info = analyze_dv_from_frame_data(stream, None)
        self.assertFalse(info.present)
        self.assertEqual(info.profile, "none")

    def test_profile_8_1_in_frame(self):
        frame = {
            "side_data_list": [
                {
                    "side_data_type": "DOVI configuration record",
                    "dv_profile": 8,
                    "dv_bl_signal_compatibility_id": 1,
                    "rpu_present_flag": 1,
                    "el_present_flag": 0,
                    "bl_present_flag": 1,
                }
            ]
        }
        info = analyze_dv_from_frame_data({}, frame)
        self.assertTrue(info.present)
        self.assertEqual(info.profile, "8.1")
        self.assertEqual(info.compatibility, "hdr10_full")
        self.assertEqual(info.quality_score, 100)

    def test_profile_5_warning_set(self):
        frame = {
            "side_data_list": [
                {
                    "side_data_type": "DOVI configuration record",
                    "dv_profile": 5,
                    "rpu_present_flag": 1,
                    "bl_present_flag": 1,
                }
            ]
        }
        info = analyze_dv_from_frame_data({}, frame)
        self.assertEqual(info.profile, "5")
        self.assertIsNotNone(info.warning)
        self.assertIn("Player", info.warning)

    def test_dv_no_rpu_warning_overridden(self):
        frame = {
            "side_data_list": [
                {
                    "side_data_type": "DOVI configuration record",
                    "dv_profile": 8,
                    "dv_bl_signal_compatibility_id": 1,
                    "rpu_present_flag": 0,
                    "el_present_flag": 0,
                }
            ]
        }
        info = analyze_dv_from_frame_data({}, frame)
        self.assertTrue(info.present)
        self.assertEqual(info.profile, "8.1")
        self.assertIn("sans RPU", info.warning)

    def test_profile_7_el_missing_warning(self):
        frame = {
            "side_data_list": [
                {
                    "side_data_type": "DOVI configuration record",
                    "dv_profile": 7,
                    "rpu_present_flag": 1,
                    "el_present_flag": 0,
                }
            ]
        }
        info = analyze_dv_from_frame_data({}, frame)
        self.assertEqual(info.profile, "7")
        self.assertIn("Enhancement Layer", info.warning)

    def test_stream_side_data_fallback(self):
        stream = {
            "side_data_list": [
                {
                    "side_data_type": "DOVI configuration record",
                    "dv_profile": 8,
                    "dv_bl_signal_compatibility_id": 4,
                    "rpu_present_flag": 1,
                }
            ]
        }
        info = analyze_dv_from_frame_data(stream, None)
        self.assertEqual(info.profile, "8.4")


# ---------------------------------------------------------------------------
# Integration normalize.py
# ---------------------------------------------------------------------------


class TestIntegrationNormalize(unittest.TestCase):
    def test_video_dict_contains_dv_fields(self):
        from cinesort.infra.probe.normalize import _ffprobe_video_dict

        stream = {
            "codec_name": "hevc",
            "width": 3840,
            "height": 2160,
            "color_primaries": "bt2020",
            "color_transfer": "smpte2084",
        }
        frame = {
            "side_data_list": [
                {
                    "side_data_type": "DOVI configuration record",
                    "dv_profile": 8,
                    "dv_bl_signal_compatibility_id": 1,
                    "rpu_present_flag": 1,
                    "el_present_flag": 0,
                }
            ]
        }
        out = _ffprobe_video_dict(stream, {}, frame)
        self.assertTrue(out.get("dv_present"))
        self.assertEqual(out.get("dv_profile"), "8.1")
        self.assertEqual(out.get("dv_compatibility"), "hdr10_full")
        self.assertFalse(out.get("dv_el_present"))
        self.assertTrue(out.get("dv_rpu_present"))
        self.assertIsNone(out.get("dv_warning"))
        self.assertEqual(out.get("dv_quality_score"), 100)

    def test_video_dict_without_dv(self):
        from cinesort.infra.probe.normalize import _ffprobe_video_dict

        stream = {"codec_name": "h264", "width": 1920, "height": 1080}
        out = _ffprobe_video_dict(stream, {}, None)
        self.assertFalse(out.get("dv_present"))
        self.assertEqual(out.get("dv_profile"), "none")
        self.assertEqual(out.get("dv_quality_score"), 0)


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    def test_all_profiles_have_labels(self):
        from cinesort.domain.perceptual.constants import DV_PROFILE_LABELS, DV_QUALITY_SCORE

        for key in ("5", "7", "8.1", "8.2", "8.4", "unknown", "none"):
            self.assertIn(key, DV_PROFILE_LABELS)
            self.assertIn(key, DV_QUALITY_SCORE)


if __name__ == "__main__":
    unittest.main()
