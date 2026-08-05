"""Issue #539 — borne de taille a la LECTURE DISQUE des caches JSON.

A ne pas confondre avec les bornes de reponse RESEAU (qui bornent un corps
HTTP en flux). Ici le fichier est LOCAL et relu au demarrage : un cache
corrompu, gonfle, ou remplace par un lien vers autre chose serait charge
INTEGRALEMENT en RAM par `read_text()` avant meme le parse JSON (CWE-400).

Les caps « nombre d'entrees » (_TMDB_CACHE_MAX_ENTRIES / _CACHE_MAX_ENTRIES)
n'aident pas : ils agissent APRES deserialisation.

Sites couverts (les 4 lectures de cache disque de l'issue) :
- TmdbClient._load_cache
- TmdbClient._cache_get_stale
- purge_expired_tmdb_cache (module-level, tourne au boot)
- OmdbClient._load_cache
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cinesort.infra.omdb_client as omdb_mod
import cinesort.infra.tmdb_client as tmdb_mod
from cinesort.infra.fs_safety import FileTooLargeError, read_text_bounded
from cinesort.infra.omdb_client import OmdbClient
from cinesort.infra.tmdb_client import TmdbClient, purge_expired_tmdb_cache

# Borne minuscule utilisee dans les tests : ecrire 50/100 MB reels serait
# absurde. On patche la constante du module, le mecanisme teste est le meme.
_TINY_LIMIT = 512


def _write_json_bigger_than(path: Path, limit: int, *, key: str = "movie|1") -> int:
    """Ecrit un cache JSON VALIDE dont la taille depasse `limit`."""
    payload = {key: {"_cached_at": 4_102_444_800.0, "value": {"blob": "x" * (limit * 4)}}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    size = path.stat().st_size
    assert size > limit, f"fixture invalide : {size} <= {limit}"
    return size


class ReadTextBoundedTests(unittest.TestCase):
    """Le helper mutualise lui-meme (fs_safety.read_text_bounded)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "data.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reads_file_under_limit(self) -> None:
        self.path.write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(read_text_bounded(self.path, max_bytes=_TINY_LIMIT), '{"a": 1}')

    def test_raises_over_limit(self) -> None:
        _write_json_bigger_than(self.path, _TINY_LIMIT)
        with self.assertRaises(FileTooLargeError):
            read_text_bounded(self.path, max_bytes=_TINY_LIMIT)

    def test_refuses_before_opening_the_file(self) -> None:
        """Le coeur du correctif : on n'OUVRE meme pas le fichier trop gros.

        Borner apres coup ne servirait a rien — c'est `read_text()` qui alloue
        la RAM. `open` est neutralise : s'il est appele, le test explose.
        """
        _write_json_bigger_than(self.path, _TINY_LIMIT)
        with patch("builtins.open", side_effect=AssertionError("fichier ouvert malgre la borne")):
            with self.assertRaises(FileTooLargeError):
                read_text_bounded(self.path, max_bytes=_TINY_LIMIT)

    def test_file_too_large_is_an_oserror(self) -> None:
        """Les `except OSError` deja en place doivent la rattraper telle quelle."""
        self.assertTrue(issubclass(FileTooLargeError, OSError))


class TmdbCacheDiskSizeLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"
        self._patch = patch.object(tmdb_mod, "_TMDB_CACHE_MAX_BYTES", _TINY_LIMIT)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _client(self) -> TmdbClient:
        return TmdbClient(api_key="x", cache_path=self.cache_path, timeout_s=1.0)

    def test_load_cache_discards_oversized_file(self) -> None:
        _write_json_bigger_than(self.cache_path, _TINY_LIMIT)
        client = self._client()
        self.assertEqual(dict(client._cache), {})

    def test_load_cache_still_reads_a_normal_file(self) -> None:
        """Garde-fou anti-regression : la borne ne doit pas tout jeter."""
        self.cache_path.write_text(json.dumps({"movie|1": {"ok": True}}), encoding="utf-8")
        client = self._client()
        self.assertIn("movie|1", client._cache)

    def test_cache_get_stale_refuses_oversized_file(self) -> None:
        """Fallback stale : relit le DISQUE, donc borne lui aussi."""
        _write_json_bigger_than(self.cache_path, _TINY_LIMIT)
        client = self._client()
        client._cache.clear()  # force le chemin « relecture disque »
        self.assertIsNone(client._cache_get_stale("movie|1"))

    def test_cache_get_stale_reads_a_normal_file(self) -> None:
        self.cache_path.write_text(
            json.dumps({"movie|1": {"_cached_at": 4_102_444_800.0, "value": {"id": 1}}}),
            encoding="utf-8",
        )
        client = self._client()
        client._cache.clear()
        self.assertEqual(client._cache_get_stale("movie|1"), {"id": 1})

    def test_purge_reports_error_instead_of_silent_success(self) -> None:
        """Un refus de lecture ne doit JAMAIS passer pour une purge reussie."""
        _write_json_bigger_than(self.cache_path, _TINY_LIMIT)
        result = purge_expired_tmdb_cache(self.cache_path, ttl_days=30)
        self.assertTrue(result.get("error"), "purge silencieusement 'reussie' sur un cache refuse")
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["purged"], 0)


class OmdbCacheDiskSizeLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_path = Path(self._tmp.name) / "omdb_cache.json"
        self._patch = patch.object(omdb_mod, "_CACHE_MAX_BYTES", _TINY_LIMIT)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _client(self) -> OmdbClient:
        return OmdbClient(api_key="x", cache_path=self.cache_path, timeout_s=1.0)

    def test_load_cache_discards_oversized_file(self) -> None:
        _write_json_bigger_than(self.cache_path, _TINY_LIMIT, key="tt0111161")
        client = self._client()
        self.assertEqual(client._cache, {})

    def test_load_cache_still_reads_a_normal_file(self) -> None:
        self.cache_path.write_text(json.dumps({"tt0111161": {"_ts": 1.0}}), encoding="utf-8")
        client = self._client()
        self.assertIn("tt0111161", client._cache)


class DefaultLimitsTests(unittest.TestCase):
    """Les bornes par defaut restent tres au-dessus d'un cache legitime."""

    def test_tmdb_default_limit(self) -> None:
        self.assertEqual(tmdb_mod._TMDB_CACHE_MAX_BYTES, 100 * 1024 * 1024)

    def test_omdb_default_limit(self) -> None:
        self.assertEqual(omdb_mod._CACHE_MAX_BYTES, 50 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
