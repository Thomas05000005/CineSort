"""VP-B (Vague P) : tests unitaires de la hierarchie qualite multi-axes.

Verifie les planchers (floors) et plafonds (ceilings) par dimension :
- resolution (probe vs name_fallback)
- video_codec (AV1/HEVC...)
- HDR (DV/HDR10+/HDR10)
- audio (TrueHD Atmos / DTS-HD MA...)
- release_group

AC-1 : default OFF -> no-op strict.
AC-2 : preserve l'autorite finale de cap_tier (securite FAILED/CAM) - delegue
        au caller, mais on verifie que apply_tier_hierarchy ne fait jamais
        remonter un tier au-dessus du floor le plus haut applicable.
"""

from __future__ import annotations

import unittest

from cinesort.domain.tiers_helpers import (
    DEFAULT_HIERARCHY_DIMENSIONS_ORDER,
    apply_tier_hierarchy,
    default_hierarchy_config,
    normalize_hierarchy_config,
)


class HierarchyDefaultOffTests(unittest.TestCase):
    """AC-1 : default OFF garantit un no-op strict (zero modification tier)."""

    def test_default_config_is_disabled(self):
        cfg = default_hierarchy_config()
        self.assertFalse(cfg["enabled"])

    def test_none_config_acts_as_disabled(self):
        tier, applied = apply_tier_hierarchy("Bronze", {"resolution_label": "2160p"}, None)
        self.assertEqual(tier, "Bronze")
        self.assertEqual(applied, [])

    def test_empty_config_acts_as_disabled(self):
        tier, applied = apply_tier_hierarchy("Bronze", {"resolution_label": "2160p"}, {})
        self.assertEqual(tier, "Bronze")
        self.assertEqual(applied, [])

    def test_explicit_enabled_false_no_op(self):
        cfg = default_hierarchy_config()
        cfg["enabled"] = False
        tier, applied = apply_tier_hierarchy(
            "Bronze",
            {
                "resolution_label": "2160p",
                "resolution_source": "probe",
                "hdr": "dolby_vision",
                "audio_codec": "truehd_atmos",
            },
            cfg,
        )
        # Avec TOUTES les dimensions premium, OFF doit donner Bronze inchange.
        self.assertEqual(tier, "Bronze")
        self.assertEqual(applied, [])


class HierarchyResolutionFloorTests(unittest.TestCase):
    """Floor resolution : 2160p_probe -> Gold."""

    def _enabled_cfg(self):
        cfg = default_hierarchy_config()
        cfg["enabled"] = True
        return cfg

    def test_2160p_probe_floors_bronze_to_gold(self):
        cfg = self._enabled_cfg()
        tier, applied = apply_tier_hierarchy(
            "Bronze",
            {"resolution_label": "2160p", "resolution_source": "probe"},
            cfg,
        )
        self.assertEqual(tier, "Gold")
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["dimension"], "resolution")
        self.assertEqual(applied[0]["type"], "floor")
        self.assertEqual(applied[0]["from"], "Bronze")
        self.assertEqual(applied[0]["to"], "Gold")

    def test_2160p_name_fallback_no_floor_by_default(self):
        """Resolution declarative (name_fallback) ne declenche PAS le floor probe."""
        cfg = self._enabled_cfg()
        tier, applied = apply_tier_hierarchy(
            "Bronze",
            {"resolution_label": "2160p", "resolution_source": "name_fallback"},
            cfg,
        )
        self.assertEqual(tier, "Bronze")
        self.assertEqual(applied, [])

    def test_2160p_probe_does_not_lower_platinum(self):
        """Floor Gold ne fait PAS descendre un Platinum."""
        cfg = self._enabled_cfg()
        tier, _ = apply_tier_hierarchy(
            "Platinum",
            {"resolution_label": "2160p", "resolution_source": "probe"},
            cfg,
        )
        self.assertEqual(tier, "Platinum")

    def test_720p_ceiling_caps_platinum_to_silver(self):
        cfg = self._enabled_cfg()
        tier, applied = apply_tier_hierarchy(
            "Platinum",
            {"resolution_label": "720p"},
            cfg,
        )
        self.assertEqual(tier, "Silver")
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["type"], "ceiling")

    def test_sd_ceiling_caps_gold_to_bronze(self):
        cfg = self._enabled_cfg()
        tier, _ = apply_tier_hierarchy(
            "Gold",
            {"resolution_label": "SD"},
            cfg,
        )
        self.assertEqual(tier, "Bronze")


