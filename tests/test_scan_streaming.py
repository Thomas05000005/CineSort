from __future__ import annotations

import itertools
import tempfile
import unittest
from pathlib import Path

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
import cinesort.domain.scan_helpers as core_scan_helpers


class ScanStreamingTests(unittest.TestCase):
    def test_stream_scan_targets_is_lazy_and_plan_results_stay_stable_on_large_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream_large_tree_") as tmp:
            root = Path(tmp)
            for idx in range(60):
                folder = root / f"Movie {idx:03d}"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"Movie.{idx:03d}.2010.1080p.mkv").write_bytes(b"x" * 4096)

            cfg = core.Config(root=root, enable_tmdb=False).normalized()
            old_min_video_bytes = core.MIN_VIDEO_BYTES
            core.MIN_VIDEO_BYTES = 1
            try:
                stream = core_scan_helpers.stream_scan_targets(cfg, min_video_bytes=core.MIN_VIDEO_BYTES)
                self.assertFalse(isinstance(stream, list))
                first_batch = list(itertools.islice(stream, 5))
                self.assertEqual(len(first_batch), 5)
                remaining = list(stream)
                all_targets = first_batch + remaining
                self.assertEqual(len(all_targets), 60)

                progress_calls = []
                rows, stats = plan_support.plan_library(
                    cfg,
                    tmdb=None,
                    log=lambda *_args: None,
                    progress=lambda idx, total, current: progress_calls.append((idx, total, current)),
                )
            finally:
                core.MIN_VIDEO_BYTES = old_min_video_bytes

            self.assertEqual(len(rows), 60)
            self.assertEqual(int(stats.folders_scanned or 0), 60)
            self.assertEqual(len(progress_calls), 60)
            self.assertTrue(all(total >= idx for idx, total, _current in progress_calls), progress_calls[:5])
            self.assertEqual(progress_calls[-1][0], progress_calls[-1][1])


