"""Tests des facades CineSortApi (issue #84 PR 1 pilote).

Cf docs/internal/REFACTOR_PLAN_84.md.

PR 1 verifie :
- Les 5 facades sont instanciees comme attributs de CineSortApi
- Les types sont corrects
- 1 methode pilote par facade fonctionne via la nouvelle voie
- La symetrie ancienne/nouvelle voie est preservee (backward-compat)
"""

from __future__ import annotations

import unittest

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
