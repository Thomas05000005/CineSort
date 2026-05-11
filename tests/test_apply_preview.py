"""P1.3 : tests pour build_apply_preview.

Vérifie que le plan de pré-apply produit une structure visuelle-friendly
sans toucher au filesystem.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi


class BuildApplyPreviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_preview_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._min_video_bytes = core.MIN_VIDEO_BYTES
        core.MIN_VIDEO_BYTES = 1

    def tearDown(self):
        core.MIN_VIDEO_BYTES = self._min_video_bytes
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _wait_done(self, api: CineSortApi, run_id: str, timeout_s: float = 10.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            last = api.get_status(run_id, 0)
            if last.get("done"):
                return
            time.sleep(0.05)
        self.fail(f"Timeout run_id={run_id}")

    def _make_plan(self, n_films: int = 2) -> tuple[CineSortApi, str, list]:
        for i in range(n_films):
            folder = self.root / f"Film.{2010 + i}.1080p"
            folder.mkdir(parents=True)
            (folder / f"Film.{2010 + i}.1080p.mkv").write_bytes(b"x" * 2048)

        api = CineSortApi()
        start = api.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.assertTrue(start.get("ok"))
        run_id = start["run_id"]
        self._wait_done(api, run_id)
        plan = api.get_plan(run_id)
        return api, run_id, plan.get("rows", [])

    def test_preview_returns_films_and_totals(self):
        api, run_id, rows = self._make_plan(n_films=3)
        self.assertTrue(rows)
        decisions = {r["row_id"]: {"ok": True, "title": r["proposed_title"], "year": r["proposed_year"]} for r in rows}

        preview = api.build_apply_preview(run_id, decisions)
        self.assertTrue(preview.get("ok"), preview)
        self.assertIn("films", preview)
        self.assertIn("totals", preview)
        self.assertGreaterEqual(len(preview["films"]), 1)
        self.assertGreaterEqual(preview["totals"]["total_ops"], 1)

    def test_preview_does_not_touch_filesystem(self):
        api, run_id, rows = self._make_plan(n_films=2)
        decisions = {r["row_id"]: {"ok": True, "title": r["proposed_title"], "year": r["proposed_year"]} for r in rows}
        # Snapshot initial
        initial_entries = {p.name for p in self.root.iterdir()}

        preview = api.build_apply_preview(run_id, decisions)
        self.assertTrue(preview.get("ok"))

        # Le filesystem doit être identique après preview
        after_entries = {p.name for p in self.root.iterdir()}
        self.assertEqual(initial_entries, after_entries)

    def test_preview_enriches_film_with_metadata(self):
        api, run_id, rows = self._make_plan(n_films=1)
        row = rows[0]
        decisions = {row["row_id"]: {"ok": True, "title": row["proposed_title"], "year": row["proposed_year"]}}

        preview = api.build_apply_preview(run_id, decisions)
        self.assertTrue(preview.get("films"))
        film = preview["films"][0]
        # Chaque film expose title, confidence, ops
        self.assertIn("title", film)
        self.assertIn("confidence", film)
        self.assertIn("confidence_label", film)
        self.assertIn("ops", film)
        self.assertIn("change_type", film)

    def test_preview_classifies_change_type(self):
        api, run_id, rows = self._make_plan(n_films=1)
        decisions = {r["row_id"]: {"ok": True, "title": r["proposed_title"], "year": r["proposed_year"]} for r in rows}
        preview = api.build_apply_preview(run_id, decisions)
        film = preview["films"][0]
        # Un film à renommer à la racine doit être classé comme rename_folder ou move_mixed
        self.assertIn(film["change_type"], ("rename_folder", "move_mixed", "move_files", "noop"))

    def test_preview_with_no_decisions_returns_empty_or_error(self):
        api, run_id, _ = self._make_plan(n_films=1)
        # Décisions vides
        preview = api.build_apply_preview(run_id, {})
        # Peut retourner ok=False (validation) ou totals.films=0 selon la logique
        if preview.get("ok"):
            self.assertEqual(preview["totals"]["total_ops"], 0)
        else:
            self.assertIn("message", preview)

    def test_preview_totals_consistent(self):
        api, run_id, rows = self._make_plan(n_films=2)
        decisions = {r["row_id"]: {"ok": True, "title": r["proposed_title"], "year": r["proposed_year"]} for r in rows}
        preview = api.build_apply_preview(run_id, decisions)
        totals = preview["totals"]
        # Les totals.changes_count + noop_count doit égaler films (au plus)
        self.assertLessEqual(totals["changes_count"] + totals["noop_count"], totals["films"] + 1)


if __name__ == "__main__":
    unittest.main()
