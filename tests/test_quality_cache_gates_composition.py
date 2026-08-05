"""Les deux gardes du cache qualite doivent COMPOSER, pas se remplacer.

Deux correctifs sont arrives par des chemins independants sur le meme `if` de
`get_quality_report(reuse_existing=True)` :

* PR#854 (main) — estampille des REGLES DE CODE (`metrics.scoring_rules_version`).
  Les 3 cles historiques venaient toutes du profil persiste : changer une regle
  de scoring ne les faisait pas bouger, et une bibliotheque melangeait ancienne
  et nouvelle formule dans le meme classement de tiers. Contrepartie livree avec
  ce correctif : si le media n'est plus atteignable (run deja applique), on rend
  l'ancien score marque `scoring_rules_stale` plutot qu'une erreur.
* N30 (PR#872) — empreinte du CONTENU du profil (`metrics.profile_fingerprint`).
  `save_quality_profile` remplace `profile_json` en GARDANT la version : un
  profil edite gardait un triplet identique et son rapport perime etait servi
  comme frais.

Aucun des deux lots ne teste l'autre : leurs fixtures respectives ignorent la cle
adverse. Ce fichier verrouille la matrice complete, et en particulier le point
d'arbitrage de la fusion : le repli « stale » n'est accorde qu'a un rapport dont
le PROFIL est prouve identique. Un rapport sans empreinte (anterieur a N30) ne
prouve rien sur son profil : il n'y a pas droit.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from cinesort.domain.quality_score import SCORING_RULES_VERSION
from cinesort.ui.api import quality_report_support

_FAKE_ROOT = "Z:/films-de-test"


def _profile(gold: int = 70) -> Dict[str, Any]:
    return {
        "id": "CinemaLux_v1",
        "version": 1,
        "engine_version": "CinemaLux_v1",
        "tiers": {"gold": gold, "silver": 50},
        "weights": {"video": 0.6, "audio": 0.4},
    }


def _persisted(
    *,
    profile: Optional[Dict[str, Any]],
    rules_version: Optional[int],
) -> Dict[str, Any]:
    """Rapport en base. `profile=None` => empreinte absente (rapport legacy)."""
    metrics: Dict[str, Any] = {"engine_version": "CinemaLux_v1", "probe_quality": "FULL"}
    if profile is not None:
        metrics["profile_fingerprint"] = quality_report_support.profile_fingerprint(profile)
    if rules_version is not None:
        metrics["scoring_rules_version"] = rules_version
    return {
        "score": 55,
        "tier": "Silver",
        "profile_id": "CinemaLux_v1",
        "profile_version": 1,
        "metrics": metrics,
    }


def _call(
    *,
    existing: Dict[str, Any],
    active_profile: Dict[str, Any],
    media_reachable: bool,
) -> Dict[str, Any]:
    """Joue le gate de cache.

    `media_reachable=False` fournit la ligne de plan mais aucun media resolvable :
    c'est l'etat d'un run DEJA APPLIQUE (le dossier source a bouge), le seul ou
    le repli « stale » peut s'exprimer. Avec `True`, aucune ligne de plan n'est
    fournie : un refus de cache se voit alors a l'erreur « introuvable dans ce
    plan », qui prouve qu'on est reparti en analyse.
    """
    api = MagicMock()
    api.settings.get_settings.return_value = {}
    plan_row = MagicMock()
    plan_row.row_id = "row_1"
    api._load_rows_from_plan_jsonl.return_value = [] if media_reachable else [plan_row]
    api._resolve_media_path_for_row.return_value = None
    api._get_run.return_value = None
    api._ensure_quality_profile.return_value = {
        "id": str(active_profile.get("id") or ""),
        "version": int(active_profile.get("version") or 1),
        "profile_json": active_profile,
    }
    store = MagicMock()
    store.quality.get_quality_report.return_value = existing
    api._find_run_row.return_value = ({"state_dir": _FAKE_ROOT}, store)
    with patch.object(quality_report_support, "enrich_quality_report_with_perceptual"):
        return quality_report_support.get_quality_report(api, "run_test", "row_1", {"reuse_existing": True})


class BothGatesAreRequiredForACacheHitTests(unittest.TestCase):
    """Le cache n'est servi que si les DEUX estampilles concordent."""

    def test_profile_and_rules_both_current_is_a_cache_hit(self) -> None:
        """Non-regression : composer les gardes ne doit pas eteindre le cache."""
        profile = _profile()
        res = _call(
            existing=_persisted(profile=profile, rules_version=SCORING_RULES_VERSION),
            active_profile=profile,
            media_reachable=True,
        )
        self.assertEqual(str(res.get("status")), "ignored_existing")
        self.assertTrue(bool(res.get("cache_hit_quality")))
        self.assertNotIn("scoring_rules_stale", res)

    def test_an_edited_profile_defeats_a_current_rules_stamp(self) -> None:
        """L'estampille de regles a jour ne rachete PAS un profil edite (N30)."""
        res = _call(
            existing=_persisted(profile=_profile(70), rules_version=SCORING_RULES_VERSION),
            active_profile=_profile(95),
            media_reachable=True,
        )
        self.assertNotEqual(str(res.get("status")), "ignored_existing")
        self.assertFalse(bool(res.get("ok")))

    def test_an_outdated_rules_stamp_defeats_an_identical_profile(self) -> None:
        """Symetrique : le profil identique ne rachete pas une regle changee."""
        profile = _profile()
        res = _call(
            existing=_persisted(profile=profile, rules_version=None),
            active_profile=profile,
            media_reachable=True,
        )
        self.assertNotEqual(str(res.get("status")), "ignored_existing")
        self.assertFalse(bool(res.get("ok")))

    def test_an_unreadable_profile_refuses_the_cache_even_if_everything_matches(self) -> None:
        """Fail-closed : empreinte active vide => on ne sert jamais le cache."""
        circulaire: Dict[str, Any] = dict(_profile())
        circulaire["self"] = circulaire  # json.dumps -> ValueError -> empreinte ""
        res = _call(
            existing=_persisted(profile=None, rules_version=SCORING_RULES_VERSION),
            active_profile=circulaire,
            media_reachable=True,
        )
        self.assertNotEqual(str(res.get("status")), "ignored_existing")
        self.assertFalse(bool(res.get("ok")))


