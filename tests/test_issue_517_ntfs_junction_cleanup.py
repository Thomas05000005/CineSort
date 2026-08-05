"""Issue #517 — les jonctions NTFS etaient TRAVERSEES sur le chemin destructif `_Nettoyage`.

`Path.is_symlink()` renvoie **False** sur une jonction (`mklink /J`,
reparse tag `0xa0000003`) alors que `is_dir()` renvoie True et que `rglob`
descend dans la cible. Le classement d'un dossier residuel se decidait donc sur
des fichiers situes HORS de la bibliotheque, puis le point de montage partait
vers `_Dossier Nettoyage`.

Reproduction mesuree sur `main` (Windows 11, CPython 3.13, vraie jonction, apply
REEL via la facade `CineSortApi`) : `symlink_count=0`, `probable_eligible=1`,
jonction absente de la racine et presente dans `_Dossier Nettoyage`, contenu
hors-bibliotheque enumerable depuis le bac de nettoyage.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import mock

import cinesort.app._dir_utils as dir_utils
import cinesort.app.apply_core as apply_core
import cinesort.app.cleanup as cleanup
import cinesort.domain.core as core
from cinesort.app._dir_utils import is_reparse_point
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done

_IS_WINDOWS = os.name == "nt"


def _make_dir_link(link: Path, target: Path) -> None:
    """Cree un lien de dossier vers `target`.

    Sous Windows : une VRAIE jonction NTFS (`mklink /J`), justement parce que
    `Path.is_symlink()` ne la voit pas — c'est tout l'objet de l'issue. La
    creation de jonction ne demande aucun privilege particulier ; un echec est
    donc une erreur dure, jamais un skip.

    Ailleurs : un lien symbolique de dossier, equivalent fonctionnel le plus
    proche, pour que ces tests restent executables hors Windows.
    """
    if _IS_WINDOWS:
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not link.exists():
            raise AssertionError(f"mklink /J a echoue (rc={proc.returncode}): {proc.stdout} {proc.stderr}")
        return
    link.symlink_to(target, target_is_directory=True)


class _SandboxCase(unittest.TestCase):
    """Bac a sable : une bibliotheque + une arborescence HORS bibliotheque."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="issue517_")
        self.base = Path(self._tmp)
        self.root = self.base / "root"
        self.state_dir = self.base / "state"
        self.outside = self.base / "AUTRE_DISQUE"
        self.root.mkdir(parents=True)
        self.state_dir.mkdir(parents=True)
        self.outside.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _sidecar_tree(self, folder: Path, marker: str = "image") -> None:
        """Arborescence composee UNIQUEMENT d'extensions residuelles autorisees.

        `marker` nomme le fichier feuille pour distinguer sans ambiguite le
        contenu HORS bibliotheque du contenu residuel legitime.
        """
        (folder / "Photos").mkdir(parents=True, exist_ok=True)
        (folder / "Photos" / f"{marker}.jpg").write_bytes(b"IMG")
        (folder / "notes.txt").write_bytes(b"NOTES")
        (folder / "film.nfo").write_bytes(b"<movie/>")

    def _cfg(self, **overrides: Any) -> "core.Config":
        params: Dict[str, Any] = {
            "root": self.root,
            "cleanup_residual_folders_enabled": True,
            "cleanup_residual_folders_folder_name": "_Dossier Nettoyage",
            "cleanup_residual_folders_scope": "root_all",
        }
        params.update(overrides)
        return core.Config(**params).normalized()


class IsReparsePointTests(_SandboxCase):
    """Le detecteur lui-meme : c'est lui qui remplace `is_symlink()`."""

    def test_plain_directory_is_not_a_reparse_point(self) -> None:
        plain = self.root / "Ordinaire"
        plain.mkdir()
        self.assertFalse(is_reparse_point(plain))

    def test_plain_file_is_not_a_reparse_point(self) -> None:
        plain = self.root / "fichier.nfo"
        plain.write_bytes(b"<movie/>")
        self.assertFalse(is_reparse_point(plain))

    def test_dir_link_is_a_reparse_point(self) -> None:
        link = self.root / "Lien"
        _make_dir_link(link, self.outside)
        self.assertTrue(is_reparse_point(link))

    def test_unreadable_path_is_treated_as_a_link(self) -> None:
        """Sens restrictif : si on ne peut pas savoir, on refuse de traverser."""
        self.assertTrue(is_reparse_point(self.root / "jamais_existe"))

    def test_posix_branch_reports_plain_directory_as_not_a_link(self) -> None:
        """La branche non-Windows reste exercee sur la machine de dev/CI Windows."""
        plain = self.root / "Ordinaire"
        plain.mkdir()
        with mock.patch.object(dir_utils, "_IS_WINDOWS", False):
            self.assertFalse(is_reparse_point(plain))

    def test_posix_branch_is_restrictive_on_unreadable_path(self) -> None:
        with mock.patch.object(dir_utils, "_IS_WINDOWS", False):
            self.assertTrue(is_reparse_point(self.root / "jamais_existe"))

    @unittest.skipUnless(_IS_WINDOWS, "semantique NTFS : jonction reelle")
    def test_windows_junction_defeats_is_symlink(self) -> None:
        """Ancrage : ce test ECHOUE si le lien teste n'est pas une vraie jonction.

        Il fige les trois faits mesures qui rendaient le garde precedent inerte.
        """
        link = self.root / "Jonction"
        _make_dir_link(link, self.outside)
        st = link.lstat()

        self.assertFalse(link.is_symlink(), "une jonction n'est PAS un symlink pour pathlib")
        self.assertTrue(link.is_dir(), "une jonction se presente comme un dossier ordinaire")
        self.assertEqual(hex(int(st.st_reparse_tag)), "0xa0000003", "IO_REPARSE_TAG_MOUNT_POINT attendu")
        self.assertTrue(bool(int(st.st_file_attributes) & stat.FILE_ATTRIBUTE_REPARSE_POINT))
        self.assertTrue(is_reparse_point(link))