class HierarchyHdrFloorTests(unittest.TestCase):
    def _enabled_cfg(self):
        cfg = default_hierarchy_config()
        cfg["enabled"] = True
        return cfg

    def test_dolby_vision_floors_bronze_to_gold(self):
        cfg = self._enabled_cfg()
        tier, applied = apply_tier_hierarchy(
            "Bronze",
            {"resolution_label": "1080p", "resolution_source": "probe", "hdr": "dolby_vision"},
            cfg,
        )
        self.assertEqual(tier, "Gold")
        # On verifie qu'au moins une decision HDR est presente.
        hdr_decisions = [d for d in applied if d["dimension"] == "hdr"]
        self.assertEqual(len(hdr_decisions), 1)
        self.assertEqual(hdr_decisions[0]["value"], "dolby_vision")

    def test_hdr10_plus_floors_bronze_to_silver(self):
        cfg = self._enabled_cfg()
        tier, applied = apply_tier_hierarchy(
            "Bronze",
            {"resolution_label": "1080p", "resolution_source": "probe", "hdr": "hdr10_plus"},
            cfg,
        )
        self.assertEqual(tier, "Silver")

    def test_hdr10_no_default_floor(self):
        """HDR10 simple ne declenche PAS de floor par defaut."""
        cfg = self._enabled_cfg()
        tier, applied = apply_tier_hierarchy(
            "Bronze",
            {"resolution_label": "1080p", "resolution_source": "probe", "hdr": "hdr10"},
            cfg,
        )
        self.assertEqual(tier, "Bronze")
        hdr_decisions = [d for d in applied if d["dimension"] == "hdr"]
        self.assertEqual(hdr_decisions, [])


class HierarchyAudioFloorTests(unittest.TestCase):
    def test_truehd_atmos_floors_bronze_to_gold(self):
        cfg = default_hierarchy_config()
        cfg["enabled"] = True
        tier, applied = apply_tier_hierarchy(
            "Bronze",
            {"audio_codec": "truehd_atmos"},
            cfg,
        )
        self.assertEqual(tier, "Gold")
        audio_decisions = [d for d in applied if d["dimension"] == "audio"]
        self.assertEqual(len(audio_decisions), 1)

    def test_dts_no_default_floor(self):
        cfg = default_hierarchy_config()
        cfg["enabled"] = True
        tier, _ = apply_tier_hierarchy("Bronze", {"audio_codec": "dts"}, cfg)
        self.assertEqual(tier, "Bronze")


class HierarchyOrderTests(unittest.TestCase):
    """Verifie que l'ordre des dimensions impacte le resultat final.

    Quand plusieurs dimensions appliquent des floors, le tier MONTE au plus
    haut (jamais en arriere). L'ordre influence cependant l'audit trail.
    """

    def test_default_order_contains_all_dimensions(self):
        order = DEFAULT_HIERARCHY_DIMENSIONS_ORDER
        self.assertEqual(
            set(order),
            {"resolution", "video_codec", "hdr", "audio", "release_group"},
        )

    def test_resolution_first_in_default_order(self):
        self.assertEqual(DEFAULT_HIERARCHY_DIMENSIONS_ORDER[0], "resolution")

    def test_multiple_floors_apply_in_order(self):
        cfg = default_hierarchy_config()
        cfg["enabled"] = True
        tier, applied = apply_tier_hierarchy(
            "Reject",
            {
                "resolution_label": "2160p",
                "resolution_source": "probe",
                "hdr": "dolby_vision",
                "audio_codec": "truehd_atmos",
            },
            cfg,
        )
        # Tous les floors sont Gold -> tier final = Gold (pas Platinum, le
        # default ne prevoit pas de Platinum floor automatique).
        self.assertEqual(tier, "Gold")
        # Premier floor declenche : resolution.
        dims_applied = [d["dimension"] for d in applied]
        self.assertEqual(dims_applied[0], "resolution")


