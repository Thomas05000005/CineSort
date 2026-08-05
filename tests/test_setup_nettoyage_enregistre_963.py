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

Le depot est donc sain aujourd'hui, et c'est cela que ce fichier verrouille.
L'issue #963 supposait ~40 sites a convertir ; la mesure montre qu'il n'y en a
aucun a corriger, mais rien n'empechait le motif de revenir.

Le garde porte sur la STRUCTURE (AST) et non sur une chaine de code source :
il ne tombe pas quand le code s'ameliore, et il attrape le motif quel que soit
son habillage — comme le fait deja `test_no_redundant_exception_handlers`.
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


def _noms_mentionnes(noeud: ast.AST) -> set[str]:
    """Tous les noms — simples ou pointes — cites dans un sous-arbre.

    `self.tmp.cleanup` donne {"cleanup", "tmp", "self", "self.tmp",
    "self.tmp.cleanup"} : on veut pouvoir reconnaitre la ressource quelle que
    soit la profondeur a laquelle l'appelant la designe.
    """
    noms: set[str] = set()
    for sous in ast.walk(noeud):
        if isinstance(sous, ast.Name):
            noms.add(sous.id)
        elif isinstance(sous, ast.Attribute):
            noms.add(sous.attr)
            chemin = _chemin_pointe(sous)
            if chemin:
                noms.add(chemin)
    return noms


def _chemin_pointe(noeud: ast.AST) -> str:
    """`self.tmp.name` -> "self.tmp.name" ; rend "" si le chemin n'est pas pur."""
    morceaux: list[str] = []
    courant = noeud
    while isinstance(courant, ast.Attribute):
        morceaux.append(courant.attr)
        courant = courant.value
    if isinstance(courant, ast.Name):
        morceaux.append(courant.id)
        return ".".join(reversed(morceaux))
    return ""


class _Ressource:
    """Un dossier temporaire cree, et les noms sous lesquels on peut le designer."""

    __slots__ = ("ligne", "noms")

    def __init__(self, ligne: int, noms: set[str]) -> None:
        self.ligne = ligne
        self.noms = noms


class _AnalyseurSetUp(ast.NodeVisitor):
    """Parcourt le corps REELLEMENT execute de `setUp`, dans l'ordre d'evaluation.

    Trois pieges que `ast.walk` + tri par `lineno` ne traite pas, et que ce
    visiteur traite :

    1. **Les fonctions imbriquees ne s'executent pas.** Un `mkdtemp` dans un
       `def _aide()` defini mais jamais appele n'a rien cree. On ne descend
       donc pas dans les `FunctionDef`, `AsyncFunctionDef` ni `Lambda`.

    2. **Les arguments sont evalues AVANT l'appel.** Dans
       `self.addCleanup(shutil.rmtree, tempfile.mkdtemp())`, Python cree le
       dossier puis enregistre le nettoyage. Un tri par ligne place les deux au
       meme rang et rend un ordre arbitraire. On visite donc les enfants
       d'abord, l'appel ensuite.

    3. **Un `addCleanup` ne protege que ce qu'il nomme.** `addCleanup(print)`
       n'efface rien : c'est exactement le faux negatif qui rendrait ce garde
       inutile. Une ressource n'est retiree de la liste d'attente que si les
       arguments du `addCleanup` la designent — par son nom, par un attribut,
       ou parce qu'elle est creee dans ces arguments memes.
    """

    def __init__(self) -> None:
        self.en_attente: list[_Ressource] = []
        self.problemes: list[tuple[int, int, str]] = []  # (ligne du saut, ligne creation, nom du saut)

    # Les corps non executes ne creent rien.
    def visit_FunctionDef(self, noeud: ast.FunctionDef) -> None:  # noqa: N802
        return

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Lambda(self, noeud: ast.Lambda) -> None:  # noqa: N802
        return

    def visit_Assign(self, noeud: ast.Assign) -> None:  # noqa: N802
        # La valeur est evaluee avant l'affectation : on la visite d'abord,
        # puis on rattache la ressource fraichement creee a ses noms de cible.
        avant = len(self.en_attente)
        self.visit(noeud.value)
        cibles: set[str] = set()
        for cible in noeud.targets:
            cibles |= _noms_mentionnes(cible)
        for ressource in self.en_attente[avant:]:
            ressource.noms |= cibles

    def visit_Call(self, noeud: ast.Call) -> None:  # noqa: N802
        avant = len(self.en_attente)
        # Arguments d'abord : c'est l'ordre d'evaluation de Python.
        for enfant in list(noeud.args) + [kw.value for kw in noeud.keywords]:
            self.visit(enfant)
        self.visit(noeud.func)

        nom = _nom_appele(noeud)
        if nom in _CREATIONS:
            self.en_attente.append(_Ressource(noeud.lineno, set()))
            return
        if nom == "addCleanup":
            designes: set[str] = set()
            for enfant in list(noeud.args) + [kw.value for kw in noeud.keywords]:
                designes |= _noms_mentionnes(enfant)
            # Une ressource creee DANS les arguments de ce meme `addCleanup`
            # est couverte par lui, par construction.
            creees_ici = set(self.en_attente[avant:])
            self.en_attente = [r for r in self.en_attente if r not in creees_ici and not (r.noms & designes)]
            return
        if nom in _SAUTS and self.en_attente:
            self.problemes.append((noeud.lineno, self.en_attente[0].ligne, nom))
            self.en_attente.clear()


