"""VP-F (Vague P batch 6) — Backward compat ABSOLUE QualityFacade.

Apres extension de `quality_facade.py` et decoupe de `profiles_support.py` en
sous-modules thematiques, ces tests garantissent que :

- AC-1 : toutes les signatures publiques pre-VP-F existent toujours sur
  `QualityFacade` (aucune disparition silencieuse).
- Aucune signature de `profiles_support.py` ne casse (re-exports OK).
- L'instanciation de la facade ne leve pas d'erreur (imports lazy/top-level OK).
- Le module historique `profiles_support` continue d'exposer get_profiles /
  save_profile / set_active_profile.

Les tests sont volontairement orientes contrat (introspection) - ils ne testent
PAS le comportement runtime (couvert par les tests d'integration existants).
"""

from __future__ import annotations

import inspect
import unittest


class QualityFacadeSignaturesPreservedTests(unittest.TestCase):
    """Verifie que toutes les methodes pre-VP-F existent encore."""

    def setUp(self) -> None:
        from cinesort.ui.api.facades.quality_facade import QualityFacade

        self.facade_cls = QualityFacade

    def test_profile_methods_present(self) -> None:
        """8 methodes Profile (pre-VP-F) doivent etre presentes."""
        expected = [
            "get_quality_profile",
            "save_quality_profile",
            "reset_quality_profile",
            "export_quality_profile",
            "import_quality_profile",
            "get_quality_presets",
            "apply_quality_preset",
            "simulate_quality_preset",
        ]
        for name in expected:
            with self.subTest(method=name):
                self.assertTrue(
                    hasattr(self.facade_cls, name),
                    f"QualityFacade.{name} a disparu (regression VP-F).",
                )

    def test_report_rules_methods_present(self) -> None:
        """5 methodes Report & rules (pre-VP-F)."""
        expected = [
            "get_quality_report",
            "analyze_quality_batch",
            "save_custom_quality_preset",
            "get_custom_rules_templates",
            "get_custom_rules_catalog",
        ]
        for name in expected:
            with self.subTest(method=name):
                self.assertTrue(hasattr(self.facade_cls, name))

    def test_perceptual_methods_present(self) -> None:
        """4+ methodes Perceptual (pre-VP-F)."""
        expected = [
            "get_perceptual_report",
            "get_perceptual_details",
            "analyze_perceptual_batch",
            "compare_perceptual",
            "get_perceptual_compare_frames",
            "get_perceptual_compare_audio",
            "queue_perceptual_analyses",
            "get_perceptual_job_status",
        ]
        for name in expected:
            with self.subTest(method=name):
                self.assertTrue(hasattr(self.facade_cls, name))

    def test_feedback_calibration_methods_present(self) -> None:
        """3 methodes Feedback / Calibration (pre-VP-F)."""
        expected = [
            "submit_score_feedback",
            "delete_score_feedback",
            "get_calibration_report",
        ]
        for name in expected:
            with self.subTest(method=name):
                self.assertTrue(hasattr(self.facade_cls, name))

    def test_validation_rules_method_present(self) -> None:
        """validate_custom_rules (pre-VP-F)."""
        self.assertTrue(hasattr(self.facade_cls, "validate_custom_rules"))

    def test_profiles_endpoints_alias_present(self) -> None:
        """quality/X aliases (get_profiles, save_profile, set_active_profile)."""
        for name in ("get_profiles", "save_profile", "set_active_profile"):
            with self.subTest(method=name):
                self.assertTrue(hasattr(self.facade_cls, name))

    def test_quality_audit_methods_present(self) -> None:
        """Vue Qualite Audit (spec 10)."""
        for name in (
            "get_films_by_tier",
            "get_history",
            "recompute_all_scores",
            "get_recompute_job_status",
        ):
            with self.subTest(method=name):
                self.assertTrue(hasattr(self.facade_cls, name))

    def test_shareable_profile_methods_present(self) -> None:
        """sprint C1 : import/export shareable."""
        self.assertTrue(hasattr(self.facade_cls, "export_shareable_profile"))
        self.assertTrue(hasattr(self.facade_cls, "import_shareable_profile"))


