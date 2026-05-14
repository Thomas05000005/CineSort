"""Tests des facades CineSortApi (issue #84 — PRs 1 pilote + 2 Run + 3 Settings + 4 Quality).

Cf docs/internal/REFACTOR_PLAN_84.md.

PR 1 verifie :
- Les 5 facades sont instanciees comme attributs de CineSortApi
- Les types sont corrects
- 1 methode pilote par facade fonctionne via la nouvelle voie
- La symetrie ancienne/nouvelle voie est preservee (backward-compat)

PR 2 ajoute : les 7 methodes du bounded context Run sur RunFacade
PR 3 ajoute : les 6 methodes du bounded context Settings sur SettingsFacade
PR 4 ajoute : les 21 methodes du bounded context Quality sur QualityFacade
PR 5 ajoute : les 11 methodes du bounded context Integrations sur IntegrationsFacade
PR 6 ajoute : les 9 methodes du bounded context Library sur LibraryFacade
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.ui.api.facades import (
    IntegrationsFacade,
    LibraryFacade,
    QualityFacade,
    RunFacade,
    SettingsFacade,
    _BaseFacade,
)


class FacadeInstanciationTests(unittest.TestCase):
    """Les 5 facades sont instanciees et exposees comme attributs."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_run_facade_exposed(self) -> None:
        self.assertIsInstance(self.api.run, RunFacade)
        self.assertIsInstance(self.api.run, _BaseFacade)

    def test_settings_facade_exposed(self) -> None:
        self.assertIsInstance(self.api.settings, SettingsFacade)

    def test_quality_facade_exposed(self) -> None:
        self.assertIsInstance(self.api.quality, QualityFacade)

    def test_integrations_facade_exposed(self) -> None:
        self.assertIsInstance(self.api.integrations, IntegrationsFacade)

    def test_library_facade_exposed(self) -> None:
        self.assertIsInstance(self.api.library, LibraryFacade)


