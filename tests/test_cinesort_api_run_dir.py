"""GATE Audit 2026-06-02 — les 4 endpoints d'integration doivent trouver le
plan.jsonl dans le VRAI dossier de run.

`_get_jellyfin_sync_report_impl`, `_import_watchlist_impl`,
`_get_plex_sync_report_impl` et `_get_radarr_status_impl` construisaient
`state_dir/runs/<run_id>/plan.jsonl` alors que `infra.state.new_run`,
`runtime_support.run_paths_for` et `app.job_runner` ecrivent tous dans
`state_dir/runs/tri_films_<run_id>/`. Les 4 endpoints ouvraient donc un dossier
inexistant : « Aucun film dans ce run. » silencieux pour Jellyfin/Plex, et un
rapport vide sans aucun signal pour Radarr/watchlist.

Ils passent desormais par `domain.film_history._resolve_run_dir`, qui applique
la convention canonique TOUT EN tolerant un dossier nu (bibliotheques dont les
runs sont anterieurs a la convention). Les deux dispositions sont donc testees :
un prefixe rigide rendrait les anciens runs invisibles.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import cinesort.ui.api.cinesort_api as backend

_RUN_ID = "run1"

# Un CSV Letterboxd minimal dont l'unique film correspond au plan.jsonl ci-dessous.
_LETTERBOXD_CSV = "Date,Name,Year,Letterboxd URI\n2026-06-02,Inception,2010,https://boxd.it/x\n"

_PLAN_ROW: Dict[str, Any] = {
    "row_id": "S|1",
    "kind": "single",
    "folder": "D:/Films/Inception (2010)",
    "video": "D:/Films/Inception (2010)/Inception.mkv",
    "proposed_title": "Inception",
    "proposed_year": 2010,
    "proposed_source": "tmdb",
    "confidence": 90,
    "candidates": [{"title": "Inception", "year": 2010, "source": "tmdb", "tmdb_id": 27205}],
}


class _RunDirTestBase(unittest.TestCase):
    """Ecrit un plan.jsonl a un emplacement choisi et pilote les 4 endpoints."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_api_rundir_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_plan(self, dir_name: str) -> None:
        run_dir = self.state_dir / "runs" / dir_name
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_dir / "plan.jsonl", "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_PLAN_ROW, ensure_ascii=False) + "\n")

    def _infra(self) -> Any:
        """Patch `_get_or_create_infra` : un unique run DONE, aucun quality report."""
        store = MagicMock()
        store.run.get_runs_summary.return_value = [{"run_id": _RUN_ID, "status": "DONE"}]
        store.quality.get_quality_report.return_value = None
        return patch.object(self.api, "_get_or_create_infra", return_value=(store, MagicMock()))

    # -- Les 4 endpoints, chacun avec son client distant neutralise (0 film distant).

    def _call_jellyfin(self) -> Dict[str, Any]:
        settings = {
            "jellyfin_enabled": True,
            "jellyfin_url": "http://jf",
            "jellyfin_api_key": "k",
            "jellyfin_user_id": "uid",
        }
        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = []
        with (
            patch.object(backend.CineSortApi, "_get_settings_impl", return_value=settings),
            patch("cinesort.infra.jellyfin_client.JellyfinClient", return_value=client),
            self._infra(),
        ):
            return self.api.integrations.get_jellyfin_sync_report(run_id=_RUN_ID)

    def _call_plex(self) -> Dict[str, Any]:
        settings = {
            "plex_enabled": True,
            "plex_url": "http://plex",
            "plex_token": "t",
            "plex_library_id": "1",
        }
        client = MagicMock()
        client.get_movies.return_value = []
        with (
            patch.object(backend.CineSortApi, "_get_settings_impl", return_value=settings),
            patch("cinesort.infra.plex_client.PlexClient", return_value=client),
            self._infra(),
        ):
            return self.api.integrations.get_plex_sync_report(run_id=_RUN_ID)

    def _call_radarr(self) -> Dict[str, Any]:
        settings = {
            "radarr_enabled": True,
            "radarr_url": "http://radarr",
            "radarr_api_key": "k",
        }
        client = MagicMock()
        client.get_movies.return_value = []
        client.get_quality_profiles.return_value = []
        with (
            patch.object(backend.CineSortApi, "_get_settings_impl", return_value=settings),
            patch("cinesort.infra.radarr_client.RadarrClient", return_value=client),
            self._infra(),
        ):
            return self.api.integrations.get_radarr_status(run_id=_RUN_ID)

    def _call_watchlist(self) -> Dict[str, Any]:
        with self._infra():
            return self.api._import_watchlist_impl(csv_content=_LETTERBOXD_CSV, source="letterboxd")

    # -- Assertions communes : le film du plan.jsonl a bien ete lu.

    def _assert_all_endpoints_see_the_film(self) -> None:
        jf = self._call_jellyfin()
        self.assertTrue(jf["ok"], f"jellyfin_sync_report: {jf.get('message')}")
        self.assertEqual(jf["total_local"], 1, "jellyfin_sync_report n'a pas lu le plan.jsonl")

        plex = self._call_plex()
        self.assertTrue(plex["ok"], f"plex_sync_report: {plex.get('message')}")
        self.assertEqual(plex["total_local"], 1, "plex_sync_report n'a pas lu le plan.jsonl")

        radarr = self._call_radarr()
        self.assertTrue(radarr["ok"], f"radarr_status: {radarr.get('message')}")
        self.assertEqual(radarr["total_local"], 1, "radarr_status n'a pas lu le plan.jsonl")

        wl = self._call_watchlist()
        self.assertTrue(wl["ok"], f"import_watchlist: {wl.get('message')}")
        self.assertEqual(wl["owned_count"], 1, "import_watchlist n'a pas lu le plan.jsonl")
        self.assertEqual(wl["missing_count"], 0)


