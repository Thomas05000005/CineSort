"""Non-regression AUDIT 2026-07-13 [CRIT-1] : granularite destructive inversee.

Bug : dans move_marked_for_deletion_to_bucket (apply_core) et
move_duplicate_losers_to_user_decided, la garde de granularite etait
`if row.kind == "collection" and video_name:` -> SEUL "collection" deplacait la
video + ses sidecars. Les kinds "extra" (video bonus d'un dossier multi-video,
plan_support_core.py:751) et "tv_episode" (folder = dossier serie/saison)
tombaient dans la branche "single" = atomic_move(MOVE_DIR) du DOSSIER ENTIER ->
le film principal / la serie entiere (fichiers JAMAIS selectionnes par
l'utilisateur) partaient dans `_review/_user_marked_for_deletion`, bucket que la
doc dit a l'utilisateur de vider lui-meme => perte definitive.

Fix : garde alignee sur la semantique DEJA correcte de quarantine_row
(apply_core.py:2526) -> dossier entier reserve au SEUL kind "single" ; tout le
reste = video + sidecars. Plus un garde-fou : kind != "single" sans video_name
-> WARN + skip (jamais MOVE_DIR).

Ces tests ECHOUENT avant le fix (le dossier partage entier disparait) et PASSENT
apres.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import List

import cinesort.app.apply_core as apply_core
import cinesort.domain.core as core


class _GranularityTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cs_crit1_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.bucket = Path(self._tmp) / "state" / "_review" / "_bucket"
        self.bucket.mkdir(parents=True, exist_ok=True)
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

    def _row(self, row_id: str, kind: str, folder: Path, video: str) -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id,
            kind=kind,
            folder=str(folder),
            video=video,
            proposed_title="Titre",
            proposed_year=2010,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[],
        )

    # --- fixtures disque ------------------------------------------------------

    def _make_bonus_folder(self) -> Path:
        """Dossier multi-video : film principal + video bonus (kind='extra')."""
        shared = self.root / "Star Wars"
        self._write(shared / "Star Wars.mkv")
        self._write(shared / "Star Wars.fr.srt", b"1\n")
        self._write(shared / "Making Of.mkv")
        self._write(shared / "Making Of.nfo", b"<m></m>")
        return shared

    def _make_series_folder(self) -> Path:
        """Dossier serie : 3 episodes (kind='tv_episode')."""
        season = self.root / "Breaking Bad S01"
        self._write(season / "Breaking Bad S01E01.mkv")
        self._write(season / "Breaking Bad S01E02.mkv")
        self._write(season / "Breaking Bad S01E03.mkv")
        return season

    def _move_ops(self) -> List[dict]:
        return [op for op in self.ops if op.get("op_type") == "MOVE_DIR"]


class MarkedForDeletionGranularityTests(_GranularityTestBase):
    """move_marked_for_deletion_to_bucket : bucket vide par l'utilisateur -> critique."""

    def _run(self, rows: List[core.PlanRow], marked: set) -> core.ApplyResult:
        res = core.ApplyResult()
        apply_core.move_marked_for_deletion_to_bucket(
            self._cfg(),
            rows,
            marked,
            marked_for_deletion_root=self.bucket,
            dry_run=False,
            log=self._log,
            res=res,
            record_op=self._record_op,
        )
        return res

    def test_extra_bonus_video_does_not_take_the_main_movie(self) -> None:
        shared = self._make_bonus_folder()
        row = self._row("R_EXTRA", "extra", shared, "Making Of.mkv")

        self._run([row], {"R_EXTRA"})

        # Le film principal et son sous-titre NE DOIVENT PAS avoir bouge.
        self.assertTrue(
            (shared / "Star Wars.mkv").exists(),
            msg="PERTE DE FICHIERS : le film principal a ete emporte par le bonus marque",
        )
        self.assertTrue((shared / "Star Wars.fr.srt").exists())
        # Le bonus (+ son sidecar) est parti dans le bucket.
        self.assertFalse((shared / "Making Of.mkv").exists())
        moved = {p.name for p in self.bucket.rglob("*") if p.is_file()}
        self.assertIn("Making Of.mkv", moved)
        self.assertIn("Making Of.nfo", moved)
        self.assertNotIn("Star Wars.mkv", moved)
        # Aucun deplacement de dossier ne doit avoir ete journalise.
        self.assertEqual(self._move_ops(), [], msg="MOVE_DIR interdit pour un kind='extra'")

    def test_tv_episode_does_not_take_the_whole_series(self) -> None:
        season = self._make_series_folder()
        row = self._row("R_EP2", "tv_episode", season, "Breaking Bad S01E02.mkv")

        self._run([row], {"R_EP2"})

        self.assertTrue(
            (season / "Breaking Bad S01E01.mkv").exists(),
            msg="PERTE DE FICHIERS : la serie entiere a ete emportee par l'episode marque",
        )
        self.assertTrue((season / "Breaking Bad S01E03.mkv").exists())
        self.assertFalse((season / "Breaking Bad S01E02.mkv").exists())
        moved = {p.name for p in self.bucket.rglob("*") if p.is_file()}
        self.assertEqual(moved, {"Breaking Bad S01E02.mkv"})
        self.assertEqual(self._move_ops(), [], msg="MOVE_DIR interdit pour un kind='tv_episode'")

    def test_non_single_without_video_is_skipped_with_warn(self) -> None:
        """Garde-fou : row corrompue (kind non-single, video vide) -> WARN + skip."""
        shared = self._make_bonus_folder()
        row = self._row("R_CORRUPT", "extra", shared, "")

        self._run([row], {"R_CORRUPT"})

        # Rien ne bouge, surtout pas le dossier entier.
        self.assertTrue((shared / "Star Wars.mkv").exists())
        self.assertTrue((shared / "Making Of.mkv").exists())
        self.assertEqual([p for p in self.bucket.rglob("*") if p.is_file()], [])
        self.assertEqual(self._move_ops(), [])
        warns = [msg for lvl, msg in self.logs if lvl == "WARN"]
        self.assertTrue(
            any("R_CORRUPT" in msg for msg in warns),
            msg=f"un WARN doit signaler la row corrompue ; logs={self.logs}",
        )

    def test_single_still_moves_the_whole_folder(self) -> None:
        """Non-regression : le kind 'single' garde bien la semantique dossier entier."""
        folder = self.root / "Inception (2010)"
        self._write(folder / "movie.mkv")
        self._write(folder / "movie.nfo", b"<m></m>")
        row = self._row("R_SINGLE", "single", folder, "movie.mkv")

        res = self._run([row], {"R_SINGLE"})

        self.assertFalse(folder.exists())
        moved = self.bucket / "Inception (2010)"
        self.assertTrue((moved / "movie.mkv").exists())
        self.assertTrue((moved / "movie.nfo").exists())
        self.assertEqual(len(self._move_ops()), 1)
        self.assertEqual(res.marked_for_deletion_moved_count, 1)


