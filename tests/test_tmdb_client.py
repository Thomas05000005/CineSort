from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

from cinesort.infra.tmdb_client import TmdbClient


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: object = None,
        text: str = "",
        raise_exc: Exception | None = None,
    ) -> None:
        self.status_code = int(status_code)
        self._payload = payload
        self.text = text
        self._raise_exc = raise_exc

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self) -> None:
        if self._raise_exc is not None:
            raise self._raise_exc


class TmdbClientCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_tmdb_")
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_flush_forces_save_even_when_throttled(self) -> None:
        client = TmdbClient(api_key="x", cache_path=self.cache_path, timeout_s=1.0)
        client._cache_set("movie|1", {"poster_path": "/a.jpg"})  # type: ignore[attr-defined]
        client._last_save_ts = time.time()  # type: ignore[attr-defined]

        client.flush()

        self.assertTrue(self.cache_path.exists(), str(self.cache_path))
        payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertIn("movie|1", payload)

    def test_throttle_still_applies_without_force(self) -> None:
        client = TmdbClient(api_key="x", cache_path=self.cache_path, timeout_s=1.0)
        client._cache_set("movie|2", {"poster_path": "/b.jpg"})  # type: ignore[attr-defined]
        client._last_save_ts = time.time()  # type: ignore[attr-defined]

        client._save_cache_atomic()  # type: ignore[attr-defined]

        self.assertFalse(self.cache_path.exists(), "Le throttle doit eviter une ecriture immediate sans force.")


class TmdbClientHostileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_tmdb_hostile_")
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"
        self.client = TmdbClient(api_key="demo_key", cache_path=self.cache_path, timeout_s=0.1)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_validate_key_handles_timeout(self) -> None:
        with mock.patch.object(self.client._session, "get", side_effect=requests.Timeout("timeout")):
            ok, message = self.client.validate_key()
        self.assertFalse(ok)
        self.assertIn("Erreur reseau", message)

    def test_validate_key_returns_status_message_on_401(self) -> None:
        response = _FakeResponse(status_code=401, payload={"status_message": "Invalid API key"}, text="bad key")
        with mock.patch.object(self.client._session, "get", return_value=response):
            ok, message = self.client.validate_key()
        self.assertFalse(ok)
        self.assertIn("HTTP 401", message)
        self.assertIn("Invalid API key", message)

    def test_validate_key_falls_back_to_response_text_when_json_is_invalid(self) -> None:
        response = _FakeResponse(
            status_code=429,
            payload=ValueError("bad json"),
            text="rate limit exceeded",
        )
        with mock.patch.object(self.client._session, "get", return_value=response):
            ok, message = self.client.validate_key()
        self.assertFalse(ok)
        self.assertIn("HTTP 429", message)
        self.assertIn("rate limit exceeded", message)

    def test_search_movie_returns_empty_list_on_http_5xx(self) -> None:
        response = _FakeResponse(
            status_code=500,
            payload={"status_message": "server error"},
            raise_exc=requests.HTTPError("500 boom"),
        )
        with mock.patch.object(self.client._session, "get", return_value=response):
            results = self.client.search_movie("Inception", year=2010)
        self.assertEqual(results, [])

    def test_search_movie_returns_empty_list_on_timeout(self) -> None:
        with mock.patch.object(self.client._session, "get", side_effect=requests.Timeout("timeout")):
            results = self.client.search_movie("Inception", year=2010)
        self.assertEqual(results, [])

    def test_search_movie_ignores_non_dict_payload(self) -> None:
        response = _FakeResponse(payload=["not", "a", "dict"])
        with mock.patch.object(self.client._session, "get", return_value=response):
            results = self.client.search_movie("Inception", year=2010)
        self.assertEqual(results, [])

    def test_search_movie_skips_malformed_result_items(self) -> None:
        response = _FakeResponse(
            payload={
                "results": [
                    "bad-item",
                    {"id": "x", "title": "Inception", "release_date": "2010-07-16"},
                    {"id": 42, "title": "Inception", "release_date": "2010-07-16"},
                ]
            }
        )
        with mock.patch.object(self.client._session, "get", return_value=response):
            results = self.client.search_movie("Inception", year=2010)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].id, 0)
        self.assertEqual(results[1].id, 42)

    def test_get_movie_poster_path_returns_none_on_timeout(self) -> None:
        with mock.patch.object(self.client._session, "get", side_effect=requests.Timeout("timeout")):
            poster = self.client.get_movie_poster_path(42)
        self.assertIsNone(poster)

    def test_get_movie_poster_path_returns_none_on_payload_non_dict(self) -> None:
        response = _FakeResponse(payload=["bad"])
        with mock.patch.object(self.client._session, "get", return_value=response):
            poster = self.client.get_movie_poster_path(42)
        self.assertIsNone(poster)

    def test_get_movie_poster_path_uses_cache_after_success(self) -> None:
        response = _FakeResponse(payload={"poster_path": "/x.jpg"})
        with mock.patch.object(self.client._session, "get", return_value=response) as mocked_get:
            first = self.client.get_movie_poster_path(42)
            second = self.client.get_movie_poster_path(42)
        self.assertEqual(first, "/x.jpg")
        self.assertEqual(second, "/x.jpg")
        self.assertEqual(mocked_get.call_count, 1)


