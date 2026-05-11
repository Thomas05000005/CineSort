"""V2-05 — Tests cinesort_api plugin/email dispatch + import_watchlist."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import cinesort.ui.api.cinesort_api as backend


class TestDispatchPluginHook(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_plugin_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch.object(backend.CineSortApi, "get_settings")
    def test_plugins_disabled_skips_dispatch(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"plugins_enabled": False}
        # Import dispatch_hook to ensure it's not called
        with patch("cinesort.app.plugin_hooks.dispatch_hook") as mock_dispatch:
            self.api._dispatch_plugin_hook("post_scan", {"x": 1})
            mock_dispatch.assert_not_called()

    @patch.object(backend.CineSortApi, "get_settings")
    def test_plugins_enabled_calls_dispatch(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"plugins_enabled": True, "plugins_timeout_s": 15}
        with patch("cinesort.app.plugin_hooks.dispatch_hook") as mock_dispatch:
            self.api._dispatch_plugin_hook("post_scan", {"x": 1})
            mock_dispatch.assert_called_once()
            kwargs = mock_dispatch.call_args.kwargs
            self.assertEqual(kwargs.get("timeout_s"), 15)
            args = mock_dispatch.call_args.args
            self.assertEqual(args[0], "post_scan")
            self.assertEqual(args[1], {"x": 1})

    @patch.object(backend.CineSortApi, "get_settings")
    def test_plugins_dispatch_swallows_errors(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"plugins_enabled": True}
        with patch("cinesort.app.plugin_hooks.dispatch_hook", side_effect=ImportError("boom")):
            # Doit retourner sans exception (catch BLE001-like)
            self.api._dispatch_plugin_hook("post_scan", {})

    @patch.object(backend.CineSortApi, "get_settings")
    def test_plugins_dispatch_default_timeout(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"plugins_enabled": True}
        with patch("cinesort.app.plugin_hooks.dispatch_hook") as mock_dispatch:
            self.api._dispatch_plugin_hook("post_scan", {})
            kwargs = mock_dispatch.call_args.kwargs
            self.assertEqual(kwargs.get("timeout_s"), 30)


class TestDispatchEmail(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_dispatch_email_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch.object(backend.CineSortApi, "get_settings")
    def test_dispatch_email_calls_dispatch(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"email_enabled": True, "email_smtp_host": "smtp.x"}
        with patch("cinesort.app.email_report.dispatch_email") as mock_dispatch:
            self.api._dispatch_email("post_scan", {"x": 1})
            mock_dispatch.assert_called_once()
            args = mock_dispatch.call_args.args
            # signature: (settings, event, data)
            self.assertEqual(args[1], "post_scan")
            self.assertEqual(args[2], {"x": 1})

    @patch.object(backend.CineSortApi, "get_settings")
    def test_dispatch_email_swallows_errors(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"email_enabled": True}
        with patch("cinesort.app.email_report.dispatch_email", side_effect=ValueError("boom")):
            # Ne doit pas remonter d'exception
            self.api._dispatch_email("post_scan", {})


class TestImportWatchlist(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_watchlist_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_invalid_source(self) -> None:
        result = self.api.import_watchlist(csv_content="x", source="netflix")
        self.assertFalse(result["ok"])
        self.assertIn("Source", result["message"])

    def test_empty_content(self) -> None:
        result = self.api.import_watchlist(csv_content="   ", source="letterboxd")
        self.assertFalse(result["ok"])
        self.assertIn("vide", result["message"])

    def test_letterboxd_no_films_parsed(self) -> None:
        with patch("cinesort.app.watchlist.parse_letterboxd_csv", return_value=[]):
            result = self.api.import_watchlist(csv_content="header\n", source="letterboxd")
            self.assertFalse(result["ok"])
            self.assertIn("Aucun film", result["message"])

    def test_imdb_no_films_parsed(self) -> None:
        with patch("cinesort.app.watchlist.parse_imdb_csv", return_value=[]):
            result = self.api.import_watchlist(csv_content="header\n", source="imdb")
            self.assertFalse(result["ok"])
            self.assertIn("Aucun film", result["message"])

    def test_letterboxd_no_run_done(self) -> None:
        fake_films = [{"title": "Inception", "year": 2010}]
        with (
            patch("cinesort.app.watchlist.parse_letterboxd_csv", return_value=fake_films),
            patch.object(self.api, "_get_or_create_infra") as mock_infra,
        ):
            store = MagicMock()
            store.get_runs_summary.return_value = []
            mock_infra.return_value = (store, MagicMock())
            result = self.api.import_watchlist(csv_content="x", source="letterboxd")
            self.assertFalse(result["ok"])
            self.assertIn("Aucun run", result["message"])

    def test_letterboxd_success_path(self) -> None:
        fake_films = [{"title": "Inception", "year": 2010}]
        fake_report = {"matches": [], "missing": [], "extras": []}
        with (
            patch("cinesort.app.watchlist.parse_letterboxd_csv", return_value=fake_films),
            patch("cinesort.app.watchlist.compare_watchlist", return_value=fake_report),
            patch.object(self.api, "_get_or_create_infra") as mock_infra,
        ):
            store = MagicMock()
            store.get_runs_summary.return_value = [{"run_id": "r1", "status": "DONE"}]
            mock_infra.return_value = (store, MagicMock())
            (self.state_dir / "runs" / "r1").mkdir(parents=True)
            (self.state_dir / "runs" / "r1" / "plan.jsonl").write_text("", encoding="utf-8")

            result = self.api.import_watchlist(csv_content="x", source="letterboxd")
            self.assertTrue(result["ok"])
            self.assertEqual(result["source"], "letterboxd")


if __name__ == "__main__":
    unittest.main()
