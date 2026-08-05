"""La purge TTL ne doit RIEN supprimer hors du bucket de quarantaine.

Issue #941. `quarantine_ttl` est le SEUL chemin de suppression recursive
automatique du depot (cron 24 h + bouton « Vider maintenant »), et c'etait le
seul sans garde de point d'analyse NTFS. Mesure sur `origin/main` :

    apply_core.py    : 5 appels de is_reparse_point
    cleanup.py       : 6 appels
    quarantine_ttl.py: 0  -- il n'importait meme pas le helper

`Path.rglob` SUIT les jonctions. Une jonction posee sous `_review/` faisait
donc supprimer les fichiers de sa CIBLE — dans la bibliotheque de
l'utilisateur, hors du bucket.

Le listage etait touche aussi : il alimente le manifeste TTL et le total
« N fichiers, X Go » affiche AVANT la confirmation de suppression.

`Path.is_symlink()` ne suffit PAS : il rend False pour une jonction Windows.
C'est la raison d'etre de `is_reparse_point`.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from cinesort.app import quarantine_ttl
from cinesort.app._dir_utils import is_reparse_point


def _creer_jonction(lien: Path, cible: Path) -> bool:
    """Cree une VRAIE jonction NTFS. False si impossible (non-Windows, droits)."""
    if sys.platform != "win32":
        return False
    r = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(lien), str(cible)],
        capture_output=True,
        text=True,
        shell=False,
    )
    return r.returncode == 0 and lien.exists()


class PurgeTtlJonctionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cs_941_")
        self.base = Path(self._tmp.name)
        self.bucket = self.base / "_review"
        self.bucket.mkdir()
        self.dehors = self.base / "bibliotheque"
        self.dehors.mkdir()
        self.precieux = self.dehors / "Film Precieux.mkv"
        self.precieux.write_bytes(b"x" * 2048)
        self.addCleanup(self._tmp.cleanup)

    def _poser_jonction(self) -> Path:
        lien = self.bucket / "raccourci"
        if not _creer_jonction(lien, self.dehors):
            self.skipTest("jonction NTFS impossible a creer (non-Windows ou droits insuffisants)")
        self.assertTrue(is_reparse_point(lien), "mklink /J n'a pas produit un point d'analyse")
        return lien

    def test_la_purge_ne_supprime_RIEN_a_travers_une_jonction(self) -> None:
        """LE CŒUR : le fichier hors du bucket doit survivre."""
        self._poser_jonction()
        # cutoff dans le FUTUR : tout ce qui est atteignable serait supprime.
        quarantine_ttl._purge_dir_recursive(self.bucket, cutoff_ts=time.time() + 86400, dry_run=False)

        self.assertTrue(
            self.precieux.exists(),
            "la purge a supprime un fichier HORS du bucket, a travers la jonction",
        )
        self.assertEqual(self.precieux.stat().st_size, 2048, "fichier tronque a travers la jonction")

    def test_la_jonction_elle_meme_est_LAISSEE_intacte(self) -> None:
        """Sens RESTRICTIF : on ne decide pas du sort d'un lien pose par l'utilisateur.

        La supprimer serait sans danger pour sa cible, mais ce n'est pas le
        role de cette garde — et une suppression de plus sur un chemin
        destructif se justifie, elle ne se suppose pas.
        """
        lien = self._poser_jonction()
        quarantine_ttl._purge_dir_recursive(self.bucket, cutoff_ts=time.time() + 86400, dry_run=False)
        self.assertTrue(lien.exists(), "la jonction a ete supprimee alors qu'on ne fait que refuser de la suivre")

    def test_le_LISTAGE_ne_compte_pas_les_fichiers_de_la_cible(self) -> None:
        """Le total affiche AVANT « Vider maintenant » ne doit pas etre gonfle.

        Ce listage alimente aussi le manifeste TTL, donc ce que la purge
        considerera ensuite.
        """
        self._poser_jonction()
        listes = quarantine_ttl._iter_review_files(self.bucket)
        noms = {p.name for p in listes}
        self.assertNotIn(
            "Film Precieux.mkv",
            noms,
            f"un fichier hors du bucket est compte dans la quarantaine : {sorted(noms)}",
        )

    def test_le_contenu_REEL_du_bucket_est_bien_purge(self) -> None:
        """Contre-epreuve : la garde ne doit pas empecher la purge legitime."""
        vrai = self.bucket / "sous-dossier"
        vrai.mkdir()
        jetable = vrai / "vieux.mkv"
        jetable.write_bytes(b"y" * 512)

        stats = quarantine_ttl._purge_dir_recursive(self.bucket, cutoff_ts=time.time() + 86400, dry_run=False)

        self.assertFalse(jetable.exists(), "la garde a empeche la purge du contenu LEGITIME")
        self.assertGreaterEqual(stats["deleted"], 1)


if __name__ == "__main__":
    unittest.main()
