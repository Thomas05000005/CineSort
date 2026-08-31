"""Le repli de `default_state_dir()` ne doit JAMAIS etre relatif.

Il valait `"."`, donc `./CineSort` quand `LOCALAPPDATA` est absent. La base, les
runs et les journaux suivaient alors le REPERTOIRE COURANT : lancer
l'application depuis un autre dossier ouvrait silencieusement une AUTRE base —
ni erreur, ni migration, juste une bibliotheque qui a l'air neuve.

`LOCALAPPDATA` est toujours pose sur un poste Windows interactif, mais pas
necessairement dans un service, une tache planifiee ou un conteneur. Et cette
fonction a **133 sites d'appel** : c'est la racine de tout l'etat.

Ce fichier eprouve la PROPRIETE (« absolu, et stable quel que soit le repertoire
de lancement »), pas la valeur exacte du repli — un test qui figerait `~/CineSort`
rougirait au premier changement de politique sans rien prouver de plus.
"""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.infra.state import default_state_dir

_RACINE = Path(__file__).resolve().parents[1]

# Seuls fichiers autorises a lire `LOCALAPPDATA` directement.
#
# - `cinesort/infra/state.py` : LE producteur du repertoire d'etat, celui que
#   ce fichier eprouve plus haut.
# - `cinesort/infra/probe/tools_manager.py` : ne construit PAS un chemin d'etat
#   CineSort mais `%LOCALAPPDATA%/Microsoft/WinGet/Packages`, pour retrouver un
#   binaire installe par winget. Il porte deja sa propre garde
#   (`if local_appdata else None`), donc aucun repli relatif.
# - `cinesort/app/plugin_hooks.py` : `LOCALAPPDATA` y est une ENTREE de la liste
#   blanche d'environnement transmise aux plugins tiers (cf #1098, qui en a
#   retire PYTHONPATH/PYTHONHOME). Aucun chemin n'y est construit.
_LECTEURS_AUTORISES = {
    "cinesort/infra/state.py",
    "cinesort/infra/probe/tools_manager.py",
    "cinesort/app/plugin_hooks.py",
}


