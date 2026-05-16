from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.app.plan_support as plan_support
import cinesort.app.apply_core as apply_core
import cinesort.domain.core as core


class MergeDuplicatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="merge_dupes_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.run_review_root = self.state_dir / "runs" / "tri_films_test" / "_review"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.logs = []

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _log(self, level: str, msg: str) -> None:
        self.logs.append((level, msg))

    def _write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _cfg(self) -> core.Config:
        return core.Config(root=self.root, enable_collection_folder=True).normalized()

    def _single_row(self, row_id: str, folder: Path, title: str, year: int, video: str = "movie.mkv") -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id,
            kind="single",
            folder=str(folder),
            video=video,
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

    def test_is_under_collection_root_respects_configured_collection_folder(self) -> None:
        cfg = self._cfg()
        inside = self.root / cfg.collection_root_name / "Saga"
        outside = self.root / "Saga"

        self.assertTrue(core.is_under_collection_root(cfg, inside))
        self.assertFalse(core.is_under_collection_root(cfg, outside))

    def test_single_folder_is_conform_requires_matching_title_and_year(self) -> None:
        self.assertTrue(core._single_folder_is_conform("Movie (2020)", "Movie", 2020))
        self.assertFalse(core._single_folder_is_conform("Movie", "Movie", 2020))
        self.assertFalse(core._single_folder_is_conform("Other (2020)", "Movie", 2020))

    def test_apply_merge_when_rename_target_exists_moves_files_and_removes_source_dir(self) -> None:
        src = self.root / "Movie source"
        dst = self.root / "Movie (2020)"
        dst.mkdir(parents=True, exist_ok=True)
        self._write(src / "movie.mkv", b"A" * 1024)
        self._write(src / "movie.nfo", b"<movie></movie>")

        row = self._single_row("S|1", src, "Movie", 2020)
        decisions = {"S|1": {"ok": True, "title": "Movie", "year": 2020}}

        result = apply_core.apply_rows(
            self._cfg(),
            [row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertEqual(result.merges_count, 1)
        self.assertTrue((dst / "movie.mkv").exists())
        self.assertTrue((dst / "movie.nfo").exists())
        self.assertFalse(src.exists())

    def test_apply_duplicate_identical_file_is_soft_deleted(self) -> None:
        src = self.root / "Movie source"
        dst = self.root / "Movie (2020)"
        dst.mkdir(parents=True, exist_ok=True)
        self._write(src / "movie.mkv", b"SAME-CONTENT")
        self._write(dst / "movie.mkv", b"SAME-CONTENT")

        row = self._single_row("S|2", src, "Movie", 2020)
        decisions = {"S|2": {"ok": True, "title": "Movie", "year": 2020}}

        result = apply_core.apply_rows(
            self._cfg(),
            [row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertEqual(result.duplicates_identical_moved_count, 1)
        self.assertEqual(result.duplicates_identical_deleted_count, 1)
        self.assertFalse((src / "movie.mkv").exists())
        self.assertTrue((dst / "movie.mkv").exists())
        moved = (
            self.run_review_root / "_duplicates_identical" / "Movie (2020)" / "__from__" / "Movie source" / "movie.mkv"
        )
        self.assertTrue(moved.exists(), f"Fichier identique attendu dans {moved}")
        self.assertEqual(moved.read_bytes(), b"SAME-CONTENT")
        self.assertTrue(
            any("DUPLICATE_IDENTICAL moved to _review/_duplicates_identical" in msg for _, msg in self.logs)
        )

    def test_apply_collision_quarantines_instead_of_overwrite(self) -> None:
        src = self.root / "Movie source"
        dst = self.root / "Movie (2020)"
        dst.mkdir(parents=True, exist_ok=True)
        self._write(src / "movie.mkv", b"AAAA")
        self._write(dst / "movie.mkv", b"BBBB")

        row = self._single_row("S|3", src, "Movie", 2020)
        decisions = {"S|3": {"ok": True, "title": "Movie", "year": 2020}}

        result = apply_core.apply_rows(
            self._cfg(),
            [row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertGreaterEqual(result.conflicts_quarantined_count, 1)
        self.assertEqual((dst / "movie.mkv").read_bytes(), b"BBBB")
        conflict_file = self.run_review_root / "_conflicts" / "Movie (2020)" / "__from__" / "Movie source" / "movie.mkv"
        self.assertTrue(conflict_file.exists(), f"Conflit attendu: {conflict_file}")
        self.assertTrue(any("CONFLICT" in msg for _, msg in self.logs))

    def test_apply_merge_leftovers_go_to_leftovers_folder(self) -> None:
        src = self.root / "Movie source"
        dst = self.root / "Movie (2020)"
        dst.mkdir(parents=True, exist_ok=True)
        self._write(src / "movie.mkv", b"A" * 1024)
        self._write(src / "sample.txt", b"leftover")

        row = self._single_row("S|4", src, "Movie", 2020)
        decisions = {"S|4": {"ok": True, "title": "Movie", "year": 2020}}

        result = apply_core.apply_rows(
            self._cfg(),
            [row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertTrue((dst / "movie.mkv").exists())
        leftovers = list((self.run_review_root / "_leftovers" / src.name).rglob("sample.txt"))
        self.assertTrue(leftovers, "Leftovers attendus sous _leftovers/<src_dir_name>/")
        self.assertGreaterEqual(result.leftovers_moved_count, 1)
        self.assertTrue(any("LEFTOVERS moved" in msg for _, msg in self.logs))

    def test_collection_folder_exists_merge_recursive(self) -> None:
        src_collection = self.root / "Saga Source"
        dst_collection = self.root / "_Collection" / "Saga Source"
        dst_collection.mkdir(parents=True, exist_ok=True)
        self._write(src_collection / "MovieA.2001.mkv", b"MOVIEA")
        self._write(src_collection / "Sub" / "cover.jpg", b"IMG")

        row = self._collection_row("C|1", src_collection, "MovieA.2001.mkv", "Movie A", 2001)
        decisions = {"C|1": {"ok": True, "title": "Movie A", "year": 2001}}

        result = apply_core.apply_rows(
            self._cfg(),
            [row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertGreaterEqual(result.collection_moves, 1)
        self.assertTrue((dst_collection / "Sub" / "cover.jpg").exists())
        self.assertTrue((dst_collection / "Movie A (2001)" / "MovieA.2001.mkv").exists())
        self.assertFalse(src_collection.exists())

    def test_collection_sidecar_dedup_avoids_redundant_operations_in_dry_run(self) -> None:
        folder = self.root / "Saga source"
        self._write(folder / "movie.mkv", b"VIDEO")
        self._write(folder / "movie.nfo", b"<movie></movie>")

        row1 = self._collection_row("C|dedup1", folder, "movie.mkv", "Movie", 2020)
        row2 = self._collection_row("C|dedup2", folder, "movie.mkv", "Movie", 2020)
        decisions = {
            "C|dedup1": {"ok": True, "title": "Movie", "year": 2020},
            "C|dedup2": {"ok": True, "title": "Movie", "year": 2020},
        }

        result = apply_core.apply_rows(
            self._cfg(),
            [row1, row2],
            decisions,
            dry_run=True,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        sidecar_moves = [msg for _, msg in self.logs if "MOVE:" in msg and "movie.nfo" in msg]
        self.assertEqual(len(sidecar_moves), 1, self.logs)
        self.assertTrue(
            any("SKIP_DEDUP collection_sidecar" in msg for _, msg in self.logs),
            "Un skip dedup sidecar doit etre journalise",
        )
        self.assertGreaterEqual(result.skip_reasons.get(core.SKIP_REASON_MERGED, 0), 1)

    def test_sidecar_conflict_kept_both_does_not_block_merge(self) -> None:
        src = self.root / "Movie source"
        dst = self.root / "Movie (2020)"
        dst.mkdir(parents=True, exist_ok=True)
        self._write(src / "movie.mkv", b"VIDEO-SRC")
        self._write(src / "movie.nfo", b"<movie><title>src</title></movie>")
        self._write(dst / "movie.nfo", b"<movie><title>dst</title></movie>")

        row = self._single_row("S|6", src, "Movie", 2020)
        decisions = {"S|6": {"ok": True, "title": "Movie", "year": 2020}}

        result = apply_core.apply_rows(
            self._cfg(),
            [row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertEqual(result.sidecar_conflicts_kept_both_count, 1)
        self.assertEqual(result.conflicts_sidecars_quarantined_count, 1)
        self.assertTrue((dst / "movie.mkv").exists())
        self.assertEqual((dst / "movie.nfo").read_bytes(), b"<movie><title>dst</title></movie>")
        sidecars = list(
            (self.run_review_root / "_conflicts_sidecars" / "Movie (2020)" / "__from__" / "Movie source").glob(
                "movie.incoming_*.nfo"
            )
        )
        self.assertTrue(sidecars, "Le NFO source doit etre conserve dans _conflicts_sidecars")
        self.assertFalse(src.exists(), "Le dossier source doit etre supprime apres merge si vide")
        self.assertTrue(any("SIDECAR CONFLICT kept both" in msg for _, msg in self.logs))

    def test_conflict_paths_are_unique(self) -> None:
        dst = self.root / "Movie (2020)"
        dst.mkdir(parents=True, exist_ok=True)
        self._write(dst / "movie.mkv", b"DST")

        src1 = self.root / "Movie source A"
        src2 = self.root / "Movie source B"
        self._write(src1 / "movie.mkv", b"AAA")
        self._write(src2 / "movie.mkv", b"BBB")

        row1 = self._single_row("S|7", src1, "Movie", 2020)
        row2 = self._single_row("S|8", src2, "Movie", 2020)
        decisions = {
            "S|7": {"ok": True, "title": "Movie", "year": 2020},
            "S|8": {"ok": True, "title": "Movie", "year": 2020},
        }

        result = apply_core.apply_rows(
            self._cfg(),
            [row1, row2],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertGreaterEqual(result.conflicts_quarantined_count, 2)
        c1 = self.run_review_root / "_conflicts" / "Movie (2020)" / "__from__" / "Movie source A" / "movie.mkv"
        c2 = self.run_review_root / "_conflicts" / "Movie (2020)" / "__from__" / "Movie source B" / "movie.mkv"
        self.assertTrue(c1.exists(), f"Conflit attendu: {c1}")
        self.assertTrue(c2.exists(), f"Conflit attendu: {c2}")
        self.assertNotEqual(c1.resolve(), c2.resolve())

    def test_check_duplicates_marks_mergeable_not_blocking(self) -> None:
        src = self.root / "Movie source"
        dst = self.root / "Movie (2020)"
        src.mkdir(parents=True, exist_ok=True)
        dst.mkdir(parents=True, exist_ok=True)
        self._write(src / "movie.mkv", b"A")

        row = self._single_row("S|5", src, "Movie", 2020)
        decisions = {"S|5": {"ok": True, "title": "Movie", "year": 2020}}

        # Cf #83 PR 4b : find_duplicate_targets vit cote app maintenant.
        dup = plan_support.find_duplicate_targets(self._cfg(), [row], decisions)
        self.assertEqual(dup["checked_rows"], 1)
        self.assertEqual(dup["total_groups"], 0)
        self.assertGreaterEqual(dup.get("mergeable_count", 0), 1)
        mergeables = dup.get("mergeables") or []
        self.assertTrue(mergeables)
        self.assertTrue(mergeables[0].get("mergeable"))
        self.assertEqual(mergeables[0].get("kind"), "mergeable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
