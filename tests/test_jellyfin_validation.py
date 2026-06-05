"""Tests validation croisee Jellyfin — item 9.26.

Couvre :
- get_all_movies enrichi (year, tmdb_id)
- Matching 3 niveaux (chemin, tmdb_id, titre+annee)
- Rapport (matched, missing, ghost, mismatch)
- Endpoint existe
- UI (bouton, CSS)
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from cinesort.app.jellyfin_validation import build_sync_report

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _local_row(title, year, folder="/films/Film", video="film.mkv", tmdb_id=None):
    cands = []
    if tmdb_id:
        cands.append(SimpleNamespace(tmdb_id=tmdb_id))
    return SimpleNamespace(
        proposed_title=title,
        proposed_year=year,
        folder=folder,
        video=video,
        candidates=cands,
    )


def _jf_movie(name, year, path, tmdb_id=None, jf_id="jf1"):
    return {"id": jf_id, "name": name, "year": year, "path": path, "tmdb_id": tmdb_id}


# ---------------------------------------------------------------------------
# get_all_movies enrichi (2 tests)
# ---------------------------------------------------------------------------


class EnrichedMovieTests(unittest.TestCase):
    """Tests que le mapping retour inclut year et tmdb_id."""

    def test_year_and_tmdb_id_present(self) -> None:
        movie = _jf_movie("Inception", 2010, "/films/Inception/inception.mkv", tmdb_id="27205")
        self.assertEqual(movie["year"], 2010)
        self.assertEqual(movie["tmdb_id"], "27205")

    def test_no_provider_ids(self) -> None:
        movie = _jf_movie("Film X", 2020, "/films/x.mkv")
        self.assertIsNone(movie["tmdb_id"])


# ---------------------------------------------------------------------------
# Matching (5 tests)
# ---------------------------------------------------------------------------


class MatchingTests(unittest.TestCase):
    """Tests du matching 3 niveaux."""

    def test_match_by_path(self) -> None:
        local = [_local_row("Inception", 2010, folder="D:/Films/Inception (2010)", video="inception.mkv")]
        jf = [_jf_movie("Inception", 2010, "D:\\Films\\Inception (2010)\\inception.mkv")]
        report = build_sync_report(local, jf)
        self.assertEqual(report["matched"], 1)
        self.assertEqual(len(report["missing_in_jellyfin"]), 0)
        self.assertEqual(len(report["ghost_in_jellyfin"]), 0)

    def test_match_by_tmdb_id_fallback(self) -> None:
        local = [_local_row("Inception", 2010, folder="/other/path", video="x.mkv", tmdb_id=27205)]
        jf = [_jf_movie("Inception", 2010, "/different/path/inception.mkv", tmdb_id="27205")]
        report = build_sync_report(local, jf)
        self.assertEqual(report["matched"], 1)

    def test_match_skips_invalid_tmdb_id(self) -> None:
        # Audit 2026-05-13 : tmdb_id non-numerique ne doit pas crasher
        # _extract_local_tmdb_id (ex: NFO corrompu, tag string "tt0123" IMDb).
        local = [_local_row("Film", 2020, folder="/films/x", video="x.mkv", tmdb_id="tt0123")]
        jf = [_jf_movie("Film", 2020, "/films/x/x.mkv")]
        report = build_sync_report(local, jf)
        # Le match tombe au niveau 3 (titre+annee), pas de crash.
        self.assertEqual(report["matched"], 1)

    def test_match_by_title_year_fallback(self) -> None:
        local = [_local_row("Inception", 2010, folder="/a", video="x.mkv")]
        jf = [_jf_movie("Inception", 2010, "/b/inception.mkv")]
        report = build_sync_report(local, jf)
        self.assertEqual(report["matched"], 1)

    def test_missing_in_jellyfin(self) -> None:
        local = [_local_row("Film X", 2020, folder="/films/x")]
        jf = []
        report = build_sync_report(local, jf)
        self.assertEqual(len(report["missing_in_jellyfin"]), 1)
        self.assertEqual(report["missing_in_jellyfin"][0]["title"], "Film X")

    def test_ghost_in_jellyfin(self) -> None:
        local = []
        jf = [_jf_movie("Old Film", 2015, "/films/old.mkv")]
        report = build_sync_report(local, jf)
        self.assertEqual(len(report["ghost_in_jellyfin"]), 1)
        self.assertEqual(report["ghost_in_jellyfin"][0]["title"], "Old Film")


# ---------------------------------------------------------------------------
# Rapport (3 tests)
# ---------------------------------------------------------------------------


class ReportStructureTests(unittest.TestCase):
    """Tests de la structure du rapport."""

    def test_report_keys(self) -> None:
        report = build_sync_report([], [])
        for key in (
            "total_local",
            "total_jellyfin",
            "matched",
            "missing_in_jellyfin",
            "ghost_in_jellyfin",
            "metadata_mismatch",
        ):
            self.assertIn(key, report)

    def test_zero_divergence(self) -> None:
        local = [_local_row("Film", 2020, folder="/f")]
        jf = [_jf_movie("Film", 2020, "/f/film.mkv")]
        report = build_sync_report(local, jf)
        self.assertEqual(len(report["metadata_mismatch"]), 0)
        self.assertEqual(report["matched"], 1)

    def test_metadata_mismatch_title(self) -> None:
        local = [_local_row("Inception", 2010, folder="/f/inception", video="x.mkv")]
        jf = [_jf_movie("Inception Extended", 2010, "/f/inception/x.mkv")]
        report = build_sync_report(local, jf)
        self.assertEqual(report["matched"], 1)
        title_mismatches = [m for m in report["metadata_mismatch"] if m["field"] == "title"]
        self.assertEqual(len(title_mismatches), 1)


# ---------------------------------------------------------------------------
# Endpoint + UI (3 tests)
# ---------------------------------------------------------------------------


class EndpointAndUiTests(unittest.TestCase):
    """Tests endpoint et presence UI."""

    def test_endpoint_exists(self) -> None:
        """Issue #84 PR 10 : get_jellyfin_sync_report est sur IntegrationsFacade."""
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        self.assertTrue(hasattr(api.integrations, "get_jellyfin_sync_report"))

    def test_ui_sync_button(self) -> None:
        root = Path(__file__).resolve().parents[1]
        jf_js = (root / "web" / "dashboard" / "views" / "jellyfin.js").read_text(encoding="utf-8")
        self.assertIn("btnJellyfinSync", jf_js)
        self.assertIn("jellyfinSyncResults", jf_js)
        self.assertIn("get_jellyfin_sync_report", jf_js)

    def test_css_sync_classes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".sync-ok", css)
        self.assertIn(".sync-warn", css)
        self.assertIn(".sync-error", css)


