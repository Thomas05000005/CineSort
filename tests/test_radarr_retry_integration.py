"""V2-12 — Verifie RadarrClient utilise retry helper."""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, ".")

from cinesort.infra.radarr_client import RadarrClient


class RadarrRetryTests(unittest.TestCase):
    def test_session_uses_retry_helper(self):
        client = RadarrClient(base_url="http://test:7878", api_key="fake")
        adapter = client._session.get_adapter("http://test:7878")
        retry = adapter.max_retries
        self.assertEqual(retry.total, 3)
        self.assertIn(503, retry.status_forcelist)

    def test_user_agent_set(self):
        client = RadarrClient(base_url="http://test:7878", api_key="fake")
        self.assertIn("CineSort", client._session.headers["User-Agent"])
        self.assertIn("Radarr", client._session.headers["User-Agent"])

    def test_api_key_header_set(self):
        client = RadarrClient(base_url="http://test:7878", api_key="my-radarr-key")
        self.assertEqual(client._session.headers.get("X-Api-Key"), "my-radarr-key")


if __name__ == "__main__":
    unittest.main()
