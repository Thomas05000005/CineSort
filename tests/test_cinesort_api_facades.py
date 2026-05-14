"""Tests des facades CineSortApi (issue #84 PR 1 pilote + PR 2 RunFacade).

Cf docs/internal/REFACTOR_PLAN_84.md.

PR 1 verifie :
- Les 5 facades sont instanciees comme attributs de CineSortApi
- Les types sont corrects
- 1 methode pilote par facade fonctionne via la nouvelle voie
- La symetrie ancienne/nouvelle voie est preservee (backward-compat)

PR 2 ajoute :
- Les 7 methodes du bounded context Run sont exposees sur RunFacade
- Chaque methode delegue correctement vers CineSortApi
- Backward-compat : les anciennes methodes directes fonctionnent toujours
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
        old = self.api.get_settings()
        new = self.api.settings.get_settings()
        # Memes cles (le contenu peut varier si timing/ts mais structure identique)
        self.assertEqual(set(old.keys()), set(new.keys()))

    def test_quality_get_quality_profile_delegates(self) -> None:
        old = self.api.get_quality_profile()
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

    Frontend JS et REST API continuent d'appeler api.start_plan(...) etc.
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
        old = self.api.get_status("run_inexistant_xyz")
        new = self.api.run.get_status("run_inexistant_xyz")
        # Les deux doivent etre des dicts avec une cle "ok"
        self.assertIsInstance(old, dict)
        self.assertIsInstance(new, dict)
        self.assertEqual(set(old.keys()), set(new.keys()))


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
        result = self.api.get_settings()
        self.assertIsInstance(result, dict)
        # Sanity check : contient au moins quelques cles attendues
        self.assertIn("root", result)
        self.assertIn("state_dir", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
