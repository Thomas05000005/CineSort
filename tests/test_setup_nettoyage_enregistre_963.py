"""Un `setUp` ne doit jamais pouvoir SAUTER en laissant un dossier derriere lui (#963).

Le defaut vise n'est pas « utiliser `tearDown` ». C'est la sequence precise :

    def setUp(self):
        self.tmp = tempfile.mkdtemp(...)   # le dossier existe
        ...
        self.skipTest("...")               # <- tearDown ne s'executera JAMAIS

`unittest` n'appelle `tearDown` que si `setUp` s'est termine normalement. Un
`skipTest` (ou un `pytest.skip`) apres la creation laisse donc le dossier, et
la boucle de #960 se referme : `%TEMP%` se remplit, et au-dela d'un seuil la
creation de dossiers temporaires echoue a son tour.

MESURE du 2026-08-05, sur les 51 appels de `skip` de `tests/` :

    46  dans un test          -> `tearDown` s'execute, aucune fuite
     3  dans un helper        -> hors sujet
     2  dans un `setUp`       -> mais les DEUX sont deja proteges

Autrement dit, **le depot est sain aujourd'hui** — et c'est precisement ce que
ce test verrouille. L'issue #963 supposait ~40 sites a convertir ; la mesure
montre qu'il n'y en a aucun a corriger, mais rien n'empechait le motif de
revenir. Ce garde coute une passe d'AST et ferme la porte.

Il porte sur la STRUCTURE (AST), pas sur une chaine de code source : il ne
tombe pas quand le code s'ameliore, et il detecte le motif quel que soit son
habillage — comme le fait deja `test_no_redundant_exception_handlers`.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_TESTS = Path(__file__).resolve().parent

#: Ce qui fait apparaitre un dossier temporaire qu'il faudra supprimer.
_CREATIONS = {"mkdtemp", "TemporaryDirectory"}
#: Ce qui interrompt `setUp` sans que `tearDown` ne soit jamais appele.
_SAUTS = {"skipTest", "skip"}


def _nom_appele(noeud: ast.Call) -> str:
    fonction = noeud.func
    if isinstance(fonction, ast.Attribute):
        return fonction.attr
    if isinstance(fonction, ast.Name):
        return fonction.id
    return ""


def _sequence(fonction: ast.FunctionDef) -> list[tuple[int, str]]:
    """Les evenements qui comptent, dans l'ordre du fichier."""
    evenements = [
        (noeud.lineno, _nom_appele(noeud))
        for noeud in ast.walk(fonction)
        if isinstance(noeud, ast.Call) and _nom_appele(noeud) in (_CREATIONS | _SAUTS | {"addCleanup"})
    ]
    return sorted(evenements)


def _fuites_possibles(chemin: Path) -> list[str]:
    """Signale tout `setUp` ou un saut suit une creation NON encore protegee."""
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    problemes: list[str] = []
    for classe in [n for n in ast.walk(arbre) if isinstance(n, ast.ClassDef)]:
        for methode in [m for m in classe.body if isinstance(m, ast.FunctionDef) and m.name == "setUp"]:
            en_attente: list[int] = []  # lignes des creations pas encore couvertes
            for ligne, nom in _sequence(methode):
                if nom in _CREATIONS:
                    en_attente.append(ligne)
                elif nom == "addCleanup":
                    # Un `addCleanup` couvre tout ce qui a ete cree avant lui :
                    # les rappels s'empilent et s'executent meme si `setUp`
                    # saute ensuite.
                    en_attente.clear()
                elif nom in _SAUTS and en_attente:
                    problemes.append(
                        f"{chemin.name}::{classe.name}.setUp : "
                        f"`{nom}` en ligne {ligne} apres une creation non protegee "
                        f"(ligne {en_attente[0]}) — `tearDown` ne s'executera pas, "
                        f"le dossier restera dans %TEMP%. Enregistrer le nettoyage "
                        f"par `addCleanup` JUSTE APRES la creation."
                    )
                    en_attente.clear()
    return problemes


class SetupNeSauteJamaisSansNettoyageTests(unittest.TestCase):
    def test_aucun_setUp_ne_saute_en_laissant_un_dossier(self) -> None:
        problemes: list[str] = []
        for fichier in sorted(_TESTS.glob("*.py")):
            problemes.extend(_fuites_possibles(fichier))
        self.assertEqual(problemes, [], "\n" + "\n".join(problemes))

    def test_le_detecteur_voit_le_motif_fautif(self) -> None:
        """Sans ce controle positif, un detecteur casse rendrait toujours [].

        On lui donne la sequence exacte du defaut, ecrite dans un fichier
        temporaire — donc sans introduire le motif dans le depot.
        """
        import tempfile

        source = (
            "import tempfile, unittest\n"
            "class T(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        self.tmp = tempfile.mkdtemp()\n"
            "        self.skipTest('pas sur cette plateforme')\n"
            "        self.addCleanup(print)\n"
        )
        with tempfile.TemporaryDirectory() as boite:
            faux = Path(boite) / "test_faux.py"
            faux.write_text(source, encoding="utf-8")
            trouve = _fuites_possibles(faux)
        self.assertEqual(len(trouve), 1, trouve)
        self.assertIn("skipTest", trouve[0])

    def test_un_addCleanup_avant_le_saut_est_accepte(self) -> None:
        """L'ordre correct ne doit pas etre signale : sinon le garde est inutilisable."""
        import tempfile

        source = (
            "import tempfile, unittest\n"
            "class T(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        self.tmp = tempfile.mkdtemp()\n"
            "        self.addCleanup(print)\n"
            "        self.skipTest('pas sur cette plateforme')\n"
        )
        with tempfile.TemporaryDirectory() as boite:
            faux = Path(boite) / "test_ok.py"
            faux.write_text(source, encoding="utf-8")
            self.assertEqual(_fuites_possibles(faux), [])


if __name__ == "__main__":
    unittest.main()