class PrefixedRunDirTests(_RunDirTestBase):
    """Disposition de PRODUCTION : `runs/tri_films_<run_id>/plan.jsonl`."""

    def setUp(self) -> None:
        super().setUp()
        self._write_plan(f"tri_films_{_RUN_ID}")

    def test_jellyfin_sync_report_reads_prefixed_run_dir(self) -> None:
        result = self._call_jellyfin()
        self.assertTrue(result["ok"], f"attendu ok, recu : {result.get('message')}")
        self.assertEqual(result["total_local"], 1)

    def test_plex_sync_report_reads_prefixed_run_dir(self) -> None:
        result = self._call_plex()
        self.assertTrue(result["ok"], f"attendu ok, recu : {result.get('message')}")
        self.assertEqual(result["total_local"], 1)

    def test_radarr_status_reads_prefixed_run_dir(self) -> None:
        result = self._call_radarr()
        self.assertTrue(result["ok"], f"attendu ok, recu : {result.get('message')}")
        self.assertEqual(result["total_local"], 1)
        self.assertEqual([f["title"] for f in result["not_in_radarr"]], ["Inception"])

    def test_import_watchlist_reads_prefixed_run_dir(self) -> None:
        result = self._call_watchlist()
        self.assertTrue(result["ok"])
        # Sans le plan.jsonl, Inception serait compte "missing" alors qu'il est
        # dans la bibliotheque : le rapport watchlist mentait en silence.
        self.assertEqual(result["owned_count"], 1)
        self.assertEqual(result["missing_count"], 0)

    def test_all_four_endpoints(self) -> None:
        self._assert_all_endpoints_see_the_film()


class BareRunDirToleranceTests(_RunDirTestBase):
    """Disposition LEGACY : `runs/<run_id>/plan.jsonl` (runs anterieurs a la
    convention). Un prefixe rigide les rendrait invisibles — cf export_support
    et `_resolve_run_dir`, qui retombent tous deux sur le dossier nu."""

    def setUp(self) -> None:
        super().setUp()
        self._write_plan(_RUN_ID)

    def test_jellyfin_sync_report_falls_back_to_bare_run_dir(self) -> None:
        result = self._call_jellyfin()
        self.assertTrue(result["ok"], f"attendu ok, recu : {result.get('message')}")
        self.assertEqual(result["total_local"], 1)

    def test_plex_sync_report_falls_back_to_bare_run_dir(self) -> None:
        result = self._call_plex()
        self.assertTrue(result["ok"], f"attendu ok, recu : {result.get('message')}")
        self.assertEqual(result["total_local"], 1)

    def test_radarr_status_falls_back_to_bare_run_dir(self) -> None:
        result = self._call_radarr()
        self.assertTrue(result["ok"], f"attendu ok, recu : {result.get('message')}")
        self.assertEqual(result["total_local"], 1)

    def test_import_watchlist_falls_back_to_bare_run_dir(self) -> None:
        result = self._call_watchlist()
        self.assertTrue(result["ok"])
        self.assertEqual(result["owned_count"], 1)

    def test_all_four_endpoints(self) -> None:
        self._assert_all_endpoints_see_the_film()


class PrefixedWinsOverBareTests(_RunDirTestBase):
    """Les deux dispositions coexistent : c'est la convention canonique
    (`tri_films_`) qui doit gagner, sinon un dossier nu residuel masquerait le
    plan du run reellement produit."""

    def setUp(self) -> None:
        super().setUp()
        self._write_plan(f"tri_films_{_RUN_ID}")
        # Dossier nu residuel avec un plan.jsonl VIDE : s'il l'emportait, les
        # endpoints retomberaient sur « Aucun film dans ce run. ».
        bare = self.state_dir / "runs" / _RUN_ID
        bare.mkdir(parents=True, exist_ok=True)
        (bare / "plan.jsonl").write_text("", encoding="utf-8")

    def test_all_four_endpoints_prefer_the_prefixed_dir(self) -> None:
        self._assert_all_endpoints_see_the_film()


if __name__ == "__main__":
    unittest.main()
