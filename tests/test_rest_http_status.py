"""Phase 11 v7.8.0 - convention opt-in HTTP status sur le dispatch REST.

Le dispatch POST /api/<method> retourne 200 par defaut, mais si le handler
inclut un champ `http_status` (int 200-599) dans son dict resultat, le code
retourne est utilise et le champ est retire du payload avant serialisation.

Permet aux handlers d'opter pour des codes 404/403/409/... sans casser les
clients existants qui lisent uniquement data.ok.
"""
from __future__ import annotations

import json
import socket
import time
import unittest
import urllib.request
import urllib.error

from cinesort.infra.rest_server import RestApiServer


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _FakeApi:
    """Faux api avec quelques methodes utilisees pour tester la convention."""

    def get_ok_default(self) -> dict:
        return {"ok": True, "message": "default 200"}

    def get_missing_resource(self) -> dict:
        return {"ok": False, "message": "ressource introuvable", "http_status": 404}

    def get_conflict(self) -> dict:
        return {"ok": False, "message": "conflit metier", "http_status": 409}

    def get_invalid_http_status(self) -> dict:
        return {"ok": True, "value": 42, "http_status": "not-a-number"}

    def get_out_of_range_status(self) -> dict:
        return {"ok": True, "value": 42, "http_status": 99}


def _post(server: RestApiServer, method: str, params: dict) -> tuple[int, dict]:
    url = f"http://127.0.0.1:{server._port}/api/{method}"
    req = urllib.request.Request(
        url,
        data=json.dumps(params).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {server._token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode("utf-8"))
        return e.code, body


class HttpStatusConventionTests(unittest.TestCase):
    server: RestApiServer

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = RestApiServer(
            _FakeApi(),
            port=_find_free_port(),
            token="x" * 32,
        )
        cls.server.start()
        # Petit warmup ; start est synchrone mais bind peut traîner sous CI
        time.sleep(0.05)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()

    def test_default_status_is_200(self) -> None:
        status, body = _post(self.server, "get_ok_default", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["ok"], True)
        self.assertNotIn("http_status", body, "le champ doit etre retire du payload")

    def test_http_status_404_propagates(self) -> None:
        status, body = _post(self.server, "get_missing_resource", {})
        self.assertEqual(status, 404)
        self.assertEqual(body["ok"], False)
        self.assertNotIn("http_status", body)

    def test_http_status_409_propagates(self) -> None:
        status, body = _post(self.server, "get_conflict", {})
        self.assertEqual(status, 409)
        self.assertEqual(body["ok"], False)
        self.assertEqual(body["message"], "conflit metier")
        self.assertNotIn("http_status", body)

    def test_invalid_http_status_falls_back_to_200(self) -> None:
        status, body = _post(self.server, "get_invalid_http_status", {})
        # "not-a-number" est ignore silencieusement
        self.assertEqual(status, 200)
        self.assertEqual(body["value"], 42)
        self.assertNotIn("http_status", body)

    def test_out_of_range_status_falls_back_to_200(self) -> None:
        status, body = _post(self.server, "get_out_of_range_status", {})
        # 99 hors plage [200, 600) -> ignore
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
