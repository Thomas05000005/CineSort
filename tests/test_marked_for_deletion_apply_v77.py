"""GATE AUDIT 2026-06-14 (R7-4) — "Marquer pour suppression" est consomme par l'apply.

Avant, le marquage (modal -> table DB ; bulk -> deletion_marks.json) etait
write-only : apply_core ne le referencait jamais, aucun film n'etait deplace ->
promesse UI silencieusement non tenue. Desormais apply_rows accepte
marked_for_deletion_row_ids et route ces films vers _review/
_user_marked_for_deletion/ (puis les exclut de la boucle apply). Securite
torrents : DEPLACEMENT, pas suppression.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.app.apply_core as apply_core
import cinesort.domain.core as core


class MarkedForDeletionApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="marked_del_")
        self.root = Path(self._tmp) / "root"
        self.run_review_root = Path(self._tmp) / "state" / "runs" / "tri_films_test" / "_review"
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs: list = []

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _log(self, level: str, msg: str) -> None:
        self.logs.append((level, msg))

    def _single_row(self, row_id: str, folder: Path, title: str, year: int) -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id, kind="single", folder=str(folder), video="movie.mkv",
            proposed_title=title, proposed_year=year, proposed_source="name",
            confidence=70, confidence_label="med", candidates=[],
        )

    def test_marked_film_moved_to_bucket_and_excluded(self) -> None:
        src = self.root / "Movie marked"
        (src).mkdir(parents=True, exist_ok=True)
        (src / "movie.mkv").write_bytes(b"DATA")
        row = self._single_row("M|1", src, "Movie", 2020)
        decisions = {"M|1": {"ok": True, "title": "Movie", "year": 2020}}

        result = apply_core.apply_rows(
            core.Config(root=self.root, enable_collection_folder=True).normalized(),
            [row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
            marked_for_deletion_row_ids={"M|1"},
        )

        bucket = self.run_review_root / "_user_marked_for_deletion" / "Movie marked"
        self.assertEqual(result.marked_for_deletion_moved_count, 1)
        self.assertTrue((bucket / "movie.mkv").exists(), "le film doit etre deplace dans le bucket")
        self.assertFalse(src.exists(), "le dossier source doit avoir ete deplace")
        # Exclu de la boucle apply -> pas de renommage vers Movie (2020).
        self.assertFalse((self.root / "Movie (2020)").exists())
        self.assertEqual(result.errors, 0)

    def test_no_marks_is_noop(self) -> None:
        src = self.root / "Movie keep"
        src.mkdir(parents=True, exist_ok=True)
        (src / "movie.mkv").write_bytes(b"DATA")
        row = self._single_row("K|1", src, "Movie", 2020)
        decisions = {"K|1": {"ok": True, "title": "Movie", "year": 2020}}
        result = apply_core.apply_rows(
            core.Config(root=self.root, enable_collection_folder=True).normalized(),
            [row], decisions, dry_run=False, quarantine_unapproved=False,
            log=self._log, run_review_root=self.run_review_root,
        )
        self.assertEqual(result.marked_for_deletion_moved_count, 0)
        self.assertFalse((self.run_review_root / "_user_marked_for_deletion").exists() and any((self.run_review_root / "_user_marked_for_deletion").iterdir()))


if __name__ == "__main__":
    unittest.main()
