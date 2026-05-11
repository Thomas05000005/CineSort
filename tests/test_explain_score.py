"""P2.1 : tests pour explain_score.build_rich_explanation.

Suite étendue : classification direction, weighted_delta pondéré correctement,
categories breakdown, baseline (distance au tier suivant), suggestions
actionables, narrative FR lisible.
"""

from __future__ import annotations

import unittest

from cinesort.domain.explain_score import build_rich_explanation


def _call(
    score: int,
    tier: str,
    factors: list | None = None,
    subscores: dict | None = None,
    weights: dict | None = None,
    tier_thresholds: dict | None = None,
) -> dict:
    """Factory fixtures — valeurs par défaut raisonnables."""
    return build_rich_explanation(
        score=score,
        tier=tier,
        factors=factors or [],
        subscores=subscores or {"video": 80, "audio": 70, "extras": 60},
        weights=weights or {"video": 60, "audio": 30, "extras": 10},
        tier_thresholds=tier_thresholds or {"platinum": 85, "gold": 68, "silver": 54, "bronze": 30},
    )


class FactorEnrichmentTests(unittest.TestCase):
    def test_direction_classification(self):
        factors = [
            {"category": "video", "delta": 10, "label": "HEVC bonus"},
            {"category": "video", "delta": -5, "label": "Low bitrate"},
            {"category": "audio", "delta": 0, "label": "Standard audio"},
        ]
        r = _call(80, "Gold", factors=factors)
        dirs = [f["direction"] for f in r["factors"]]
        self.assertEqual(dirs, ["+", "-", "="])

    def test_weighted_delta_video(self):
        # video weight = 60%, delta video +10 → weighted = 6.0
        factors = [{"category": "video", "delta": 10, "label": "HEVC"}]
        r = _call(80, "Gold", factors=factors)
        self.assertEqual(r["factors"][0]["weighted_delta"], 6.0)

    def test_weighted_delta_audio(self):
        # audio weight = 30%, delta +10 → weighted = 3.0
        factors = [{"category": "audio", "delta": 10, "label": "Atmos"}]
        r = _call(80, "Gold", factors=factors)
        self.assertEqual(r["factors"][0]["weighted_delta"], 3.0)

    def test_weighted_delta_extras(self):
        # extras weight = 10%, delta +10 → weighted = 1.0
        factors = [{"category": "extras", "delta": 10, "label": "Subs FR"}]
        r = _call(80, "Gold", factors=factors)
        self.assertEqual(r["factors"][0]["weighted_delta"], 1.0)

    def test_weighted_delta_zero_stays_zero(self):
        factors = [{"category": "video", "delta": 0, "label": "Neutre"}]
        r = _call(80, "Gold", factors=factors)
        self.assertEqual(r["factors"][0]["weighted_delta"], 0.0)

    def test_weighted_delta_custom_counts_as_video(self):
        # custom factors s'appliquent au video_sub dans compute_quality_score
        factors = [{"category": "custom", "delta": 10, "label": "Rule X"}]
        r = _call(80, "Gold", factors=factors)
        self.assertEqual(r["factors"][0]["weighted_delta"], 6.0)  # video weight


