"""Tests unitaires pour JellyfinClient (mocks requests)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from cinesort.infra.jellyfin_client import (
    JellyfinClient,
    JellyfinError,
    _build_auth_header,
    _normalize_url,
)


class TestNormalizeUrl(unittest.TestCase):
    """Tests pour _normalize_url."""

    def test_strip_trailing_slash(self):
        self.assertEqual(_normalize_url("http://localhost:8096/"), "http://localhost:8096")

    def test_add_http_prefix(self):
        self.assertEqual(_normalize_url("192.168.1.10:8096"), "http://192.168.1.10:8096")

    def test_keep_https(self):
        self.assertEqual(_normalize_url("https://jellyfin.example.com"), "https://jellyfin.example.com")

    def test_empty(self):
        self.assertEqual(_normalize_url(""), "")

    def test_strip_whitespace(self):
        self.assertEqual(_normalize_url("  http://host:8096  "), "http://host:8096")


class TestBuildAuthHeader(unittest.TestCase):
    """Tests pour _build_auth_header."""

    def test_contains_token(self):
        header = _build_auth_header("my-key-123")
        self.assertIn('Token="my-key-123"', header)
        self.assertIn("MediaBrowser", header)


class TestJellyfinClientInit(unittest.TestCase):
    """Tests d'initialisation."""

    def test_timeout_clamped_min(self):
        c = JellyfinClient("http://host", "key", timeout_s=0.1)
        self.assertEqual(c.timeout_s, 1.0)

    def test_timeout_clamped_max(self):
        c = JellyfinClient("http://host", "key", timeout_s=999)
        self.assertEqual(c.timeout_s, 60.0)

    def test_url_normalized(self):
        c = JellyfinClient("http://host:8096/", "key")
        self.assertEqual(c.base_url, "http://host:8096")


