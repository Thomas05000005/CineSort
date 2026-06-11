"""GATE AUDIT 2026-06-11 (R1b) — les secrets ne sont PAS persistes en clair dans
runs.config_json.

Depuis le fix d'hydratation, le dict settings contient les vraies cles
dechiffrees DPAPI. _scrub_secrets_for_persist masque ces secrets dans la copie
passee a start_job(config=...) (le scan, lui, lit les vraies cles via job_fn).
"""

from __future__ import annotations

import inspect
import unittest

from cinesort.ui.api import run_flow_support
from cinesort.ui.api.run_flow_support import _scrub_secrets_for_persist
from cinesort.ui.api.settings_support import _SECRET_FIELDS, _SECRET_MASK


class ScrubSecretsForPersistTests(unittest.TestCase):
    def test_real_secrets_masked(self) -> None:
        settings = {
            "tmdb_api_key": "REAL_tmdb", "omdb_api_key": "REAL_omdb",
            "jellyfin_api_key": "REAL_jf", "plex_token": "REAL_plex",
            "radarr_api_key": "REAL_radarr", "email_smtp_password": "REAL_pwd",
            "rest_api_token": "REAL_rest", "library_path": "C:/Films",
        }
        out = _scrub_secrets_for_persist(settings)
        for f in _SECRET_FIELDS:
            self.assertEqual(out.get(f), _SECRET_MASK, f"{f} doit etre masque")
        # aucune vraie cle ne subsiste
        for leaked in ("REAL_tmdb", "REAL_omdb", "REAL_jf", "REAL_plex", "REAL_radarr", "REAL_pwd", "REAL_rest"):
            self.assertNotIn(leaked, out.values())
        # les non-secrets sont preserves
        self.assertEqual(out["library_path"], "C:/Films")

    def test_empty_secret_not_masked(self) -> None:
        out = _scrub_secrets_for_persist({"tmdb_api_key": "", "library_path": "X"})
        self.assertEqual(out["tmdb_api_key"], "")  # vide -> pas de masque parasite

    def test_does_not_mutate_input(self) -> None:
        settings = {"tmdb_api_key": "REAL"}
        _scrub_secrets_for_persist(settings)
        self.assertEqual(settings["tmdb_api_key"], "REAL", "l'entree ne doit pas etre mutee")

    def test_non_dict_returns_empty(self) -> None:
        self.assertEqual(_scrub_secrets_for_persist(None), {})

    def test_call_site_uses_scrub(self) -> None:
        # Garde-fou de cablage : _start_plan_impl doit scrubber le config persiste.
        src = inspect.getsource(run_flow_support._start_plan_impl)
        self.assertIn("_scrub_secrets_for_persist", src,
                      "le config de start_job doit passer par _scrub_secrets_for_persist")
        self.assertNotIn("config=dict(settings or {})", src,
                         "l'ancien config en clair ne doit plus exister")


if __name__ == "__main__":
    unittest.main()
