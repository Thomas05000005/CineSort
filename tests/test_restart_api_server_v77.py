"""GATE AUDIT 2026-06-10 — _restart_api_server_impl doit relancer le serveur REST
avec le VRAI token (pas le masque), le host LAN (0.0.0.0) et la cors_origin
configuree.

Avant le fix : token lu masque "••••••••" (constante publique -> 401 pour tous),
host omis (rebind 127.0.0.1 -> perte exposition LAN), cors_origin omise (retour "*").
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cinesort.ui.api.cinesort_api as backend
from cinesort.ui.api.settings_support import _SECRET_MASK


class RestartApiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_restart_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "settings.json").write_text(
            json.dumps({
                "rest_api_enabled": True,
                "rest_api_token": "REAL_secret_token_32chars_abcdefgh",
                "rest_api_port": 8642,
                "rest_api_cors_origin": "http://192.168.1.50:8642",
            }),
            encoding="utf-8",
        )
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]
        self.api._rest_server = None  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch("cinesort.infra.rest_server.RestApiServer")
    def test_restart_uses_real_token_host_and_cors(self, mock_server_cls: MagicMock) -> None:
        server = MagicMock()
        server._is_https = False
        server.dashboard_url = "http://0.0.0.0:8642/dashboard/"
        mock_server_cls.return_value = server

        result = self.api._restart_api_server_impl()
        self.assertTrue(result["ok"], f"got {result}")

        # RestApiServer construit avec les bons parametres
        _args, kwargs = mock_server_cls.call_args
        self.assertEqual(kwargs["token"], "REAL_secret_token_32chars_abcdefgh")
        self.assertNotEqual(kwargs["token"], _SECRET_MASK)
        self.assertEqual(kwargs["host"], "0.0.0.0", "exposition LAN preservee")
        self.assertEqual(kwargs["cors_origin"], "http://192.168.1.50:8642")
        server.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