class TestValidateConnection(unittest.TestCase):
    """Tests pour validate_connection."""

    def test_missing_url(self):
        c = JellyfinClient("", "key")
        result = c.validate_connection()
        self.assertFalse(result["ok"])
        self.assertIn("URL", result["error"])

    def test_missing_api_key(self):
        c = JellyfinClient("http://host", "")
        result = c.validate_connection()
        self.assertFalse(result["ok"])
        self.assertIn("Clé API", result["error"])

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._get")
    def test_success(self, mock_get):
        """validate_connection appelle /System/Info/Public puis /Users."""
        server_resp = MagicMock()
        server_resp.json.return_value = {"ServerName": "Mon Serveur", "Version": "10.9.0"}
        users_resp = MagicMock()
        users_resp.json.return_value = [
            {
                "Id": "user-uuid-123",
                "Name": "admin",
                "Policy": {"IsAdministrator": True},
            },
        ]
        mock_get.side_effect = [server_resp, users_resp]

        c = JellyfinClient("http://host:8096", "valid-key")
        result = c.validate_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["server_name"], "Mon Serveur")
        self.assertEqual(result["version"], "10.9.0")
        self.assertEqual(result["user_id"], "user-uuid-123")
        self.assertEqual(result["user_name"], "admin")
        self.assertTrue(result["is_admin"])
        # Verifier que /Users est appele (pas /Users/Me)
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[1][0][0], "/Users")

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._get")
    def test_success_picks_admin_from_list(self, mock_get):
        """Si plusieurs users, validate_connection prend le premier admin."""
        server_resp = MagicMock()
        server_resp.json.return_value = {"ServerName": "Srv", "Version": "10.9"}
        users_resp = MagicMock()
        users_resp.json.return_value = [
            {"Id": "u1", "Name": "guest", "Policy": {"IsAdministrator": False}},
            {"Id": "u2", "Name": "admin", "Policy": {"IsAdministrator": True}},
        ]
        mock_get.side_effect = [server_resp, users_resp]

        c = JellyfinClient("http://host:8096", "key")
        result = c.validate_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["user_id"], "u2")
        self.assertEqual(result["user_name"], "admin")
        self.assertTrue(result["is_admin"])

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._get")
    def test_success_no_admin_falls_back_first(self, mock_get):
        """Si aucun admin, prend le premier utilisateur."""
        server_resp = MagicMock()
        server_resp.json.return_value = {"ServerName": "Srv", "Version": "10.9"}
        users_resp = MagicMock()
        users_resp.json.return_value = [
            {"Id": "u1", "Name": "viewer", "Policy": {"IsAdministrator": False}},
        ]
        mock_get.side_effect = [server_resp, users_resp]

        c = JellyfinClient("http://host:8096", "key")
        result = c.validate_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["user_id"], "u1")
        self.assertFalse(result["is_admin"])

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._get")
    def test_empty_users_list(self, mock_get):
        """Si GET /Users retourne une liste vide, erreur explicite."""
        server_resp = MagicMock()
        server_resp.json.return_value = {"ServerName": "Srv", "Version": "10.9"}
        users_resp = MagicMock()
        users_resp.json.return_value = []
        mock_get.side_effect = [server_resp, users_resp]

        c = JellyfinClient("http://host:8096", "key")
        result = c.validate_connection()
        self.assertFalse(result["ok"])
        self.assertIn("Aucun utilisateur", result["error"])

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._get")
    def test_server_unreachable(self, mock_get):
        mock_get.side_effect = JellyfinError("Connexion impossible")
        c = JellyfinClient("http://host:8096", "key")
        result = c.validate_connection()
        self.assertFalse(result["ok"])
        self.assertIn("Connexion impossible", result["error"])

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._get")
    def test_auth_failure(self, mock_get):
        server_resp = MagicMock()
        server_resp.json.return_value = {"ServerName": "Srv", "Version": "10.9"}
        mock_get.side_effect = [server_resp, JellyfinError("Erreur HTTP 401")]
        c = JellyfinClient("http://host:8096", "bad-key")
        result = c.validate_connection()
        self.assertFalse(result["ok"])
        self.assertEqual(result["server_name"], "Srv")
        self.assertIn("401", result["error"])


class TestGetLibraries(unittest.TestCase):
    """Tests pour get_libraries."""

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._get")
    def test_returns_libraries(self, mock_get):
        resp = MagicMock()
        resp.json.return_value = {
            "Items": [
                {"Id": "lib-1", "Name": "Films", "CollectionType": "movies"},
                {"Id": "lib-2", "Name": "Séries", "CollectionType": "tvshows"},
            ]
        }
        mock_get.return_value = resp
        c = JellyfinClient("http://host", "key")
        libs = c.get_libraries("user-id")
        self.assertEqual(len(libs), 2)
        self.assertEqual(libs[0]["name"], "Films")
        self.assertEqual(libs[1]["collection_type"], "tvshows")

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._get")
    def test_error_propagates(self, mock_get):
        mock_get.side_effect = JellyfinError("Erreur HTTP 403")
        c = JellyfinClient("http://host", "key")
        with self.assertRaises(JellyfinError):
            c.get_libraries("user-id")


class TestGetMoviesCount(unittest.TestCase):
    """Tests pour get_movies_count."""

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._get")
    def test_returns_count(self, mock_get):
        resp = MagicMock()
        resp.json.return_value = {"TotalRecordCount": 142, "Items": []}
        mock_get.return_value = resp
        c = JellyfinClient("http://host", "key")
        self.assertEqual(c.get_movies_count("user-id"), 142)


class TestRefreshLibrary(unittest.TestCase):
    """Tests pour refresh_library."""

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._post")
    def test_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        c = JellyfinClient("http://host", "key")
        self.assertTrue(c.refresh_library())

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._post")
    def test_failure_raises(self, mock_post):
        mock_post.side_effect = JellyfinError("Erreur HTTP 401")
        c = JellyfinClient("http://host", "key")
        with self.assertRaises(JellyfinError):
            c.refresh_library()


