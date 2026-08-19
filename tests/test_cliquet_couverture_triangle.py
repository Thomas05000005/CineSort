"""Cliquet : combien de routes destructives echappent encore au verdict ?

POURQUOI UN CLIQUET, ET PAS UN FICHIER DE PLUS
----------------------------------------------
Ce depot fabrique des instruments que personne ne lit. La mesure du 2026-08-19 :

    apply_audit.jsonl      4 sites d'ecriture    0 lecteur
    debug_api.log          1                     0
    debug_tmdb.log         1                     0
    debug_sqlite.log       1                     0

Plus 78 rapports d'audit dormant sur des branches (#1085), 7 `debug_*.log` vides,
8 cles de cache mortes. Ajouter un onzieme journal referait, en plus gros,
l'erreur commise dix fois.

Le seul remede est qu'un manque de couverture ROUGISSE, pas qu'un fichier attende
un lecteur. D'ou ce cliquet : il compte les routes destructives que le triangle
ne couvre pas encore, et refuse que ce nombre remonte.

LES QUATRE ASSERTIONS (forme canonique du depot)
------------------------------------------------
1. le detecteur n'est pas MUET  — l'enumeration trouve bien les routes ;
2. le compte ne MONTE pas       — la borne, a marge zero ;
3. la borne n'est pas PERIMEE   — elle doit descendre quand la couverture monte ;
4. la premisse est TESTEE       — « apply est couverte » est prouve, pas affirme.

Sans la 4e, `ROUTES_COUVERTES` serait une liste de vœux : il suffirait d'y ecrire
les neuf noms pour rendre le cliquet vert sans avoir couvert quoi que ce soit.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

#: Les routes destructives que le triangle couvre AUJOURD'HUI. Chacune doit etre
#: prouvee par un test qui l'execute — cf. `LaPremisseEstTesteeTests`.
ROUTES_COUVERTES: frozenset[str] = frozenset({"RunFacade.apply"})

#: Marge ZERO. Ce nombre ne peut que descendre.
NON_COUVERTES_MAX = 8

_FACADES = pathlib.Path("cinesort/ui/api/facades")


def _routes_destructives() -> set[str]:
    """Les methodes de facade portant `dry_run`, relevees a l'AST.

    A l'AST et non au grep : un `dry_run` cite dans une docstring ou un
    commentaire ressemble a une signature, et gonflerait le denominateur.
    """
    trouvees: set[str] = set()
    for fichier in sorted(_FACADES.glob("*.py")):
        arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        for cls in [n for n in arbre.body if isinstance(n, ast.ClassDef)]:
            for membre in cls.body:
                if not isinstance(membre, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if "dry_run" in {a.arg for a in membre.args.args + membre.args.kwonlyargs}:
                    trouvees.add(f"{cls.name}.{membre.name}")
    return trouvees


class LeDetecteurNEstPasMuetTests(unittest.TestCase):
    """Assertion 1. Sans elle, une enumeration cassee rendrait un ensemble vide,
    donc « 0 route non couverte » — un cliquet vert qui ne mesure RIEN."""

    def test_les_facades_sont_bien_lues(self):
        self.assertTrue(_FACADES.is_dir(), f"{_FACADES} a bouge : l'enumeration ne mesure plus rien")
        self.assertGreaterEqual(len(list(_FACADES.glob("*.py"))), 5)

    def test_l_enumeration_trouve_des_routes(self):
        routes = _routes_destructives()
        self.assertGreaterEqual(len(routes), 9, f"l'AST ne trouve plus les routes destructives : {sorted(routes)}")
        self.assertIn("RunFacade.apply", routes, "la route la plus destructive de l'app a disparu du releve")


class LeCompteNeMontePasTests(unittest.TestCase):
    """Assertion 2. La borne."""

    def test_le_nombre_de_routes_non_couvertes_ne_monte_pas(self):
        non_couvertes = _routes_destructives() - ROUTES_COUVERTES
        self.assertLessEqual(
            len(non_couvertes),
            NON_COUVERTES_MAX,
            "une route destructive de plus echappe au verdict. Soit la couvrir, "
            "soit remonter NON_COUVERTES_MAX — ce qui doit rester une ligne de "
            f"diff visible en review. Non couvertes : {sorted(non_couvertes)}",
        )


class LaBorneNEstPasPerimeeTests(unittest.TestCase):
    """Assertion 3. Une borne qu'on ne resserre jamais finit par tout autoriser.

    C'est le defaut que ce depot a deja paye : une allowlist qui documentait
    elle-meme sa limite (« une fonction allowlistee peut grossir — c'est la
    limite assumee ») pendant que 136 fonctions depassaient le seuil.
    """

    def test_la_borne_colle_a_la_realite(self):
        non_couvertes = _routes_destructives() - ROUTES_COUVERTES
        self.assertEqual(
            len(non_couvertes),
            NON_COUVERTES_MAX,
            f"la couverture a change : descendre NON_COUVERTES_MAX a {len(non_couvertes)}",
        )


class LaPremisseEstTesteeTests(unittest.TestCase):
    """Assertion 4, et la plus importante.

    `ROUTES_COUVERTES` est une AFFIRMATION. Sans preuve, il suffirait d'y ecrire
    les neuf noms pour rendre tout ce fichier vert sans avoir couvert une seule
    route — un cliquet qui se ment a lui-meme.
    """

    def test_chaque_route_declaree_couverte_EXISTE(self):
        inconnues = ROUTES_COUVERTES - _routes_destructives()
        self.assertEqual(inconnues, set(), f"routes declarees couvertes mais introuvables : {sorted(inconnues)}")

    def test_apply_est_REELLEMENT_couverte(self):
        """On execute le vrai corps d'apply et on exige le verdict.

        C'est le meme harnais que `test_verdicts_cablage_apply.py` : si l'appel
        disparait de `_apply_changes_body`, cette assertion rougit ICI aussi, et
        `ROUTES_COUVERTES` cesse d'etre une declaration en l'air.
        """
        from tests.test_verdicts_cablage_apply import (
            LE_CORPS_D_APPLY_APPELLE_VRAIMENT_LE_VERDICT_Tests as Reel,
        )

        cas = Reel("test_un_apply_REEL_incoherent_porte_son_verdict")
        payload = cas._payload_d_un_apply_reel([{"op_type": "MOVE_FILE", "error_message": "boom"}])
        self.assertIn(
            "verdict",
            payload,
            "RunFacade.apply est declaree couverte mais son corps ne produit aucun verdict",
        )


if __name__ == "__main__":
    unittest.main()
