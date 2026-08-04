"""Issue #614 — le watcher et les jonctions NTFS.

Faits mesures sur Windows 11 / CPython 3.13, avec une VRAIE jonction
(`mklink /J`) et un vrai lien symbolique de dossier (`mklink /D`) :

    jonction  is_dir(follow_symlinks=False) -> True   (elle EST dans le snapshot)
              is_symlink()                  -> False
              entry.stat().st_mtime_ns      -> mtime du LIEN, jamais celui de la
                                               cible ; releve a t+0, +1, +3 et
                                               +6 s apres modification de la
                                               cible : inchange, alors que
                                               os.stat change des t+0
    lien /D   is_dir(follow_symlinks=False) -> False  (absent du snapshot)
    les deux  os.stat -> meme (st_dev, st_ino) que la cible

L'issue annonce donc la mauvaise cause (« les jonctions sont exclues ») pour un
symptome reel : la branche attachee etait surveillee en apparence et muette en
pratique, parce que le mtime enregistre etait celui du lien. Ces tests figent
les trois proprietes attendues : suivre la cible, ne jamais compter deux fois le
meme dossier physique, et ne jamais renoncer a surveiller.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator, List, Optional
from unittest import mock

from cinesort.app import watcher

_IS_WINDOWS = os.name == "nt"


def _make_junction(link: Path, target: Path) -> None:
    """Cree un lien de dossier vers `target`.

    Sous Windows : une VRAIE jonction NTFS (`mklink /J`), justement parce
    qu'aucune garde naturelle ne la detecte. Sa creation ne demande aucun
    privilege particulier : un echec est une erreur dure, jamais un skip.

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


def _try_symlink(link: Path, target: Path, *, directory: bool) -> bool:
    """Cree un VRAI lien symbolique. Rend False si le privilege est refuse.

    Sous Windows, `mklink /D` exige SeCreateSymbolicLinkPrivilege (ou le mode
    developpeur) : indisponible, le test se skippe au lieu de mentir.
    """
    try:
        os.symlink(str(target), str(link), target_is_directory=directory)
    except (OSError, NotImplementedError, AttributeError):
        return False
    return True


def _noms(snapshot) -> set:
    """Noms des dossiers presents dans un snapshot 'nom|mtime'."""
    return {entree.rsplit("|", 1)[0] for entree in snapshot}


def _mtime(snapshot, nom: str) -> Optional[int]:
    """mtime enregistre pour `nom`, ou None si absent."""
    for entree in snapshot:
        cle, _, valeur = entree.rpartition("|")
        if cle == nom:
            return int(valeur)
    return None


def _mtime_du_cache(dossier: Path, nom: str) -> int:
    """mtime tel que le rend le cache d'annuaire de `os.scandir`."""
    with os.scandir(dossier) as scanner:
        entree = next(e for e in scanner if e.name == nom)
        return int(entree.stat().st_mtime_ns)


_VRAI_SCANDIR = os.scandir


@contextlib.contextmanager
def _scandir_inverse(chemin) -> Iterator[List["os.DirEntry[str]"]]:
    """`os.scandir` rendant les VRAIES entrees du disque, en ordre inverse.

    `os.scandir` ne garantit aucun ordre et rien ne permet d'en demander un
    autre au systeme de fichiers : la seule facon d'eprouver l'independance a
    cet ordre est de le retourner ici. Les entrees, elles, restent celles du
    disque.
    """
    with _VRAI_SCANDIR(chemin) as scanner:
        entrees = list(scanner)
    yield entrees[::-1]


