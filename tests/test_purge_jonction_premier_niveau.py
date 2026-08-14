"""Une jonction de PREMIER NIVEAU du bucket n'est ni traversee ni supprimee.

Trou de la garde posee par #941. Cette garde vit dans
`_descendre_sans_franchir_les_jonctions`, qui ne teste que les dossiers
DECOUVERTS pendant son parcours — jamais la racine qu'on lui donne. Or la
production n'entre JAMAIS par le bucket entier :

    # purge_review_bucket / purge_review_bucket_all
    for child in root.iterdir():                       # <- enumeration NON gardee
        if child.is_dir() and child.name not in excluded:
            _purge_dir_recursive(child, ...)           # <- `child` devient la racine

Chaque enfant de premier niveau devient donc la racine d'un nouveau parcours,
c'est-a-dire le seul chemin ou la garde ne regarde pas. Un `iterdir()` sur une
jonction enumere sa CIBLE, et « Vider maintenant » passe `arrival_of=None` avec
un cutoff dans le futur : tout ce qui est atteignable est supprime.

POURQUOI LE TEST DE #941 RESTAIT VERT : il appelle
`_purge_dir_recursive(self.bucket, ...)`, c'est-a-dire avec le BUCKET pour
racine. Sous cette forme la jonction est un enfant decouvert, donc gardee. Mais
aucune fonction de production n'appelle `_purge_dir_recursive` sur le bucket :
les deux purges lui passent toujours un sous-dossier. Le harnais ne reproduisait
pas la production.

Ces tests-ci entrent donc par `purge_review_bucket_all(cfg)` et
`purge_review_bucket(cfg, ttl_days=...)` — les deux seules portes reelles.

`Path.is_symlink()` ne suffit PAS sous Windows : il rend False pour une
jonction. C'est la raison d'etre de `is_reparse_point`.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cinesort.app import quarantine_ttl
from cinesort.app._dir_utils import is_reparse_point


def _second_chemin(lien: Path, cible: Path) -> bool:
    """Second chemin vers `cible` : jonction sur Windows, lien symbolique ailleurs.

    `mklink /J` ne demande aucun privilege particulier, donc fonctionne sur le
    runner Windows de la CI. Rend False si rien n'aboutit, l'appelant saute
    alors le test.
    """
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(lien), str(cible)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return r.returncode == 0 and lien.exists()
    try:
        os.symlink(str(cible), str(lien), target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        return False
    return lien.exists()


class JonctionDePremierNiveauTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cs_jonction_n1_")
        self.base = Path(self._tmp.name)
        self.cfg = SimpleNamespace(root=self.base)
        self.bucket = self.base / quarantine_ttl.REVIEW_FOLDER_NAME
        self.bucket.mkdir()
        self.dehors = self.base / "bibliotheque"
        self.dehors.mkdir()
        self.precieux = self.dehors / "Film Precieux.mkv"
        self.precieux.write_bytes(b"x" * 2048)
        self.addCleanup(self._tmp.cleanup)

    def _poser_jonction_au_premier_niveau(self) -> Path:
        """La jonction est un ENFANT DIRECT de `_review/` — le cas de production.

        C'est ainsi qu'une jonction y arrive : `apply_core.quarantine_row`
        deplace le DOSSIER du film en entier sous `<root>/_review/`, et sur
        Windows `os.rename` deplace le point d'analyse lui-meme.
        """
        lien = self.bucket / "Raccourci"
        if not _second_chemin(lien, self.dehors):
            self.skipTest("jonction/lien impossible a creer (droits insuffisants)")
        self.assertTrue(is_reparse_point(lien), "le lien pose n'est pas un point d'analyse")
        return lien

    def test_vider_maintenant_ne_supprime_RIEN_a_travers_la_jonction(self) -> None:
        """LE CŒUR : « Vider maintenant » ne doit pas atteindre la cible."""
        self._poser_jonction_au_premier_niveau()

        res = quarantine_ttl.purge_review_bucket_all(self.cfg)

        self.assertTrue(
            self.precieux.exists(),
            "purge_review_bucket_all a supprime un fichier HORS du bucket, a travers la jonction",
        )
        self.assertEqual(self.precieux.stat().st_size, 2048, "fichier tronque a travers la jonction")
        self.assertEqual(res["deleted"], 0, f"des fichiers hors bucket ont ete comptes comme purges : {res}")

    def test_vider_maintenant_laisse_la_jonction_intacte(self) -> None:
        """`child.rmdir()` ne doit pas retirer le lien pose par l'utilisateur.

        Sous Windows, `rmdir` sur une jonction reussit et detruit le point
        d'analyse (la cible survit) : la trace du lien disparait sans que rien
        ne le signale. C'est l'invariant que #941 avait retenu — « on ne decide
        pas du sort d'un lien pose par l'utilisateur » — et que le premier
        niveau ne tenait pas.
        """
        lien = self._poser_jonction_au_premier_niveau()

        quarantine_ttl.purge_review_bucket_all(self.cfg)

        self.assertTrue(lien.exists(), "la jonction de premier niveau a ete supprimee")
        self.assertTrue(is_reparse_point(lien), "la jonction a ete remplacee par un dossier reel")

    def test_le_cron_ttl_laisse_la_jonction_intacte(self) -> None:
        """Meme invariant sur l'autre porte : le cron 24 h.

        Le TTL ne supprime pas les fichiers de la cible (ils sont absents du
        manifeste d'arrivee, donc dates a `now`), mais il atteignait quand meme
        `child.rmdir()`.
        """
        lien = self._poser_jonction_au_premier_niveau()

        quarantine_ttl.purge_review_bucket(self.cfg, ttl_days=30)

        self.assertTrue(lien.exists(), "le cron TTL a supprime la jonction de premier niveau")
        self.assertTrue(self.precieux.exists(), "le cron TTL a supprime un fichier hors du bucket")

    def test_le_LISTAGE_ne_compte_pas_la_cible_de_la_jonction(self) -> None:
        """Le total annonce AVANT la confirmation de suppression ne doit pas etre gonfle.

        NON DISCRIMINANT pour le correctif de ce fichier, et c'est dit :
        `list_review_bucket_files` entre par le bucket, donc la jonction y est
        un enfant DECOUVERT — deja couvert par #941. Ce test verrouille que le
        correctif du premier niveau n'a rien casse de ce cote.
        """
        self._poser_jonction_au_premier_niveau()

        inventaire = quarantine_ttl.list_review_bucket_files(self.cfg)

        noms = {entry["rel"] for entry in inventaire["files"]}
        self.assertFalse(
            any("Film Precieux.mkv" in nom for nom in noms),
            f"un fichier hors du bucket est compte dans la quarantaine : {sorted(noms)}",
        )
        self.assertEqual(inventaire["purge_scope_files_count"], 0)

    def test_le_contenu_REEL_du_bucket_reste_purge(self) -> None:
        """Contre-epreuve : la garde ne doit pas eteindre la purge legitime.

        Sans elle, un correctif qui refuserait TOUT enfant de premier niveau
        laisserait ce test vert cote « rien hors bucket » tout en cassant la
        fonctionnalite.
        """
        self._poser_jonction_au_premier_niveau()
        vrai = self.bucket / "Un Film (2019)"
        vrai.mkdir()
        jetable = vrai / "jetable.mkv"
        jetable.write_bytes(b"y" * 512)

        res = quarantine_ttl.purge_review_bucket_all(self.cfg)

        self.assertFalse(jetable.exists(), "la garde a empeche la purge du contenu LEGITIME")
        self.assertEqual(res["deleted"], 1, f"le compte des suppressions reelles est faux : {res}")
        self.assertTrue(self.precieux.exists(), "le fichier hors bucket a disparu")


if __name__ == "__main__":
    unittest.main()
