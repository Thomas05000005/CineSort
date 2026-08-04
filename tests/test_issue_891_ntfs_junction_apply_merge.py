"""Issue #891 — le chemin DESTRUCTIF de l'apply traversait les jonctions NTFS.

Trois `rglob("*")` (deux dans `merge_dir_safe`, un dans `prune_empty_dirs`)
descendaient dans une jonction (`mklink /J`) : `is_symlink()` y repond False,
`is_dir()` True, et l'enumeration part vers la cible. Mesure sur `main`
(Windows 11, CPython 3.13, vraie jonction, `merge_dir_safe(dry_run=False)`) :

    jonction encore la ?        False   <- point de montage DETRUIT
    precieux.mkv hors biblio ?  False   <- video EXTERNE entree dans la biblio
    notes.txt hors biblio ?     False   <- fichier EXTERNE parti en _leftovers
    errors= 0  moves= 2  leftovers= 1  source_dirs_deleted= 1

et `prune_empty_dirs` supprimait un dossier vide situe HORS de la racine, voire
la jonction elle-meme. `ensure_inside_root` etait contourne : la jonction fait
sortir du perimetre sans qu'aucun chemin ne quitte `cfg.root` en apparence.

Ces tests verrouillent les quatre gardes, chacune isolable :

    G1  merge_dir_safe : `src_dir` lui-meme est un point d'analyse -> refus
    G2  descente explicite qui n'entre dans aucun point d'analyse
    G3  prune_empty_dirs : `root` lui-meme est un point d'analyse -> refus
    G4  dry_run : ne pas promettre la suppression d'une source qui survivra

Le SCAN, lui, doit continuer a traverser les jonctions (arbitrage proprietaire :
analyser est le but de l'app) — rien ici ne le touche.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import List, Tuple

import cinesort.app.apply_core as apply_core
import cinesort.domain.core as core
from cinesort.app._dir_utils import is_reparse_point
from tests._helpers import create_file as _create_file

_IS_WINDOWS = os.name == "nt"


def _make_dir_link(link: Path, target: Path) -> None:
    """Cree un lien de dossier vers `target`.

    Sous Windows : une VRAIE jonction NTFS (`mklink /J`), justement parce que
    `Path.is_symlink()` ne la voit pas — c'est tout l'objet de l'issue. La
    creation de jonction ne demande aucun privilege ; un echec est donc une
    erreur dure, jamais un skip qui viderait la batterie de sa substance.

    Ailleurs : un lien symbolique de dossier. La descente corrigee passe par
    `iterdir()` + `is_dir()`, qui suivent les liens symboliques sur toutes les
    plateformes : les tests restent donc discriminants hors Windows.
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