class DiscoverRootLevelTests(unittest.TestCase):
    def test_discover_root_level_video(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discover_root_") as tmp:
            root = Path(tmp)
            (root / "Inception.2010.1080p.mkv").write_bytes(b"x" * 4096)
            (root / "Matrix (1999)").mkdir()
            (root / "Matrix (1999)" / "Matrix.1999.mkv").write_bytes(b"x" * 4096)

            cfg = core.Config(root=root, enable_tmdb=False).normalized()
            candidates = core_scan_helpers.discover_candidate_folders(cfg)

            resolved = {Path(c).resolve() for c in candidates}
            self.assertIn(root.resolve(), resolved)
            self.assertIn((root / "Matrix (1999)").resolve(), resolved)

    def test_discover_root_level_bonus_only_ignored(self) -> None:
        with tempfile.TemporaryDirectory(prefix="discover_root_bonus_") as tmp:
            root = Path(tmp)
            (root / "sample.mkv").write_bytes(b"x" * 4096)
            (root / "trailer.mp4").write_bytes(b"x" * 4096)
            (root / "Matrix (1999)").mkdir()
            (root / "Matrix (1999)" / "Matrix.1999.mkv").write_bytes(b"x" * 4096)

            cfg = core.Config(root=root, enable_tmdb=False).normalized()
            candidates = core_scan_helpers.discover_candidate_folders(cfg)

            resolved = {Path(c).resolve() for c in candidates}
            self.assertNotIn(root.resolve(), resolved)
            self.assertIn((root / "Matrix (1999)").resolve(), resolved)


class RootLevelPlanTests(unittest.TestCase):
    def test_plan_library_handles_root_level_film(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plan_root_") as tmp:
            root = Path(tmp)
            (root / "Inception.2010.1080p.mkv").write_bytes(b"x" * 4096)
            (root / "Matrix (1999)").mkdir()
            (root / "Matrix (1999)" / "Matrix.1999.mkv").write_bytes(b"x" * 4096)

            cfg = core.Config(root=root, enable_tmdb=False).normalized()
            old_min = core.MIN_VIDEO_BYTES
            core.MIN_VIDEO_BYTES = 1
            try:
                rows, stats = plan_support.plan_library(
                    cfg,
                    tmdb=None,
                    log=lambda *_a: None,
                    progress=lambda *_a: None,
                )
            finally:
                core.MIN_VIDEO_BYTES = old_min

            self.assertEqual(stats.root_level_films_seen, 1)
            root_rows = [r for r in rows if Path(r.folder).resolve() == root.resolve()]
            self.assertEqual(len(root_rows), 1)
            self.assertEqual(root_rows[0].kind, "collection")
            self.assertEqual(root_rows[0].video, "Inception.2010.1080p.mkv")
            self.assertIn("inception", root_rows[0].proposed_title.lower())
            self.assertEqual(root_rows[0].proposed_year, 2010)
            self.assertIn("root_level_source", root_rows[0].warning_flags)

            # Le resume doit mentionner la section "FILMS DETECTES A LA RACINE"
            from cinesort.ui.api.run_flow_support import _build_analysis_summary

            class _FakePaths:
                plan_jsonl = "/tmp/plan.jsonl"

            summary = _build_analysis_summary(rows, stats, root, root, _FakePaths())
            self.assertIn("FILMS DETECTES A LA RACINE", summary)
            self.assertIn("1 film(s) pose(s) directement a la racine", summary)
            self.assertNotIn("ATTENTION : racine en vrac", summary)

    def test_plan_library_bulk_warning_triggers_above_threshold(self) -> None:
        import cinesort.app.plan_support as plan_support

        with tempfile.TemporaryDirectory(prefix="plan_bulk_") as tmp:
            root = Path(tmp)
            bulk_count = plan_support._ROOT_BULK_WARNING_THRESHOLD
            for idx in range(bulk_count):
                (root / f"Film.{idx:03d}.2010.mkv").write_bytes(b"x" * 4096)

            cfg = core.Config(root=root, enable_tmdb=False).normalized()
            messages: list[tuple[str, str]] = []
            old_min = core.MIN_VIDEO_BYTES
            core.MIN_VIDEO_BYTES = 1
            try:
                _rows, stats = plan_support.plan_library(
                    cfg,
                    tmdb=None,
                    log=lambda level, msg: messages.append((level, msg)),
                    progress=lambda *_a: None,
                )
            finally:
                core.MIN_VIDEO_BYTES = old_min

            self.assertEqual(stats.root_level_films_seen, bulk_count)
            warnings = [m for lvl, m in messages if lvl == "WARN" and "Racine en vrac" in m]
            self.assertEqual(len(warnings), 1, warnings)

            # Resume analyse doit contenir l'avertissement vrac proeminent.
            from cinesort.ui.api.run_flow_support import _build_analysis_summary

            class _FakePaths:
                plan_jsonl = "/tmp/plan.jsonl"

            summary = _build_analysis_summary([], stats, root, root, _FakePaths())
            self.assertIn("ATTENTION : racine en vrac", summary)

    def test_plan_library_bulk_warning_silent_below_threshold(self) -> None:
        with tempfile.TemporaryDirectory(prefix="plan_nobulk_") as tmp:
            root = Path(tmp)
            for idx in range(3):
                (root / f"Film.{idx:03d}.2010.mkv").write_bytes(b"x" * 4096)

            cfg = core.Config(root=root, enable_tmdb=False).normalized()
            messages: list[tuple[str, str]] = []
            old_min = core.MIN_VIDEO_BYTES
            core.MIN_VIDEO_BYTES = 1
            try:
                plan_support.plan_library(
                    cfg,
                    tmdb=None,
                    log=lambda level, msg: messages.append((level, msg)),
                    progress=lambda *_a: None,
                )
            finally:
                core.MIN_VIDEO_BYTES = old_min

            warnings = [m for lvl, m in messages if lvl == "WARN" and "Racine en vrac" in m]
            self.assertEqual(len(warnings), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
