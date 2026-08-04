"""Issue #888 : un dossier atteignable par deux chemins ne doit etre scanne qu'une fois.

Aucune garde « naturelle » ne detecte une jonction NTFS : `is_symlink()` rend False
(delibere depuis Python 3.8), `is_dir()` rend True, et `os.walk`/`rglob` descendent.
Consequence mesuree avant correctif, avec de vraies jonctions `mklink /J` :

    Bibliotheque/Raccourci -> Bibliotheque/Films
      candidat : Films\\Dune (2021)
      candidat : Raccourci\\Dune (2021)      <- 1 seul realpath pour 2 candidats

Ce ne sont pas deux films qui se ressemblent : c'est le MEME dossier compte deux
fois. L'ecran Doublons propose alors de « supprimer le doublon » d'un fichier
unique, et un apply qui deplace par un chemin casse l'autre.

ARBITRAGE DU PROPRIETAIRE, verrouille par `test_dossier_externe_reste_scanne` :
le scan doit CONTINUER de descendre dans les jonctions. Analyser est la raison
d'etre de l'application ; monter un disque mutualise dans la bibliotheque via
`mklink /J` est un usage legitime dont les films doivent rester visibles. La
correction ne retire donc aucune decouverte : elle supprime seulement la SECONDE
visite d'un dossier physique deja vu.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
import cinesort.domain.scan_helpers as core_scan_helpers


def _second_chemin(lien: Path, cible: Path) -> bool:
    """Cree un SECOND chemin vers `cible`, par le meilleur moyen disponible.

    Windows : jonction `mklink /J` — elle ne demande AUCUN privilege particulier,
    contrairement aux liens symboliques, donc elle fonctionne sur le runner de CI.
    Ailleurs : lien symbolique de repertoire, que `os.stat` suit de la meme facon.

    Rend False si aucun des deux n'aboutit ; l'appelant saute alors le test plutot
    que de le faire passer sur un montage qui n'existe pas.
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


def _film(dossier: Path, nom: str) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f"{nom}.mkv").write_bytes(b"\x00" * 4096)


