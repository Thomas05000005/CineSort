"""V2-05 — Tests cinesort_api Plex endpoints (test_plex_connection / get_plex_libraries / get_plex_sync_report)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import cinesort.ui.api.cinesort_api as backend


class TestPlexConnection(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_plex_conn_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_url_or_token_missing_returns_message(self) -> None:
        result = self.api.integrations.test_plex_connection(url="", token="")
        self.assertFalse(result["ok"])
        self.assertIn("URL", result["message"])

    def test_only_url_returns_message(self) -> None:
        result = self.api.integrations.test_plex_connection(url="http://10.0.0.1:32400", token="")
        self.assertFalse(result["ok"])

    def test_only_token_returns_message(self) -> None:
        result = self.api.integrations.test_plex_connection(url="", token="abc")
        self.assertFalse(result["ok"])

    @patch("cinesort.infra.plex_client.PlexClient")
    def test_test_plex_connection_success(self, mock_client_cls: MagicMock) -> None:
        client = MagicMock()
        client.validate_connection.return_value = {"ok": True, "version": "1.30", "server_name": "Plex"}
        mock_client_cls.return_value = client
        result = self.api.integrations.test_plex_connection(url="http://10.0.0.1:32400", token="abc", timeout_s=10.0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["version"], "1.30")
        mock_client_cls.assert_called_once()
        args, _kwargs = mock_client_cls.call_args
        self.assertEqual(args[0], "http://10.0.0.1:32400")
        self.assertEqual(args[1], "abc")

    @patch("cinesort.infra.plex_client.PlexClient")
    def test_timeout_clamped_high(self, mock_client_cls: MagicMock) -> None:
        client = MagicMock()
        client.validate_connection.return_value = {"ok": True}
        mock_client_cls.return_value = client
        self.api.integrations.test_plex_connection(url="http://x", token="t", timeout_s=999.0)
        kwargs = mock_client_cls.call_args.kwargs
        self.assertLessEqual(kwargs.get("timeout_s", 0), 30)

    @patch("cinesort.infra.plex_client.PlexClient")
    def test_timeout_clamped_low(self, mock_client_cls: MagicMock) -> None:
        client = MagicMock()
        client.validate_connection.return_value = {"ok": True}
        mock_client_cls.return_value = client
        self.api.integrations.test_plex_connection(url="http://x", token="t", timeout_s=0.0)
        kwargs = mock_client_cls.call_args.kwargs
        self.assertGreaterEqual(kwargs.get("timeout_s", 0), 1)


class TestGetPlexLibraries(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_plex_libs_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_url_no_token_no_settings(self) -> None:
        result = self.api.integrations.get_plex_libraries(url="", token="")
        self.assertFalse(result["ok"])
        self.assertIn("requis", result["message"])

    @patch("cinesort.infra.plex_client.PlexClient")
    def test_get_libraries_success(self, mock_client_cls: MagicMock) -> None:
        client = MagicMock()
        client.get_libraries.return_value = [{"id": "1", "name": "Films", "type": "movie"}]
        mock_client_cls.return_value = client
        result = self.api.integrations.get_plex_libraries(url="http://10.0.0.1:32400", token="abc")
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["libraries"]), 1)
        self.assertEqual(result["libraries"][0]["name"], "Films")

    @patch("cinesort.infra.plex_client.PlexClient")
    def test_get_libraries_plex_error(self, mock_client_cls: MagicMock) -> None:
        from cinesort.infra.plex_client import PlexError

        client = MagicMock()
        client.get_libraries.side_effect = PlexError("server unreachable")
        mock_client_cls.return_value = client
        result = self.api.integrations.get_plex_libraries(url="http://x", token="t")
        self.assertFalse(result["ok"])
        self.assertIn("server unreachable", result["message"])

    @patch.object(backend.CineSortApi, "_get_settings_impl")
    @patch("cinesort.infra.plex_client.PlexClient")
    def test_fallback_settings(self, mock_client_cls: MagicMock, mock_get_settings: MagicMock) -> None:
        # Mock settings : retourne URL/token configurés
        mock_get_settings.return_value = {
            "plex_url": "http://settings.local:32400",
            "plex_token": "settings_token",
        }
        client = MagicMock()
        client.get_libraries.return_value = []
        mock_client_cls.return_value = client
        result = self.api.integrations.get_plex_libraries(url="", token="")
        self.assertTrue(result["ok"])
        args = mock_client_cls.call_args.args
        self.assertEqual(args[0], "http://settings.local:32400")
        self.assertEqual(args[1], "settings_token")


class TestGetPlexSyncReport(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_plex_sync_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch.object(backend.CineSortApi, "_get_settings_impl")
    def test_plex_disabled(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"plex_enabled": False}
        result = self.api.integrations.get_plex_sync_report()
        self.assertFalse(result["ok"])
        self.assertIn("Plex non configure", result["message"])

    @patch.object(backend.CineSortApi, "_get_settings_impl")
    def test_plex_enabled_but_url_missing(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {
            "plex_enabled": True,
            "plex_url": "",
            "plex_token": "abc",
            "plex_library_id": "1",
        }
        result = self.api.integrations.get_plex_sync_report()
        self.assertFalse(result["ok"])
        self.assertIn("manquant", result["message"])

    @patch.object(backend.CineSortApi, "_get_settings_impl")
    def test_plex_enabled_but_library_id_missing(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {
            "plex_enabled": True,
            "plex_url": "http://x",
            "plex_token": "abc",
            "plex_library_id": "",
        }
        result = self.api.integrations.get_plex_sync_report()
        self.assertFalse(result["ok"])
        self.assertIn("manquant", result["message"])

    @patch.object(backend.CineSortApi, "_get_settings_impl")
    def test_plex_enabled_no_run_done(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {
            "plex_enabled": True,
            "plex_url": "http://x",
            "plex_token": "abc",
            "plex_library_id": "1",
        }
        result = self.api.integrations.get_plex_sync_report()
        self.assertFalse(result["ok"])
        self.assertIn("Aucun run", result["message"])

    @patch.object(backend.CineSortApi, "_get_settings_impl")
    @patch("cinesort.infra.plex_client.PlexClient")
    def test_plex_connection_error_returns_message(
        self, mock_client_cls: MagicMock, mock_get_settings: MagicMock
    ) -> None:
        from cinesort.infra.plex_client import PlexError

        mock_get_settings.return_value = {
            "plex_enabled": True,
            "plex_url": "http://x",
            "plex_token": "abc",
            "plex_library_id": "1",
        }
        # Forge un run terminé mais PlexClient échoue
        client = MagicMock()
        client.get_movies.side_effect = PlexError("network down")
        mock_client_cls.return_value = client

        # Crée une fausse runs_summary entry → on patch le store
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.get_runs_summary.return_value = [{"run_id": "r1", "status": "DONE"}]
            mock_infra.return_value = (store, MagicMock())

            # Crée un fichier plan.jsonl factice (vide → renverra "Aucun film")
            (self.state_dir / "runs" / "r1").mkdir(parents=True)
            (self.state_dir / "runs" / "r1" / "plan.jsonl").write_text("", encoding="utf-8")

            result = self.api.integrations.get_plex_sync_report(run_id="r1")
            self.assertFalse(result["ok"])
            self.assertIn("Aucun film", result["message"])


if __name__ == "__main__":
    unittest.main()