def _fuites_possibles(chemin: Path) -> list[str]:
    """Signale tout `setUp` ou un saut suit une creation NON encore protegee."""
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    problemes: list[str] = []
    for classe in [n for n in ast.walk(arbre) if isinstance(n, ast.ClassDef)]:
        for methode in [m for m in classe.body if isinstance(m, ast.FunctionDef) and m.name == "setUp"]:
            analyseur = _AnalyseurSetUp()
            for instruction in methode.body:
                analyseur.visit(instruction)
            for ligne_saut, ligne_creation, nom in analyseur.problemes:
                problemes.append(
                    f"{chemin.name}::{classe.name}.setUp : "
                    f"`{nom}` en ligne {ligne_saut} apres une creation non protegee "
                    f"(ligne {ligne_creation}) — `tearDown` ne s'executera pas, "
                    f"le dossier restera dans %TEMP%. Enregistrer le nettoyage "
                    f"par `addCleanup` JUSTE APRES la creation, et lui passer la "
                    f"ressource concernee."
                )
    return problemes


def _analyser_source(source: str) -> list[str]:
    """Analyse une source en memoire — pour eprouver le detecteur lui-meme."""
    import tempfile

    with tempfile.TemporaryDirectory() as boite:
        fichier = Path(boite) / "test_sonde.py"
        fichier.write_text(source, encoding="utf-8")
        return _fuites_possibles(fichier)


_ENTETE = "import tempfile, shutil, unittest\nclass T(unittest.TestCase):\n    def setUp(self):\n"


class SetupNeSauteJamaisSansNettoyageTests(unittest.TestCase):
    def test_aucun_setUp_ne_saute_en_laissant_un_dossier(self) -> None:
        problemes: list[str] = []
        for fichier in sorted(_TESTS.glob("*.py")):
            problemes.extend(_fuites_possibles(fichier))
        self.assertEqual(problemes, [], "\n" + "\n".join(problemes))


class DetecteurTests(unittest.TestCase):
    """Le detecteur doit voir ROUGE quand il faut, et VERT quand il faut.

    Sans ces controles, un detecteur casse rendrait toujours `[]` et le test
    ci-dessus serait vert pour de mauvaises raisons.
    """

    def test_le_motif_fautif_est_detecte(self) -> None:
        trouve = _analyser_source(_ENTETE + "        self.tmp = tempfile.mkdtemp()\n        self.skipTest('non')\n")
        self.assertEqual(len(trouve), 1, trouve)
        self.assertIn("skipTest", trouve[0])

    def test_un_addCleanup_qui_designe_la_ressource_protege(self) -> None:
        self.assertEqual(
            _analyser_source(
                _ENTETE
                + "        self.tmp = tempfile.mkdtemp()\n"
                + "        self.addCleanup(shutil.rmtree, self.tmp, True)\n"
                + "        self.skipTest('non')\n"
            ),
            [],
        )

    def test_un_addCleanup_qui_ne_nettoie_PAS_la_ressource_ne_protege_pas(self) -> None:
        """Le faux negatif qui rendrait ce garde inutile.

        `addCleanup(print)` enregistre bien un rappel — mais il ne supprime pas
        le dossier. Une version anterieure de ce fichier l'acceptait, et le
        test correspondant VERROUILLAIT donc le defaut.
        """
        trouve = _analyser_source(
            _ENTETE
            + "        self.tmp = tempfile.mkdtemp()\n"
            + "        self.addCleanup(print)\n"
            + "        self.skipTest('non')\n"
        )
        self.assertEqual(len(trouve), 1, trouve)

    def test_une_creation_dans_les_arguments_du_addCleanup_est_couverte(self) -> None:
        """`addCleanup(rmtree, mkdtemp())` : Python cree PUIS enregistre.

        Un tri par numero de ligne place les deux appels au meme rang et rend
        un ordre arbitraire — d'ou un faux positif.
        """
        self.assertEqual(
            _analyser_source(
                _ENTETE
                + "        self.addCleanup(shutil.rmtree, tempfile.mkdtemp())\n"
                + "        self.skipTest('non')\n"
            ),
            [],
        )

    def test_une_creation_dans_une_fonction_imbriquee_n_est_pas_comptee(self) -> None:
        """Un corps defini mais jamais appele n'a rien cree."""
        self.assertEqual(
            _analyser_source(
                _ENTETE
                + "        def _aide():\n            return tempfile.mkdtemp()\n"
                + "        self.skipTest('non')\n"
            ),
            [],
        )

    def test_un_temporarydirectory_protege_par_son_propre_cleanup(self) -> None:
        """La forme la plus courante du depot : `addCleanup(self.tmp.cleanup)`."""
        self.assertEqual(
            _analyser_source(
                _ENTETE
                + "        self.tmp = tempfile.TemporaryDirectory()\n"
                + "        self.addCleanup(self.tmp.cleanup)\n"
                + "        self.skipTest('non')\n"
            ),
            [],
        )

    def test_un_saut_AVANT_toute_creation_est_sans_effet(self) -> None:
        self.assertEqual(
            _analyser_source(
                _ENTETE
                + "        self.skipTest('non')\n"
                + "        self.tmp = tempfile.mkdtemp()\n"
                + "        self.addCleanup(shutil.rmtree, self.tmp, True)\n"
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
