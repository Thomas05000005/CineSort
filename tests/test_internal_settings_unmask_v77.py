"""GATE AUDIT 2026-06-10 — CineSortApi._internal_settings() rend les secrets EN
CLAIR pour les consommateurs internes (Jellyfin/Plex/Radarr/SMTP), alors que
_get_settings_impl() (frontend) les masque.

Avant le fix, les rapports sync et l'email lisaient le payload masque et
envoyaient "••••••••" comme credential -> 401 systematique des qu'un secret
etait configure.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend
from cinesort.ui.api.settings_support import _SECRET_MASK


class InternalSettingsUnmaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_intset_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "settings.json").write_text(
            json.dumps(
                {
                    "jellyfin_api_key": "REAL_jf_key",
                    "plex_token": "REAL_plex_token",
                    "radarr_api_key": "REAL_radarr_key",
                    "email_smtp_password": "REAL_smtp_pwd",
                    "tmdb_api_key": "REAL_tmdb_key",
                }
            ),
            encoding="utf-8",
        )
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_get_settings_impl_masks_secrets(self) -> None:
        """Le payload frontend masque bien les secrets (comportement conserve)."""
        s = self.api._get_settings_impl()
        self.assertEqual(s["jellyfin_api_key"], _SECRET_MASK)
        self.assertEqual(s["plex_token"], _SECRET_MASK)

    def test_internal_settings_returns_clear_secrets(self) -> None:
        """GATE : _internal_settings dé-masque depuis le disque."""
        s = self.api._internal_settings()
        self.assertEqual(s["jellyfin_api_key"], "REAL_jf_key")
        self.assertEqual(s["plex_token"], "REAL_plex_token")
        self.assertEqual(s["radarr_api_key"], "REAL_radarr_key")
        self.assertEqual(s["email_smtp_password"], "REAL_smtp_pwd")
        self.assertEqual(s["tmdb_api_key"], "REAL_tmdb_key")
        # jamais le masque
        self.assertNotIn(_SECRET_MASK, s.values())

    def test_internal_settings_keeps_non_masked_value(self) -> None:
        """Si _get_settings_impl est mocke avec une cle en clair (cas tests), elle
        est conservee (la dé-masquage ne touche que les valeurs == masque)."""
        original = self.api._get_settings_impl

        def _fake():
            d = original()
            d["jellyfin_api_key"] = "injected_test_key"  # deja en clair
            return d

        self.api._get_settings_impl = _fake  # type: ignore[assignment]
        s = self.api._internal_settings()
        self.assertEqual(s["jellyfin_api_key"], "injected_test_key")


if __name__ == "__main__":
    unittest.main()
