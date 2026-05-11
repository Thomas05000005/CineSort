"""Tests integration Radarr — item 9.25.

Couvre :
- RadarrClient : validate, get_movies, get_quality_profiles, search_movie
- build_radarr_report : matching, not_in_radarr, wanted
- should_propose_upgrade : score, encode, codec, monitored
- Endpoints API
- Settings defaults + round-trip
- UI : section Radarr settings + dashboard
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cinesort.infra.radarr_client import RadarrClient
from cinesort.app.radarr_sync import (
    build_radarr_report,
    should_propose_upgrade,
)


# ---------------------------------------------------------------------------
# Client mock (4 tests)
# ---------------------------------------------------------------------------


class RadarrClientMockTests(unittest.TestCase):
    """Tests du client Radarr avec responses mockees."""

    @mock.patch("cinesort.infra.radarr_client.RadarrClient._get")
    def test_validate_connection(self, mock_get) -> None:
        resp = mock.MagicMock()
        resp.json.return_value = {"instanceName": "My Radarr", "version": "5.0.0"}
        mock_get.return_value = resp
        client = RadarrClient("http://localhost:7878", "key123")
        result = client.validate_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["server_name"], "My Radarr")

    @mock.patch("cinesort.infra.radarr_client.RadarrClient._get")
    def test_get_movies(self, mock_get) -> None:
        resp = mock.MagicMock()
        resp.json.return_value = [
            {
                "id": 1,
                "title": "Inception",
                "year": 2010,
                "tmdbId": 27205,
                "monitored": True,
                "hasFile": True,
                "qualityProfileId": 4,
                "movieFile": {
                    "path": "D:/Films/Inception/inception.mkv",
                    "quality": {"quality": {"name": "Bluray-1080p"}},
                },
            }
        ]
        mock_get.return_value = resp
        client = RadarrClient("http://localhost:7878", "key")
        movies = client.get_movies()
        self.assertEqual(len(movies), 1)
        self.assertEqual(movies[0]["tmdb_id"], 27205)
        self.assertTrue(movies[0]["has_file"])
        self.assertEqual(movies[0]["quality_name"], "Bluray-1080p")

    @mock.patch("cinesort.infra.radarr_client.RadarrClient._get")
    def test_get_quality_profiles(self, mock_get) -> None:
        resp = mock.MagicMock()
        resp.json.return_value = [{"id": 4, "name": "HD-1080p"}, {"id": 6, "name": "Ultra-HD"}]
        mock_get.return_value = resp
        client = RadarrClient("http://localhost:7878", "key")
        profiles = client.get_quality_profiles()
        self.assertEqual(len(profiles), 2)
        self.assertEqual(profiles[0]["name"], "HD-1080p")

    @mock.patch("cinesort.infra.radarr_client.RadarrClient._post")
    def test_search_movie(self, mock_post) -> None:
        resp = mock.MagicMock()
        mock_post.return_value = resp
        client = RadarrClient("http://localhost:7878", "key")
        self.assertTrue(client.search_movie(1))
        mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# Matching + rapport (3 tests)
# ---------------------------------------------------------------------------


def _local_row(title, year, tmdb_id=None, row_id="r1"):
    cands = [SimpleNamespace(tmdb_id=tmdb_id)] if tmdb_id else []
    return SimpleNamespace(
        proposed_title=title,
        proposed_year=year,
        row_id=row_id,
        folder="/films/" + title,
        video="x.mkv",
        candidates=cands,
    )


class RadarrReportTests(unittest.TestCase):
    """Tests du rapport Radarr."""

    def test_match_by_tmdb(self) -> None:
        local = [_local_row("Inception", 2010, tmdb_id=27205)]
        radarr = [
            {
                "id": 1,
                "title": "Inception",
                "year": 2010,
                "tmdb_id": 27205,
                "monitored": True,
                "has_file": True,
                "quality_profile_id": 4,
                "path": "",
                "quality_name": "Bluray-1080p",
            }
        ]
        report = build_radarr_report(local, radarr, {}, [{"id": 4, "name": "HD"}])
        self.assertEqual(report["matched_count"], 1)
        self.assertEqual(report["matched"][0]["profile_name"], "HD")

    def test_not_in_radarr(self) -> None:
        local = [_local_row("Film X", 2020)]
        report = build_radarr_report(local, [], {}, [])
        self.assertEqual(len(report["not_in_radarr"]), 1)

    def test_wanted_films(self) -> None:
        radarr = [
            {
                "id": 2,
                "title": "Film Y",
                "year": 2021,
                "tmdb_id": 999,
                "monitored": True,
                "has_file": False,
                "quality_profile_id": 4,
                "path": "",
                "quality_name": "",
            }
        ]
        report = build_radarr_report([], radarr, {}, [])
        self.assertEqual(len(report["wanted"]), 1)


# ---------------------------------------------------------------------------
# should_propose_upgrade (5 tests)
# ---------------------------------------------------------------------------


class UpgradeProposalTests(unittest.TestCase):
    """Tests de la proposition d'upgrade."""

    def test_low_score_upgrade(self) -> None:
        self.assertTrue(
            should_propose_upgrade(
                {"monitored": True},
                {"score": 40, "metrics": {}, "reasons": []},
            )
        )

    def test_high_score_no_upgrade(self) -> None:
        self.assertFalse(
            should_propose_upgrade(
                {"monitored": True},
                {"score": 85, "metrics": {}, "reasons": []},
            )
        )

    def test_not_monitored_no_upgrade(self) -> None:
        self.assertFalse(
            should_propose_upgrade(
                {"monitored": False},
                {"score": 30, "metrics": {}, "reasons": []},
            )
        )

    def test_upscale_suspect_upgrade(self) -> None:
        self.assertTrue(
            should_propose_upgrade(
                {"monitored": True},
                {"score": 60, "metrics": {}, "reasons": ["upscale suspect detected"]},
            )
        )

    def test_obsolete_codec_upgrade(self) -> None:
        self.assertTrue(
            should_propose_upgrade(
                {"monitored": True},
                {"score": 60, "metrics": {"detected": {"codec": "xvid"}}, "reasons": []},
            )
        )


