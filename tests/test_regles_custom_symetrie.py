"""L'evaluateur de regles doit etre symetrique de son validateur, et validee UNE fois.

Constats 1 et 2 de l'audit du 2026-08-15 (#1082), verifies par mesure puis
corriges.

## 1 — l'evaluateur etait PERMISSIF la ou le validateur est RESTRICTIF

    _validate_single_rule : "any" if match == "any" else "all"    (restrictif)
    evaluate_rule         : all  if match == "all" else any       (permissif)

Une regle persistee avec `match: "AND"` — ou simplement `"all "` avec une espace
de fin — annonce « TOUTES ces conditions » et s'evaluait sur UNE SEULE.

MESURE AVANT CORRECTIF, une condition vraie sur deux, contexte conforme a
`FIELD_PATHS` (les champs vivent sous `detected`) :

    match="all"   -> ne declenche pas   conforme
    match="AND"   -> DECLENCHAIT        le mot annonce « toutes »
    match="all "  -> DECLENCHAIT        une simple espace de fin
    match="ALL"   -> ne declenche pas   conforme (le `.lower()` couvre la casse)

Les actions incluent `force_tier` et `cap_max`, donc **Reject** — le tier qui
oriente les suppressions. Une regle qui se declenche plus souvent que son propre
texte ne le promet va dans le sens PERMISSIF sur un chemin destructif.

## 2 — six chemins d'ecriture, un seul validait

`validate_quality_profile` laissait passer `custom_rules` verbatim, en deleguant
par commentaire a `custom_rules.validate_rules`. Cette delegation n'avait aucun
point d'application garanti.

MESURE : une regle a champ inconnu + operateur inconnu + `match` non canonique
est refusee par `validate_rules` (3 erreurs) et **acceptee** par
`validate_quality_profile` (`ok=True`, zero erreur), recopiee telle quelle.

Portee reelle, mesuree et plus etroite que l'inventaire ne le laissait croire :
`import_recyclarr_yaml` ne porte AUCUNE `custom_rules`, et
`profiles_support_crud.set_active_profile` relit un profil deja stocke. Il n'y a
donc pas de charge externe — mais un `settings.json` edite a la main, ou des
donnees anterieures a la validation, passaient.
"""

from __future__ import annotations

import unittest

from cinesort.domain import custom_rules as CR
from cinesort.domain.quality_score import default_quality_profile

#: Contexte conforme a `FIELD_PATHS` : les champs vivent sous `detected`. Une
#: fixture a plat ne matche RIEN et rendrait le test muet — c'est la premiere
#: version de la mesure, et elle ne prouvait rien.
_CONTEXTE = {"detected": {"resolution": "4k", "audio_best_codec": "dts"}}

#: Une condition VRAIE, une FAUSSE : le seul scenario qui distingue « toutes »
#: de « au moins une ».
#:
#: `action` est au SINGULIER et c'est un OBJET — schema lu dans
#: `_validate_action`, pas devine. Une premiere version ecrivait
#: `actions: [...]` : le validateur repondait « action manquante », et le test
#: aurait pu passer pour une preuve alors qu'il n'eprouvait qu'une faute de
#: fixture.
_REGLE = {
    "match": "all",
    "conditions": [
        {"field": "resolution", "op": "=", "value": "4k"},
        {"field": "audio_codec", "op": "=", "value": "JAMAIS_CE_CODEC"},
    ],
    "action": {"type": "force_tier", "value": "reject"},
}