class _SandboxCase(unittest.TestCase):
    """Bac a sable : un root surveille + une arborescence HORS du root."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="issue614_")
        self.base = Path(self._tmp)
        self.root = self.base / "root"
        self.externe = self.base / "AUTRE_DISQUE"
        self.root.mkdir(parents=True)
        self.externe.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)


class AncrageJonctionTests(_SandboxCase):
    """Ancrage des faits mesures : ces tests echouent si le lien teste n'est pas
    une vraie jonction, ou si CPython change d'avis sur son compte."""

    @unittest.skipUnless(_IS_WINDOWS, "semantique NTFS : jonction reelle")
    def test_une_jonction_nest_pas_exclue_par_le_filtre_historique(self) -> None:
        """L'issue se trompe de cause : `follow_symlinks=False` LAISSE PASSER
        la jonction. Le defaut est ailleurs (cf. test suivant)."""
        lien = self.root / "Attache"
        _make_junction(lien, self.externe)

        with os.scandir(self.root) as scanner:
            entree = next(e for e in scanner if e.name == "Attache")
            self.assertTrue(entree.is_dir(follow_symlinks=False), "la jonction se presente comme un dossier ordinaire")
            self.assertFalse(entree.is_symlink(), "une jonction n'est pas un symlink pour CPython")
            self.assertTrue(entree.is_junction(), "is_junction() est le seul detecteur sans syscall")

    @unittest.skipUnless(_IS_WINDOWS, "semantique NTFS : jonction reelle")
    def test_le_cache_de_scandir_ne_suit_jamais_la_cible_dune_jonction(self) -> None:
        """La cause reelle du silence : `entry.stat()` rend le mtime du LIEN.

        L'egalite `cache_apres == cache_avant` est l'ancrage : elle ne depend
        d'aucune granularite d'horloge. Le `sleep` de 50 ms qui la precede met
        les deux dates hors de portee du pas de l'horloge Windows (~15 ms), et
        celui de 1,5 s laisse au cache d'annuaire NTFS le temps de se
        rafraichir — il le fait pour un dossier reel, jamais pour une jonction.
        """
        lien = self.root / "Attache"
        _make_junction(lien, self.externe)
        cache_avant = _mtime_du_cache(self.root, "Attache")
        time.sleep(0.05)

        (self.externe / "Nouveau Film (2024)").mkdir()
        time.sleep(1.5)

        cache_apres = _mtime_du_cache(self.root, "Attache")
        reel = int(os.stat(str(self.externe)).st_mtime_ns)
        self.assertEqual(cache_apres, cache_avant, "le cache reste fige sur le mtime du lien")
        self.assertNotEqual(cache_apres, reel, "il ne suit donc jamais la cible")
        self.assertEqual(reel, int(os.stat(str(lien)).st_mtime_ns), "os.stat, lui, suit la jonction")


class SuiviDeLaCibleTests(_SandboxCase):
    """Le snapshot doit enregistrer le mtime de la CIBLE, pas celui du lien."""

    def test_le_mtime_enregistre_est_celui_de_la_cible(self) -> None:
        lien = self.root / "Attache"
        _make_junction(lien, self.externe)
        (self.externe / "Nouveau Film (2024)").mkdir()

        snapshot = watcher._snapshot_root(self.root)

        self.assertEqual(_noms(snapshot), {"Attache"})
        self.assertEqual(_mtime(snapshot, "Attache"), int(os.stat(str(self.externe)).st_mtime_ns))

    def test_un_ajout_dans_la_branche_attachee_est_detecte(self) -> None:
        """Le symptome decrit par l'issue, de bout en bout."""
        _make_junction(self.root / "Attache", self.externe)
        avant = watcher._snapshot_all([self.root])
        time.sleep(0.05)

        (self.externe / "Nouveau Film (2024)").mkdir()

        apres = watcher._snapshot_all([self.root])
        change, detail = watcher._has_changed(avant, apres)
        self.assertTrue(change, f"avant={sorted(avant[str(self.root)])} apres={sorted(apres[str(self.root)])}")
        self.assertIn(str(self.root), detail)

    def test_un_lien_symbolique_de_dossier_est_surveille(self) -> None:
        """`follow_symlinks=False` les rendait purement invisibles."""
        lien = self.root / "LienSymbolique"
        if not _try_symlink(lien, self.externe, directory=True):
            self.skipTest("creation de lien symbolique refusee par le systeme")

        snapshot = watcher._snapshot_root(self.root)

        self.assertEqual(_noms(snapshot), {"LienSymbolique"})
        self.assertEqual(_mtime(snapshot, "LienSymbolique"), int(os.stat(str(self.externe)).st_mtime_ns))

    def test_un_lien_vers_un_fichier_nentre_pas_dans_le_snapshot(self) -> None:
        """Le watcher surveille des dossiers : un lien vers un fichier n'en est pas un."""
        cible = self.externe / "film.mkv"
        cible.write_bytes(b"VIDEO")
        lien = self.root / "raccourci.mkv"
        if not _try_symlink(lien, cible, directory=False):
            self.skipTest("creation de lien symbolique refusee par le systeme")

        self.assertEqual(_noms(watcher._snapshot_root(self.root)), set())


