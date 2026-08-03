"""R8 F3 — DOUBLE DIFFERENTIEL CSRF/origine sur le serveur REST reel (R8-030 + R8-031).

Instance de test locale (bind 127.0.0.1, port libre, token factice). Requetes
FORGEES via http.client. Aucune vraie biblio, aucun secret.

R8-030 (GET force CSRF) : `/api/poster?...&force=1` PURGE le cache + re-DL TMDb.
  Un <img> CROSS-SITE (Sec-Fetch-Site: cross-site, sans Origin) le declenchait en CSRF.
  -> APRES : `force` neutralise si cross-site ; conserve si same-origin / client natif.

R8-031 (origine port ignore) : `_allowed_origin` acceptait n'importe quel PORT loopback
  -> une 2e app locale (http://localhost:<autre_port>) passait la garde CSRF.
  -> APRES : seul le port d'ecoute du serveur est autorise.

Double diff : (1) attaque fermee ; (2) usage loopback legitime intact.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f3_rest_csrf_diff.py
"""

from __future__ import annotations

import contextlib
import json
import socket
import tempfile
import time
from http.client import HTTPConnection
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend
from cinesort.infra.integrations import poster_proxy
from cinesort.infra.rest_server import RestApiServer


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _avant_allowed_origin_localhost(origin: str, own_port: int) -> bool:
    """Replique le comportement AVANT R8-031 : tout host loopback autorise,
    PORT IGNORE. (Pour montrer le gap qui existait.)"""
    from urllib.parse import urlsplit

    host = (urlsplit(origin).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}  # any port -> allowed


def _request(port, method, path, headers=None, body=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        payload = json.dumps(body or {}) if body is not None else ""
        conn.request(method, path, body=payload.encode("utf-8"), headers=h)
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        return status
    finally:
        with contextlib.suppress(OSError):
            conn.close()


def run():
    results = {}
    tmp = Path(tempfile.mkdtemp(prefix="r8_f3_csrf_"))
    (tmp / "root").mkdir()
    (tmp / "state").mkdir()
    api = backend.CineSortApi()
    api.settings.save_settings({"root": str(tmp / "root"), "state_dir": str(tmp / "state"), "tmdb_enabled": False})
    port = _free_port()
    server = RestApiServer(api, port=port, token="secret-token-xyz-123456")
    server.start()
    time.sleep(0.25)

    # Capture du `force` recu par serve_poster (sans toucher a TMDb).
    captured: dict = {}

    def _fake_serve_poster(handler, state_dir, cache_root, query, allow_fetch=True):
        captured["query"] = dict(query)
        captured["allow_fetch"] = allow_fetch
        handler.send_response(204)
        with contextlib.suppress(Exception):
            handler._send_cors_headers()
        handler.end_headers()

    orig_serve = poster_proxy.serve_poster
    poster_proxy.serve_poster = _fake_serve_poster
    try:
        # ===== R8-030 : force CSRF =====
        print("=== R8-030 : GET /api/poster?...&force=1 ===")
        # (1) ATTAQUE : <img> cross-site (Sec-Fetch-Site: cross-site, pas d'Origin).
        captured.clear()
        _request(
            port,
            "GET",
            "/api/poster?id=550&size=w500&force=1",
            headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "image"},
        )
        force_after_crosssite = "force" in captured.get("query", {})
        results["R8030_attaque_force_neutralise_crosssite"] = not force_after_crosssite
        print(
            f"  (1) ATTAQUE cross-site : force recu par le proxy = {force_after_crosssite} (attendu False -> neutralise)"
        )

        # (2a) LEGITIME : <img> same-origin (Sec-Fetch-Site: same-origin).
        captured.clear()
        _request(
            port,
            "GET",
            "/api/poster?id=550&size=w500&force=1",
            headers={"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Dest": "image"},
        )
        force_same_origin = "force" in captured.get("query", {})
        results["R8030_legitime_force_conserve_sameorigin"] = force_same_origin
        print(f"  (2a) LEGITIME same-origin : force conserve = {force_same_origin} (attendu True)")

        # (2b) LEGITIME : client natif (aucun header Sec-Fetch / aucun Origin).
        captured.clear()
        _request(port, "GET", "/api/poster?id=550&size=w500&force=1")
        force_native = "force" in captured.get("query", {})
        results["R8030_legitime_force_conserve_natif"] = force_native
        print(f"  (2b) LEGITIME client natif : force conserve = {force_native} (attendu True)")

        # ===== R8-031 : origine port ignore (CSRF) =====
        print("\n=== R8-031 : POST avec Origin loopback sur un AUTRE port ===")
        other = port + 1 if port + 1 != port else port + 2
        # AVANT (replique) : localhost:<autre> aurait ete AUTORISE.
        avant_allow = _avant_allowed_origin_localhost(f"http://localhost:{other}", port)
        print(f"  AVANT (replique) localhost:{other} autorise = {avant_allow} (gap CSRF)")

        # (1) ATTAQUE : POST avec Origin http://localhost:<autre_port> -> 403 (cross-site).
        st_attack = _request(
            port, "POST", "/api/run/get_dashboard", headers={"Origin": f"http://localhost:{other}"}, body={}
        )
        results["R8031_attaque_autre_port_403"] = st_attack == 403
        print(f"  (1) ATTAQUE Origin localhost:{other} -> HTTP {st_attack} (attendu 403)")

        # (2) LEGITIME : POST avec Origin du serveur (meme port) -> PAS 403.
        st_same = _request(
            port, "POST", "/api/run/get_dashboard", headers={"Origin": f"http://127.0.0.1:{port}"}, body={}
        )
        results["R8031_legitime_meme_port_pas_403"] = st_same != 403
        print(f"  (2) LEGITIME Origin 127.0.0.1:{port} -> HTTP {st_same} (attendu != 403)")

        # ===== NON-REGRESSION : bypass loopback / lecture publique =====
        print("\n=== NON-REGRESSION loopback legitime ===")
        st_health = _request(port, "GET", "/api/health")
        results["NONREG_health_ouvert"] = st_health == 200
        print(f"  GET /api/health (lecture publique) -> HTTP {st_health} (attendu 200)")
        # POST local SANS Origin (client natif desktop) -> PAS 403 (CSRF ne bloque pas).
        st_local = _request(port, "POST", "/api/run/get_dashboard", body={})
        results["NONREG_post_local_sans_origin_pas_403"] = st_local != 403
        print(f"  POST local sans Origin -> HTTP {st_local} (attendu != 403)")
    finally:
        poster_proxy.serve_poster = orig_serve
        server.stop()

    allok = all(results.values())
    print(
        f"\nVERDICT : {'CORRIGE (R8-030 + R8-031 : attaques fermees, loopback legitime intact)' if allok else 'INCOMPLET'}"
    )
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
