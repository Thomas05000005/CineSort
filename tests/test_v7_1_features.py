from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend
import cinesort.app.apply_core as apply_core
import cinesort.domain.core as core
from cinesort.app.apply_core import build_apply_context


class V71FeaturesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="v71_features_")
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

    def _write(self, path: Path, data: bytes = b"x") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

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

    def test_collection_folder_name_defaults_to__Collection(self) -> None:
        api = backend.CineSortApi()
        api._state_dir = self.state_dir / "defaults_v71"  # type: ignore[attr-defined]
        settings = api.settings.get_settings()

        self.assertEqual(settings.get("collection_folder_name"), "_Collection")
        self.assertEqual(settings.get("empty_folders_folder_name"), "_Vide")
        self.assertEqual(bool(settings.get("move_empty_folders_enabled")), False)
        self.assertEqual(settings.get("empty_folders_scope"), "root_all")
        self.assertEqual(settings.get("cleanup_residual_folders_folder_name"), "_Dossier Nettoyage")
        self.assertEqual(bool(settings.get("cleanup_residual_folders_enabled")), False)
        self.assertEqual(settings.get("cleanup_residual_folders_scope"), "touched_only")
        self.assertEqual(bool(settings.get("cleanup_residual_include_nfo")), True)
        self.assertEqual(bool(settings.get("cleanup_residual_include_images")), True)
        self.assertEqual(bool(settings.get("cleanup_residual_include_subtitles")), True)
        self.assertEqual(bool(settings.get("cleanup_residual_include_texts")), True)

    def test_migrate_Collection_to__Collection(self) -> None:
        legacy_movie = self.root / "Collection" / "Saga Source" / "MovieA.2001.mkv"
        self._write(legacy_movie, b"MOVIEA")

        row = self._collection_row("C|v71", legacy_movie.parent, "MovieA.2001.mkv", "Movie A", 2001)
        decisions = {"C|v71": {"ok": True, "title": "Movie A", "year": 2001}}

        cfg = core.Config(
            root=self.root,
            enable_collection_folder=True,
            collection_root_name="_Collection",
        ).normalized()

        result = apply_core.apply_rows(
            cfg,
            [row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertFalse((self.root / "Collection").exists(), "Le dossier legacy Collection doit etre migre")
        self.assertTrue((self.root / "_Collection").exists())
        self.assertTrue((self.root / "_Collection" / "Saga Source" / "Movie A (2001)" / "MovieA.2001.mkv").exists())

    def test_move_empty_folders_root_all_moves_only_empty_top_level(self) -> None:
        (self.root / "EmptyA").mkdir(parents=True, exist_ok=True)
        self._write(self.root / "NonEmpty" / "keep.txt", b"keep")
        (self.root / "HasSub" / "child").mkdir(parents=True, exist_ok=True)

        cfg = core.Config(
            root=self.root,
            collection_root_name="_Collection",
            move_empty_folders_enabled=True,
            empty_folders_folder_name="_Vide",
            empty_folders_scope="root_all",
        ).normalized()

        result = apply_core.apply_rows(
            cfg,
            [],
            {},
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertEqual(result.empty_folders_moved_count, 1)
        self.assertFalse((self.root / "EmptyA").exists())
        self.assertTrue((self.root / "_Vide" / "EmptyA").exists())
        self.assertTrue((self.root / "NonEmpty").exists())
        self.assertTrue((self.root / "HasSub").exists())
        self.assertFalse((self.root / "_Vide" / "HasSub").exists())

    def test_empty_folders_scope_touched_only(self) -> None:
        (self.root / "PreExistingEmpty").mkdir(parents=True, exist_ok=True)
        touched = self.root / "Film Conforme (2020)"
        self._write(touched / "Film.Conforme.2020.mkv", b"video")

        row = self._single_row("S|touched", touched, "Film Conforme", 2020, video="Film.Conforme.2020.mkv")
        decisions = {"S|touched": {"ok": True, "title": "Film Conforme", "year": 2020}}

        cfg = core.Config(
            root=self.root,
            move_empty_folders_enabled=True,
            empty_folders_folder_name="_Vide",
            empty_folders_scope="touched_only",
        ).normalized()

        result = apply_core.apply_rows(
            cfg,
            [row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertEqual(result.empty_folders_moved_count, 0)
        self.assertTrue(
            (self.root / "PreExistingEmpty").exists(), "Les dossiers vides pre-existants ne doivent pas bouger"
        )
        self.assertFalse((self.root / "_Vide" / "PreExistingEmpty").exists())

    def test_cleanup_residual_folders_root_all_moves_sidecar_only_dir(self) -> None:
        residue = self.root / "ResiduelA"
        self._write(residue / "movie.nfo", b"<movie></movie>")
        self._write(residue / "poster.jpg", b"img")
        self._write(residue / "notes.txt", b"note")

        cfg = core.Config(
            root=self.root,
            cleanup_residual_folders_enabled=True,
            cleanup_residual_folders_folder_name="_Dossier Nettoyage",
            cleanup_residual_folders_scope="root_all",
        ).normalized()

        result = apply_core.apply_rows(
            cfg,
            [],
            {},
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertEqual(result.cleanup_residual_folders_moved_count, 1)
        self.assertFalse(residue.exists())
        self.assertTrue((self.root / "_Dossier Nettoyage" / "ResiduelA" / "movie.nfo").exists())
        self.assertTrue((self.root / "_Dossier Nettoyage" / "ResiduelA" / "poster.jpg").exists())

    def test_cleanup_residual_folders_skips_dir_with_video(self) -> None:
        keep = self.root / "HasVideo"
        self._write(keep / "movie.nfo", b"<movie></movie>")
        self._write(keep / "featurette.mkv", b"video")

        cfg = core.Config(
            root=self.root,
            cleanup_residual_folders_enabled=True,
            cleanup_residual_folders_folder_name="_Dossier Nettoyage",
            cleanup_residual_folders_scope="root_all",
        ).normalized()

        result = apply_core.apply_rows(
            cfg,
            [],
            {},
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertEqual(result.cleanup_residual_folders_moved_count, 0)
        self.assertTrue(keep.exists())
        self.assertFalse((self.root / "_Dossier Nettoyage" / "HasVideo").exists())

    def test_cleanup_residual_folders_skips_ambiguous_unknown_extension(self) -> None:
        keep = self.root / "Ambiguous"
        self._write(keep / "poster.jpg", b"img")
        self._write(keep / "manifest.bin", b"??")

        cfg = core.Config(
            root=self.root,
            cleanup_residual_folders_enabled=True,
            cleanup_residual_folders_folder_name="_Dossier Nettoyage",
            cleanup_residual_folders_scope="root_all",
        ).normalized()

        result = apply_core.apply_rows(
            cfg,
            [],
            {},
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertEqual(result.cleanup_residual_folders_moved_count, 0)
        self.assertTrue(keep.exists())
        self.assertFalse((self.root / "_Dossier Nettoyage" / "Ambiguous").exists())

    def test_cleanup_residual_folders_touched_only_skips_preexisting_noise(self) -> None:
        preexisting = self.root / "OldNoise"
        self._write(preexisting / "movie.nfo", b"<movie></movie>")

        touched = self.root / "Source"
        self._write(touched / "Source.2020.mkv", b"video")
        self._write(touched / "keep.txt", b"note")
        row = self._single_row("S|source", touched, "Source", 2020, video="Source.2020.mkv")
        decisions = {"S|source": {"ok": True, "title": "Source", "year": 2020}}

        cfg = core.Config(
            root=self.root,
            cleanup_residual_folders_enabled=True,
            cleanup_residual_folders_folder_name="_Dossier Nettoyage",
            cleanup_residual_folders_scope="touched_only",
        ).normalized()

        result = apply_core.apply_rows(
            cfg,
            [row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertEqual(result.cleanup_residual_folders_moved_count, 0)
        self.assertTrue(preexisting.exists())
        self.assertFalse((self.root / "_Dossier Nettoyage" / "OldNoise").exists())

    def test_noop_requires_year_in_folder_name_when_year_known(self) -> None:
        src = self.root / "Gravity"
        self._write(src / "Gravity.mkv", b"gravity")

        row = self._single_row("S|gravity", src, "Gravity", 2013, video="Gravity.mkv")
        decisions = {"S|gravity": {"ok": True, "title": "Gravity", "year": 2013}}

        cfg = core.Config(root=self.root, collection_root_name="_Collection").normalized()
        result = apply_core.apply_rows(
            cfg,
            [row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertEqual(result.renames, 1)
        self.assertFalse(src.exists())
        self.assertTrue((self.root / "Gravity (2013)").exists())

    def test_build_apply_context_prepares_roots_and_decision_keys(self) -> None:
        cfg = core.Config(root=self.root, collection_root_name="_Collection")
        row = self._single_row("S|ctx", self.root / "Source", "Film Test", 2021)

        # Issue #83 : migrer vers la vraie origine (app.apply_core.build_apply_context)
        # au lieu du re-export domain.core._build_apply_context.
        ctx = build_apply_context(
            cfg,
            [row],
            dry_run=False,
            quarantine_unapproved=True,
            run_review_root=self.run_review_root,
            decision_presence={"S|ctx", "S|other"},
        )

        self.assertEqual(ctx.cfg.collection_root_name, "_Collection")
        self.assertEqual(ctx.res.total_rows, 1)
        self.assertEqual(ctx.res.considered_rows, 1)
        self.assertEqual(ctx.decision_keys, {"S|ctx", "S|other"})
        self.assertTrue(ctx.review_root.exists())
        self.assertTrue(ctx.conflicts_root.exists())
        self.assertTrue(ctx.conflicts_sidecars_root.exists())
        self.assertTrue(ctx.duplicates_identical_root.exists())
        self.assertTrue(ctx.leftovers_root.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
