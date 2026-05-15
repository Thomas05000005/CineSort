from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi


class RunReportExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_report_")
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
            status = api.run.get_status(run_id, 0)
            if status.get("done"):
                return
            time.sleep(0.05)
        self.fail(f"Timeout waiting completion for run_id={run_id}")

    def test_export_run_report_json_and_csv(self) -> None:
        self._create_file(self.root / "Interstellar.2014.1080p" / "Interstellar.2014.1080p.mkv")
        self._create_file(self.root / "Dune.2021.2160p" / "Dune.2021.2160p.mkv")

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
        run_id = start["run_id"]
        self._wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        self.assertGreaterEqual(len(rows), 2)

        decisions = {
            row["row_id"]: {
                "ok": True,
                "title": row.get("proposed_title"),
                "year": row.get("proposed_year"),
            }
            for row in rows
        }
        saved = api.save_validation(run_id, decisions)
        self.assertTrue(saved.get("ok"), saved)

        score_one = api.quality.get_quality_report(run_id, rows[0]["row_id"], {"reuse_existing": False})
        self.assertTrue(score_one.get("ok"), score_one)

        dry = api.apply(run_id, decisions, True, False)
        self.assertTrue(dry.get("ok"), dry)

        exported_json = api.run.export_run_report(run_id, "json")
        self.assertTrue(exported_json.get("ok"), exported_json)
        json_path = Path(exported_json["path"])
        self.assertTrue(json_path.exists(), json_path)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("run_id"), run_id)
        self.assertEqual(len(payload.get("rows", [])), len(rows))
        counts = payload.get("counts", {})
        self.assertEqual(int(counts.get("rows_total") or 0), len(rows))
        self.assertGreaterEqual(int(counts.get("quality_reports") or 0), 1)

        exported_csv = api.run.export_run_report(run_id, "csv")
        self.assertTrue(exported_csv.get("ok"), exported_csv)
        csv_path = Path(exported_csv["path"])
        self.assertTrue(csv_path.exists(), csv_path)
        csv_bytes = csv_path.read_bytes()
        self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))
        csv_text = csv_path.read_text(encoding="utf-8-sig")
        self.assertIn("run_id;row_id;kind;folder", csv_text)
        self.assertIn(run_id, csv_text)
        self.assertGreaterEqual(len(csv_text.splitlines()), 2)

    def test_export_run_report_rejects_bad_format(self) -> None:
        api = CineSortApi()
        result = api.run.export_run_report("abcd1234", "xml")
        self.assertFalse(result.get("ok"), result)
        self.assertIn("format invalide", str(result.get("message", "")).lower())

    def test_export_run_report_requires_existing_run(self) -> None:
        api = CineSortApi()
        result = api.run.export_run_report("abcd1234", "json")
        self.assertFalse(result.get("ok"), result)
        self.assertIn("introuvable", str(result.get("message", "")).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
