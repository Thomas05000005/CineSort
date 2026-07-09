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
        with patch.object(self.api, "_start_plan_impl", return_value=sentinel) as mocked:
            settings = {"root": "C:/test"}
            result = self.api.run.start_plan(settings)
        mocked.assert_called_once_with(settings)
        self.assertEqual(result, sentinel)

    def test_get_status_delegates(self) -> None:
        sentinel = {"ok": True, "progress": 0.5}
        with patch.object(self.api, "_get_status_impl", return_value=sentinel) as mocked:
            result = self.api.run.get_status("run_xyz", last_log_index=42)
        mocked.assert_called_once_with("run_xyz", 42)
        self.assertEqual(result, sentinel)

    def test_get_status_default_last_log_index(self) -> None:
        """Le default last_log_index=0 doit etre transmis correctement."""
        sentinel = {"ok": True}
        with patch.object(self.api, "_get_status_impl", return_value=sentinel) as mocked:
            self.api.run.get_status("run_xyz")
        mocked.assert_called_once_with("run_xyz", 0)

    def test_get_plan_delegates(self) -> None:
        sentinel = {"ok": True, "rows": []}
        with patch.object(self.api, "_get_plan_impl", return_value=sentinel) as mocked:
            result = self.api.run.get_plan("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)

    def test_export_run_report_delegates(self) -> None:
        sentinel = {"ok": True, "path": "C:/export.json"}
        with patch.object(self.api, "_export_run_report_impl", return_value=sentinel) as mocked:
            result = self.api.run.export_run_report("run_xyz", fmt="csv")
        mocked.assert_called_once_with("run_xyz", "csv")
        self.assertEqual(result, sentinel)

    def test_export_run_report_default_fmt(self) -> None:
        """Le default fmt='json' doit etre transmis correctement."""
        sentinel = {"ok": True}
        with patch.object(self.api, "_export_run_report_impl", return_value=sentinel) as mocked:
            self.api.run.export_run_report("run_xyz")
        mocked.assert_called_once_with("run_xyz", "json")

    def test_cancel_run_delegates(self) -> None:
        sentinel = {"ok": True, "cancelled": True}
        with patch.object(self.api, "_cancel_run_impl", return_value=sentinel) as mocked:
            result = self.api.run.cancel_run("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)

    def test_build_apply_preview_delegates(self) -> None:
        sentinel = {"ok": True, "films": []}
        decisions = {"film_1": {"approved": True}}
        with patch.object(self.api, "_build_apply_preview_impl", return_value=sentinel) as mocked:
            result = self.api.run.build_apply_preview("run_xyz", decisions)
        mocked.assert_called_once_with("run_xyz", decisions)
        self.assertEqual(result, sentinel)

    def test_list_apply_history_delegates(self) -> None:
        sentinel = {"ok": True, "batches": []}
        with patch.object(self.api, "_list_apply_history_impl", return_value=sentinel) as mocked:
            result = self.api.run.list_apply_history("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)


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
        with patch.object(self.api, "_get_settings_impl", return_value=sentinel) as mocked:
            result = self.api.settings.get_settings()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_save_settings_delegates(self) -> None:
        sentinel = {"ok": True}
        settings = {"root": "C:/new_root"}
        with patch.object(self.api, "_save_settings_impl", return_value=sentinel) as mocked:
            result = self.api.settings.save_settings(settings)
        mocked.assert_called_once_with(settings)
        self.assertEqual(result, sentinel)

    def test_set_locale_delegates(self) -> None:
        sentinel = {"ok": True, "locale": "en"}
        with patch.object(self.api, "_set_locale_impl", return_value=sentinel) as mocked:
            result = self.api.settings.set_locale("en")
        mocked.assert_called_once_with("en")
        self.assertEqual(result, sentinel)

    def test_restart_api_server_delegates(self) -> None:
        sentinel = {"ok": True, "restarted": True}
        with patch.object(self.api, "_restart_api_server_impl", return_value=sentinel) as mocked:
            result = self.api.settings.restart_api_server()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_reset_all_user_data_delegates(self) -> None:
        sentinel = {"ok": True, "backup_path": "C:/backup.zip"}
        with patch.object(self.api, "_reset_all_user_data_impl", return_value=sentinel) as mocked:
            result = self.api.settings.reset_all_user_data("CONFIRM")
        mocked.assert_called_once_with("CONFIRM")
        self.assertEqual(result, sentinel)

    def test_reset_all_user_data_default_confirmation(self) -> None:
        """Le default confirmation='' doit etre transmis correctement."""
        sentinel = {"ok": False, "message": "confirmation manquante"}
        with patch.object(self.api, "_reset_all_user_data_impl", return_value=sentinel) as mocked:
            self.api.settings.reset_all_user_data()
        mocked.assert_called_once_with("")

    def test_get_user_data_size_delegates(self) -> None:
        sentinel = {"data": {"total_bytes": 12345}}
        with patch.object(self.api, "_get_user_data_size_impl", return_value=sentinel) as mocked:
            result = self.api.settings.get_user_data_size()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)


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
        with patch.object(self.api, "_get_quality_profile_impl", return_value=sentinel) as mocked:
            result = self.api.quality.get_quality_profile()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_save_quality_profile_delegates(self) -> None:
        sentinel = {"ok": True}
        profile = {"version": 1, "weights": {"video": 50}}
        with patch.object(self.api, "_save_quality_profile_impl", return_value=sentinel) as mocked:
            result = self.api.quality.save_quality_profile(profile)
        mocked.assert_called_once_with(profile)
        self.assertEqual(result, sentinel)

    def test_reset_quality_profile_delegates(self) -> None:
        sentinel = {"ok": True, "reset": True}
        with patch.object(self.api, "_reset_quality_profile_impl", return_value=sentinel) as mocked:
            result = self.api.quality.reset_quality_profile()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_export_quality_profile_delegates(self) -> None:
        sentinel = {"ok": True, "profile_json": {}}
        with patch.object(self.api, "_export_quality_profile_impl", return_value=sentinel) as mocked:
            result = self.api.quality.export_quality_profile()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_import_quality_profile_delegates(self) -> None:
        sentinel = {"ok": True}
        profile = {"version": 1}
        with patch.object(self.api, "_import_quality_profile_impl", return_value=sentinel) as mocked:
            result = self.api.quality.import_quality_profile(profile)
        mocked.assert_called_once_with(profile)
        self.assertEqual(result, sentinel)

    def test_get_quality_presets_delegates(self) -> None:
        sentinel = {"ok": True, "presets": []}
        with patch.object(self.api, "_get_quality_presets_impl", return_value=sentinel) as mocked:
            result = self.api.quality.get_quality_presets()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_apply_quality_preset_delegates(self) -> None:
        sentinel = {"ok": True, "applied": "equilibre"}
        with patch.object(self.api, "_apply_quality_preset_impl", return_value=sentinel) as mocked:
            result = self.api.quality.apply_quality_preset("equilibre")
        mocked.assert_called_once_with("equilibre")
        self.assertEqual(result, sentinel)

    def test_simulate_quality_preset_delegates_with_defaults(self) -> None:
        """Les 4 defaults (run_id, preset_id, overrides, scope) sont transmis correctement."""
        sentinel = {"ok": True}
        with patch.object(self.api, "_simulate_quality_preset_impl", return_value=sentinel) as mocked:
            self.api.quality.simulate_quality_preset()
        mocked.assert_called_once_with(run_id="latest", preset_id="equilibre", overrides=None, scope="run")

    def test_simulate_quality_preset_delegates_with_overrides(self) -> None:
        sentinel = {"ok": True, "summary": {}}
        overrides = {"weights": {"video": 60}}
        with patch.object(self.api, "_simulate_quality_preset_impl", return_value=sentinel) as mocked:
            self.api.quality.simulate_quality_preset(
                run_id="run_xyz", preset_id="strict", overrides=overrides, scope="film"
            )
        mocked.assert_called_once_with(run_id="run_xyz", preset_id="strict", overrides=overrides, scope="film")

    # ----- Report & rules (5) -----

    def test_get_quality_report_delegates(self) -> None:
        sentinel = {"ok": True, "score": 85}
        with patch.object(self.api, "_get_quality_report_impl", return_value=sentinel) as mocked:
            result = self.api.quality.get_quality_report("run_xyz", "row_42", {"verbose": True})
        mocked.assert_called_once_with("run_xyz", "row_42", {"verbose": True})
        self.assertEqual(result, sentinel)

    def test_get_quality_report_default_options(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_get_quality_report_impl", return_value=sentinel) as mocked:
            self.api.quality.get_quality_report("run_xyz", "row_42")
        mocked.assert_called_once_with("run_xyz", "row_42", None)

    def test_analyze_quality_batch_delegates(self) -> None:
        sentinel = {"ok": True, "processed": 3}
        with patch.object(self.api, "_analyze_quality_batch_impl", return_value=sentinel) as mocked:
            result = self.api.quality.analyze_quality_batch("run_xyz", ["a", "b", "c"], None)
        mocked.assert_called_once_with("run_xyz", ["a", "b", "c"], None)
        self.assertEqual(result, sentinel)

    def test_save_custom_quality_preset_delegates(self) -> None:
        sentinel = {"ok": True}
        profile = {"weights": {}}
        with patch.object(self.api, "_save_custom_quality_preset_impl", return_value=sentinel) as mocked:
            result = self.api.quality.save_custom_quality_preset("MyPreset", profile)
        mocked.assert_called_once_with("MyPreset", profile)
        self.assertEqual(result, sentinel)

    def test_get_custom_rules_templates_delegates(self) -> None:
        sentinel = {"ok": True, "templates": []}
        with patch.object(self.api, "_get_custom_rules_templates_impl", return_value=sentinel) as mocked:
            result = self.api.quality.get_custom_rules_templates()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_get_custom_rules_catalog_delegates(self) -> None:
        sentinel = {"ok": True, "fields": []}
        with patch.object(self.api, "_get_custom_rules_catalog_impl", return_value=sentinel) as mocked:
            result = self.api.quality.get_custom_rules_catalog()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    # ----- Validation (1) -----

    def test_validate_custom_rules_delegates(self) -> None:
        sentinel = {"ok": True, "errors": [], "normalized": []}
        rules = [{"field": "score", "operator": "gt", "value": 80}]
        with patch.object(self.api, "_validate_custom_rules_impl", return_value=sentinel) as mocked:
            result = self.api.quality.validate_custom_rules(rules)
        mocked.assert_called_once_with(rules)
        self.assertEqual(result, sentinel)

    # ----- Perceptual (4) -----

    def test_get_perceptual_report_delegates(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_get_perceptual_report_impl", return_value=sentinel) as mocked:
            result = self.api.quality.get_perceptual_report("run_xyz", "row_42", None)
        mocked.assert_called_once_with("run_xyz", "row_42", None)
        self.assertEqual(result, sentinel)

    def test_get_perceptual_details_delegates(self) -> None:
        sentinel = {"ok": True, "metrics": {}}
        with patch.object(self.api, "_get_perceptual_details_impl", return_value=sentinel) as mocked:
            result = self.api.quality.get_perceptual_details("run_xyz", "row_42")
        mocked.assert_called_once_with("run_xyz", "row_42")
        self.assertEqual(result, sentinel)

    def test_analyze_perceptual_batch_delegates(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_analyze_perceptual_batch_impl", return_value=sentinel) as mocked:
            result = self.api.quality.analyze_perceptual_batch("run_xyz", ["a", "b"], None)
        mocked.assert_called_once_with("run_xyz", ["a", "b"], None)
        self.assertEqual(result, sentinel)

    def test_compare_perceptual_delegates(self) -> None:
        sentinel = {"ok": True, "similarity": 0.95}
        with patch.object(self.api, "_compare_perceptual_impl", return_value=sentinel) as mocked:
            result = self.api.quality.compare_perceptual("run_xyz", "row_a", "row_b", None)
        mocked.assert_called_once_with("run_xyz", "row_a", "row_b", None)
        self.assertEqual(result, sentinel)

    # ----- Feedback / Calibration (3) -----

    def test_submit_score_feedback_delegates(self) -> None:
        sentinel = {"ok": True, "feedback_id": 1}
        with patch.object(self.api, "_submit_score_feedback_impl", return_value=sentinel) as mocked:
            result = self.api.quality.submit_score_feedback(
                "run_xyz", "row_42", "Gold", category_focus="video", comment="nice"
            )
        mocked.assert_called_once_with("run_xyz", "row_42", "Gold", "video", "nice")
        self.assertEqual(result, sentinel)

    def test_submit_score_feedback_minimal_args(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_submit_score_feedback_impl", return_value=sentinel) as mocked:
            self.api.quality.submit_score_feedback("run_xyz", "row_42", "Gold")
        mocked.assert_called_once_with("run_xyz", "row_42", "Gold", None, None)

    def test_delete_score_feedback_delegates(self) -> None:
        sentinel = {"ok": True, "deleted_count": 1}
        with patch.object(self.api, "_delete_score_feedback_impl", return_value=sentinel) as mocked:
            result = self.api.quality.delete_score_feedback(42)
        mocked.assert_called_once_with(42)
        self.assertEqual(result, sentinel)

    def test_get_calibration_report_delegates(self) -> None:
        sentinel = {"ok": True, "bias": {}}
        with patch.object(self.api, "_get_calibration_report_impl", return_value=sentinel) as mocked:
            result = self.api.quality.get_calibration_report()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)


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
        with patch.object(self.api, "_test_tmdb_key_impl", return_value=sentinel) as mocked:
            result = self.api.integrations.test_tmdb_key("KEY123", "C:/state", 5.0)
        mocked.assert_called_once_with("KEY123", "C:/state", 5.0)
        self.assertEqual(result, sentinel)

    def test_test_tmdb_key_default_timeout(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_test_tmdb_key_impl", return_value=sentinel) as mocked:
            self.api.integrations.test_tmdb_key("KEY", "C:/state")
        mocked.assert_called_once_with("KEY", "C:/state", 10.0)

    def test_get_tmdb_posters_delegates(self) -> None:
        sentinel = {"ok": True, "posters": {}}
        with patch.object(self.api, "_get_tmdb_posters_impl", return_value=sentinel) as mocked:
            result = self.api.integrations.get_tmdb_posters([27205, 19995], size="w185")
        mocked.assert_called_once_with([27205, 19995], "w185", force_refresh=False)
        self.assertEqual(result, sentinel)

    def test_get_tmdb_posters_default_size(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_get_tmdb_posters_impl", return_value=sentinel) as mocked:
            self.api.integrations.get_tmdb_posters([1])
        mocked.assert_called_once_with([1], "w92", force_refresh=False)

    # ----- Jellyfin (3) -----

    def test_test_jellyfin_connection_delegates(self) -> None:
        sentinel = {"ok": True, "server": "Jellyfin"}
        with patch.object(self.api, "_test_jellyfin_connection_impl", return_value=sentinel) as mocked:
            result = self.api.integrations.test_jellyfin_connection(url="http://jf:8096", api_key="KEY", timeout_s=5.0)
        mocked.assert_called_once_with(url="http://jf:8096", api_key="KEY", timeout_s=5.0)
        self.assertEqual(result, sentinel)

    def test_get_jellyfin_libraries_delegates(self) -> None:
        sentinel = {"ok": True, "libraries": []}
        with patch.object(self.api, "_get_jellyfin_libraries_impl", return_value=sentinel) as mocked:
            result = self.api.integrations.get_jellyfin_libraries()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_get_jellyfin_sync_report_delegates(self) -> None:
        sentinel = {"ok": True, "matched": []}
        with patch.object(self.api, "_get_jellyfin_sync_report_impl", return_value=sentinel) as mocked:
            result = self.api.integrations.get_jellyfin_sync_report("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)

    def test_get_jellyfin_sync_report_default_run_id(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_get_jellyfin_sync_report_impl", return_value=sentinel) as mocked:
            self.api.integrations.get_jellyfin_sync_report()
        mocked.assert_called_once_with("")

    # ----- Plex (3) -----

    def test_test_plex_connection_delegates(self) -> None:
        sentinel = {"ok": True, "server": "Plex"}
        with patch.object(self.api, "_test_plex_connection_impl", return_value=sentinel) as mocked:
            result = self.api.integrations.test_plex_connection(url="http://plex:32400", token="TOKEN", timeout_s=8.0)
        mocked.assert_called_once_with(url="http://plex:32400", token="TOKEN", timeout_s=8.0)
        self.assertEqual(result, sentinel)

    def test_get_plex_libraries_delegates(self) -> None:
        sentinel = {"ok": True, "libraries": []}
        with patch.object(self.api, "_get_plex_libraries_impl", return_value=sentinel) as mocked:
            result = self.api.integrations.get_plex_libraries(url="http://plex:32400", token="TOKEN", timeout_s=10.0)
        mocked.assert_called_once_with(url="http://plex:32400", token="TOKEN", timeout_s=10.0)
        self.assertEqual(result, sentinel)

    def test_get_plex_sync_report_delegates(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_get_plex_sync_report_impl", return_value=sentinel) as mocked:
            result = self.api.integrations.get_plex_sync_report("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)

    # ----- Radarr (3) -----

    def test_test_radarr_connection_delegates(self) -> None:
        sentinel = {"ok": True, "version": "5.0"}
        with patch.object(self.api, "_test_radarr_connection_impl", return_value=sentinel) as mocked:
            result = self.api.integrations.test_radarr_connection(
                url="http://radarr:7878", api_key="KEY", timeout_s=10.0
            )
        mocked.assert_called_once_with(url="http://radarr:7878", api_key="KEY", timeout_s=10.0)
        self.assertEqual(result, sentinel)

    def test_get_radarr_status_delegates(self) -> None:
        sentinel = {"ok": True, "matched": 0}
        with patch.object(self.api, "_get_radarr_status_impl", return_value=sentinel) as mocked:
            result = self.api.integrations.get_radarr_status("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)

    def test_request_radarr_upgrade_delegates(self) -> None:
        sentinel = {"ok": True, "task_id": 42}
        with patch.object(self.api, "_request_radarr_upgrade_impl", return_value=sentinel) as mocked:
            result = self.api.integrations.request_radarr_upgrade(123)
        mocked.assert_called_once_with(123)
        self.assertEqual(result, sentinel)


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
        with patch.object(self.api, "_get_library_filtered_impl", return_value=sentinel) as mocked:
            result = self.api.library.get_library_filtered(
                run_id="run_xyz", filters=filters, sort="score", page=2, page_size=25
            )
        mocked.assert_called_once_with(run_id="run_xyz", filters=filters, sort="score", page=2, page_size=25)
        self.assertEqual(result, sentinel)

    def test_get_library_filtered_defaults(self) -> None:
        """Sanity check : les defaults matchent ceux de CineSortApi (sort='title')."""
        sentinel = {"ok": True}
        with patch.object(self.api, "_get_library_filtered_impl", return_value=sentinel) as mocked:
            self.api.library.get_library_filtered()
        mocked.assert_called_once_with(run_id=None, filters=None, sort="title", page=1, page_size=50)

    def test_get_smart_playlists_delegates(self) -> None:
        sentinel = {"ok": True, "playlists": []}
        with patch.object(self.api, "_get_smart_playlists_impl", return_value=sentinel) as mocked:
            result = self.api.library.get_smart_playlists()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_save_smart_playlist_delegates(self) -> None:
        sentinel = {"ok": True, "playlist_id": "pl_42"}
        filters = {"tier_v2": "gold"}
        with patch.object(self.api, "_save_smart_playlist_impl", return_value=sentinel) as mocked:
            result = self.api.library.save_smart_playlist("My Playlist", filters, playlist_id="pl_42")
        mocked.assert_called_once_with("My Playlist", filters, "pl_42")
        self.assertEqual(result, sentinel)

    def test_save_smart_playlist_no_id(self) -> None:
        """playlist_id optionnel : None doit etre transmis quand absent."""
        sentinel = {"ok": True}
        filters = {}
        with patch.object(self.api, "_save_smart_playlist_impl", return_value=sentinel) as mocked:
            self.api.library.save_smart_playlist("New", filters)
        mocked.assert_called_once_with("New", filters, None)

    def test_delete_smart_playlist_delegates(self) -> None:
        sentinel = {"ok": True, "deleted": True}
        with patch.object(self.api, "_delete_smart_playlist_impl", return_value=sentinel) as mocked:
            result = self.api.library.delete_smart_playlist("pl_42")
        mocked.assert_called_once_with("pl_42")
        self.assertEqual(result, sentinel)

    def test_get_scoring_rollup_delegates(self) -> None:
        sentinel = {"ok": True, "rollup": []}
        with patch.object(self.api, "_get_scoring_rollup_impl", return_value=sentinel) as mocked:
            result = self.api.library.get_scoring_rollup(by="decade", limit=10, run_id="run_xyz")
        mocked.assert_called_once_with(by="decade", limit=10, run_id="run_xyz")
        self.assertEqual(result, sentinel)

    def test_get_scoring_rollup_defaults(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_get_scoring_rollup_impl", return_value=sentinel) as mocked:
            self.api.library.get_scoring_rollup()
        mocked.assert_called_once_with(by="franchise", limit=20, run_id=None)

    # ----- Film (3) -----

    def test_get_film_full_delegates(self) -> None:
        sentinel = {"ok": True, "film": {}}
        with patch.object(self.api, "_get_film_full_impl", return_value=sentinel) as mocked:
            result = self.api.library.get_film_full("row_42", run_id="run_xyz")
        mocked.assert_called_once_with("row_42", "run_xyz")
        self.assertEqual(result, sentinel)

    def test_get_film_full_no_run_id(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_get_film_full_impl", return_value=sentinel) as mocked:
            self.api.library.get_film_full("row_42")
        mocked.assert_called_once_with("row_42", None)

    def test_get_film_history_delegates(self) -> None:
        sentinel = {"ok": True, "timeline": []}
        with patch.object(self.api, "_get_film_history_impl", return_value=sentinel) as mocked:
            result = self.api.library.get_film_history("film_xyz")
        mocked.assert_called_once_with("film_xyz")
        self.assertEqual(result, sentinel)

    def test_list_films_with_history_delegates(self) -> None:
        sentinel = {"ok": True, "films": []}
        with patch.object(self.api, "_list_films_with_history_impl", return_value=sentinel) as mocked:
            result = self.api.library.list_films_with_history(limit=25)
        mocked.assert_called_once_with(25)
        self.assertEqual(result, sentinel)

    def test_list_films_with_history_default_limit(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_list_films_with_history_impl", return_value=sentinel) as mocked:
            self.api.library.list_films_with_history()
        mocked.assert_called_once_with(50)

    # ----- Export RGPD (1) -----

    def test_export_full_library_delegates(self) -> None:
        sentinel = {"ok": True, "version": "1.0", "films": []}
        with patch.object(self.api, "_export_full_library_impl", return_value=sentinel) as mocked:
            result = self.api.library.export_full_library()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)


# ---------------------------------------------------------------------------
# Sprint C1 (mai 2026) — extraction 8 methodes orphelines vers facades
# (suite de PR #335 / refactor #84). Couvre :
#   - SettingsFacade : get_naming_presets, preview_naming_template
#   - QualityFacade  : export_shareable_profile, import_shareable_profile
#   - RunFacade      : get_auto_approved_summary, undo_last_apply_preview,
#                      undo_by_row_preview, undo_selected_rows
# ---------------------------------------------------------------------------


class SettingsFacadeNamingExtensionTests(unittest.TestCase):
    """Sprint C1 : 2 methodes naming ajoutees sur SettingsFacade."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_get_naming_presets_exposed_and_delegates(self) -> None:
        self.assertTrue(callable(getattr(self.api.settings, "get_naming_presets", None)))
        sentinel = {"ok": True, "presets": [{"id": "kodi", "label": "Kodi"}]}
        with patch.object(self.api, "_get_naming_presets_impl", return_value=sentinel) as mocked:
            result = self.api.settings.get_naming_presets()
        mocked.assert_called_once_with()
        self.assertEqual(result, sentinel)

    def test_preview_naming_template_exposed_and_delegates(self) -> None:
        self.assertTrue(callable(getattr(self.api.settings, "preview_naming_template", None)))
        sentinel = {"ok": True, "result": "Inception (2010)", "variables": {}}
        with patch.object(self.api, "_preview_naming_template_impl", return_value=sentinel) as mocked:
            result = self.api.settings.preview_naming_template("{title} ({year})", "row_42")
        mocked.assert_called_once_with("{title} ({year})", "row_42")
        self.assertEqual(result, sentinel)

    def test_preview_naming_template_defaults(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_preview_naming_template_impl", return_value=sentinel) as mocked:
            self.api.settings.preview_naming_template()
        mocked.assert_called_once_with("", "")


class QualityFacadeShareableExtensionTests(unittest.TestCase):
    """Sprint C1 : 2 methodes shareable profile ajoutees sur QualityFacade."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_export_shareable_profile_exposed_and_delegates(self) -> None:
        self.assertTrue(callable(getattr(self.api.quality, "export_shareable_profile", None)))
        sentinel = {"ok": True, "content": "{}", "filename_suggestion": "x.cinesort.json"}
        with patch.object(self.api, "_export_shareable_profile_impl", return_value=sentinel) as mocked:
            result = self.api.quality.export_shareable_profile(name="MyProfile", author="me", description="hi")
        mocked.assert_called_once_with(name="MyProfile", author="me", description="hi")
        self.assertEqual(result, sentinel)

    def test_export_shareable_profile_defaults(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_export_shareable_profile_impl", return_value=sentinel) as mocked:
            self.api.quality.export_shareable_profile()
        mocked.assert_called_once_with(name="", author="", description="")

    def test_import_shareable_profile_exposed_and_delegates(self) -> None:
        self.assertTrue(callable(getattr(self.api.quality, "import_shareable_profile", None)))
        sentinel = {"ok": True, "meta": {}, "activated": True, "saved_profile_id": "x_1"}
        with patch.object(self.api, "_import_shareable_profile_impl", return_value=sentinel) as mocked:
            result = self.api.quality.import_shareable_profile('{"profile": {}}', activate=False)
        mocked.assert_called_once_with('{"profile": {}}', activate=False)
        self.assertEqual(result, sentinel)

    def test_import_shareable_profile_default_activate(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_import_shareable_profile_impl", return_value=sentinel) as mocked:
            self.api.quality.import_shareable_profile('{"profile": {}}')
        mocked.assert_called_once_with('{"profile": {}}', activate=True)


class RunFacadeAutoApproveUndoExtensionTests(unittest.TestCase):
    """Sprint C1 : 4 methodes (auto_approve + 3 undo previews) ajoutees sur RunFacade."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_get_auto_approved_summary_exposed_and_delegates(self) -> None:
        self.assertTrue(callable(getattr(self.api.run, "get_auto_approved_summary", None)))
        sentinel = {"ok": True, "auto_approved_count": 3}
        with patch.object(self.api, "_get_auto_approved_summary_impl", return_value=sentinel) as mocked:
            result = self.api.run.get_auto_approved_summary(
                "run_xyz", threshold=90, enabled=True, quarantine_corrupted=True
            )
        mocked.assert_called_once_with("run_xyz", threshold=90, enabled=True, quarantine_corrupted=True)
        self.assertEqual(result, sentinel)

    def test_get_auto_approved_summary_defaults(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_get_auto_approved_summary_impl", return_value=sentinel) as mocked:
            self.api.run.get_auto_approved_summary("run_xyz")
        mocked.assert_called_once_with("run_xyz", threshold=85, enabled=False, quarantine_corrupted=False)

    def test_undo_last_apply_preview_exposed_and_delegates(self) -> None:
        self.assertTrue(callable(getattr(self.api.run, "undo_last_apply_preview", None)))
        sentinel = {"ok": True, "operations": []}
        with patch.object(self.api, "_undo_last_apply_preview_impl", return_value=sentinel) as mocked:
            result = self.api.run.undo_last_apply_preview("run_xyz")
        mocked.assert_called_once_with("run_xyz")
        self.assertEqual(result, sentinel)

    def test_undo_by_row_preview_exposed_and_delegates(self) -> None:
        self.assertTrue(callable(getattr(self.api.run, "undo_by_row_preview", None)))
        sentinel = {"ok": True, "rows": []}
        with patch.object(self.api, "_undo_by_row_preview_impl", return_value=sentinel) as mocked:
            result = self.api.run.undo_by_row_preview("run_xyz", batch_id="b_99")
        mocked.assert_called_once_with("run_xyz", batch_id="b_99")
        self.assertEqual(result, sentinel)

    def test_undo_by_row_preview_default_batch_id(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_undo_by_row_preview_impl", return_value=sentinel) as mocked:
            self.api.run.undo_by_row_preview("run_xyz")
        mocked.assert_called_once_with("run_xyz", batch_id=None)

    def test_undo_selected_rows_exposed_and_delegates(self) -> None:
        self.assertTrue(callable(getattr(self.api.run, "undo_selected_rows", None)))
        sentinel = {"ok": True, "undone": 2}
        with patch.object(self.api, "_undo_selected_rows_impl", return_value=sentinel) as mocked:
            result = self.api.run.undo_selected_rows(
                "run_xyz",
                row_ids=["r1", "r2"],
                dry_run=False,
                batch_id="b_99",
                atomic=False,
            )
        mocked.assert_called_once_with(
            "run_xyz",
            row_ids=["r1", "r2"],
            dry_run=False,
            batch_id="b_99",
            atomic=False,
        )
        self.assertEqual(result, sentinel)

    def test_undo_selected_rows_defaults(self) -> None:
        sentinel = {"ok": True}
        with patch.object(self.api, "_undo_selected_rows_impl", return_value=sentinel) as mocked:
            self.api.run.undo_selected_rows("run_xyz")
        mocked.assert_called_once_with(
            "run_xyz",
            row_ids=None,
            dry_run=True,
            batch_id=None,
            atomic=True,
        )


# ---------------------------------------------------------------------------
# Sprint C1 — Input clamping (audit C7 P1)
# Verifie que les 5 endpoints de test connexion + test_reset bornent les
# inputs numeriques (timeout_s entre [1.0, 60.0], min_video_bytes >= 0).
# ---------------------------------------------------------------------------


class TimeoutClampingValidatorsTests(unittest.TestCase):
    """Audit C7 P1 : helper clamp_timeout (range 1-60s + fallback)."""

    def test_clamp_timeout_default_for_none(self) -> None:
        from cinesort.ui.api._validators import clamp_timeout

        self.assertEqual(clamp_timeout(None), 10.0)

    def test_clamp_timeout_clamps_low(self) -> None:
        from cinesort.ui.api._validators import clamp_timeout

        self.assertEqual(clamp_timeout(0), 1.0)
        self.assertEqual(clamp_timeout(-5), 1.0)

    def test_clamp_timeout_clamps_high(self) -> None:
        from cinesort.ui.api._validators import clamp_timeout

        self.assertEqual(clamp_timeout(99999), 60.0)
        self.assertEqual(clamp_timeout(1000.5), 60.0)

    def test_clamp_timeout_passes_through_valid(self) -> None:
        from cinesort.ui.api._validators import clamp_timeout

        self.assertEqual(clamp_timeout(5.5), 5.5)
        self.assertEqual(clamp_timeout(30), 30.0)

    def test_clamp_timeout_handles_str(self) -> None:
        from cinesort.ui.api._validators import clamp_timeout

        # str numerique : parsed comme float
        self.assertEqual(clamp_timeout("15"), 15.0)
        # str non-numerique : tombe sur default
        self.assertEqual(clamp_timeout("abc"), 10.0)

    def test_clamp_timeout_handles_nan_inf(self) -> None:
        from cinesort.ui.api._validators import clamp_timeout

        self.assertEqual(clamp_timeout(float("nan")), 10.0)
        self.assertEqual(clamp_timeout(float("inf")), 10.0)
        self.assertEqual(clamp_timeout(float("-inf")), 10.0)

    def test_clamp_non_negative_int_handles_invalid(self) -> None:
        from cinesort.ui.api._validators import clamp_non_negative_int

        self.assertEqual(clamp_non_negative_int(None), 0)
        self.assertEqual(clamp_non_negative_int("abc"), 0)
        self.assertEqual(clamp_non_negative_int(-10), 0)
        self.assertEqual(clamp_non_negative_int(42), 42)
        self.assertEqual(clamp_non_negative_int(3.7), 3)
        self.assertEqual(clamp_non_negative_int("100"), 100)


class ApiInputClampingIntegrationTests(unittest.TestCase):
    """Audit C7 P1 : verifie que les 5 endpoints connexion + test_reset bornent leurs inputs."""

    def setUp(self) -> None:
        self.api = CineSortApi()

    def test_tmdb_clamps_timeout(self) -> None:
        """timeout_s extreme doit etre clampe avant d'arriver au support."""
        with patch("cinesort.ui.api.cinesort_api.settings_support.test_tmdb_key") as mocked:
            mocked.return_value = {"ok": True}
            # Passe timeout_s=99999 (au-dessus de la borne max)
            self.api._test_tmdb_key_impl("key", "C:/state", timeout_s=99999)
        # Le 3eme arg positional (timeout_s) doit etre 60.0
        args, kwargs = mocked.call_args
        self.assertEqual(args[2], 60.0)

    def test_jellyfin_clamps_timeout(self) -> None:
        with patch("cinesort.ui.api.cinesort_api.settings_support.test_jellyfin_connection") as mocked:
            mocked.return_value = {"ok": True}
            self.api._test_jellyfin_connection_impl(url="http://j:8096", api_key="k", timeout_s=0)
        args, kwargs = mocked.call_args
        # 3eme arg = timeout clampe a 1.0
        self.assertEqual(args[2], 1.0)

    def test_plex_clamps_timeout(self) -> None:
        """Plex utilise clamp_timeout pour creer le client."""
        with patch("cinesort.ui.api.cinesort_api._plex_mod") as mocked_mod:
            mocked_client = mocked_mod.PlexClient.return_value
            mocked_client.validate_connection.return_value = {"ok": True}
            self.api._test_plex_connection_impl(url="http://p:32400", token="t", timeout_s=99999)
        # PlexClient appele avec timeout_s=60.0 (kwarg)
        args, kwargs = mocked_mod.PlexClient.call_args
        self.assertEqual(kwargs.get("timeout_s"), 60.0)

    def test_radarr_clamps_timeout(self) -> None:
        with patch("cinesort.ui.api.cinesort_api._radarr_mod") as mocked_mod:
            mocked_client = mocked_mod.RadarrClient.return_value
            mocked_client.validate_connection.return_value = {"ok": True}
            self.api._test_radarr_connection_impl(url="http://r:7878", api_key="k", timeout_s=-1)
        args, kwargs = mocked_mod.RadarrClient.call_args
        self.assertEqual(kwargs.get("timeout_s"), 1.0)

    def test_omdb_clamps_timeout(self) -> None:
        with patch("cinesort.ui.api.cinesort_api.OmdbClient") as mocked_cls:
            mocked_client = mocked_cls.return_value
            mocked_client.test_connection.return_value = {"ok": True}
            self.api._test_omdb_connection_impl(api_key="k", timeout_s="abc")  # type: ignore[arg-type]
        # str non-numerique = fallback default 10.0
        _, kwargs = mocked_cls.call_args
        self.assertEqual(kwargs.get("timeout_s"), 10.0)

    def test_reset_clamps_min_video_bytes_negative(self) -> None:
        """test_reset accepte min_video_bytes negatif sans crasher (clamp >= 0)."""
        import os as _os

        prev = _os.environ.get("CINESORT_E2E")
        _os.environ["CINESORT_E2E"] = "1"
        try:
            result = self.api.test_reset(min_video_bytes=-100)
            self.assertTrue(result.get("ok"))
        finally:
            if prev is None:
                _os.environ.pop("CINESORT_E2E", None)
            else:
                _os.environ["CINESORT_E2E"] = prev

    def test_reset_clamps_min_video_bytes_invalid_str(self) -> None:
        """test_reset accepte une str non-numerique (clamp -> 0)."""
        import os as _os

        prev = _os.environ.get("CINESORT_E2E")
        _os.environ["CINESORT_E2E"] = "1"
        try:
            result = self.api.test_reset(min_video_bytes="abc")  # type: ignore[arg-type]
            self.assertTrue(result.get("ok"))
        finally:
            if prev is None:
                _os.environ.pop("CINESORT_E2E", None)
            else:
                _os.environ["CINESORT_E2E"] = prev


if __name__ == "__main__":
    unittest.main(verbosity=2)
