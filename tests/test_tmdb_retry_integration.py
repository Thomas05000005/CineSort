"""V2-09 — Verifie que TmdbClient utilise make_session_with_retry (audit ID-ROB-001)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cinesort.infra.tmdb_client import TmdbClient


class TmdbRetryIntegrationTests(unittest.TestCase):
    """Le client TMDb doit s'appuyer sur la Session retry/backoff partagee."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_tmdb_retry_")
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_session_uses_retry_helper(self) -> None:
        """L'adapter HTTPS doit etre configure avec total=3 + status_forcelist 5xx/429."""
        client = TmdbClient(api_key="fake", cache_path=self.cache_path, timeout_s=5.0)
        adapter = client._session.get_adapter("https://api.themoviedb.org")
        retry = adapter.max_retries
        self.assertEqual(retry.total, 3)
        self.assertIn(503, retry.status_forcelist)
        self.assertIn(429, retry.status_forcelist)
        self.assertIn(500, retry.status_forcelist)
        self.assertIn(502, retry.status_forcelist)
        self.assertIn(504, retry.status_forcelist)

    def test_user_agent_set(self) -> None:
        """Le User-Agent doit identifier CineSort + TmdbClient."""
        client = TmdbClient(api_key="fake", cache_path=self.cache_path, timeout_s=5.0)
        ua = client._session.headers.get("User-Agent", "")
        self.assertIn("CineSort", ua)
        self.assertIn("Tmdb", ua)

    def test_backoff_factor_set(self) -> None:
        """Le backoff exponentiel doit etre actif (>0) pour respecter les rate limits."""
        client = TmdbClient(api_key="fake", cache_path=self.cache_path, timeout_s=5.0)
        adapter = client._session.get_adapter("https://api.themoviedb.org")
        retry = adapter.max_retries
        self.assertGreater(retry.backoff_factor, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