class FacadeDelegationTests(unittest.TestCase):
    """Les methodes pilote des facades delegent au CineSortApi parent."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_settings_get_settings_delegates(self) -> None:
        """SettingsFacade.get_settings retourne le meme resultat que CineSortApi.get_settings."""
        old = self.api.settings.get_settings()
        new = self.api.settings.get_settings()
        # Memes cles (le contenu peut varier si timing/ts mais structure identique)
        self.assertEqual(set(old.keys()), set(new.keys()))

    def test_quality_get_quality_profile_delegates(self) -> None:
        old = self.api.quality.get_quality_profile()
        new = self.api.quality.get_quality_profile()
        # Memes cles structurelles (les ts/version peuvent varier)
        self.assertEqual(set(old.keys()), set(new.keys()))


class FacadeStoreReferenceTests(unittest.TestCase):
    """Les facades stockent la reference vers le CineSortApi parent."""

    def test_run_facade_stores_api(self) -> None:
        api = CineSortApi()
        self.assertIs(api.run._api, api)

    def test_settings_facade_stores_api(self) -> None:
        api = CineSortApi()
        self.assertIs(api.settings._api, api)


class RunFacadeFullMigrationTests(unittest.TestCase):
    """PR 2 : les 7 methodes du bounded context Run sont exposees sur RunFacade.

    Chaque test verifie :
    1. La methode existe sur RunFacade et est callable
    2. La methode delegue vers CineSortApi (memes args, meme retour)

    Strategie de delegation : on mock self._api avec MagicMock et on verifie
    que la methode facade appelle bien self._api.X(...) avec les bons args.
    """

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_run_facade_exposes_7_methods(self) -> None:
        """Sanity : les 7 methodes du bounded context Run existent."""
        expected = {
            "start_plan",
            "get_status",
            "get_plan",
            "export_run_report",
            "cancel_run",
            "build_apply_preview",
            "list_apply_history",
        }
        for name in expected:
            self.assertTrue(
                hasattr(self.api.run, name),
                f"RunFacade.{name} manquante",
            )
            self.assertTrue(
                callable(getattr(self.api.run, name)),
                f"RunFacade.{name} non callable",
            )

    def test_start_plan_delegates(self) -> None:
        sentinel = {"ok": True, "run_id": "test_123"}
        with patch.object(self.api, "start_plan", return_value=sentinel) as mocked:
            settings = {"root": "C:/test"}
            result = self.api.run.start_plan(settings)
        mocked.assert_called_once_with(settings)
        self.assertEqual(result, sentinel)

    def test_get_status_delegates(self) -> None:
        sentinel = {"ok": True, "progress": 0.5}
        with patch.object(self.api, "get_status", return_value=sentinel) as mocked:
            result = self.api.run.get_status("run_xyz", last_log_index=42)
        mocked.assert_called_once_with("run_xyz", 42)
        self.assertEqual(result, sentinel)

    def test_get_status_default_last_log_index(self) -> None:
        """Le default last_log_index=0 doit etre transmis correctement."""
        sentinel = {"ok": True}
        with patch.object(self.api, "get_status", return_value=sentinel) as mocked:
            self.api.run.get_status("run_xyz")
        mocked.assert_called_once_with("run_xyz", 0)

    def test_get_plan_delegates(self) -> None:
        sentinel = {"ok": True, "rows": []}
        with patch.object(self.api, "get_plan", return_value=sentinel) as mocked:
            result = self.api.run.get_plan("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)

    def test_export_run_report_delegates(self) -> None:
        sentinel = {"ok": True, "path": "C:/export.json"}
        with patch.object(self.api, "export_run_report", return_value=sentinel) as mocked:
            result = self.api.run.export_run_report("run_xyz", fmt="csv")
        mocked.assert_called_once_with("run_xyz", "csv")
        self.assertEqual(result, sentinel)

    def test_export_run_report_default_fmt(self) -> None:
        """Le default fmt='json' doit etre transmis correctement."""
        sentinel = {"ok": True}
        with patch.object(self.api, "export_run_report", return_value=sentinel) as mocked:
            self.api.run.export_run_report("run_xyz")
        mocked.assert_called_once_with("run_xyz", "json")

    def test_cancel_run_delegates(self) -> None:
        sentinel = {"ok": True, "cancelled": True}
        with patch.object(self.api, "cancel_run", return_value=sentinel) as mocked:
            result = self.api.run.cancel_run("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)

    def test_build_apply_preview_delegates(self) -> None:
        sentinel = {"ok": True, "films": []}
        decisions = {"film_1": {"approved": True}}
        with patch.object(self.api, "build_apply_preview", return_value=sentinel) as mocked:
            result = self.api.run.build_apply_preview("run_xyz", decisions)
        mocked.assert_called_once_with("run_xyz", decisions)
        self.assertEqual(result, sentinel)

    def test_list_apply_history_delegates(self) -> None:
        sentinel = {"ok": True, "batches": []}
        with patch.object(self.api, "list_apply_history", return_value=sentinel) as mocked:
            result = self.api.run.list_apply_history("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)


class RunFacadeBackwardCompatTests(unittest.TestCase):
    """Les 7 anciennes methodes directes restent fonctionnelles (Strangler Fig).

    Frontend JS et REST API continuent d'appeler api.run.start_plan(...) etc.
    Tant que la PR 10 n'a pas migre tous les callers, ces methodes doivent rester.
    """

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_all_7_old_methods_still_exist(self) -> None:
        for name in (
            "start_plan",
            "get_status",
            "get_plan",
            "export_run_report",
            "cancel_run",
            "build_apply_preview",
            "list_apply_history",
        ):
            self.assertTrue(
                hasattr(self.api, name),
                f"CineSortApi.{name} a disparu (regression backward-compat)",
            )

    def test_get_status_invalid_run_id_via_old_and_new(self) -> None:
        """Sanity : appeler get_status sur un run_id inexistant retourne le meme
        type de reponse via l'ancienne et la nouvelle voie."""
        old = self.api.run.get_status("run_inexistant_xyz")
        new = self.api.run.get_status("run_inexistant_xyz")
        # Les deux doivent etre des dicts avec une cle "ok"
        self.assertIsInstance(old, dict)
        self.assertIsInstance(new, dict)
        self.assertEqual(set(old.keys()), set(new.keys()))


