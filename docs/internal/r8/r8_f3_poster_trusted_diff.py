"""R8 F3 (filet) — DOUBLE DIFFERENTIEL R8-094 + R8-095 : effets de bord du proxy poster.

Survivants du filet F3 :
- origin-0 (R8-094, 3/3) : `force` (purge cache + re-DL TMDb) etait honore pour un client LAN
  NON-navigateur (curl en bind 0.0.0.0, sans Origin ni Sec-Fetch) -> R8-030 ne couvrait que le
  navigateur cross-site.
- guards-0 (R8-095, 3/3) : meme SANS `force`, un GET /api/poster cross-site sur cache MISS declenchait
  un fetch TMDb sortant + ecriture disque (amplification / brulage quota cle API).

Fix coherent : `_poster_trusted_caller()` (rest_server) decide si l'appelant peut declencher les EFFETS
DE BORD. Untrusted -> `force` neutralise (R8-094) ET `serve_poster(allow_fetch=False)` = CACHE SEUL
(R8-095, aucun fetch/ecriture). La LECTURE du cache reste ouverte.

Double diff : (1) attaque fermee ; (2) usage legitime (desktop loopback / LAN dashboard same-origin) intact.

Usage : PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/r8/r8_f3_poster_trusted_diff.py
"""

from __future__ import annotations

import email.message
import io
import json
import tempfile
from pathlib import Path

from cinesort.infra.integrations import poster_proxy
from cinesort.infra.rest_server import _CineSortHandler


def _mk_handler(client_ip: str, headers: dict):
    obj = _CineSortHandler.__new__(_CineSortHandler)
    obj.client_address = (client_ip, 50000)
    msg = email.message.Message()
    for k, v in headers.items():
        msg[k] = v
    obj.headers = msg
    obj.cors_origin = ""
    return obj


class FakeHTTP:
    def __init__(self, client_ip="127.0.0.1", headers=None):
        self.client_address = (client_ip, 50000)
        msg = email.message.Message()
        for k, v in (headers or {}).items():
            msg[k] = v
        self.headers = msg
        self.status = None
        self.wfile = io.BytesIO()

    def send_response(self, code):
        self.status = code

    def send_header(self, *a, **k):
        pass

    def end_headers(self):
        pass


def run():
    results = {}

    # ===== R8-094 : _poster_trusted_caller (decision effets de bord) =====
    print("=== R8-094 : _poster_trusted_caller (force) ===")
    cases = [
        ("desktop natif loopback", "127.0.0.1", {}, True),
        ("LAN curl non-navigateur (ATTAQUE)", "192.168.1.50", {}, False),
        ("LAN dashboard same-origin (LEGITIME)", "192.168.1.50", {"Sec-Fetch-Site": "same-origin"}, True),
        ("navigateur cross-site (R8-030)", "127.0.0.1", {"Sec-Fetch-Site": "cross-site"}, False),
    ]
    ok_094 = True
    for label, ip, hdrs, expected in cases:
        got = _mk_handler(ip, hdrs)._poster_trusted_caller()
        ok = got == expected
        ok_094 = ok_094 and ok
        print(f"  {label:42} trusted={got} (attendu {expected}) {'OK' if ok else 'KO'}")
    results["R8094_trusted_caller_decisions"] = ok_094

    # ===== R8-095 : serve_poster allow_fetch -> cache seul si untrusted =====
    print("\n=== R8-095 : serve_poster(allow_fetch) ===")
    with tempfile.TemporaryDirectory() as td:
        state = Path(td)
        cache_root = state / "cache" / "posters"
        (cache_root / "w500").mkdir(parents=True)
        (cache_root / "w500" / "550.jpg").write_bytes(b"\xff\xd8\xff\xe0CACHED")  # cache hit

        # Spy : detecte toute tentative de fetch (construction client TMDb).
        fetch_calls = {"n": 0}
        orig = poster_proxy._build_or_get_tmdb_client

        def _spy(state_dir):
            fetch_calls["n"] += 1
            return None  # pas de cle -> 503 si appele

        poster_proxy._build_or_get_tmdb_client = _spy
        try:
            # (1) ATTAQUE : untrusted (allow_fetch=False) + cache MISS -> 404, AUCUN fetch.
            fetch_calls["n"] = 0
            h = FakeHTTP()
            poster_proxy.serve_poster(h, state, cache_root, {"id": "999", "size": "w500"}, allow_fetch=False)
            miss_untrusted_no_fetch = h.status == 404 and fetch_calls["n"] == 0
            print(f"  untrusted + MISS  : status={h.status} fetch_calls={fetch_calls['n']} (attendu 404 / 0)")

            # (2a) LEGITIME : untrusted + cache HIT -> 200 servi, AUCUN fetch (lecture ok).
            fetch_calls["n"] = 0
            h = FakeHTTP()
            poster_proxy.serve_poster(h, state, cache_root, {"id": "550", "size": "w500"}, allow_fetch=False)
            hit_untrusted_served = h.status == 200 and fetch_calls["n"] == 0
            print(f"  untrusted + HIT   : status={h.status} fetch_calls={fetch_calls['n']} (attendu 200 / 0)")

            # (2b) LEGITIME : trusted (allow_fetch=True) + MISS -> fetch TENTE (gate effectif).
            fetch_calls["n"] = 0
            h = FakeHTTP()
            poster_proxy.serve_poster(h, state, cache_root, {"id": "999", "size": "w500"}, allow_fetch=True)
            miss_trusted_fetches = fetch_calls["n"] == 1
            print(f"  trusted   + MISS  : status={h.status} fetch_calls={fetch_calls['n']} (attendu fetch=1)")
        finally:
            poster_proxy._build_or_get_tmdb_client = orig

    results["R8095_untrusted_miss_no_fetch"] = miss_untrusted_no_fetch
    results["R8095_untrusted_hit_served"] = hit_untrusted_served
    results["R8095_trusted_miss_fetches"] = miss_trusted_fetches

    allok = all(results.values())
    print(
        f"\nVERDICT : {'CORRIGE (effets de bord poster gates par _poster_trusted_caller ; lecture cache intacte)' if allok else 'INCOMPLET'}"
    )
    print("RESUME:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    run()
