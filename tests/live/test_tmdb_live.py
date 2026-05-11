from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import live_env
from cinesort.infra.tmdb_client import TmdbClient


class TmdbLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.capability = live_env.require_tmdb_live()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_tmdb_live_")
        self.addCleanup(self._tmp.cleanup)
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"

    def test_validate_key_and_search_movie_live(self) -> None:
        client = TmdbClient(
            api_key=live_env.env_text("CINESORT_TMDB_API_KEY"),
            cache_path=self.cache_path,
            timeout_s=10.0,
        )

        ok, message = client.validate_key()
        self.assertTrue(ok, message)

        results = client.search_movie("Inception", year=2010, language="fr-FR", max_results=5)
        summary = [
            {
                "id": int(item.id),
                "title": str(item.title),
                "year": int(item.year or 0),
                "original_title": str(item.original_title or ""),
            }
            for item in results[:3]
        ]
        self.assertGreaterEqual(len(results), 1, f"Aucun resultat TMDb exploitable. Resume={summary}")
        self.assertTrue(
            any(
                int(item.id) > 0
                and int(item.year or 0) == 2010
                and "inception" in f"{item.title} {item.original_title or ''}".lower()
                for item in results
            ),
            f"Resultats inattendus: {summary}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