class TmdbClientTvTests(unittest.TestCase):
    """Tests pour les methodes TV (search_tv, get_tv_episode_title)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_tmdb_tv_")
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"
        self.client = TmdbClient(api_key="test_key", cache_path=self.cache_path, timeout_s=5.0)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_search_tv_attributes_and_request(self) -> None:
        """Verifie que search_tv utilise les bons attributs et forme la requete correctement."""
        response = _FakeResponse(
            payload={
                "results": [
                    {
                        "id": 1396,
                        "name": "Breaking Bad",
                        "first_air_date": "2008-01-20",
                        "original_name": "Breaking Bad",
                        "popularity": 200.5,
                        "vote_count": 5000,
                        "poster_path": "/bb.jpg",
                    }
                ]
            }
        )
        with mock.patch.object(self.client._session, "get", return_value=response) as mocked:
            results = self.client.search_tv("Breaking Bad")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 1396)
        self.assertEqual(results[0].name, "Breaking Bad")
        self.assertEqual(results[0].first_air_date_year, 2008)
        # Verifie que la requete est bien formee avec api_key et timeout_s
        call_kwargs = mocked.call_args
        self.assertIn("api_key", call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {})))
        self.assertEqual(call_kwargs.kwargs.get("timeout", call_kwargs[1].get("timeout")), 5.0)

    def test_get_tv_episode_title_attributes_and_request(self) -> None:
        """Verifie que get_tv_episode_title utilise les bons attributs et retourne le titre."""
        response = _FakeResponse(payload={"name": "Pilot"})
        with mock.patch.object(self.client._session, "get", return_value=response) as mocked:
            title = self.client.get_tv_episode_title(1396, 1, 1)
        self.assertEqual(title, "Pilot")
        # Verifie l'URL contenant series_id/season/episode
        url = mocked.call_args[0][0]
        self.assertIn("/tv/1396/season/1/episode/1", url)
        # Verifie les params (api_key et timeout)
        call_kwargs = mocked.call_args
        self.assertEqual(call_kwargs.kwargs.get("timeout", call_kwargs[1].get("timeout")), 5.0)

    def test_search_tv_returns_empty_on_network_error(self) -> None:
        with mock.patch.object(self.client._session, "get", side_effect=requests.Timeout("timeout")):
            results = self.client.search_tv("Test")
        self.assertEqual(results, [])

    def test_get_tv_episode_title_returns_none_on_error(self) -> None:
        with mock.patch.object(self.client._session, "get", side_effect=requests.ConnectionError("err")):
            title = self.client.get_tv_episode_title(1, 1, 1)
        self.assertIsNone(title)


if __name__ == "__main__":
    unittest.main(verbosity=2)
