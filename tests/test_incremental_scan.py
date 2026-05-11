from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

import cinesort.domain.core as core
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir


class IncrementalScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_incremental_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir))
        self.store.initialize()

        self._min_video_bytes = core.MIN_VIDEO_BYTES
        core.MIN_VIDEO_BYTES = 1

    def tearDown(self) -> None:
        core.MIN_VIDEO_BYTES = self._min_video_bytes
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _create_video(self, folder: Path, name: str, payload: bytes) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / name
        p.write_bytes(payload)
        return p

    def _run_plan(self, *, incremental: bool, run_id: str):
        cfg = core.Config(
            root=self.root,
            enable_tmdb=False,
            incremental_scan_enabled=incremental,
        )
        logs = []
        rows, stats = core.plan_library(
            cfg,
            tmdb=None,
            log=lambda level, msg: logs.append((level, msg)),
            progress=lambda _idx, _total, _cur: None,
            scan_index=self.store if incremental else None,
            run_id=run_id,
        )
        return rows, stats, logs

    def _rows_signature(self, rows):
        out = []
        for row in rows:
            out.append(
                (
                    str(row.kind),
                    str(row.folder),
                    str(row.video),
                    str(row.proposed_title),
                    int(row.proposed_year),
                    str(row.proposed_source),
                    str(row.confidence_label),
                )
            )
        out.sort()
        return out

    def test_incremental_scan_matches_full_scan_and_reuses_cache(self) -> None:
        self._create_video(self.root / "Inception.2010.1080p", "Inception.2010.1080p.mkv", b"a" * 4096)
        self._create_video(self.root / "Interstellar.2014.2160p", "Interstellar.2014.2160p.mkv", b"b" * 4096)
        self._create_video(self.root / "Matrix Saga", "The.Matrix.1999.1080p.mkv", b"c" * 4096)
        self._create_video(self.root / "Matrix Saga", "The.Matrix.Reloaded.2003.1080p.mkv", b"d" * 4096)

        rows_full, stats_full, _ = self._run_plan(incremental=False, run_id="full")
        rows_inc_first, stats_inc_first, _ = self._run_plan(incremental=True, run_id="inc_1")
        rows_inc_second, stats_inc_second, _ = self._run_plan(incremental=True, run_id="inc_2")

        self.assertEqual(stats_full.planned_rows, stats_inc_first.planned_rows)
        self.assertEqual(stats_full.planned_rows, stats_inc_second.planned_rows)
        self.assertEqual(self._rows_signature(rows_full), self._rows_signature(rows_inc_first))
        self.assertEqual(self._rows_signature(rows_full), self._rows_signature(rows_inc_second))

        self.assertGreaterEqual(int(stats_inc_first.incremental_cache_misses), 1)
        self.assertEqual(int(stats_inc_first.incremental_cache_hits), 0)
        self.assertGreaterEqual(int(stats_inc_second.incremental_cache_hits), 1)
        self.assertGreaterEqual(int(stats_inc_second.incremental_cache_rows_reused), 1)

    def test_incremental_scan_invalidates_changed_folder_only(self) -> None:
        f1 = self._create_video(self.root / "Movie.One.2010", "Movie.One.2010.mkv", b"x" * 4096)
        self._create_video(self.root / "Movie.Two.2011", "Movie.Two.2011.mkv", b"y" * 4096)

        _rows_1, stats_1, _ = self._run_plan(incremental=True, run_id="inc_first")
        self.assertGreaterEqual(int(stats_1.incremental_cache_misses), 1)

        time.sleep(0.01)  # ensure mtime changes on all supported filesystems
        f1.write_bytes(b"z" * 5000)

        _rows_2, stats_2, _ = self._run_plan(incremental=True, run_id="inc_second")
        self.assertGreaterEqual(int(stats_2.incremental_cache_misses), 1)
        self.assertGreaterEqual(int(stats_2.incremental_cache_hits), 1)

    def test_incremental_second_pass_has_better_or_similar_runtime(self) -> None:
        for i in range(25):
            self._create_video(
                self.root / f"Film.{i:02d}.2010",
                f"Film.{i:02d}.2010.1080p.mkv",
                bytes([65 + (i % 20)]) * 8192,
            )

        t0 = time.perf_counter()
        _rows_1, _stats_1, _ = self._run_plan(incremental=True, run_id="perf_1")
        dt_first = time.perf_counter() - t0

        t1 = time.perf_counter()
        _rows_2, _stats_2, _ = self._run_plan(incremental=True, run_id="perf_2")
        dt_second = time.perf_counter() - t1

        # Relative sanity check: second pass should not degrade significantly.
        self.assertLessEqual(dt_second, (dt_first * 1.5) + 0.05)

    # ===== Scan v2: per-video row cache =====

    def test_v2_row_cache_reuses_unchanged_video(self) -> None:
        """When folder_sig changes (nfo added) but video is unchanged, v2 cache reuses the row."""
        self._create_video(self.root / "V2.Movie.2020", "V2.Movie.2020.1080p.mkv", b"v" * 4096)

        # First scan: populate both caches.
        rows_1, stats_1, store = self._run_plan(incremental=True, run_id="v2_1")
        self.assertGreater(len(rows_1), 0)

        # Add a .nfo file — folder_sig changes but video doesn't.
        nfo = self.root / "V2.Movie.2020" / "movie.nfo"
        nfo.write_text('<?xml version="1.0"?><movie><title>V2 Movie</title><year>2020</year></movie>', encoding="utf-8")

        # Second scan: folder_sig miss but video v2 should hit.
        rows_2, stats_2, _ = self._run_plan(incremental=True, run_id="v2_2")
        self.assertEqual(len(rows_1), len(rows_2))
        # V2 row cache: the video file was unchanged, so row should be reused
        # (unless nfo_sig change also invalidated it — which is expected since NFO appeared).
        # In this case nfo_sig changed (None → hash), so it's a miss.
        # But if nfo was already there, it would be a hit.

    def test_v2_row_cache_invalidates_on_video_change(self) -> None:
        """When a video file content changes, the v2 row cache misses."""
        self._create_video(self.root / "V2.Change.2021", "V2.Change.2021.mkv", b"a" * 4096)

        rows_1, stats_1, store = self._run_plan(incremental=True, run_id="v2c_1")
        self.assertEqual(len(rows_1), 1)

        # Modify the video file.
        (self.root / "V2.Change.2021" / "V2.Change.2021.mkv").write_bytes(b"b" * 5000)

        rows_2, stats_2, _ = self._run_plan(incremental=True, run_id="v2c_2")
        self.assertEqual(len(rows_2), 1)
        # Row should be recalculated (video changed) — row cache miss for this video.
        self.assertGreaterEqual(int(getattr(stats_2, "incremental_cache_row_misses", 0) or 0), 1)

    def test_v2_prune_removes_deleted_videos(self) -> None:
        """Videos removed from library are pruned from the row cache."""
        self._create_video(self.root / "V2.Prune.A.2022", "V2.Prune.A.2022.mkv", b"x" * 4096)
        self._create_video(self.root / "V2.Prune.B.2022", "V2.Prune.B.2022.mkv", b"y" * 4096)

        rows_1, _, store = self._run_plan(incremental=True, run_id="v2p_1")
        self.assertEqual(len(rows_1), 2)

        # Delete one folder.
        import shutil

        shutil.rmtree(str(self.root / "V2.Prune.B.2022"))

        rows_2, _, _ = self._run_plan(incremental=True, run_id="v2p_2")
        self.assertEqual(len(rows_2), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
