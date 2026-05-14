"""V2-05 — Tests cinesort_api Radarr endpoints (test_radarr_connection / get_radarr_status / request_radarr_upgrade)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import cinesort.ui.api.cinesort_api as backend


class TestRadarrConnection(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_radarr_conn_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_url_or_key_missing(self) -> None:
        result = self.api.integrations.test_radarr_connection(url="", api_key="")
        self.assertFalse(result["ok"])
        self.assertIn("URL", result["message"])

    def test_only_url(self) -> None:
        result = self.api.integrations.test_radarr_connection(url="http://10.0.0.1:7878", api_key="")
        self.assertFalse(result["ok"])

    def test_only_key(self) -> None:
        result = self.api.integrations.test_radarr_connection(url="", api_key="abc")
        self.assertFalse(result["ok"])

    @patch("cinesort.infra.radarr_client.RadarrClient")
    def test_connection_success(self, mock_client_cls: MagicMock) -> None:
        client = MagicMock()
        client.validate_connection.return_value = {"ok": True, "version": "5.1.0", "instance_name": "Radarr"}
        mock_client_cls.return_value = client
        result = self.api.integrations.test_radarr_connection(url="http://10.0.0.1:7878", api_key="key")
        self.assertTrue(result["ok"])
        self.assertEqual(result["version"], "5.1.0")
        mock_client_cls.assert_called_once()

    @patch("cinesort.infra.radarr_client.RadarrClient")
    def test_timeout_clamped(self, mock_client_cls: MagicMock) -> None:
        client = MagicMock()
        client.validate_connection.return_value = {"ok": True}
        mock_client_cls.return_value = client
        self.api.integrations.test_radarr_connection(url="http://x", api_key="k", timeout_s=999.0)
        kwargs = mock_client_cls.call_args.kwargs
        self.assertLessEqual(kwargs.get("timeout_s", 0), 30)


class TestGetRadarrStatus(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_radarr_status_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch.object(backend.CineSortApi, "get_settings")
    def test_radarr_disabled(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"radarr_enabled": False}
        result = self.api.integrations.get_radarr_status()
        self.assertFalse(result["ok"])
        self.assertIn("non configure", result["message"])

    @patch.object(backend.CineSortApi, "get_settings")
    def test_radarr_enabled_but_url_missing(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {
            "radarr_enabled": True,
            "radarr_url": "",
            "radarr_api_key": "k",
        }
        result = self.api.integrations.get_radarr_status()
        self.assertFalse(result["ok"])
        self.assertIn("manquante", result["message"])

    @patch.object(backend.CineSortApi, "get_settings")
    def test_radarr_no_run(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {
            "radarr_enabled": True,
            "radarr_url": "http://x",
            "radarr_api_key": "k",
        }
        result = self.api.integrations.get_radarr_status()
        self.assertFalse(result["ok"])
        self.assertIn("Aucun run", result["message"])

    @patch.object(backend.CineSortApi, "get_settings")
    @patch("cinesort.infra.radarr_client.RadarrClient")
    def test_radarr_connection_error(self, mock_client_cls: MagicMock, mock_get_settings: MagicMock) -> None:
        from cinesort.infra.radarr_client import RadarrError

        mock_get_settings.return_value = {
            "radarr_enabled": True,
            "radarr_url": "http://x",
            "radarr_api_key": "k",
        }
        client = MagicMock()
        client.get_movies.side_effect = RadarrError("network down")
        mock_client_cls.return_value = client

        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.get_runs_summary.return_value = [{"run_id": "r1", "status": "DONE"}]
            mock_infra.return_value = (store, MagicMock())
            (self.state_dir / "runs" / "r1").mkdir(parents=True)
            (self.state_dir / "runs" / "r1" / "plan.jsonl").write_text("", encoding="utf-8")

            result = self.api.integrations.get_radarr_status(run_id="r1")
            self.assertFalse(result["ok"])
            self.assertIn("network down", result["message"])


class TestRequestRadarrUpgrade(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_radarr_upg_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch.object(backend.CineSortApi, "get_settings")
    def test_radarr_disabled(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"radarr_enabled": False}
        result = self.api.integrations.request_radarr_upgrade(radarr_movie_id=42)
        self.assertFalse(result["ok"])
        self.assertIn("non configure", result["message"])

    @patch.object(backend.CineSortApi, "get_settings")
    def test_invalid_movie_id(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {
            "radarr_enabled": True,
            "radarr_url": "http://x",
            "radarr_api_key": "k",
        }
        result = self.api.integrations.request_radarr_upgrade(radarr_movie_id=0)
        self.assertFalse(result["ok"])
        self.assertIn("invalide", result["message"])

    @patch.object(backend.CineSortApi, "get_settings")
    def test_negative_movie_id(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {
            "radarr_enabled": True,
            "radarr_url": "http://x",
            "radarr_api_key": "k",
        }
        result = self.api.integrations.request_radarr_upgrade(radarr_movie_id=-1)
        self.assertFalse(result["ok"])
        self.assertIn("invalide", result["message"])

    @patch.object(backend.CineSortApi, "get_settings")
    @patch("cinesort.infra.radarr_client.RadarrClient")
    def test_upgrade_success(self, mock_client_cls: MagicMock, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {
            "radarr_enabled": True,
            "radarr_url": "http://x",
            "radarr_api_key": "k",
        }
        client = MagicMock()
        client.search_movie.return_value = True
        mock_client_cls.return_value = client
        result = self.api.integrations.request_radarr_upgrade(radarr_movie_id=42)
        self.assertTrue(result["ok"])
        self.assertIn("42", result["message"])
        client.search_movie.assert_called_once_with(42)

    @patch.object(backend.CineSortApi, "get_settings")
    @patch("cinesort.infra.radarr_client.RadarrClient")
    def test_upgrade_radarr_error(self, mock_client_cls: MagicMock, mock_get_settings: MagicMock) -> None:
        from cinesort.infra.radarr_client import RadarrError

        mock_get_settings.return_value = {
            "radarr_enabled": True,
            "radarr_url": "http://x",
            "radarr_api_key": "k",
        }
        client = MagicMock()
        client.search_movie.side_effect = RadarrError("server overloaded")
        mock_client_cls.return_value = client
        result = self.api.integrations.request_radarr_upgrade(radarr_movie_id=42)
        self.assertFalse(result["ok"])
        self.assertIn("server overloaded", result["message"])


if __name__ == "__main__":
    unittest.main()