class DuplicateLoserGranularityTests(_GranularityTestBase):
    """move_duplicate_losers_to_user_decided : meme garde inversee."""

    def _run(self, rows: List[core.PlanRow], losers: set) -> core.ApplyResult:
        res = core.ApplyResult()
        apply_core.move_duplicate_losers_to_user_decided(
            self._cfg(),
            rows,
            losers,
            duplicates_user_decided_root=self.bucket,
            dry_run=False,
            log=self._log,
            res=res,
            record_op=self._record_op,
        )
        return res

    def test_extra_loser_does_not_take_the_main_movie(self) -> None:
        shared = self._make_bonus_folder()
        row = self._row("R_EXTRA", "extra", shared, "Making Of.mkv")

        self._run([row], {"R_EXTRA"})

        self.assertTrue(
            (shared / "Star Wars.mkv").exists(),
            msg="PERTE DE FICHIERS : le film principal a ete emporte par le bonus loser",
        )
        self.assertFalse((shared / "Making Of.mkv").exists())
        self.assertEqual(self._move_ops(), [])

    def test_tv_episode_loser_does_not_take_the_whole_series(self) -> None:
        season = self._make_series_folder()
        row = self._row("R_EP2", "tv_episode", season, "Breaking Bad S01E02.mkv")

        self._run([row], {"R_EP2"})

        self.assertTrue((season / "Breaking Bad S01E01.mkv").exists())
        self.assertTrue((season / "Breaking Bad S01E03.mkv").exists())
        self.assertFalse((season / "Breaking Bad S01E02.mkv").exists())
        self.assertEqual(self._move_ops(), [])

    def test_non_single_without_video_is_skipped_with_warn(self) -> None:
        season = self._make_series_folder()
        row = self._row("R_CORRUPT", "tv_episode", season, "")

        self._run([row], {"R_CORRUPT"})

        self.assertTrue((season / "Breaking Bad S01E01.mkv").exists())
        self.assertEqual(self._move_ops(), [])
        warns = [msg for lvl, msg in self.logs if lvl == "WARN"]
        self.assertTrue(any("R_CORRUPT" in msg for msg in warns))

    def test_single_loser_still_moves_the_whole_folder(self) -> None:
        folder = self.root / "F&F4 720p"
        self._write(folder / "movie.mkv")
        row = self._row("R_SINGLE", "single", folder, "movie.mkv")

        res = self._run([row], {"R_SINGLE"})

        self.assertFalse(folder.exists())
        self.assertTrue((self.bucket / "F&F4 720p" / "movie.mkv").exists())
        self.assertEqual(len(self._move_ops()), 1)
        self.assertEqual(res.duplicates_user_decided_moved_count, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
