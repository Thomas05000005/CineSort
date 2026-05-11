"""Tests §5 v7.5.0 — HDR metadata."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.domain.perceptual.hdr_analysis import (
    HdrInfo,
    analyze_hdr_from_frame_data,
    compute_hdr_quality_score,
    detect_hdr10_plus_multi_frame,
    detect_hdr_type,
    parse_ratio,
    validate_hdr,
)


def _fake_completed(stdout: str = "", returncode: int = 0) -> MagicMock:
    cp = MagicMock()
    cp.stdout = stdout
    cp.stderr = ""
    cp.returncode = returncode
    return cp


# ---------------------------------------------------------------------------
# parse_ratio
# ---------------------------------------------------------------------------


class TestParseRatio(unittest.TestCase):
    def test_valid_ratio(self):
        self.assertAlmostEqual(parse_ratio("10000000/10000"), 1000.0)

    def test_fraction(self):
        self.assertAlmostEqual(parse_ratio("34000/50000"), 0.68)

    def test_none_returns_0(self):
        self.assertEqual(parse_ratio(None), 0.0)

    def test_zero_denominator(self):
        self.assertEqual(parse_ratio("1000/0"), 0.0)

    def test_malformed_string(self):
        self.assertEqual(parse_ratio("not a ratio"), 0.0)

    def test_plain_float(self):
        self.assertAlmostEqual(parse_ratio("500.5"), 500.5)

    def test_plain_int(self):
        self.assertAlmostEqual(parse_ratio(500), 500.0)


# ---------------------------------------------------------------------------
# detect_hdr_type
# ---------------------------------------------------------------------------


class TestDetectHdrType(unittest.TestCase):
    def test_hlg_via_transfer(self):
        v = detect_hdr_type("bt2020", "arib-std-b67", [])
        self.assertEqual(v, "hlg")

    def test_hlg_via_transfer_named(self):
        v = detect_hdr_type("bt2020", "hlg", [])
        self.assertEqual(v, "hlg")

    def test_dolby_vision_via_side_data(self):
        sd = [{"side_data_type": "DOVI configuration record"}]
        v = detect_hdr_type("bt2020", "smpte2084", sd)
        self.assertEqual(v, "dolby_vision")

    def test_hdr10_plus_via_side_data(self):
        sd = [{"side_data_type": "HDR Dynamic Metadata SMPTE ST 2094-40"}]
        v = detect_hdr_type("bt2020", "smpte2084", sd)
        self.assertEqual(v, "hdr10_plus")

    def test_hdr10_standard(self):
        sd = [{"side_data_type": "Mastering display metadata"}]
        v = detect_hdr_type("bt2020", "smpte2084", sd)
        self.assertEqual(v, "hdr10")

    def test_hdr10_without_mastering_still_classified(self):
        # Transfer smpte2084 + primaries bt2020 suffit
        v = detect_hdr_type("bt2020", "smpte2084", [])
        self.assertEqual(v, "hdr10")

    def test_sdr_default(self):
        v = detect_hdr_type("bt709", "bt709", [])
        self.assertEqual(v, "sdr")

    def test_sdr_empty_strings(self):
        v = detect_hdr_type("", "", [])
        self.assertEqual(v, "sdr")

    def test_priority_hlg_over_hdr10(self):
        # HLG meme si bt2020 + mastering
        sd = [{"side_data_type": "Mastering display metadata"}]
        v = detect_hdr_type("bt2020", "arib-std-b67", sd)
        self.assertEqual(v, "hlg")


# ---------------------------------------------------------------------------
# validate_hdr
# ---------------------------------------------------------------------------


class TestValidateHdr(unittest.TestCase):
    def test_hdr10_no_maxcll_missing(self):
        ok, flag = validate_hdr("hdr10", max_cll=0.0, max_fall=0.0, color_primaries="bt2020")
        self.assertFalse(ok)
        self.assertEqual(flag, "hdr_metadata_missing")

    def test_hdr10_low_punch(self):
        ok, flag = validate_hdr("hdr10", max_cll=400.0, max_fall=100.0, color_primaries="bt2020")
        self.assertTrue(ok)
        self.assertEqual(flag, "hdr_low_punch")

    def test_hdr10_valid(self):
        ok, flag = validate_hdr("hdr10", max_cll=1000.0, max_fall=400.0, color_primaries="bt2020")
        self.assertTrue(ok)
        self.assertIsNone(flag)

    def test_sdr_bt2020_color_mismatch(self):
        ok, flag = validate_hdr("sdr", max_cll=0, max_fall=0, color_primaries="bt2020")
        self.assertFalse(ok)
        self.assertEqual(flag, "color_mismatch_sdr_bt2020")

    def test_hlg_always_valid(self):
        ok, flag = validate_hdr("hlg", max_cll=0, max_fall=0, color_primaries="bt2020")
        self.assertTrue(ok)
        self.assertIsNone(flag)

    def test_dv_always_valid(self):
        ok, flag = validate_hdr("dolby_vision", max_cll=0, max_fall=0, color_primaries="bt2020")
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# compute_hdr_quality_score
# ---------------------------------------------------------------------------


def _mk_hdr(hdr_type: str, flag=None) -> HdrInfo:
    return HdrInfo(
        hdr_type=hdr_type,
        max_cll=1000 if hdr_type == "hdr10" else 0,
        max_fall=0,
        min_luminance=0,
        max_luminance=1000,
        color_primaries="bt2020",
        color_transfer="smpte2084",
        color_space="bt2020",
        is_valid=True,
        validation_flag=flag,
        quality_score=0,
    )


class TestComputeHdrQualityScore(unittest.TestCase):
    def test_dv_100(self):
        self.assertEqual(compute_hdr_quality_score(_mk_hdr("dolby_vision")), 100)

    def test_hdr10_plus_90(self):
        self.assertEqual(compute_hdr_quality_score(_mk_hdr("hdr10_plus")), 90)

    def test_hdr10_valid_85(self):
        self.assertEqual(compute_hdr_quality_score(_mk_hdr("hdr10")), 85)

    def test_hdr10_low_punch_65(self):
        self.assertEqual(compute_hdr_quality_score(_mk_hdr("hdr10", flag="hdr_low_punch")), 65)

    def test_hdr10_invalid_50(self):
        self.assertEqual(compute_hdr_quality_score(_mk_hdr("hdr10", flag="hdr_metadata_missing")), 50)

    def test_hlg_75(self):
        self.assertEqual(compute_hdr_quality_score(_mk_hdr("hlg")), 75)

    def test_sdr_40(self):
        self.assertEqual(compute_hdr_quality_score(_mk_hdr("sdr")), 40)


# ---------------------------------------------------------------------------
# analyze_hdr_from_frame_data
# ---------------------------------------------------------------------------


class TestAnalyzeHdrFromFrameData(unittest.TestCase):
    def test_sdr_default(self):
        stream = {"color_primaries": "bt709", "color_transfer": "bt709", "color_space": "bt709"}
        out = analyze_hdr_from_frame_data(stream, None)
        self.assertEqual(out.hdr_type, "sdr")
        self.assertEqual(out.quality_score, 40)

    def test_hdr10_from_frame_side_data(self):
        stream = {}
        frame = {
            "color_primaries": "bt2020",
            "color_transfer": "smpte2084",
            "color_space": "bt2020nc",
            "side_data_list": [
                {
                    "side_data_type": "Mastering display metadata",
                    "min_luminance": "50/10000",
                    "max_luminance": "10000000/10000",
                },
                {"side_data_type": "Content light level metadata", "max_content": 1000, "max_average": 400},
            ],
        }
        out = analyze_hdr_from_frame_data(stream, frame)
        self.assertEqual(out.hdr_type, "hdr10")
        self.assertAlmostEqual(out.max_cll, 1000.0)
        self.assertAlmostEqual(out.max_fall, 400.0)
        self.assertAlmostEqual(out.max_luminance, 1000.0)
        self.assertAlmostEqual(out.min_luminance, 0.005)
        self.assertEqual(out.quality_score, 85)

    def test_hdr10_plus_from_side_data(self):
        frame = {
            "color_primaries": "bt2020",
            "color_transfer": "smpte2084",
            "side_data_list": [
                {"side_data_type": "HDR Dynamic Metadata SMPTE ST 2094-40"},
                {"side_data_type": "Content light level metadata", "max_content": 4000, "max_average": 500},
            ],
        }
        out = analyze_hdr_from_frame_data({}, frame)
        self.assertEqual(out.hdr_type, "hdr10_plus")
        self.assertEqual(out.quality_score, 90)

    def test_hdr10_low_punch_flag(self):
        frame = {
            "color_primaries": "bt2020",
            "color_transfer": "smpte2084",
            "side_data_list": [
                {"side_data_type": "Content light level metadata", "max_content": 300, "max_average": 100},
            ],
        }
        out = analyze_hdr_from_frame_data({}, frame)
        self.assertEqual(out.hdr_type, "hdr10")
        self.assertEqual(out.validation_flag, "hdr_low_punch")
        self.assertEqual(out.quality_score, 65)

    def test_fallback_to_stream_when_no_frame(self):
        stream = {
            "color_primaries": "bt2020",
            "color_transfer": "arib-std-b67",
            "color_space": "bt2020nc",
        }
        out = analyze_hdr_from_frame_data(stream, None)
        self.assertEqual(out.hdr_type, "hlg")

    def test_dolby_vision_detected(self):
        frame = {
            "color_primaries": "bt2020",
            "color_transfer": "smpte2084",
            "side_data_list": [
                {"side_data_type": "DOVI configuration record"},
            ],
        }
        out = analyze_hdr_from_frame_data({}, frame)
        self.assertEqual(out.hdr_type, "dolby_vision")
        self.assertEqual(out.quality_score, 100)


# ---------------------------------------------------------------------------
# detect_hdr10_plus_multi_frame (mock subprocess)
# ---------------------------------------------------------------------------


class TestHdr10PlusMultiFrame(unittest.TestCase):
    def test_finds_smpte2094_40(self):
        payload = {
            "frames": [
                {"side_data_list": [{"side_data_type": "Some Metadata"}]},
                {"side_data_list": [{"side_data_type": "HDR Dynamic Metadata SMPTE ST 2094-40"}]},
            ]
        }
        with patch(
            "cinesort.domain.perceptual.hdr_analysis.tracked_run",
            return_value=_fake_completed(stdout=json.dumps(payload)),
        ):
            self.assertTrue(detect_hdr10_plus_multi_frame("/tmp/ffprobe", "/tmp/x.mkv"))

    def test_no_hdr10_plus(self):
        payload = {
            "frames": [
                {"side_data_list": [{"side_data_type": "Mastering display metadata"}]},
            ]
        }
        with patch(
            "cinesort.domain.perceptual.hdr_analysis.tracked_run",
            return_value=_fake_completed(stdout=json.dumps(payload)),
        ):
            self.assertFalse(detect_hdr10_plus_multi_frame("/tmp/ffprobe", "/tmp/x.mkv"))

    def test_returncode_error_returns_false(self):
        with patch(
            "cinesort.domain.perceptual.hdr_analysis.tracked_run",
            return_value=_fake_completed(returncode=1),
        ):
            self.assertFalse(detect_hdr10_plus_multi_frame("/tmp/ffprobe", "/tmp/x.mkv"))

    def test_timeout_returns_false(self):
        with patch(
            "cinesort.domain.perceptual.hdr_analysis.tracked_run",
            side_effect=subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=15),
        ):
            self.assertFalse(detect_hdr10_plus_multi_frame("/tmp/ffprobe", "/tmp/x.mkv"))

    def test_oserror_returns_false(self):
        with patch(
            "cinesort.domain.perceptual.hdr_analysis.tracked_run",
            side_effect=OSError("no ffprobe"),
        ):
            self.assertFalse(detect_hdr10_plus_multi_frame("/tmp/ffprobe", "/tmp/x.mkv"))

    def test_malformed_json_returns_false(self):
        with patch(
            "cinesort.domain.perceptual.hdr_analysis.tracked_run",
            return_value=_fake_completed(stdout="not json"),
        ):
            self.assertFalse(detect_hdr10_plus_multi_frame("/tmp/ffprobe", "/tmp/x.mkv"))

    def test_missing_path_returns_false(self):
        self.assertFalse(detect_hdr10_plus_multi_frame("", "/tmp/x.mkv"))
        self.assertFalse(detect_hdr10_plus_multi_frame("/tmp/ffprobe", ""))


# ---------------------------------------------------------------------------
# Spec hook
# ---------------------------------------------------------------------------


class TestSpecContainsHdrAnalysis(unittest.TestCase):
    def test_hiddenimport_module(self):
        spec = (Path(__file__).resolve().parents[1] / "CineSort.spec").read_text(encoding="utf-8")
        self.assertIn("cinesort.domain.perceptual.hdr_analysis", spec)


if __name__ == "__main__":
    unittest.main()
