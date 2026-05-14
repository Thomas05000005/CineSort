from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir


class CriticalFlowIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_critical_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._min_video_bytes = core.MIN_VIDEO_BYTES
        core.MIN_VIDEO_BYTES = 1

    def tearDown(self) -> None:
        core.MIN_VIDEO_BYTES = self._min_video_bytes
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _create_file(self, path: Path, size: int = 2048) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)

    def _wait_done(self, api: CineSortApi, run_id: str, timeout_s: float = 10.0) -> dict:
        deadline = time.time() + timeout_s
        last = {}
        while time.time() < deadline:
            last = api.run.get_status(run_id, 0)
            if last.get("done"):
                return last
            time.sleep(0.05)
        self.fail(f"Timeout waiting run completion run_id={run_id} last={last}")

    def _configured_api(self) -> CineSortApi:
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
        return api

    def _store(self) -> SQLiteStore:
        store = SQLiteStore(db_path_for_state_dir(self.state_dir))
        store.initialize()
        return store

    def _run_dir(self, run_id: str) -> Path:
        return self.state_dir / "runs" / f"tri_films_{run_id}"

    def _batch_row(self, batch_id: str) -> sqlite3.Row:
        conn = sqlite3.connect(str(db_path_for_state_dir(self.state_dir)))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT batch_id, status, summary_json FROM apply_batches WHERE batch_id=?",
                (batch_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, batch_id)
        return row

    def test_plan_validation_duplicates_survive_reconfigured_api_instances(self) -> None:
        self._create_file(self.root / "Movie.2020.1080p" / "movie_a.mkv")
        self._create_file(self.root / "Movie.2020.BluRay" / "movie_b.mkv")

        api_plan = CineSortApi()
        start = api_plan.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])

        status = self._wait_done(api_plan, run_id)
        self.assertIsNone(status.get("error"), status)

        plan = api_plan.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        self.assertEqual(len(rows), 2, rows)

        plan_jsonl = self._run_dir(run_id) / "plan.jsonl"
        self.assertTrue(plan_jsonl.exists(), plan_jsonl)
        line_count = sum(1 for line in plan_jsonl.read_text(encoding="utf-8").splitlines() if line.strip())
        self.assertEqual(line_count, len(rows))

        run_row = self._store().get_run(run_id)
        self.assertIsNotNone(run_row, run_id)
        self.assertEqual(str(run_row.get("status") or ""), "DONE")

        dirty_title = f"  {rows[0]['proposed_title']}:*?  "
        expected_title = core.windows_safe(dirty_title.strip())
        decisions = {
            row["row_id"]: {
                "ok": True,
                "title": dirty_title,
                "year": "not-a-year",
            }
            for row in rows
        }

        api_disk = self._configured_api()
        saved = api_disk.save_validation(run_id, decisions)
        self.assertTrue(saved.get("ok"), saved)
        validation_json = self._run_dir(run_id) / "validation.json"
        self.assertEqual(saved.get("path"), str(validation_json))
        self.assertTrue(validation_json.exists(), validation_json)

        loaded = api_disk.load_validation(run_id)
        self.assertTrue(loaded.get("ok"), loaded)
        normalized = loaded.get("decisions", {})
        self.assertEqual(set(normalized), {row["row_id"] for row in rows})
        for row in rows:
            decision = normalized[row["row_id"]]
            self.assertTrue(decision["ok"])
            self.assertEqual(decision["title"], expected_title)
            self.assertEqual(decision["year"], int(row["proposed_year"]))

        disk_payload = json.loads(validation_json.read_text(encoding="utf-8"))
        self.assertEqual(disk_payload, normalized)

        duplicates = api_disk.check_duplicates(run_id, normalized)
        self.assertTrue(duplicates.get("ok"), duplicates)
        self.assertGreaterEqual(int(duplicates.get("total_groups") or 0), 1, duplicates)
        groups = duplicates.get("groups", [])
        self.assertTrue(any(bool(group.get("plan_conflict")) for group in groups), groups)
        first_group = next(group for group in groups if group.get("plan_conflict"))
        targets = {str(item.get("target") or "") for item in first_group.get("rows", [])}
        self.assertEqual(len(targets), 1, first_group)

    def test_real_apply_and_undo_use_disk_state_logs_and_sqlite_journal(self) -> None:
        source_dir = self.root / "Old.Name.2010.1080p"
        source_video = source_dir / "Old.Name.2010.1080p.mkv"
        self._create_file(source_video)

        api_plan = CineSortApi()
        start = api_plan.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        self._wait_done(api_plan, run_id)

        plan = api_plan.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]

        decisions = {
            row["row_id"]: {
                "ok": True,
                "title": row["proposed_title"],
                "year": row["proposed_year"],
            }
        }

        expected_dir = self.root / core.windows_safe(f"{row['proposed_title']} ({row['proposed_year']})")
        expected_video = expected_dir / source_video.name
        run_dir = self._run_dir(run_id)
        ui_log = run_dir / "ui_log.txt"
        summary_txt = run_dir / "summary.txt"

        api_validate = self._configured_api()
        saved = api_validate.save_validation(run_id, decisions)
        self.assertTrue(saved.get("ok"), saved)

        api_apply = self._configured_api()
        applied = api_apply.apply(run_id, {}, False, False)
        self.assertTrue(applied.get("ok"), applied)
        self.assertTrue(applied.get("apply_batch_id"), applied)
        self.assertEqual(int((applied.get("result") or {}).get("errors") or 0), 0, applied)
        apply_batch_id = str(applied["apply_batch_id"])

        self.assertFalse(source_dir.exists(), source_dir)
        self.assertTrue(expected_dir.exists(), expected_dir)
        self.assertTrue(expected_video.exists(), expected_video)

        self.assertTrue(ui_log.exists(), ui_log)
        ui_log_text = ui_log.read_text(encoding="utf-8")
        self.assertIn("=== START PLAN ROOTS=", ui_log_text)
        self.assertIn("Validation enregistr", ui_log_text)
        self.assertIn("=== APPLY start", ui_log_text)
        self.assertIn("=== APPLY done", ui_log_text)

        self.assertTrue(summary_txt.exists(), summary_txt)
        summary_after_apply = summary_txt.read_text(encoding="utf-8")
        self.assertIn("=== RESUME APPLICATION ===", summary_after_apply)

        store = self._store()
        run_row = store.get_run(run_id)
        self.assertIsNotNone(run_row, run_id)
        self.assertEqual(str(run_row.get("status") or ""), "DONE")

        reversible_batch = store.get_last_reversible_apply_batch(run_id)
        self.assertIsNotNone(reversible_batch, run_id)
        self.assertEqual(str(reversible_batch.get("batch_id") or ""), apply_batch_id)
        self.assertEqual(str(reversible_batch.get("status") or ""), "DONE")

        ops_before = store.list_apply_operations(batch_id=apply_batch_id)
        self.assertTrue(ops_before, apply_batch_id)
        self.assertTrue(all(str(op.get("undo_status") or "") == "PENDING" for op in ops_before), ops_before)

        api_undo = self._configured_api()
        preview = api_undo.undo_last_apply_preview(run_id)
        self.assertTrue(preview.get("ok"), preview)
        self.assertTrue(preview.get("can_undo"), preview)
        self.assertEqual(str(preview.get("batch_id") or ""), apply_batch_id)
        self.assertGreaterEqual(int((preview.get("counts") or {}).get("reversible") or 0), 1, preview)

        undone = api_undo.undo_last_apply(run_id, False)
        self.assertTrue(undone.get("ok"), undone)
        self.assertIn(str(undone.get("status") or ""), {"UNDONE_DONE", "UNDONE_PARTIAL"})

        self.assertTrue(source_dir.exists(), source_dir)
        self.assertTrue(source_video.exists(), source_video)
        self.assertFalse(expected_dir.exists(), expected_dir)

        ui_log_after_undo = ui_log.read_text(encoding="utf-8")
        self.assertIn("=== UNDO start", ui_log_after_undo)
        self.assertIn("=== UNDO done", ui_log_after_undo)
        summary_after_undo = summary_txt.read_text(encoding="utf-8")
        self.assertIn("=== RESUME UNDO ===", summary_after_undo)

        ops_after = self._store().list_apply_operations(batch_id=apply_batch_id)
        self.assertTrue(ops_after, apply_batch_id)
        self.assertTrue(all(str(op.get("undo_status") or "") == "DONE" for op in ops_after), ops_after)

        batch_row = self._batch_row(apply_batch_id)
        self.assertIn(str(batch_row["status"]), {"UNDONE_DONE", "UNDONE_PARTIAL"})
        summary_payload = json.loads(str(batch_row["summary_json"] or "{}"))
        self.assertEqual(summary_payload.get("run_id"), run_id)
        self.assertGreaterEqual(int(((summary_payload.get("undo") or {}).get("done")) or 0), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