class ScanJonctionsDoublonsTests(unittest.TestCase):
    def _decouvrir(self, root: Path) -> list[Path]:
        cfg = core.Config(root=root, enable_tmdb=False).normalized()
        with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
            return core_scan_helpers.discover_candidate_folders(cfg)

    def test_jonction_vers_un_frere_ne_duplique_pas_le_film(self) -> None:
        """`Raccourci -> Films` : `Dune (2021)` ne doit sortir qu'une fois."""
        with tempfile.TemporaryDirectory(prefix="jonc_frere_") as tmp:
            root = Path(tmp) / "Bibliotheque"
            _film(root / "Films" / "Dune (2021)", "Dune.2021")
            if not _second_chemin(root / "Raccourci", root / "Films"):
                self.skipTest("impossible de creer un second chemin vers un dossier")

            cands = self._decouvrir(root)

            self.assertEqual(len(cands), 1, f"attendu 1 candidat, obtenu {cands}")
            # Preuve independante du comptage : un seul dossier PHYSIQUE.
            reels = {os.path.realpath(str(c)) for c in cands}
            self.assertEqual(len(reels), 1)

    def test_le_chemin_reel_est_prefere_au_lien(self) -> None:
        """A egalite, c'est `Films\\...` qui sort, pas `Raccourci\\...`.

        `os.scandir` ne garantit aucun ordre — mesure faite, il a rendu le lien
        AVANT le dossier reel. Sans tri, le plan afficherait a l'utilisateur un
        chemin qu'il ne reconnait pas, sur un ecran dont l'action deplace des
        dossiers sur son disque.
        """
        with tempfile.TemporaryDirectory(prefix="jonc_ordre_") as tmp:
            root = Path(tmp) / "Bibliotheque"
            _film(root / "Films" / "Dune (2021)", "Dune.2021")
            # Nom choisi pour trier AVANT "Films" alphabetiquement : si le tri par
            # nature n'existait pas, ce lien pourrait gagner.
            if not _second_chemin(root / "AAA_lien", root / "Films"):
                self.skipTest("impossible de creer un second chemin vers un dossier")

            cands = self._decouvrir(root)

            self.assertEqual(len(cands), 1)
            self.assertIn("Films", cands[0].parts)
            self.assertNotIn("AAA_lien", cands[0].parts)

    def test_jonction_vers_un_ancetre_ne_multiplie_pas_le_film(self) -> None:
        """`SousDossier/retour -> racine` : le film ne sort qu'une fois.

        Sans garde, `max_depth` borne la descente (donc pas de boucle infinie)
        mais le meme film ressortait 4 fois.
        """
        with tempfile.TemporaryDirectory(prefix="jonc_ancetre_") as tmp:
            root = Path(tmp) / "Bibliotheque"
            _film(root / "Avatar (2009)", "Avatar.2009")
            (root / "SousDossier").mkdir(parents=True, exist_ok=True)
            if not _second_chemin(root / "SousDossier" / "retour", root):
                self.skipTest("impossible de creer un second chemin vers un dossier")

            cands = self._decouvrir(root)

            self.assertEqual(len(cands), 1, f"attendu 1 candidat, obtenu {cands}")

    def test_jonction_bouclante_ne_multiplie_pas_le_film(self) -> None:
        """`lib/Boucle -> lib` : le scenario qui VIDAIT la bibliotheque.

        Verification en conditions reelles du 2026-08-04, sur `main` sans
        correctif, du scan jusqu'a l'undo :

            1 seul fichier video reel
              -> 7 lignes de plan (chemins reels distincts : 1)
              -> check_duplicates rend UN groupe de 6 membres pour ce fichier
              -> en designant un gagnant, l'apply REEL rend ok=true,
                 duplicates_user_decided_moved_count=1, AUCUNE erreur
              -> la bibliotheque contient alors ZERO video

        La bibliotheque se vidait donc avec un apply annonce reussi. L'undo la
        restaurait, mais encore fallait-il comprendre qu'il s'etait passe
        quelque chose.

        Ce test ferme le premier maillon : sans lignes en double, aucun groupe
        de doublons ne se forme, donc il n'y a plus rien a deplacer.
        """
        with tempfile.TemporaryDirectory(prefix="jonc_boucle_") as tmp:
            root = Path(tmp) / "lib"
            _film(root / "Dune (2021)", "Dune.2021")
            if not _second_chemin(root / "Boucle", root):
                self.skipTest("impossible de creer un second chemin vers un dossier")

            cands = self._decouvrir(root)

            reels = {os.path.realpath(str(c)) for c in cands}
            self.assertEqual(len(reels), 1, "un seul fichier physique dans ce bac a sable")
            self.assertEqual(
                len(cands),
                1,
                f"une jonction bouclante ne doit pas multiplier le film : {cands}",
            )

    def test_lien_pointant_droit_sur_un_dossier_annee_ne_duplique_pas(self) -> None:
        """`Lien -> Films/Dune (2021)` : le raccourci `(YYYY)` doit aussi etre couvert.

        Ce chemin ajoute un candidat SANS passer par `_walk` : une garde posee
        uniquement en tete de la descente ne le verrait jamais.
        """
        with tempfile.TemporaryDirectory(prefix="jonc_annee_") as tmp:
            root = Path(tmp) / "Bibliotheque"
            _film(root / "Films" / "Dune (2021)", "Dune.2021")
            if not _second_chemin(root / "Lien", root / "Films" / "Dune (2021)"):
                self.skipTest("impossible de creer un second chemin vers un dossier")

            cands = self._decouvrir(root)

            reels = {os.path.realpath(str(c)) for c in cands}
            self.assertEqual(len(reels), 1, f"un seul dossier physique attendu, obtenu {cands}")
            self.assertEqual(len(cands), 1, f"attendu 1 candidat, obtenu {cands}")

    def test_dossier_externe_reste_scanne(self) -> None:
        """ARBITRAGE : un film derriere une jonction DOIT rester decouvert.

        Ce test existe pour empecher qu'on « corrige » un jour les jonctions en
        refusant d'y descendre. C'est l'usage principal vise : mutualiser un
        disque en le montant dans la bibliotheque. Le proprietaire a tranche
        explicitement le 2026-08-04 — analyser est le but de l'application.
        """
        with tempfile.TemporaryDirectory(prefix="jonc_externe_") as tmp:
            root = Path(tmp) / "Bibliotheque"
            externe = Path(tmp) / "AutreDisque"
            _film(root / "Inception (2010)", "Inception.2010")
            _film(externe / "Interstellar (2014)", "Interstellar.2014")
            if not _second_chemin(root / "monte", externe):
                self.skipTest("impossible de creer un second chemin vers un dossier")

            cands = self._decouvrir(root)
            noms = {c.name for c in cands}

            self.assertIn("Interstellar (2014)", noms, "le film derriere la jonction doit rester decouvert")
            self.assertIn("Inception (2010)", noms)
            self.assertEqual(len(cands), 2)

    def test_arborescence_sans_lien_est_inchangee(self) -> None:
        """Non-regression : sans lien, la garde ne doit rien retirer."""
        with tempfile.TemporaryDirectory(prefix="jonc_aucun_") as tmp:
            root = Path(tmp) / "Bibliotheque"
            for i in range(12):
                _film(root / "Films" / f"Film {i:02d} (20{i:02d})", f"Film.{i:02d}")

            cands = self._decouvrir(root)

            self.assertEqual(len(cands), 12)


if __name__ == "__main__":
    unittest.main()