class _JunctionSandbox(unittest.TestCase):
    """Bibliotheque + arborescence HORS bibliotheque, reliees par une jonction."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="issue891_")
        self.base = Path(self._tmp)
        self.root = self.base / "root"
        self.outside = self.base / "AUTRE_DISQUE"
        self.review = self.base / "state" / "_review"
        self.root.mkdir(parents=True)
        self.outside.mkdir(parents=True)
        self.review.mkdir(parents=True)
        self.logs: List[Tuple[str, str]] = []

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self) -> "core.Config":
        return core.Config(root=self.root).normalized()

    def _log(self, level: str, message: str) -> None:
        self.logs.append((level, message))

    def _logged(self, level: str, needle: str) -> bool:
        return any(lvl == level and needle in msg for lvl, msg in self.logs)

    def _merge(self, src_dir: Path, dst_dir: Path, *, dry_run: bool) -> "core.ApplyResult":
        res = core.ApplyResult()
        apply_core.merge_dir_safe(
            self._cfg(),
            src_dir,
            dst_dir,
            dry_run=dry_run,
            log=self._log,
            res=res,
            conflicts_root=self.review / "_conflicts",
            conflicts_sidecars_root=self.review / "_conflicts_sidecars",
            duplicates_identical_root=self.review / "_duplicates_identical",
            leftovers_root=self.review / "_leftovers",
        )
        return res

    def _external_tree(self) -> None:
        """Contenu HORS bibliotheque : une video et un fichier non gere."""
        _create_file(self.outside / "precieux.mkv")
        (self.outside / "notes.txt").write_bytes(b"NOTES")

    def _assert_external_tree_intact(self) -> None:
        self.assertTrue((self.outside / "precieux.mkv").exists(), "la video externe doit rester hors bibliotheque")
        self.assertTrue((self.outside / "notes.txt").exists(), "le fichier externe doit rester hors bibliotheque")

    def _assert_nothing_external_entered(self, dst_dir: Path) -> None:
        """Aucun octet venu d'un autre volume dans la cible ni dans `_review`.

        On n'enumere PAS depuis `self.root` : un `rglob` y traverserait la
        jonction et verrait le fichier externe *a travers* le point de montage,
        transformant l'assertion en faux rouge. Ni la cible ni `_review` ne
        contiennent de point d'analyse : les enumerer est sur.
        """
        intrus = [str(p) for p in dst_dir.rglob("*") if p.name in {"precieux.mkv", "notes.txt"}]
        intrus += [str(p) for p in self.review.rglob("*") if p.name in {"precieux.mkv", "notes.txt"}]
        self.assertEqual(intrus, [], "aucun octet venu d'un autre volume ne doit entrer dans la bibliotheque")


class MeasurementAnchorTests(_JunctionSandbox):
    """Ancrage : sans lui, toute la batterie pourrait etre VACANTE.

    Si le lien pose n'etait pas une vraie jonction, `rglob` ne le traverserait
    pas et les tests suivants passeraient au vert sans rien prouver.
    """

    @unittest.skipUnless(_IS_WINDOWS, "semantique NTFS : jonction reelle")
    def test_rglob_crosses_a_real_junction_but_the_safe_walk_does_not(self) -> None:
        self._external_tree()
        src = self.root / "Film.2019"
        _create_file(src / "Film.2019.mkv")
        _make_dir_link(src / "extras", self.outside)

        crossed = sorted(p.name for p in src.rglob("*") if p.is_file())
        self.assertIn("precieux.mkv", crossed, "rglob DOIT traverser la jonction : c'est le bug mesure")

        walk = apply_core._walk_without_crossing_reparse_points(src)
        self.assertEqual(sorted(p.name for p in walk.files), ["Film.2019.mkv"])
        self.assertEqual([p.name for p in walk.blocked], ["extras"])
        self.assertEqual(walk.dirs, [], "la jonction ne doit pas etre listee comme dossier a traiter")


class MergeSourceIsJunctionTests(_JunctionSandbox):
    """G1 — fusionner DEPUIS une jonction viderait un autre volume dans la biblio."""

    def test_merge_from_a_junction_is_refused_and_reported_as_an_error(self) -> None:
        self._external_tree()
        src = self.root / "Film.2019"
        _make_dir_link(src, self.outside)
        dst = self.root / "Film (2019)"

        res = self._merge(src, dst, dry_run=False)

        self.assertTrue(src.exists(), "le point de montage doit rester en place")
        self._assert_external_tree_intact()
        self.assertFalse(dst.exists(), "la cible ne doit meme pas etre creee")
        # Un echec ne devient pas un succes silencieux.
        self.assertEqual(int(res.errors), 1, "le refus doit etre COMPTE, pas tu")
        self.assertEqual(int(res.moves), 0)
        self.assertEqual(int(res.merges_count), 0, "rien n'a ete fusionne")
        self.assertEqual(int(res.source_dirs_deleted_count), 0)
        self.assertTrue(
            any(str(src) in message for message in res.error_messages),
            f"le message utilisateur doit nommer le chemin refuse: {res.error_messages}",
        )
        self.assertTrue(self._logged("ERROR", str(src)))

    def test_merge_from_a_plain_directory_still_works(self) -> None:
        """Non-regression : la garde ne doit pas geler la fusion ordinaire."""
        src = self.root / "Film.2019"
        _create_file(src / "Film.2019.mkv")
        dst = self.root / "Film (2019)"

        res = self._merge(src, dst, dry_run=False)

        self.assertEqual(int(res.errors), 0)
        self.assertEqual(int(res.merges_count), 1)
        self.assertEqual(int(res.moves), 1)
        self.assertTrue((dst / "Film.2019.mkv").exists())
        self.assertFalse(src.exists(), "la source videe doit etre supprimee")
        self.assertEqual(int(res.source_dirs_deleted_count), 1)


class MergeNestedJunctionTests(_JunctionSandbox):
    """G2 — la descente ne doit entrer dans aucun point d'analyse.

    Reproduction exacte de l'issue, en apply REEL (`dry_run=False`).
    """

    def test_real_merge_never_pulls_external_bytes_into_the_library(self) -> None:
        self._external_tree()
        src = self.root / "Film.2019"
        _create_file(src / "Film.2019.mkv")
        junction = src / "extras"
        _make_dir_link(junction, self.outside)
        dst = self.root / "Film (2019)"

        res = self._merge(src, dst, dry_run=False)

        self.assertTrue(junction.exists(), "le point de montage doit survivre a la fusion")
        self.assertTrue(is_reparse_point(junction), "il doit rester un point de montage, pas une copie locale")
        self._assert_external_tree_intact()
        self._assert_nothing_external_entered(dst)
        self.assertFalse((dst / "extras").exists(), "la jonction ne doit pas etre recreee dans la cible")
        # Le film, lui, est bien fusionne : la garde ne gele pas la fonction.
        self.assertTrue((dst / "Film.2019.mkv").exists())
        self.assertEqual(int(res.moves), 1)
        self.assertEqual(int(res.errors), 0)
        # La source survit (elle contient encore la jonction) et le compteur le dit.
        self.assertTrue(src.exists())
        self.assertEqual(int(res.source_dirs_deleted_count), 0, "aucune suppression de source ne doit etre annoncee")
        self.assertTrue(self._logged("WARN", str(junction)), f"le refus doit etre journalise: {self.logs}")

    def test_a_plain_subdirectory_is_still_merged_entirely(self) -> None:
        """Non-regression : un vrai sous-dossier reste fusionne et la source purgee."""
        src = self.root / "Film.2019"
        _create_file(src / "Film.2019.mkv")
        _create_file(src / "extras" / "bonus.mkv")
        dst = self.root / "Film (2019)"

        res = self._merge(src, dst, dry_run=False)

        self.assertTrue((dst / "extras" / "bonus.mkv").exists())
        self.assertEqual(int(res.moves), 2)
        self.assertFalse(src.exists())
        self.assertEqual(int(res.source_dirs_deleted_count), 1)


class MergeDryRunHonestyTests(_JunctionSandbox):
    """G4 — la preview ne doit pas promettre ce que l'apply reel refusera.

    NB : en `dry_run`, `merge_dir_safe` sort en erreur si la cible n'existe pas
    (rien n'est cree en simulation) — la cible est donc creee au prealable, sans
    quoi la fonction ne descendrait jamais jusqu'a la branche testee.
    """

    def test_dry_run_does_not_promise_to_delete_a_source_holding_a_junction(self) -> None:
        self._external_tree()
        src = self.root / "Film.2019"
        _create_file(src / "Film.2019.mkv")
        junction = src / "extras"
        _make_dir_link(junction, self.outside)
        dst = self.root / "Film (2019)"
        dst.mkdir()

        res = self._merge(src, dst, dry_run=True)

        self.assertEqual(int(res.errors), 0, self.logs)
        self.assertEqual(
            int(res.source_dirs_deleted_count),
            0,
            "la source contiendra encore la jonction : l'apply reel ne pourra pas la supprimer",
        )
        self.assertEqual(int(res.leftovers_moved_count), 0, "aucun fichier externe ne doit etre annonce en leftovers")
        self.assertTrue(self._logged("WARN", str(src)), f"le refus doit etre journalise: {self.logs}")
        # Une preview ne touche jamais le disque.
        self.assertTrue(junction.exists())
        self._assert_external_tree_intact()
        self._assert_nothing_external_entered(dst)

    def test_dry_run_still_promises_deletion_for_a_plain_source(self) -> None:
        """Non-regression : sans point d'analyse, la promesse reste."""
        src = self.root / "Film.2019"
        _create_file(src / "Film.2019.mkv")
        (src / "notes.txt").write_bytes(b"NOTES")
        dst = self.root / "Film (2019)"
        dst.mkdir()

        res = self._merge(src, dst, dry_run=True)

        self.assertEqual(int(res.errors), 0, self.logs)
        self.assertEqual(int(res.source_dirs_deleted_count), 1)
        self.assertEqual(int(res.leftovers_moved_count), 1)
        self.assertTrue(src.exists(), "un dry_run ne supprime rien")


class PruneEmptyDirsJunctionTests(_JunctionSandbox):
    """`prune_empty_dirs` : G2 sur les sous-dossiers, G3 sur la racine."""

    def test_prune_does_not_delete_an_empty_directory_located_outside_the_root(self) -> None:
        """G2 — mesure de l'issue : `AUTRE_DISQUE\\vide` disparaissait."""
        (self.outside / "garde.txt").write_bytes(b"GARDE")
        (self.outside / "vide").mkdir()
        src = self.root / "Film.2019"
        src.mkdir()
        junction = src / "vers_ailleurs"
        _make_dir_link(junction, self.outside)

        removed = apply_core.prune_empty_dirs(src)

        self.assertFalse(removed, "aucun dossier de la bibliotheque n'etait vide")
        self.assertTrue((self.outside / "vide").exists(), "un dossier HORS racine ne doit jamais etre supprime")
        self.assertTrue((self.outside / "garde.txt").exists())
        self.assertTrue(junction.exists(), "le point de montage doit survivre")
        self.assertTrue(src.exists())

    def test_prune_never_removes_the_junction_itself_when_its_target_is_empty(self) -> None:
        """G2 — cible vide : `rmdir` sur une jonction detruit le point de montage."""
        src = self.root / "Film.2019"
        src.mkdir()
        junction = src / "vers_ailleurs"
        _make_dir_link(junction, self.outside)  # self.outside est vide

        removed = apply_core.prune_empty_dirs(src)

        self.assertFalse(removed)
        self.assertTrue(junction.exists(), "la jonction ne doit JAMAIS etre supprimee")
        self.assertTrue(self.outside.exists(), "la cible externe doit rester intacte")
        self.assertTrue(src.exists(), "la source n'est pas vide : elle porte encore la jonction")

    def test_prune_refuses_a_root_that_is_itself_a_junction(self) -> None:
        """G3 — sinon `iterdir` enumere la cible et purge un autre volume."""
        (self.outside / "vide").mkdir()
        link = self.root / "Film.2019"
        _make_dir_link(link, self.outside)

        removed = apply_core.prune_empty_dirs(link)

        self.assertFalse(removed)
        self.assertTrue((self.outside / "vide").exists(), "un dossier HORS racine ne doit jamais etre supprime")
        self.assertTrue(link.exists())

    def test_prune_still_removes_genuinely_empty_directories(self) -> None:
        """Non-regression : la garde ne doit pas geler la purge legitime."""
        src = self.root / "Film.2019"
        (src / "a" / "b").mkdir(parents=True)
        (src / "c").mkdir()

        removed = apply_core.prune_empty_dirs(src)

        self.assertTrue(removed)
        self.assertFalse(src.exists(), "toute l'arborescence vide doit partir, racine comprise")


if __name__ == "__main__":
    unittest.main()
