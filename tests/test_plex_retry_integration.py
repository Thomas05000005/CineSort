"""V2-11 — Verifie PlexClient utilise make_session_with_retry (audit ID-ROB-001)."""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, ".")

from cinesort.infra.plex_client import PlexClient


class PlexRetryTests(unittest.TestCase):
    def test_session_uses_retry_helper(self) -> None:
        client = PlexClient(base_url="http://test:32400", token="fake")
        adapter = client._session.get_adapter("http://test:32400")
        retry = adapter.max_retries
        self.assertEqual(retry.total, 3)
        self.assertIn(503, retry.status_forcelist)
        self.assertIn(429, retry.status_forcelist)

    def test_user_agent_set(self) -> None:
        client = PlexClient(base_url="http://test:32400", token="fake")
        ua = client._session.headers.get("User-Agent", "")
        self.assertIn("CineSort", ua)
        self.assertIn("Plex", ua)

    def test_plex_token_header_set(self) -> None:
        client = PlexClient(base_url="http://test:32400", token="my-token-123")
        self.assertEqual(client._session.headers.get("X-Plex-Token"), "my-token-123")

    def test_plex_default_headers_preserved(self) -> None:
        client = PlexClient(base_url="http://test:32400", token="tok")
        self.assertEqual(client._session.headers.get("X-Plex-Product"), "CineSort")
        self.assertEqual(client._session.headers.get("X-Plex-Client-Identifier"), "cinesort-desktop")


if __name__ == "__main__":
    unittest.main()