class HierarchyCustomOrderTests(unittest.TestCase):
    def test_user_can_reorder_dimensions(self):
        cfg = default_hierarchy_config()
        cfg["enabled"] = True
        cfg["order"] = ["hdr", "resolution"]
        tier, applied = apply_tier_hierarchy(
            "Reject",
            {
                "resolution_label": "2160p",
                "resolution_source": "probe",
                "hdr": "dolby_vision",
            },
            cfg,
        )
        self.assertEqual(tier, "Gold")
        # HDR doit etre la PREMIERE decision (ordre user).
        self.assertEqual(applied[0]["dimension"], "hdr")

    def test_unknown_dimension_in_order_is_filtered(self):
        cfg = default_hierarchy_config()
        cfg["enabled"] = True
        cfg["order"] = ["resolution", "fake_dimension"]
        # Ne doit pas lever.
        tier, _ = apply_tier_hierarchy(
            "Bronze",
            {"resolution_label": "2160p", "resolution_source": "probe"},
            cfg,
        )
        self.assertEqual(tier, "Gold")


class HierarchyNormalizationTests(unittest.TestCase):
    def test_normalize_legacy_tier_in_floor(self):
        """User peut ecrire 'Premium' dans le profil -> normalise en 'Platinum'."""
        cfg = default_hierarchy_config()
        cfg["enabled"] = True
        cfg["resolution_floors"]["2160p_probe"] = "Premium"
        normalized = normalize_hierarchy_config(cfg)
        self.assertEqual(normalized["resolution_floors"]["2160p_probe"], "Platinum")

    def test_invalid_tier_in_floor_is_dropped(self):
        cfg = default_hierarchy_config()
        cfg["enabled"] = True
        normalized = normalize_hierarchy_config({"enabled": True, "resolution_floors": {"2160p_probe": "WTF_TIER"}})
        # Invalide -> retombe sur defaut TRaSH 2026 (Gold).
        self.assertEqual(normalized["resolution_floors"]["2160p_probe"], "Gold")

    def test_legacy_premium_tier_input(self):
        """Le tier d'entree legacy (Premium/Bon/Moyen) est normalise."""
        cfg = default_hierarchy_config()
        cfg["enabled"] = True
        tier, _ = apply_tier_hierarchy(
            "Premium",
            {"resolution_label": "720p"},  # ceiling Silver
            cfg,
        )
        self.assertEqual(tier, "Silver")

    def test_str_enabled_yes_normalized(self):
        cfg = normalize_hierarchy_config({"enabled": "yes"})
        self.assertTrue(cfg["enabled"])

    def test_str_enabled_no_normalized(self):
        cfg = normalize_hierarchy_config({"enabled": "no"})
        self.assertFalse(cfg["enabled"])


class HierarchyUnknownTierTests(unittest.TestCase):
    def test_unknown_input_tier_returns_as_is(self):
        cfg = default_hierarchy_config()
        cfg["enabled"] = True
        tier, applied = apply_tier_hierarchy(
            "Unknown",
            {"resolution_label": "2160p", "resolution_source": "probe"},
            cfg,
        )
        # Tier inconnu : pas de modification (safe default).
        self.assertEqual(tier, "Unknown")
        self.assertEqual(applied, [])


if __name__ == "__main__":
    unittest.main()
