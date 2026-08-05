"""Issue #567 — `_classify_cleanable_residual_dir` : UN SEUL `lstat()` par entree.

Ce que ces tests mesurent, et pourquoi cette grandeur-la
--------------------------------------------------------
Le cout reel du classement residuel sur une bibliotheque SMB/NAS n'est pas du
temps de calcul : c'est un nombre d'allers-retours reseau. Un ratio de durees
mesure sur un runner partage ne dirait rien de fiable ; le **nombre d'appels a
`os.stat`** est deterministe et se compte exactement.

Mesure sur `main` avant correctif (Windows 11 / CPython 3.13, 8 fichiers +
1 sous-dossier) : **34 appels**, soit 4 par fichier
(`is_reparse_point` -> `lstat`, `is_dir()`, `is_file()`, `stat().st_size`) et
2 par sous-dossier. Apres correctif : **9 appels**, exactement un par entree.

`pathlib` route tout par `os.stat` (`Path.lstat()` appelle
`os.stat(self, follow_symlinks=False)`), et `rglob` n'en ajoute aucun : le
compteur ci-dessous n'attribue donc au classement que ses propres syscalls.

Le second volet fige le contrat partage : `stat_is_reparse_point` doit rendre
exactement le meme verdict que `is_reparse_point` — la boucle rapide ne doit pas
pouvoir deriver de la semantique NTFS de l'issue #517.
"""

from __future__ import annotations

import collections
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import cinesort.app.cleanup as cleanup
import cinesort.domain.core as core
from cinesort.app._dir_utils import is_reparse_point, stat_is_reparse_point

_IS_WINDOWS = os.name == "nt"


