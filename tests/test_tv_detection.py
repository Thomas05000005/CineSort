from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path
import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.domain.tv_helpers import parse_tv_info


class TvParsingTests(unittest.TestCase):
    """Test parse_tv_info() extraction of series metadata from filenames."""

    def test_parse_s01e01_pattern(self) -> None:
        folder = Path("/lib/Breaking Bad")
        video = Path("/lib/Breaking Bad/Breaking.Bad.S01E01.Pilot.720p.mkv")
        result = parse_tv_info(folder, video)
        self.assertIsNotNone(result)
        self.assertEqual(result.season, 1)
        self.assertEqual(result.episode, 1)
        self.assertIn("Breaking", result.series_name)

    def test_parse_2x05_pattern(self) -> None:
        folder = Path("/lib/Friends")
        video = Path("/lib/Friends/Friends.2x05.mkv")
        result = parse_tv_info(folder, video)
        self.assertIsNotNone(result)
        self.assertEqual(result.season, 2)
        self.assertEqual(result.episode, 5)

    def test_parse_episode_pattern(self) -> None:
        folder = Path("/lib/Lost")
        video = Path("/lib/Lost/Lost.Episode.10.720p.mkv")
        result = parse_tv_info(folder, video)
        self.assertIsNotNone(result)
        self.assertIsNone(result.season)
        self.assertEqual(result.episode, 10)

    def test_season_folder_extracts_series_from_parent(self) -> None:
        folder = Path("/lib/The Wire/Season 3")
        video = Path("/lib/The Wire/Season 3/S03E01.mkv")
        result = parse_tv_info(folder, video)
        self.assertIsNotNone(result)
        self.assertEqual(result.season, 3)
        self.assertEqual(result.episode, 1)
        self.assertIn("Wire", result.series_name)

    def test_non_tv_returns_none(self) -> None:
        folder = Path("/lib/Inception (2010)")
        video = Path("/lib/Inception (2010)/Inception.2010.1080p.mkv")
        result = parse_tv_info(folder, video)
        self.assertIsNone(result)

    def test_year_extracted_from_folder(self) -> None:
        folder = Path("/lib/Breaking Bad (2008)")
        video = Path("/lib/Breaking Bad (2008)/S01E01.mkv")
        result = parse_tv_info(folder, video)
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2008)


class TvPlanFlowTests(unittest.TestCase):
    """Integration test: TV detection in plan_library with enable_tv_detection."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_tv_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # Issue #86 : mock.patch.object pour auto-restore safe meme si exception
        _p_min_video = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p_min_video.start()
        self.addCleanup(_p_min_video.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _create_file(self, path: Path, size: int = 2048) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)

    def _wait_done(self, api: CineSortApi, run_id: str, timeout_s: float = 10.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            s = api.run.get_status(run_id, 0)
            if s.get("done"):
                return
            time.sleep(0.05)
        self.fail("Timeout")

    def test_tv_episodes_detected_with_enable_tv_detection(self) -> None:
        series_dir = self.root / "Breaking Bad"
        self._create_file(series_dir / "Breaking.Bad.S01E01.720p.mkv")
        self._create_file(series_dir / "Breaking.Bad.S01E02.720p.mkv")
        self._create_file(series_dir / "Breaking.Bad.S01E03.720p.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
                "enable_tv_detection": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = start["run_id"]
        self._wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        tv_rows = [r for r in rows if r.get("kind") == "tv_episode"]
        self.assertGreaterEqual(len(tv_rows), 2, f"Expected TV rows, got {len(tv_rows)}")
        for r in tv_rows:
            self.assertTrue(r.get("tv_series_name"), r)
            self.assertIsNotNone(r.get("tv_season"), r)
            self.assertIsNotNone(r.get("tv_episode"), r)

    def test_tv_skipped_without_enable_tv_detection(self) -> None:
        series_dir = self.root / "Skipped Series"
        self._create_file(series_dir / "Skipped.S01E01.mkv")
        self._create_file(series_dir / "Skipped.S01E02.mkv")
        self._create_file(series_dir / "Skipped.S01E03.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
                "enable_tv_detection": False,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = start["run_id"]
        self._wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        tv_rows = [r for r in rows if r.get("kind") == "tv_episode"]
        self.assertEqual(len(tv_rows), 0, "TV should be skipped without enable_tv_detection")

    def test_tv_apply_creates_series_structure(self) -> None:
        series_dir = self.root / "TestSeries"
        self._create_file(series_dir / "TestSeries.S01E01.mkv")
        self._create_file(series_dir / "TestSeries.S01E02.mkv")
        self._create_file(series_dir / "TestSeries.S01E03.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
                "enable_tv_detection": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = start["run_id"]
        self._wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        tv_rows = [r for r in rows if r.get("kind") == "tv_episode"]
        if not tv_rows:
            self.skipTest("No TV rows detected")

        decisions = {
            r["row_id"]: {"ok": True, "title": r.get("proposed_title"), "year": r.get("proposed_year")} for r in tv_rows
        }
        applied = api.apply(run_id, decisions, False, False)
        self.assertTrue(applied.get("ok"), applied)

        # Check that a Saison folder was created.
        saison_found = any("saison" in str(p).lower() for p in self.root.rglob("*") if p.is_dir())
        self.assertTrue(saison_found, f"Expected Saison folder structure under {self.root}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