class ClassifyResidualJunctionTests(_SandboxCase):
    """`_classify_cleanable_residual_dir` : le classement ne doit jamais porter
    sur des fichiers situes hors de la bibliotheque."""

    def test_top_level_junction_is_never_eligible(self) -> None:
        self._sidecar_tree(self.outside)
        link = self.root / "DisqueMutualise"
        _make_dir_link(link, self.outside)

        self.assertEqual(cleanup._classify_cleanable_residual_dir(self._cfg(), link), "symlink")
        self.assertFalse(cleanup._is_cleanable_residual_dir(self._cfg(), link))

    def test_nested_junction_makes_the_parent_ineligible(self) -> None:
        self._sidecar_tree(self.outside)
        residual = self.root / "Residuel"
        residual.mkdir()
        (residual / "film.nfo").write_bytes(b"<movie/>")
        _make_dir_link(residual / "vers_ailleurs", self.outside)

        self.assertEqual(cleanup._classify_cleanable_residual_dir(self._cfg(), residual), "symlink")

    def test_plain_sidecar_only_dir_stays_eligible(self) -> None:
        """Non-regression : le garde ne doit pas geler la fonctionnalite."""
        residual = self.root / "Residuel"
        self._sidecar_tree(residual)

        self.assertEqual(cleanup._classify_cleanable_residual_dir(self._cfg(), residual), "eligible")

    def test_oversized_sidecar_extension_is_ambiguous(self) -> None:
        """Classement par extension SEULE : un `.txt` enorme n'est pas un sidecar."""
        residual = self.root / "Residuel"
        residual.mkdir()
        (residual / "film.nfo").write_bytes(b"<movie/>")
        (residual / "en_fait_une_video.txt").write_bytes(b"V" * 4096)

        with mock.patch.object(cleanup, "MAX_RESIDUAL_SIDECAR_BYTES", 1024):
            self.assertEqual(cleanup._classify_cleanable_residual_dir(self._cfg(), residual), "ambiguous")

    def test_small_sidecar_below_threshold_stays_eligible(self) -> None:
        residual = self.root / "Residuel"
        residual.mkdir()
        (residual / "film.nfo").write_bytes(b"<movie/>")
        (residual / "notes.txt").write_bytes(b"N" * 16)

        with mock.patch.object(cleanup, "MAX_RESIDUAL_SIDECAR_BYTES", 1024):
            self.assertEqual(cleanup._classify_cleanable_residual_dir(self._cfg(), residual), "eligible")

    def test_size_threshold_stays_generous_enough_for_real_sidecars(self) -> None:
        """Garde-fou inverse : un seuil trop bas mutilerait des sidecars legitimes
        (pistes `.sup` Blu-ray, planches d'images) en les rendant ambigus."""
        self.assertGreaterEqual(cleanup.MAX_RESIDUAL_SIDECAR_BYTES, 100 * 1024 * 1024)


class PreviewJunctionTests(_SandboxCase):
    """Le preview doit DIRE que le dossier est un lien, pas le taire."""

    def test_preview_reports_junction_as_symlink_not_eligible(self) -> None:
        self._sidecar_tree(self.outside)
        _make_dir_link(self.root / "DisqueMutualise", self.outside)

        preview = cleanup.preview_cleanup_residual_folders(self._cfg(), set())

        self.assertEqual(int(preview["probable_eligible_count"]), 0)
        self.assertEqual(int(preview["symlink_count"]), 1)
        self.assertIn(str(self.root / "DisqueMutualise"), preview["sample_symlink_dirs"])