class RunIdValidationTests(unittest.TestCase):
    """Audit 2026-05-20 : run_id non valide doit etre rejete avant la construction de chemin.

    Les endpoints sync Jellyfin/Plex/Radarr construisent state_dir / "runs" / run_id /
    "plan.jsonl". Sans validation, un run_id contenant "../" permettait de lire un
    fichier hors du dossier runs/ (CWE-22 Path Traversal).
    """

    def _make_api_with_settings(self, settings: dict):
        import tempfile
        from unittest.mock import patch

        import cinesort.ui.api.cinesort_api as backend

        tmp = tempfile.mkdtemp(prefix="audit_runid_")
        state_dir = Path(tmp) / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        api = backend.CineSortApi()
        api._state_dir = state_dir  # type: ignore[attr-defined]
        patcher = patch.object(api, "_get_settings_impl", return_value=settings)
        patcher.start()
        return api, tmp, patcher

    def _cleanup(self, tmp: str, patcher) -> None:
        import shutil

        patcher.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    def test_jellyfin_sync_report_rejects_path_traversal_run_id(self) -> None:
        settings = {
            "jellyfin_enabled": True,
            "jellyfin_url": "http://localhost:8096",
            "jellyfin_api_key": "fake_key",
            "jellyfin_user_id": "fake_user",
        }
        api, tmp, patcher = self._make_api_with_settings(settings)
        try:
            result = api._get_jellyfin_sync_report_impl(run_id="../../etc/passwd")
            self.assertFalse(result.get("ok"))
            self.assertIn("invalide", str(result.get("message", "")).lower())
        finally:
            self._cleanup(tmp, patcher)

    def test_plex_sync_report_rejects_path_traversal_run_id(self) -> None:
        settings = {
            "plex_enabled": True,
            "plex_url": "http://localhost:32400",
            "plex_token": "fake_token",
            "plex_library_id": "1",
        }
        api, tmp, patcher = self._make_api_with_settings(settings)
        try:
            result = api._get_plex_sync_report_impl(run_id="../../etc/passwd")
            self.assertFalse(result.get("ok"))
            self.assertIn("invalide", str(result.get("message", "")).lower())
        finally:
            self._cleanup(tmp, patcher)

    def test_radarr_status_rejects_path_traversal_run_id(self) -> None:
        settings = {
            "radarr_enabled": True,
            "radarr_url": "http://localhost:7878",
            "radarr_api_key": "fake_key",
        }
        api, tmp, patcher = self._make_api_with_settings(settings)
        try:
            result = api._get_radarr_status_impl(run_id="../../etc/passwd")
            self.assertFalse(result.get("ok"))
            self.assertIn("invalide", str(result.get("message", "")).lower())
        finally:
            self._cleanup(tmp, patcher)


if __name__ == "__main__":
    unittest.main()
