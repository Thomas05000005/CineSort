"""GATE AUDIT 2026-06-11 (R3d, gap[6]) — l'undo reel acquiert le slot apply.

Avant : undo_last_apply et undo_selected_rows executaient le vrai undo (FS+DB)
SANS acquerir api._apply_slot_guard ; seuls apply_changes/build_apply_preview
le prenaient. Un apply concurrent du meme run pouvait donc courir avec un undo
-> corruption potentielle (un fichier deplace par l'apply, restaure par l'undo
au milieu).

Apres : les deux chemins undo reels passent par _apply_slot_guard(run_id) et
renvoient HTTP 409 (apply_already_in_progress) si le slot est deja occupe,
exactement comme apply. La dry-run reste hors slot (lecture seule).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import cleanup_test_tree
from tests._helpers import wait_run_done as _wait_done


def _create_file(path: Path, size: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class UndoSlotGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_undo_slot_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

    def tearDown(self) -> None:
        cleanup_test_tree(self._tmp)

    def _apply_one(self):
        src = self.root / "Slot.Guard.2021.1080p"
        _create_file(src / "Slot.Guard.2021.1080p.mkv")
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
        _wait_done(api, run_id)
        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        self.assertTrue(rows, plan)
        decisions = {
            r["row_id"]: {"ok": True, "title": r.get("proposed_title"), "year": r.get("proposed_year")} for r in rows
        }
        applied = api._apply_impl(run_id, decisions, False, False)
        self.assertTrue(applied.get("ok"), applied)
        return api, run_id, rows[0]["row_id"]

    def test_undo_last_apply_blocked_when_slot_busy(self) -> None:
        api, run_id, _row_id = self._apply_one()
        # Simuler un apply concurrent : slot occupe.
        self.assertTrue(api._acquire_apply_slot(run_id))
        try:
            real = api._undo_last_apply_impl(run_id, False)
        finally:
            api._release_apply_slot(run_id)
        self.assertFalse(real.get("ok"), f"undo reel doit etre bloque si slot occupe : {real}")
        self.assertEqual(real.get("http_status"), 409, f"slot occupe -> 409 attendu : {real}")

    def test_undo_selected_rows_blocked_when_slot_busy(self) -> None:
        api, run_id, row_id = self._apply_one()
        self.assertTrue(api._acquire_apply_slot(run_id))
        try:
            real = api._undo_selected_rows_impl(run_id, [row_id], dry_run=False)
        finally:
            api._release_apply_slot(run_id)
        self.assertFalse(real.get("ok"), f"undo selectif doit etre bloque si slot occupe : {real}")
        self.assertEqual(real.get("http_status"), 409, f"slot occupe -> 409 attendu : {real}")

    def test_undo_works_once_slot_released(self) -> None:
        # Non-regression : slot libre -> l'undo reel passe normalement.
        api, run_id, row_id = self._apply_one()
        real = api._undo_selected_rows_impl(run_id, [row_id], dry_run=False)
        self.assertTrue(real.get("ok"), f"slot libre : undo doit passer : {real}")
        self.assertIn(real.get("status"), {"UNDONE_DONE", "UNDONE_PARTIAL"})

    def test_dry_run_not_blocked_by_slot(self) -> None:
        # La dry-run (lecture seule) ne doit PAS etre bloquee par le slot.
        api, run_id, row_id = self._apply_one()
        self.assertTrue(api._acquire_apply_slot(run_id))
        try:
            dry = api._undo_selected_rows_impl(run_id, [row_id], dry_run=True)
        finally:
            api._release_apply_slot(run_id)
        self.assertTrue(dry.get("ok"), f"dry-run ne doit pas etre bloquee : {dry}")
        self.assertEqual(dry.get("status"), "PREVIEW_ONLY")


if __name__ == "__main__":
    unittest.main()
