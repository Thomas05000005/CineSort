"""Tests dedies aux fixes R8-080 + LOTD-INT-01 (jellyfin_sync.restore_watched).

Vague Lot D-fix (verif/totale-2026-07) — mock http.server local (pattern
tests/test_lotd_chain_integrations.py) : JellyfinClient REEL contre un serveur
scripte sur port ephemere, AUCUN reseau externe.

  - R8-080      : mark_played en echec transitoire (503) doit rester en pending
                  et etre RE-TENTE par la boucle de restauration (le POST est
                  exclu du retry de session par design anti-double-effet, la
                  boucle est donc la SEULE couche de retry). Erreur definitive
                  comptee en 'errors' uniquement apres epuisement des tentatives.
  - LOTD-INT-01 : JellyfinError sur la liste des films (404/5xx transitoire)
                  doit consommer une tentative et re-essayer, pas s'echapper.

Execution : "C:/Users/blanc/projects/CineSort/.venv/Scripts/python.exe" -X utf8
            -m pytest tests/test_jellyfin_sync_transient_retry.py -q
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from cinesort.app._path_utils import normalize_path
from cinesort.app.jellyfin_sync import WatchedInfo, restore_watched
from cinesort.infra.jellyfin_client import JellyfinClient
from tests._helpers import find_free_port

_RouteResult = Tuple[int, Optional[Any], float]
_RouteFn = Callable[[str, str], _RouteResult]


# ---------------------------------------------------------------------------
# Serveur HTTP mock local (pattern test_lotd_chain_integrations)
# ---------------------------------------------------------------------------


class _ScriptedHandler(BaseHTTPRequestHandler):
    def _serve(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            try:
                self.rfile.read(length)
            except OSError:
                pass
        with self.server.calls_lock:  # type: ignore[attr-defined]
            self.server.calls.append((method, self.path))  # type: ignore[attr-defined]
        try:
            status, payload, sleep_s = self.server.route_fn(method, self.path)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — crash de scenario => 500 visible
            status, payload, sleep_s = 500, {"error": "route_fn crash"}, 0.0
        if sleep_s:
            time.sleep(sleep_s)
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (ConnectionError, OSError):
            pass

    def do_GET(self) -> None:  # noqa: N802
        self._serve("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._serve("POST")

    def log_message(self, *args: Any) -> None:
        pass


class _MockHTTP:
    def __init__(self, route_fn: _RouteFn):
        port = find_free_port()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _ScriptedHandler)
        self.httpd.daemon_threads = True
        self.httpd.route_fn = route_fn  # type: ignore[attr-defined]
        self.httpd.calls = []  # type: ignore[attr-defined]
        self.httpd.calls_lock = threading.Lock()  # type: ignore[attr-defined]
        self.url = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def calls(self) -> List[Tuple[str, str]]:
        with self.httpd.calls_lock:  # type: ignore[attr-defined]
            return list(self.httpd.calls)  # type: ignore[attr-defined]

    def hits(self, method: str, path_fragment: str) -> int:
        return sum(1 for m, p in self.calls if m == method and path_fragment in p)

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self) -> "_MockHTTP":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _jellyfin_routes(
    movies: Optional[List[Dict[str, Any]]] = None,
    *,
    items_statuses: Optional[List[int]] = None,
    played_statuses: Optional[List[int]] = None,
) -> _RouteFn:
    """Mock Jellyfin minimal ; les listes *_statuses sont consommees requete
    par requete, une fois epuisees => 200."""
    state = {"items": list(items_statuses or []), "played": list(played_statuses or [])}
    lock = threading.Lock()

    def _pop(key: str) -> int:
        with lock:
            return state[key].pop(0) if state[key] else 200

    def route(method: str, path: str) -> _RouteResult:
        p = path.split("?", 1)[0]
        if p == "/Users":
            return 200, [{"Id": "u1", "Name": "admin", "Policy": {"IsAdministrator": True}}], 0.0
        if p.endswith("/Views"):
            return 200, {"Items": [{"Id": "lib1", "Name": "Films", "CollectionType": "movies"}]}, 0.0
        if method == "POST" and "/PlayedItems/" in p:
            return _pop("played"), {}, 0.0
        if p.endswith("/Items"):
            status = _pop("items")
            if status != 200:
                return status, {}, 0.0
            items = movies or []
            return 200, {"Items": items, "TotalRecordCount": len(items)}, 0.0
        return 404, {}, 0.0

    return route


def _watched_fixture(tmp_path: Path) -> Tuple[Dict[str, WatchedInfo], List[Dict[str, Any]], Dict[str, Any]]:
    old_path = str(tmp_path / "films" / "Ancien.Film.2020" / "Ancien.Film.2020.1080p.mkv")
    new_path = str(tmp_path / "films" / "Nouveau Film (2020)" / "Nouveau Film (2020).mkv")
    snapshot = {
        normalize_path(old_path): WatchedInfo(played=True, play_count=3, last_played_date="2026-01-01T00:00:00Z")
    }
    operations = [{"op_type": "MOVE", "src_path": old_path, "dst_path": new_path, "undo_status": "PENDING"}]
    movie = {
        "Id": "item-1",
        "Name": "Nouveau Film",
        "Path": new_path,
        "ProductionYear": 2020,
        "ProviderIds": {},
        "UserData": {"Played": False, "PlayCount": 0},
    }
    return snapshot, operations, movie


def _restore(client: JellyfinClient, snapshot: Any, operations: Any, max_retries: int = 3) -> Any:
    return restore_watched(
        client,
        "u1",
        snapshot,
        operations,
        initial_delay_s=0.02,
        retry_delay_s=0.02,
        max_retries=max_retries,
    )


# ---------------------------------------------------------------------------
# R8-080 : mark_played 503 transitoire re-tente par la boucle, flag 'vu' restaure
# ---------------------------------------------------------------------------


def test_r8_080_mark_played_503_transitoire_retente_et_restaure(tmp_path: Path) -> None:
    """503 au 1er POST puis 200 : le film reste en pending et la tentative
    suivante restaure le flag. Exactement 2 POST (retry par la BOUCLE seule,
    le retry de session exclut POST par design anti-double-effet)."""
    snapshot, operations, movie = _watched_fixture(tmp_path)
    with _MockHTTP(_jellyfin_routes([movie], played_statuses=[503])) as server:
        client = JellyfinClient(server.url, "jf-mock-key", timeout_s=5)
        try:
            result = _restore(client, snapshot, operations)
            post_hits = server.hits("POST", "/PlayedItems/")
        finally:
            client.close()
    assert result.restored == 1, result.to_dict()
    assert result.errors == 0, result.to_dict()
    assert result.not_found == 0, result.to_dict()
    assert post_hits == 2, f"attendu 1 POST par tentative (503 puis 200), hits={post_hits}"


def test_r8_080_mark_played_echec_persistant_erreur_definitive(tmp_path: Path) -> None:
    """503 a CHAQUE tentative : erreur definitive comptee UNE fois en 'errors'
    (pas en not_found), avec 1 POST par tentative — pas de double comptage."""
    snapshot, operations, movie = _watched_fixture(tmp_path)
    with _MockHTTP(_jellyfin_routes([movie], played_statuses=[503, 503, 503])) as server:
        client = JellyfinClient(server.url, "jf-mock-key", timeout_s=5)
        try:
            result = _restore(client, snapshot, operations, max_retries=3)
            post_hits = server.hits("POST", "/PlayedItems/")
        finally:
            client.close()
    assert result.restored == 0, result.to_dict()
    assert result.errors == 1, result.to_dict()
    assert result.not_found == 0, result.to_dict()
    assert post_hits == 3, f"attendu 1 POST par tentative, hits={post_hits}"
    error_details = [d for d in result.details if d.get("action") == "error"]
    assert len(error_details) == 1, result.details
    assert error_details[0]["reason"] == "mark_played failed"
    assert error_details[0]["item_id"] == "item-1"


# ---------------------------------------------------------------------------
# FIX #15 : mark_played echoue PUIS le film disparait de l'index -> not_found
# (etat le plus recent = absent), PAS 'error mark_played failed' avec item_id perime
# ---------------------------------------------------------------------------


def _routes_present_puis_disparu(movie: Dict[str, Any]) -> _RouteFn:
    """GET /Items : renvoie [movie] a la 1re requete puis [] (film disparu) ;
    POST /PlayedItems : toujours 503 (mark_played echoue a la 1re tentative)."""
    state = {"items_calls": 0}
    lock = threading.Lock()

    def route(method: str, path: str) -> _RouteResult:
        p = path.split("?", 1)[0]
        if p == "/Users":
            return 200, [{"Id": "u1", "Name": "admin", "Policy": {"IsAdministrator": True}}], 0.0
        if p.endswith("/Views"):
            return 200, {"Items": [{"Id": "lib1", "Name": "Films", "CollectionType": "movies"}]}, 0.0
        if method == "POST" and "/PlayedItems/" in p:
            return 503, {}, 0.0
        if p.endswith("/Items"):
            with lock:
                state["items_calls"] += 1
                first = state["items_calls"] == 1
            items = [movie] if first else []
            return 200, {"Items": items, "TotalRecordCount": len(items)}, 0.0
        return 404, {}, 0.0

    return route


def test_fix15_mark_played_echoue_puis_film_disparait_not_found(tmp_path: Path) -> None:
    """Le film est present a la tentative 1 (mark_played renvoie 503 -> pose un
    item_id dans mark_failed) puis DISPARAIT de l'index aux tentatives suivantes.
    L'etat le plus recent (absent) doit primer : not_found, PAS 'error' avec un
    item_id perime. Un seul POST part (seule la tentative 1 a matche le film)."""
    snapshot, operations, movie = _watched_fixture(tmp_path)
    with _MockHTTP(_routes_present_puis_disparu(movie)) as server:
        client = JellyfinClient(server.url, "jf-mock-key", timeout_s=5)
        try:
            result = _restore(client, snapshot, operations, max_retries=3)
            post_hits = server.hits("POST", "/PlayedItems/")
        finally:
            client.close()
    assert result.restored == 0, result.to_dict()
    assert result.errors == 0, result.to_dict()
    assert result.not_found == 1, result.to_dict()
    assert post_hits == 1, f"seule la tentative 1 matche le film, hits={post_hits}"
    not_found_details = [d for d in result.details if d.get("action") == "not_found"]
    assert len(not_found_details) == 1, result.details
    # Aucun detail 'error' ne doit subsister (pas d'item_id perime).
    assert not [d for d in result.details if d.get("action") == "error"], result.details
    assert "item_id" not in not_found_details[0], not_found_details[0]


# ---------------------------------------------------------------------------
# LOTD-INT-01 : JellyfinError sur la liste consommee par la boucle, pas escape
# ---------------------------------------------------------------------------


def test_lotd_int_01_jellyfinerror_liste_transitoire_consomme_une_tentative(tmp_path: Path) -> None:
    """404 (non re-tente par la session) au 1er GET /Items puis 200 : la boucle
    catch JellyfinError, consomme la tentative et restaure a la suivante."""
    snapshot, operations, movie = _watched_fixture(tmp_path)
    with _MockHTTP(_jellyfin_routes([movie], items_statuses=[404])) as server:
        client = JellyfinClient(server.url, "jf-mock-key", timeout_s=5)
        try:
            # Ne doit PLUS lever JellyfinError (catch jellyfin_sync elargi).
            result = _restore(client, snapshot, operations)
        finally:
            client.close()
    assert result.restored == 1, result.to_dict()
    assert result.errors == 0, result.to_dict()


def test_lotd_int_01_jellyfinerror_persistant_not_found_propre(tmp_path: Path) -> None:
    """Liste en echec a CHAQUE tentative : pas d'exception, le film finit en
    not_found (jamais matche), zero 'errors' (aucun mark tente)."""
    snapshot, operations, movie = _watched_fixture(tmp_path)
    with _MockHTTP(_jellyfin_routes([movie], items_statuses=[404, 404, 404])) as server:
        client = JellyfinClient(server.url, "jf-mock-key", timeout_s=5)
        try:
            result = _restore(client, snapshot, operations, max_retries=3)
            post_hits = server.hits("POST", "/PlayedItems/")
        finally:
            client.close()
    assert result.restored == 0, result.to_dict()
    assert result.not_found == 1, result.to_dict()
    assert result.errors == 0, result.to_dict()
    assert post_hits == 0, f"aucun mark_played ne devait partir, hits={post_hits}"
