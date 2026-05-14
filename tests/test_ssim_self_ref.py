"""Tests §13 v7.5.0 — SSIM self-referential (detection fake 4K)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.domain.perceptual.ssim_self_ref import (
    _parse_ssim_stderr,
    build_ssim_self_ref_command,
    classify_ssim_verdict,
    compute_ssim_self_ref,
)


def _fake_completed(stderr: str = "", returncode: int = 0) -> MagicMock:
    cp = MagicMock()
    cp.stdout = ""
    cp.stderr = stderr
    cp.returncode = returncode
    return cp


class TestClassifyVerdict(unittest.TestCase):
    def test_097_fake(self):
        v, c = classify_ssim_verdict(0.97)
        self.assertEqual(v, "upscale_fake")
        self.assertAlmostEqual(c, 0.85)

    def test_095_fake(self):
        v, _ = classify_ssim_verdict(0.95)
        self.assertEqual(v, "upscale_fake")

    def test_092_ambiguous(self):
        v, c = classify_ssim_verdict(0.92)
        self.assertEqual(v, "ambiguous")
        self.assertAlmostEqual(c, 0.60)

    def test_090_ambiguous(self):
        v, _ = classify_ssim_verdict(0.90)
        self.assertEqual(v, "ambiguous")

    def test_084_native(self):
        v, c = classify_ssim_verdict(0.84)
        self.assertEqual(v, "native")
        self.assertAlmostEqual(c, 0.90)

    def test_zero_native(self):
        v, _ = classify_ssim_verdict(0.0)
        self.assertEqual(v, "native")


class TestBuildCommand(unittest.TestCase):
    def test_includes_split_and_scale(self):
        cmd = build_ssim_self_ref_command("ffmpeg", "x.mkv", 100.0, 120.0)
        joined = " ".join(cmd)
        self.assertIn("split=2", joined)
        self.assertIn("scale=1920:1080", joined)
        self.assertIn("scale=3840:2160", joined)
        self.assertIn("ssim", joined)
        self.assertIn("-ss", cmd)
        self.assertIn("100.0", cmd)
        self.assertIn("-t", cmd)


class TestParseSsimStderr(unittest.TestCase):
    def test_parses_all_and_y(self):
        stderr = "[Parsed_ssim_0 @ 0x7f] SSIM Y:0.862134 (8.6) U:0.94 V:0.93 All:0.884 (9.3)"
        r = _parse_ssim_stderr(stderr)
        self.assertAlmostEqual(r.ssim_y, 0.862134, places=4)
        self.assertAlmostEqual(r.ssim_all, 0.884, places=3)
        self.assertEqual(r.upscale_verdict, "native")

    def test_parses_high_ssim_fake(self):
        stderr = "[Parsed_ssim_0 @ 0x7f] SSIM Y:0.9723 All:0.975"
        r = _parse_ssim_stderr(stderr)
        self.assertEqual(r.upscale_verdict, "upscale_fake")

    def test_parses_ambiguous_range(self):
        stderr = "[Parsed_ssim_0 @ 0x7f] SSIM Y:0.921 All:0.925"
        r = _parse_ssim_stderr(stderr)
        self.assertEqual(r.upscale_verdict, "ambiguous")

    def test_empty_stderr_error(self):
        r = _parse_ssim_stderr("")
        self.assertEqual(r.upscale_verdict, "error")

    def test_no_ssim_line_error(self):
        r = _parse_ssim_stderr("ffmpeg version 7.0\nblah blah")
        self.assertEqual(r.upscale_verdict, "error")

    def test_only_y_no_all(self):
        stderr = "SSIM Y:0.88"
        r = _parse_ssim_stderr(stderr)
        self.assertAlmostEqual(r.ssim_y, 0.88, places=2)
        self.assertEqual(r.ssim_all, -1.0)
        self.assertEqual(r.upscale_verdict, "native")


class TestComputeSsimSelfRef(unittest.TestCase):
    def test_skip_if_not_4k(self):
        r = compute_ssim_self_ref("ffmpeg", "x.mkv", 7200.0, video_height=1080)
        self.assertEqual(r.upscale_verdict, "not_applicable_resolution")

    def test_skip_if_animation(self):
        r = compute_ssim_self_ref("ffmpeg", "x.mkv", 7200.0, video_height=2160, is_animation=True)
        self.assertEqual(r.upscale_verdict, "not_applicable_animation")

    def test_skip_if_duration_too_short(self):
        r = compute_ssim_self_ref("ffmpeg", "x.mkv", 60.0, video_height=2160)
        self.assertEqual(r.upscale_verdict, "not_applicable_duration")

    def test_missing_ffmpeg_returns_error(self):
        r = compute_ssim_self_ref("", "x.mkv", 7200.0, video_height=2160)
        self.assertEqual(r.upscale_verdict, "error")

    def test_ffmpeg_error_returns_error(self):
        with patch(
            "cinesort.domain.perceptual.ssim_self_ref.tracked_run",
            return_value=_fake_completed(returncode=1, stderr="error"),
        ):
            r = compute_ssim_self_ref("ffmpeg", "x.mkv", 7200.0, video_height=2160)
        self.assertEqual(r.upscale_verdict, "error")

    def test_timeout_returns_error(self):
        with patch(
            "cinesort.domain.perceptual.ssim_self_ref.tracked_run",
            side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=45),
        ):
            r = compute_ssim_self_ref("ffmpeg", "x.mkv", 7200.0, video_height=2160)
        self.assertEqual(r.upscale_verdict, "error")

    def test_oserror_returns_error(self):
        with patch(
            "cinesort.domain.perceptual.ssim_self_ref.tracked_run",
            side_effect=OSError("no ffmpeg"),
        ):
            r = compute_ssim_self_ref("ffmpeg", "x.mkv", 7200.0, video_height=2160)
        self.assertEqual(r.upscale_verdict, "error")

    def test_native_4k_end_to_end(self):
        stderr = "[Parsed_ssim_0 @ 0x] SSIM Y:0.87 All:0.88"
        with patch(
            "cinesort.domain.perceptual.ssim_self_ref.tracked_run",
            return_value=_fake_completed(stderr=stderr),
        ):
            r = compute_ssim_self_ref("ffmpeg", "x.mkv", 7200.0, video_height=2160)
        self.assertEqual(r.upscale_verdict, "native")

    def test_fake_4k_end_to_end(self):
        stderr = "[Parsed_ssim_0 @ 0x] SSIM Y:0.973 All:0.975"
        with patch(
            "cinesort.domain.perceptual.ssim_self_ref.tracked_run",
            return_value=_fake_completed(stderr=stderr),
        ):
            r = compute_ssim_self_ref("ffmpeg", "x.mkv", 7200.0, video_height=2160)
        self.assertEqual(r.upscale_verdict, "upscale_fake")


class TestSettings(unittest.TestCase):
    def setUp(self):
        import cinesort.ui.api.cinesort_api as backend

        self._tmp = tempfile.mkdtemp(prefix="cinesort_ssim_")
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
        self.assertTrue(s.get("perceptual_ssim_self_ref_enabled"))

    def test_roundtrip_false(self):
        self._save({"perceptual_ssim_self_ref_enabled": False})
        s = self.api.settings.get_settings()
        self.assertFalse(s.get("perceptual_ssim_self_ref_enabled"))


class TestStoreRoundtrip(unittest.TestCase):
    def test_upsert_and_get_preserves_ssim_fields(self):
        from cinesort.infra.db.sqlite_store import SQLiteStore

        tmp = tempfile.mkdtemp(prefix="cinesort_ssimdb_")
        try:
            db_path = Path(tmp) / "db" / "test.sqlite"
            store = SQLiteStore(db_path)
            store.initialize()
            store.upsert_perceptual_report(
                run_id="run1",
                row_id="row1",
                visual_score=80,
                audio_score=75,
                global_score=78,
                global_tier="excellent",
                metrics={"foo": "bar"},
                settings_used={},
                ssim_self_ref=0.973,
                upscale_verdict="upscale_fake",
            )
            got = store.get_perceptual_report(run_id="run1", row_id="row1")
            self.assertIsNotNone(got)
            self.assertAlmostEqual(got.get("ssim_self_ref"), 0.973, places=3)
            self.assertEqual(got.get("upscale_verdict"), "upscale_fake")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestModelSerialization(unittest.TestCase):
    def test_video_perceptual_to_dict_contains_upscale_block(self):
        from cinesort.domain.perceptual.models import VideoPerceptual

        vp = VideoPerceptual()
        vp.ssim_self_ref = 0.973
        vp.upscale_verdict = "upscale_fake"
        vp.upscale_confidence = 0.85
        d = vp.to_dict()
        self.assertIn("upscale_self_ref", d)
        self.assertAlmostEqual(d["upscale_self_ref"]["ssim_y"], 0.973, places=3)
        self.assertEqual(d["upscale_self_ref"]["verdict"], "upscale_fake")


class TestSpecContainsSsim(unittest.TestCase):
    def test_hiddenimport_module(self):
        spec = (Path(__file__).resolve().parents[1] / "CineSort.spec").read_text(encoding="utf-8")
        self.assertIn("cinesort.domain.perceptual.ssim_self_ref", spec)


if __name__ == "__main__":
    unittest.main()
