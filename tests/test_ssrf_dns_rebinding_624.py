"""Issue #624 — SSRF : FQDN resolvant vers une IP interdite + garde a la connexion.

Deux niveaux distincts, testes separement :

1. `is_safe_external_url` resout desormais les FQDN et refuse ceux qui pointent
   vers une IP interdite AU MOMENT DE LA VALIDATION.
2. `SsrfGuardHTTPAdapter` (monte par `make_session_with_retry`) verifie l'adresse
   REELLEMENT jointe par la socket avant qu'un octet ne soit emis — c'est ce
   niveau-la, et lui seul, qui ferme la fenetre de DNS rebinding (TOCTOU).
"""

from __future__ import annotations

import ipaddress
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import requests

from cinesort.infra import network_utils
from cinesort.infra._http_utils import (
    _assert_peer_allowed,
    _SsrfGuardHTTPConnection,
    _SsrfGuardHTTPSConnection,
    make_session_with_retry,
)
from cinesort.infra.network_utils import BlockedAddressError, blocked_ip_reason, is_safe_external_url


class _FakeSocket:
    """Tient le role d'une socket connectee : repond a getpeername() et close()."""

    def __init__(self, peer: object, *, raises: bool = False) -> None:
        self._peer = peer
        self._raises = raises
        self.closed = False

    def getpeername(self) -> object:
        if self._raises:
            raise OSError("socket detachee")
        return self._peer

    def close(self) -> None:
        self.closed = True


class PeerAssertionTests(unittest.TestCase):
    """`_assert_peer_allowed` : verdict + fermeture de la socket refusee."""

    def test_allowed_peer_leaves_socket_open(self) -> None:
        sock = _FakeSocket(("192.168.1.20", 8096))
        _assert_peer_allowed(sock, "jellyfin.home.lan")  # type: ignore[arg-type]
        self.assertFalse(sock.closed)

    def test_blocked_peer_raises_and_closes_socket(self) -> None:
        sock = _FakeSocket(("169.254.169.254", 80))
        with self.assertRaises(BlockedAddressError):
            _assert_peer_allowed(sock, "rebind.attacker.test")  # type: ignore[arg-type]
        self.assertTrue(sock.closed)

    def test_unreadable_peer_raises_and_closes_socket(self) -> None:
        # Fail-closed : si on ne peut pas savoir a qui on parle, on ne parle pas.
        sock = _FakeSocket(None, raises=True)
        with self.assertRaises(BlockedAddressError):
            _assert_peer_allowed(sock, "whatever.test")  # type: ignore[arg-type]
        self.assertTrue(sock.closed)


class BlockedIpPolicyTests(unittest.TestCase):
    """Politique d'adresse, partagee par la validation d'URL et la garde socket."""

    def test_link_local_ipv4_blocked(self) -> None:
        self.assertIn("link-local", blocked_ip_reason("169.254.169.254").lower())

    def test_link_local_ipv6_blocked(self) -> None:
        self.assertIn("link-local", blocked_ip_reason("fe80::1").lower())

    def test_ipv4_mapped_metadata_blocked(self) -> None:
        self.assertNotEqual("", blocked_ip_reason("::ffff:169.254.169.254"))

    def test_aws_ipv6_metadata_ula_blocked(self) -> None:
        # fd00:ec2::254 est une ULA (fc00::/7), PAS une link-local : sans la
        # liste explicite des IP metadata, `is_link_local` seul la laisse passer.
        self.assertIn("metadata", blocked_ip_reason("fd00:ec2::254").lower())

    def test_lan_and_loopback_allowed(self) -> None:
        for addr in ("127.0.0.1", "192.168.1.50", "10.0.0.8", "::1"):
            self.assertEqual("", blocked_ip_reason(addr), addr)

    def test_public_address_allowed(self) -> None:
        self.assertEqual("", blocked_ip_reason("93.184.216.34"))

    def test_unreadable_address_is_refused_fail_closed(self) -> None:
        for bogus in ("", None, "not-an-ip", "999.999.999.999"):
            self.assertNotEqual("", blocked_ip_reason(bogus), repr(bogus))


