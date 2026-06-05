"""VP-B (Vague P) : tests migration profil legacy -> tier_hierarchy.

Verifie qu'un profil sauvegarde PRE-VP-B (sans la cle ``tier_hierarchy``)
est correctement normalise lors de la relecture via
``validate_quality_profile`` :

- AC-1 : default OFF -> aucun risque de redistribution silencieuse.
- Backward compat ABSOLUE : tous les anciens profils (1.5.x, 7.x) doivent
  continuer a fonctionner sans modification user.

NOTE : VP-B n'introduit PAS de migration SQL (profile_json suffit selon le
brief ROADMAP). Ces tests ne touchent donc pas SQLite - ils verifient le
contrat de normalisation in-memory au niveau du module domain.
"""

from __future__ import annotations

import copy
import unittest

from cinesort.domain.quality_score import (
    default_quality_profile,
    validate_quality_profile,
)
from cinesort.domain.tiers_helpers import (
    DEFAULT_HIERARCHY_DIMENSIONS_ORDER,
    default_hierarchy_config,
    normalize_hierarchy_config,
)

# Profil V1.5.7 typique (sauvegarde avant VP-B), pre-hierarchy.
_LEGACY_PROFILE_V157 = {
    "id": "CinemaLux_Legacy_v1",
    "version": 1,
    "engine_version": "CinemaLux_v1",
    "weights": {"video": 60, "audio": 30, "extras": 10},
    "toggles": {
        "include_metadata": False,
        "include_naming": False,
        "enable_4k_light": True,
    },
    "video_thresholds": {
        "bitrate_min_kbps_2160p": 18000,
        "bitrate_min_kbps_1080p": 8000,
        "penalty_low_bitrate": 14,
        "penalty_4k_light": 7,
        "penalty_hdr_8bit": 8,
    },
    "hdr_bonuses": {"dv_bonus": 12, "hdr10p_bonus": 10, "hdr10_bonus": 8},
    "codec_bonuses": {"hevc_bonus": 8, "av1_bonus": 9, "avc_bonus": 5},
    "audio_bonuses": {
        "truehd_atmos_bonus": 12,
        "dts_hd_ma_bonus": 10,
        "dts_bonus": 6,
        "aac_bonus": 3,
        "channels_bonus_map": {"2.0": 2, "5.1": 6, "7.1": 8},
    },
    "languages": {"bonus_vo_present": 4, "bonus_vf_present": 2},
    "tiers": {"platinum": 70, "gold": 66, "silver": 55, "bronze": 40},
    # Pas de cle "tier_hierarchy" - profil pre-VP-B.
}


class LegacyProfileMigrationTests(unittest.TestCase):
    """Profils legacy sans cle tier_hierarchy : default OFF applique."""

    def test_legacy_profile_validates_with_default_hierarchy_off(self):
        ok, errs, profile = validate_quality_profile(_LEGACY_PROFILE_V157)
        self.assertTrue(ok, f"errs={errs}")
        self.assertIn("tier_hierarchy", profile)
        self.assertFalse(profile["tier_hierarchy"]["enabled"],
                         "Default OFF requis pour backward compat ABSOLUE")

    def test_legacy_profile_gets_default_dimensions_order(self):
        _, _, profile = validate_quality_profile(_LEGACY_PROFILE_V157)
        self.assertEqual(
            profile["tier_hierarchy"]["order"],
            list(DEFAULT_HIERARCHY_DIMENSIONS_ORDER),
        )

    def test_legacy_profile_gets_trash_2026_floors(self):
        """Le profil legacy doit avoir les defaults TRaSH 2026 (mais OFF)."""
        _, _, profile = validate_quality_profile(_LEGACY_PROFILE_V157)
        hierarchy = profile["tier_hierarchy"]
        # Floor resolution 2160p_probe -> Gold (default TRaSH).
        self.assertEqual(hierarchy["resolution_floors"]["2160p_probe"], "Gold")
        # Ceiling 720p -> Silver (default TRaSH).
        self.assertEqual(hierarchy["resolution_ceilings"]["720p"], "Silver")


