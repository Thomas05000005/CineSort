"""Tests Vague F (v1.5.3) - endpoints critiques + alias collection_folder.

Verifie 3 fixes apportes par Vague F :

1. `run_flow_support.get_status` : wrap global try/except -> contrat propre
   `{ok: False, error: "run_status_unavailable", ...}` au lieu d'un HTTP 500
   visible en polling depuis l'UI Traitement.

2. `history_support.cancel_run` : wrap global try/except -> contrat propre
   `{ok: False, error: "cancel_run_failed", ...}` au lieu d'un HTTP 500 sur
   action destructive (cancel d'un run en cours).

3. `settings_support._save_section_cleanup` : alias UI `collection_folder` ->
   backend `collection_folder_name`. Avant le fix, l'UI envoyait
   `collection_folder` qui etait silencieusement ignore, et le backend
   ecrasait la valeur par le defaut `_Collection`.

Fix audit 2026-05-25 (v1.5.3) Vague F.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock


def _make_api_raising_get_run(exc: Exception) -> MagicMock:
    """API mock dont `_get_run` leve une exception non-geree."""
    api = MagicMock()
    api._is_valid_run_id.return_value = True
    api._get_run.side_effect = exc
    return api


class GetStatusErrorHandlingTests(unittest.TestCase):
    """Vague F Fix 1 : wrap global try/except dans get_status."""

    def test_get_status_handles_exception(self) -> None:
        from cinesort.ui.api import run_flow_support

        api = _make_api_raising_get_run(RuntimeError("database is locked"))

        res = run_flow_support.get_status(api, "run_abc_123")

        self.assertIsInstance(res, dict)
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "run_status_unavailable")
        # Le contrat doit aussi exposer un message utilisateur exploitable.
        self.assertIn("user_message", res)
        self.assertTrue(res["user_message"])
        # Le message technique brut est conserve pour le debug cote serveur.
        self.assertIn("database is locked", res.get("message", ""))


class CancelRunErrorHandlingTests(unittest.TestCase):
    """Vague F Fix 2 : wrap global try/except dans cancel_run."""

    def test_cancel_run_handles_exception(self) -> None:
        from cinesort.ui.api import history_support

        api = _make_api_raising_get_run(MemoryError("infra blow up"))

        res = history_support.cancel_run(api, "run_abc_123")

        self.assertIsInstance(res, dict)
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "cancel_run_failed")
        self.assertIn("user_message", res)
        self.assertTrue(res["user_message"])
        self.assertIn("infra blow up", res.get("message", ""))


class CollectionFolderAliasTests(unittest.TestCase):
    """Vague F Fix 3 : alias UI collection_folder -> collection_folder_name."""

    def _save_cleanup(self, payload: dict) -> dict:
        from cinesort.ui.api.settings_support import _save_section_cleanup

        return _save_section_cleanup(
            payload,
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vides",
            default_residual_cleanup_folder_name="_Residuels",
        )

    def test_collection_folder_alias_persists(self) -> None:
        """L'UI envoie `collection_folder` -> backend persiste sous
        `collection_folder_name` (et non plus la valeur defaut)."""
        result = self._save_cleanup({"collection_folder": "MesFilms"})

        # Avant le fix : "_Collection" (defaut, valeur UI ignoree silencieusement).
        # Apres le fix : "MesFilms" est preservee.
        self.assertEqual(result["collection_folder_name"], "MesFilms")

    def test_collection_folder_name_still_works(self) -> None:
        """Retrocompat : si l'UI envoie la cle backend, elle reste prioritaire."""
        result = self._save_cleanup({"collection_folder_name": "FilmsBackend"})
        self.assertEqual(result["collection_folder_name"], "FilmsBackend")

    def test_collection_folder_alias_wins_when_both_provided(self) -> None:
        """Quand les deux cles sont presentes, la cle UI prime (cas reel : la
        meme payload poussee depuis le formulaire UI utilisera la nouvelle cle)."""
        result = self._save_cleanup(
            {"collection_folder": "UIValue", "collection_folder_name": "BackendValue"}
        )
        self.assertEqual(result["collection_folder_name"], "UIValue")

    def test_default_when_neither_provided(self) -> None:
        """Aucune des deux cles -> defaut applique."""
        result = self._save_cleanup({})
        self.assertEqual(result["collection_folder_name"], "_Collection")


if __name__ == "__main__":
    unittest.main()
