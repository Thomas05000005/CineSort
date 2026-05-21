"""Tests phase 6 doublons : integration apply -> bucket _duplicates_user_decided/.

Spec : docs/internal/design/refonte_2026_05_17/screens/01-doublons.md §3.7.

Verifie :
- move_duplicate_losers_to_user_decided deplace les rows "single" vers le bucket.
- move_duplicate_losers_to_user_decided deplace les rows "collection" (video + sidecars)
  sans casser les autres films du dossier partage.
- apply_rows accepte le parametre duplicate_loser_row_ids et exclut les losers
  de la boucle apply normale.
- Les operations passent par record_apply_op (reversible via undo).
- Le bucket est cree automatiquement dans build_apply_context.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import List

import cinesort.app.apply_core as apply_core
import cinesort.domain.core as core


class DuplicatesUserDecidedApplyTests(unittest.TestCase):
    """Section 1 : move_duplicate_losers_to_user_decided (apply_core)."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cs_dup_apply_")
        self.root = Path(self._tmp) / "root"
        self.run_review_root = Path(self._tmp) / "state" / "runs" / "r1" / "_review"
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs: List[tuple] = []
        self.ops: List[dict] = []

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _log(self, level: str, msg: str) -> None:
        self.logs.append((level, msg))

    def _record_op(self, payload: dict) -> None:
        self.ops.append(dict(payload))

    def _cfg(self) -> core.Config:
        return core.Config(root=self.root, enable_collection_folder=True).normalized()

    def _write(self, path: Path, data: bytes = b"X" * 64) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _single_row(self, row_id: str, folder: Path, title: str, year: int) -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id,
            kind="single",
            folder=str(folder),
            video="movie.mkv",
            proposed_title=title,
            proposed_year=year,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[core.Candidate(title=title, year=year, source="name", score=0.7)],
        )

    def _collection_row(self, row_id: str, folder: Path, video: str, title: str, year: int) -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id,
            kind="collection",
            folder=str(folder),
            video=video,
            proposed_title=title,
            proposed_year=year,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[core.Candidate(title=title, year=year, source="name", score=0.7)],
            collection_name=folder.name,
        )

    # -------------------------------------------------------------------------
    # build_apply_context : crée le bucket
    # -------------------------------------------------------------------------

    def test_build_apply_context_creates_duplicates_user_decided_bucket(self) -> None:
        ctx = apply_core.build_apply_context(
            self._cfg(),
            rows=[],
            dry_run=False,
            quarantine_unapproved=False,
            run_review_root=self.run_review_root,
            decision_presence=None,
        )
        self.assertIsNotNone(ctx.duplicates_user_decided_root)
        bucket = ctx.duplicates_user_decided_root
        assert bucket is not None
        self.assertTrue(bucket.exists(), msg=f"bucket {bucket} doit etre cree")
        self.assertEqual(bucket.name, "_duplicates_user_decided")

    def test_build_apply_context_skips_mkdir_in_dry_run(self) -> None:
        ctx = apply_core.build_apply_context(
            self._cfg(),
            rows=[],
            dry_run=True,
            quarantine_unapproved=False,
            run_review_root=self.run_review_root,
            decision_presence=None,
        )
        bucket = ctx.duplicates_user_decided_root
        assert bucket is not None
        self.assertFalse(bucket.exists(), msg="dry_run ne doit rien creer sur disque")

    # -------------------------------------------------------------------------
    # move_duplicate_losers_to_user_decided : single rows
    # -------------------------------------------------------------------------

    def test_single_loser_folder_moved_to_bucket(self) -> None:
        loser = self.root / "F&F4 720p"
        self._write(loser / "movie.mkv")
        self._write(loser / "movie.nfo", b"<m></m>")
        row = self._single_row("R_LOSER", loser, "Fast & Furious 4", 2009)

        bucket = self.run_review_root / "_duplicates_user_decided"
        bucket.mkdir(parents=True, exist_ok=True)

        res = core.ApplyResult()
        apply_core.move_duplicate_losers_to_user_decided(
            self._cfg(),
            [row],
            {"R_LOSER"},
            duplicates_user_decided_root=bucket,
            dry_run=False,
            log=self._log,
            res=res,
            record_op=self._record_op,
        )

        # Source folder disparait
        self.assertFalse(loser.exists())
        # Bucket recoit le folder
        moved = bucket / "F&F4 720p"
        self.assertTrue(moved.exists(), msg=f"bucket contenu : {list(bucket.iterdir())}")
        self.assertTrue((moved / "movie.mkv").exists())
        # Op journalisee
        move_ops = [op for op in self.ops if op["op_type"] == "MOVE_DIR"]
        self.assertEqual(len(move_ops), 1)
        self.assertEqual(move_ops[0]["row_id"], "R_LOSER")
        self.assertTrue(move_ops[0]["reversible"])

    def test_empty_loser_set_is_noop(self) -> None:
        loser = self.root / "X (2000)"
        self._write(loser / "movie.mkv")
        row = self._single_row("R1", loser, "X", 2000)

        bucket = self.run_review_root / "_duplicates_user_decided"
        bucket.mkdir(parents=True, exist_ok=True)
        res = core.ApplyResult()
        apply_core.move_duplicate_losers_to_user_decided(
            self._cfg(),
            [row],
            set(),
            duplicates_user_decided_root=bucket,
            dry_run=False,
            log=self._log,
            res=res,
            record_op=self._record_op,
        )
        self.assertTrue(loser.exists(), msg="le folder ne doit pas etre deplace")
        self.assertEqual(self.ops, [])

    def test_unknown_row_id_logs_warn_and_continues(self) -> None:
        bucket = self.run_review_root / "_duplicates_user_decided"
        bucket.mkdir(parents=True, exist_ok=True)
        res = core.ApplyResult()
        apply_core.move_duplicate_losers_to_user_decided(
            self._cfg(),
            rows=[],
            loser_row_ids={"R_INCONNU"},
            duplicates_user_decided_root=bucket,
            dry_run=False,
            log=self._log,
            res=res,
            record_op=self._record_op,
        )
        warns = [(lvl, msg) for (lvl, msg) in self.logs if lvl == "WARN"]
        self.assertTrue(any("R_INCONNU" in msg for _, msg in warns))

    # -------------------------------------------------------------------------
    # move_duplicate_losers_to_user_decided : collection rows
    # -------------------------------------------------------------------------

    def test_collection_loser_video_only_moved(self) -> None:
        # Un dossier shared avec 2 films : seul le loser doit etre deplace.
        shared = self.root / "Saga"
        self._write(shared / "film_loser.mkv")
        self._write(shared / "film_loser.nfo", b"<m></m>")
        self._write(shared / "film_other.mkv")  # ne doit PAS bouger

        row_loser = self._collection_row("R_COLL_LOSER", shared, "film_loser.mkv", "Film", 2010)

        bucket = self.run_review_root / "_duplicates_user_decided"
        bucket.mkdir(parents=True, exist_ok=True)
        res = core.ApplyResult()
        apply_core.move_duplicate_losers_to_user_decided(
            self._cfg(),
            [row_loser],
            {"R_COLL_LOSER"},
            duplicates_user_decided_root=bucket,
            dry_run=False,
            log=self._log,
            res=res,
            record_op=self._record_op,
        )

        # film_loser.mkv + film_loser.nfo dans le bucket
        moved_root = bucket / "Saga"
        self.assertTrue(moved_root.exists())
        # Le sidecar nfo et la video doivent etre dans le bucket
        moved_files = {p.name for p in moved_root.rglob("*") if p.is_file()}
        self.assertIn("film_loser.mkv", moved_files)
        self.assertIn("film_loser.nfo", moved_files)
        # Le film "other" reste a sa place dans le dossier source partage
        self.assertTrue((shared / "film_other.mkv").exists())

    # -------------------------------------------------------------------------
    # Integration : apply_rows accepte le parametre et exclut les losers
    # -------------------------------------------------------------------------

    def test_apply_rows_excludes_losers_from_normal_loop(self) -> None:
        winner = self.root / "F&F4 1080p"
        loser = self.root / "F&F4 720p"
        self._write(winner / "movie.mkv")
        self._write(loser / "movie.mkv")

        winner_row = self._single_row("R_WIN", winner, "Fast & Furious 4", 2009)
        loser_row = self._single_row("R_LOS", loser, "Fast & Furious 4", 2009)
        # Decisions : seuls les winners passent dans la boucle normale.
        decisions = {
            "R_WIN": {"ok": True, "title": "Fast & Furious 4", "year": 2009},
            # R_LOS n'est PAS dans `decisions` car il est ecarte via duplicate_loser_row_ids.
        }

        result = apply_core.apply_rows(
            self._cfg(),
            [winner_row, loser_row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
            record_op=self._record_op,
            duplicate_loser_row_ids={"R_LOS"},
        )

        # Loser deplacé vers le bucket
        bucket = self.run_review_root / "_duplicates_user_decided"
        self.assertTrue((bucket / "F&F4 720p" / "movie.mkv").exists())
        self.assertFalse(loser.exists())
        # Winner traité normalement → renomme en "Fast & Furious 4 (2009)"
        renamed = self.root / "Fast & Furious 4 (2009)"
        self.assertTrue(renamed.exists(), msg=f"renamed manquant. root={list(self.root.iterdir())}")
        # Pas d'erreur
        self.assertEqual(result.errors, 0)


if __name__ == "__main__":
    unittest.main()