class PartialHierarchyConfigTests(unittest.TestCase):
    """Profils avec tier_hierarchy partiel : merge defaults pour cles manquantes."""

    def test_only_enabled_true_uses_default_order_and_floors(self):
        prof_in = copy.deepcopy(_LEGACY_PROFILE_V157)
        prof_in["tier_hierarchy"] = {"enabled": True}
        ok, errs, profile = validate_quality_profile(prof_in)
        self.assertTrue(ok, f"errs={errs}")
        hierarchy = profile["tier_hierarchy"]
        self.assertTrue(hierarchy["enabled"])
        self.assertEqual(hierarchy["order"], list(DEFAULT_HIERARCHY_DIMENSIONS_ORDER))
        # Floors par defaut TRaSH 2026 conserves.
        self.assertEqual(hierarchy["resolution_floors"]["2160p_probe"], "Gold")

    def test_user_floors_merge_with_defaults(self):
        """User peut surcharger un floor specifique sans perdre les autres."""
        prof_in = copy.deepcopy(_LEGACY_PROFILE_V157)
        prof_in["tier_hierarchy"] = {
            "enabled": True,
            "resolution_floors": {"1080p": "Silver"},  # ajout user
        }
        _, _, profile = validate_quality_profile(prof_in)
        hierarchy = profile["tier_hierarchy"]
        # Default conserve.
        self.assertEqual(hierarchy["resolution_floors"]["2160p_probe"], "Gold")
        # User-defined applique.
        self.assertEqual(hierarchy["resolution_floors"]["1080p"], "Silver")

    def test_user_can_disable_after_first_save(self):
        prof_in = copy.deepcopy(_LEGACY_PROFILE_V157)
        prof_in["tier_hierarchy"] = {"enabled": False, "order": ["audio", "resolution"]}
        _, _, profile = validate_quality_profile(prof_in)
        hierarchy = profile["tier_hierarchy"]
        self.assertFalse(hierarchy["enabled"])
        # L'ordre user est preserve meme si OFF (pour repris si user reactivate).
        self.assertEqual(hierarchy["order"], ["audio", "resolution"])


class InvalidHierarchyConfigTolerantTests(unittest.TestCase):
    """Un tier_hierarchy invalide ne casse PAS la validation (fallback default)."""

    def test_non_dict_tier_hierarchy_falls_back_to_default(self):
        prof_in = copy.deepcopy(_LEGACY_PROFILE_V157)
        prof_in["tier_hierarchy"] = "not a dict"
        ok, errs, profile = validate_quality_profile(prof_in)
        self.assertTrue(ok, f"errs={errs}")
        self.assertFalse(profile["tier_hierarchy"]["enabled"])

    def test_invalid_enabled_value_is_disabled(self):
        prof_in = copy.deepcopy(_LEGACY_PROFILE_V157)
        prof_in["tier_hierarchy"] = {"enabled": "n/a"}
        _, _, profile = validate_quality_profile(prof_in)
        self.assertFalse(profile["tier_hierarchy"]["enabled"])

    def test_invalid_tier_in_floor_uses_default(self):
        prof_in = copy.deepcopy(_LEGACY_PROFILE_V157)
        prof_in["tier_hierarchy"] = {
            "enabled": True,
            "resolution_floors": {"2160p_probe": "MEGAPLAT"},  # tier inconnu
        }
        _, _, profile = validate_quality_profile(prof_in)
        # Le tier inconnu doit etre drop -> revient au default TRaSH (Gold).
        self.assertEqual(
            profile["tier_hierarchy"]["resolution_floors"]["2160p_probe"], "Gold",
        )


class DefaultProfileHasHierarchyDisabledTests(unittest.TestCase):
    """``default_quality_profile`` expose tier_hierarchy DESACTIVE par defaut."""

    def test_default_profile_includes_tier_hierarchy(self):
        prof = default_quality_profile()
        self.assertIn("tier_hierarchy", prof)

    def test_default_profile_hierarchy_is_disabled(self):
        prof = default_quality_profile()
        self.assertFalse(prof["tier_hierarchy"]["enabled"])

    def test_default_hierarchy_matches_helper(self):
        """default_quality_profile et default_hierarchy_config doivent etre coherents."""
        prof = default_quality_profile()
        helper = default_hierarchy_config()
        self.assertEqual(prof["tier_hierarchy"]["enabled"], helper["enabled"])
        self.assertEqual(prof["tier_hierarchy"]["order"], helper["order"])


class NormalizeHierarchyConfigStandaloneTests(unittest.TestCase):
    """Tests directs du helper normalize_hierarchy_config (couche domain pure)."""

    def test_none_returns_default(self):
        cfg = normalize_hierarchy_config(None)
        self.assertEqual(cfg, default_hierarchy_config())

    def test_empty_dict_returns_default(self):
        cfg = normalize_hierarchy_config({})
        self.assertEqual(cfg, default_hierarchy_config())

    def test_legacy_premium_tier_in_floor_normalized(self):
        cfg = normalize_hierarchy_config({
            "enabled": True,
            "resolution_floors": {"2160p_probe": "Premium"},
        })
        self.assertEqual(cfg["resolution_floors"]["2160p_probe"], "Platinum")

    def test_fr_long_label_in_floor_normalized(self):
        cfg = normalize_hierarchy_config({
            "enabled": True,
            "resolution_floors": {"2160p_probe": "Platine"},
        })
        self.assertEqual(cfg["resolution_floors"]["2160p_probe"], "Platinum")


if __name__ == "__main__":
    unittest.main()
