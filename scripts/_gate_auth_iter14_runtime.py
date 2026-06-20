"""GATE AUTH ITER14 - Matrice runtime non-loopback + loopback + rate-limit + X-Request-Id.

Verifie en RUNTIME (pas en lecture code) :
1. NON-LOOPBACK no-token  -> 401 + X-Request-Id
2. NON-LOOPBACK wrong-token -> 401 + X-Request-Id
3. NON-LOOPBACK valid-token -> != 401 (200/4xx/5xx metier, defense ouverte)
4. LOOPBACK valid-token -> 200 (bypass loopback bind 127.0.0.1)
5. LOOPBACK no-token -> 200 (bypass loopback actif)
6. Rate-limit: 6 echecs consecutifs non-loopback -> 429 (PAS 410)
7. X-Request-Id present sur toutes reponses (y compris 401)
8. 5 endpoints facade non-loopback sans token -> 401 (defense en profondeur)

Strategie deux phases :
  Phase A (non-loopback) : CINESORT_DISABLE_LOCAL_AUTH=1 + monkey-patch _client_ip
    -> bypass loopback _check_auth desactive (kill-switch) ET rate-limiter actif
       (l'IP fake 10.0.0.42 n'est plus dans _LOCAL_CLIENT_IPS).
    -> Test matrice non-loopback complete + rate-limit + 5 endpoints facade.
  Phase B (loopback) : env var unset, _client_ip restore (vrai 127.0.0.1)
    -> bypass loopback ACTIF, conserve.
    -> Test bypass valid-token + no-token -> 200.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from http.client import HTTPConnection


def find_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def post(port: int, path: str, token: str | None) -> tuple[int, str | None, bytes]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    conn.request("POST", path, body=b"{}", headers=headers)
    resp = conn.getresponse()
    status = resp.status
    xreq = resp.getheader("X-Request-ID")
    body = resp.read()
    conn.close()
    return status, xreq, body


def main() -> int:
    results: dict[str, object] = {
        "non_loopback_no_token": None,
        "non_loopback_wrong_token": None,
        "non_loopback_valid_token": None,
        "loopback_valid_token": None,
        "loopback_no_token": None,
        "rate_limit_status_last": None,
        "rate_limit_any_410": None,
        "x_request_id_on_401": None,
        "facade_5_endpoints": {},
    }

    import cinesort.ui.api.cinesort_api as backend
    from cinesort.infra.rest_server import RestApiServer, _CineSortHandler

    valid_token = "valid-token-iter14-runtime-test"
    api = backend.CineSortApi()
    port = find_free_port()
    server = RestApiServer(api, port=port, token=valid_token)
    server.start()
    time.sleep(0.4)

    original_client_ip = _CineSortHandler._client_ip
    original_env = os.environ.get("CINESORT_DISABLE_LOCAL_AUTH")

    def fake_non_loopback_ip(self) -> str:
        return "10.0.0.42"

    try:
        # ===== PHASE A : NON-LOOPBACK simulation =====
        # Active le kill-switch -> _check_auth ne bypass plus en loopback.
        # Et monkey-patch _client_ip -> rate-limiter compte les 10.0.0.42.
        os.environ["CINESORT_DISABLE_LOCAL_AUTH"] = "1"
        _CineSortHandler._client_ip = fake_non_loopback_ip
        server._rate_limiter.reset()

        # A.1 NON-LOOPBACK no-token -> 401
        status, xreq, body = post(port, "/api/settings/get_settings", token=None)
        results["non_loopback_no_token"] = status
        print(f"[A.1] NON-LOOPBACK no-token: status={status}, X-Request-ID={xreq!r}")
        results["x_request_id_on_401"] = bool(xreq) and status == 401

        # A.2 NON-LOOPBACK wrong-token -> 401
        status_w, xreq_w, _ = post(port, "/api/settings/get_settings", token="wrong-token-xx")
        results["non_loopback_wrong_token"] = status_w
        print(f"[A.2] NON-LOOPBACK wrong-token: status={status_w}, X-Request-ID={xreq_w!r}")

        # Reset rate-limit avant valid-token
        server._rate_limiter.reset()

        # A.3 NON-LOOPBACK valid-token -> != 401
        status_v, xreq_v, body_v = post(port, "/api/settings/get_settings", token=valid_token)
        results["non_loopback_valid_token"] = status_v
        print(f"[A.3] NON-LOOPBACK valid-token: status={status_v}, X-Request-ID={xreq_v!r}")

        # ===== B. RATE LIMIT 6 echecs -> 429 (pas 410) =====
        # FIX 2026-06-07 : seul un WRONG-token incremente le compteur
        # (no-token = bug client, pas attaque). Donc on utilise wrong-token.
        server._rate_limiter.reset()
        rl_statuses = []
        for i in range(6):
            s, _, _ = post(port, "/api/settings/get_settings", token="wrong-token-xyz")
            rl_statuses.append(s)
        print(f"[B] 6 echecs WRONG-token (non-loopback) statuses={rl_statuses}")
        results["rate_limit_status_last"] = rl_statuses[-1]
        results["rate_limit_any_410"] = any(s == 410 for s in rl_statuses)

        # ===== C. 5 endpoints facade non-loopback no-token -> 401 =====
        facade_endpoints = [
            "/api/settings/get_settings",
            "/api/run/list_runs",
            "/api/quality/get_quality_metrics_status",
            "/api/integrations/get_jellyfin_libraries",
            "/api/library/export_films",
        ]
        for ep in facade_endpoints:
            server._rate_limiter.reset()
            s, x, _ = post(port, ep, token=None)
            results["facade_5_endpoints"][ep] = {"status": s, "xreq": bool(x)}
            print(f"[C] facade {ep}: status={s}, X-Request-ID={bool(x)}")

        # ===== PHASE D : LOOPBACK (bypass conserve) =====
        # Restore _client_ip (vrai 127.0.0.1) ET unset kill-switch
        _CineSortHandler._client_ip = original_client_ip
        os.environ.pop("CINESORT_DISABLE_LOCAL_AUTH", None)
        server._rate_limiter.reset()

        # D.1 LOOPBACK valid-token -> 200 (bypass)
        status_lv, xreq_lv, _ = post(port, "/api/settings/get_settings", token=valid_token)
        results["loopback_valid_token"] = status_lv
        print(f"[D.1] LOOPBACK valid-token: status={status_lv}, X-Request-ID={xreq_lv!r}")

        # D.2 LOOPBACK no-token -> 200 (bypass actif)
        status_ln, xreq_ln, _ = post(port, "/api/settings/get_settings", token=None)
        results["loopback_no_token"] = status_ln
        print(f"[D.2] LOOPBACK no-token: status={status_ln}, X-Request-ID={xreq_ln!r}")

    finally:
        _CineSortHandler._client_ip = original_client_ip
        if original_env is None:
            os.environ.pop("CINESORT_DISABLE_LOCAL_AUTH", None)
        else:
            os.environ["CINESORT_DISABLE_LOCAL_AUTH"] = original_env
        server.stop()

    # Resume
    print("\n=== RESUME GATE AUTH ITER14 ===")
    print(json.dumps(results, indent=2, default=str))

    # Verdicts
    facade_5_no_token_401 = all(
        v["status"] == 401 for v in results["facade_5_endpoints"].values()
    )
    facade_5_xreq = all(
        v["xreq"] for v in results["facade_5_endpoints"].values()
    )
    verdicts = {
        "non_loopback_no_token=401": results["non_loopback_no_token"] == 401,
        "non_loopback_wrong_token=401": results["non_loopback_wrong_token"] == 401,
        "non_loopback_valid_token!=401": results["non_loopback_valid_token"] != 401,
        "loopback_valid_token=200": results["loopback_valid_token"] == 200,
        "loopback_no_token=200_bypass": results["loopback_no_token"] == 200,
        "rate_limit_429_not_410": results["rate_limit_status_last"] == 429 and not results["rate_limit_any_410"],
        "x_request_id_on_401": results["x_request_id_on_401"] is True,
        "facade_5_no_token_401": facade_5_no_token_401,
        "facade_5_xreq_present": facade_5_xreq,
    }
    print("\n=== VERDICTS ===")
    for k, v in verdicts.items():
        marker = "OK" if v else "FAIL"
        print(f"[{marker}] {k}")

    all_pass = all(verdicts.values())
    print(f"\nGATE_AUTH_VERDICT={'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
