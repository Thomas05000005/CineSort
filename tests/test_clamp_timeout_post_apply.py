"""Issue #434 — `clamp_timeout` sur les chemins post-apply et les rapports d'integration.

Les endpoints de TEST de connexion (test_plex_connection, test_radarr_connection...)
passaient deja par `clamp_timeout`. Les chemins post-apply et les rapports de
synchronisation, eux, lisaient `*_timeout_s` avec un `float()` nu :

- `float(x)` sur une valeur non numerique leve `ValueError` ;
- a `apply_support._make_jellyfin_client` et `cinesort_api._get_jellyfin_libraries_impl`
  l'appel est **hors de tout `try`** : l'exception remonte brute ;
- ailleurs elle est dans un `try` dont l'`except` ne liste que
  `IntegrationError` / `OSError` / `requests.RequestException` (resp.
  `JellyfinError` / `PlexError` / `RadarrError`, tous derives de
  `IntegrationError`, donc **aucun n'attrape `ValueError`**).

`settings_support` borne deja ces cles a [1.0, 60.0] **a l'ecriture** : ces tests
couvrent donc l'exposition residuelle (un `settings.json` edite a la main ou
herite d'une version anterieure a ce clamp) — defense en profondeur.

Chaque site a son test dedie : muter un seul `clamp_timeout` en `float()` nu doit
faire tomber exactement le(s) test(s) de ce site, jamais zero.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cinesort.ui.api.cinesort_api as backend
from cinesort.ui.api.apply_support import (
    _make_jellyfin_client,
    _trigger_plex_refresh,
    refresh_plex_library_now,
)

# Valeur non numerique : `float("abc")` leve ValueError, `clamp_timeout` retombe
# sur le defaut. C'est le cas qui faisait planter le chemin post-apply.
GARBAGE = "abc"
# Valeur numerique hors bornes : `float()` la laisse passer telle quelle
# (thread API bloque ~28 h), `clamp_timeout` la ramene a la borne haute 60.0.
HUGE = 99999


def _write_settings(state_dir: Path, **fields: object) -> None:
    """Ecrit un settings.json brut, sans passer par la normalisation d'ecriture."""
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "settings.json").write_text(json.dumps(fields), encoding="utf-8")


def _timeout_passed(mock_cls: MagicMock) -> float:
    """Extrait le `timeout_s` passe au constructeur du client."""
    mock_cls.assert_called_once()
    return float(mock_cls.call_args.kwargs["timeout_s"])


