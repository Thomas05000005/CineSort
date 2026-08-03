"""Tests SCORE-02 (Vague M, M-06) : tiers_helpers central + alias legacy.

Verifie que le module tiers_helpers absorbe correctement la retro-compat
legacy pre-v1.5.5 (premium/bon/moyen/faible) pour TOUS les helpers exposes,
sans regression de comportement vs. l'ancienne logique dispersee.
"""

from __future__ import annotations

import unittest

from cinesort.domain.tiers_helpers import (
    DEFAULT_TIER_THRESHOLDS,
    TIER_ORDER_BEST_FIRST,
    TIER_ORDER_WORST_FIRST,
    TIER_V2_CANONICAL,
    cap_tier,
    determine_tier,
    is_premium_tier,
    normalize_tier_string,
    normalize_tiers,
    reconcile_display_tier,
    tier_label_fr,
    tier_min_score,
    tier_order,
    tier_ordinal,
    to_canonical_v2_tier,
)


class NormalizeTierStringTests(unittest.TestCase):
    def test_canonical_names_pass_through(self):
        for canonical in ("Platinum", "Gold", "Silver", "Bronze", "Reject"):
            self.assertEqual(normalize_tier_string(canonical), canonical)

    def test_legacy_aliases_mapped(self):
        self.assertEqual(normalize_tier_string("Premium"), "Platinum")
        self.assertEqual(normalize_tier_string("Bon"), "Gold")
        self.assertEqual(normalize_tier_string("Moyen"), "Silver")
        self.assertEqual(normalize_tier_string("Faible"), "Bronze")
        self.assertEqual(normalize_tier_string("Mauvais"), "Reject")

    def test_case_insensitive(self):
        self.assertEqual(normalize_tier_string("platinum"), "Platinum")
        self.assertEqual(normalize_tier_string("PLATINUM"), "Platinum")
        self.assertEqual(normalize_tier_string("  premium  "), "Platinum")

    def test_fr_long_labels_accepted(self):
        self.assertEqual(normalize_tier_string("Platine"), "Platinum")

    def test_unknown_returns_empty_string(self):
        self.assertEqual(normalize_tier_string(""), "")
        self.assertEqual(normalize_tier_string(None), "")
        self.assertEqual(normalize_tier_string("UnknownTier"), "")

    def test_non_string_input_safe(self):
        # int / dict ne crashent pas
        self.assertEqual(normalize_tier_string(42), "")


class NormalizeTiersTests(unittest.TestCase):
    def test_empty_returns_defaults(self):
        self.assertEqual(normalize_tiers({}), DEFAULT_TIER_THRESHOLDS)
        self.assertEqual(normalize_tiers(None), DEFAULT_TIER_THRESHOLDS)

    def test_legacy_keys_mapped_to_canonical(self):
        result = normalize_tiers({"premium": 85, "bon": 70, "moyen": 50, "faible": 30})
        self.assertEqual(result["platinum"], 85)
        self.assertEqual(result["gold"], 70)
        self.assertEqual(result["silver"], 50)
        self.assertEqual(result["bronze"], 30)

    def test_canonical_keys_preserved(self):
        result = normalize_tiers({"platinum": 80, "gold": 65, "silver": 50, "bronze": 35})
        self.assertEqual(result, {"platinum": 80, "gold": 65, "silver": 50, "bronze": 35})

    def test_canonical_takes_priority_over_legacy(self):
        # Si les deux sont presents, le canonique gagne (semantique attendue)
        result = normalize_tiers({"platinum": 90, "premium": 50})
        self.assertEqual(result["platinum"], 90)

    def test_clamp_0_100(self):
        result = normalize_tiers({"platinum": 150, "gold": -10})
        self.assertEqual(result["platinum"], 100)
        self.assertEqual(result["gold"], 0)

    def test_invalid_values_use_defaults(self):
        result = normalize_tiers({"platinum": "abc", "gold": None})
        self.assertEqual(result["platinum"], DEFAULT_TIER_THRESHOLDS["platinum"])
        self.assertEqual(result["gold"], DEFAULT_TIER_THRESHOLDS["gold"])


