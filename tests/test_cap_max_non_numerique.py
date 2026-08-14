"""Un plafond non numerique ne doit pas faire tomber le film en Reject.

`_clamp` rend **0** sur une valeur non numerique — c'est son contrat historique,
ecrit dans sa docstring. `_act_cap_max` le consommait directement, donc un
`cap_max` mal saisi devenait un plafond a 0 : le score est ramene a 0, le film
tombe en **Reject**, et Reject oriente des decisions destructives (c'est le sac
que l'utilisateur vide). Le seul message existait `if reason:` — donc absent par
defaut, le champ « motif » du constructeur de regles etant facultatif.

C'est la panne de **#723** (`score_multiplier` negatif) et celle que
`_act_force_score` garde deja (« refuser silencieusement les valeurs
non-numeriques au lieu de forcer le score a 0 »), laissee dans les deux seules
actions qui n'avaient pas de garde — dont la seule dont la direction est
destructive.

COMMENT LA VALEUR ARRIVE. Le constructeur de regles
(`web/dashboard/components/regles-qualite.js`) envoie :

    value: b.action.value === "" ? undefined
         : Number.isNaN(Number(b.action.value)) ? b.action.value
         : Number(b.action.value)

Un champ VIDE part donc en `undefined`, cle que `JSON.stringify` **supprime** :
le backend recoit une action sans `value`, soit `None`. Une saisie non
numerique, elle, part telle quelle en chaine.

Les deux tests d'application ci-dessous sont ROUGES sans le correctif
(`score == 0`), et les deux tests de validation le sont aussi (`ok is True`).
"""

from __future__ import annotations

import unittest

from cinesort.domain.custom_rules import apply_custom_rules, validate_rules


def _contexte():
    """Contexte minimal : seul `video_codec` sert de condition."""
    return {
        "detected": {"video_codec": "hevc"},
        "__context__": {},
        "__computed__": {},
    }


#: Marqueur « la cle `value` est absente de l'action », ce que produit le
#: constructeur de regles quand le champ est vide (`undefined` -> cle supprimee
#: par JSON.stringify). Distinct de `None`, qui est ce que le backend LIT.
_ABSENT = object()


def _regle(action_value, *, atype="cap_max", reason=None):
    action = {"type": atype}
    if action_value is not _ABSENT:
        action["value"] = action_value
    if reason is not None:
        action["reason"] = reason
    return {
        "id": "r1",
        "conditions": [{"field": "video_codec", "op": "=", "value": "hevc"}],
        "action": action,
    }


class CapMaxNonNumeriqueApplicationTests(unittest.TestCase):
    """Cote APPLICATION : profils deja persistes, qui ne repassent pas par la validation."""

    def test_cap_max_sans_valeur_ne_ramene_PAS_le_score_a_zero(self):
        resultat = apply_custom_rules(80, _contexte(), [_regle(_ABSENT)])
        self.assertEqual(
            resultat["score"],
            80,
            "un cap_max sans valeur a plafonne le score a 0 (Reject) au lieu d'etre refuse",
        )

    def test_cap_max_non_numerique_ne_ramene_PAS_le_score_a_zero(self):
        resultat = apply_custom_rules(80, _contexte(), [_regle("soixante-cinq")])
        self.assertEqual(resultat["score"], 80)

    def test_le_refus_est_DIT_meme_sans_motif_saisi(self):
        """Le champ « motif » est facultatif : le message ne peut pas en dependre.

        C'est ce qui distingue ce correctif d'un simple `return` : une regle
        silencieusement inerte est une autre facon de mentir a l'utilisateur.
        """
        resultat = apply_custom_rules(80, _contexte(), [_regle(_ABSENT)])
        self.assertTrue(
            any("non numerique" in raison for raison in resultat["reasons"]),
            f"aucune raison ne dit que la regle a ete refusee : {resultat['reasons']}",
        )

    def test_cap_min_non_numerique_est_refuse_aussi(self):
        resultat = apply_custom_rules(40, _contexte(), [_regle(_ABSENT, atype="cap_min")])
        self.assertEqual(resultat["score"], 40)
        self.assertTrue(any("non numerique" in raison for raison in resultat["reasons"]))

    def test_un_cap_max_LEGITIME_plafonne_toujours(self):
        """Contre-epreuve : la garde ne doit pas eteindre l'action.

        Sans elle, un correctif qui refuserait TOUT `cap_max` laisserait les
        quatre tests ci-dessus verts.
        """
        resultat = apply_custom_rules(80, _contexte(), [_regle(65)])
        self.assertEqual(resultat["score"], 65)

    def test_un_cap_max_a_ZERO_reste_un_plafond_legitime(self):
        """0 SAISI n'est pas 0 SUBI : la sentinelle et la valeur doivent differer.

        C'est le piege « sentinelle falsy » du depot : refuser sur `not value`
        au lieu de `_num_strict(...) is _MISSING` aurait aussi refuse le
        plafond 0, qu'un utilisateur peut vouloir.
        """
        resultat = apply_custom_rules(80, _contexte(), [_regle(0)])
        self.assertEqual(resultat["score"], 0)


class CapMaxNonNumeriqueValidationTests(unittest.TestCase):
    """Cote VALIDATION : refus AMONT, comme #723 pour score_multiplier."""

    def test_validate_refuse_un_cap_max_sans_valeur(self):
        ok, erreurs, _norm = validate_rules([_regle(_ABSENT)])
        self.assertFalse(ok, "un cap_max sans valeur a ete accepte a l'enregistrement")
        self.assertTrue(any("cap_max" in e for e in erreurs), erreurs)

    def test_validate_refuse_un_cap_min_non_numerique(self):
        ok, erreurs, _norm = validate_rules([_regle("beaucoup", atype="cap_min")])
        self.assertFalse(ok)
        self.assertTrue(any("cap_min" in e for e in erreurs), erreurs)

    def test_validate_accepte_toujours_un_plafond_numerique(self):
        ok, erreurs, norm = validate_rules([_regle(65)])
        self.assertTrue(ok, erreurs)
        self.assertEqual(norm[0]["action"]["value"], 65)

    def test_validate_accepte_une_chaine_numerique(self):
        """`"65"` reste accepte : c'est ce que produit un `<input type=text>`.

        Le refus doit porter sur « pas un nombre », pas sur « pas un int ».
        """
        ok, erreurs, _norm = validate_rules([_regle("65")])
        self.assertTrue(ok, erreurs)


if __name__ == "__main__":
    unittest.main()