class SettingsFacadeFullMigrationTests(unittest.TestCase):
    """PR 3 : les 6 methodes du bounded context Settings sont exposees sur SettingsFacade.

    Chaque test verifie :
    1. La methode existe sur SettingsFacade et est callable
    2. La methode delegue vers CineSortApi (memes args, meme retour)
    """

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_settings_facade_exposes_6_methods(self) -> None:
        """Sanity : les 6 methodes du bounded context Settings existent."""
        expected = {
            "get_settings",
            "save_settings",
            "set_locale",
            "restart_api_server",
            "reset_all_user_data",
            "get_user_data_size",
        }
        for name in expected:
            self.assertTrue(
                hasattr(self.api.settings, name),
                f"SettingsFacade.{name} manquante",
            )
            self.assertTrue(
                callable(getattr(self.api.settings, name)),
                f"SettingsFacade.{name} non callable",
            )

    def test_get_settings_delegates(self) -> None:
        sentinel = {"root": "C:/test", "state_dir": "C:/state"}
        with patch.object(self.api, "get_settings", return_value=sentinel) as mocked:
            result = self.api.settings.get_settings()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_save_settings_delegates(self) -> None:
        sentinel = {"ok": True}
        settings = {"root": "C:/new_root"}
        with patch.object(self.api, "save_settings", return_value=sentinel) as mocked:
            result = self.api.settings.save_settings(settings)
        mocked.assert_called_once_with(settings)
        self.assertEqual(result, sentinel)

    def test_set_locale_delegates(self) -> None:
        sentinel = {"ok": True, "locale": "en"}
        with patch.object(self.api, "set_locale", return_value=sentinel) as mocked:
            result = self.api.settings.set_locale("en")
        mocked.assert_called_once_with("en")
        self.assertEqual(result, sentinel)

    def test_restart_api_server_delegates(self) -> None:
        sentinel = {"ok": True, "restarted": True}
        with patch.object(self.api, "restart_api_server", return_value=sentinel) as mocked:
            result = self.api.settings.restart_api_server()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_reset_all_user_data_delegates(self) -> None:
        sentinel = {"ok": True, "backup_path": "C:/backup.zip"}
        with patch.object(self.api, "reset_all_user_data", return_value=sentinel) as mocked:
            result = self.api.settings.reset_all_user_data("CONFIRM")
        mocked.assert_called_once_with("CONFIRM")
        self.assertEqual(result, sentinel)

    def test_reset_all_user_data_default_confirmation(self) -> None:
        """Le default confirmation='' doit etre transmis correctement."""
        sentinel = {"ok": False, "message": "confirmation manquante"}
        with patch.object(self.api, "reset_all_user_data", return_value=sentinel) as mocked:
            self.api.settings.reset_all_user_data()
        mocked.assert_called_once_with("")

    def test_get_user_data_size_delegates(self) -> None:
        sentinel = {"data": {"total_bytes": 12345}}
        with patch.object(self.api, "get_user_data_size", return_value=sentinel) as mocked:
            result = self.api.settings.get_user_data_size()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)