class LEvaluateurEstSymetriqueDuValidateurTests(unittest.TestCase):
    def _declenche(self, match: str) -> bool:
        return CR.evaluate_rule(dict(_REGLE, match=match), _CONTEXTE)

    def test_un_match_NON_CANONIQUE_est_traite_comme_TOUTES(self) -> None:
        """LE defaut. `AND` et `all ` s'evaluaient sur une seule condition."""
        for forme in ("AND", "all ", " all", "OR", "toutes", ""):
            with self.subTest(match=forme):
                self.assertFalse(
                    self._declenche(forme),
                    f"match={forme!r} declenche sur UNE condition alors que la regle "
                    "en annonce deux : sens permissif sur un chemin qui force Reject",
                )

    def test_ANY_reste_ANY(self) -> None:
        """CONTRE-EPREUVE. Symetriser ne doit pas supprimer le mode « any » —
        sans ce test, `reducer = all` tout court passerait."""
        for forme in ("any", "ANY", " any "):
            with self.subTest(match=forme):
                self.assertTrue(self._declenche(forme), f"match={forme!r} ne declenche plus")

    def test_ALL_explicite_reste_ALL(self) -> None:
        for forme in ("all", "ALL"):
            with self.subTest(match=forme):
                self.assertFalse(self._declenche(forme))

    def test_les_DEUX_conditions_vraies_declenchent_en_mode_TOUTES(self) -> None:
        """Sans lui, un correctif qui rendrait TOUJOURS False passerait les
        trois tests precedents."""
        regle = dict(
            _REGLE,
            match="all",
            conditions=[
                {"field": "resolution", "op": "=", "value": "4k"},
                {"field": "audio_codec", "op": "=", "value": "dts"},
            ],
        )
        self.assertTrue(CR.evaluate_rule(regle, _CONTEXTE))


class UneRegleINVALIDEEstECARTEEAActivationTests(unittest.TestCase):
    """`set_active_profile` est le SEUL chemin qui re-persistait des regles sans
    les valider.

    OU CETTE GARDE N'EST PAS, ET POURQUOI — c'est mesure, pas suppose. Deux
    essais precedents l'ont posee dans `validate_quality_profile`, et les deux
    ont ETEINT une garde existante :

    - **ajouter les erreurs de regles a `errs`** : `compute_quality_score` fait
      `if not ok: return _build_invalid_profile_result(...)`, donc une regle
      inutilisable mettait TOUS les films a 0 (mesure : 0 au lieu de 46). Cela
      annulait #723, dont le principe est de refuser la VALEUR en preservant le
      score ;
    - **ecarter les regles dans le validateur** : `save_quality_profile` lit
      `custom_rules` APRES lui, donc sa propre verification ne voyait plus rien
      et son refus de #723 cessait de fonctionner.

    Ce chemin-ci re-persiste du STOCKE, que personne ne saisit. On y ecarte donc
    les regles inutilisables — un profil stocke doit rester activable — au lieu
    de refuser l'activation.
    """

    def setUp(self) -> None:
        import copy
        import tempfile
        from pathlib import Path

        from tests.test_phase4_parametres_endpoints import _FakeApi

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.api = _FakeApi(Path(self._tmp.name))

        self.bonne = {
            "id": "ok",
            "name": "valide",
            "match": "any",
            "conditions": [{"field": "resolution", "op": "=", "value": "4k"}],
            "action": {"type": "cap_max", "value": 70},
        }
        self.pourrie = {
            "id": "ko",
            "name": "invalide",
            "match": "AND",
            "conditions": [{"field": "CHAMP_INCONNU", "op": "OPERATEUR_INCONNU", "value": "x"}],
            "action": {"type": "force_tier", "value": "reject"},
        }
        prof = copy.deepcopy(default_quality_profile())
        prof["id"] = "AvecRegles_v1"
        prof["custom_rules"] = [self.bonne, self.pourrie]
        self.api.settings._payload = {"custom_quality_profiles": [prof]}

    def _activer(self):
        from cinesort.ui.api import profiles_support

        return profiles_support.set_active_profile(self.api, "AvecRegles_v1")

    def test_l_activation_REUSSIT_malgre_la_regle_invalide(self) -> None:
        """Un profil stocke doit rester activable : refuser l'enfermerait."""
        out = self._activer()
        self.assertTrue(out.get("ok"), out)

    def test_la_regle_INVALIDE_n_est_pas_re_persistee(self) -> None:
        self._activer()
        regles = (self.api._db_active_profile or {}).get("custom_rules") or []
        ids = [r.get("id") for r in regles]
        self.assertNotIn("ko", ids, "la regle invalide a ete re-persistee telle quelle")

    def test_la_regle_VALIDE_survit(self) -> None:
        """CONTRE-EPREUVE : sans elle, tout ecarter passerait le test precedent."""
        self._activer()
        regles = (self.api._db_active_profile or {}).get("custom_rules") or []
        ids = [r.get("id") for r in regles]
        self.assertIn("ok", ids, "la regle valide a ete ecartee avec l'autre")


if __name__ == "__main__":
    unittest.main()
