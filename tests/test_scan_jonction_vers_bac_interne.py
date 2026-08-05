"""Une jonction ne doit pas faire rentrer un bac INTERNE par la fenetre.

Trou de la garde d'identite posee par #893, trouve en resolvant un conflit sur
la PR#889. Le skip des dossiers de travail de CineSort (`_Collection`, `_Vide`,
`_review`, et tout prefixe `_` a la racine) se fait par NOM. Ces dossiers
n'entraient donc jamais dans l'ensemble des identites deja vues — et une
jonction portant un AUTRE nom, qui pointe dessus, les faisait scanner.

Mesure sur `main` avant correctif :

    Bibliotheque/_Collection/Deja Trie (2019)/Deja.Trie.2019.mkv
    Bibliotheque/Raccourci -> _Collection

    candidats : 2
       Dune (2021)
       Raccourci\\Deja Trie (2019)     <- un film DEJA trie, requalifie en candidat

Consequence : un film deja range ou quarantine redevient candidat au tri, et
l'apply peut le redeplacer. Le skip par NOM ne suffit pas : c'est le dossier
PHYSIQUE qu'il faut interdire, pas l'un de ses chemins d'acces.
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
    """Second chemin vers `cible` : jonction sur Windows, lien symbolique ailleurs.

    `mklink /J` ne demande aucun privilege particulier, donc fonctionne sur le
    runner de CI. Rend False si rien n'aboutit, l'appelant saute alors le test.
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
    (dossier / f"{nom}.mkv").write_bytes(nom.encode("utf-8") + b"\x00" * 4096)


class JonctionVersBacInterneTests(unittest.TestCase):
    def _decouvrir(self, root: Path) -> list[Path]:
        cfg = core.Config(root=root, enable_tmdb=False).normalized()
        with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
            return core_scan_helpers.discover_candidate_folders(cfg)

    def test_jonction_vers_collection_ne_ressort_pas_les_films_deja_tries(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jonc_bac_") as tmp:
            root = Path(tmp) / "Bibliotheque"
            _film(root / "Dune (2021)", "Dune.2021")
            _film(root / "_Collection" / "Deja Trie (2019)", "Deja.Trie.2019")
            if not _second_chemin(root / "Raccourci", root / "_Collection"):
                self.skipTest("impossible de creer un second chemin vers un dossier")

            cands = self._decouvrir(root)
            noms = sorted(c.name for c in cands)

            self.assertEqual(
                noms,
                ["Dune (2021)"],
                f"un bac interne est ressorti par la jonction : {[str(c) for c in cands]}",
            )

    def test_jonction_vers_un_dossier_underscore_quelconque(self) -> None:
        """Meme trou pour tout prefixe `_` a la racine, pas seulement _Collection."""
        with tempfile.TemporaryDirectory(prefix="jonc_underscore_") as tmp:
            root = Path(tmp) / "Bibliotheque"
            _film(root / "Dune (2021)", "Dune.2021")
            _film(root / "_A trier" / "En attente (2020)", "En.Attente.2020")
            if not _second_chemin(root / "Acces", root / "_A trier"):
                self.skipTest("impossible de creer un second chemin vers un dossier")

            cands = self._decouvrir(root)
            noms = sorted(c.name for c in cands)

            self.assertEqual(
                noms,
                ["Dune (2021)"],
                f"un dossier '_' est ressorti par la jonction : {[str(c) for c in cands]}",
            )

    def test_jonction_vers_un_dossier_collection_SANS_underscore(self) -> None:
        """Le nom du dossier collection est CONFIGURABLE, et peut ne pas commencer par '_'.

        Ce test existe parce qu'une mutation l'a exige. En retirant la garde de
        la branche `collection_root_name`, les autres tests restaient VERTS : le
        defaut `_Collection` commence par '_', donc la branche du prefixe
        l'attrapait avant. La seconde garde paraissait donc equivalente.

        Elle ne l'est pas : `collection_root_name` est expose a l'utilisateur
        (`settings_support.py`, clef `collection_folder_name`), et
        `core.Config.normalized()` n'impose aucun underscore — il ne fait que
        `windows_safe(...) or \"_Collection\"`. Un utilisateur qui nomme son
        dossier `Collection` sort donc entierement de la premiere branche.
        """
        with tempfile.TemporaryDirectory(prefix="jonc_collection_nom_") as tmp:
            root = Path(tmp) / "Bibliotheque"
            _film(root / "Dune (2021)", "Dune.2021")
            _film(root / "Collection" / "Deja Trie (2019)", "Deja.Trie.2019")
            if not _second_chemin(root / "Raccourci", root / "Collection"):
                self.skipTest("impossible de creer un second chemin vers un dossier")

            cfg = core.Config(root=root, enable_tmdb=False, collection_root_name="Collection").normalized()
            with mock.patch.object(core, "MIN_VIDEO_BYTES", 1):
                cands = core_scan_helpers.discover_candidate_folders(cfg)

            noms = sorted(c.name for c in cands)
            self.assertEqual(
                noms,
                ["Dune (2021)"],
                f"le bac collection est ressorti par la jonction : {[str(c) for c in cands]}",
            )

    def test_un_dossier_externe_legitime_reste_scanne(self) -> None:
        """ARBITRAGE preserve : seuls les bacs INTERNES sont fermes.

        Une jonction vers un disque mutualise doit toujours livrer ses films —
        c'est l'usage que le proprietaire a explicitement demande de conserver.
        """
        with tempfile.TemporaryDirectory(prefix="jonc_externe_") as tmp:
            root = Path(tmp) / "Bibliotheque"
            externe = Path(tmp) / "AutreDisque"
            _film(root / "Dune (2021)", "Dune.2021")
            _film(externe / "Interstellar (2014)", "Interstellar.2014")
            if not _second_chemin(root / "monte", externe):
                self.skipTest("impossible de creer un second chemin vers un dossier")

            noms = {c.name for c in self._decouvrir(root)}

            self.assertIn("Interstellar (2014)", noms, "le film externe a disparu")
            self.assertIn("Dune (2021)", noms)


if __name__ == "__main__":
    unittest.main()
