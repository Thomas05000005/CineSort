"""GATE AUDIT 2026-06-11 (R3d, gap[5]) — undo selectif respecte le delai 24h.

Avant : la garde 24h/410 n'existait que dans undo_last_apply (apply_support
L1018). undo_selected_rows allait directement de la selection a
_execute_undo_ops -> un undo REEL restait possible apres expiration du delai,
alors que l'UI pretend le bloquer (incoherence backend/frontend).

Apres : undo_selected_rows refuse l'execution reelle (HTTP 410) passe
_UNDO_DEADLINE_SECONDS, comme undo_last_apply. La dry_run reste autorisee meme
expiree (l'UI doit pouvoir afficher l'apercu).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api import apply_support
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import cleanup_test_tree
from tests._helpers import wait_run_done as _wait_done


def _create_file(path: Path, size: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class UndoSelective24hDeadlineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_undo24h_")
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
        src = self.root / "Dead.Line.2021.1080p"
        _create_file(src / "Dead.Line.2021.1080p.mkv")
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
        first_row_id = rows[0]["row_id"]
        # Recuperer started_ts du batch pour simuler l'expiration.
        _row, store = api._find_run_row(run_id)
        batch = store.apply.get_last_reversible_apply_batch(run_id)
        apply_ts = float(batch["started_ts"])
        return api, run_id, first_row_id, apply_ts

    def test_real_undo_refused_after_24h(self) -> None:
        api, run_id, row_id, apply_ts = self._apply_one()
        # On se place 25h apres l'apply.
        future = apply_ts + 25 * 3600
        with mock.patch.object(apply_support.time, "time", return_value=future):
            real = api._undo_selected_rows_impl(run_id, [row_id], dry_run=False)
        self.assertFalse(real.get("ok"), f"undo reel doit etre refuse apres 24h : {real}")
        self.assertEqual(
            real.get("http_status"),
            410,
            f"refus undo expire doit etre HTTP 410 (Gone) : {real}",
        )

    def test_dry_run_still_allowed_after_24h(self) -> None:
        api, run_id, row_id, apply_ts = self._apply_one()
        future = apply_ts + 25 * 3600
        with mock.patch.object(apply_support.time, "time", return_value=future):
            dry = api._undo_selected_rows_impl(run_id, [row_id], dry_run=True)
        self.assertTrue(dry.get("ok"), f"dry-run doit rester autorisee meme expiree : {dry}")
        self.assertEqual(dry.get("status"), "PREVIEW_ONLY")

    def test_real_undo_allowed_before_24h(self) -> None:
        # Garde non-regressive : avant l'echeance, l'undo reel passe normalement.
        api, run_id, row_id, _apply_ts = self._apply_one()
        real = api._undo_selected_rows_impl(run_id, [row_id], dry_run=False)
        self.assertTrue(real.get("ok"), f"undo reel avant 24h doit passer : {real}")
        self.assertIn(real.get("status"), {"UNDONE_DONE", "UNDONE_PARTIAL"})


if __name__ == "__main__":
    unittest.main()