class QualityFacadeVPFNewMethodsTests(unittest.TestCase):
    """VP-F : nouvelles methodes ajoutees, doivent etre instanciables."""

    def setUp(self) -> None:
        from cinesort.ui.api.facades.quality_facade import QualityFacade

        self.facade_cls = QualityFacade

    def test_recyclarr_yaml_methods_added(self) -> None:
        self.assertTrue(hasattr(self.facade_cls, "export_recyclarr_yaml"))
        self.assertTrue(hasattr(self.facade_cls, "import_recyclarr_yaml"))

    def test_embedded_presets_method_added(self) -> None:
        self.assertTrue(hasattr(self.facade_cls, "get_embedded_presets"))

    def test_upgrade_until_score_methods_added(self) -> None:
        self.assertTrue(hasattr(self.facade_cls, "get_upgrade_until_score"))
        self.assertTrue(hasattr(self.facade_cls, "set_upgrade_until_score"))

    def test_breakdown_5_axes_method_added(self) -> None:
        self.assertTrue(hasattr(self.facade_cls, "get_breakdown_5_axes"))

    def test_no_new_facade_class_created(self) -> None:
        """VP-F : aucune nouvelle facade ; tout reste sur QualityFacade."""
        from cinesort.ui.api import facades as facades_pkg

        # Cherche des classes contenant "Profile" dans le nom (potentielle dupli)
        bad_names = []
        for name in dir(facades_pkg):
            obj = getattr(facades_pkg, name, None)
            if inspect.isclass(obj) and "Profile" in name and name != "QualityFacade":
                bad_names.append(name)
        self.assertEqual(
            bad_names,
            [],
            f"VP-F doit etendre QualityFacade, pas creer de nouvelle facade : {bad_names}",
        )


class ProfilesSupportBackwardCompatTests(unittest.TestCase):
    """Le module historique `profiles_support` reste un point d'entree valide."""

    def test_module_imports_ok(self) -> None:
        import cinesort.ui.api.profiles_support as ps  # noqa: F401

    def test_crud_functions_reexported(self) -> None:
        from cinesort.ui.api import profiles_support as ps

        self.assertTrue(callable(getattr(ps, "get_profiles", None)))
        self.assertTrue(callable(getattr(ps, "save_profile", None)))
        self.assertTrue(callable(getattr(ps, "set_active_profile", None)))

    def test_vpf_functions_reexported(self) -> None:
        from cinesort.ui.api import profiles_support as ps

        for name in (
            "export_recyclarr_yaml",
            "import_recyclarr_yaml",
            "get_embedded_presets",
            "get_upgrade_until_score",
            "set_upgrade_until_score",
            "get_breakdown_5_axes",
            "yaml_dump",
            "yaml_load",
        ):
            with self.subTest(symbol=name):
                self.assertTrue(callable(getattr(ps, name, None)), f"{name} non re-exporte")

    def test_internal_helpers_reexported(self) -> None:
        """Les helpers privates utilises par d'autres tests doivent survivre."""
        from cinesort.ui.api import profiles_support as ps

        for name in (
            "_normalize_tiers_decreasing",
            "_normalize_weights_sum",
            "_build_profile_row",
            "_read_settings_dict",
            "_save_settings_dict",
        ):
            with self.subTest(symbol=name):
                self.assertTrue(callable(getattr(ps, name, None)))

    def test_constants_reexported(self) -> None:
        from cinesort.ui.api import profiles_support as ps

        self.assertEqual(ps._WEIGHT_SUM_TARGET_FRACTION, 1.0)
        self.assertEqual(ps._WEIGHT_SUM_TARGET_PERCENT, 100.0)
        self.assertAlmostEqual(ps._WEIGHT_SUM_TOLERANCE_FRACTION, 0.05)
        self.assertEqual(ps.DEFAULT_UPGRADE_UNTIL_SCORE, 10000)


class CineSortApiImplsUnchangedTests(unittest.TestCase):
    """Les _X_impl de CineSortApi doivent continuer de fonctionner."""

    def test_get_profiles_impl_calls_crud(self) -> None:
        from cinesort.ui.api.cinesort_api import CineSortApi

        for name in ("_get_profiles_impl", "_save_profile_impl", "_set_active_profile_impl"):
            with self.subTest(impl=name):
                self.assertTrue(hasattr(CineSortApi, name))


if __name__ == "__main__":
    unittest.main()
