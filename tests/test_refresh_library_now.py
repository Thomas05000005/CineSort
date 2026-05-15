"""Tests pour les endpoints refresh_jellyfin_library_now / refresh_plex_library_now (#92 #1)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.ui.api.apply_support import (
    refresh_jellyfin_library_now,
    refresh_plex_library_now,
)
from cinesort.ui.api.cinesort_api import CineSortApi


def _write_settings(state_dir: Path, **fields) -> None:
    """Helper : ecrit un settings.json minimal."""
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "settings.json").write_text(json.dumps(fields), encoding="utf-8")


class RefreshJellyfinNowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_refresh_jf_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp

    def test_returns_error_when_jellyfin_disabled(self) -> None:
        _write_settings(self._tmp, jellyfin_enabled=False)
        r = refresh_jellyfin_library_now(self.api)
        self.assertFalse(r["ok"])
        self.assertIn("non configure", r["message"].lower())

    def test_returns_error_when_url_or_key_missing(self) -> None:
        _write_settings(self._tmp, jellyfin_enabled=True, jellyfin_url="", jellyfin_api_key="")
        r = refresh_jellyfin_library_now(self.api)
        self.assertFalse(r["ok"])

    def test_calls_client_refresh_when_configured(self) -> None:
        _write_settings(
            self._tmp,
            jellyfin_enabled=True,
            jellyfin_url="http://localhost:8096",
            jellyfin_api_key="testkey",
        )
        with mock.patch("cinesort.ui.api.apply_support._make_jellyfin_client") as mk_client:
            client_mock = mock.MagicMock()
            mk_client.return_value = client_mock
            r = refresh_jellyfin_library_now(self.api)
        self.assertTrue(r["ok"])
        client_mock.refresh_library.assert_called_once()

    def test_returns_error_on_client_exception(self) -> None:
        from cinesort.infra.integration_errors import IntegrationError

        _write_settings(
            self._tmp,
            jellyfin_enabled=True,
            jellyfin_url="http://localhost:8096",
            jellyfin_api_key="testkey",
        )
        with mock.patch("cinesort.ui.api.apply_support._make_jellyfin_client") as mk_client:
            client_mock = mock.MagicMock()
            client_mock.refresh_library.side_effect = IntegrationError("server down")
            mk_client.return_value = client_mock
            r = refresh_jellyfin_library_now(self.api)
        self.assertFalse(r["ok"])
        self.assertIn("Jellyfin", r["message"])


class RefreshPlexNowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_refresh_plex_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp

    def test_returns_error_when_plex_disabled(self) -> None:
        _write_settings(self._tmp, plex_enabled=False)
        r = refresh_plex_library_now(self.api)
        self.assertFalse(r["ok"])
        self.assertIn("non configure", r["message"].lower())

    def test_returns_error_when_missing_fields(self) -> None:
        _write_settings(self._tmp, plex_enabled=True, plex_url="", plex_token="", plex_library_id="")
        r = refresh_plex_library_now(self.api)
        self.assertFalse(r["ok"])
        self.assertIn("incomplet", r["message"].lower())

    def test_calls_client_refresh_when_configured(self) -> None:
        _write_settings(
            self._tmp,
            plex_enabled=True,
            plex_url="http://localhost:32400",
            plex_token="testtok",
            plex_library_id="42",
        )
        with mock.patch("cinesort.infra.plex_client.PlexClient") as PlexClientCls:
            client_mock = mock.MagicMock()
            PlexClientCls.return_value = client_mock
            r = refresh_plex_library_now(self.api)
        self.assertTrue(r["ok"])
        client_mock.refresh_library.assert_called_once_with("42")


class RefreshFacadeIntegrationTests(unittest.TestCase):
    """Verifie que les methodes sont exposees via IntegrationsFacade."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_refresh_facade_"))
        self.api = CineSortApi()
        self.api._state_dir = self._tmp

    def test_jellyfin_method_on_facade(self) -> None:
        _write_settings(self._tmp, jellyfin_enabled=False)
        r = self.api.integrations.refresh_jellyfin_library_now()
        self.assertFalse(r["ok"])

    def test_plex_method_on_facade(self) -> None:
        _write_settings(self._tmp, plex_enabled=False)
        r = self.api.integrations.refresh_plex_library_now()
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
