"""Tests §4 v7.5.0 — scene detection hybride."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.domain.perceptual.scene_detection import (
    SceneKeyframe,
    _parse_showinfo_stderr,
    detect_scene_keyframes,
    merge_hybrid_timestamps,
    should_skip_scene_detection,
)


def _fake_completed(stderr: str, returncode: int = 0, stdout: str = "") -> MagicMock:
    cp = MagicMock()
    cp.stdout = stdout
    cp.stderr = stderr
    cp.returncode = returncode
    return cp


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParseShowinfoStderr(unittest.TestCase):
    def test_parses_pts_time_and_score(self):
        stderr = """
[Parsed_showinfo_0 @ 0x7f] n:   1 pts:10000 pts_time:5.000 scene_score:0.42
[Parsed_showinfo_0 @ 0x7f] n:   2 pts:24000 pts_time:12.500 scene_score:0.35
[Parsed_showinfo_0 @ 0x7f] n:   3 pts:60000 pts_time:30.000 scene_score:0.91
"""
        kfs = _parse_showinfo_stderr(stderr)
        self.assertEqual(len(kfs), 3)
        self.assertAlmostEqual(kfs[0].timestamp_s, 5.0)
        self.assertAlmostEqual(kfs[0].score, 0.42)
        self.assertAlmostEqual(kfs[2].score, 0.91)

    def test_fallback_score_when_absent(self):
        stderr = "[Parsed_showinfo_0 @ 0x] pts_time:7.250 something else"
        kfs = _parse_showinfo_stderr(stderr)
        self.assertEqual(len(kfs), 1)
        self.assertEqual(kfs[0].score, 1.0)

    def test_ignores_unrelated_lines(self):
        stderr = """
ffmpeg version 7.0
[libav @ 0x] random log
[Parsed_showinfo_0 @ 0x] pts_time:42.0 scene_score:0.5
"""
        kfs = _parse_showinfo_stderr(stderr)
        self.assertEqual(len(kfs), 1)
        self.assertAlmostEqual(kfs[0].timestamp_s, 42.0)

    def test_empty_returns_empty(self):
        self.assertEqual(_parse_showinfo_stderr(""), [])

    def test_malformed_score_fallbacks_to_1(self):
        stderr = "[Parsed_showinfo_0 @ 0x] pts_time:1.0 scene_score:NaN"
        kfs = _parse_showinfo_stderr(stderr)
        self.assertEqual(len(kfs), 1)
        self.assertEqual(kfs[0].score, 1.0)


# ---------------------------------------------------------------------------
# detect_scene_keyframes (mock subprocess)
# ---------------------------------------------------------------------------


class TestDetectSceneKeyframes(unittest.TestCase):
    def test_returns_sorted_by_timestamp(self):
        stderr = """
