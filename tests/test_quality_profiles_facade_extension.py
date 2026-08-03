"""VP-F (Vague P batch 6) — QualityFacade extension (pas nouvelle facade).

AC-1 : `quality_facade.py` etendue avec :
- export_recyclarr_yaml / import_recyclarr_yaml (Recyclarr round-trip)
- get_embedded_presets (TRaSH 2026 + alternatifs, DESACTIVES par defaut)
- get_upgrade_until_score / set_upgrade_until_score (default 10000)
- get_breakdown_5_axes (Source / Codec / HDR / Audio / Group)

Ces tests ciblent la facade (et non le module support directement) pour
verifier que l'extension est bien plumbed et que le _BaseFacade.__init__
fonctionne correctement.

AC-3 : preset TRaSH 2026 embarque mais DESACTIVE par defaut.
AC-4 : breakdown 5 axes structure pour UI.
AC-5 : upgrade_until_score exposable via UI (default 10000).
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from cinesort.domain.quality_score import default_quality_profile
from cinesort.ui.api.facades.quality_facade import QualityFacade


def _make_stub_api(profile: dict | None = None) -> MagicMock:
    """Construit un stub CineSortApi pour tester la facade sans DB."""
    p = profile or default_quality_profile()
    api = MagicMock()
    api._active_quality_profile_payload.return_value = {
        "profile_id": p.get("id", "default_v1"),
        "profile_version": 1,
        "profile_json": p,
    }
    settings_facade = MagicMock()
    settings_facade.get_settings.return_value = {
        "custom_quality_profiles": [],
        "active_quality_profile_id": "",
    }
    settings_facade.save_settings.return_value = {"ok": True}
    api.settings = settings_facade
    api._save_active_quality_profile = MagicMock()
    return api


class FacadeIsExtendedNotDuplicatedTests(unittest.TestCase):
    """AC-1 : QualityFacade etendue (pas nouvelle facade)."""

    def test_facade_class_exists(self) -> None:
        self.assertTrue(hasattr(QualityFacade, "__init__"))

    def test_facade_can_be_instantiated_with_stub(self) -> None:
        facade = QualityFacade(_make_stub_api())
        self.assertIsNotNone(facade)

    def test_vpf_methods_callable(self) -> None:
        facade = QualityFacade(_make_stub_api())
        # Tous callables.
        self.assertTrue(callable(facade.export_recyclarr_yaml))
        self.assertTrue(callable(facade.import_recyclarr_yaml))
        self.assertTrue(callable(facade.get_embedded_presets))
        self.assertTrue(callable(facade.get_upgrade_until_score))
        self.assertTrue(callable(facade.set_upgrade_until_score))
        self.assertTrue(callable(facade.get_breakdown_5_axes))


class EmbeddedPresetsTests(unittest.TestCase):
    """AC-3 : TRaSH 2026 + alternatifs, DESACTIVES par defaut."""

    def test_get_embedded_presets_returns_ok(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.get_embedded_presets()
        self.assertTrue(res.get("ok"))
        self.assertIn("presets", res)

    def test_trash_preset_disabled_by_default(self) -> None:
        """AC-3 : preset principal TRaSH 2026 DOIT etre enabled_by_default=False."""
        facade = QualityFacade(_make_stub_api())
        res = facade.get_embedded_presets()
        presets = res.get("presets", [])
        self.assertGreater(len(presets), 0, "Au moins 1 preset embarque attendu")
        main_preset = next((p for p in presets if p["preset_id"] == "trash_2026"), None)
        self.assertIsNotNone(main_preset, "Preset 'trash_2026' attendu")
        assert main_preset is not None
        self.assertFalse(
            main_preset["enabled_by_default"],
            "AC-3 fix #4 : TRaSH 2026 doit etre DESACTIVE par defaut.",
        )
        # tier_hierarchy.enabled doit etre False egalement.
        self.assertFalse(
            main_preset["tier_hierarchy"].get("enabled", True),
            "tier_hierarchy.enabled doit etre False",
        )

    def test_alternative_presets_present(self) -> None:
        """Presets alternatifs : puriste DV, qualite max audio."""
        facade = QualityFacade(_make_stub_api())
        res = facade.get_embedded_presets()
        preset_ids = {p["preset_id"] for p in res.get("presets", [])}
        self.assertIn("puriste_dv", preset_ids)
        self.assertIn("qualite_max_audio", preset_ids)

    def test_all_embedded_presets_disabled(self) -> None:
        """AC-3 : TOUS les presets embarques sont OFF par defaut."""
        facade = QualityFacade(_make_stub_api())
        res = facade.get_embedded_presets()
        for preset in res.get("presets", []):
            with self.subTest(preset_id=preset["preset_id"]):
                self.assertFalse(
                    preset["enabled_by_default"],
                    f"Preset {preset['preset_id']} doit etre OFF par defaut.",
                )


class UpgradeUntilScoreTests(unittest.TestCase):
    """AC-5 : default 10000, expose via UI."""

    def test_get_default_returns_10000(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.get_upgrade_until_score()
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("upgrade_until_score"), 10000)

    def test_get_custom_value_preserved(self) -> None:
        profile = default_quality_profile()
        profile["upgrade_until_score"] = 7777
        facade = QualityFacade(_make_stub_api(profile))
        res = facade.get_upgrade_until_score()
        self.assertEqual(res.get("upgrade_until_score"), 7777)

    def test_set_valid_score(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.set_upgrade_until_score(5500)
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res.get("upgrade_until_score"), 5500)

    def test_set_negative_rejected(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.set_upgrade_until_score(-1)
        self.assertFalse(res.get("ok"))

    def test_set_out_of_bounds_rejected(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.set_upgrade_until_score(999999)
        self.assertFalse(res.get("ok"))

    def test_set_non_int_rejected(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.set_upgrade_until_score("not a number")
        self.assertFalse(res.get("ok"))


class Breakdown5AxesTests(unittest.TestCase):
    """AC-4 : breakdown 5 axes (Source / Codec / HDR / Audio / Group)."""

    def test_breakdown_returns_5_axes(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.get_breakdown_5_axes()
        self.assertTrue(res.get("ok"))
        axes = res.get("axes", [])
        self.assertEqual(len(axes), 5, "5 axes attendus")

    def test_breakdown_axes_ids(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.get_breakdown_5_axes()
        ids = [a["id"] for a in res.get("axes", [])]
        self.assertEqual(ids, ["source", "codec", "hdr", "audio", "group"])

    def test_breakdown_each_axis_has_required_fields(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.get_breakdown_5_axes()
        for axis in res.get("axes", []):
            with self.subTest(axis=axis["id"]):
                self.assertIn("label", axis)
                self.assertIn("weight", axis)
                self.assertIn("details", axis)
                self.assertIsInstance(axis["details"], dict)

    def test_breakdown_includes_upgrade_until_score(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.get_breakdown_5_axes()
        self.assertEqual(res.get("upgrade_until_score"), 10000)


class RecyclarrIntegrationTests(unittest.TestCase):
    """AC-2 : import/export round-trip via la facade."""

    def test_export_returns_yaml(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.export_recyclarr_yaml()
        self.assertTrue(res.get("ok"))
        self.assertIn("quality_profiles", res["yaml"])

    def test_export_specific_preset_id(self) -> None:
        facade = QualityFacade(_make_stub_api())
        # Preset existant.
        res = facade.export_recyclarr_yaml(profile_id="equilibre")
        self.assertTrue(res.get("ok"))

    def test_export_unknown_id_returns_error(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.export_recyclarr_yaml(profile_id="not_a_real_profile_xxx")
        self.assertFalse(res.get("ok"))

    def test_facade_import_invalid_payload_returns_error(self) -> None:
        facade = QualityFacade(_make_stub_api())
        res = facade.import_recyclarr_yaml("")
        self.assertFalse(res.get("ok"))


if __name__ == "__main__":
    unittest.main()
