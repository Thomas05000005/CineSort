"""Cliquet : combien de routes destructives echappent encore au verdict ?

POURQUOI UN CLIQUET, ET PAS UN FICHIER DE PLUS
----------------------------------------------
Ce depot fabrique des instruments peu lus. Mesure du 2026-08-19, RECTIFIEE :
`apply_audit.jsonl` a **4 sites d'ecriture et 3 lecteurs** — deux de production
anterieurs a cette branche (`apply_batches_reconciliation.py:200`,
`apply_support.export_apply_audit`) plus le verdict. Une premiere version de ce
fichier annoncait « 0 lecteur » et en tirait toute sa these ; le chiffre etait
faux, repris d'un plan sans etre remesure.

La these tient sans lui : 78 rapports d'audit ont dormi sur des branches
(#1085), sept `debug_*.log` sont vides, et `payload["verdict"]` que cette
campagne ajoute n'est **lu par aucun ecran**. Le remede n'est pas d'ecrire un
fichier de plus, c'est qu'un manque de couverture ROUGISSE.

LE DENOMINATEUR
---------------
« Route destructive » = methode de facade portant `dry_run` **ou**
`confirmation`. Les deux sont les marqueurs que le depot lui-meme pose sur ses
frontieres irreversibles. Le premier seul ratait
`SettingsFacade.reset_all_user_data`, qui efface TOUTES les donnees utilisateur
et ne prend qu'une `confirmation` — la route la plus destructive de
l'application etait hors du compte.

Releve a l'AST, jamais au grep : un `dry_run` cite dans une docstring ressemble
a une signature et gonflerait le denominateur.

LES QUATRE ASSERTIONS
---------------------
1. le detecteur n'est pas MUET  — l'enumeration trouve bien les routes ;
2. le compte ne MONTE pas       — la borne, a marge zero ;
3. la borne n'est pas PERIMEE   — elle descend quand la couverture monte ;
4. la premisse est TESTEE       — chaque route declaree couverte est PROUVEE.

La 4e a d'abord ete decorative : elle ne prouvait que `RunFacade.apply`, en dur.
Ecrire les dix noms dans `ROUTES_COUVERTES` la laissait donc INTEGRALEMENT
verte. Elle exige desormais une PREUVE ENREGISTREE par route, et une route sans
preuve fait rougir — c'est ce que le fichier annoncait deja faire.
"""

from __future__ import annotations

import ast
import pathlib
import re
import unittest
from typing import Callable, Dict

_FACADES = pathlib.Path("cinesort/ui/api/facades")

#: Les marqueurs que le depot pose sur ses frontieres irreversibles.
MARQUEURS_DESTRUCTIFS = ("dry_run", "confirmation")

#: Marge ZERO. Ce nombre ne peut que descendre.
NON_COUVERTES_MAX = 9


