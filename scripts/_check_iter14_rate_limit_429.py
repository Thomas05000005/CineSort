"""Harness ITER14 RATE_LIMIT_429_FACADE.

Verifie en runtime :
1. Le seuil 5/60s est inchange.
2. La reponse 429 inclut un header Retry-After.
3. Le bypass loopback CONSERVE pour test #2 (seuil ne s'applique pas en local desktop).

Lance avec CINESORT_DISABLE_LOCAL_AUTH=1 pour simuler non-loopback en local.
"""

from __future__ import annotations

import os
import socket
import sys
import time
from http.client import HTTPConnection

os.environ["CINESORT_DISABLE_LOCAL_AUTH"] = "1"


def find_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> int:
    import cinesort.ui.api.cinesort_api as backend
    from cinesort.infra.rest_server import RestApiServer

    api = backend.CineSortApi()
    port = find_free_port()
    server = RestApiServer(api, port=port, token="good-token-test-12345678901234")
    server.start()
    time.sleep(0.3)

    try:
        # Pre-saturate le compteur avec un IP non-locale (simule attaque LAN).
        # 127.0.0.1 reste exempte par design (bypass loopback).
        # Mais avec CINESORT_DISABLE_LOCAL_AUTH=1 le bypass _check_auth est off ;
        # le rate-limiter exempte tout de meme 127.0.0.1 par design (FIX 2026-06-07).
        # Pour ce harness on enregistre directement sur une IP fake.
        for _ in range(5):
            server._rate_limiter.record_failure("10.0.0.42")
        assert server._rate_limiter.is_blocked("10.0.0.42"), "Seuil 5 non atteint"
        print("[1] OK seuil 5 echecs / 60s respecte sur IP simulee 10.0.0.42")

        # Patcher temporairement _client_ip pour simuler une requete distante
        # via un attaquant fake. Comme c'est un test localhost, on monkey-patch
        # le handler pour retourner 10.0.0.42.
        from cinesort.infra.rest_server import _CineSortHandler

        original_client_ip = _CineSortHandler._client_ip

        def fake_client_ip(self) -> str:
            return "10.0.0.42"

        _CineSortHandler._client_ip = fake_client_ip  # type: ignore[assignment]

        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request(
                "POST",
                "/api/settings/get_settings",
                body=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer good-token-test-12345678901234",
                },
            )
            resp = conn.getresponse()
            status = resp.status
            retry_after = resp.getheader("Retry-After")
            xreq = resp.getheader("X-Request-ID")
            body = resp.read()
            conn.close()
        finally:
            _CineSortHandler._client_ip = original_client_ip  # type: ignore[assignment]

        print(f"[2] status={status}")
        print(f"[2] Retry-After={retry_after!r}")
        print(f"[2] X-Request-ID={xreq!r}")
        print(f"[2] body={body!r}")

        assert status == 429, f"Attendu 429, recu {status}"
        assert retry_after == "60", f"Attendu Retry-After=60, recu {retry_after!r}"
        assert xreq, "X-Request-ID manquant"
        print("[2] OK 429 + Retry-After=60 + X-Request-ID present sur facade path")

        # Test bypass loopback CONSERVE : 127.0.0.1 reste exempte du rate-limit
        # meme si _disable_local_auth=1 (semantique FIX 2026-06-07).
        server._rate_limiter.reset()
        for _ in range(10):
            server._rate_limiter.record_failure("127.0.0.1")
        assert server._rate_limiter.is_blocked("127.0.0.1"), "Compteur n'a pas explose"
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            "/api/settings/get_settings",
            body=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer good-token-test-12345678901234",
            },
        )
        resp = conn.getresponse()
        status_loopback = resp.status
        resp.read()
        conn.close()
        print(f"[3] loopback (saturated counter) status={status_loopback}")
        # Loopback exempte du rate-limit, donc passe a auth. CINESORT_DISABLE_LOCAL_AUTH=1
        # est positionne, donc bypass loopback _check_auth desactive ; bon token = 200.
        assert status_loopback == 200, (
            f"Attendu 200 sur loopback exempte rate-limit, recu {status_loopback}"
        )
        print("[3] OK bypass rate-limit loopback CONSERVE (jamais 429 en 127.0.0.1)")

        print("\nFIX_OK")
        return 0
    finally:
        server.stop()


if __name__ == "__main__":
    sys.exit(main())