class _StatSpy:
    """Compte les `os.stat` portant sur les DESCENDANTS de `under`.

    Ce n'est pas un mock : le vrai `os.stat` est appele et son resultat rendu
    intact. Un faux `stat_result` fabriquerait justement la condition testee.
    """

    def __init__(self, under: Path) -> None:
        self._prefix = str(under) + os.sep
        self.calls: collections.Counter = collections.Counter()
        self._real = os.stat

    def __enter__(self) -> "_StatSpy":
        os.stat = self._spy  # type: ignore[assignment]
        return self

    def __exit__(self, *exc: Any) -> None:
        os.stat = self._real  # type: ignore[assignment]

    def _spy(self, path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        try:
            as_str = os.fspath(path)
        except TypeError:
            as_str = None
        if isinstance(as_str, str) and as_str.startswith(self._prefix):
            self.calls[as_str] += 1
        return self._real(path, *args, **kwargs)

    @property
    def total(self) -> int:
        return sum(self.calls.values())

    @property
    def worst_entry(self) -> int:
        return max(self.calls.values()) if self.calls else 0


class _ResidualCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="issue567_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self, **overrides: Any) -> "core.Config":
        params: Dict[str, Any] = {
            "root": self.root,
            "cleanup_residual_folders_enabled": True,
            "cleanup_residual_folders_folder_name": "_Dossier Nettoyage",
            "cleanup_residual_folders_scope": "root_all",
        }
        params.update(overrides)
        return core.Config(**params).normalized()

    def _sidecar_tree(self, folder: Path, n_files: int = 8) -> List[Path]:
        (folder / "Photos").mkdir(parents=True, exist_ok=True)
        (folder / "film.nfo").write_bytes(b"<movie/>")
        (folder / "notes.txt").write_bytes(b"NOTES")
        for i in range(n_files):
            (folder / "Photos" / f"img{i}.jpg").write_bytes(b"IMG")
        return sorted(folder.rglob("*"))


class SyscallBudgetTests(_ResidualCase):
    def test_one_stat_per_entry_on_an_eligible_tree(self) -> None:
        residual = self.root / "Residuel"
        entries = self._sidecar_tree(residual)
        self.assertGreaterEqual(len(entries), 10, "arbre trop petit pour que la mesure ait un sens")

        with _StatSpy(residual) as spy:
            verdict = cleanup._classify_cleanable_residual_dir(self._cfg(), residual)

        self.assertEqual(verdict, "eligible", "le budget de syscalls ne doit pas changer le verdict")
        self.assertEqual(
            spy.worst_entry,
            1,
            f"au plus un stat par entree attendu, mesure {spy.worst_entry} (detail : {dict(spy.calls)})",
        )
        self.assertEqual(
            spy.total,
            len(entries),
            f"{len(entries)} entrees -> {len(entries)} stat attendus, mesure {spy.total}",
        )

    def test_one_stat_per_entry_when_a_size_check_is_needed(self) -> None:
        """Le controle de taille (issue #517) doit se lire sur le MEME stat.

        C'est le chemin qui coutait 4 syscalls par fichier : sans cette
        assertion, une regression qui rappellerait `item.stat()` pour la taille
        passerait inapercue, le test precedent s'arretant plus tot.
        """
        residual = self.root / "Residuel"
        residual.mkdir()
        (residual / "film.nfo").write_bytes(b"<movie/>")
        for i in range(6):
            (residual / f"notes{i}.txt").write_bytes(b"N" * 512)
        entries = sorted(residual.rglob("*"))

        with mock.patch.object(cleanup, "MAX_RESIDUAL_SIDECAR_BYTES", 1024):
            with _StatSpy(residual) as spy:
                verdict = cleanup._classify_cleanable_residual_dir(self._cfg(), residual)

        self.assertEqual(verdict, "eligible")
        self.assertEqual(spy.worst_entry, 1, f"detail : {dict(spy.calls)}")
        self.assertEqual(spy.total, len(entries))

    def test_spy_does_not_alter_the_verdict(self) -> None:
        """Garde-fou sur l'instrument : la mesure ne doit rien changer au mesure."""
        residual = self.root / "Residuel"
        self._sidecar_tree(residual)
        without = cleanup._classify_cleanable_residual_dir(self._cfg(), residual)
        with _StatSpy(residual):
            withspy = cleanup._classify_cleanable_residual_dir(self._cfg(), residual)
        self.assertEqual(without, withspy)


class VerdictParityTests(_ResidualCase):
    """Le budget de syscalls ne se paie sur AUCUN verdict."""

    def test_video_extension_still_wins(self) -> None:
        residual = self.root / "Residuel"
        residual.mkdir()
        (residual / "film.nfo").write_bytes(b"<movie/>")
        (residual / "film.mkv").write_bytes(b"V" * 32)
        self.assertEqual(cleanup._classify_cleanable_residual_dir(self._cfg(), residual), "has_video")

    def test_iso_still_counts_as_video(self) -> None:
        residual = self.root / "Residuel"
        residual.mkdir()
        (residual / "film.iso").write_bytes(b"V" * 32)
        self.assertEqual(cleanup._classify_cleanable_residual_dir(self._cfg(), residual), "has_video")

    def test_unknown_extension_is_ambiguous(self) -> None:
        residual = self.root / "Residuel"
        residual.mkdir()
        (residual / "archive.rar").write_bytes(b"RAR")
        self.assertEqual(cleanup._classify_cleanable_residual_dir(self._cfg(), residual), "ambiguous")

    def test_oversized_sidecar_is_ambiguous(self) -> None:
        residual = self.root / "Residuel"
        residual.mkdir()
        (residual / "en_fait_une_video.txt").write_bytes(b"V" * 4096)
        with mock.patch.object(cleanup, "MAX_RESIDUAL_SIDECAR_BYTES", 1024):
            self.assertEqual(cleanup._classify_cleanable_residual_dir(self._cfg(), residual), "ambiguous")

    def test_dirs_only_yields_no_files(self) -> None:
        residual = self.root / "Residuel"
        (residual / "a" / "b").mkdir(parents=True)
        self.assertEqual(cleanup._classify_cleanable_residual_dir(self._cfg(), residual), "no_files")

    def test_non_regular_entry_is_ambiguous_even_with_an_allowed_extension(self) -> None:
        """La garde « ni dossier, ni fichier ordinaire » doit rester atteinte.

        Windows ne laisse pas creer de FIFO/socket dans un dossier, si bien que
        supprimer cette garde ne cassait AUCUN test : le chemin n'etait pas
        emprunte. Ce n'est pas un mutant equivalent, c'est un test manquant — on
        force donc la condition.

        Le `stat_result` rendu ici est un VRAI `os.stat_result`, derive du stat
        reel du fichier avec le seul champ de type modifie : ses autres champs
        (`st_size`, `st_file_attributes`) restent authentiques, donc le classement
        traverse bien la detection de point d'analyse avant d'atteindre la garde.
        Un faux objet aurait fabrique la condition mesuree, ou serait sorti en
        `AttributeError` avant d'atteindre le test vise.

        L'extension est `.nfo`, donc AUTORISEE : sans la garde, le dossier
        deviendrait "eligible" et partirait au nettoyage.
        """
        import stat as stat_mod

        residual = self.root / "Residuel"
        residual.mkdir()
        (residual / "film.nfo").write_bytes(b"<movie/>")
        odd = residual / "tuyau.nfo"
        odd.write_bytes(b"<movie/>")

        real_lstat = Path.lstat

        def fifo_lstat(self: Path, *a: Any, **kw: Any) -> os.stat_result:
            st = real_lstat(self, *a, **kw)
            if self.name != "tuyau.nfo":
                return st
            fields = list(tuple(st))
            fields[0] = (fields[0] & ~stat_mod.S_IFMT(fields[0])) | stat_mod.S_IFIFO
            extra: Dict[str, Any] = {
                "st_atime": st.st_atime,
                "st_mtime": st.st_mtime,
                "st_ctime": st.st_ctime,
                "st_atime_ns": st.st_atime_ns,
                "st_mtime_ns": st.st_mtime_ns,
                "st_ctime_ns": st.st_ctime_ns,
            }
            for name in ("st_file_attributes", "st_reparse_tag", "st_birthtime"):
                if hasattr(st, name):
                    extra[name] = getattr(st, name)
            return os.stat_result(tuple(fields), extra)

        # Ancrage : sans cela le test pourrait passer pour une tout autre raison.
        with mock.patch.object(Path, "lstat", fifo_lstat):
            forced = odd.lstat()
        self.assertTrue(stat_mod.S_ISFIFO(forced.st_mode), "la condition n'a pas ete forcee")
        self.assertFalse(stat_mod.S_ISDIR(forced.st_mode))
        self.assertFalse(stat_mod.S_ISREG(forced.st_mode))

        with mock.patch.object(Path, "lstat", fifo_lstat):
            verdict = cleanup._classify_cleanable_residual_dir(self._cfg(), residual)
        self.assertEqual(verdict, "ambiguous")

    def test_entry_that_vanishes_mid_walk_stays_symlink(self) -> None:
        """Sens RESTRICTIF conserve : une entree illisible n'est jamais eligible.

        Avant le correctif, `is_reparse_point` repondait deja True sur un
        `lstat()` en echec — le verdict etait donc "symlink". Le `lstat()` unique
        doit rendre exactement le meme verdict, pas "ambiguous" ni pire "eligible".
        """
        residual = self.root / "Residuel"
        residual.mkdir()
        (residual / "film.nfo").write_bytes(b"<movie/>")
        (residual / "disparu.jpg").write_bytes(b"IMG")

        real_lstat = Path.lstat

        def flaky_lstat(self: Path, *a: Any, **kw: Any) -> os.stat_result:
            if self.name == "disparu.jpg":
                raise OSError(2, "disparu pendant l'enumeration")
            return real_lstat(self, *a, **kw)

        with mock.patch.object(Path, "lstat", flaky_lstat):
            verdict = cleanup._classify_cleanable_residual_dir(self._cfg(), residual)
        self.assertEqual(verdict, "symlink")


class SharedReparseContractTests(_ResidualCase):
    """`stat_is_reparse_point` doit rendre le MEME verdict que `is_reparse_point`.

    Sans cela, la boucle rapide pourrait derailler la protection issue #517 tout
    en laissant les tests de #517 au vert (ils passent par `is_reparse_point`).
    """

    def _assert_agree(self, path: Path) -> None:
        self.assertEqual(
            stat_is_reparse_point(path.lstat()),
            is_reparse_point(path),
            f"desaccord sur {path}",
        )

    def test_agree_on_plain_directory(self) -> None:
        plain = self.root / "Ordinaire"
        plain.mkdir()
        self._assert_agree(plain)
        self.assertFalse(stat_is_reparse_point(plain.lstat()))

    def test_agree_on_plain_file(self) -> None:
        plain = self.root / "fichier.nfo"
        plain.write_bytes(b"<movie/>")
        self._assert_agree(plain)
        self.assertFalse(stat_is_reparse_point(plain.lstat()))

    @unittest.skipUnless(_IS_WINDOWS, "semantique NTFS : jonction reelle")
    def test_agree_on_ntfs_junction(self) -> None:
        target = Path(self._tmp) / "AUTRE_DISQUE"
        target.mkdir()
        link = self.root / "Jonction"
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not link.exists():
            raise AssertionError(f"mklink /J a echoue (rc={proc.returncode}): {proc.stdout} {proc.stderr}")
        self._assert_agree(link)
        self.assertTrue(stat_is_reparse_point(link.lstat()))

    @unittest.skipIf(_IS_WINDOWS, "branche POSIX : lien symbolique")
    def test_agree_on_posix_symlink(self) -> None:
        target = Path(self._tmp) / "cible"
        target.mkdir()
        link = self.root / "lien"
        link.symlink_to(target, target_is_directory=True)
        self._assert_agree(link)
        self.assertTrue(stat_is_reparse_point(link.lstat()))


if __name__ == "__main__":
    unittest.main()
