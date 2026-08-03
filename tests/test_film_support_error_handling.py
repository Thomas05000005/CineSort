"""Tests Vague F Fix 3 (v1.5.3) — gestion d'erreurs film_support.get_film_full.

Verifie que get_film_full ne leve JAMAIS d'exception au handler REST :
- run_id obsolete / inexistant -> retour propre {ok: False, ...}
- exception dans la facade api.run.get_plan / store -> contrat {ok: False, error,
  user_message} (pas de HTTP 500)
- message UX (user_message) present et exploitable par le frontend

Fix audit 2026-05-25 (v1.5.3) Vague F : eviter la modale "Serveur indisponible
(HTTP 500)" au clic sur un film.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock


def _make_api_raising() -> MagicMock:
    """API mock qui leve une exception non-geree dans la chaine d'acces store.

    Reproduit le cas Vague F : settings.get_settings() leve -> wrap global
    doit intercepter et retourner un contrat d'erreur.
    """
    api = MagicMock()
    api.settings.get_settings.side_effect = RuntimeError("database is locked")
    return api


def _make_api_obsolete_run() -> MagicMock:
    """API mock dont run.get_plan() leve (run_id obsolete / DB inaccessible)."""
    api = MagicMock()
    api.settings.get_settings.return_value = {"state_dir": None, "tmdb_api_key": ""}
    # _resolve_run_id voit run_id non vide -> renvoie tel quel sans toucher au store.
    # _find_plan_row appelle api.run.get_plan -> mais celui-ci attrape deja les
    # exceptions tabulaires ; on force donc une exception NON listee dans le
    # except etroit pour faire remonter au wrap global.
    api.run.get_plan.side_effect = MemoryError("simulated infra blow up")
    return api


class GetFilmFullErrorHandlingTests(unittest.TestCase):
    """Vague F Fix 3 : wrap global try/except dans get_film_full."""

    def test_returns_error_contract_when_settings_raises(self) -> None:
        from cinesort.ui.api import film_support

        api = _make_api_raising()

        # Avec run_id=None, _resolve_run_id va tomber sur api.settings... qui leve.
        # _resolve_run_id attrape (OSError, AttributeError, KeyError, TypeError,
        # ValueError) mais PAS RuntimeError -> remonte au wrap global.
        res = film_support.get_film_full(api, None, "row42")

        self.assertIsInstance(res, dict)
        self.assertFalse(res.get("ok"))
        # Soit l'erreur a ete attrapee par le wrap global (film_load_failed),
        # soit par _resolve_run_id qui retourne None -> "Aucun run disponible"
        # (categorie state). Les deux sont des retours propres, pas un HTTP 500.
        self.assertTrue(("error" in res) or ("message" in res))

    def test_returns_film_load_failed_when_get_plan_raises(self) -> None:
        from cinesort.ui.api import film_support

        api = _make_api_obsolete_run()
        # _find_plan_row a un except etroit (OSError, AttributeError, KeyError,
        # TypeError, ValueError). MemoryError n'est PAS dans la liste -> remonte
        # au wrap global de get_film_full.
        res = film_support.get_film_full(api, "run_obsolete", "row42")

        self.assertIsInstance(res, dict)
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error"), "film_load_failed")
        self.assertIn("user_message", res)
        self.assertIsInstance(res["user_message"], str)
        self.assertTrue(len(res["user_message"]) > 0)
        # Le message technique est preserve pour le log/debug
        self.assertIn("message", res)
        self.assertIn("simulated infra blow up", res["message"])

    def test_no_run_returns_clean_error(self) -> None:
        """run_id None + aucun run en base -> retour propre 'Aucun run disponible'."""
        from cinesort.ui.api import film_support

        api = MagicMock()
        api.settings.get_settings.return_value = {"state_dir": None, "tmdb_api_key": ""}
        # _get_or_create_infra renvoie un store dont list_runs() est vide
        store = MagicMock()
        store.run.list_runs.return_value = []
        api._get_or_create_infra.return_value = (store, None)

        res = film_support.get_film_full(api, None, "row42")
        self.assertIsInstance(res, dict)
        self.assertFalse(res.get("ok"))
        # Doit etre un retour structure (message OU error present),
        # pas une exception qui remonte vers le handler REST
        self.assertTrue(("error" in res) or ("message" in res))


if __name__ == "__main__":
    unittest.main()
