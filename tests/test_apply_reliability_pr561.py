"""Regressions PR#561 — 3 gardes de fiabilite sur le chemin destructif de l'apply.

Ces tests couvrent les 3 correctifs CONSERVES de la PR (le 4e, sur
`disk_space_check.estimate_apply_size`, a ete retire : il transformait un
sur-comptage fail-SAFE en sous-comptage fail-OPEN) :

1. `cleanup._move_dirs_to_bucket` : `moved += 1` doit etre SOUS `if not dry_run:`.
   Sans ca, la preview (dry_run) annonce a l'utilisateur des dossiers deplaces
   qui ne l'ont pas ete — jusque dans le rapport final
   (`ui/api/apply_support.py`, lignes "Dossiers vides deplaces (_Vide)" /
   "Dossiers residuels deplaces (_Dossier Nettoyage)") et dans les
   "action_lines" qui pointent alors un dossier `_Vide` inexistant.

2. `apply_core.apply_tv_episode` : garde `row.video` vide. `folder / ""` vaut
   `folder`, donc `.exists()` est True et le chemin "video manquante" ne se
   declenche pas ; `move_file_with_collision_policy` ne teste jamais
   `src.is_file()` -> le DOSSIER COMPLET partait vers
   `Saison NN/SxxExx - Titre.ext`.

3. `apply_core.quarantine_row` : `folder.iterdir()` sans try/except tuait tout
   le batch de quarantaine (rows suivantes perdues) sur un dossier disparu
   (move concurrent) ou un acces refuse.
"""

from __future__ import annotations

import shutil
import tempfile
import unicodedata
import unittest
import unittest.mock
from pathlib import Path
from typing import Any, List, Tuple

import cinesort.app.apply_core as apply_core
import cinesort.app.cleanup as cleanup
import cinesort.domain.core as core


