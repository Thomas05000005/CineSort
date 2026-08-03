"""Tests SCORE-01 (Vague M, M-06) : explain_score._compute_baseline defaults alignes.

Avant SCORE-01, _compute_baseline utilisait des defaults legacy 85/68/54/30
quand le profil ne fournissait pas de seuils explicites, ce qui divergeait
de quality_score.default_quality_profile() v1.5.7 (70/66/55/40).

Symptome : ``distance_to_next_tier`` faux pour les profils minimalistes, ce
qui faussait les suggestions et le narrative explain-score.
"""

from __future__ import annotations

import unittest

from cinesort.domain.explain_score import build_rich_explanation


class ComputeBaselineDefaultsAlignedTests(unittest.TestCase):
    """Verifie que les defaults v1.5.7 (70/66/55/40) sont utilises quand le
    profil ne specifie pas de seuils tiers explicitement."""

    def _build_with_empty_tiers(self, score: int, tier: str):
        return build_rich_explanation(
            score=score,
            tier=tier,
            factors=[],
            subscores={"video": 60, "audio": 60, "extras": 60},
            weights={"video": 60, "audio": 30, "extras": 10},
            tier_thresholds={},
        )

    def test_defaults_v157_thresholds_used_when_empty(self):
        result = self._build_with_empty_tiers(50, "Silver")
        baseline = result["baseline"]
        thresholds = baseline["tier_thresholds"]
        # Defaults SCORE-01 (alignes sur calibration biblio reelle v1.5.7)
        self.assertEqual(thresholds["Platinum"], 70)
        self.assertEqual(thresholds["Gold"], 66)
        self.assertEqual(thresholds["Silver"], 55)
        self.assertEqual(thresholds["Bronze"], 40)

    def test_distance_to_next_tier_uses_v157_defaults(self):
        # Score 50 -> distance vers Silver (55) = 5 (pas 4 comme legacy 54)
        result = self._build_with_empty_tiers(50, "Bronze")
        self.assertEqual(result["baseline"]["next_tier"], "Silver")
        self.assertEqual(result["baseline"]["distance_to_next_tier"], 5)

    def test_distance_to_platinum_uses_v157_defaults(self):
        # Score 68 -> next = Platinum (70), distance = 2 (pas 17 comme legacy 85)
        result = self._build_with_empty_tiers(68, "Gold")
        self.assertEqual(result["baseline"]["next_tier"], "Platinum")
        self.assertEqual(result["baseline"]["distance_to_next_tier"], 2)

    def test_legacy_premium_alias_still_supported(self):
        # Un profil sauvegarde pre-v1.5.5 doit toujours fonctionner via les
        # alias premium/bon/moyen.
        result = build_rich_explanation(
            score=80,
            tier="Platinum",
            factors=[],
            subscores={"video": 80, "audio": 80, "extras": 80},
            weights={"video": 60, "audio": 30, "extras": 10},
            tier_thresholds={"premium": 85, "bon": 68, "moyen": 54, "bronze": 30},
        )
        thresholds = result["baseline"]["tier_thresholds"]
        self.assertEqual(thresholds["Platinum"], 85)
        self.assertEqual(thresholds["Gold"], 68)
        self.assertEqual(thresholds["Silver"], 54)
        self.assertEqual(thresholds["Bronze"], 30)

    def test_canonical_thresholds_preserved(self):
        # Profil moderne avec seuils explicites : ils doivent etre utilises tels quels.
        result = build_rich_explanation(
            score=72,
            tier="Platinum",
            factors=[],
            subscores={"video": 75, "audio": 70, "extras": 80},
            weights={"video": 60, "audio": 30, "extras": 10},
            tier_thresholds={"platinum": 70, "gold": 66, "silver": 55, "bronze": 40},
        )
        thresholds = result["baseline"]["tier_thresholds"]
        self.assertEqual(thresholds["Platinum"], 70)
        self.assertEqual(thresholds["Gold"], 66)
        self.assertEqual(thresholds["Silver"], 55)
        self.assertEqual(thresholds["Bronze"], 40)
        # Score 72 -> aucun tier superieur (deja Platinum max)
        self.assertIsNone(result["baseline"]["next_tier"])

    def test_partial_tier_thresholds_filled_with_defaults(self):
        # Seul platinum est specifie : les autres defaults v1.5.7 sont remplis.
        result = build_rich_explanation(
            score=60,
            tier="Silver",
            factors=[],
            subscores={"video": 60, "audio": 60, "extras": 60},
            weights={"video": 60, "audio": 30, "extras": 10},
            tier_thresholds={"platinum": 80},
        )
        thresholds = result["baseline"]["tier_thresholds"]
        self.assertEqual(thresholds["Platinum"], 80)  # specifie
        self.assertEqual(thresholds["Gold"], 66)  # default v1.5.7
        self.assertEqual(thresholds["Silver"], 55)  # default v1.5.7
        self.assertEqual(thresholds["Bronze"], 40)  # default v1.5.7


if __name__ == "__main__":
    unittest.main()