class DuplicationTests(_SandboxCase):
    """Aucune garde naturelle ne detecte une jonction : le meme dossier atteint
    par deux chemins etait compte deux fois."""

    def test_le_meme_dossier_physique_nest_compte_quune_fois(self) -> None:
        films = self.root / "Films"
        films.mkdir()
        _make_junction(self.root / "Raccourci", films)

        self.assertEqual(_noms(watcher._snapshot_root(self.root)), {"Films"})

    def test_cest_le_nom_du_dossier_reel_qui_survit(self) -> None:
        """Le lien trie AVANT le dossier reel par ordre alphabetique : c'est
        pourtant le nom que l'utilisateur reconnait qui doit rester."""
        films = self.root / "Films"
        films.mkdir()
        _make_junction(self.root / "AAA_Raccourci", films)

        self.assertEqual(_noms(watcher._snapshot_root(self.root)), {"Films"})

    def test_entre_deux_liens_equivalents_le_choix_est_deterministe(self) -> None:
        """`os.scandir` ne garantit aucun ordre. Un choix qui en dependrait
        ferait varier le snapshot d'un poll a l'autre, donc un faux changement,
        donc un scan automatique pour rien a chaque intervalle."""
        _make_junction(self.root / "ZZZ_lien", self.externe)
        _make_junction(self.root / "AAA_lien", self.externe)

        self.assertEqual(_noms(watcher._snapshot_root(self.root)), {"AAA_lien"})

    def test_le_snapshot_ne_depend_pas_de_lordre_du_systeme_de_fichiers(self) -> None:
        """Deux polls successifs doivent rendre le MEME snapshot, quel que soit
        l'ordre d'enumeration : sinon le watcher fabrique un changement."""
        (self.root / "Films").mkdir()
        _make_junction(self.root / "ZZZ_lien", self.externe)
        _make_junction(self.root / "AAA_lien", self.externe)

        ordre_disque = watcher._snapshot_root(self.root)
        with mock.patch.object(watcher.os, "scandir", _scandir_inverse):
            ordre_inverse = watcher._snapshot_root(self.root)

        self.assertEqual(ordre_disque, ordre_inverse)

    def test_une_jonction_vers_le_root_lui_meme_est_ignoree(self) -> None:
        films = self.root / "Films"
        films.mkdir()
        _make_junction(self.root / "Boucle", self.root)

        self.assertEqual(_noms(watcher._snapshot_root(self.root)), {"Films"})

    def test_deux_roots_qui_designent_le_meme_dossier_ne_sont_lus_quune_fois(self) -> None:
        films = self.base / "Films"
        films.mkdir()
        (films / "Dune (2021)").mkdir()
        lien = self.base / "Raccourci"
        _make_junction(lien, films)

        snapshots = watcher._snapshot_all([films, lien])

        self.assertEqual(list(snapshots), [str(films)])

    def test_un_root_reste_lu_si_son_identite_est_illisible(self) -> None:
        """Sens permissif : sur un doute, on continue de surveiller."""
        films = self.base / "Films"
        films.mkdir()
        (films / "Dune (2021)").mkdir()
        lien = self.base / "Raccourci"
        _make_junction(lien, films)

        with mock.patch.object(watcher, "_stat_cible", return_value=None):
            snapshots = watcher._snapshot_all([films, lien])

        self.assertEqual(sorted(snapshots), sorted([str(films), str(lien)]))


class JamaisRenoncerTests(_SandboxCase):
    """Une information manquante ne doit jamais faire disparaitre une branche du
    snapshot : ce serait annonce comme une suppression, donc un scan pour rien."""

    def test_un_lien_dont_la_cible_est_injoignable_reste_surveille(self) -> None:
        lien = self.root / "DisqueEteint"
        _make_junction(lien, self.externe)
        shutil.rmtree(self.externe)  # la cible disparait : os.stat echoue

        snapshot = watcher._snapshot_root(self.root)

        self.assertEqual(_noms(snapshot), {"DisqueEteint"})
        self.assertEqual(_mtime(snapshot, "DisqueEteint"), 0)

    def test_un_systeme_de_fichiers_sans_inode_ne_fait_disparaitre_personne(self) -> None:
        """`st_ino == 0` (partage qui ne renseigne pas l'inode) : le couple ne
        distingue plus rien et deviendrait un faux « deja vu ». Les DEUX liens
        visent des dossiers differents : aucun ne doit disparaitre."""
        films = self.root / "Films"
        films.mkdir()
        autre = self.base / "AUTRE_DISQUE_2"
        autre.mkdir()
        _make_junction(self.root / "Externe", self.externe)
        _make_junction(self.root / "ExterneBis", autre)
        vrai_stat = watcher._stat_cible

        def _sans_inode(chemin: str):
            st = vrai_stat(chemin)
            if st is None:
                return None
            return SimpleNamespace(st_dev=st.st_dev, st_ino=0, st_mode=st.st_mode, st_mtime_ns=st.st_mtime_ns)

        with mock.patch.object(watcher, "_stat_cible", side_effect=_sans_inode):
            snapshot = watcher._snapshot_root(self.root)

        self.assertEqual(_noms(snapshot), {"Films", "Externe", "ExterneBis"})

    def test_identite_physique_rend_none_quand_elle_ne_dit_rien(self) -> None:
        self.assertIsNone(watcher._identite_physique(None))
        self.assertIsNone(
            watcher._identite_physique(SimpleNamespace(st_dev=7, st_ino=0)),  # type: ignore[arg-type]
        )

    def test_identite_physique_confond_une_jonction_et_sa_cible(self) -> None:
        lien = self.root / "Attache"
        _make_junction(lien, self.externe)

        self.assertEqual(
            watcher._identite_physique(watcher._stat_cible(str(lien))),
            watcher._identite_physique(watcher._stat_cible(str(self.externe))),
        )
        self.assertIsNotNone(watcher._identite_physique(watcher._stat_cible(str(self.externe))))


