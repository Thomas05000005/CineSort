"""Tests SCORE-02 (Vague M, M-06) : 5 profils legacy pre-v1.5.5 valides.

Garantit que les profils sauvegardes AVANT la migration v1.5.5 (qui utilise
les anciennes cles premium/bon/moyen/faible) sont correctement normalises
par TOUS les helpers tiers centralises - aucune regression pour les users
qui auraient un profil JSON exporte ancien dans leur backup.

Parametre sur 5 profils legacy typiques :
1. RemuxStrict legacy (seuils hauts)
2. CinemaLux equilibre legacy (defaults pre-v1.5.5)
3. Light legacy (seuils permissifs)
4. Profil custom user (valeurs exotiques mais valides)
5. Profil mixte legacy+canonique (cas migration partielle)
"""

from __future__ import annotations

import unittest

from cinesort.domain.quality_score import _determine_tier, validate_quality_profile
from cinesort.domain.tiers_helpers import determine_tier, normalize_tiers, tier_ordinal

LEGACY_PROFILES = [
    {
        "id": "legacy_remux_strict",
        "name": "RemuxStrict pre-v1.5.5",
        "tiers": {"premium": 90, "bon": 76, "moyen": 60, "bronze": 30},
        # Score expectations (score -> expected tier)
        "expectations": [
            (95, "Platinum"),
            (90, "Platinum"),
            (89, "Gold"),
            (76, "Gold"),
            (75, "Silver"),
            (60, "Silver"),
            (59, "Bronze"),
            (30, "Bronze"),
            (29, "Reject"),
        ],
    },
    {
        "id": "legacy_cinemalux_default",
        "name": "CinemaLux equilibre pre-v1.5.5",
        "tiers": {"premium": 85, "bon": 68, "moyen": 54, "bronze": 30},
        "expectations": [
            (85, "Platinum"),
            (84, "Gold"),
            (68, "Gold"),
            (54, "Silver"),
            (30, "Bronze"),
            (29, "Reject"),
        ],
    },
    {
        "id": "legacy_light",
        "name": "Light pre-v1.5.5",
        "tiers": {"premium": 80, "bon": 64, "moyen": 50, "faible": 25},
        "expectations": [
            (80, "Platinum"),
            (79, "Gold"),
            (64, "Gold"),
            (50, "Silver"),
            (25, "Bronze"),
            (24, "Reject"),
        ],
    },
    {
        "id": "legacy_user_custom",
        "name": "Custom user pre-v1.5.5",
        "tiers": {"premium": 95, "bon": 80, "moyen": 65, "bronze": 50},
        "expectations": [
            (95, "Platinum"),
            (80, "Gold"),
            (65, "Silver"),
            (50, "Bronze"),
            (49, "Reject"),
        ],
    },
    {
        "id": "legacy_mixed_partial",
        "name": "Migration partielle (mix legacy + canonique)",
        # Cas reel : user a edite manuellement son JSON et a melange noms
        "tiers": {"platinum": 75, "bon": 60, "moyen": 45, "bronze": 30},
        "expectations": [
            (75, "Platinum"),
            (74, "Gold"),
            (60, "Gold"),
            (45, "Silver"),
            (30, "Bronze"),
            (29, "Reject"),
        ],
    },
]


class LegacyProfileNormalizationTests(unittest.TestCase):
    """Verifie que normalize_tiers normalise correctement chaque profil."""

    def test_all_legacy_profiles_normalize_to_canonical_keys(self):
        for prof in LEGACY_PROFILES:
            with self.subTest(profile=prof["id"]):
                result = normalize_tiers(prof["tiers"])
                # Toutes les cles canoniques doivent etre presentes
                self.assertIn("platinum", result)
                self.assertIn("gold", result)
                self.assertIn("silver", result)
                self.assertIn("bronze", result)
                # Aucune cle legacy ne doit subsister
                self.assertNotIn("premium", result)
                self.assertNotIn("bon", result)
                self.assertNotIn("moyen", result)
                self.assertNotIn("faible", result)


class LegacyProfileDetermineTierTests(unittest.TestCase):
    """Verifie que determine_tier (helper central) retourne le bon tier."""

    def test_determine_tier_central_helper(self):
        for prof in LEGACY_PROFILES:
            for score, expected_tier in prof["expectations"]:
                with self.subTest(profile=prof["id"], score=score):
                    self.assertEqual(
                        determine_tier(score, prof["tiers"]),
                        expected_tier,
                    )

    def test_determine_tier_quality_score_module_equivalent(self):
        """quality_score._determine_tier doit produire les memes resultats."""
        for prof in LEGACY_PROFILES:
            for score, expected_tier in prof["expectations"]:
                with self.subTest(profile=prof["id"], score=score):
                    self.assertEqual(
                        _determine_tier(score, prof["tiers"]),
                        expected_tier,
                    )


class LegacyProfileValidateTests(unittest.TestCase):
    """Verifie que validate_quality_profile accepte les profils legacy."""

    def test_validate_quality_profile_accepts_legacy_tiers(self):
        for prof_data in LEGACY_PROFILES:
            with self.subTest(profile=prof_data["id"]):
                raw = {"id": prof_data["id"], "version": 1, "tiers": prof_data["tiers"]}
                ok, errs, normalized = validate_quality_profile(raw)
                self.assertTrue(ok, f"Profil {prof_data['id']} rejete: {errs}")
                # Les cles canoniques sont presentes
                self.assertIn("platinum", normalized["tiers"])
                # Les cles legacy ont ete supprimees
                self.assertNotIn("premium", normalized["tiers"])
                self.assertNotIn("bon", normalized["tiers"])
                self.assertNotIn("moyen", normalized["tiers"])


class LegacyProfileTierOrdinalTests(unittest.TestCase):
    """Verifie que tier_ordinal accepte les anciens noms (Premium...)."""

    def test_tier_ordinal_legacy_premium_yields_platinum_rank(self):
        # Avant le refactor, calibration.tier_ordinal acceptait deja ces alias.
        # On verifie la non-regression.
        self.assertEqual(tier_ordinal("Premium"), tier_ordinal("Platinum"))
        self.assertEqual(tier_ordinal("Bon"), tier_ordinal("Gold"))
        self.assertEqual(tier_ordinal("Moyen"), tier_ordinal("Silver"))
        self.assertEqual(tier_ordinal("Faible"), tier_ordinal("Bronze"))
        self.assertEqual(tier_ordinal("Mauvais"), tier_ordinal("Reject"))


class CalibrationModuleStillWorksTests(unittest.TestCase):
    """calibration.tier_ordinal doit toujours exister apres dedup (re-export)."""

    def test_calibration_tier_ordinal_still_importable(self):
        from cinesort.domain.calibration import tier_ordinal as calib_tier_ordinal

        # Meme fonction (re-export)
        self.assertEqual(calib_tier_ordinal("Platinum"), 4)
        self.assertEqual(calib_tier_ordinal("Premium"), 4)
        self.assertEqual(calib_tier_ordinal("???"), -1)


if __name__ == "__main__":
    unittest.main()