[Parsed_showinfo_0 @ 0x] pts_time:30.0 scene_score:0.5
[Parsed_showinfo_0 @ 0x] pts_time:10.0 scene_score:0.8
[Parsed_showinfo_0 @ 0x] pts_time:20.0 scene_score:0.6
"""
        with patch(
            "cinesort.domain.perceptual.scene_detection.tracked_run",
            return_value=_fake_completed(stderr),
        ):
            kfs = detect_scene_keyframes("/tmp/ffmpeg", "/tmp/movie.mkv")
        self.assertEqual([k.timestamp_s for k in kfs], [10.0, 20.0, 30.0])

    def test_caps_at_max_keyframes_by_score(self):
        lines = [f"[Parsed_showinfo_0 @ 0x] pts_time:{i * 10}.0 scene_score:{0.1 + i * 0.01}" for i in range(40)]
        stderr = "\n".join(lines)
        with patch(
            "cinesort.domain.perceptual.scene_detection.tracked_run",
            return_value=_fake_completed(stderr),
        ):
            kfs = detect_scene_keyframes("/tmp/ffmpeg", "/tmp/movie.mkv", max_keyframes=5)
        self.assertEqual(len(kfs), 5)
        # Les 5 avec le meilleur score (derniers indices = 35..39)
        ts_values = sorted(k.timestamp_s for k in kfs)
        self.assertEqual(ts_values, [350.0, 360.0, 370.0, 380.0, 390.0])

    def test_timeout_returns_empty(self):
        with patch(
            "cinesort.domain.perceptual.scene_detection.tracked_run",
            side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30),
        ):
            self.assertEqual(detect_scene_keyframes("/tmp/ffmpeg", "/tmp/movie.mkv"), [])

    def test_oserror_returns_empty(self):
        with patch(
            "cinesort.domain.perceptual.scene_detection.tracked_run",
            side_effect=OSError("not found"),
        ):
            self.assertEqual(detect_scene_keyframes("/tmp/ffmpeg", "/tmp/movie.mkv"), [])

    def test_returncode_error_returns_empty(self):
        with patch(
            "cinesort.domain.perceptual.scene_detection.tracked_run",
            return_value=_fake_completed("", returncode=2),
        ):
            self.assertEqual(detect_scene_keyframes("/tmp/ffmpeg", "/tmp/movie.mkv"), [])

    def test_empty_stderr_returns_empty(self):
        with patch(
            "cinesort.domain.perceptual.scene_detection.tracked_run",
            return_value=_fake_completed(""),
        ):
            self.assertEqual(detect_scene_keyframes("/tmp/ffmpeg", "/tmp/movie.mkv"), [])

    def test_missing_ffmpeg_path_returns_empty(self):
        self.assertEqual(detect_scene_keyframes("", "/tmp/movie.mkv"), [])
        self.assertEqual(detect_scene_keyframes("/tmp/ffmpeg", ""), [])


# ---------------------------------------------------------------------------
# merge_hybrid_timestamps
# ---------------------------------------------------------------------------


class TestMergeHybridTimestamps(unittest.TestCase):
    def test_no_keyframes_returns_uniform(self):
        uniform = [10.0, 30.0, 50.0]
        self.assertEqual(merge_hybrid_timestamps(uniform, [], target_count=3), uniform)

    def test_no_keyframes_clamps_target(self):
        uniform = [10.0, 30.0, 50.0, 70.0, 90.0]
        self.assertEqual(merge_hybrid_timestamps(uniform, [], target_count=3), uniform[:3])

    def test_50_50_split_respected(self):
        uniform = [10.0, 30.0, 50.0, 70.0, 90.0]
        keyframes = [
            SceneKeyframe(timestamp_s=15.0, score=0.9),
            SceneKeyframe(timestamp_s=45.0, score=0.8),
            SceneKeyframe(timestamp_s=75.0, score=0.7),
        ]
        out = merge_hybrid_timestamps(uniform, keyframes, target_count=6, dedup_tolerance_s=3.0)
        # 6 * 0.5 = 3 keyframes, 3 uniform
        self.assertLessEqual(len(out), 6)
        # Toutes les keyframes doivent etre presentes (scores eleves)
        for kf in (15.0, 45.0, 75.0):
            self.assertIn(kf, out)

    def test_dedup_by_tolerance(self):
        uniform = [10.0, 30.0, 50.0]
        keyframes = [SceneKeyframe(timestamp_s=12.0, score=0.9)]
        # Uniforme `10` a moins de 15s du keyframe `12` -> ignore
        out = merge_hybrid_timestamps(uniform, keyframes, target_count=3, dedup_tolerance_s=15.0)
        self.assertIn(12.0, out)
        self.assertNotIn(10.0, out)

    def test_target_count_respected(self):
        uniform = [5.0, 15.0, 25.0, 35.0, 45.0]
        keyframes = [SceneKeyframe(timestamp_s=100.0 + i, score=0.5) for i in range(10)]
        out = merge_hybrid_timestamps(uniform, keyframes, target_count=5)
        self.assertLessEqual(len(out), 5)

    def test_result_is_sorted(self):
        uniform = [10.0, 30.0, 50.0]
        keyframes = [
            SceneKeyframe(timestamp_s=60.0, score=0.9),
            SceneKeyframe(timestamp_s=5.0, score=0.8),
        ]
        out = merge_hybrid_timestamps(uniform, keyframes, target_count=5, dedup_tolerance_s=1.0)
        self.assertEqual(out, sorted(out))

    def test_empty_uniform_with_keyframes(self):
        keyframes = [SceneKeyframe(timestamp_s=20.0, score=0.9)]
        out = merge_hybrid_timestamps([], keyframes, target_count=3)
        self.assertEqual(out, [20.0])


# ---------------------------------------------------------------------------
# should_skip_scene_detection
# ---------------------------------------------------------------------------


class TestShouldSkipSceneDetection(unittest.TestCase):
    def test_setting_disabled_skips(self):
        self.assertTrue(should_skip_scene_detection(duration_s=1000.0, setting_enabled=False))

    def test_short_film_skips(self):
        self.assertTrue(should_skip_scene_detection(duration_s=60.0, setting_enabled=True))
        self.assertTrue(should_skip_scene_detection(duration_s=179.0, setting_enabled=True))

    def test_long_film_enabled_runs(self):
        self.assertFalse(should_skip_scene_detection(duration_s=180.0, setting_enabled=True))
        self.assertFalse(should_skip_scene_detection(duration_s=7200.0, setting_enabled=True))


# ---------------------------------------------------------------------------
# Settings roundtrip
# ---------------------------------------------------------------------------


class TestSettingDefaults(unittest.TestCase):
    def setUp(self):
        import cinesort.ui.api.cinesort_api as backend

        self._tmp = tempfile.mkdtemp(prefix="cinesort_scene_")
        self._root = Path(self._tmp) / "root"
        self._sd = Path(self._tmp) / "state"
        self._root.mkdir()
        self._sd.mkdir()
        self.api = backend.CineSortApi()
        self.api._state_dir = self._sd

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _save(self, extra):
        base = {"root": str(self._root), "state_dir": str(self._sd)}
        base.update(extra)
        return self.api.settings.save_settings(base)

    def test_default_enabled(self):
        s = self.api.settings.get_settings()
        self.assertTrue(s.get("perceptual_scene_detection_enabled"))

    def test_roundtrip_false(self):
        self._save({"perceptual_scene_detection_enabled": False})
        s = self.api.settings.get_settings()
        self.assertFalse(s.get("perceptual_scene_detection_enabled"))


# ---------------------------------------------------------------------------
# Integration dans extract_representative_frames
# ---------------------------------------------------------------------------


class TestIntegrationExtract(unittest.TestCase):
    def test_setting_false_bypasses_detection(self):
        from cinesort.domain.perceptual import frame_extraction as fe

        with (
            patch.object(fe, "detect_scene_keyframes") as mock_detect,
            patch.object(fe, "_try_extract_valid_frame", return_value=None),
        ):
            fe.extract_representative_frames(
                "/tmp/ffmpeg",
                "/tmp/movie.mkv",
                duration_s=7200.0,
                width=1920,
                height=1080,
                bit_depth=8,
                frames_count=5,
                scene_detection_enabled=False,
            )
            mock_detect.assert_not_called()

    def test_enabled_calls_detection_on_long_film(self):
        from cinesort.domain.perceptual import frame_extraction as fe

        with (
            patch.object(fe, "detect_scene_keyframes", return_value=[]) as mock_detect,
            patch.object(fe, "_try_extract_valid_frame", return_value=None),
        ):
            fe.extract_representative_frames(
                "/tmp/ffmpeg",
                "/tmp/movie.mkv",
                duration_s=7200.0,
                width=1920,
                height=1080,
                bit_depth=8,
                frames_count=5,
                scene_detection_enabled=True,
            )
            mock_detect.assert_called_once()

    def test_short_film_skips_detection(self):
        from cinesort.domain.perceptual import frame_extraction as fe

        with (
            patch.object(fe, "detect_scene_keyframes") as mock_detect,
            patch.object(fe, "_try_extract_valid_frame", return_value=None),
        ):
            fe.extract_representative_frames(
                "/tmp/ffmpeg",
                "/tmp/movie.mkv",
                duration_s=60.0,  # < 180 s
                width=1920,
                height=1080,
                bit_depth=8,
                frames_count=3,
                scene_detection_enabled=True,
            )
            mock_detect.assert_not_called()


class TestSpecContainsSceneDetection(unittest.TestCase):
    def test_hiddenimport(self):
        spec = (Path(__file__).resolve().parents[1] / "CineSort.spec").read_text(encoding="utf-8")
        self.assertIn("cinesort.domain.perceptual.scene_detection", spec)


if __name__ == "__main__":
    unittest.main()
