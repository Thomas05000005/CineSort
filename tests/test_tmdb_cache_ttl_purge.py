"""V5-03 polish v7.7.0 (R5-STRESS-4) — tests purge auto cache TMDb + TTL configurable.

Verifie que :
- purge_expired_tmdb_cache supprime les entrees expirees, conserve les fraiches
- Les entrees ancien format (sans _cached_at) sont preservees (backward compat)
- Le clamp [1, 365] du TTL fonctionne
- Le fallback graceful (cache stale si API fail) fonctionne via _cache_get_stale
- Le TTL configurable au niveau du client fonctionne
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

from cinesort.infra.tmdb_client import (
    DEFAULT_CACHE_TTL_DAYS,
    MAX_CACHE_TTL_DAYS,
    MIN_CACHE_TTL_DAYS,
    TmdbClient,
    _clamp_ttl_days,
    _ttl_for_key,
    purge_expired_tmdb_cache,
)


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, payload: object = None) -> None:
        self.status_code = int(status_code)
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class ClampTtlDaysTests(unittest.TestCase):
    def test_default_when_none(self) -> None:
        self.assertEqual(_clamp_ttl_days(None), DEFAULT_CACHE_TTL_DAYS)

    def test_clamp_lower_bound(self) -> None:
        self.assertEqual(_clamp_ttl_days(0), MIN_CACHE_TTL_DAYS)
        self.assertEqual(_clamp_ttl_days(-100), MIN_CACHE_TTL_DAYS)

    def test_clamp_upper_bound(self) -> None:
        self.assertEqual(_clamp_ttl_days(10000), MAX_CACHE_TTL_DAYS)

    def test_pass_through_valid(self) -> None:
        self.assertEqual(_clamp_ttl_days(60), 60)

    def test_invalid_type_returns_default(self) -> None:
        self.assertEqual(_clamp_ttl_days("garbage"), DEFAULT_CACHE_TTL_DAYS)


class TtlForKeyConfigurableTests(unittest.TestCase):
    def test_uses_configured_ttl_for_long(self) -> None:
        # 90 jours -> 90 * 86400 secs pour les lookups deterministes
        self.assertEqual(_ttl_for_key("movie|123", ttl_days=90), 90 * 24 * 3600)

    def test_uses_quarter_for_search_when_configured(self) -> None:
        # search est 1/4 du TTL principal (proportion 30j/7j historique)
        self.assertEqual(_ttl_for_key("search|fr|x", ttl_days=40), 10 * 24 * 3600)

    def test_search_min_one_day_when_ttl_small(self) -> None:
        # Avec TTL 1 jour, search doit etre au moins 1 jour (pas zero)
        self.assertGreaterEqual(_ttl_for_key("search|fr|x", ttl_days=1), 24 * 3600)


class PurgeExpiredCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_purge_")
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_cache(self, data: dict) -> None:
        self.cache_path.write_text(json.dumps(data), encoding="utf-8")

    def test_no_cache_file_returns_zero(self) -> None:
        result = purge_expired_tmdb_cache(self.cache_path, ttl_days=30)
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["purged"], 0)
        self.assertIsNone(result["error"])

    def test_fresh_entries_preserved(self) -> None:
        now = time.time()
        self._write_cache(
            {
                "movie|1": {"_cached_at": now, "value": {"poster_path": "/a.jpg"}},
                "movie|2": {"_cached_at": now - 3600, "value": {"poster_path": "/b.jpg"}},
            }
        )
        result = purge_expired_tmdb_cache(self.cache_path, ttl_days=30)
        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["purged"], 0)

    def test_expired_entries_purged(self) -> None:
        now = time.time()
        old = now - (40 * 24 * 3600)  # 40 jours -> expire pour TTL 30
        self._write_cache(
            {
                "movie|1": {"_cached_at": now, "value": {"poster_path": "/a.jpg"}},
                "movie|2": {"_cached_at": old, "value": {"poster_path": "/b.jpg"}},
            }
        )
        result = purge_expired_tmdb_cache(self.cache_path, ttl_days=30)
        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["purged"], 1)

        # Verifier que le fichier a bien ete reecrit
        on_disk = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertIn("movie|1", on_disk)
        self.assertNotIn("movie|2", on_disk)

    def test_legacy_entries_preserved(self) -> None:
        """Backward compat : entrees sans _cached_at = TTL infini."""
        old = time.time() - (40 * 24 * 3600)
        self._write_cache(
            {
                "movie|legacy": {"poster_path": "/old.jpg"},  # Ancien format direct
                "movie|expired": {"_cached_at": old, "value": {"poster_path": "/exp.jpg"}},
            }
        )
        result = purge_expired_tmdb_cache(self.cache_path, ttl_days=30)
        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["purged"], 1)
        self.assertEqual(result["preserved_legacy"], 1)

        on_disk = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertIn("movie|legacy", on_disk)
        self.assertNotIn("movie|expired", on_disk)

    def test_no_purge_no_disk_write(self) -> None:
        """Si rien a purger, on n'ecrit pas le fichier (preserve mtime)."""
        now = time.time()
        self._write_cache({"movie|1": {"_cached_at": now, "value": {}}})
        original_mtime = self.cache_path.stat().st_mtime_ns
        time.sleep(0.05)
        result = purge_expired_tmdb_cache(self.cache_path, ttl_days=30)
        self.assertEqual(result["purged"], 0)
        new_mtime = self.cache_path.stat().st_mtime_ns
        self.assertEqual(original_mtime, new_mtime)

    def test_corrupt_json_returns_error(self) -> None:
        self.cache_path.write_text("not valid json {{{", encoding="utf-8")
        result = purge_expired_tmdb_cache(self.cache_path, ttl_days=30)
        self.assertIsNotNone(result["error"])
        self.assertIn("parse_error", result["error"])

    def test_ttl_clamp_applied(self) -> None:
        """Un ttl_days hors bornes doit etre clamp."""
        old = time.time() - (2 * 24 * 3600)  # 2 jours
        self._write_cache(
            {"movie|1": {"_cached_at": old, "value": {}}}
        )
        # ttl_days = 0 -> clamp a 1 jour. 2 jours d'age > 1 jour -> purge.
        result = purge_expired_tmdb_cache(self.cache_path, ttl_days=0)
        self.assertEqual(result["purged"], 1)

    def test_search_keys_use_shorter_ttl(self) -> None:
        """search|... a un TTL plus court que movie|... (1/4)."""
        # 10 jours d'age, ttl_days=30 -> long_ttl=30j (movie OK), short_ttl=7.5j (search expire)
        ten_days_ago = time.time() - (10 * 24 * 3600)
        self._write_cache(
            {
                "movie|1": {"_cached_at": ten_days_ago, "value": {}},
                "search|fr-FR|inception|2010": {"_cached_at": ten_days_ago, "value": []},
            }
        )
        result = purge_expired_tmdb_cache(self.cache_path, ttl_days=30)
        self.assertEqual(result["purged"], 1)  # seul search a ete purge
        on_disk = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertIn("movie|1", on_disk)
        self.assertNotIn("search|fr-FR|inception|2010", on_disk)


class TmdbClientConfigurableTtlTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_tmdb_ttl_")
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_client_accepts_ttl_days_param(self) -> None:
        client = TmdbClient(api_key="x", cache_path=self.cache_path, cache_ttl_days=60)
        self.assertEqual(client.cache_ttl_days, 60)

    def test_client_clamps_ttl_days(self) -> None:
        client = TmdbClient(api_key="x", cache_path=self.cache_path, cache_ttl_days=10000)
        self.assertEqual(client.cache_ttl_days, MAX_CACHE_TTL_DAYS)

    def test_client_default_ttl_days_none(self) -> None:
        """Par defaut, cache_ttl_days=None -> utilise TTL historique."""
        client = TmdbClient(api_key="x", cache_path=self.cache_path)
        self.assertIsNone(client.cache_ttl_days)

    def test_cache_get_respects_configured_ttl(self) -> None:
        """Avec ttl_days=2, une entree de 5 jours doit etre invalidee."""
        client = TmdbClient(api_key="x", cache_path=self.cache_path, cache_ttl_days=2)
        old = time.time() - (5 * 24 * 3600)
        client._cache["movie|123"] = {"_cached_at": old, "value": {"poster_path": "/x.jpg"}}
        # ttl_days=2 -> long_ttl=2j -> 5j d'age = expire
        self.assertIsNone(client._cache_get("movie|123"))


class TmdbClientStaleFallbackTests(unittest.TestCase):
    """Verifie le fallback graceful : si API echoue, utiliser cache meme expire."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_stale_")
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_get_movie_detail_falls_back_to_stale_on_api_error(self) -> None:
        client = TmdbClient(api_key="x", cache_path=self.cache_path, cache_ttl_days=30)
        # Pre-seed une entree expiree (40 jours d'age, TTL 30) -> _cache_get returns None
        # mais on l'a aussi sur le disque pour _cache_get_stale.
        old = time.time() - (40 * 24 * 3600)
        stale_value = {"poster_path": "/stale.jpg", "collection_id": None, "collection_name": None}
        client._cache["movie|999"] = {"_cached_at": old, "value": stale_value}
        client._dirty = True
        client._save_cache_atomic(force=True)
        # Re-init pour bien partir du disque
        client2 = TmdbClient(api_key="x", cache_path=self.cache_path, cache_ttl_days=30)

        # Mock l'API : echec network
        with mock.patch.object(
            client2._session,
            "get",
            side_effect=requests.ConnectionError("network down"),
        ):
            result = client2._get_movie_detail_cached(999)

        self.assertEqual(result, stale_value, "Fallback graceful: doit retourner le cache expire")

    def test_search_falls_back_to_stale_on_api_error(self) -> None:
        client = TmdbClient(api_key="x", cache_path=self.cache_path, cache_ttl_days=30)
        # Pre-seed : search expiree (8 jours, TTL search = 7.5j a TTL=30)
        old = time.time() - (8 * 24 * 3600)
        # Format en cache : liste de dict (TmdbResult.__dict__)
        stale_results = [
            {
                "id": 1,
                "title": "Stale Movie",
                "year": 2020,
                "original_title": "Stale Movie",
                "popularity": 1.0,
                "vote_count": 100,
                "vote_average": 7.5,
                "poster_path": "/p.jpg",
            }
        ]
        cache_key = "search|fr-FR|inception|2010"
        client._cache[cache_key] = {"_cached_at": old, "value": stale_results}
        client._dirty = True
        client._save_cache_atomic(force=True)

        client2 = TmdbClient(api_key="x", cache_path=self.cache_path, cache_ttl_days=30)
        with mock.patch.object(
            client2._session,
            "get",
            side_effect=requests.Timeout("api timeout"),
        ):
            results = client2.search_movie("inception", year=2010)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Stale Movie")

    def test_no_fallback_if_no_cache(self) -> None:
        """Pas de cache stale -> retourne resultat vide normal."""
        client = TmdbClient(api_key="x", cache_path=self.cache_path, cache_ttl_days=30)
        with mock.patch.object(
            client._session,
            "get",
            side_effect=requests.Timeout("timeout"),
        ):
            results = client.search_movie("nonexistent")
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
