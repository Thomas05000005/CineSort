# -*- coding: utf-8 -*-
"""E4 + E4-bis (verif totale 2026-07) : force_refresh de get_tmdb_posters.

Le bouton refresh jaquette envoie force_refresh=true depuis 2026-05-24 mais le
parametre n'existait pas cote backend (TypeError => 400, bouton mort). Le
cablage retenu apres revue adversaire (E4-bis) : bypass de LECTURE du cache
dans _get_movie_detail_cached — pas de purge, donc le fallback stale survit si
TMDb est injoignable. Teste ici sans reseau (mock _http_get).
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from cinesort.infra.tmdb_client import TmdbClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.content = b"{}"

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _detail_payload(poster: str):
    return {"id": 42, "title": "Film", "poster_path": poster}


class ForceRefreshBypassTests(unittest.TestCase):
    def _client(self, tmp: str) -> TmdbClient:
        return TmdbClient(api_key="k", cache_path=Path(tmp) / "tmdb_cache.json")

    def test_default_serves_cache_force_refresh_refetches(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmdb = self._client(tmp)
            tmdb._cache_set("movie|42", {"poster_path": "/old.jpg"})
            with patch.object(tmdb, "_http_get", return_value=_FakeResponse(_detail_payload("/new.jpg"))) as http:
                self.assertEqual(tmdb.get_movie_poster_path(42), "/old.jpg")
                http.assert_not_called()
                self.assertEqual(tmdb.get_movie_poster_path(42, force_refresh=True), "/new.jpg")
                http.assert_called_once()

    def test_force_refresh_updates_cache_for_next_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmdb = self._client(tmp)
            tmdb._cache_set("movie|42", {"poster_path": "/old.jpg"})
            with patch.object(tmdb, "_http_get", return_value=_FakeResponse(_detail_payload("/new.jpg"))):
                tmdb.get_movie_poster_path(42, force_refresh=True)
            with patch.object(tmdb, "_http_get") as http:
                self.assertEqual(tmdb.get_movie_poster_path(42), "/new.jpg")
                http.assert_not_called()

    def test_force_refresh_keeps_stale_fallback_on_network_failure(self):
        # E4-bis : la purge preventive (1ere version du fix) detruisait le
        # fallback stale — le bypass de lecture doit le conserver.
        with tempfile.TemporaryDirectory() as tmp:
            tmdb = self._client(tmp)
            tmdb._cache_set("movie|42", {"poster_path": "/old.jpg"})
            with patch.object(tmdb, "_http_get", side_effect=requests.ConnectionError("down")):
                self.assertEqual(tmdb.get_movie_poster_path(42, force_refresh=True), "/old.jpg")

    def test_thumb_url_propagates_force_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmdb = self._client(tmp)
            tmdb._cache_set("movie|42", {"poster_path": "/old.jpg"})
            with patch.object(tmdb, "_http_get", return_value=_FakeResponse(_detail_payload("/new.jpg"))):
                url = tmdb.get_movie_poster_thumb_url(42, size="w185", force_refresh=True)
            self.assertEqual(url, "https://image.tmdb.org/t/p/w185/new.jpg")

    def test_facade_signature_accepts_force_refresh(self):
        import inspect

        from cinesort.ui.api.facades.integrations_facade import IntegrationsFacade

        params = inspect.signature(IntegrationsFacade.get_tmdb_posters).parameters
        self.assertIn("force_refresh", params)
        self.assertIs(params["force_refresh"].default, False)


if __name__ == "__main__":
    unittest.main()