class RealApplyJunctionTests(_SandboxCase):
    """Le coeur : un apply REEL (dry_run=False) via la facade de production.

    Un test qui ne couvre que le preview ne prouve rien sur l'operation reelle.
    """

    def setUp(self) -> None:
        super().setUp()
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

    def _run_full_apply(self, settings: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        api = CineSortApi()
        base: Dict[str, Any] = {
            "root": str(self.root),
            "state_dir": str(self.state_dir),
            "tmdb_enabled": False,
        }
        base.update(settings)
        start = api.run.start_plan(base)
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        _wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows: List[Dict[str, Any]] = plan.get("rows", [])
        decisions = {
            row["row_id"]: {
                "ok": True,
                "title": row.get("proposed_title"),
                "year": row.get("proposed_year"),
            }
            for row in rows
        }
        preview = api.run.get_cleanup_residual_preview(run_id)
        applied = api._apply_impl(run_id, decisions, False, False)
        self.assertTrue(applied.get("ok"), applied)
        return preview, applied

    def test_real_apply_leaves_the_junction_in_place_and_still_cleans_the_real_residue(self) -> None:
        self._sidecar_tree(self.outside, marker="hors_bibliotheque")
        _make_dir_link(self.root / "DisqueMutualise", self.outside)

        real_residue = self.root / "Residuel"
        self._sidecar_tree(real_residue, marker="residu_legitime")

        film = self.root / "Real.Movie.2019.1080p"
        _create_file(film / "Real.Movie.2019.1080p.mkv")

        preview, applied = self._run_full_apply(
            {
                "cleanup_residual_folders_enabled": True,
                "cleanup_residual_folders_folder_name": "_Dossier Nettoyage",
                "cleanup_residual_folders_scope": "root_all",
            }
        )

        bucket = self.root / "_Dossier Nettoyage"
        junction = self.root / "DisqueMutualise"

        self.assertEqual(int(applied.get("errors") or 0), 0, applied)
        # 1. La jonction n'a pas bouge et n'est pas dans le bac de nettoyage.
        self.assertTrue(junction.exists(), "la jonction doit rester a la racine de la bibliotheque")
        self.assertFalse((bucket / "DisqueMutualise").exists(), "la jonction ne doit JAMAIS partir en nettoyage")
        # 2. Aucun fichier hors bibliotheque n'est atteignable depuis le bac.
        self.assertEqual(
            [str(p) for p in bucket.rglob("hors_bibliotheque.jpg")] if bucket.exists() else [],
            [],
            "aucun contenu hors bibliotheque ne doit apparaitre dans le bac de nettoyage",
        )
        # 3. L'arborescence externe est intacte.
        self.assertTrue((self.outside / "Photos" / "hors_bibliotheque.jpg").exists())
        # 4. Le vrai residu, lui, est bien nettoye : le garde ne gele pas la fonction.
        self.assertFalse(real_residue.exists(), "le dossier residuel legitime doit avoir ete deplace")
        self.assertTrue((bucket / "Residuel" / "film.nfo").exists())
        # 5. Le preview annonce le lien au lieu de le presenter comme eligible.
        preview_body = preview.get("preview") or {}
        self.assertEqual(int(preview_body.get("symlink_count") or 0), 1, preview)
        self.assertIn(str(junction), preview_body.get("sample_symlink_dirs") or [])
        self.assertNotIn(str(junction), preview_body.get("sample_eligible_dirs") or [])


class RealApplyEmptyFolderJunctionTests(_SandboxCase):
    """Meme angle mort sur le bac `_Vide` : une jonction vers un dossier vide
    est vue `is_dir_empty() == True`. Apply REEL via `apply_core.apply_rows`."""

    def test_real_apply_does_not_move_a_junction_to_the_empty_bucket(self) -> None:
        junction = self.root / "DisqueDemonte"
        _make_dir_link(junction, self.outside)  # self.outside est vide

        genuinely_empty = self.root / "VraimentVide"
        genuinely_empty.mkdir()

        cfg = core.Config(
            root=self.root,
            move_empty_folders_enabled=True,
            empty_folders_folder_name="_Vide",
            empty_folders_scope="root_all",
        ).normalized()

        logs: List[Tuple[str, str]] = []
        result = apply_core.apply_rows(
            cfg,
            [],
            {},
            dry_run=False,
            quarantine_unapproved=False,
            log=lambda level, msg: logs.append((level, msg)),
            run_review_root=self.state_dir / "runs" / "tri_films_test" / "_review",
        )

        self.assertEqual(int(result.errors), 0)
        self.assertTrue(junction.exists(), "la jonction doit rester a la racine")
        self.assertFalse((self.root / "_Vide" / "DisqueDemonte").exists())
        # Non-regression : un dossier reellement vide part bien en `_Vide`.
        self.assertFalse(genuinely_empty.exists())
        self.assertTrue((self.root / "_Vide" / "VraimentVide").exists())
        self.assertEqual(int(result.empty_folders_moved_count), 1)


if __name__ == "__main__":
    unittest.main()