class CategoriesBreakdownTests(unittest.TestCase):
    def test_breakdown_includes_all_three(self):
        r = _call(75, "Gold")
        self.assertIn("video", r["categories"])
        self.assertIn("audio", r["categories"])
        self.assertIn("extras", r["categories"])

    def test_breakdown_weight_pct_sums_to_100(self):
        r = _call(75, "Gold")
        total = sum(r["categories"][c]["weight_pct"] for c in ("video", "audio", "extras"))
        self.assertAlmostEqual(total, 100.0, places=0)

    def test_breakdown_contribution_sums_approx_score(self):
        # Avec les subscores fixtures et weights 60/30/10 :
        # video 80 * 0.6 = 48
        # audio 70 * 0.3 = 21
        # extras 60 * 0.1 = 6
        # total = 75 ≈ score fixture 75
        r = _call(75, "Gold")
        total = sum(r["categories"][c]["contribution"] for c in ("video", "audio", "extras"))
        self.assertAlmostEqual(total, 75.0, places=0)

    def test_breakdown_counts_positive_and_negative(self):
        factors = [
            {"category": "video", "delta": 10, "label": "A"},
            {"category": "video", "delta": -5, "label": "B"},
            {"category": "audio", "delta": 3, "label": "C"},
        ]
        r = _call(75, "Gold", factors=factors)
        self.assertEqual(r["categories"]["video"]["positive_count"], 1)
        self.assertEqual(r["categories"]["video"]["negative_count"], 1)
        self.assertEqual(r["categories"]["audio"]["positive_count"], 1)

    def test_breakdown_has_french_label(self):
        r = _call(75, "Gold")
        self.assertEqual(r["categories"]["video"]["label"], "Vidéo")
        self.assertEqual(r["categories"]["audio"]["label"], "Audio")


class BaselineTests(unittest.TestCase):
    def test_next_tier_when_close_to_platinum(self):
        r = _call(82, "Gold")
        self.assertEqual(r["baseline"]["next_tier"], "Platinum")
        self.assertEqual(r["baseline"]["distance_to_next_tier"], 3)

    def test_next_tier_none_when_platinum(self):
        r = _call(95, "Platinum")
        self.assertIsNone(r["baseline"]["next_tier"])

    def test_baseline_includes_all_thresholds(self):
        r = _call(75, "Gold")
        thresholds = r["baseline"]["tier_thresholds"]
        self.assertEqual(thresholds["Platinum"], 85)
        self.assertEqual(thresholds["Gold"], 68)
        self.assertEqual(thresholds["Silver"], 54)
        self.assertEqual(thresholds["Bronze"], 30)

    def test_baseline_uses_legacy_threshold_names(self):
        # Rétrocompat : si un profil utilise encore "premium"/"bon"
        thresholds = {"premium": 90, "bon": 70, "silver": 54, "bronze": 30}
        r = _call(75, "Gold", tier_thresholds=thresholds)
        self.assertEqual(r["baseline"]["tier_thresholds"]["Platinum"], 90)
        self.assertEqual(r["baseline"]["tier_thresholds"]["Gold"], 70)


class SuggestionsTests(unittest.TestCase):
    def test_upscale_triggers_suggestion(self):
        factors = [{"category": "video", "delta": -8, "label": "Upscale suspect"}]
        r = _call(60, "Silver", factors=factors)
        self.assertTrue(any("upscale" in s.lower() for s in r["suggestions"]))

    def test_4k_light_triggers_suggestion(self):
        factors = [{"category": "video", "delta": -3, "label": "4K light (streaming)"}]
        r = _call(70, "Gold", factors=factors)
        self.assertTrue(any("remux" in s.lower() or "35 mbps" in s.lower() for s in r["suggestions"]))

    def test_no_suggestion_when_no_negative_and_far_from_next(self):
        r = _call(60, "Silver")  # Silver, loin de Gold (68)
        self.assertEqual(r["suggestions"], [])

    def test_generic_suggestion_when_close_to_next_tier(self):
        r = _call(66, "Silver")  # à 2 points de Gold (68)
        self.assertTrue(r["suggestions"])
        self.assertTrue(any("gold" in s.lower() or "2 point" in s.lower() for s in r["suggestions"]))

    def test_suggestions_are_unique(self):
        factors = [
            {"category": "video", "delta": -8, "label": "Upscale suspect version 1"},
            {"category": "video", "delta": -8, "label": "Upscale suspect version 2"},
        ]
        r = _call(60, "Silver", factors=factors)
        # Même suggestion ne doit apparaître qu'une fois
        self.assertEqual(len(r["suggestions"]), len(set(r["suggestions"])))