class TestSettingsJellyfinIntegration(unittest.TestCase):
    """Tests pour test_jellyfin_connection via settings_support."""

    def test_test_connection_missing_url(self):
        from cinesort.ui.api.settings_support import test_jellyfin_connection

        result = test_jellyfin_connection("", "key123")
        self.assertFalse(result["ok"])
        self.assertIn("URL", result["message"])

    def test_test_connection_missing_key(self):
        from cinesort.ui.api.settings_support import test_jellyfin_connection

        result = test_jellyfin_connection("http://host", "")
        self.assertFalse(result["ok"])
        self.assertIn("Clé API", result["message"])

    def test_test_connection_success(self):
        from cinesort.ui.api.settings_support import test_jellyfin_connection

        mock_client = MagicMock()
        mock_client.validate_connection.return_value = {
            "ok": True,
            "server_name": "TestSrv",
            "version": "10.9.0",
            "user_id": "uid",
            "user_name": "admin",
            "is_admin": True,
        }
        mock_client.get_libraries.return_value = [
            {"id": "1", "name": "Films", "collection_type": "movies"},
        ]
        mock_client.get_movies_count.return_value = 42
        mock_cls = MagicMock(return_value=mock_client)

        result = test_jellyfin_connection(
            "http://host:8096",
            "valid-key",
            jellyfin_client_cls=mock_cls,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["server_name"], "TestSrv")
        self.assertEqual(result["movies_count"], 42)
        self.assertEqual(len(result["libraries"]), 1)

    def test_test_connection_failure(self):
        from cinesort.ui.api.settings_support import test_jellyfin_connection

        mock_client = MagicMock()
        mock_client.validate_connection.return_value = {
            "ok": False,
            "error": "Connexion impossible",
        }
        mock_cls = MagicMock(return_value=mock_client)
        result = test_jellyfin_connection(
            "http://host:8096",
            "key",
            jellyfin_client_cls=mock_cls,
        )
        self.assertFalse(result["ok"])
        self.assertIn("Connexion impossible", result["message"])


class TestGetAllMovies(unittest.TestCase):
    """Tests pour get_all_movies (Phase 2)."""

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._get")
    def test_returns_movies_with_watched_status(self, mock_get):
        resp = MagicMock()
        resp.json.return_value = {
            "Items": [
                {
                    "Id": "m1",
                    "Name": "Inception",
                    "Path": r"C:\Films\Inception (2010)\Inception.mkv",
                    "UserData": {"Played": True, "PlayCount": 3, "LastPlayedDate": "2025-12-01"},
                },
                {
                    "Id": "m2",
                    "Name": "Matrix",
                    "Path": r"C:\Films\Matrix (1999)\Matrix.mkv",
                    "UserData": {"Played": False, "PlayCount": 0, "LastPlayedDate": ""},
                },
            ]
        }
        mock_get.return_value = resp
        c = JellyfinClient("http://host", "key")
        movies = c.get_all_movies("user-id")
        self.assertEqual(len(movies), 2)
        self.assertTrue(movies[0]["played"])
        self.assertEqual(movies[0]["play_count"], 3)
        self.assertFalse(movies[1]["played"])

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._get")
    def test_error_propagates(self, mock_get):
        mock_get.side_effect = JellyfinError("Erreur HTTP 500")
        c = JellyfinClient("http://host", "key")
        with self.assertRaises(JellyfinError):
            c.get_all_movies("user-id")

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._get")
    def test_empty_items(self, mock_get):
        resp = MagicMock()
        resp.json.return_value = {"Items": []}
        mock_get.return_value = resp
        c = JellyfinClient("http://host", "key")
        movies = c.get_all_movies("user-id")
        self.assertEqual(movies, [])