class _ApplyReliabilityBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="pr561_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.run_review_root = self.state_dir / "runs" / "run_pr561" / "_review"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.logs: List[Tuple[str, str]] = []

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _log(self, level: str, msg: str) -> None:
        self.logs.append((level, msg))

    def _write(self, path: Path, data: bytes = b"x") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class CleanupDryRunCounterTests(_ApplyReliabilityBase):
    """Correctif UNIQUE de la PR : le compteur de moves ment en dry_run."""

    def _cfg_cleanup(self) -> Any:
        return core.Config(
            root=self.root,
            move_empty_folders_enabled=True,
            empty_folders_folder_name="_Vide",
            empty_folders_scope="root_all",
            cleanup_residual_folders_enabled=True,
            cleanup_residual_folders_folder_name="_Dossier Nettoyage",
            cleanup_residual_folders_scope="root_all",
        ).normalized()

    def test_move_dirs_to_bucket_ne_compte_rien_en_dry_run(self) -> None:
        """Contrat de la docstring : "0 si dry_run ou aucun eligible".

        PR#852 a rendu `res`/`counter_attr` obligatoires (le compteur est
        desormais incremente dossier par dossier DANS la fonction, plus par un
        `+=` du caller). Le contrat dry_run vaut donc pour les DEUX compteurs :
        la valeur de retour ET l'attribut de `res`, qui est celui reellement
        remonte a l'UI.
        """
        src = self.root / "EmptyA"
        src.mkdir(parents=True, exist_ok=True)
        bucket = self.root / "_Vide"
        res = core.ApplyResult()

        moved = cleanup._move_dirs_to_bucket(
            candidates=[src],
            bucket_root=bucket,
            is_eligible=lambda _p: True,
            dry_run=True,
            log=self._log,
            log_prefix="TEST",
            res=res,
            counter_attr="empty_folders_moved_count",
        )

        self.assertEqual(moved, 0, "dry_run ne deplace rien : le compteur doit rester a 0")
        self.assertEqual(
            res.empty_folders_moved_count,
            0,
            "dry_run : le compteur expose a l'UI ne doit pas bouger non plus",
        )
        self.assertTrue(src.exists(), "dry_run ne doit RIEN deplacer sur le disque")
        self.assertFalse(bucket.exists())

    def test_move_dirs_to_bucket_compte_les_moves_reels(self) -> None:
        """Garde-fou anti sur-correction : hors dry_run le compteur doit bouger."""
        src = self.root / "EmptyB"
        src.mkdir(parents=True, exist_ok=True)
        bucket = self.root / "_Vide"
        res = core.ApplyResult()

        moved = cleanup._move_dirs_to_bucket(
            candidates=[src],
            bucket_root=bucket,
            is_eligible=lambda _p: True,
            dry_run=False,
            log=self._log,
            log_prefix="TEST",
            res=res,
            counter_attr="empty_folders_moved_count",
        )

        self.assertEqual(moved, 1)
        self.assertEqual(res.empty_folders_moved_count, 1)
        self.assertFalse(src.exists())
        self.assertTrue((bucket / "EmptyB").exists())

    def test_apply_rows_dry_run_ne_gonfle_pas_les_compteurs_exposes_a_l_ui(self) -> None:
        """Bout-en-bout : les 2 compteurs remontes dans le rapport apply restent a 0."""
        empty_dir = self.root / "EmptyA"
        empty_dir.mkdir(parents=True, exist_ok=True)
        residue = self.root / "ResiduelA"
        self._write(residue / "movie.nfo", b"<movie></movie>")
        self._write(residue / "poster.jpg", b"img")

        result = apply_core.apply_rows(
            self._cfg_cleanup(),
            [],
            {},
            dry_run=True,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertEqual(
            result.empty_folders_moved_count,
            0,
            "dry_run : apply_support.py annonce sinon des dossiers deplaces vers _Vide qui ne l'ont pas ete",
        )
        self.assertEqual(
            result.cleanup_residual_folders_moved_count,
            0,
            "dry_run : le rapport annonce sinon des dossiers residuels deplaces fantomes",
        )
        # Rien n'a bouge sur le disque : la preview et les compteurs concordent.
        self.assertTrue(empty_dir.exists())
        self.assertTrue(residue.exists())
        self.assertFalse((self.root / "_Vide").exists())
        self.assertFalse((self.root / "_Dossier Nettoyage").exists())

    def test_apply_rows_reel_compte_bien_les_moves(self) -> None:
        """Meme scenario hors dry_run : les compteurs doivent etre a 1 (anti sur-correction)."""
        empty_dir = self.root / "EmptyA"
        empty_dir.mkdir(parents=True, exist_ok=True)
        residue = self.root / "ResiduelA"
        self._write(residue / "movie.nfo", b"<movie></movie>")
        self._write(residue / "poster.jpg", b"img")

        result = apply_core.apply_rows(
            self._cfg_cleanup(),
            [],
            {},
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0)
        self.assertEqual(result.empty_folders_moved_count, 1)
        self.assertEqual(result.cleanup_residual_folders_moved_count, 1)


class TvEpisodeEmptyVideoGuardTests(_ApplyReliabilityBase):
    """Le dossier COMPLET partait vers un nom de fichier video si row.video == ""."""

    def _tv_row(self, folder: Path, video: str) -> core.PlanRow:
        return core.PlanRow(
            row_id="TV|empty",
            kind="tv_episode",
            folder=str(folder),
            video=video,
            proposed_title="Ma Serie",
            proposed_year=2020,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[core.Candidate(title="Ma Serie", year=2020, source="name", score=0.7)],
            tv_series_name="Ma Serie",
            tv_season=1,
            tv_episode=1,
            tv_episode_title="Pilote",
        )

    def test_folder_slash_empty_string_vaut_le_folder(self) -> None:
        """Premisse du bug : `folder / ""` == folder, donc `.exists()` est True."""
        folder = self.root / "Ma Serie S01"
        folder.mkdir(parents=True, exist_ok=True)
        self.assertEqual(folder / "", folder)
        self.assertTrue((folder / "").exists())

    def test_video_vide_ne_deplace_pas_le_dossier(self) -> None:
        folder = self.root / "Ma Serie S01"
        self._write(folder / "Ma.Serie.S01E01.mkv", b"video")
        self._write(folder / "Ma.Serie.S01E02.mkv", b"video2")

        cfg = core.Config(root=self.root).normalized()
        res = core.ApplyResult()

        apply_core.apply_tv_episode(
            cfg,
            folder,
            self._tv_row(folder, ""),
            False,
            self._log,
            res,
            conflicts_root=self.run_review_root / "_conflicts",
            conflicts_sidecars_root=self.run_review_root / "_conflicts_sidecars",
            duplicates_identical_root=self.run_review_root / "_duplicates_identical",
        )

        # Le dossier et SES DEUX videos (dont l'episode non concerne) sont intacts.
        self.assertTrue(folder.is_dir(), "le dossier source ne doit pas avoir ete deplace")
        self.assertTrue((folder / "Ma.Serie.S01E01.mkv").exists())
        self.assertTrue((folder / "Ma.Serie.S01E02.mkv").exists())
        # Aucune arborescence Serie (annee)/Saison NN/ n'a ete creee.
        self.assertFalse(
            any(p.name.startswith("Saison") for p in self.root.rglob("*") if p.is_dir()),
            "aucun dossier Saison NN ne doit avoir ete cree",
        )
        # La row est comptee comme skippee, pas comme un move.
        self.assertEqual(res.moves, 0)
        self.assertEqual(res.skipped, 1)
        self.assertEqual(res.skip_reasons.get(core.SKIP_REASON_AUTRE), 1)

    def test_iterdir_qui_leve_est_loggue_avec_sa_cause(self) -> None:
        """Revue PR#561 (sourcery-ai) : un echec FS ne doit pas se lire comme une video absente.

        Le skip est identique dans les deux cas ; seul le log distingue « le
        share ne repond pas » de « le fichier n'est pas la ». Sans cette trace,
        l'utilisateur cherche un fichier qui est en fait sur le disque.
        """
        folder = self.root / "Ma Serie S01"
        self._write(folder / "Ma.Serie.S01E01.mkv", b"video")

        cfg = core.Config(root=self.root).normalized()
        res = core.ApplyResult()
        real_iterdir = Path.iterdir

        def _boom(self_path: Path):  # type: ignore[no-untyped-def]
            if self_path == folder:
                raise PermissionError(13, "Access is denied")
            return real_iterdir(self_path)

        with unittest.mock.patch.object(Path, "iterdir", _boom):
            apply_core.apply_tv_episode(
                cfg,
                folder,
                self._tv_row(folder, "introuvable.mkv"),
                False,
                self._log,
                res,
                conflicts_root=self.run_review_root / "_conflicts",
                conflicts_sidecars_root=self.run_review_root / "_conflicts_sidecars",
                duplicates_identical_root=self.run_review_root / "_duplicates_identical",
            )

        self.assertEqual(res.skipped, 1)
        causes = [msg for level, msg in self.logs if level == "WARN" and "PermissionError" in msg]
        self.assertTrue(
            causes,
            f"l'echec d'enumeration doit etre trace avec sa cause ; logs={self.logs}",
        )
        self.assertTrue(
            any(str(folder) in msg for msg in causes),
            f"le log doit nommer le dossier fautif ; logs={self.logs}",
        )

    def test_video_presente_est_toujours_traitee(self) -> None:
        """Anti sur-correction : la garde ne doit pas bloquer un episode valide."""
        folder = self.root / "Ma Serie S01"
        self._write(folder / "Ma.Serie.S01E01.mkv", b"video")

        cfg = core.Config(root=self.root).normalized()
        res = core.ApplyResult()

        apply_core.apply_tv_episode(
            cfg,
            folder,
            self._tv_row(folder, "Ma.Serie.S01E01.mkv"),
            False,
            self._log,
            res,
            conflicts_root=self.run_review_root / "_conflicts",
            conflicts_sidecars_root=self.run_review_root / "_conflicts_sidecars",
            duplicates_identical_root=self.run_review_root / "_duplicates_identical",
        )

        moved = list(self.root.rglob("S01E01 - Pilote.mkv"))
        self.assertEqual(len(moved), 1, f"l'episode valide doit etre range ; arbo={list(self.root.rglob('*'))}")
        self.assertEqual(res.skip_reasons.get(core.SKIP_REASON_AUTRE, 0), 0)


class QuarantineRowIterdirGuardTests(_ApplyReliabilityBase):
    """Un iterdir() qui leve tuait tout le batch de quarantaine."""

    def _coll_row(self, folder: Path, video: str) -> core.PlanRow:
        return core.PlanRow(
            row_id="C|q",
            kind="collection",
            folder=str(folder),
            video=video,
            proposed_title="Film",
            proposed_year=2020,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[core.Candidate(title="Film", year=2020, source="name", score=0.7)],
            collection_name=folder.name,
        )

    def _quarantine(self, folder: Path, row: core.PlanRow, res: core.ApplyResult) -> None:
        cfg = core.Config(root=self.root).normalized()
        apply_core.quarantine_row(
            cfg,
            folder,
            row,
            False,
            self._log,
            res,
            self.root / "_review",  # ensure_inside_root exige un review_root sous cfg.root
        )

    def test_iterdir_permission_denied_ne_tue_pas_le_batch(self) -> None:
        folder = self.root / "Saga"
        self._write(folder / "autre.mkv", b"video")
        row = self._coll_row(folder, "introuvable.mkv")
        res = core.ApplyResult()

        real_iterdir = Path.iterdir

        def _boom(self_path: Path):  # type: ignore[no-untyped-def]
            if self_path == folder:
                raise PermissionError(13, "Access is denied")
            return real_iterdir(self_path)

        with unittest.mock.patch.object(Path, "iterdir", _boom):
            self._quarantine(folder, row, res)

        # Pas de remontee d'exception : la row est simplement skippee.
        self.assertEqual(res.skipped, 1)
        self.assertEqual(res.skip_reasons.get(core.SKIP_REASON_AUTRE), 1)
        self.assertEqual(res.quarantined, 0)
        # Revue PR#561 (sourcery-ai) : ce chemin skippait SANS aucun log. Un
        # share tombe en plein batch de quarantaine se lisait alors comme une
        # bibliotheque vide.
        causes = [msg for level, msg in self.logs if level == "WARN" and "PermissionError" in msg]
        self.assertTrue(causes, f"l'echec d'enumeration doit etre trace avec sa cause ; logs={self.logs}")
        self.assertTrue(
            any(str(folder) in msg for msg in causes),
            f"le log doit nommer le dossier fautif ; logs={self.logs}",
        )

    def test_iterdir_folder_disparu_ne_tue_pas_le_batch(self) -> None:
        """TOCTOU : le dossier existe au check d'entree puis disparait (move concurrent)."""
        folder = self.root / "Saga"
        self._write(folder / "autre.mkv", b"video")
        row = self._coll_row(folder, "introuvable.mkv")
        res = core.ApplyResult()

        real_iterdir = Path.iterdir

        def _gone(self_path: Path):  # type: ignore[no-untyped-def]
            if self_path == folder:
                raise FileNotFoundError(2, "No such file or directory")
            return real_iterdir(self_path)

        with unittest.mock.patch.object(Path, "iterdir", _gone):
            self._quarantine(folder, row, res)

        self.assertEqual(res.skipped, 1)
        self.assertEqual(res.quarantined, 0)

    def test_resolution_par_iterdir_toujours_active(self) -> None:
        """Anti sur-correction : le try/except ne doit pas neutraliser la resolution _name_eq_fs.

        On utilise un ecart NFC/NFD (scan SMB macOS) que NTFS ne replie PAS,
        contrairement a une simple difference de casse : seul le fallback
        `iterdir()` + `_name_eq_fs` peut retrouver le fichier.
        """
        folder = self.root / "Saga"
        on_disk = unicodedata.normalize("NFC", "Café.2020.mkv")
        in_plan = unicodedata.normalize("NFD", "Café.2020.mkv")
        self.assertNotEqual(on_disk, in_plan, "le fixture doit vraiment differer en octets")
        self._write(folder / on_disk, b"video")
        self.assertFalse((folder / in_plan).exists(), "le chemin direct doit echouer, sinon le test ne prouve rien")

        row = self._coll_row(folder, in_plan)
        res = core.ApplyResult()

        self._quarantine(folder, row, res)

        self.assertEqual(res.quarantined, 1, "le fichier doit etre retrouve via iterdir + _name_eq_fs")
        self.assertEqual(res.skipped, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
