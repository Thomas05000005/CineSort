"""Lot D — Chaine 4.5 INTEGRATIONS bout-en-bout (verif/totale-2026-07).

Chaine verifiee : facade integrations (CineSortApi.integrations) -> clients
infra (JellyfinClient / RadarrClient / TmdbClient) -> HTTP reel contre des
serveurs mock locaux (http.server sur port ephemere, AUCUN reseau externe,
AUCUN chemin hors tempdir).

Scenarios joues :
  1. test_jellyfin_connection / test_radarr_connection OK contre mock 200,
     et erreur PROPRE (ok=False + message, pas d'exception) contre port ferme ;
  2. R8-080 : restauration du flag 'vu' (jellyfin_sync.restore_watched) quand
     le POST /PlayedItems repond 503 puis 200 -> garde nominative si le film
     n'est JAMAIS re-tente (compte en 'errors' des le 1er 503) ;
  3. timeouts respectes : mock qui dort > timeout => erreur bornee, pas de hang ;
  4. aucun secret en clair dans les logs (scrubber prod installe comme au boot,
     capture root DEBUG, grep des tokens mock) ;
  5. TMDb sans reseau reel : cle vide => erreur de validation propre ;
     cle bidon + endpoint redirige vers un port local ferme => erreur propre ;
     get_tmdb_posters sans cle => ok=True + reason=tmdb_not_configured.

Gardes nominatives (bugs d'app REPORTES, pas corriges — pattern sweeps Lot C) :
  - R8-080      : mark_played 503 => comptabilise en 'errors' et retire de
                  pending, jamais re-tente (jellyfin_sync.py:217-248) ; le
                  retry de session HTTP exclut POST (allowed_methods,
                  _http_utils.py:15) donc AUCUNE couche ne re-tente.
  - LOTD-INT-01 : le catch de la boucle retry de restore_watched
                  (jellyfin_sync.py:205 — ConnectionError/OSError/Timeout
                  Error/ValueError) n'inclut PAS JellyfinError : un echec HTTP
                  transitoire sur la liste des films fait s'echapper
                  l'exception et abandonne TOUTE la restauration au lieu de
                  re-tenter a la tentative suivante.
  - LOTD-INT-02 : (dynamique) le message d'erreur d'un read-timeout doit
                  mentionner le timeout (pas seulement "Connexion impossible").
  - LOTD-INT-03 : cle TMDb potentiellement en clair dans le message d'erreur
                  renvoye au frontend par validate_key ("Erreur reseau: {exc}"
                  ou exc contient l'URL avec ?api_key=...).

Execution : "C:/Users/<utilisateur>/projects/CineSort/.venv/Scripts/python.exe" -X utf8
            -m pytest tests/test_lotd_chain_integrations.py -q
"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

import cinesort.ui.api.cinesort_api as backend
from cinesort.app._path_utils import normalize_path
from cinesort.app.jellyfin_sync import WatchedInfo, restore_watched
from cinesort.infra.jellyfin_client import JellyfinClient, JellyfinError
from cinesort.infra.log_scrubber import install_global_scrubber
from tests._helpers import find_free_port

# (status HTTP, payload JSON ou None, sleep_s avant reponse)
_RouteResult = Tuple[int, Optional[Any], float]
_RouteFn = Callable[[str, str], _RouteResult]


# ---------------------------------------------------------------------------
# Serveur HTTP mock local (port ephemere, thread daemon)
# ---------------------------------------------------------------------------


class _ScriptedHandler(BaseHTTPRequestHandler):
    """Handler pilote par server.route_fn ; enregistre chaque requete."""

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
        except Exception:  # noqa: BLE001 — un crash de scenario => 500 visible
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
            # Client parti (ex: timeout cote client) — attendu dans ces tests.
            pass

    def do_GET(self) -> None:  # noqa: N802
        self._serve("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._serve("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._serve("DELETE")

    def log_message(self, *args: Any) -> None:  # silence stderr
        pass


class _MockHTTP:
    """Serveur HTTP mock sur 127.0.0.1:<port ephemere> (context manager)."""

    def __init__(self, route_fn: _RouteFn):
        port = find_free_port()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _ScriptedHandler)
        self.httpd.daemon_threads = True  # pas de join des handlers qui dorment
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


# ---------------------------------------------------------------------------
# Scenarios de routage Jellyfin / Radarr
# ---------------------------------------------------------------------------


def _jellyfin_routes(
    movies: Optional[List[Dict[str, Any]]] = None,
    *,
    info_statuses: Optional[List[int]] = None,
    items_statuses: Optional[List[int]] = None,
    played_statuses: Optional[List[int]] = None,
    info_sleep_s: float = 0.0,
) -> _RouteFn:
    """Mock d'API Jellyfin minimal.

    Les listes *_statuses sont consommees requete par requete (y compris les
    retries de session urllib3) ; une fois epuisees => 200.
    """
    state = {
        "info": list(info_statuses or []),
        "items": list(items_statuses or []),
        "played": list(played_statuses or []),
    }
    lock = threading.Lock()

    def _pop(key: str) -> int:
        with lock:
            return state[key].pop(0) if state[key] else 200

    def route(method: str, path: str) -> _RouteResult:
        p = path.split("?", 1)[0]
        if p == "/System/Info/Public":
            status = _pop("info")
            payload = {"ServerName": "MockJellyfin", "Version": "10.9.0"} if status == 200 else {}
            return status, payload, info_sleep_s
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


def _radarr_routes() -> _RouteFn:
    def route(method: str, path: str) -> _RouteResult:
        p = path.split("?", 1)[0]
        if p == "/api/v3/system/status":
            return 200, {"instanceName": "MockRadarr", "appName": "Radarr", "version": "5.14.0"}, 0.0
        return 404, {}, 0.0

    return route


def _make_api(tmp_path: Path) -> Any:
    """CineSortApi pilote directement, state_dir dans le tempdir du test."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    api = backend.CineSortApi()
    api._state_dir = state_dir  # type: ignore[attr-defined]
    return api


