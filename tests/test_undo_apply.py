from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file


class UndoApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_undo_")
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

    def _wait_done(self, api: CineSortApi, run_id: str, timeout_s: float = 10.0) -> None:
        deadline = time.time() + timeout_s
        last = {}
        while time.time() < deadline:
            last = api.run.get_status(run_id, 0)
            if last.get("done"):
                return
            time.sleep(0.05)
        self.fail(f"Timeout waiting run completion run_id={run_id} last={last}")

    def _build_decisions(self, rows):
        return {
            row["row_id"]: {
                "ok": True,
                "title": row.get("proposed_title"),
                "year": row.get("proposed_year"),
            }
            for row in rows
        }

    def test_real_apply_creates_journal_and_undo_restores(self) -> None:
        src_folder = self.root / "Old.Name.2010.1080p"
        _create_file(src_folder / "Old.Name.2010.1080p.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        self._wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        self.assertTrue(rows)
        decisions = self._build_decisions(rows)

        applied = api.apply(run_id, decisions, False, False)
        self.assertTrue(applied.get("ok"), applied)
        self.assertTrue(applied.get("apply_batch_id"))

        preview = api.undo_last_apply_preview(run_id)
        self.assertTrue(preview.get("ok"), preview)
        self.assertTrue(preview.get("can_undo"), preview)
        self.assertGreaterEqual(int((preview.get("counts") or {}).get("reversible", 0)), 1)

        dry_preview = api.undo_last_apply(run_id, True)
        self.assertTrue(dry_preview.get("ok"), dry_preview)
        self.assertEqual(dry_preview.get("status"), "PREVIEW_ONLY")

        restored = api.undo_last_apply(run_id, False)
        self.assertTrue(restored.get("ok"), restored)
        self.assertIn(restored.get("status"), {"UNDONE_DONE", "UNDONE_PARTIAL"})
        self.assertTrue(src_folder.exists(), f"Source folder should be restored: {src_folder}")

        second_preview = api.undo_last_apply_preview(run_id)
        self.assertTrue(second_preview.get("ok"), second_preview)
        self.assertFalse(second_preview.get("can_undo"), second_preview)

    def test_dry_run_apply_does_not_create_undo_candidate(self) -> None:
        src_folder = self.root / "DryRun.Movie.2011.1080p"
        _create_file(src_folder / "DryRun.Movie.2011.1080p.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        self._wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        decisions = self._build_decisions(rows)
        dry = api.apply(run_id, decisions, True, False)
        self.assertTrue(dry.get("ok"), dry)

        preview = api.undo_last_apply_preview(run_id)
        self.assertTrue(preview.get("ok"), preview)
        self.assertFalse(preview.get("can_undo"), preview)

    def test_cleanup_residual_folder_is_included_in_undo_preview_and_restored(self) -> None:
        movie_folder = self.root / "Residual.Movie.2012.1080p"
        noise_folder = self.root / "Residual.Noise"
        _create_file(movie_folder / "Residual.Movie.2012.1080p.mkv")
        _create_file(noise_folder / "movie.nfo", size=64)
        _create_file(noise_folder / "poster.jpg", size=64)

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
                "cleanup_residual_folders_enabled": True,
                "cleanup_residual_folders_folder_name": "_Dossier Nettoyage",
                "cleanup_residual_folders_scope": "root_all",
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        self._wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        decisions = self._build_decisions(rows)
        applied = api.apply(run_id, decisions, False, False)
        self.assertTrue(applied.get("ok"), applied)

        cleanup_bucket = self.root / "_Dossier Nettoyage" / noise_folder.name
        self.assertFalse(noise_folder.exists())
        self.assertTrue(cleanup_bucket.exists(), f"Expected cleanup bucket folder: {cleanup_bucket}")

        preview = api.undo_last_apply_preview(run_id)
        self.assertTrue(preview.get("ok"), preview)
        self.assertTrue(preview.get("can_undo"), preview)
        categories = preview.get("categories") or {}
        self.assertEqual(int(categories.get("cleanup_residual_dirs") or 0), 1)
        summary_txt = self.state_dir / "runs" / f"tri_films_{run_id}" / "summary.txt"
        self.assertIn(
            "Dossiers residuels deplaces (inclus dans l'undo du run)",
            summary_txt.read_text(encoding="utf-8"),
        )

        restored = api.undo_last_apply(run_id, False)
        self.assertTrue(restored.get("ok"), restored)
        restored_categories = restored.get("categories") or {}
        self.assertEqual(int(restored_categories.get("cleanup_residual_dirs_reversed") or 0), 1)
        self.assertTrue(noise_folder.exists(), f"Residual folder should be restored: {noise_folder}")
        self.assertFalse(cleanup_bucket.exists(), f"Cleanup bucket folder should be removed by undo: {cleanup_bucket}")

    def test_undo_preview_logs_structured_error_and_returns_clean_message(self) -> None:
        api = CineSortApi()
        saved = api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(saved.get("ok"), saved)

        store, _runner = api._get_or_create_infra(self.state_dir)  # type: ignore[attr-defined]
        run_id = "20260309_120000_undo"
        store.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={"tmdb_enabled": False},
            created_ts=time.time() - 2.0,
        )
        store.mark_run_running(run_id, started_ts=time.time() - 1.0)
        store.mark_run_done(run_id, stats={"planned_rows": 0}, ended_ts=time.time())

        with mock.patch.object(api, "_build_undo_preview_payload", side_effect=OSError("undo preview boom")):
            out = api.undo_last_apply_preview(run_id)
            out_real = api.undo_last_apply(run_id, False)

        self.assertFalse(out.get("ok"), out)
        self.assertEqual(str(out.get("message") or ""), "Impossible de preparer l'annulation.")
        self.assertNotIn("undo preview boom", str(out.get("message") or ""))
        self.assertFalse(out_real.get("ok"), out_real)
        self.assertEqual(str(out_real.get("message") or ""), "Impossible d'annuler le dernier apply.")
        self.assertNotIn("undo preview boom", str(out_real.get("message") or ""))

        errs = store.list_errors(run_id)
        self.assertTrue(errs, errs)
        steps = [str(x.get("step") or "") for x in errs]
        self.assertIn("undo_last_apply_preview", steps)
        self.assertIn("undo_last_apply", steps)

    # ===== Undo v5 tests =====

    def test_undo_by_row_preview_shows_per_film_details(self) -> None:
        src1 = self.root / "Film.Alpha.2020.1080p"
        _create_file(src1 / "Film.Alpha.2020.1080p.mkv")
        src2 = self.root / "Film.Beta.2021.1080p"
        _create_file(src2 / "Film.Beta.2021.1080p.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        self._wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        self.assertGreaterEqual(len(rows), 2)
        decisions = self._build_decisions(rows)
        applied = api.apply(run_id, decisions, False, False)
        self.assertTrue(applied.get("ok"), applied)

        preview = api.undo_by_row_preview(run_id)
        self.assertTrue(preview.get("ok"), preview)
        self.assertTrue(preview.get("batch_id"))
        preview_rows = preview.get("rows", [])
        self.assertGreaterEqual(len(preview_rows), 1)
        for pr in preview_rows:
            self.assertIn("row_id", pr)
            self.assertIn("ops_total", pr)
            self.assertIn("can_undo", pr)
            self.assertIn("operations", pr)
            self.assertIsInstance(pr["operations"], list)

    def test_undo_selected_rows_restores_only_chosen_films(self) -> None:
        src1 = self.root / "Sel.Movie.A.2022.1080p"
        _create_file(src1 / "Sel.Movie.A.2022.1080p.mkv")
        src2 = self.root / "Sel.Movie.B.2023.1080p"
        _create_file(src2 / "Sel.Movie.B.2023.1080p.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        self._wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        self.assertGreaterEqual(len(rows), 2)
        decisions = self._build_decisions(rows)
        applied = api.apply(run_id, decisions, False, False)
        self.assertTrue(applied.get("ok"), applied)

        # Only undo the first film.
        first_row_id = rows[0]["row_id"]
        result = api.undo_selected_rows(run_id, [first_row_id], dry_run=False)
        self.assertTrue(result.get("ok"), result)
        self.assertIn(result.get("status"), {"UNDONE_DONE", "UNDONE_PARTIAL"})
        self.assertGreaterEqual(result.get("counts", {}).get("done", 0), 1)

        # The batch should be partially undone since only one film was restored.
        preview_after = api.undo_by_row_preview(run_id)
        self.assertTrue(preview_after.get("ok"), preview_after)

    def test_list_apply_history_returns_batches(self) -> None:
        src = self.root / "Hist.Movie.2019.1080p"
        _create_file(src / "Hist.Movie.2019.1080p.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        self._wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        decisions = self._build_decisions(rows)
        api.apply(run_id, decisions, False, False)

        history = api.run.list_apply_history(run_id)
        self.assertTrue(history.get("ok"), history)
        batches = history.get("batches", [])
        self.assertGreaterEqual(len(batches), 1)
        self.assertEqual(batches[0]["run_id"], run_id)

    def test_undo_selected_rows_dry_run_returns_preview(self) -> None:
        src = self.root / "DrySelective.2020.1080p"
        _create_file(src / "DrySelective.2020.1080p.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        self._wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        decisions = self._build_decisions(rows)
        api.apply(run_id, decisions, False, False)

        first_row_id = rows[0]["row_id"]
        result = api.undo_selected_rows(run_id, [first_row_id], dry_run=True)
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("status"), "PREVIEW_ONLY")
        self.assertTrue(result.get("dry_run"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
