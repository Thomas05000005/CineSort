"""Tests pour les fixes perf #78 (find_main_video skip) et #75 (TMDb cache LRU)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.infra.tmdb_client import _TMDB_CACHE_MAX_ENTRIES, TmdbClient


class TmdbCacheLruCapTests(unittest.TestCase):
    """Issue #75 : cache TMDb cap LRU."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_tmdb_cache_"))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_cache_eviction_keeps_max_entries(self) -> None:
        """_cache_set au-dela de MAX_ENTRIES doit evict les plus anciennes."""
        client = TmdbClient(api_key="fake", cache_path=self._tmp / "tmdb_cache.json")
        # Override le max pour le test (sinon 100k iterations c'est lent)
        from cinesort.infra import tmdb_client as mod

        original = mod._TMDB_CACHE_MAX_ENTRIES
        mod._TMDB_CACHE_MAX_ENTRIES = 5
        try:
            for i in range(20):
                client._cache_set(f"key_{i}", {"data": i})
            # Doit contenir au plus 5 entrees (les 5 dernieres : 15-19)
            self.assertEqual(len(client._cache), 5)
            self.assertIn("key_19", client._cache)
            self.assertNotIn("key_0", client._cache)
            self.assertNotIn("key_10", client._cache)
        finally:
            mod._TMDB_CACHE_MAX_ENTRIES = original

    def test_cache_lru_move_to_end_on_set(self) -> None:
        """Re-set une cle existante doit la deplacer en fin (LRU bump)."""
        client = TmdbClient(api_key="fake", cache_path=self._tmp / "tmdb_cache.json")
        from cinesort.infra import tmdb_client as mod

        original = mod._TMDB_CACHE_MAX_ENTRIES
        mod._TMDB_CACHE_MAX_ENTRIES = 3
        try:
            client._cache_set("a", {"v": 1})
            client._cache_set("b", {"v": 2})
            client._cache_set("c", {"v": 3})
            # Re-set "a" -> il devient le plus recent
            client._cache_set("a", {"v": 1.1})
            # Ajout "d" -> doit evict "b" (le plus ancien apres bump de "a")
            client._cache_set("d", {"v": 4})
            self.assertIn("a", client._cache)
            self.assertNotIn("b", client._cache)
            self.assertIn("c", client._cache)
            self.assertIn("d", client._cache)
        finally:
            mod._TMDB_CACHE_MAX_ENTRIES = original

    def test_cache_load_prunes_oversized_cache(self) -> None:
        """Si on charge un cache pre-existant > MAX, on garde les dernieres entrees."""
        import json

        cache_path = self._tmp / "tmdb_cache.json"
        # Simule un cache historique sans cap
        oversized = {f"key_{i}": {"v": i} for i in range(50)}
        cache_path.write_text(json.dumps(oversized), encoding="utf-8")

        from cinesort.infra import tmdb_client as mod

        original = mod._TMDB_CACHE_MAX_ENTRIES
        mod._TMDB_CACHE_MAX_ENTRIES = 10
        try:
            client = TmdbClient(api_key="fake", cache_path=cache_path)
            self.assertLessEqual(len(client._cache), 10)
            # Les dernieres entrees JSON doivent etre conservees
            self.assertIn("key_49", client._cache)
            self.assertNotIn("key_0", client._cache)
        finally:
            mod._TMDB_CACHE_MAX_ENTRIES = original

    def test_max_entries_constant_reasonable(self) -> None:
        """Sanity check sur la constante."""
        self.assertGreater(_TMDB_CACHE_MAX_ENTRIES, 1000)
        self.assertLess(_TMDB_CACHE_MAX_ENTRIES, 10_000_000)


class ApplySingleMainVideoFilenameTests(unittest.TestCase):
    """Issue #78 : apply_single accepte main_video_filename pour skipper find_main_video_in_folder."""

    def test_apply_single_signature_has_main_video_filename_kwarg(self) -> None:
        """apply_single doit avoir le kwarg main_video_filename."""
        import inspect

        from cinesort.app.apply_core import apply_single

        sig = inspect.signature(apply_single)
        self.assertIn("main_video_filename", sig.parameters)
        # Defaut None pour backward compat
        self.assertIsNone(sig.parameters["main_video_filename"].default)

    def test_caller_passes_row_video(self) -> None:
        """Verification statique : le caller dans apply_core passe row.video."""
        src = (Path(__file__).resolve().parents[1] / "cinesort" / "app" / "apply_core.py").read_text(encoding="utf-8")
        self.assertIn('main_video_filename=getattr(row, "video", None)', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
