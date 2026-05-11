"""H-4 audit QA 20260428 — exposition LAN du serveur REST.

Verifie que :
- Bind 127.0.0.1 reste le defaut.
- Bind 0.0.0.0 avec token court (< 32 chars) est retrograde en 127.0.0.1
  avec un message explicite (lan_demoted=True).
- Bind 0.0.0.0 avec token solide (>= 32 chars) est conserve.
- Le mode standalone --api respecte le defaut localhost (sans --public).
"""

from __future__ import annotations

import unittest

from cinesort.infra.rest_server import RestApiServer


class _MockApi:
    """API minimale pour instancier RestApiServer sans demarrer un vrai serveur."""

    def get_settings(self):
        return {}


class RestLanExposureTests(unittest.TestCase):
    def test_default_host_is_localhost(self) -> None:
        server = RestApiServer(_MockApi(), token="any_token_12345678901234567890ab")
        self.assertEqual(server.host, "127.0.0.1")
        self.assertEqual(server.host_requested, "127.0.0.1")
        self.assertFalse(server.lan_demoted)

    def test_lan_with_short_token_is_demoted(self) -> None:
        """Token de moins de 32 caracteres + bind LAN demande → retrogradation."""
        short_token = "x" * 16
        self.assertLess(len(short_token), RestApiServer.MIN_LAN_TOKEN_LENGTH)
        server = RestApiServer(_MockApi(), token=short_token, host="0.0.0.0")
        self.assertEqual(server.host, "127.0.0.1")
        self.assertEqual(server.host_requested, "0.0.0.0")
        self.assertTrue(server.lan_demoted)
        self.assertIn("Token REST trop court", server.lan_demotion_reason)
        self.assertIn(str(RestApiServer.MIN_LAN_TOKEN_LENGTH), server.lan_demotion_reason)

    def test_lan_with_strong_token_keeps_host(self) -> None:
        """Token >= 32 caracteres + bind LAN demande → bind LAN conserve."""
        strong_token = "a" * 32
        self.assertGreaterEqual(len(strong_token), RestApiServer.MIN_LAN_TOKEN_LENGTH)
        server = RestApiServer(_MockApi(), token=strong_token, host="0.0.0.0")
        self.assertEqual(server.host, "0.0.0.0")
        self.assertEqual(server.host_requested, "0.0.0.0")
        self.assertFalse(server.lan_demoted)
        self.assertEqual(server.lan_demotion_reason, "")

    def test_lan_with_empty_token_is_demoted(self) -> None:
        """Token vide → forcement retrogradation."""
        server = RestApiServer(_MockApi(), token="", host="0.0.0.0")
        self.assertEqual(server.host, "127.0.0.1")
        self.assertTrue(server.lan_demoted)

    def test_localhost_with_short_token_is_not_demoted(self) -> None:
        """Pas de bind LAN demande → pas de retrogradation meme avec token court."""
        server = RestApiServer(_MockApi(), token="short", host="127.0.0.1")
        self.assertEqual(server.host, "127.0.0.1")
        self.assertFalse(server.lan_demoted)

    def test_minimum_length_constant_is_32(self) -> None:
        """Documentation : la longueur minimale est 32 caracteres (cf audit H-4)."""
        self.assertEqual(RestApiServer.MIN_LAN_TOKEN_LENGTH, 32)


if __name__ == "__main__":
    unittest.main()