class TierOrderTests(unittest.TestCase):
    def test_best_first_ordering(self):
        self.assertEqual(tier_order("Platinum"), 0)
        self.assertEqual(tier_order("Gold"), 1)
        self.assertEqual(tier_order("Silver"), 2)
        self.assertEqual(tier_order("Bronze"), 3)
        self.assertEqual(tier_order("Reject"), 4)

    def test_legacy_aliases(self):
        self.assertEqual(tier_order("Premium"), 0)
        self.assertEqual(tier_order("Bon"), 1)

    def test_unknown_returns_sentinel(self):
        self.assertEqual(tier_order("???"), len(TIER_ORDER_BEST_FIRST))


class TierOrdinalTests(unittest.TestCase):
    """Coherence avec l'ancien calibration.tier_ordinal."""

    def test_worst_first_ordering(self):
        self.assertEqual(tier_ordinal("Reject"), 0)
        self.assertEqual(tier_ordinal("Bronze"), 1)
        self.assertEqual(tier_ordinal("Silver"), 2)
        self.assertEqual(tier_ordinal("Gold"), 3)
        self.assertEqual(tier_ordinal("Platinum"), 4)

    def test_legacy_aliases(self):
        self.assertEqual(tier_ordinal("Premium"), 4)
        self.assertEqual(tier_ordinal("Bon"), 3)
        self.assertEqual(tier_ordinal("Moyen"), 2)
        self.assertEqual(tier_ordinal("Mauvais"), 0)

    def test_unknown_returns_minus_one(self):
        self.assertEqual(tier_ordinal("???"), -1)
        self.assertEqual(tier_ordinal(""), -1)
        self.assertEqual(tier_ordinal(None), -1)


class IsPremiumTierTests(unittest.TestCase):
    def test_platinum_and_gold_are_premium(self):
        self.assertTrue(is_premium_tier("Platinum"))
        self.assertTrue(is_premium_tier("Gold"))

    def test_silver_bronze_reject_are_not_premium(self):
        self.assertFalse(is_premium_tier("Silver"))
        self.assertFalse(is_premium_tier("Bronze"))
        self.assertFalse(is_premium_tier("Reject"))

    def test_legacy_aliases_premium(self):
        self.assertTrue(is_premium_tier("Premium"))
        self.assertTrue(is_premium_tier("Bon"))
        self.assertFalse(is_premium_tier("Moyen"))


class TierLabelFrTests(unittest.TestCase):
    def test_canonical_labels(self):
        self.assertEqual(tier_label_fr("Platinum"), "Platine")
        self.assertEqual(tier_label_fr("Gold"), "Or")
        self.assertEqual(tier_label_fr("Silver"), "Argent")
        self.assertEqual(tier_label_fr("Bronze"), "Bronze")
        self.assertEqual(tier_label_fr("Reject"), "Rejete")

    def test_legacy_aliases_yield_canonical_fr(self):
        self.assertEqual(tier_label_fr("Premium"), "Platine")
        self.assertEqual(tier_label_fr("Bon"), "Or")

    def test_unknown_returns_empty(self):
        self.assertEqual(tier_label_fr("???"), "")


class TierMinScoreTests(unittest.TestCase):
    def test_defaults_v157(self):
        # Defaults alignes sur quality_score.default_quality_profile() v1.5.7
        self.assertEqual(tier_min_score("Platinum"), 70)
        self.assertEqual(tier_min_score("Gold"), 66)
        self.assertEqual(tier_min_score("Silver"), 55)
        self.assertEqual(tier_min_score("Bronze"), 40)

    def test_reject_is_zero(self):
        self.assertEqual(tier_min_score("Reject"), 0)

    def test_custom_profile_tiers(self):
        prof = {"platinum": 90, "gold": 75, "silver": 60, "bronze": 45}
        self.assertEqual(tier_min_score("Platinum", prof), 90)
        self.assertEqual(tier_min_score("Gold", prof), 75)

    def test_legacy_profile_tiers(self):
        # Profil sauvegarde avant migration 011
        prof = {"premium": 85, "bon": 70, "moyen": 50, "bronze": 30}
        self.assertEqual(tier_min_score("Platinum", prof), 85)
        self.assertEqual(tier_min_score("Gold", prof), 70)
        self.assertEqual(tier_min_score("Silver", prof), 50)
        self.assertEqual(tier_min_score("Bronze", prof), 30)


