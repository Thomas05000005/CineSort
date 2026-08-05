"""L'affichage des doublons doit annoncer ce que l'apply FERA, pas autre chose.

Remarque de revue sur la PR #846. La table `duplicate_decisions` est
upsert-only sur `(run_id, group_key)` et sa cle DERIVE de `titre|annee` : des
que l'utilisateur corrige l'annee ou le titre, la cle change et la decision
precedente SURVIT. Plusieurs decisions historiques peuvent donc se CHEVAUCHER
sur un meme row.

    l'apply resout GLOBALEMENT, par recence
    l'affichage rattachait par ENSEMBLE EXACT de row_ids — un critere LOCAL

Les deux divergeaient :

    decision ancienne sur {r1, r2} : gagnant r1, perdant r2
    decision recente  sur {r1, r3} : gagnant r3, perdant r1
    groupe affiche = {r1, r2}

L'UI annoncait « ✓ Decide, r1 garde ». L'apply, lui, deplacait r1. Sur un
chemin qui DEPLACE des dossiers, l'ecran et le disque disaient l'inverse.
"""

from __future__ import annotations

import unittest

from cinesort.ui.api._duplicate_roles import (
    decision_matches_effective_roles,
    resolve_duplicate_loser_row_ids,
    resolve_duplicate_roles,
)


def _dec(ts, winner, losers, key="k"):
    return {"group_key": key, "winner_row_id": winner, "loser_row_ids": list(losers), "decided_ts": ts}


class RolesEffectifsTests(unittest.TestCase):
    def test_la_decision_recente_retire_le_role_de_gagnant(self) -> None:
        """Le coeur du contrat, cote resolution."""
        roles = resolve_duplicate_roles([_dec(100.0, "r1", ["r2"], "a"), _dec(200.0, "r3", ["r1"], "b")])
        self.assertEqual(roles.get("r1"), "loser", "r1 est perdant de la decision la PLUS RECENTE")
        self.assertEqual(roles.get("r3"), "winner")
        self.assertEqual(roles.get("r2"), "loser")

    def test_une_decision_sans_perdant_n_arbitre_rien(self) -> None:
        """Sans ce garde, elle confererait une immunite a son « gagnant »."""
        roles = resolve_duplicate_roles([_dec(100.0, "r1", ["r2"], "a"), _dec(200.0, "r1", [], "b")])
        self.assertEqual(roles.get("r2"), "loser", "la decision vide a annule une decision legitime")

    def test_les_perdants_effectifs_sont_ceux_que_l_apply_deplacera(self) -> None:
        perdants = resolve_duplicate_loser_row_ids([_dec(100.0, "r1", ["r2"], "a"), _dec(200.0, "r3", ["r1"], "b")])
        self.assertEqual(perdants, {"r1", "r2"})


class AnnotationRefuseeTests(unittest.TestCase):
    """LE SCENARIO DE LA REVUE : deux ensembles historiques qui se chevauchent."""

    def setUp(self) -> None:
        self.ancienne = _dec(100.0, "r1", ["r2"], "titre|2010")
        self.recente = _dec(200.0, "r3", ["r1"], "titre|2011")
        self.roles = resolve_duplicate_roles([self.ancienne, self.recente])

    def test_la_decision_perimee_est_REFUSEE(self) -> None:
        """r1 y est gagnant, mais l'apply en fera un perdant."""
        self.assertFalse(
            decision_matches_effective_roles(self.ancienne, self.roles),
            "l'UI annoncerait « r1 garde » alors que l'apply le deplace",
        )

    def test_la_decision_courante_reste_ACCEPTEE(self) -> None:
        """Contre-epreuve : le refus ne doit pas tout bloquer."""
        self.assertTrue(decision_matches_effective_roles(self.recente, self.roles))

    def test_sans_chevauchement_rien_ne_change(self) -> None:
        """Cas nominal : deux decisions disjointes restent toutes deux valides."""
        d1 = _dec(100.0, "a1", ["a2"], "A")
        d2 = _dec(200.0, "b1", ["b2"], "B")
        roles = resolve_duplicate_roles([d1, d2])
        self.assertTrue(decision_matches_effective_roles(d1, roles))
        self.assertTrue(decision_matches_effective_roles(d2, roles))

    def test_une_decision_sans_perdant_est_refusee(self) -> None:
        """Meme regle qu'a l'apply : elle n'arbitre rien, donc pas de badge."""
        vide = _dec(300.0, "r9", [], "C")
        self.assertFalse(decision_matches_effective_roles(vide, resolve_duplicate_roles([vide])))


class _FakeApplyRepo:
    def __init__(self, decisions):
        self._d = decisions

    def list_duplicate_decisions(self, run_id):  # noqa: ARG002
        return self._d


class _FakeStore:
    def __init__(self, decisions):
        self.apply = _FakeApplyRepo(decisions)


class SiteDAppelTests(unittest.TestCase):
    """Le SITE D'APPEL, pas seulement le helper.

    Premiere version de ces tests : ils n'exercaient que
    `decision_matches_effective_roles`. Retirer le refus de
    `_annotate_groups_with_decisions` les laissait donc tous VERTS — le
    correctif n'etait couvert nulle part la ou il agit.
    """

    def _groupe(self, *row_ids):
        return {"rows": [{"row_id": r} for r in row_ids]}

    def _annoter(self, groupes, decisions):
        from cinesort.ui.api import run_flow_support

        data = {"groups": groupes}
        run_flow_support._annotate_groups_with_decisions(data, "RUN1", _FakeStore(decisions))
        return data["groups"]

    def test_le_groupe_contredit_par_une_decision_recente_n_est_PAS_annote(self) -> None:
        """LE SCENARIO COMPLET, de bout en bout.

        Le groupe {r1, r2} correspond exactement a l'ancienne decision, mais r1
        est perdant de la plus recente : l'apply le deplacera. Aucun badge ne
        doit promettre le contraire.
        """
        groupes = self._annoter(
            [self._groupe("r1", "r2")],
            [_dec(100.0, "r1", ["r2"], "titre|2010"), _dec(200.0, "r3", ["r1"], "titre|2011")],
        )
        self.assertNotIn(
            "winner_decided",
            groupes[0],
            f"badge « decide » pose alors que l'apply deplacera r1 : {groupes[0]}",
        )

    def test_un_groupe_NON_contredit_reste_annote(self) -> None:
        """Contre-epreuve : le refus ne doit pas eteindre les badges legitimes."""
        groupes = self._annoter(
            [self._groupe("a1", "a2")],
            [_dec(100.0, "a1", ["a2"], "A")],
        )
        self.assertTrue(groupes[0].get("winner_decided"), "badge legitime perdu")
        self.assertEqual(groupes[0].get("winner_row_id"), "a1")


class SourceUniqueTests(unittest.TestCase):
    def test_apply_et_affichage_partagent_LA_MEME_fonction(self) -> None:
        """Deux copies deriveraient — c'est exactement ce qui a produit ce bug.

        `apply_support._resolve_duplicate_loser_row_ids` doit DELEGUER, pas
        reimplementer.
        """
        from cinesort.ui.api import apply_support

        decisions = [_dec(100.0, "r1", ["r2"], "a"), _dec(200.0, "r3", ["r1"], "b")]
        self.assertEqual(
            apply_support._resolve_duplicate_loser_row_ids(decisions, lambda *_a: None),
            resolve_duplicate_loser_row_ids(decisions),
        )


if __name__ == "__main__":
    unittest.main()