# ---------------------------------------------------------------------------
# 1. test_*_connection : OK contre mock 200, erreur PROPRE contre port ferme
# ---------------------------------------------------------------------------


def test_jellyfin_connection_ok_contre_mock_200(tmp_path: Path) -> None:
    movie = {
        "Id": "item-1",
        "Name": "Film Mock",
        "Path": str(tmp_path / "films" / "Film.Mock.2020" / "Film.Mock.2020.mkv"),
        "ProductionYear": 2020,
        "ProviderIds": {},
        "UserData": {"Played": False, "PlayCount": 0},
    }
    with _MockHTTP(_jellyfin_routes([movie])) as server:
        api = _make_api(tmp_path)
        res = api.integrations.test_jellyfin_connection(url=server.url, api_key="jf-mock-key", timeout_s=5)
    assert res["ok"] is True, res
    assert res["server_name"] == "MockJellyfin"
    assert res["user_id"] == "u1"
    assert res["movies_count"] == 1
    assert [lib["id"] for lib in res["libraries"]] == ["lib1"]


def test_radarr_connection_ok_contre_mock_200(tmp_path: Path) -> None:
    with _MockHTTP(_radarr_routes()) as server:
        api = _make_api(tmp_path)
        res = api.integrations.test_radarr_connection(url=server.url, api_key="ra-mock-key", timeout_s=5)
    assert res["ok"] is True, res
    assert res["server_name"] == "MockRadarr"
    assert res["version"] == "5.14.0"


def test_jellyfin_connection_erreur_propre_port_ferme(tmp_path: Path) -> None:
    closed = find_free_port()  # port libere => rien n'ecoute => refus immediat
    api = _make_api(tmp_path)
    res = api.integrations.test_jellyfin_connection(
        url=f"http://127.0.0.1:{closed}", api_key="jf-mock-key", timeout_s=2
    )
    assert res["ok"] is False, res
    assert str(res.get("message") or "").strip(), f"message vide : {res}"
    assert "Traceback" not in str(res)


def test_radarr_connection_erreur_propre_port_ferme(tmp_path: Path) -> None:
    closed = find_free_port()
    api = _make_api(tmp_path)
    res = api.integrations.test_radarr_connection(url=f"http://127.0.0.1:{closed}", api_key="ra-mock-key", timeout_s=2)
    assert res["ok"] is False, res
    # RadarrClient.validate_connection renvoie {'ok': False, 'error': ...}
    assert str(res.get("error") or res.get("message") or "").strip(), f"erreur vide : {res}"
    assert "Traceback" not in str(res)