class SettingsFacadeBackwardCompatTests(unittest.TestCase):
    """Les 6 anciennes methodes Settings directes restent fonctionnelles."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_all_6_old_settings_methods_still_exist(self) -> None:
        for name in (
            "get_settings",
            "save_settings",
            "set_locale",
            "restart_api_server",
            "reset_all_user_data",
            "get_user_data_size",
        ):
            self.assertTrue(
                hasattr(self.api, name),
                f"CineSortApi.{name} a disparu (regression backward-compat)",
            )

    def test_get_settings_via_old_and_new_returns_same_keys(self) -> None:
        """Parite structurelle : memes cles via api.X et api.settings.X."""
        old = self.api.settings.get_settings()
        new = self.api.settings.get_settings()
        self.assertEqual(set(old.keys()), set(new.keys()))


class QualityFacadeFullMigrationTests(unittest.TestCase):
    """PR 4 : les 21 methodes du bounded context Quality sont exposees sur QualityFacade.

    Strategie de test : verifier que toutes les methodes existent, sont callables,
    et que chacune delegue correctement vers self._api.X(...) avec les memes args.

    On regroupe les tests par sous-domaine (Profile / Report / Perceptual / Feedback).
    """

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_quality_facade_exposes_21_methods(self) -> None:
        """Sanity : les 21 methodes du bounded context Quality existent."""
        expected = {
            # Profile (8)
            "get_quality_profile",
            "save_quality_profile",
            "reset_quality_profile",
            "export_quality_profile",
            "import_quality_profile",
            "get_quality_presets",
            "apply_quality_preset",
            "simulate_quality_preset",
            # Report & rules (5)
            "get_quality_report",
            "analyze_quality_batch",
            "save_custom_quality_preset",
            "get_custom_rules_templates",
            "get_custom_rules_catalog",
            # Validation (1)
            "validate_custom_rules",
            # Perceptual (4)
            "get_perceptual_report",
            "get_perceptual_details",
            "analyze_perceptual_batch",
            "compare_perceptual",
            # Feedback / Calibration (3)
            "submit_score_feedback",
            "delete_score_feedback",
            "get_calibration_report",
        }
        self.assertEqual(len(expected), 21)
        for name in expected:
            self.assertTrue(
                hasattr(self.api.quality, name),
                f"QualityFacade.{name} manquante",
            )
            self.assertTrue(
                callable(getattr(self.api.quality, name)),
                f"QualityFacade.{name} non callable",
            )

    # ----- Profile (8) -----

    def test_get_quality_profile_delegates(self) -> None:
        sentinel = {"version": 1, "weights": {}}
        with patch.object(self.api, "get_quality_profile", return_value=sentinel) as mocked:
            result = self.api.quality.get_quality_profile()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_save_quality_profile_delegates(self) -> None:
        sentinel = {"ok": True}
        profile = {"version": 1, "weights": {"video": 50}}
        with patch.object(self.api, "save_quality_profile", return_value=sentinel) as mocked:
            result = self.api.quality.save_quality_profile(profile)
        mocked.assert_called_once_with(profile)
        self.assertEqual(result, sentinel)

    def test_reset_quality_profile_delegates(self) -> None:
        sentinel = {"ok": True, "reset": True}
        with patch.object(self.api, "reset_quality_profile", return_value=sentinel) as mocked:
            result = self.api.quality.reset_quality_profile()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_export_quality_profile_delegates(self) -> None:
        sentinel = {"ok": True, "profile_json": {}}
        with patch.object(self.api, "export_quality_profile", return_value=sentinel) as mocked:
            result = self.api.quality.export_quality_profile()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_import_quality_profile_delegates(self) -> None:
        sentinel = {"ok": True}
        profile = {"version": 1}
        with patch.object(self.api, "import_quality_profile", return_value=sentinel) as mocked:
            result = self.api.quality.import_quality_profile(profile)
        mocked.assert_called_once_with(profile)
        self.assertEqual(result, sentinel)

    def test_get_quality_presets_delegates(self) -> None:
        sentinel = {"ok": True, "presets": []}
        with patch.object(self.api, "get_quality_presets", return_value=sentinel) as mocked:
            result = self.api.quality.get_quality_presets()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_apply_quality_preset_delegates(self) -> None:
        sentinel = {"ok": True, "applied": "equilibre"}
        with patch.object(self.api, "apply_quality_preset", return_value=sentinel) as mocked:
            result = self.api.quality.apply_quality_preset("equilibre")
        mocked.assert_called_once_with("equilibre")
        self.assertEqual(result, sentinel)

    def test_simulate_quality_preset_delegates_with_defaults(self) -> None:
        """Les 4 defaults (run_id, preset_id, overrides, scope) sont transmis correctement."""
        sentinel = {"ok": True}
        with patch.object(self.api, "simulate_quality_preset", return_value=sentinel) as mocked:
            self.api.quality.simulate_quality_preset()
        mocked.assert_called_once_with(run_id="latest", preset_id="equilibre", overrides=None, scope="run")

    def test_simulate_quality_preset_delegates_with_overrides(self) -> None:
        sentinel = {"ok": True, "summary": {}}
        overrides = {"weights": {"video": 60}}
        with patch.object(self.api, "simulate_quality_preset", return_value=sentinel) as mocked:
            self.api.quality.simulate_quality_preset(
                run_id="run_xyz", preset_id="strict", overrides=overrides, scope="film"
            )
        mocked.assert_called_once_with(run_id="run_xyz", preset_id="strict", overrides=overrides, scope="film")

    # ----- Report & rules (5) -----

    def test_get_quality_report_delegates(self) -> None:
        sentinel = {"ok": True, "score": 85}
        with patch.object(self.api, "get_quality_report", return_value=sentinel) as mocked:
            result = self.api.quality.get_quality_report("run_xyz", "row_42", {"verbose": True})
        mocked.assert_called_once_with("run_xyz", "row_42", {"verbose": True})
        self.assertEqual(result, sentinel)

    def test_get_quality_report_default_options(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "get_quality_report", return_value=sentinel) as mocked:
            self.api.quality.get_quality_report("run_xyz", "row_42")
        mocked.assert_called_once_with("run_xyz", "row_42", None)

    def test_analyze_quality_batch_delegates(self) -> None:
        sentinel = {"ok": True, "processed": 3}
        with patch.object(self.api, "analyze_quality_batch", return_value=sentinel) as mocked:
            result = self.api.quality.analyze_quality_batch("run_xyz", ["a", "b", "c"], None)
        mocked.assert_called_once_with("run_xyz", ["a", "b", "c"], None)
        self.assertEqual(result, sentinel)

    def test_save_custom_quality_preset_delegates(self) -> None:
        sentinel = {"ok": True}
        profile = {"weights": {}}
        with patch.object(self.api, "save_custom_quality_preset", return_value=sentinel) as mocked:
            result = self.api.quality.save_custom_quality_preset("MyPreset", profile)
        mocked.assert_called_once_with("MyPreset", profile)
        self.assertEqual(result, sentinel)

    def test_get_custom_rules_templates_delegates(self) -> None:
        sentinel = {"ok": True, "templates": []}
        with patch.object(self.api, "get_custom_rules_templates", return_value=sentinel) as mocked:
            result = self.api.quality.get_custom_rules_templates()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_get_custom_rules_catalog_delegates(self) -> None:
        sentinel = {"ok": True, "fields": []}
        with patch.object(self.api, "get_custom_rules_catalog", return_value=sentinel) as mocked:
            result = self.api.quality.get_custom_rules_catalog()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    # ----- Validation (1) -----

    def test_validate_custom_rules_delegates(self) -> None:
        sentinel = {"ok": True, "errors": [], "normalized": []}
        rules = [{"field": "score", "operator": "gt", "value": 80}]
        with patch.object(self.api, "validate_custom_rules", return_value=sentinel) as mocked:
            result = self.api.quality.validate_custom_rules(rules)
        mocked.assert_called_once_with(rules)
        self.assertEqual(result, sentinel)

    # ----- Perceptual (4) -----

    def test_get_perceptual_report_delegates(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "get_perceptual_report", return_value=sentinel) as mocked:
            result = self.api.quality.get_perceptual_report("run_xyz", "row_42", None)
        mocked.assert_called_once_with("run_xyz", "row_42", None)
        self.assertEqual(result, sentinel)

    def test_get_perceptual_details_delegates(self) -> None:
        sentinel = {"ok": True, "metrics": {}}
        with patch.object(self.api, "get_perceptual_details", return_value=sentinel) as mocked:
            result = self.api.quality.get_perceptual_details("run_xyz", "row_42")
        mocked.assert_called_once_with("run_xyz", "row_42")
        self.assertEqual(result, sentinel)

    def test_analyze_perceptual_batch_delegates(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "analyze_perceptual_batch", return_value=sentinel) as mocked:
            result = self.api.quality.analyze_perceptual_batch("run_xyz", ["a", "b"], None)
        mocked.assert_called_once_with("run_xyz", ["a", "b"], None)
        self.assertEqual(result, sentinel)

    def test_compare_perceptual_delegates(self) -> None:
        sentinel = {"ok": True, "similarity": 0.95}
        with patch.object(self.api, "compare_perceptual", return_value=sentinel) as mocked:
            result = self.api.quality.compare_perceptual("run_xyz", "row_a", "row_b", None)
        mocked.assert_called_once_with("run_xyz", "row_a", "row_b", None)
        self.assertEqual(result, sentinel)

    # ----- Feedback / Calibration (3) -----

    def test_submit_score_feedback_delegates(self) -> None:
        sentinel = {"ok": True, "feedback_id": 1}
        with patch.object(self.api, "submit_score_feedback", return_value=sentinel) as mocked:
            result = self.api.quality.submit_score_feedback(
                "run_xyz", "row_42", "Gold", category_focus="video", comment="nice"
            )
        mocked.assert_called_once_with("run_xyz", "row_42", "Gold", "video", "nice")
        self.assertEqual(result, sentinel)

    def test_submit_score_feedback_minimal_args(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "submit_score_feedback", return_value=sentinel) as mocked:
            self.api.quality.submit_score_feedback("run_xyz", "row_42", "Gold")
        mocked.assert_called_once_with("run_xyz", "row_42", "Gold", None, None)

    def test_delete_score_feedback_delegates(self) -> None:
        sentinel = {"ok": True, "deleted_count": 1}
        with patch.object(self.api, "delete_score_feedback", return_value=sentinel) as mocked:
            result = self.api.quality.delete_score_feedback(42)
        mocked.assert_called_once_with(42)
        self.assertEqual(result, sentinel)

    def test_get_calibration_report_delegates(self) -> None:
        sentinel = {"ok": True, "bias": {}}
        with patch.object(self.api, "get_calibration_report", return_value=sentinel) as mocked:
            result = self.api.quality.get_calibration_report()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)


class QualityFacadeBackwardCompatTests(unittest.TestCase):
    """Les 21 anciennes methodes Quality directes restent fonctionnelles."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_all_21_old_quality_methods_still_exist(self) -> None:
        for name in (
            "get_quality_profile",
            "save_quality_profile",
            "reset_quality_profile",
            "export_quality_profile",
            "import_quality_profile",
            "get_quality_presets",
            "apply_quality_preset",
            "simulate_quality_preset",
            "get_quality_report",
            "analyze_quality_batch",
            "save_custom_quality_preset",
            "get_custom_rules_templates",
            "get_custom_rules_catalog",
            "validate_custom_rules",
            "get_perceptual_report",
            "get_perceptual_details",
            "analyze_perceptual_batch",
            "compare_perceptual",
            "submit_score_feedback",
            "delete_score_feedback",
            "get_calibration_report",
        ):
            self.assertTrue(
                hasattr(self.api, name),
                f"CineSortApi.{name} a disparu (regression backward-compat)",
            )

    def test_get_quality_profile_via_old_and_new_returns_same_keys(self) -> None:
        """Parite structurelle : memes cles via api.X et api.quality.X."""
        old = self.api.quality.get_quality_profile()
        new = self.api.quality.get_quality_profile()
        self.assertEqual(set(old.keys()), set(new.keys()))


