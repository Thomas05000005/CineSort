"""Tests §8 v7.5.0 — Interlacing + Crop + Judder + IMAX."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.domain.perceptual.metadata_analysis import (
    CropSegment,
    _classify_judder,
    _parse_idet_stderr,
    _parse_last_crop,
    _parse_mpdecimate_stderr,
    classify_crop,
    classify_imax,
    detect_crop_multi_segments,
    detect_crop_single_segment,
    detect_interlacing,
    detect_judder,
)


def _fake_completed(stderr: str = "", returncode: int = 0) -> MagicMock:
    cp = MagicMock()
    cp.stdout = ""
    cp.stderr = stderr
    cp.returncode = returncode
    return cp


# ---------------------------------------------------------------------------
# 8.1 Interlacing
# ---------------------------------------------------------------------------


class TestParseIdetStderr(unittest.TestCase):
    def test_progressive_dominant(self):
        stderr = "[Parsed_idet_0 @ 0x] Multi frame detection: TFF: 2 BFF: 0 Progressive: 720 Undetermined: 0"
        info = _parse_idet_stderr(stderr)
        self.assertFalse(info.detected)
        self.assertEqual(info.interlace_type, "progressive")
        self.assertEqual(info.progressive_count, 720)

    def test_tff_dominant_interlaced(self):
        stderr = "[Parsed_idet_0 @ 0x] Multi frame detection: TFF: 500 BFF: 0 Progressive: 50 Undetermined: 0"
        info = _parse_idet_stderr(stderr)
        self.assertTrue(info.detected)
        self.assertEqual(info.interlace_type, "tff")

    def test_bff_dominant(self):
        stderr = "Multi frame detection: TFF: 0 BFF: 400 Progressive: 30 Undetermined: 0"
        info = _parse_idet_stderr(stderr)
        self.assertTrue(info.detected)
        self.assertEqual(info.interlace_type, "bff")

    def test_mixed_tff_bff(self):
        stderr = "Multi frame detection: TFF: 300 BFF: 200 Progressive: 10 Undetermined: 0"
        info = _parse_idet_stderr(stderr)
        self.assertTrue(info.detected)
        self.assertEqual(info.interlace_type, "mixed")

    def test_no_match_unknown(self):
        info = _parse_idet_stderr("ffmpeg version 7.0\n")
        self.assertFalse(info.detected)
        self.assertEqual(info.interlace_type, "unknown")

    def test_empty_stderr(self):
        info = _parse_idet_stderr("")
        self.assertEqual(info.interlace_type, "unknown")


class TestDetectInterlacing(unittest.TestCase):
    def test_end_to_end_progressive(self):
        stderr = "Multi frame detection: TFF: 0 BFF: 0 Progressive: 720 Undetermined: 0"
        with patch(
            "cinesort.domain.perceptual.metadata_analysis.tracked_run",
            return_value=_fake_completed(stderr=stderr),
        ):
            info = detect_interlacing("ffmpeg", "x.mkv", 7200.0)
        self.assertFalse(info.detected)

    def test_timeout_returns_unknown(self):
        with patch(
            "cinesort.domain.perceptual.metadata_analysis.tracked_run",
            side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30),
        ):
            info = detect_interlacing("ffmpeg", "x.mkv", 7200.0)
        self.assertEqual(info.interlace_type, "unknown")

    def test_missing_ffmpeg(self):
        info = detect_interlacing("", "x.mkv", 7200.0)
        self.assertEqual(info.interlace_type, "unknown")


# ---------------------------------------------------------------------------
# 8.2 Crop
# ---------------------------------------------------------------------------


class TestParseLastCrop(unittest.TestCase):
    def test_single_match(self):
        stderr = "[Parsed_cropdetect_0 @ 0x] crop=1920:800:0:140"
        out = _parse_last_crop(stderr)
        self.assertEqual(out, (1920, 800, 0, 140))

    def test_multiple_keeps_last(self):
        stderr = "crop=1920:1080:0:0\ncrop=1920:800:0:140\ncrop=1920:816:0:132"
        out = _parse_last_crop(stderr)
        self.assertEqual(out, (1920, 816, 0, 132))

    def test_no_match(self):
        self.assertIsNone(_parse_last_crop("ffmpeg version 7.0"))

    def test_empty(self):
        self.assertIsNone(_parse_last_crop(""))


class TestClassifyCrop(unittest.TestCase):
    def _seg(self, w: int, h: int, x: int = 0, y: int = 0) -> CropSegment:
        ar = w / h if h > 0 else 0.0
        return CropSegment(0.0, w, h, x, y, ar)

    def test_full_frame(self):
        info = classify_crop([self._seg(1920, 1080)], 1920, 1080)
        self.assertFalse(info.has_bars)
        self.assertEqual(info.verdict, "full_frame")

    def test_letterbox_2_39(self):
        # 1920x804 = 2.388 : nettement dans la zone 2.39
        info = classify_crop([self._seg(1920, 804, 0, 138)], 1920, 1080)
        self.assertTrue(info.has_bars)
        self.assertEqual(info.verdict, "letterbox_2_39")

    def test_letterbox_2_35(self):
        info = classify_crop([self._seg(1920, 816, 0, 132)], 1920, 1080)
        self.assertTrue(info.has_bars)
        self.assertEqual(info.verdict, "letterbox_2_35")

    def test_letterbox_other(self):
        # aspect ratio 1.85 -> "letterbox_other"
        info = classify_crop([self._seg(1920, 1038, 0, 21)], 1920, 1080)
        self.assertTrue(info.has_bars)
        self.assertEqual(info.verdict, "letterbox_other")

    def test_pillarbox(self):
        info = classify_crop([self._seg(1440, 1080, 240, 0)], 1920, 1080)
        self.assertTrue(info.has_bars)
        self.assertEqual(info.verdict, "pillarbox")

    def test_windowbox(self):
        info = classify_crop([self._seg(1440, 800, 240, 140)], 1920, 1080)
        self.assertEqual(info.verdict, "windowbox")

    def test_empty_segments_unknown(self):
        info = classify_crop([], 1920, 1080)
        self.assertEqual(info.verdict, "unknown")


class TestDetectCropSingleSegment(unittest.TestCase):
    def test_end_to_end(self):
        stderr = "crop=1920:800:0:140\ncrop=1920:800:0:140"
        with patch(
            "cinesort.domain.perceptual.metadata_analysis.tracked_run",
            return_value=_fake_completed(stderr=stderr),
        ):
            seg = detect_crop_single_segment("ffmpeg", "x.mkv", 120.0)
        self.assertIsNotNone(seg)
        self.assertEqual(seg.crop_w, 1920)
        self.assertEqual(seg.crop_h, 800)
        self.assertAlmostEqual(seg.aspect_ratio, 1920 / 800)

    def test_no_crop_line(self):
        with patch(
            "cinesort.domain.perceptual.metadata_analysis.tracked_run",
            return_value=_fake_completed(stderr="ffmpeg version"),
        ):
            self.assertIsNone(detect_crop_single_segment("ffmpeg", "x.mkv", 0))

    def test_timeout(self):
        with patch(
            "cinesort.domain.perceptual.metadata_analysis.tracked_run",
            side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30),
        ):
            self.assertIsNone(detect_crop_single_segment("ffmpeg", "x.mkv", 0))


class TestDetectCropMultiSegments(unittest.TestCase):
    def test_3_segments(self):
        call_count = [0]

        def _fake_run(cmd, *args, **kwargs):
            call_count[0] += 1
            # Segments alternent pour simuler IMAX Expansion
            if call_count[0] == 1:
                return _fake_completed(stderr="crop=1920:800:0:140")
            if call_count[0] == 2:
                return _fake_completed(stderr="crop=1920:1080:0:0")
            return _fake_completed(stderr="crop=1920:800:0:140")

        with patch(
            "cinesort.domain.perceptual.metadata_analysis.tracked_run",
            side_effect=_fake_run,
        ):
            segs = detect_crop_multi_segments("ffmpeg", "x.mkv", 7200.0, n_segments=3)
        self.assertEqual(len(segs), 3)
        ars = [s.aspect_ratio for s in segs]
        self.assertGreater(max(ars) - min(ars), 0.3)


# ---------------------------------------------------------------------------
# 8.3 Judder
# ---------------------------------------------------------------------------


class TestParseMpdecimate(unittest.TestCase):
    def test_drops_and_keeps(self):
        stderr = """
