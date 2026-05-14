"""V2-05 — Tests cinesort_api Email + Jellyfin endpoints (test_email_report / get_jellyfin_libraries / get_jellyfin_sync_report)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import cinesort.ui.api.cinesort_api as backend


class TestEmailReport(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_email_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch.object(backend.CineSortApi, "get_settings")
    def test_smtp_host_missing(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"email_smtp_host": "", "email_to": "x@y"}
        result = self.api.test_email_report()
        self.assertFalse(result["ok"])
        self.assertIn("SMTP", result["message"])

    @patch.object(backend.CineSortApi, "get_settings")
    def test_email_to_missing(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"email_smtp_host": "smtp.example.com", "email_to": ""}
        result = self.api.test_email_report()
        self.assertFalse(result["ok"])

    @patch("cinesort.app.email_report.send_email_report")
    @patch.object(backend.CineSortApi, "get_settings")
    def test_send_success(self, mock_get_settings: MagicMock, mock_send: MagicMock) -> None:
        mock_get_settings.return_value = {
            "email_smtp_host": "smtp.example.com",
            "email_to": "x@y",
        }
        mock_send.return_value = True
        result = self.api.test_email_report()
        self.assertTrue(result["ok"])
        self.assertIn("envoye", result["message"])
        mock_send.assert_called_once()
        # Le 2e arg doit être l'event "post_scan"
        args = mock_send.call_args.args
        self.assertEqual(args[1], "post_scan")

    @patch("cinesort.app.email_report.send_email_report")
    @patch.object(backend.CineSortApi, "get_settings")
    def test_send_failure(self, mock_get_settings: MagicMock, mock_send: MagicMock) -> None:
        mock_get_settings.return_value = {
            "email_smtp_host": "smtp.example.com",
            "email_to": "x@y",
        }
        mock_send.return_value = False
        result = self.api.test_email_report()
        self.assertFalse(result["ok"])
        self.assertIn("Echec", result["message"])


class TestGetJellyfinLibraries(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_jf_libs_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch("cinesort.ui.api.cinesort_api._read_settings")
    def test_jellyfin_url_missing(self, mock_read_settings: MagicMock) -> None:
        mock_read_settings.return_value = {"jellyfin_url": "", "jellyfin_api_key": "k"}
        result = self.api.integrations.get_jellyfin_libraries()
        self.assertFalse(result["ok"])
        self.assertIn("non configur", result["message"])

    @patch("cinesort.infra.jellyfin_client.JellyfinClient")
    @patch("cinesort.ui.api.cinesort_api._read_settings")
    def test_libraries_with_user_id(self, mock_read_settings: MagicMock, mock_jf_cls: MagicMock) -> None:
        mock_read_settings.return_value = {
            "jellyfin_url": "http://10.0.0.1:8096",
            "jellyfin_api_key": "key",
            "jellyfin_user_id": "uid42",
            "jellyfin_timeout_s": 5.0,
        }
        client = MagicMock()
        client.get_libraries.return_value = [{"id": "1", "name": "Films"}]
        client.get_movies_count.return_value = 100
        mock_jf_cls.return_value = client
        result = self.api.integrations.get_jellyfin_libraries()
        self.assertTrue(result["ok"])
        self.assertEqual(result["movies_count"], 100)
        client.get_libraries.assert_called_once_with("uid42")

    @patch("cinesort.infra.jellyfin_client.JellyfinClient")
    @patch("cinesort.ui.api.cinesort_api._read_settings")
    def test_libraries_validate_connection_when_no_user_id(
        self, mock_read_settings: MagicMock, mock_jf_cls: MagicMock
    ) -> None:
        mock_read_settings.return_value = {
            "jellyfin_url": "http://x",
            "jellyfin_api_key": "k",
            "jellyfin_user_id": "",
        }
        client = MagicMock()
        client.validate_connection.return_value = {"ok": True, "user_id": "auto_uid"}
        client.get_libraries.return_value = []
        client.get_movies_count.return_value = 0
        mock_jf_cls.return_value = client
        result = self.api.integrations.get_jellyfin_libraries()
        self.assertTrue(result["ok"])
        client.validate_connection.assert_called_once()
        client.get_libraries.assert_called_once_with("auto_uid")

    @patch("cinesort.infra.jellyfin_client.JellyfinClient")
    @patch("cinesort.ui.api.cinesort_api._read_settings")
    def test_libraries_validate_connection_fails(self, mock_read_settings: MagicMock, mock_jf_cls: MagicMock) -> None:
        mock_read_settings.return_value = {
            "jellyfin_url": "http://x",
            "jellyfin_api_key": "k",
            "jellyfin_user_id": "",
        }
        client = MagicMock()
        client.validate_connection.return_value = {"ok": False, "error": "401 unauthorized"}
        mock_jf_cls.return_value = client
        result = self.api.integrations.get_jellyfin_libraries()
        self.assertFalse(result["ok"])
        self.assertIn("unauthorized", result["message"])

    @patch("cinesort.infra.jellyfin_client.JellyfinClient")
    @patch("cinesort.ui.api.cinesort_api._read_settings")
    def test_libraries_jellyfin_error(self, mock_read_settings: MagicMock, mock_jf_cls: MagicMock) -> None:
        from cinesort.infra.jellyfin_client import JellyfinError

        mock_read_settings.return_value = {
            "jellyfin_url": "http://x",
            "jellyfin_api_key": "k",
            "jellyfin_user_id": "uid",
        }
        client = MagicMock()
        client.get_libraries.side_effect = JellyfinError("connection refused")
        mock_jf_cls.return_value = client
        result = self.api.integrations.get_jellyfin_libraries()
        self.assertFalse(result["ok"])
        self.assertIn("connection refused", result["message"])


class TestGetJellyfinSyncReport(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_jf_sync_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch.object(backend.CineSortApi, "get_settings")
    def test_jellyfin_disabled(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"jellyfin_enabled": False}
        result = self.api.integrations.get_jellyfin_sync_report()
        self.assertFalse(result["ok"])
        self.assertIn("non configure", result["message"])

    @patch.object(backend.CineSortApi, "get_settings")
    def test_jellyfin_url_missing(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {
            "jellyfin_enabled": True,
            "jellyfin_url": "",
            "jellyfin_api_key": "k",
        }
        result = self.api.integrations.get_jellyfin_sync_report()
        self.assertFalse(result["ok"])
        self.assertIn("manquante", result["message"])

    @patch.object(backend.CineSortApi, "get_settings")
    def test_jellyfin_no_run(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {
            "jellyfin_enabled": True,
            "jellyfin_url": "http://x",
            "jellyfin_api_key": "k",
            "jellyfin_user_id": "uid",
        }
        result = self.api.integrations.get_jellyfin_sync_report()
        self.assertFalse(result["ok"])
        self.assertIn("Aucun run", result["message"])

    @patch.object(backend.CineSortApi, "get_settings")
    @patch("cinesort.infra.jellyfin_client.JellyfinClient")
    def test_jellyfin_connection_error(self, mock_jf_cls: MagicMock, mock_get_settings: MagicMock) -> None:
        from cinesort.infra.jellyfin_client import JellyfinError

        mock_get_settings.return_value = {
            "jellyfin_enabled": True,
            "jellyfin_url": "http://x",
            "jellyfin_api_key": "k",
            "jellyfin_user_id": "uid",
        }
        client = MagicMock()
        client.get_all_movies_from_all_libraries.side_effect = JellyfinError("DNS fail")
        mock_jf_cls.return_value = client

        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.get_runs_summary.return_value = [{"run_id": "r1", "status": "DONE"}]
            mock_infra.return_value = (store, MagicMock())
            (self.state_dir / "runs" / "r1").mkdir(parents=True)
            (self.state_dir / "runs" / "r1" / "plan.jsonl").write_text("", encoding="utf-8")

            result = self.api.integrations.get_jellyfin_sync_report(run_id="r1")
            self.assertFalse(result["ok"])
            self.assertIn("Aucun film", result["message"])


if __name__ == "__main__":
    unittest.main()
