"""Tests pour le QR code dashboard (segno integration)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cinesort.ui.api.cinesort_api import CineSortApi


class QrCodeEndpointTests(unittest.TestCase):
    """Tests pour get_dashboard_qr()."""

    def setUp(self):
        self.api = CineSortApi()

    def test_qr_endpoint_returns_svg(self):
        result = self.api.get_dashboard_qr()
        self.assertTrue(result["ok"])
        self.assertIn("svg", result)
        self.assertIn("url", result)

    def test_qr_svg_starts_with_svg_tag(self):
        result = self.api.get_dashboard_qr()
        self.assertTrue(result["svg"].strip().startswith("<svg"), "SVG doit commencer par <svg")

    def test_qr_svg_contains_dark_color(self):
        """Verifie que la couleur CinemaLux sombre est dans le SVG."""
        result = self.api.get_dashboard_qr()
        # segno encode les couleurs en attributs fill
        self.assertIn("#e0e0e8", result["svg"].lower())

    def test_qr_url_contains_dashboard(self):
        result = self.api.get_dashboard_qr()
        self.assertIn("/dashboard/", result["url"])

    @patch("cinesort.infra.network_utils.get_local_ip", return_value="127.0.0.1")
    def test_qr_works_with_localhost_fallback(self, _mock_ip):
        result = self.api.get_dashboard_qr()
        self.assertTrue(result["ok"])
        self.assertIn("127.0.0.1", result["url"])


if __name__ == "__main__":
    unittest.main()
