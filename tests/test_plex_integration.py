"""Tests integration Plex — item 9.14.

Couvre :
- PlexClient : validate, get_libraries, get_movies, refresh
- Refresh post-apply
- Validation croisee (build_sync_report avec donnees Plex)
- Endpoints API
- Settings defaults + round-trip
- UI : section Plex settings + dashboard
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cinesort.infra.plex_client import PlexClient


# ---------------------------------------------------------------------------
# Client mock (4 tests)
# ---------------------------------------------------------------------------


class PlexClientMockTests(unittest.TestCase):
    """Tests du client Plex avec responses mockees."""

    @mock.patch("cinesort.infra.plex_client.PlexClient._get")
    def test_validate_connection(self, mock_get) -> None:
        resp = mock.MagicMock()
        resp.json.return_value = {"MediaContainer": {"friendlyName": "My Plex", "version": "1.40"}}
        mock_get.return_value = resp
        client = PlexClient("http://localhost:32400", "tok123")
        result = client.validate_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["server_name"], "My Plex")
        self.assertEqual(result["version"], "1.40")

    @mock.patch("cinesort.infra.plex_client.PlexClient._get")
    def test_get_libraries(self, mock_get) -> None:
        resp = mock.MagicMock()
        resp.json.return_value = {
            "MediaContainer": {
                "Directory": [
                    {"key": "1", "title": "Films", "type": "movie"},
                    {"key": "2", "title": "Series", "type": "show"},
                ]
            }
        }
        mock_get.return_value = resp
        client = PlexClient("http://localhost:32400", "tok")
        libs = client.get_libraries("movie")
        self.assertEqual(len(libs), 1)
        self.assertEqual(libs[0]["name"], "Films")
        self.assertEqual(libs[0]["id"], "1")

    @mock.patch("cinesort.infra.plex_client.PlexClient._get")
    def test_get_movies(self, mock_get) -> None:
        resp = mock.MagicMock()
        resp.json.return_value = {
            "MediaContainer": {
                "Metadata": [
                    {
                        "ratingKey": "100",
                        "title": "Inception",
                        "year": 2010,
                        "Guid": [{"id": "tmdb://27205"}],
                        "Media": [{"Part": [{"file": "D:/Films/Inception/inception.mkv"}]}],
                        "viewCount": 2,
                    },
                ]
            }
        }
        mock_get.return_value = resp
        client = PlexClient("http://localhost:32400", "tok")
        movies = client.get_movies("1")
        self.assertEqual(len(movies), 1)
        self.assertEqual(movies[0]["name"], "Inception")
        self.assertEqual(movies[0]["year"], 2010)
        self.assertEqual(movies[0]["tmdb_id"], "27205")
        self.assertIn("inception.mkv", movies[0]["path"])
        self.assertTrue(movies[0]["played"])

    @mock.patch("cinesort.infra.plex_client.PlexClient._get")
    def test_refresh_library(self, mock_get) -> None:
        resp = mock.MagicMock()
        mock_get.return_value = resp
        client = PlexClient("http://localhost:32400", "tok")
        self.assertTrue(client.refresh_library("1"))


# ---------------------------------------------------------------------------
# Refresh post-apply (2 tests)
# ---------------------------------------------------------------------------


class PlexRefreshApplyTests(unittest.TestCase):
    """Tests du refresh Plex post-apply."""

    @mock.patch("cinesort.infra.plex_client.PlexClient.refresh_library", return_value=True)
    def test_refresh_called_if_enabled(self, mock_refresh) -> None:
        from cinesort.ui.api.apply_support import _trigger_plex_refresh

        api = mock.MagicMock()
        api.get_settings.return_value = {
            "plex_enabled": True,
            "plex_refresh_on_apply": True,
            "plex_url": "http://localhost:32400",
            "plex_token": "tok",
            "plex_library_id": "1",
            "plex_timeout_s": 5,
        }
        log = mock.MagicMock()
        _trigger_plex_refresh(api, log, dry_run=False)
        mock_refresh.assert_called_once_with("1")

    def test_skip_if_disabled(self) -> None:
        from cinesort.ui.api.apply_support import _trigger_plex_refresh

        api = mock.MagicMock()
        api.get_settings.return_value = {"plex_enabled": False}
        log = mock.MagicMock()
        _trigger_plex_refresh(api, log, dry_run=False)
        # Pas de crash


# ---------------------------------------------------------------------------
# Validation croisee (2 tests)
# ---------------------------------------------------------------------------


class PlexSyncReportTests(unittest.TestCase):
    """Tests de build_sync_report avec donnees format Plex."""

    def test_sync_report_with_plex_data(self) -> None:
        from cinesort.app.jellyfin_validation import build_sync_report

        local = [
            SimpleNamespace(
                proposed_title="Inception",
                proposed_year=2010,
                folder="D:/Films/Inception (2010)",
                video="inception.mkv",
                candidates=[SimpleNamespace(tmdb_id=27205)],
            )
        ]
        plex = [
            {
                "id": "100",
                "name": "Inception",
                "year": 2010,
                "path": "D:/Films/Inception (2010)/inception.mkv",
                "tmdb_id": "27205",
            }
        ]
        report = build_sync_report(local, plex)
        self.assertEqual(report["matched"], 1)
        self.assertEqual(len(report["missing_in_jellyfin"]), 0)

    def test_missing_from_plex(self) -> None:
        from cinesort.app.jellyfin_validation import build_sync_report

        local = [
            SimpleNamespace(
                proposed_title="Film X",
                proposed_year=2020,
                folder="/f",
                video="x.mkv",
                candidates=[],
            )
        ]
        report = build_sync_report(local, [])
        self.assertEqual(len(report["missing_in_jellyfin"]), 1)


# ---------------------------------------------------------------------------
# Endpoints (3 tests)
# ---------------------------------------------------------------------------


class PlexEndpointTests(unittest.TestCase):
    """Tests que les endpoints Plex existent."""

    def test_test_plex_connection_exists(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        self.assertTrue(hasattr(api, "test_plex_connection"))

    def test_get_plex_libraries_exists(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        self.assertTrue(hasattr(api, "get_plex_libraries"))

    def test_get_plex_sync_report_disabled(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        result = api.get_plex_sync_report()
        self.assertFalse(result["ok"])


# ---------------------------------------------------------------------------
# Settings (2 tests)
# ---------------------------------------------------------------------------


class PlexSettingsTests(unittest.TestCase):
    """Tests des settings Plex."""

    def test_defaults(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        s = api.get_settings()
        self.assertFalse(s.get("plex_enabled"))
        self.assertEqual(s.get("plex_url"), "")
        self.assertTrue(s.get("plex_refresh_on_apply"))

    def test_round_trip(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        tmp = tempfile.mkdtemp(prefix="cinesort_plex_s_")
        try:
            root = Path(tmp) / "root"
            sd = Path(tmp) / "state"
            root.mkdir()
            sd.mkdir()
            api = backend.CineSortApi()
            api.save_settings(
                {
                    "root": str(root),
                    "state_dir": str(sd),
                    "tmdb_enabled": False,
                    "plex_enabled": True,
                    "plex_url": "http://plex:32400",
                    "plex_token": "abc",
                    "plex_library_id": "1",
                }
            )
            s = api.get_settings()
            self.assertTrue(s["plex_enabled"])
            self.assertEqual(s["plex_url"], "http://plex:32400")
            self.assertEqual(s["plex_library_id"], "1")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# UI (2 tests)
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/status.js supprime — adaptation v5 deferee a V5C-03")
class PlexUiTests(unittest.TestCase):
    """Tests presence UI Plex."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.html = (root / "web" / "index.html").read_text(encoding="utf-8")
        cls.settings_js = (root / "web" / "views" / "settings.js").read_text(encoding="utf-8")
        cls.status_js = (root / "web" / "dashboard" / "views" / "status.js").read_text(encoding="utf-8")

    def test_desktop_section_present(self) -> None:
        self.assertIn("ckPlexEnabled", self.html)
        self.assertIn("inPlexUrl", self.html)
        self.assertIn("inPlexToken", self.html)
        self.assertIn("selPlexLibrary", self.html)
        self.assertIn("btnTestPlex", self.html)

    def test_settings_js_plex(self) -> None:
        self.assertIn("plex_enabled", self.settings_js)
        self.assertIn("plex_url", self.settings_js)
        self.assertIn("plex_library_id", self.settings_js)
        self.assertIn("test_plex_connection", self.settings_js)

    def test_dashboard_plex_indicator(self) -> None:
        self.assertIn("plex_enabled", self.status_js)
        self.assertIn("Plex", self.status_js)


if __name__ == "__main__":
    unittest.main()