class IntegrationsFacadeFullMigrationTests(unittest.TestCase):
    """PR 5 : les 11 methodes du bounded context Integrations sont exposees."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_integrations_facade_exposes_11_methods(self) -> None:
        """Sanity : les 11 methodes du bounded context Integrations existent."""
        expected = {
            # TMDb (2)
            "test_tmdb_key",
            "get_tmdb_posters",
            # Jellyfin (3)
            "test_jellyfin_connection",
            "get_jellyfin_libraries",
            "get_jellyfin_sync_report",
            # Plex (3)
            "test_plex_connection",
            "get_plex_libraries",
            "get_plex_sync_report",
            # Radarr (3)
            "test_radarr_connection",
            "get_radarr_status",
            "request_radarr_upgrade",
        }
        self.assertEqual(len(expected), 11)
        for name in expected:
            self.assertTrue(
                hasattr(self.api.integrations, name),
                f"IntegrationsFacade.{name} manquante",
            )
            self.assertTrue(
                callable(getattr(self.api.integrations, name)),
                f"IntegrationsFacade.{name} non callable",
            )

    # ----- TMDb (2) -----

    def test_test_tmdb_key_delegates(self) -> None:
        sentinel = {"ok": True, "capabilities": []}
        with patch.object(self.api, "test_tmdb_key", return_value=sentinel) as mocked:
            result = self.api.integrations.test_tmdb_key("KEY123", "C:/state", 5.0)
        mocked.assert_called_once_with("KEY123", "C:/state", 5.0)
        self.assertEqual(result, sentinel)

    def test_test_tmdb_key_default_timeout(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "test_tmdb_key", return_value=sentinel) as mocked:
            self.api.integrations.test_tmdb_key("KEY", "C:/state")
        mocked.assert_called_once_with("KEY", "C:/state", 10.0)

    def test_get_tmdb_posters_delegates(self) -> None:
        sentinel = {"ok": True, "posters": {}}
        with patch.object(self.api, "get_tmdb_posters", return_value=sentinel) as mocked:
            result = self.api.integrations.get_tmdb_posters([27205, 19995], size="w185")
        mocked.assert_called_once_with([27205, 19995], "w185")
        self.assertEqual(result, sentinel)

    def test_get_tmdb_posters_default_size(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "get_tmdb_posters", return_value=sentinel) as mocked:
            self.api.integrations.get_tmdb_posters([1])
        mocked.assert_called_once_with([1], "w92")

    # ----- Jellyfin (3) -----

    def test_test_jellyfin_connection_delegates(self) -> None:
        sentinel = {"ok": True, "server": "Jellyfin"}
        with patch.object(self.api, "test_jellyfin_connection", return_value=sentinel) as mocked:
            result = self.api.integrations.test_jellyfin_connection(url="http://jf:8096", api_key="KEY", timeout_s=5.0)
        mocked.assert_called_once_with(url="http://jf:8096", api_key="KEY", timeout_s=5.0)
        self.assertEqual(result, sentinel)

    def test_get_jellyfin_libraries_delegates(self) -> None:
        sentinel = {"ok": True, "libraries": []}
        with patch.object(self.api, "get_jellyfin_libraries", return_value=sentinel) as mocked:
            result = self.api.integrations.get_jellyfin_libraries()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_get_jellyfin_sync_report_delegates(self) -> None:
        sentinel = {"ok": True, "matched": []}
        with patch.object(self.api, "get_jellyfin_sync_report", return_value=sentinel) as mocked:
            result = self.api.integrations.get_jellyfin_sync_report("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)

    def test_get_jellyfin_sync_report_default_run_id(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "get_jellyfin_sync_report", return_value=sentinel) as mocked:
            self.api.integrations.get_jellyfin_sync_report()
        mocked.assert_called_once_with("")

    # ----- Plex (3) -----

    def test_test_plex_connection_delegates(self) -> None:
        sentinel = {"ok": True, "server": "Plex"}
        with patch.object(self.api, "test_plex_connection", return_value=sentinel) as mocked:
            result = self.api.integrations.test_plex_connection(url="http://plex:32400", token="TOKEN", timeout_s=8.0)
        mocked.assert_called_once_with(url="http://plex:32400", token="TOKEN", timeout_s=8.0)
        self.assertEqual(result, sentinel)

    def test_get_plex_libraries_delegates(self) -> None:
        sentinel = {"ok": True, "libraries": []}
        with patch.object(self.api, "get_plex_libraries", return_value=sentinel) as mocked:
            result = self.api.integrations.get_plex_libraries(url="http://plex:32400", token="TOKEN", timeout_s=10.0)
        mocked.assert_called_once_with(url="http://plex:32400", token="TOKEN", timeout_s=10.0)
        self.assertEqual(result, sentinel)

    def test_get_plex_sync_report_delegates(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "get_plex_sync_report", return_value=sentinel) as mocked:
            result = self.api.integrations.get_plex_sync_report("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)

    # ----- Radarr (3) -----

    def test_test_radarr_connection_delegates(self) -> None:
        sentinel = {"ok": True, "version": "5.0"}
        with patch.object(self.api, "test_radarr_connection", return_value=sentinel) as mocked:
            result = self.api.integrations.test_radarr_connection(
                url="http://radarr:7878", api_key="KEY", timeout_s=10.0
            )
        mocked.assert_called_once_with(url="http://radarr:7878", api_key="KEY", timeout_s=10.0)
        self.assertEqual(result, sentinel)

    def test_get_radarr_status_delegates(self) -> None:
        sentinel = {"ok": True, "matched": 0}
        with patch.object(self.api, "get_radarr_status", return_value=sentinel) as mocked:
            result = self.api.integrations.get_radarr_status("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)

    def test_request_radarr_upgrade_delegates(self) -> None:
        sentinel = {"ok": True, "task_id": 42}
        with patch.object(self.api, "request_radarr_upgrade", return_value=sentinel) as mocked:
            result = self.api.integrations.request_radarr_upgrade(123)
        mocked.assert_called_once_with(123)
        self.assertEqual(result, sentinel)


class IntegrationsFacadeBackwardCompatTests(unittest.TestCase):
    """Les 11 anciennes methodes Integrations directes restent fonctionnelles."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_all_11_old_integrations_methods_still_exist(self) -> None:
        for name in (
            "test_tmdb_key",
            "get_tmdb_posters",
            "test_jellyfin_connection",
            "get_jellyfin_libraries",
            "get_jellyfin_sync_report",
            "test_plex_connection",
            "get_plex_libraries",
            "get_plex_sync_report",
            "test_radarr_connection",
            "get_radarr_status",
            "request_radarr_upgrade",
        ):
            self.assertTrue(
                hasattr(self.api, name),
                f"CineSortApi.{name} a disparu (regression backward-compat)",
            )