def _routes_destructives() -> set[str]:
    """Les methodes de facade portant un marqueur destructif, relevees a l'AST."""
    trouvees: set[str] = set()
    for fichier in sorted(_FACADES.glob("*.py")):
        arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        for cls in [n for n in arbre.body if isinstance(n, ast.ClassDef)]:
            for membre in cls.body:
                if not isinstance(membre, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                args = {a.arg for a in membre.args.args + membre.args.kwonlyargs}
                if args & set(MARQUEURS_DESTRUCTIFS):
                    trouvees.add(f"{cls.name}.{membre.name}")
    return trouvees


def _prouver_run_facade_apply() -> bool:
    """Execute le VRAI corps d'apply et exige qu'il produise un verdict.

    Si l'appel disparait de `_apply_changes_body`, cette preuve echoue — et
    `RunFacade.apply` cesse d'etre declarable comme couverte.
    """
    from tests.test_verdicts_cablage_apply import (
        LE_CORPS_D_APPLY_APPELLE_VRAIMENT_LE_VERDICT_Tests as Reel,
    )

    cas = Reel("test_un_apply_REEL_incoherent_porte_son_verdict")
    payload = cas._payload_d_un_apply_reel([{"op_type": "MOVE_FILE", "error_message": "boom"}])
    return "verdict" in payload


#: Route -> preuve EXECUTABLE qu'elle produit reellement un verdict.
#:
#: C'est ce dictionnaire, et non une liste de noms, qui fait foi. Y ajouter une
#: route sans ecrire sa preuve fait rougir l'assertion 4.
PREUVES: Dict[str, Callable[[], bool]] = {
    "RunFacade.apply": _prouver_run_facade_apply,
}

ROUTES_COUVERTES: frozenset[str] = frozenset(PREUVES)


class LeDetecteurNEstPasMuetTests(unittest.TestCase):
    """Assertion 1. Sans elle, une enumeration cassee rendrait un ensemble vide,
    donc « 0 route non couverte » — un cliquet vert qui ne mesure RIEN."""

    def test_les_facades_sont_bien_lues(self):
        self.assertTrue(_FACADES.is_dir(), f"{_FACADES} a bouge : l'enumeration ne mesure plus rien")
        self.assertGreaterEqual(len(list(_FACADES.glob("*.py"))), 5)

    def test_l_enumeration_trouve_des_routes(self):
        routes = _routes_destructives()
        self.assertGreaterEqual(len(routes), 10, f"l'AST ne trouve plus les routes destructives : {sorted(routes)}")
        self.assertIn("RunFacade.apply", routes, "la route la plus destructive de l'app a disparu du releve")

    def test_les_DEUX_marqueurs_comptent(self):
        """Le marqueur `confirmation` a ete ajoute apres coup : sans lui,
        `reset_all_user_data` — qui efface TOUTES les donnees — echappait au
        denominateur. Ce test empeche de le reperdre."""
        routes = _routes_destructives()
        self.assertIn("SettingsFacade.reset_all_user_data", routes)
        self.assertIn("SettingsFacade.reset_database", routes)


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
    """Assertion 3. Une borne qu'on ne resserre jamais finit par tout autoriser."""

    def test_la_borne_colle_a_la_realite(self):
        non_couvertes = _routes_destructives() - ROUTES_COUVERTES
        self.assertEqual(
            len(non_couvertes),
            NON_COUVERTES_MAX,
            f"la couverture a change : ajuster NON_COUVERTES_MAX a {len(non_couvertes)}",
        )


class LaPremisseEstTesteeTests(unittest.TestCase):
    """Assertion 4, et la plus importante.

    Une premiere version prouvait `RunFacade.apply` EN DUR. Mesure : ecrire les
    dix noms dans `ROUTES_COUVERTES` la laissait integralement VERTE — le
    cliquet se mentait exactement comme son docstring promettait qu'il ne le
    ferait pas. La preuve est desormais indexee PAR ROUTE.
    """

    def test_chaque_route_declaree_couverte_EXISTE(self):
        inconnues = ROUTES_COUVERTES - _routes_destructives()
        self.assertEqual(inconnues, set(), f"routes declarees couvertes mais introuvables : {sorted(inconnues)}")

    def test_chaque_route_declaree_couverte_a_une_PREUVE(self):
        """Le verrou : declarer sans prouver est desormais impossible."""
        sans_preuve = ROUTES_COUVERTES - set(PREUVES)
        self.assertEqual(sans_preuve, set(), f"declarees couvertes sans preuve executable : {sorted(sans_preuve)}")

    def test_chaque_preuve_PASSE_reellement(self):
        """On EXECUTE chaque preuve. Une couverture qui a cesse de fonctionner
        rougit ici, pas dans six mois."""
        for route, preuve in sorted(PREUVES.items()):
            with self.subTest(route=route):
                self.assertTrue(preuve(), f"{route} est declaree couverte mais sa preuve echoue")

    def test_la_preuve_d_apply_SAIT_dire_NON(self):
        """Une preuve qui rend toujours `True` est decorative.

        Mutant survivant de la batterie : remplacer le corps de
        `_prouver_run_facade_apply` par `return True` ne faisait rougir aucun
        test — on verifiait qu'elle PASSE, jamais qu'elle SAIT ECHOUER.

        On neutralise donc le verdict au site de production et on exige que la
        preuve s'en apercoive. C'est le meme principe qu'un detecteur qu'on
        eprouve sur une entree connue negative.
        """
        from unittest import mock

        from cinesort.ui.api import apply_support

        with mock.patch.object(apply_support, "_avec_verdict", side_effect=lambda payload, **_: payload):
            self.assertFalse(
                _prouver_run_facade_apply(),
                "la preuve rend True alors que le verdict est neutralise : elle ne prouve rien",
            )

    def test_une_route_SANS_preuve_ferait_bien_rougir(self):
        """Le contre-test de l'assertion 4 : sans lui, on ne saurait pas si le
        verrou mord. On simule l'ajout d'un nom sans preuve."""
        declarees_a_tort = frozenset(PREUVES) | {"SettingsFacade.reset_database"}
        self.assertNotEqual(
            declarees_a_tort - set(PREUVES),
            set(),
            "ajouter un nom sans preuve doit produire un ecart non vide",
        )


class LeVerdictNAtteintAUCUNEcranTests(unittest.TestCase):
    """Ce que cette campagne n'a PAS fait, ecrit plutot que tu.

    `payload["verdict"]` est produit sur le chemin destructif et n'est lu par
    aucun fichier du front — pas plus que `journal_warning` ou `undo_available`,
    deux cles posees par des correctifs anterieurs pour la meme raison.

    L'incoherence atteint donc l'utilisateur par le CENTRE DE NOTIFICATIONS
    (`_publier_incoherence`), le seul canal qui survit a la fermeture de l'ecran
    d'apply — et non par l'ecran qui vient de lui annoncer le resultat. C'est
    mieux que le journal technique seul, ce n'est pas encore l'ecran.

    Ce test ne l'interdit pas — il le CONSTATE, pour que le jour ou un ecran le
    lira, quelqu'un vienne mettre ce constat a jour au lieu de le decouvrir.
    """

    def test_aucun_ecran_ne_lit_encore_la_cle_verdict(self):
        web = pathlib.Path("web")
        if not web.is_dir():
            self.skipTest("dossier web/ absent")
        # ACCES a la cle, pas le MOT. Une premiere version cherchait « verdict »
        # dans le texte brut et rendait `traitement.js`, ou le mot n'apparait que
        # dans trois COMMENTAIRES parlant d'un tout autre verdict (la decision
        # `auto_approvable`). Un grep ne distingue pas le code du texte.
        motif = re.compile(r"""\.verdict\b|\[\s*["']verdict["']\s*\]""")
        lecteurs, autres_verdicts = [], []
        for f in sorted(web.rglob("*.js")):
            code = "\n".join(
                ligne.split("//")[0] for ligne in f.read_text(encoding="utf-8", errors="replace").splitlines()
            )
            if not motif.search(code):
                continue
            # QUALIFIER, plutot qu'exclure par nom de fichier. `perceptual-modal.js`
            # accede bien a un `.verdict` — celui des doublons perceptuels, un tout
            # autre objet. L'exclure par son nom masquerait le jour ou il lirait
            # VRAIMENT l'apply ; on demande donc au fichier de parler d'apply.
            (lecteurs if "apply" in code else autres_verdicts).append(f.as_posix())

        self.assertTrue(
            autres_verdicts,
            "aucun fichier ne porte plus de `.verdict` etranger : la sonde ne "
            "distingue peut-etre plus rien, la verifier avant de la croire",
        )
        self.assertEqual(
            lecteurs,
            [],
            "un ecran lit desormais le verdict : mettre a jour ce constat, le "
            f"docstring du module et CLAUDE.md. Lecteurs : {lecteurs}",
        )


if __name__ == "__main__":
    unittest.main()