def test_jellyfin_libraries_non_configure_erreur_propre(tmp_path: Path) -> None:
    """Settings vierges (tempdir) => reponse metier propre, aucun appel reseau."""
    api = _make_api(tmp_path)
    res = api.integrations.get_jellyfin_libraries()
    assert res["ok"] is False
    assert "Jellyfin" in str(res.get("message") or "")


# ---------------------------------------------------------------------------
# 2. Retries : GET 503->200 re-tente (session), POST 503->200 jamais (R8-080)
# ---------------------------------------------------------------------------


def test_jellyfin_get_503_puis_200_retry_session_ok(tmp_path: Path) -> None:
    """Preuve POSITIVE : le retry de session (make_session_with_retry) re-tente
    bien un GET 503 => la connexion aboutit malgre un hoquet transitoire."""
    with _MockHTTP(_jellyfin_routes(info_statuses=[503])) as server:
        api = _make_api(tmp_path)
        res = api.integrations.test_jellyfin_connection(url=server.url, api_key="jf-mock-key", timeout_s=5)
        hits = server.hits("GET", "/System/Info/Public")
    assert res["ok"] is True, res
    assert hits >= 2, f"GET /System/Info/Public aurait du etre re-tente apres 503 (hits={hits})"


def _watched_fixture(tmp_path: Path) -> Tuple[Dict[str, WatchedInfo], List[Dict[str, Any]], Dict[str, Any]]:
    """Snapshot 'vu' + operation MOVE + item Jellyfin re-indexe au NOUVEAU chemin."""
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


def test_r8_080_flag_vu_mark_played_503_puis_200(tmp_path: Path) -> None:
    """R8-080 : le mock repond 503 au 1er POST /PlayedItems puis 200 ensuite.

    Comportement ATTENDU (contrat de la chaine sync 'vu') : le film est
    re-tente (par la session HTTP ou par la boucle retry H-11) et finit
    restaure. Comportement CONSTATE : mark_played() retourne False sur le 503,
    restore_watched comptabilise 'errors' et RETIRE le film de pending
    (jellyfin_sync.py:225-246) ; le retry de session exclut POST
    (_http_utils.py:15 allowed_methods) => le flag 'vu' est PERDU.
    """
    snapshot, operations, movie = _watched_fixture(tmp_path)
    with _MockHTTP(_jellyfin_routes([movie], played_statuses=[503])) as server:
        client = JellyfinClient(server.url, "jf-mock-key", timeout_s=5)
        result = restore_watched(
            client,
            "u1",
            snapshot,
            operations,
            initial_delay_s=0.02,
            retry_delay_s=0.02,
            max_retries=3,
        )
        post_hits = server.hits("POST", "/PlayedItems/")
        client.close()

    if result.restored == 1 and result.errors == 0:
        # Un retry (session ou boucle) existe desormais : garde levee.
        assert post_hits >= 2
        return

    # Signature exacte du bug : 1 seul POST, 0 restaure, 1 erreur definitive.
    assert result.restored == 0, result.to_dict()
    assert result.errors == 1, result.to_dict()
    assert post_hits == 1, f"POST PlayedItems hits={post_hits}"
    pytest.xfail(
        "R8-080 CONFIRME : mark_played 503 -> compte en 'errors' et jamais re-tente "
        "(jellyfin_sync.py:225-246 retire le film de pending ; POST exclu du retry "
        "de session _http_utils.py:15) => flag 'vu' perdu sur hoquet transitoire."
    )