class NarrativeTests(unittest.TestCase):
    def test_narrative_mentions_score_and_tier(self):
        r = _call(82, "Gold")
        self.assertIn("82", r["narrative"])
        self.assertIn("Gold", r["narrative"])

    def test_narrative_mentions_best_and_worst_category(self):
        subscores = {"video": 95, "audio": 40, "extras": 70}
        r = _call(75, "Gold", subscores=subscores)
        narrative_lower = r["narrative"].lower()
        # On doit évoquer vidéo (le meilleur) ET audio (le pire)
        self.assertIn("vidéo", narrative_lower)
        self.assertIn("audio", narrative_lower)

    def test_narrative_mentions_distance_to_next_tier_when_close(self):
        r = _call(82, "Gold")  # à 3 de Platinum
        self.assertIn("3", r["narrative"])
        self.assertIn("Platinum", r["narrative"])

    def test_narrative_skips_distance_when_far(self):
        r = _call(55, "Silver")  # loin de Gold (68)
        # La distance ne doit PAS apparaître (seulement si <= 10)
        self.assertNotIn("13 point", r["narrative"])

    def test_narrative_handles_no_factors(self):
        r = _call(75, "Gold", factors=[])
        # Ne doit pas crasher, doit être lisible
        self.assertTrue(r["narrative"])
        self.assertIn("75", r["narrative"])


class TopPositiveNegativeTests(unittest.TestCase):
    def test_top_positive_sorted_by_weighted_impact(self):
        # Un gros delta audio (10*0.3=3) doit passer AVANT un petit delta video (4*0.6=2.4)
        factors = [
            {"category": "audio", "delta": 10, "label": "Atmos"},  # weighted 3.0
            {"category": "video", "delta": 4, "label": "HEVC"},  # weighted 2.4
        ]
        r = _call(80, "Gold", factors=factors)
        self.assertEqual(r["top_positive"][0]["label"], "Atmos")

    def test_top_negative_sorted_by_weighted_impact(self):
        factors = [
            {"category": "audio", "delta": -5, "label": "Mono"},  # weighted -1.5
            {"category": "video", "delta": -4, "label": "Low bitrate"},  # weighted -2.4
        ]
        r = _call(60, "Silver", factors=factors)
        self.assertEqual(r["top_negative"][0]["label"], "Low bitrate")

    def test_top_3_limit(self):
        factors = [{"category": "video", "delta": 10, "label": f"Factor{i}"} for i in range(5)]
        r = _call(80, "Gold", factors=factors)
        self.assertEqual(len(r["top_positive"]), 3)


class RobustnessTests(unittest.TestCase):
    def test_handles_missing_weights_key(self):
        r = build_rich_explanation(
            score=75,
            tier="Gold",
            factors=[],
            subscores={"video": 80, "audio": 70, "extras": 60},
            weights={},  # vide
            tier_thresholds={"platinum": 85, "gold": 68, "silver": 54, "bronze": 30},
        )
        # Ne doit pas crasher, category weight_pct doit être cohérent (0 partout)
        self.assertIn("video", r["categories"])

    def test_handles_negative_weights_gracefully(self):
        r = build_rich_explanation(
            score=75,
            tier="Gold",
            factors=[{"category": "video", "delta": 5, "label": "Test"}],
            subscores={"video": 80, "audio": 70, "extras": 60},
            weights={"video": -10, "audio": 30, "extras": 10},
            tier_thresholds={"platinum": 85, "gold": 68, "silver": 54, "bronze": 30},
        )
        # Doit gérer proprement (pas de division par zéro/nombres négatifs cassés)
        self.assertIsNotNone(r["factors"][0]["weighted_delta"])

    def test_handles_malformed_factor(self):
        # Factor avec delta manquant
        factors = [{"category": "video", "label": "Missing delta"}]
        r = _call(75, "Gold", factors=factors)
        self.assertEqual(r["factors"][0]["direction"], "=")
        self.assertEqual(r["factors"][0]["weighted_delta"], 0.0)


if __name__ == "__main__":
    unittest.main()