class NonRegressionTests(_SandboxCase):
    """Le cas courant — aucun lien — doit rester exactement ce qu'il etait."""

    def test_dossiers_ordinaires_noms_et_mtimes(self) -> None:
        for nom in ("Dune (2021)", "Avatar (2009)"):
            (self.root / nom).mkdir()
        (self.root / "poster.jpg").write_bytes(b"IMG")

        snapshot = watcher._snapshot_root(self.root)

        self.assertEqual(_noms(snapshot), {"Dune (2021)", "Avatar (2009)"})
        for nom in ("Dune (2021)", "Avatar (2009)"):
            self.assertGreater(_mtime(snapshot, nom) or 0, 0)

    def test_les_buckets_internes_restent_ignores(self) -> None:
        (self.root / "_Doublons").mkdir()
        (self.root / "Films").mkdir()
        _make_junction(self.root / "_Attache", self.externe)

        self.assertEqual(_noms(watcher._snapshot_root(self.root)), {"Films"})

    def test_un_root_absent_rend_un_snapshot_vide(self) -> None:
        self.assertEqual(watcher._snapshot_root(self.base / "jamais_existe"), frozenset())

    def test_un_changement_ordinaire_reste_detecte(self) -> None:
        (self.root / "Dune (2021)").mkdir()
        avant = watcher._snapshot_all([self.root])

        (self.root / "Avatar (2009)").mkdir()

        change, detail = watcher._has_changed(avant, watcher._snapshot_all([self.root]))
        self.assertTrue(change)
        self.assertIn("+1", detail)

    def test_un_dossier_reel_nest_jamais_retire_par_la_deduplication(self) -> None:
        """Garde-fou inverse : la garde ne doit pas amputer la bibliotheque."""
        for nom in ("Dune (2021)", "Avatar (2009)", "Films"):
            (self.root / nom).mkdir()
        _make_junction(self.root / "Raccourci", self.root / "Films")

        self.assertEqual(_noms(watcher._snapshot_root(self.root)), {"Dune (2021)", "Avatar (2009)", "Films"})


class EstLienTests(_SandboxCase):
    """Le classement lien/dossier reel decide de tout le reste."""

    def test_un_dossier_ordinaire_nest_pas_un_lien(self) -> None:
        (self.root / "Films").mkdir()
        with os.scandir(self.root) as scanner:
            self.assertFalse(watcher._est_lien(next(iter(scanner))))

    def test_une_jonction_est_un_lien(self) -> None:
        _make_junction(self.root / "Attache", self.externe)
        with os.scandir(self.root) as scanner:
            self.assertTrue(watcher._est_lien(next(iter(scanner))))

    def test_une_entree_illisible_est_traitee_comme_un_lien(self) -> None:
        """Sens qui CONTINUE de surveiller : la branche « lien » relit la cible."""
        entree = SimpleNamespace(
            name="Illisible",
            is_symlink=mock.Mock(side_effect=OSError("ACL")),
            is_junction=mock.Mock(return_value=False),
        )
        self.assertTrue(watcher._est_lien(entree))  # type: ignore[arg-type]


class StatCibleTests(_SandboxCase):
    def test_stat_cible_suit_le_lien(self) -> None:
        lien = self.root / "Attache"
        _make_junction(lien, self.externe)
        st = watcher._stat_cible(str(lien))
        self.assertIsNotNone(st)
        assert st is not None
        self.assertTrue(stat.S_ISDIR(st.st_mode))

    def test_stat_cible_rend_none_sur_un_chemin_absent(self) -> None:
        self.assertIsNone(watcher._stat_cible(str(self.base / "jamais_existe")))


if __name__ == "__main__":
    unittest.main()