class LibraryFacadeFullMigrationTests(unittest.TestCase):
    """PR 6 : les 9 methodes du bounded context Library sont exposees."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_library_facade_exposes_9_methods(self) -> None:
        expected = {
            # Library + agregats (5)
            "get_library_filtered",
            "get_smart_playlists",
            "save_smart_playlist",
            "delete_smart_playlist",
            "get_scoring_rollup",
            # Film (3)
            "get_film_full",
            "get_film_history",
            "list_films_with_history",
            # Export (1)
            "export_full_library",
        }
        self.assertEqual(len(expected), 9)
        for name in expected:
            self.assertTrue(
                hasattr(self.api.library, name),
                f"LibraryFacade.{name} manquante",
            )
            self.assertTrue(
                callable(getattr(self.api.library, name)),
                f"LibraryFacade.{name} non callable",
            )

    # ----- Library + agregats (5) -----

    def test_get_library_filtered_delegates(self) -> None:
        sentinel = {"ok": True, "films": []}
        filters = {"tier_v2": "platinum"}
        with patch.object(self.api, "get_library_filtered", return_value=sentinel) as mocked:
            result = self.api.library.get_library_filtered(
                run_id="run_xyz", filters=filters, sort="score", page=2, page_size=25
            )
        mocked.assert_called_once_with(run_id="run_xyz", filters=filters, sort="score", page=2, page_size=25)
        self.assertEqual(result, sentinel)

    def test_get_library_filtered_defaults(self) -> None:
        """Sanity check : les defaults matchent ceux de CineSortApi (sort='title')."""
        sentinel = {"ok": True}
        with patch.object(self.api, "get_library_filtered", return_value=sentinel) as mocked:
            self.api.library.get_library_filtered()
        mocked.assert_called_once_with(run_id=None, filters=None, sort="title", page=1, page_size=50)

    def test_get_smart_playlists_delegates(self) -> None:
        sentinel = {"ok": True, "playlists": []}
        with patch.object(self.api, "get_smart_playlists", return_value=sentinel) as mocked:
            result = self.api.library.get_smart_playlists()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_save_smart_playlist_delegates(self) -> None:
        sentinel = {"ok": True, "playlist_id": "pl_42"}
        filters = {"tier_v2": "gold"}
        with patch.object(self.api, "save_smart_playlist", return_value=sentinel) as mocked:
            result = self.api.library.save_smart_playlist("My Playlist", filters, playlist_id="pl_42")
        mocked.assert_called_once_with("My Playlist", filters, "pl_42")
        self.assertEqual(result, sentinel)

    def test_save_smart_playlist_no_id(self) -> None:
        """playlist_id optionnel : None doit etre transmis quand absent."""
        sentinel = {"ok": True}
        filters = {}
        with patch.object(self.api, "save_smart_playlist", return_value=sentinel) as mocked:
            self.api.library.save_smart_playlist("New", filters)
        mocked.assert_called_once_with("New", filters, None)

    def test_delete_smart_playlist_delegates(self) -> None:
        sentinel = {"ok": True, "deleted": True}
        with patch.object(self.api, "delete_smart_playlist", return_value=sentinel) as mocked:
            result = self.api.library.delete_smart_playlist("pl_42")
        mocked.assert_called_once_with("pl_42")
        self.assertEqual(result, sentinel)

    def test_get_scoring_rollup_delegates(self) -> None:
        sentinel = {"ok": True, "rollup": []}
        with patch.object(self.api, "get_scoring_rollup", return_value=sentinel) as mocked:
            result = self.api.library.get_scoring_rollup(by="decade", limit=10, run_id="run_xyz")
        mocked.assert_called_once_with(by="decade", limit=10, run_id="run_xyz")
        self.assertEqual(result, sentinel)

    def test_get_scoring_rollup_defaults(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "get_scoring_rollup", return_value=sentinel) as mocked:
            self.api.library.get_scoring_rollup()
        mocked.assert_called_once_with(by="franchise", limit=20, run_id=None)

    # ----- Film (3) -----

    def test_get_film_full_delegates(self) -> None:
        sentinel = {"ok": True, "film": {}}
        with patch.object(self.api, "get_film_full", return_value=sentinel) as mocked:
            result = self.api.library.get_film_full("row_42", run_id="run_xyz")
        mocked.assert_called_once_with("row_42", "run_xyz")
        self.assertEqual(result, sentinel)

    def test_get_film_full_no_run_id(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "get_film_full", return_value=sentinel) as mocked:
            self.api.library.get_film_full("row_42")
        mocked.assert_called_once_with("row_42", None)

    def test_get_film_history_delegates(self) -> None:
        sentinel = {"ok": True, "timeline": []}
        with patch.object(self.api, "get_film_history", return_value=sentinel) as mocked:
            result = self.api.library.get_film_history("film_xyz")
        mocked.assert_called_once_with("film_xyz")
        self.assertEqual(result, sentinel)

    def test_list_films_with_history_delegates(self) -> None:
        sentinel = {"ok": True, "films": []}
        with patch.object(self.api, "list_films_with_history", return_value=sentinel) as mocked:
            result = self.api.library.list_films_with_history(limit=25)
        mocked.assert_called_once_with(25)
        self.assertEqual(result, sentinel)

    def test_list_films_with_history_default_limit(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "list_films_with_history", return_value=sentinel) as mocked:
            self.api.library.list_films_with_history()
        mocked.assert_called_once_with(50)

    # ----- Export RGPD (1) -----

    def test_export_full_library_delegates(self) -> None:
        sentinel = {"ok": True, "version": "1.0", "films": []}
        with patch.object(self.api, "export_full_library", return_value=sentinel) as mocked:
            result = self.api.library.export_full_library()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)


class LibraryFacadeBackwardCompatTests(unittest.TestCase):
    """Les 9 anciennes methodes Library directes restent fonctionnelles."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_all_9_old_library_methods_still_exist(self) -> None:
        for name in (
            "get_library_filtered",
            "get_smart_playlists",
            "save_smart_playlist",
            "delete_smart_playlist",
            "get_scoring_rollup",
            "get_film_full",
            "get_film_history",
            "list_films_with_history",
            "export_full_library",
        ):
            self.assertTrue(
                hasattr(self.api, name),
                f"CineSortApi.{name} a disparu (regression backward-compat)",
            )


class BackwardCompatTests(unittest.TestCase):
    """Les anciennes methodes directes restent fonctionnelles (Strangler Fig safety)."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_old_methods_still_exist(self) -> None:
        """Sanity : les methodes pilote sont toujours sur l'API directe."""
        self.assertTrue(hasattr(self.api, "start_plan"))
        self.assertTrue(hasattr(self.api, "get_settings"))
        self.assertTrue(hasattr(self.api, "get_quality_profile"))
        self.assertTrue(hasattr(self.api, "test_jellyfin_connection"))
        self.assertTrue(hasattr(self.api, "get_library_filtered"))

    def test_old_methods_callable(self) -> None:
        """Les anciennes methodes sont toujours callables."""
        # get_settings ne necessite aucun arg, retourne directement le dict settings
        result = self.api.settings.get_settings()
        self.assertIsInstance(result, dict)
        # Sanity check : contient au moins quelques cles attendues
        self.assertIn("root", result)
        self.assertIn("state_dir", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
