"""V2-10 — Verifie JellyfinClient utilise make_session_with_retry (audit ID-ROB-001)."""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, ".")

from cinesort.infra.jellyfin_client import JellyfinClient


class JellyfinRetryTests(unittest.TestCase):
    def test_session_uses_retry_helper(self):
        client = JellyfinClient(base_url="http://test", api_key="fake")
        adapter = client._session.get_adapter("http://test")
        retry = adapter.max_retries
        self.assertEqual(retry.total, 3)
        self.assertIn(503, retry.status_forcelist)

    def test_user_agent_set(self):
        client = JellyfinClient(base_url="http://test", api_key="fake")
        self.assertIn("CineSort", client._session.headers["User-Agent"])
        self.assertIn("Jellyfin", client._session.headers["User-Agent"])

    def test_auth_header_preserved(self):
        """L'auth header MediaBrowser doit etre preserve apres migration Session."""
        client = JellyfinClient(base_url="http://test", api_key="fake-key-123")
        self.assertIn('Token="fake-key-123"', client._session.headers["Authorization"])
        self.assertIn("MediaBrowser", client._session.headers["Authorization"])
        self.assertEqual(client._session.headers["X-Emby-Token"], "fake-key-123")


if __name__ == "__main__":
    unittest.main()
