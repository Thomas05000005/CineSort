"""Tests pour cinesort.infra.network_utils — detection IP locale et URL dashboard."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cinesort.infra.network_utils import build_dashboard_url, get_local_ip


class NetworkUtilsTests(unittest.TestCase):
    """Tests detection IP locale et construction URL."""

    def test_get_local_ip_returns_string(self):
        ip = get_local_ip()
        self.assertIsInstance(ip, str)
        self.assertTrue(len(ip) >= 7)  # au minimum "x.x.x.x"

    def test_get_local_ip_not_empty(self):
        ip = get_local_ip()
        self.assertNotEqual(ip, "")

    def test_get_local_ip_is_valid_format(self):
        ip = get_local_ip()
        parts = ip.split(".")
        self.assertEqual(len(parts), 4, f"IP invalide: {ip}")
        for p in parts:
            self.assertTrue(0 <= int(p) <= 255, f"Octet invalide: {p}")

    @patch("cinesort.infra.network_utils.socket")
    def test_get_local_ip_fallback_hostname(self, mock_socket):
        """Si la technique UDP echoue, fallback sur gethostbyname."""
        # Simuler echec UDP
        mock_udp = mock_socket.socket.return_value.__enter__.return_value
        mock_udp.connect.side_effect = OSError("no route")
        mock_socket.gethostbyname.return_value = "192.168.1.50"
        mock_socket.gethostname.return_value = "myhost"
        mock_socket.error = OSError
        mock_socket.AF_INET = 2
        mock_socket.SOCK_DGRAM = 2
        ip = get_local_ip()
        self.assertEqual(ip, "192.168.1.50")

    @patch("cinesort.infra.network_utils.socket")
    def test_get_local_ip_fallback_localhost(self, mock_socket):
        """Si tout echoue, retourne 127.0.0.1."""
        mock_socket.socket.return_value.__enter__.return_value.connect.side_effect = OSError
        mock_socket.gethostbyname.side_effect = OSError
        mock_socket.gethostname.return_value = "myhost"
        mock_socket.error = OSError
        mock_socket.AF_INET = 2
        mock_socket.SOCK_DGRAM = 2
        ip = get_local_ip()
        self.assertEqual(ip, "127.0.0.1")

    def test_build_dashboard_url_http(self):
        url = build_dashboard_url("192.168.1.10", 8642)
        self.assertEqual(url, "http://192.168.1.10:8642/dashboard/")

    def test_build_dashboard_url_https(self):
        url = build_dashboard_url("10.0.0.5", 9000, https=True)
        self.assertEqual(url, "https://10.0.0.5:9000/dashboard/")

    def test_build_dashboard_url_localhost(self):
        url = build_dashboard_url("127.0.0.1", 8642)
        self.assertEqual(url, "http://127.0.0.1:8642/dashboard/")


class ServerInfoEndpointTests(unittest.TestCase):
    """Tests pour get_server_info et restart_api_server dans CineSortApi."""

    def test_get_server_info_no_server(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi()
        result = api.get_server_info()
        self.assertFalse(result["ok"])
        self.assertIn("non demarre", result["message"])

    def test_get_server_info_with_mock_server(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi()

        class _FakeServer:
            is_running = True
            _port = 8642
            _is_https = False

        api._rest_server = _FakeServer()
        result = api.get_server_info()
        self.assertTrue(result["ok"])
        self.assertIn("dashboard_url", result)
        self.assertIn("8642", result["dashboard_url"])
        self.assertIn("http://", result["dashboard_url"])

    def test_restart_api_no_token(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi()
        # Forcer enabled sans token → echec "aucun token"
        with patch.object(api, "_get_settings_impl", return_value={"rest_api_enabled": True, "rest_api_token": ""}):
            result = api.settings.restart_api_server()
            self.assertFalse(result["ok"])
            self.assertIn("token", result["message"])

    def test_restart_api_disabled(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi()
        with patch.object(api, "_get_settings_impl", return_value={"rest_api_enabled": False}):
            result = api.settings.restart_api_server()
            self.assertFalse(result["ok"])
            self.assertIn("desactivee", result["message"])


if __name__ == "__main__":
    unittest.main()