class DetermineTierTests(unittest.TestCase):
    """Equivalence comportementale avec quality_score._determine_tier."""

    def test_defaults_v157(self):
        self.assertEqual(determine_tier(100), "Platinum")
        self.assertEqual(determine_tier(70), "Platinum")
        self.assertEqual(determine_tier(69), "Gold")
        self.assertEqual(determine_tier(66), "Gold")
        self.assertEqual(determine_tier(65), "Silver")
        self.assertEqual(determine_tier(55), "Silver")
        self.assertEqual(determine_tier(40), "Bronze")
        self.assertEqual(determine_tier(39), "Reject")
        self.assertEqual(determine_tier(0), "Reject")

    def test_legacy_profile_pre_v155(self):
        # Profil legacy avant v1.5.5 : premium 85, bon 68, moyen 54, bronze 30
        prof = {"premium": 85, "bon": 68, "moyen": 54, "bronze": 30}
        self.assertEqual(determine_tier(86, prof), "Platinum")
        self.assertEqual(determine_tier(68, prof), "Gold")
        self.assertEqual(determine_tier(54, prof), "Silver")
        self.assertEqual(determine_tier(30, prof), "Bronze")
        self.assertEqual(determine_tier(29, prof), "Reject")


class CapTierTests(unittest.TestCase):
    """Equivalence comportementale avec quality_score._cap_tier."""

    def test_cap_lowers_tier(self):
        self.assertEqual(cap_tier("Platinum", "Silver"), "Silver")
        self.assertEqual(cap_tier("Gold", "Bronze"), "Bronze")

    def test_cap_does_not_raise_tier(self):
        # On NE remonte jamais : Bronze < Silver => garde Bronze
        self.assertEqual(cap_tier("Bronze", "Silver"), "Bronze")
        self.assertEqual(cap_tier("Reject", "Platinum"), "Reject")

    def test_cap_with_legacy_aliases(self):
        self.assertEqual(cap_tier("Premium", "Gold"), "Gold")
        self.assertEqual(cap_tier("Bon", "Bronze"), "Bronze")


class ConstantsCoherenceTests(unittest.TestCase):
    """Garantit que les constantes restent coherentes avec les autres modules."""

    def test_best_first_is_reverse_of_worst_first(self):
        self.assertEqual(TIER_ORDER_BEST_FIRST, list(reversed(TIER_ORDER_WORST_FIRST)))

    def test_defaults_match_quality_profile(self):
        # MEMOIRE INVIOLABLE : ne pas changer ces seuils sans recalibrage biblio.
        # Coherence avec default_quality_profile() v1.5.7.
        from cinesort.domain.quality_score import default_quality_profile

        prof_tiers = default_quality_profile()["tiers"]
        self.assertEqual(DEFAULT_TIER_THRESHOLDS["platinum"], prof_tiers["platinum"])
        self.assertEqual(DEFAULT_TIER_THRESHOLDS["gold"], prof_tiers["gold"])
        self.assertEqual(DEFAULT_TIER_THRESHOLDS["silver"], prof_tiers["silver"])
        self.assertEqual(DEFAULT_TIER_THRESHOLDS["bronze"], prof_tiers["bronze"])


