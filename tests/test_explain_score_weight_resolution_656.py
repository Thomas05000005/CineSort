"""#656 — une seule clef de poids invalide reinitialisait les TROIS poids.

`_weighted_delta_for_factor` castait les trois poids dans un unique `try` :

    try:
        w_video = int(weights.get("video", 60))
        w_audio = int(weights.get("audio", 30))
        w_extras = int(weights.get("extras", 10))
    except (TypeError, ValueError):
        w_video, w_audio, w_extras = 60, 30, 10

`{"video": None, "audio": 300, "extras": 100}` -> `int(None)` leve TypeError et
les poids audio/extras LEGITIMES etaient jetes au profit de 30/10. Le
`weighted_delta` (et donc top_positive / top_negative / narrative) devenait faux.

`_compute_category_contribution` avait le meme tout-ou-rien sur une valeur non
castable. Les deux passent par `_resolve_weight`, resolution PAR CLEF, avec des
defauts propres a chaque fonction (60/30/10 vs 0) — leurs contrats different
deliberement, ce qui change c'est la granularite.

Piege explicitement evite : `int(weights.get(k, d) or d)` — `0 or 60` vaut 60,
un poids delibrement nul serait ressuscite. Ce module documente `0` comme
valeur sentinelle legitime (audit 2026-05-21) ; un test le verrouille ci-dessous.

Tous les tests passent par `build_rich_explanation`, le vrai point d'entree
(appele par `quality_score.compute_quality_score` avec
`weights=prof.get("weights") or {}`, donc un dict venant de la config
utilisateur), et non par les helpers prives.
"""

from __future__ import annotations

import unittest

from cinesort.domain.explain_score import build_rich_explanation

_SUBSCORES = {"video": 80, "audio": 60, "extras": 40}
_TIERS = {"platinum": 70, "gold": 66, "silver": 55, "bronze": 40}


def _explain(weights, factors):
    return build_rich_explanation(
        score=70,
        tier="Platinum",
        factors=factors,
        subscores=_SUBSCORES,
        weights=weights,
        tier_thresholds=_TIERS,
    )


def _weighted(result, label):
    return next(f["weighted_delta"] for f in result["factors"] if f["label"] == label)


class WeightedDeltaPerKeyResolutionTests(unittest.TestCase):
    def test_one_none_key_does_not_discard_the_two_valid_weights(self) -> None:
        result = _explain(
            {"video": None, "audio": 300, "extras": 100},
            [
                {"label": "piste audio", "category": "audio", "delta": 30},
                {"label": "codec video", "category": "video", "delta": 30},
            ],
        )
        # video -> defaut 60 ; audio=300 et extras=100 CONSERVES -> total 460.
        self.assertAlmostEqual(_weighted(result, "piste audio"), round(30 * 300 / 460, 2), places=2)
        self.assertAlmostEqual(_weighted(result, "codec video"), round(30 * 60 / 460, 2), places=2)

    def test_one_uncastable_key_does_not_discard_the_two_valid_weights(self) -> None:
        result = _explain(
            {"video": "soixante", "audio": 300, "extras": 100},
            [{"label": "piste audio", "category": "audio", "delta": 30}],
        )
        self.assertAlmostEqual(_weighted(result, "piste audio"), round(30 * 300 / 460, 2), places=2)

    def test_explicit_zero_weight_is_not_resurrected_to_its_default(self) -> None:
        """Garde anti-`or` : `0` est une valeur sentinelle legitime.

        Un poids video mis a 0 par l'utilisateur doit annuler la contribution
        video, pas retomber sur le defaut 60.
        """
        result = _explain(
            {"video": 0, "audio": 30, "extras": 10},
            [{"label": "codec video", "category": "video", "delta": 30}],
        )
        self.assertEqual(_weighted(result, "codec video"), 0.0)

    def test_absent_keys_still_fall_back_on_60_30_10(self) -> None:
        """Non-regression : l'absence de clef garde le contrat historique."""
        result = _explain({}, [{"label": "piste audio", "category": "audio", "delta": 30}])
        self.assertAlmostEqual(_weighted(result, "piste audio"), round(30 * 30 / 100, 2), places=2)


class CategoryContributionPerKeyResolutionTests(unittest.TestCase):
    def test_one_uncastable_key_does_not_zero_the_whole_breakdown(self) -> None:
        result = _explain({"video": "soixante", "audio": 30, "extras": 10}, [])
        categories = result["categories"]
        # Defauts 0 ici (contrat propre a _compute_category_contribution) :
        # video tombe a 0, mais audio/extras gardent 30/10 -> somme 40.
        self.assertEqual(categories["video"]["weight"], 0)
        self.assertEqual(categories["audio"]["weight"], 30)
        self.assertEqual(categories["audio"]["weight_pct"], 75.0)
        self.assertEqual(categories["extras"]["weight_pct"], 25.0)
        self.assertEqual(categories["audio"]["contribution"], round(60 * 30 / 40, 1))

    def test_all_weights_zero_still_reports_explicit_nulls(self) -> None:
        """Non-regression : le bloc anti-sentinelle (`sum_weights <= 0`) reste actif."""
        result = _explain({"video": 0, "audio": 0, "extras": 0}, [])
        for cat in ("video", "audio", "extras"):
            self.assertEqual(result["categories"][cat]["weight_pct"], 0.0)
            self.assertEqual(result["categories"][cat]["contribution"], 0.0)


if __name__ == "__main__":
    unittest.main()