def test_lotd_int_01_restore_watched_echec_transitoire_liste_films(tmp_path: Path) -> None:
    """LOTD-INT-01 : un echec HTTP transitoire (404/5xx epuise) sur la liste des
    films pendant restore_watched devrait consommer une tentative et re-essayer
    (c'est le but du `continue` jellyfin_sync.py:205-207). Or le catch ne couvre
    que (ConnectionError, OSError, TimeoutError, ValueError) : JellyfinError
    (IntegrationError -> Exception) s'echappe => restauration ABANDONNEE.
    """
    snapshot, operations, movie = _watched_fixture(tmp_path)
    # 1er GET /Items -> 404 (non re-tente par la session), suivants -> 200.
    with _MockHTTP(_jellyfin_routes([movie], items_statuses=[404])) as server:
        client = JellyfinClient(server.url, "jf-mock-key", timeout_s=5)
        try:
            result = restore_watched(
                client,
                "u1",
                snapshot,
                operations,
                initial_delay_s=0.02,
                retry_delay_s=0.02,
                max_retries=3,
            )
        except JellyfinError as exc:
            pytest.xfail(
                "LOTD-INT-01 CONFIRME : JellyfinError s'echappe de la boucle retry de "
                f"restore_watched (catch jellyfin_sync.py:205 trop etroit) — {exc}. "
                "La restauration des flags 'vu' est abandonnee au lieu d'etre re-tentee."
            )
        finally:
            client.close()
    # Comportement attendu si le catch est corrige : tentative 2 reussit.
    assert result.restored == 1, result.to_dict()


# ---------------------------------------------------------------------------
# 3. Timeouts : mock qui dort > timeout => erreur bornee, pas de hang
# ---------------------------------------------------------------------------

# Le retry de session (3 retries + backoff 0.5/1/2s) multiplie le timeout
# unitaire : 4 tentatives x 1s + 3.5s de backoff ~= 8s. Borne large a 30s.
_TIMEOUT_WALL_CAP_S = 30.0


def test_timeout_jellyfin_respecte_pas_de_hang(tmp_path: Path) -> None:
    with _MockHTTP(_jellyfin_routes(info_sleep_s=2.0)) as server:
        api = _make_api(tmp_path)
        t0 = time.monotonic()
        res = api.integrations.test_jellyfin_connection(url=server.url, api_key="jf-mock-key", timeout_s=1)
        elapsed = time.monotonic() - t0
    assert res["ok"] is False, res
    assert str(res.get("message") or "").strip()
    assert elapsed < _TIMEOUT_WALL_CAP_S, f"hang suspect : {elapsed:.1f}s pour timeout_s=1"


def test_timeout_jellyfin_message_mentionne_le_timeout(tmp_path: Path) -> None:
    """LOTD-INT-02 (dynamique) : le message d'un read-timeout doit permettre a
    l'utilisateur de diagnostiquer un TIMEOUT (pas seulement 'connexion')."""
    with _MockHTTP(_jellyfin_routes(info_sleep_s=2.0)) as server:
        api = _make_api(tmp_path)
        res = api.integrations.test_jellyfin_connection(url=server.url, api_key="jf-mock-key", timeout_s=1)
    assert res["ok"] is False, res
    msg = str(res.get("message") or "")
    if "timeout" not in msg.lower() and "timed out" not in msg.lower():
        pytest.xfail(
            "LOTD-INT-02 CONFIRME : read-timeout classe sans mention de timeout "
            f"dans le message utilisateur : {msg[:200]!r}"
        )


# ---------------------------------------------------------------------------
# 4. Secrets : aucun token mock en clair dans les logs
# ---------------------------------------------------------------------------

_JF_SECRET = "JF-SECRET-TOKEN-abc123DEF"
_RA_SECRET = "RA-SECRET-KEY-456ghiJKL"
_TM_SECRET = "TMDB-SECRET-KEY-789mnoPQR"