# ---------------------------------------------------------------------------
# Settings (2 tests)
# ---------------------------------------------------------------------------


class RadarrSettingsTests(unittest.TestCase):
    """Tests des settings Radarr."""

    def test_defaults(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        # Utiliser un state_dir temporaire vide pour tester les vrais defaults
        tmp = tempfile.mkdtemp(prefix="cinesort_radarr_def_")
        try:
            api = backend.CineSortApi()
            api._state_dir = Path(tmp)
            s = api.get_settings()
            self.assertFalse(s.get("radarr_enabled"))
            self.assertEqual(s.get("radarr_url"), "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_round_trip(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        tmp = tempfile.mkdtemp(prefix="cinesort_radarr_s_")
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
                    "radarr_enabled": True,
                    "radarr_url": "http://radarr:7878",
                    "radarr_api_key": "abc123",
                }
            )
            s = api.get_settings()
            self.assertTrue(s["radarr_enabled"])
            self.assertEqual(s["radarr_url"], "http://radarr:7878")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Endpoints (3 tests)
# ---------------------------------------------------------------------------


class RadarrEndpointTests(unittest.TestCase):
    """Tests que les endpoints Radarr existent."""

    def test_test_radarr_connection_exists(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        self.assertTrue(hasattr(api, "test_radarr_connection"))

    def test_get_radarr_status_disabled(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        result = api.get_radarr_status()
        self.assertFalse(result["ok"])

    def test_request_radarr_upgrade_disabled(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        result = api.request_radarr_upgrade(1)
        self.assertFalse(result["ok"])


# ---------------------------------------------------------------------------
# UI (2 tests)
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/status.js supprime — adaptation v5 deferee a V5C-03")
class RadarrUiTests(unittest.TestCase):
    """Tests presence UI Radarr."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.html = (root / "web" / "index.html").read_text(encoding="utf-8")
        cls.settings_js = (root / "web" / "views" / "settings.js").read_text(encoding="utf-8")
        cls.status_js = (root / "web" / "dashboard" / "views" / "status.js").read_text(encoding="utf-8")

    def test_desktop_section_present(self) -> None:
        self.assertIn("ckRadarrEnabled", self.html)
        self.assertIn("inRadarrUrl", self.html)
        self.assertIn("inRadarrApiKey", self.html)
        self.assertIn("btnTestRadarr", self.html)

    def test_settings_js_radarr(self) -> None:
        self.assertIn("radarr_enabled", self.settings_js)
        self.assertIn("radarr_url", self.settings_js)
        self.assertIn("test_radarr_connection", self.settings_js)

    def test_dashboard_radarr_indicator(self) -> None:
        self.assertIn("radarr_enabled", self.status_js)
        self.assertIn("Radarr", self.status_js)


if __name__ == "__main__":
    unittest.main()