[mpdecimate @ 0x] keep pts:0
[mpdecimate @ 0x] drop pts:90090
[mpdecimate @ 0x] keep pts:93093
[mpdecimate @ 0x] drop pts:96096
"""
        drop, keep = _parse_mpdecimate_stderr(stderr)
        self.assertEqual(drop, 2)
        self.assertEqual(keep, 2)

    def test_no_matches(self):
        drop, keep = _parse_mpdecimate_stderr("ffmpeg version 7.0")
        self.assertEqual((drop, keep), (0, 0))

    def test_empty(self):
        self.assertEqual(_parse_mpdecimate_stderr(""), (0, 0))


class TestClassifyJudder(unittest.TestCase):
    def test_none(self):
        self.assertEqual(_classify_judder(0.02), "judder_none")

    def test_light(self):
        self.assertEqual(_classify_judder(0.10), "judder_light")

    def test_pulldown(self):
        self.assertEqual(_classify_judder(0.20), "pulldown_3_2_suspect")

    def test_heavy(self):
        self.assertEqual(_classify_judder(0.30), "judder_heavy")


class TestDetectJudder(unittest.TestCase):
    def test_end_to_end(self):
        stderr = "\n".join(["keep pts:0"] * 95 + ["drop pts:0"] * 5)
        with patch(
            "cinesort.domain.perceptual.metadata_analysis.tracked_run",
            return_value=_fake_completed(stderr=stderr),
        ):
            info = detect_judder("ffmpeg", "x.mkv", 7200.0)
        self.assertEqual(info.drop_count, 5)
        self.assertEqual(info.keep_count, 95)
        self.assertAlmostEqual(info.drop_ratio, 0.05)

    def test_timeout_returns_none(self):
        with patch(
            "cinesort.domain.perceptual.metadata_analysis.tracked_run",
            side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30),
        ):
            info = detect_judder("ffmpeg", "x.mkv", 7200.0)
        self.assertEqual(info.verdict, "judder_none")


# ---------------------------------------------------------------------------
# 8.4 IMAX
# ---------------------------------------------------------------------------


class TestClassifyImax(unittest.TestCase):
    def _seg(self, ar: float) -> CropSegment:
        return CropSegment(0.0, 1920, int(1920 / ar) if ar > 0 else 1080, 0, 0, ar)

    def test_expansion_variable_ar(self):
        segs = [self._seg(2.39), self._seg(1.78), self._seg(2.39)]
        info = classify_imax(1920, 1080, segs, [])
        self.assertTrue(info.is_imax)
        self.assertEqual(info.imax_type, "expansion")
        self.assertAlmostEqual(info.confidence, 0.90)

    def test_ar_143_full_frame(self):
        info = classify_imax(2880, 2016, [], [])  # AR 1.428
        self.assertTrue(info.is_imax)
        self.assertEqual(info.imax_type, "full_frame_143")

    def test_ar_190_digital(self):
        info = classify_imax(1920, 1012, [], [])  # AR 1.897
        self.assertTrue(info.is_imax)
        self.assertEqual(info.imax_type, "digital_190")

    def test_native_high_resolution(self):
        info = classify_imax(3840, 2800, [], [])  # 2800 > 2600
        self.assertTrue(info.is_imax)
        self.assertEqual(info.imax_type, "native_high_resolution")

    def test_tmdb_keyword_fallback(self):
        info = classify_imax(1920, 1080, [], ["IMAX", "Action"])
        self.assertTrue(info.is_imax)
        self.assertEqual(info.imax_type, "tmdb_keyword")

    def test_no_imax_standard(self):
        info = classify_imax(1920, 1080, [], [])
        self.assertFalse(info.is_imax)
        self.assertEqual(info.imax_type, "none")

    def test_expansion_priority_over_container(self):
        # Meme avec AR container 1.78, si expansion -> expansion
        segs = [self._seg(2.39), self._seg(1.78)]
        info = classify_imax(1920, 1080, segs, [])
        self.assertEqual(info.imax_type, "expansion")


# ---------------------------------------------------------------------------
# Settings roundtrip
# ---------------------------------------------------------------------------


class TestSettings(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile

        import cinesort.ui.api.cinesort_api as backend

        self._tmp = tempfile.mkdtemp(prefix="cinesort_meta_")
        self._root = Path(self._tmp) / "root"
        self._sd = Path(self._tmp) / "state"
        self._root.mkdir()
        self._sd.mkdir()
        self.api = backend.CineSortApi()
        self.api._state_dir = self._sd
        self._shutil = shutil

    def tearDown(self):
        self._shutil.rmtree(self._tmp, ignore_errors=True)

    def _save(self, extra):
        base = {"root": str(self._root), "state_dir": str(self._sd)}
        base.update(extra)
        return self.api.settings.save_settings(base)

    def test_defaults(self):
        s = self.api.settings.get_settings()
        self.assertTrue(s.get("perceptual_interlacing_detection_enabled"))
        self.assertTrue(s.get("perceptual_crop_detection_enabled"))
        self.assertFalse(s.get("perceptual_judder_detection_enabled"))  # opt-in

    def test_roundtrip(self):
        self._save(
            {
                "perceptual_interlacing_detection_enabled": False,
                "perceptual_crop_detection_enabled": False,
                "perceptual_judder_detection_enabled": True,
            }
        )
        s = self.api.settings.get_settings()
        self.assertFalse(s.get("perceptual_interlacing_detection_enabled"))
        self.assertFalse(s.get("perceptual_crop_detection_enabled"))
        self.assertTrue(s.get("perceptual_judder_detection_enabled"))


# ---------------------------------------------------------------------------
# Model serialization
# ---------------------------------------------------------------------------


class TestModelSerialization(unittest.TestCase):
    def test_video_perceptual_blocks(self):
        from cinesort.domain.perceptual.models import VideoPerceptual

        vp = VideoPerceptual()
        vp.interlaced_detected = True
        vp.interlace_type = "tff"
        vp.crop_has_bars = True
        vp.crop_verdict = "letterbox_2_39"
        vp.detected_aspect_ratio = 2.40
        vp.judder_verdict = "pulldown_3_2_suspect"
        vp.is_imax = True
        vp.imax_type = "expansion"
        vp.imax_confidence = 0.90
        d = vp.to_dict()
        self.assertEqual(d["interlacing"]["type"], "tff")
        self.assertEqual(d["crop"]["verdict"], "letterbox_2_39")
        self.assertEqual(d["judder"]["verdict"], "pulldown_3_2_suspect")
        self.assertTrue(d["imax"]["is_imax"])
        self.assertEqual(d["imax"]["type"], "expansion")


class TestSpecContainsMetadataAnalysis(unittest.TestCase):
    def test_hiddenimport(self):
        spec = (Path(__file__).resolve().parents[1] / "CineSort.spec").read_text(encoding="utf-8")
        self.assertIn("cinesort.domain.perceptual.metadata_analysis", spec)


if __name__ == "__main__":
    unittest.main()