@pytest.fixture
def root_log_capture() -> Any:
    """Capture root DEBUG + scrubber installe comme en prod (app.py au boot).

    Restaure integralement l'etat logging (handler, level, filtres ajoutes par
    install_global_scrubber) pour ne pas polluer le reste de la suite.
    """
    root = logging.getLogger()
    records: List[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                records.append(self.format(record))
            except Exception:  # noqa: BLE001 — la capture ne doit jamais casser le test
                pass

    handler = _Capture(level=logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    prev_level = root.level
    prev_root_filters = list(root.filters)
    prev_handler_filters = {id(h): list(h.filters) for h in root.handlers}
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    install_global_scrubber()
    try:
        yield records
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_level)
        for f in list(root.filters):
            if f not in prev_root_filters:
                root.removeFilter(f)
        for h in root.handlers:
            prev = prev_handler_filters.get(id(h))
            if prev is None:
                continue
            for f in list(h.filters):
                if f not in prev:
                    h.removeFilter(f)


def test_aucun_secret_en_clair_dans_les_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root_log_capture: List[str]
) -> None:
    """Grep des 3 tokens mock dans TOUT ce qui part vers le root logger (DEBUG)
    pendant des appels reels : Jellyfin OK, Radarr OK, TMDb en echec reseau
    local (URL ?api_key=... presente dans les logs urllib3/warnings TMDb =>
    le scrubber doit la caviarder)."""
    api = _make_api(tmp_path)
    with _MockHTTP(_jellyfin_routes()) as jf, _MockHTTP(_radarr_routes()) as ra:
        res_jf = api.integrations.test_jellyfin_connection(url=jf.url, api_key=_JF_SECRET, timeout_s=5)
        res_ra = api.integrations.test_radarr_connection(url=ra.url, api_key=_RA_SECRET, timeout_s=5)
    assert res_jf["ok"] is True
    assert res_ra["ok"] is True

    closed = find_free_port()
    monkeypatch.setattr("cinesort.infra.tmdb_client.TMDB_API_BASE", f"http://127.0.0.1:{closed}/3")
    res_tm = api.integrations.test_tmdb_key(_TM_SECRET, str(tmp_path / "state"), timeout_s=2)
    assert res_tm["ok"] is False  # cle bidon + endpoint local ferme => erreur propre

    blob = "\n".join(root_log_capture)
    assert _JF_SECRET not in blob, "token Jellyfin en clair dans les logs"
    assert _RA_SECRET not in blob, "cle Radarr en clair dans les logs"
    assert _TM_SECRET not in blob, "cle TMDb en clair dans les logs"
    # Toute occurrence api_key= dans les logs doit etre caviardee.
    for line in root_log_capture:
        low = line.lower()
        if "api_key=" in low or "apikey=" in low:
            assert "[REDACTED]" in line, f"api_key non caviarde : {line[:200]!r}"


def test_lotd_int_03_message_erreur_tmdb_ne_leak_pas_la_cle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """LOTD-INT-03 : le message renvoye au FRONTEND par test_tmdb_key en echec
    reseau ('Erreur reseau: {exc}') ne doit pas contenir la cle API (politique
    repo : cf _safe_integration_error 'ne pas leak exc string'). L'exception
    requests contient l'URL complete avec ?api_key=... => verification reelle.
    """
    closed = find_free_port()
    monkeypatch.setattr("cinesort.infra.tmdb_client.TMDB_API_BASE", f"http://127.0.0.1:{closed}/3")
    api = _make_api(tmp_path)
    res = api.integrations.test_tmdb_key(_TM_SECRET, str(tmp_path / "state"), timeout_s=2)
    assert res["ok"] is False, res
    msg = str(res.get("message") or "")
    assert msg.strip()
    if _TM_SECRET in msg:
        pytest.xfail(
            "LOTD-INT-03 CONFIRME : la cle TMDb apparait en clair dans le message "
            "d'erreur renvoye au frontend (tmdb_client.validate_key:407 'Erreur "
            "reseau: {e}' — l'exception requests embarque l'URL ?api_key=...)."
        )


# ---------------------------------------------------------------------------
# 5. TMDb sans reseau reel
# ---------------------------------------------------------------------------


def test_tmdb_cle_vide_erreur_validation_sans_reseau(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    res = api.integrations.test_tmdb_key("", str(tmp_path / "state"), timeout_s=2)
    assert res["ok"] is False, res
    assert str(res.get("message") or "").strip()


def test_tmdb_posters_sans_cle_reason_tmdb_not_configured(tmp_path: Path) -> None:
    """Settings vierges (aucune cle TMDb) => contrat R6-G/audit 2026-06-08 :
    ok=True, posters={}, reason='tmdb_not_configured' — et AUCUN appel reseau."""
    api = _make_api(tmp_path)
    res = api.integrations.get_tmdb_posters([603, 550])
    assert res["ok"] is True, res
    assert res["posters"] == {}
    assert res.get("reason") == "tmdb_not_configured"