class LeRepliEstABSOLUTests(unittest.TestCase):
    def test_sans_LOCALAPPDATA_le_chemin_reste_absolu(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOCALAPPDATA", None)
            chemin = default_state_dir()
        self.assertTrue(
            chemin.is_absolute(),
            f"le repli est RELATIF ({chemin}) : la base suivrait le repertoire de lancement",
        )

    def test_le_repli_ne_DEPEND_PAS_du_repertoire_courant(self) -> None:
        """LA propriete qui compte. Un `Path('.')` est deja « resolu » en absolu
        par `Path.cwd()` chez certains appelants : seule la STABILITE entre deux
        repertoires de lancement distingue le repli sain du repli fautif."""
        depart = Path.cwd()
        with tempfile.TemporaryDirectory(prefix="cs_cwd_a_") as a, tempfile.TemporaryDirectory(prefix="cs_cwd_b_") as b:
            try:
                with mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("LOCALAPPDATA", None)
                    os.chdir(a)
                    depuis_a = default_state_dir().resolve()
                    os.chdir(b)
                    depuis_b = default_state_dir().resolve()
            finally:
                os.chdir(depart)

        self.assertEqual(
            depuis_a,
            depuis_b,
            f"le repertoire d'etat CHANGE avec le repertoire de lancement : {depuis_a} vs {depuis_b}",
        )

    def test_avec_LOCALAPPDATA_rien_ne_change(self) -> None:
        """CONTRE-EPREUVE : le chemin nominal — celui de 100 % des postes
        Windows interactifs — doit rester exactement le meme."""
        with tempfile.TemporaryDirectory(prefix="cs_lad_") as tmp:
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                self.assertEqual(default_state_dir(), Path(tmp) / "CineSort")


class AucuneREIMPLEMENTATIONDuRepertoireDEtatTests(unittest.TestCase):
    """Le garde ci-dessus est JUSTE, et son perimetre etait TROP ETROIT.

    Il eprouve `default_state_dir()`. Il ne pouvait donc pas voir les sites qui
    REFONT le meme calcul a la main — et il y en avait **neuf** :

        app.py                          6  (crash de demarrage, journal x2,
                                            webview2_userdata, storage webview,
                                            purge EBWebView, verrou d'instance)
        cinesort/ui/api/cinesort_api.py 2  (chemin des logs affiche, et ouvert)
        cinesort/ui/api/reset_support.py 1 (defauts de la reinitialisation)

    Chacun valait `Path(os.environ.get("LOCALAPPDATA", ".")) / "CineSort"`, ou
    `os.path.join(os.environ.get("LOCALAPPDATA", ""), "CineSort", ...)` : sans
    `LOCALAPPDATA`, exactement le chemin RELATIF que #1074 a supprime de
    `default_state_dir()`. Deux consequences mesurees :

    - `app.py` donnait ce chemin a `InstanceLock`, alors que `CineSortApi` ouvre
      la base sur `default_state_dir()` (ABSOLU). Le verrou anti-double-instance
      ne gardait donc plus la base qu'il protege : deux lancements depuis deux
      repertoires prenaient deux verrous distincts sur une base unique.
    - `_shutil.rmtree` (purge du cache WebView2) portait sur un chemin dependant
      du repertoire de lancement.

    Ce test est STATIQUE a dessein : il lit les sources, n'importe aucun module
    applicatif, et rougit donc meme si la regression vit dans `app.py`.
    """

    def _fichiers_de_production(self) -> list[Path]:
        fichiers = [_RACINE / "app.py"]
        fichiers.extend(sorted((_RACINE / "cinesort").rglob("*.py")))
        return [f for f in fichiers if f.is_file()]

    def test_seul_default_state_dir_lit_LOCALAPPDATA(self) -> None:
        """AST, pas grep : une mention en commentaire ou en docstring est
        legitime (elle DECRIT le chemin nominal) et ne doit pas rougir."""
        coupables: list[str] = []
        for fichier in self._fichiers_de_production():
            relatif = fichier.relative_to(_RACINE).as_posix()
            if relatif in _LECTEURS_AUTORISES:
                continue
            arbre = ast.parse(fichier.read_text(encoding="utf-8", errors="replace"))
            for noeud in ast.walk(arbre):
                if isinstance(noeud, ast.Constant) and noeud.value == "LOCALAPPDATA":
                    coupables.append(f"{relatif}:{noeud.lineno}")

        self.assertEqual(
            [],
            coupables,
            "le repertoire d'etat se reconstruit a la main ici — utiliser "
            "`cinesort.infra.state.default_state_dir()`, seul endroit ou le repli "
            f"est garanti ABSOLU (cf #1074) : {coupables}",
        )

    def test_le_lecteur_de_logs_pointe_la_ou_l_ecrivain_ecrit(self) -> None:
        """La propriete qui compte pour l'utilisateur.

        `app.py` passe `default_state_dir() / "logs"` a `install_rotating_log` ;
        la visionneuse (`runtime_support._logs_dir`) doit resoudre le MEME
        dossier. Elles divergeaient sans `LOCALAPPDATA` : l'ecrivain sur
        `./CineSort/logs`, le lecteur sur `~/AppData/Local/CineSort/logs`.
        """
        from cinesort.ui.api import runtime_support

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOCALAPPDATA", None)
            lecteur = runtime_support._logs_dir()
            ecrivain = default_state_dir() / "logs"

        self.assertTrue(lecteur.is_absolute(), f"le dossier de logs lu est RELATIF : {lecteur}")
        self.assertEqual(
            ecrivain,
            lecteur,
            f"la visionneuse lit {lecteur} alors que le journal est ecrit dans {ecrivain}",
        )


if __name__ == "__main__":
    unittest.main()