class ToCanonicalV2TierTests(unittest.TestCase):
    """VN-B.2 : normalisation tout -> echelle V2 lowercase."""

    def test_v2_lowercase_pass_through(self):
        for canonical in TIER_V2_CANONICAL:
            self.assertEqual(to_canonical_v2_tier(canonical), canonical)

    def test_v1_capitalized_to_v2_lowercase(self):
        self.assertEqual(to_canonical_v2_tier("Platinum"), "platinum")
        self.assertEqual(to_canonical_v2_tier("Gold"), "gold")
        self.assertEqual(to_canonical_v2_tier("Silver"), "silver")
        self.assertEqual(to_canonical_v2_tier("Bronze"), "bronze")
        self.assertEqual(to_canonical_v2_tier("Reject"), "reject")

    def test_legacy_aliases_to_v2(self):
        self.assertEqual(to_canonical_v2_tier("Premium"), "platinum")
        self.assertEqual(to_canonical_v2_tier("Bon"), "gold")
        self.assertEqual(to_canonical_v2_tier("Moyen"), "silver")
        self.assertEqual(to_canonical_v2_tier("Faible"), "bronze")
        self.assertEqual(to_canonical_v2_tier("Mauvais"), "reject")

    def test_empty_and_none(self):
        self.assertEqual(to_canonical_v2_tier(""), "")
        self.assertEqual(to_canonical_v2_tier(None), "")
        self.assertEqual(to_canonical_v2_tier("   "), "")

    def test_unknown_returns_empty(self):
        self.assertEqual(to_canonical_v2_tier("???"), "")
        self.assertEqual(to_canonical_v2_tier("UnknownTier"), "")

    def test_case_normalization_mixed(self):
        self.assertEqual(to_canonical_v2_tier("PLATINUM"), "platinum")
        self.assertEqual(to_canonical_v2_tier("  Gold  "), "gold")


class ReconcileDisplayTierTests(unittest.TestCase):
    """VN-B.2 : reconcile_display_tier remplace le fallback OR de library_support."""

    def test_v2_perceptual_priority(self):
        display, source = reconcile_display_tier(perc_tier_v2="platinum", qual_tier_v1="Bronze")
        self.assertEqual(display, "platinum")
        self.assertEqual(source, "perceptual")

    def test_v1_fallback_when_no_v2(self):
        display, source = reconcile_display_tier(perc_tier_v2=None, qual_tier_v1="Gold")
        self.assertEqual(display, "gold")
        self.assertEqual(source, "quality_v1")

    def test_legacy_v1_alias_fallback(self):
        # quality_report.tier sauvegarde pre-v1.5.5 (Premium au lieu de Platinum)
        display, source = reconcile_display_tier(perc_tier_v2=None, qual_tier_v1="Premium")
        self.assertEqual(display, "platinum")
        self.assertEqual(source, "quality_v1")

    def test_v2_lowercase_in_quality_marked_as_v2(self):
        # cas rare : quality_report.tier deja en lowercase V2
        display, source = reconcile_display_tier(perc_tier_v2=None, qual_tier_v1="silver")
        self.assertEqual(display, "silver")
        self.assertEqual(source, "quality_v2")

    def test_both_none_returns_fallback(self):
        display, source = reconcile_display_tier(perc_tier_v2=None, qual_tier_v1=None)
        self.assertEqual(display, "unknown")
        self.assertEqual(source, "fallback")

    def test_empty_strings_fallback(self):
        display, source = reconcile_display_tier(perc_tier_v2="", qual_tier_v1="")
        self.assertEqual(display, "unknown")
        self.assertEqual(source, "fallback")

    def test_custom_default(self):
        display, source = reconcile_display_tier(default="bronze")
        self.assertEqual(display, "bronze")
        self.assertEqual(source, "fallback")

    def test_perceptual_capitalized_normalized(self):
        # perceptual peut theoriquement renvoyer Capitalized (defensive)
        display, source = reconcile_display_tier(perc_tier_v2="Platinum", qual_tier_v1="Bronze")
        self.assertEqual(display, "platinum")
        self.assertEqual(source, "perceptual")

    def test_unknown_perceptual_falls_back_to_v1(self):
        # perc.global_tier_v2 = "???" doit etre traite comme absent
        display, source = reconcile_display_tier(perc_tier_v2="???", qual_tier_v1="Gold")
        self.assertEqual(display, "gold")
        self.assertEqual(source, "quality_v1")

    def test_no_mixing_v1_v2_thresholds(self):
        """MEMOIRE : V1 (70/66/55/40) et V2 (90/80/65/50) ne se melangent plus.

        Un film Platinum V1 (score 75) reste affiche platinum (pas Silver V2)
        - la reconciliation est une normalisation de label, pas un recalcul.
        Le scoring V2 reel viendra raffiner si l'analyse perceptuelle est
        lancee.
        """
        display, _src = reconcile_display_tier(perc_tier_v2=None, qual_tier_v1="Platinum")
        self.assertEqual(display, "platinum")


if __name__ == "__main__":
    unittest.main()
