from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import skipUnless

import cinesort.domain.core as core


@skipUnless(__import__("os").environ.get("CINESORT_STRESS") == "1", "CINESORT_STRESS=1 requis pour la suite stress.")
class LargeVolumeFlowStressTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_stress_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "library"
        self.root.mkdir(parents=True, exist_ok=True)
        self._original_min_video_bytes = core.MIN_VIDEO_BYTES
        core.MIN_VIDEO_BYTES = 1
        self.addCleanup(self._restore_min_video_bytes)

    def _restore_min_video_bytes(self) -> None:
        core.MIN_VIDEO_BYTES = self._original_min_video_bytes

    def _make_movie_dirs(self, count: int) -> None:
        for idx in range(count):
            folder = self.root / f"Movie {idx:04d} (2001)"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"Movie {idx:04d} (2001).mkv").write_bytes(b"\x00")

    def test_plan_library_handles_1000_synthetic_folders(self) -> None:
        self._make_movie_dirs(1000)
        cfg = core.Config(root=self.root).normalized()

        rows, stats = core.plan_library(
            cfg,
            tmdb=None,
            log=lambda *_args: None,
            progress=lambda *_args: None,
        )

        self.assertEqual(len(rows), 1000)
        self.assertEqual(stats.planned_rows, 1000)
        decisions = {row.row_id: {"ok": True, "title": "Shared Title", "year": 2001} for row in rows[:50]}
        data = core.find_duplicate_targets(cfg, rows[:50], decisions)
        self.assertGreaterEqual(int(data.get("total_groups") or 0), 1)

    def test_plan_library_handles_5000_synthetic_folders_and_dry_run_apply_subset(self) -> None:
        self._make_movie_dirs(5000)
        cfg = core.Config(root=self.root).normalized()

        rows, stats = core.plan_library(
            cfg,
            tmdb=None,
            log=lambda *_args: None,
            progress=lambda *_args: None,
        )

        self.assertEqual(len(rows), 5000)
        self.assertEqual(stats.planned_rows, 5000)

        subset = rows[:100]
        decisions = {
            row.row_id: {"ok": True, "title": f"Renamed {idx:04d}", "year": 2001} for idx, row in enumerate(subset)
        }
        dup_data = core.find_duplicate_targets(cfg, subset, decisions)
        self.assertEqual(int(dup_data.get("total_groups") or 0), 0)

        result = core.apply_rows(
            cfg,
            subset,
            decisions,
            dry_run=True,
            quarantine_unapproved=False,
            log=lambda *_args: None,
        )
        self.assertEqual(int(result.total_rows or 0), len(subset))
        self.assertEqual(int(result.considered_rows or 0), len(subset))
        self.assertEqual(int(result.errors or 0), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