class ApplySupportClampTimeoutTests(unittest.TestCase):
    """Les 3 sites de refresh post-apply de `apply_support.py`."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_clamp_apply_"))
        self.api = backend.CineSortApi()
        self.api._state_dir = self._tmp  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _plex_settings(self, timeout: object) -> None:
        _write_settings(
            self._tmp,
            plex_enabled=True,
            plex_refresh_on_apply=True,
            plex_url="http://localhost:32400",
            plex_token="tok",
            plex_library_id="42",
            plex_timeout_s=timeout,
        )

    # ---- site 1 : _make_jellyfin_client (hors try : ValueError remontait brute) ----

    def test_make_jellyfin_client_garbage_timeout_falls_back_to_default(self) -> None:
        data = {
            "jellyfin_url": "http://localhost:8096",
            "jellyfin_api_key": "key",
            "jellyfin_timeout_s": GARBAGE,
        }
        with patch("cinesort.ui.api.apply_support.JellyfinClient") as JellyfinCls:
            _make_jellyfin_client(data)
        self.assertEqual(_timeout_passed(JellyfinCls), 10.0)

    def test_make_jellyfin_client_huge_timeout_clamped_to_upper_bound(self) -> None:
        data = {
            "jellyfin_url": "http://localhost:8096",
            "jellyfin_api_key": "key",
            "jellyfin_timeout_s": HUGE,
        }
        with patch("cinesort.ui.api.apply_support.JellyfinClient") as JellyfinCls:
            _make_jellyfin_client(data)
        self.assertEqual(_timeout_passed(JellyfinCls), 60.0)

    # ---- site 2 : _trigger_plex_refresh (except sans ValueError) ----

    def test_trigger_plex_refresh_garbage_timeout_falls_back_to_default(self) -> None:
        self._plex_settings(GARBAGE)
        logs: list[tuple[str, str]] = []
        with patch("cinesort.infra.plex_client.PlexClient") as PlexCls:
            _trigger_plex_refresh(self.api, lambda lvl, msg: logs.append((lvl, msg)), dry_run=False)
        self.assertEqual(_timeout_passed(PlexCls), 10.0)

    def test_trigger_plex_refresh_huge_timeout_clamped_to_upper_bound(self) -> None:
        self._plex_settings(HUGE)
        logs: list[tuple[str, str]] = []
        with patch("cinesort.infra.plex_client.PlexClient") as PlexCls:
            _trigger_plex_refresh(self.api, lambda lvl, msg: logs.append((lvl, msg)), dry_run=False)
        self.assertEqual(_timeout_passed(PlexCls), 60.0)

    # ---- site 3 : refresh_plex_library_now (except sans ValueError) ----

    def test_refresh_plex_library_now_garbage_timeout_falls_back_to_default(self) -> None:
        self._plex_settings(GARBAGE)
        with patch("cinesort.infra.plex_client.PlexClient") as PlexCls:
            result = refresh_plex_library_now(self.api)
        self.assertEqual(_timeout_passed(PlexCls), 10.0)
        # Le refresh doit reussir, pas remonter une ValueError ni un ok=False.
        self.assertTrue(result["ok"])

    def test_refresh_plex_library_now_huge_timeout_clamped_to_upper_bound(self) -> None:
        self._plex_settings(HUGE)
        with patch("cinesort.infra.plex_client.PlexClient") as PlexCls:
            result = refresh_plex_library_now(self.api)
        self.assertEqual(_timeout_passed(PlexCls), 60.0)
        self.assertTrue(result["ok"])


class CineSortApiClampTimeoutTests(unittest.TestCase):
    """Les 5 sites de `cinesort_api.py` (elargissement de la portee)."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_clamp_api_"))
        self.state_dir = self._tmp / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _plan_run(self, run_id: str = "run1") -> MagicMock:
        """Cree un run DONE avec une PlanRow, et retourne le store mocke."""
        run_dir = self.state_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "plan.jsonl").write_text(json.dumps({"row_id": "r1"}) + "\n", encoding="utf-8")
        store = MagicMock()
        store.run.get_runs_summary.return_value = [{"run_id": run_id, "status": "DONE"}]
        return store

    # ---- site 4 : _get_jellyfin_libraries_impl (hors try) ----

    def test_get_jellyfin_libraries_garbage_timeout_falls_back_to_default(self) -> None:
        _write_settings(
            self.state_dir,
            jellyfin_url="http://localhost:8096",
            jellyfin_api_key="key",
            jellyfin_user_id="u1",
            jellyfin_timeout_s=GARBAGE,
        )
        with patch("cinesort.infra.jellyfin_client.JellyfinClient") as JellyfinCls:
            JellyfinCls.return_value = MagicMock()
            self.api.integrations.get_jellyfin_libraries()
        self.assertEqual(_timeout_passed(JellyfinCls), 10.0)

    # ---- site 5 : _get_jellyfin_sync_report_impl (except JellyfinError) ----

    @patch.object(backend.CineSortApi, "_get_settings_impl")
    @patch("cinesort.infra.jellyfin_client.JellyfinClient")
    def test_get_jellyfin_sync_report_garbage_timeout_falls_back_to_default(
        self, JellyfinCls: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.return_value = {
            "jellyfin_enabled": True,
            "jellyfin_url": "http://localhost:8096",
            "jellyfin_api_key": "key",
            "jellyfin_user_id": "u1",
            "jellyfin_timeout_s": GARBAGE,
        }
        JellyfinCls.return_value = MagicMock()
        store = self._plan_run()
        with patch.object(self.api, "_get_or_create_infra", return_value=(store, MagicMock())):
            self.api.integrations.get_jellyfin_sync_report(run_id="run1")
        self.assertEqual(_timeout_passed(JellyfinCls), 10.0)

    # ---- site 6 : _get_plex_sync_report_impl (except PlexError) ----

    @patch.object(backend.CineSortApi, "_get_settings_impl")
    @patch("cinesort.infra.plex_client.PlexClient")
    def test_get_plex_sync_report_garbage_timeout_falls_back_to_default(
        self, PlexCls: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.return_value = {
            "plex_enabled": True,
            "plex_url": "http://localhost:32400",
            "plex_token": "tok",
            "plex_library_id": "42",
            "plex_timeout_s": GARBAGE,
        }
        PlexCls.return_value = MagicMock()
        store = self._plan_run()
        with patch.object(self.api, "_get_or_create_infra", return_value=(store, MagicMock())):
            self.api.integrations.get_plex_sync_report(run_id="run1")
        self.assertEqual(_timeout_passed(PlexCls), 10.0)

    # ---- site 7 : _get_radarr_status_impl (except RadarrError) ----

    @patch.object(backend.CineSortApi, "_get_settings_impl")
    @patch("cinesort.infra.radarr_client.RadarrClient")
    def test_get_radarr_status_garbage_timeout_falls_back_to_default(
        self, RadarrCls: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.return_value = {
            "radarr_enabled": True,
            "radarr_url": "http://localhost:7878",
            "radarr_api_key": "key",
            "radarr_timeout_s": GARBAGE,
        }
        RadarrCls.return_value = MagicMock()
        store = self._plan_run()
        with patch.object(self.api, "_get_or_create_infra", return_value=(store, MagicMock())):
            self.api.integrations.get_radarr_status(run_id="run1")
        self.assertEqual(_timeout_passed(RadarrCls), 10.0)

    # ---- site 8 : _request_radarr_upgrade_impl (except RadarrError) ----

    @patch.object(backend.CineSortApi, "_get_settings_impl")
    @patch("cinesort.infra.radarr_client.RadarrClient")
    def test_request_radarr_upgrade_garbage_timeout_falls_back_to_default(
        self, RadarrCls: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.return_value = {
            "radarr_enabled": True,
            "radarr_url": "http://localhost:7878",
            "radarr_api_key": "key",
            "radarr_timeout_s": GARBAGE,
        }
        RadarrCls.return_value = MagicMock()
        result = self.api.integrations.request_radarr_upgrade(radarr_movie_id=7)
        self.assertEqual(_timeout_passed(RadarrCls), 10.0)
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
