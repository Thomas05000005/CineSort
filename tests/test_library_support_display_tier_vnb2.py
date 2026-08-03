"""VN-B.2 (Vague N batch 2) : tests display_tier explicite end-to-end.

Verifie que _build_display_tier_fields :
  - retourne display_tier en lowercase canonique V2
  - retourne tier_source pour traque debug
  - conserve tier_v2 alias backward compat
  - traite correctement le fallback V1 capitalized -> V2 lowercase
  - traite les rows pre-VN-B.2 (perc.global_tier_v2 absent) sans crasher
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.library_support import _build_display_tier_fields


class BuildDisplayTierFieldsTests(unittest.TestCase):
    """Cas nominaux + edge cases du helper de reconciliation."""

    def test_perceptual_v2_priority(self):
        perc = {"global_tier_v2": "platinum"}
        qual = {"tier": "Bronze"}
        result = _build_display_tier_fields(perc, qual)
        self.assertEqual(result["display_tier"], "platinum")
        self.assertEqual(result["tier_source"], "perceptual")
        # Backward compat : tier_v2 == display_tier
        self.assertEqual(result["tier_v2"], "platinum")

    def test_quality_v1_fallback(self):
        perc = None
        qual = {"tier": "Gold"}
        result = _build_display_tier_fields(perc, qual)
        self.assertEqual(result["display_tier"], "gold")
        self.assertEqual(result["tier_source"], "quality_v1")
        self.assertEqual(result["tier_v2"], "gold")

    def test_legacy_premium_alias_fallback(self):
        # Rapport pre-v1.5.5 avec Premium au lieu de Platinum
        perc = None
        qual = {"tier": "Premium"}
        result = _build_display_tier_fields(perc, qual)
        self.assertEqual(result["display_tier"], "platinum")
        self.assertEqual(result["tier_source"], "quality_v1")

    def test_no_data_unknown(self):
        result = _build_display_tier_fields(None, None)
        self.assertEqual(result["display_tier"], "unknown")
        self.assertEqual(result["tier_source"], "fallback")
        self.assertEqual(result["tier_v2"], "unknown")

    def test_perc_present_without_v2_tier(self):
        # perc existe mais global_tier_v2 absent (run V1 sans V2 calcule)
        perc = {"global_score": 60}
        qual = {"tier": "Silver"}
        result = _build_display_tier_fields(perc, qual)
        self.assertEqual(result["display_tier"], "silver")
        self.assertEqual(result["tier_source"], "quality_v1")

    def test_both_empty_dicts_fallback(self):
        result = _build_display_tier_fields({}, {})
        self.assertEqual(result["display_tier"], "unknown")
        self.assertEqual(result["tier_source"], "fallback")

    def test_no_mixing_v1_v2_thresholds(self):
        """MEMOIRE INVIOLABLE : V1 (70/66/55/40) et V2 (90/80/65/50) ont des
        seuils differents mais on NE recalcule PAS depuis le score. Un film
        Platinum V1 reste 'platinum' (l'utilisateur peut lancer l'analyse V2
        plus tard pour raffiner).
        """
        perc = None
        qual = {"tier": "Platinum", "score": 75}  # Platinum V1 = 70+, pas 90+
        result = _build_display_tier_fields(perc, qual)
        self.assertEqual(result["display_tier"], "platinum")

    def test_unknown_v2_in_perc_falls_back_to_v1(self):
        # perc.global_tier_v2 = "" ou "unknown" doit etre ignore
        perc = {"global_tier_v2": ""}
        qual = {"tier": "Gold"}
        result = _build_display_tier_fields(perc, qual)
        self.assertEqual(result["display_tier"], "gold")
        self.assertEqual(result["tier_source"], "quality_v1")

    def test_display_tier_always_lowercase(self):
        """L'echelle V2 canonique est lowercase. Le frontend mappe sur des
        classes CSS --tier-{name} (hex colors INVARIANTES par memoire).
        """
        for perc_in, qual_in in [
            ({"global_tier_v2": "PLATINUM"}, None),
            ({"global_tier_v2": "Gold"}, None),
            (None, {"tier": "SILVER"}),
            (None, {"tier": "Bronze"}),
        ]:
            with self.subTest(perc=perc_in, qual=qual_in):
                result = _build_display_tier_fields(perc_in, qual_in)
                self.assertEqual(
                    result["display_tier"],
                    result["display_tier"].lower(),
                )

    def test_quality_v2_source_when_already_lowercase(self):
        # Cas rare : quality_report.tier persiste deja en lowercase
        perc = None
        qual = {"tier": "silver"}
        result = _build_display_tier_fields(perc, qual)
        self.assertEqual(result["display_tier"], "silver")
        self.assertEqual(result["tier_source"], "quality_v2")


if __name__ == "__main__":
    unittest.main()