class TheStaleFallbackRequiresAProvenProfileTests(unittest.TestCase):
    """Le repli du run deja applique ne vaut que pour l'estampille de CODE."""

    def test_same_profile_outdated_rules_still_degrades_to_the_stale_score(self) -> None:
        """Le repli de PR#854 survit a la fusion : c'est son cas nominal."""
        profile = _profile()
        res = _call(
            existing=_persisted(profile=profile, rules_version=None),
            active_profile=profile,
            media_reachable=False,
        )
        self.assertTrue(bool(res.get("ok")), res)
        self.assertEqual(str(res.get("status")), "ignored_existing")
        self.assertTrue(bool(res.get("scoring_rules_stale")))
        self.assertEqual(int(res.get("score") or 0), 55)

    def test_a_legacy_report_without_fingerprint_gets_no_stale_fallback(self) -> None:
        """Point d'arbitrage de la fusion.

        Un rapport anterieur a N30 ne porte aucune empreinte : rien ne prouve
        qu'il a ete calcule avec le profil courant, l'utilisateur ayant pu
        editer ses seuils entre-temps sans changer la version. Le rendre marque
        `scoring_rules_stale` mentirait sur la cause ET rouvrirait exactement le
        faux positif que N30 ferme — d'autant que ce drapeau n'est lu par aucune
        vue du dashboard aujourd'hui : cote utilisateur, il serait servi comme un
        score ordinaire. On rend donc l'erreur franche.
        """
        res = _call(
            existing=_persisted(profile=None, rules_version=None),
            active_profile=_profile(),
            media_reachable=False,
        )
        self.assertFalse(bool(res.get("ok")), res)
        self.assertNotIn("scoring_rules_stale", res)
        self.assertIsNone(res.get("score"))

    def test_an_edited_profile_gets_no_stale_fallback_either(self) -> None:
        res = _call(
            existing=_persisted(profile=_profile(70), rules_version=None),
            active_profile=_profile(95),
            media_reachable=False,
        )
        self.assertFalse(bool(res.get("ok")), res)
        self.assertNotIn("scoring_rules_stale", res)


if __name__ == "__main__":
    unittest.main()