class FqdnResolutionTests(unittest.TestCase):
    """`is_safe_external_url` : le verdict depend maintenant de la resolution DNS."""

    def test_fqdn_resolving_to_metadata_ip_is_refused(self) -> None:
        with patch.object(network_utils, "_resolve_host_addresses", return_value=["169.254.169.254"]):
            ok, reason = is_safe_external_url("http://rebind.attacker.test/")
        self.assertFalse(ok)
        self.assertIn("interdite", reason.lower())

    def test_fqdn_refused_when_only_one_answer_is_blocked(self) -> None:
        # Round-robin hostile : une IP publique + l'IP metadata. Le refus doit
        # porter des qu'UNE adresse est interdite, pas seulement si toutes le sont.
        with patch.object(
            network_utils,
            "_resolve_host_addresses",
            return_value=["93.184.216.34", "169.254.169.254"],
        ):
            ok, _reason = is_safe_external_url("http://rebind.attacker.test/")
        self.assertFalse(ok)

    def test_fqdn_resolving_to_aws_ipv6_metadata_is_refused(self) -> None:
        with patch.object(network_utils, "_resolve_host_addresses", return_value=["fd00:ec2::254"]):
            ok, _reason = is_safe_external_url("http://rebind.attacker.test/")
        self.assertFalse(ok)

    def test_fqdn_resolving_to_lan_stays_allowed(self) -> None:
        # Politique produit inchangee : l'utilisateur heberge son Jellyfin sur son LAN.
        with patch.object(network_utils, "_resolve_host_addresses", return_value=["192.168.1.42"]):
            ok, _reason = is_safe_external_url("http://jellyfin.home.lan:8096/")
        self.assertTrue(ok)

    def test_resolution_failure_is_logged_not_silent(self) -> None:
        # Choix assume : un nom temporairement non resolvable reste configurable
        # (serveur eteint). Le trou n'est pas silencieux — il est trace — et la
        # garde de connexion reste en vigueur.
        with patch.object(network_utils, "_resolve_host_addresses", side_effect=socket.gaierror("no dns")):
            with self.assertLogs("cinesort.infra.network_utils", level="WARNING") as captured:
                ok, _reason = is_safe_external_url("http://offline.example.test/")
        self.assertTrue(ok)
        self.assertTrue(any("offline.example.test" in line for line in captured.output))

    def test_literal_ip_does_not_trigger_dns(self) -> None:
        with patch.object(network_utils, "_resolve_host_addresses") as resolver:
            is_safe_external_url("http://192.168.1.50:8096")
        resolver.assert_not_called()

    def test_resolve_dns_false_skips_resolution(self) -> None:
        with patch.object(network_utils, "_resolve_host_addresses") as resolver:
            ok, _reason = is_safe_external_url("http://jellyfin.example.com", resolve_dns=False)
        resolver.assert_not_called()
        self.assertTrue(ok)


class _OkHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802 - signature imposee par BaseHTTPRequestHandler
        self.server.seen_paths.append(self.path)  # type: ignore[attr-defined]
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """Silence les logs stderr du serveur de test."""


class ConnectTimeGuardTests(unittest.TestCase):
    """Bout-en-bout : la garde refuse la connexion AVANT d'emettre la requete.

    Un vrai serveur HTTP local sert de temoin : s'il ne voit pas la requete,
    c'est que rien n'a ete emis vers l'adresse refusee.
    """

    def setUp(self) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
        self.httpd.seen_paths = []  # type: ignore[attr-defined]
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        self.session = make_session_with_retry(max_attempts=0)

    def tearDown(self) -> None:
        self.session.close()
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def test_allowed_peer_passes(self) -> None:
        resp = self.session.get(self._url("/allowed"), timeout=5)
        self.assertEqual(200, resp.status_code)
        self.assertIn("/allowed", self.httpd.seen_paths)  # type: ignore[attr-defined]

    def test_blocked_peer_refused_before_any_byte_is_sent(self) -> None:
        # On ne mocke PAS la decision : on ajoute 127.0.0.1 a la LISTE d'IP
        # interdites, et toute la chaine de decision reelle s'execute.
        blocked = frozenset({ipaddress.ip_address("127.0.0.1")})
        with patch.object(network_utils, "_BLOCKED_METADATA_IPS", blocked):
            with self.assertRaises(requests.exceptions.RequestException) as ctx:
                self.session.get(self._url("/blocked"), timeout=5)
        self.assertIn("BlockedAddressError", str(ctx.exception))
        self.assertNotIn("/blocked", self.httpd.seen_paths)  # type: ignore[attr-defined]


class GuardWiringTests(unittest.TestCase):
    """La session partagee doit reellement construire des connexions gardees."""

    def test_pools_use_guarded_connection_classes(self) -> None:
        session = make_session_with_retry()
        try:
            manager = session.get_adapter("http://example.com").poolmanager
            self.assertIs(
                manager.connection_from_url("http://example.com").ConnectionCls,
                _SsrfGuardHTTPConnection,
            )
            self.assertIs(
                manager.connection_from_url("https://example.com").ConnectionCls,
                _SsrfGuardHTTPSConnection,
            )
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