class TestMarkPlayed(unittest.TestCase):
    """Tests pour mark_played (Phase 2)."""

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._post")
    def test_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        c = JellyfinClient("http://host", "key")
        self.assertTrue(c.mark_played("uid", "item-1"))

    @patch("cinesort.infra.jellyfin_client.JellyfinClient._post")
    def test_failure_returns_false(self, mock_post):
        mock_post.side_effect = JellyfinError("HTTP 500")
        c = JellyfinClient("http://host", "key")
        self.assertFalse(c.mark_played("uid", "item-1"))


class TestMarkUnplayed(unittest.TestCase):
    """Tests pour mark_unplayed (Phase 2)."""

    def test_success(self):
        c = JellyfinClient("http://host", "key")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        c._session = MagicMock()
        c._session.delete.return_value = mock_resp
        self.assertTrue(c.mark_unplayed("uid", "item-1"))

    def test_failure_returns_false(self):
        import requests

        c = JellyfinClient("http://host", "key")
        c._session = MagicMock()
        c._session.delete.side_effect = requests.ConnectionError("refused")
        self.assertFalse(c.mark_unplayed("uid", "item-1"))


class TestTriggerJellyfinRefresh(unittest.TestCase):
    """Tests pour _trigger_jellyfin_refresh dans apply_support."""

    @patch("cinesort.ui.api.apply_support.read_settings")
    def test_skipped_in_dry_run(self, mock_read):
        from cinesort.ui.api.apply_support import _trigger_jellyfin_refresh

        api = MagicMock()
        log_fn = MagicMock()
        _trigger_jellyfin_refresh(api, log_fn, dry_run=True)
        mock_read.assert_not_called()

    @patch("cinesort.ui.api.apply_support.read_settings")
    def test_skipped_when_disabled(self, mock_read):
        from cinesort.ui.api.apply_support import _trigger_jellyfin_refresh

        mock_read.return_value = {"jellyfin_enabled": False}
        api = MagicMock()
        log_fn = MagicMock()
        _trigger_jellyfin_refresh(api, log_fn, dry_run=False)
        log_fn.assert_not_called()

    @patch("cinesort.infra.jellyfin_client.JellyfinClient.refresh_library")
    @patch("cinesort.ui.api.apply_support.read_settings")
    def test_triggered_when_enabled(self, mock_read, mock_refresh):
        from cinesort.ui.api.apply_support import _trigger_jellyfin_refresh

        mock_read.return_value = {
            "jellyfin_enabled": True,
            "jellyfin_refresh_on_apply": True,
            "jellyfin_url": "http://host:8096",
            "jellyfin_api_key": "key123",
            "jellyfin_timeout_s": 5.0,
        }
        mock_refresh.return_value = True
        api = MagicMock()
        log_fn = MagicMock()
        _trigger_jellyfin_refresh(api, log_fn, dry_run=False)
        mock_refresh.assert_called_once()
        log_fn.assert_called()
        # Verify the success log message
        args = log_fn.call_args_list[-1][0]
        self.assertEqual(args[0], "INFO")
        self.assertIn("Jellyfin", args[1])

    @patch("cinesort.infra.jellyfin_client.JellyfinClient.refresh_library")
    @patch("cinesort.ui.api.apply_support.read_settings")
    def test_failure_logs_warning(self, mock_read, mock_refresh):
        from cinesort.ui.api.apply_support import _trigger_jellyfin_refresh

        mock_read.return_value = {
            "jellyfin_enabled": True,
            "jellyfin_refresh_on_apply": True,
            "jellyfin_url": "http://host:8096",
            "jellyfin_api_key": "key123",
            "jellyfin_timeout_s": 5.0,
        }
        mock_refresh.side_effect = JellyfinError("timeout")
        api = MagicMock()
        log_fn = MagicMock()
        # Should not crash
        _trigger_jellyfin_refresh(api, log_fn, dry_run=False)
        args = log_fn.call_args_list[-1][0]
        self.assertEqual(args[0], "WARN")


if __name__ == "__main__":
    unittest.main()
