# -*- coding: utf-8 -*-
"""Lot D (verif totale 2026-07) — chaine 4.7 REST PUR, bout-en-bout.

Chaine verifiee sur un RestApiServer EPHEMERE (port libre, jamais 8642) adosse
a une bibliotheque VIRTUELLE JETABLE (tempfile.TemporaryDirectory, mini .mkv
factices + .srt + .nfo). Aucun binaire externe requis (probe_backend="none").

Scenarios figes (dans l'ordre) :
  01. GET /api/health public (sans token) : ok/version/ts, PAS d'active_run_id
      au repos.
  02. GET /api/spec public : OpenAPI 3.0.3 parseable, les 6 facades presentes
      (run, settings, quality, integrations, library, runtime), bearerAuth.
  03. Auth avec CINESORT_DISABLE_LOCAL_AUTH=1 (posee AVANT le start du
      serveur) : 401 sans token, 401 token faux, 200 token correct.
  03b. Garde xfail nominative [BUG-LOTD-401-RST-BODY] (voir ci-dessous).
  04. Legacy POST /api/<methode> (Pass 1 desactivee par defaut, P0 #233) :
      410 Gone "Use /api/<facade>/<method> instead" ; l'auth passe AVANT le
      dispatch (401 sans token) ; methode facade inconnue -> 404.
  05. Run reel scan+plan sur la bibliotheque virtuelle : start_plan 200 +
      run_id ; double start immediat -> 409 (convention http_status opt-in
      d'un endpoint METIER reel, champ http_status consomme par le dispatch) ;
      /api/health expose active_run_id PENDANT le run et le retire apres.
  06. Garde xfail nominative [BUG-LOTD-ITERVIDEOS-KWARG] (voir ci-dessous).
  07. Rate-limit : seuil REEL 5 echecs / 60 s par IP (cap global 20) ->
      sequence 401 x5 puis 429 (+ Retry-After: 60), 429 persistant, retour a
      401 apres expiration de la fenetre (time-travel des timestamps),
      200 + purge du compteur apres auth reussie.
  08. _MAX_BODY_SIZE (16 Mo) : body annonce/envoye de 17 Mo -> rejet propre
      413 sans crash, le serveur repond encore apres.

BUG APP CONNU (constate par cette chaine le 2026-07-08 — REPORTE, pas corrige ;
le test 06 fait pytest.xfail() tant que le bug est present et redeviendra
passant de lui-meme une fois le bug corrige) :
  [BUG-LOTD-ITERVIDEOS-KWARG]
      cinesort/ui/api/run_read_support.py:100 appelle
      `core.iter_videos(cfg, folder)` SANS le kwarg keyword-only OBLIGATOIRE
      `min_video_bytes` (signature : cinesort/domain/scan_helpers.py:80).
      Des que la resolution directe du fichier video echoue (fichier
      supprime/renomme apres le plan, ou row sans nom video), le fallback
      leve TypeError — non attrape par le `except (OSError, PermissionError)`
      local — et get_quality_report repond {ok:false,
      error:"quality_report_failed", message:"iter_videos() missing 1
      required keyword-only argument: 'min_video_bytes'"}. Le meme crash se
      declenche spontanement pendant l'auto-scoring qualite d'un run nominal
      (observe 2 fois sur 2 runs d'exploration, cf
      docs/internal/verif_totale_2026_07/lotd/chain_rest_observations.txt).

  [BUG-LOTD-401-RST-BODY]
      Les reponses emises AVANT lecture du body (401 auth, 410 legacy, 404
      methode inconnue, 413 trop gros) ne drainent PAS le body de la requete.
      Le serveur (HTTP/1.0, close apres reponse) ferme alors la socket avec
      des octets non lus dans son buffer de reception -> TCP RST au lieu de
      FIN -> sous Windows le client peut PERDRE la reponse d'erreur deja
      bufferisee (ConnectionAbortedError WinError 10053 au lieu du JSON 401).
      Observe de maniere intermittente (1 run sur 3) sur un POST 2 octets
      avec mauvais token. Impact reel : un client REST (fetch dashboard,
      curl) peut voir "erreur reseau" au lieu de "Cle d'acces invalide".
      Garde : test_03b (probabiliste — xfail des qu'un abort est observe sur
      30 essais ; redevient passant une fois le body draine ou keep-alive).

LIMITES explicites :
  - Rate-limit : en production loopback, `_is_rate_limited` EXEMPTE totalement
    les IPs locales (_LOCAL_CLIENT_IPS, fix definitif 2026-06-07) — un client
    127.0.0.1 ne peut donc JAMAIS observer un 429 reel. Le test 07 patch
    `rest_server._LOCAL_CLIENT_IPS = frozenset()` (restaure en finally) pour
    exercer la pile HTTP complete comme un client distant.
  - Expiration de fenetre : verifiee par time-travel des timestamps du
    limiter (fenetre reelle = 60 s, dormir 60 s rendrait le test fragile).
  - Le bypass localhost OFF (CINESORT_DISABLE_LOCAL_AUTH absent) n'est PAS
    reteste ici (deja couvert par les sweeps).
  - probe_backend="none" : la chaine se degrade proprement sans
    ffprobe/mediainfo ; les branches qui exigent le binaire ne sont pas
    exercees.

Lancer :
  "C:/Users/blanc/projects/CineSort/.venv/Scripts/python.exe" -X utf8 -m pytest \
      tests/test_lotd_chain_rest.py -q
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import tempfile
import time
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest

from tests._helpers import find_free_port, join_background_threads

# Demarre un serveur REST reel -> exclu des sweeps rapides (marker projet).
pytestmark = pytest.mark.runtime

# Token >= 32 chars (MIN_LAN_TOKEN_LENGTH) pour rester representatif de la prod.
_TOKEN = "lotd-rest-chain-token-0123456789abcdef"
_WRONG_TOKEN = "lotd-wrong-token-ffffffffffffffffff"

# 150 dossiers -> le run scan+plan dure plusieurs secondes (~28 ms/dossier
# observe), ce qui rend deterministes le 409 double-start et l'observation
# d'active_run_id dans /api/health. Augmenter N si flaky un jour.
_N_FOLDERS = 150

_ENV_FORCED = {
    # test_reset(min_video_bytes=...) n'est autorise qu'en mode E2E.
    "CINESORT_E2E": "1",
    # Regle mission Lot D : posee AVANT le start du serveur.
    "CINESORT_DISABLE_LOCAL_AUTH": "1",
}
# Garanties d'etat : Pass 1 legacy doit rester au defaut (desactivee) et le
# debug auth ne doit pas polluer les logs.
_ENV_CLEARED = (
    "CINESORT_REST_LEGACY_PASS1_ENABLED",
    "CINESORT_REST_LEGACY_PASS1_DISABLED",
    "CINESORT_DEBUG",
)


def _build_virtual_library(root: Path, count: int) -> None:
    """Bibliotheque virtuelle jetable : mini .mkv (bytes arbitraires) + .srt + .nfo."""
    for i in range(count):
        year = 2000 + (i % 26)
        folder = root / f"Film Test {i:03d} ({year})"
        folder.mkdir()
        # Magic bytes EBML + padding : fichier factice, jamais probe (probe none).
        (folder / f"Film.Test.{i:03d}.{year}.1080p.mkv").write_bytes(b"\x1a\x45\xdf\xa3" + bytes(2048))
        (folder / f"Film.Test.{i:03d}.fr.srt").write_text(
            "1\n00:00:01,000 --> 00:00:02,000\nBonjour\n", encoding="utf-8"
        )
        (folder / "movie.nfo").write_text(
            f"<movie><title>Film Test {i:03d}</title><year>{year}</year></movie>",
            encoding="utf-8",
        )


def _request(
    port: int,
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
    timeout: float = 30.0,
) -> Tuple[int, Any, Dict[str, str]]:
    """Requete HTTP brute (stdlib pur, comme un client REST externe)."""
    conn = HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        resp_headers = {k: v for k, v in resp.getheaders()}
        try:
            parsed: Any = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            parsed = raw
        return resp.status, parsed, resp_headers
    finally:
        with contextlib.suppress(Exception):
            conn.close()


@pytest.fixture(scope="module")
def chain():
    """Serveur REST ephemere + API reelle + bibliotheque virtuelle jetable."""
    saved_env: Dict[str, Optional[str]] = {}
    for key, value in _ENV_FORCED.items():
        saved_env[key] = os.environ.get(key)
        os.environ[key] = value
    for key in _ENV_CLEARED:
        saved_env[key] = os.environ.get(key)
        os.environ.pop(key, None)

    # Imports APRES la pose des env vars (CINESORT_DISABLE_LOCAL_AUTH est lue
    # par requete, mais on respecte strictement la regle "env avant start").
    import cinesort.ui.api.cinesort_api as backend
    from cinesort.domain import core as domain_core
    from cinesort.infra.rest_server import RestApiServer

    saved_min_video_bytes = domain_core.MIN_VIDEO_BYTES

    tmp = tempfile.TemporaryDirectory(prefix="cinesort_lotd_rest_", ignore_cleanup_errors=True)
    base = Path(tmp.name)
    root = base / "root"
    state_dir = base / "state"
    root.mkdir()
    state_dir.mkdir()
    _build_virtual_library(root, _N_FOLDERS)

    settings = {
        "root": str(root),
        "state_dir": str(state_dir),
        "tmdb_enabled": False,
        "jellyfin_enabled": False,
        "plex_enabled": False,
        "watch_enabled": False,
        "plugins_enabled": False,
        "perceptual_enabled": False,
        "rest_api_enabled": True,
        "rest_api_token": _TOKEN,
        # Degrade proprement sans ffprobe/mediainfo (binaires absents en CI).
        "probe_backend": "none",
    }

    api = backend.CineSortApi()
    saved = api.settings.save_settings(dict(settings))
    assert saved.get("ok") is True, f"save_settings a echoue: {saved}"
    # Hook E2E officiel : abaisse le seuil taille video pour les .mkv factices.
    reset = api.test_reset(min_video_bytes=1024)
    assert reset.get("ok") is True, f"test_reset a echoue: {reset}"

    port = find_free_port()
    server = RestApiServer(api, port=port, token=_TOKEN)
    server.start()

    # Attente readiness via /api/health (public).
    deadline = time.monotonic() + 10.0
    ready = False
    while time.monotonic() < deadline:
        try:
            status, _, _ = _request(port, "GET", "/api/health", timeout=2.0)
            if status == 200:
                ready = True
                break
        except OSError:
            pass
        time.sleep(0.05)
    if not ready:
        server.stop()
        tmp.cleanup()
        pytest.fail("Le serveur REST ephemere n'a pas demarre en 10 s")

    ctx: Dict[str, Any] = {
        "port": port,
        "server": server,
        "api": api,
        "root": root,
        "state_dir": state_dir,
        "settings": settings,
        # Rempli par test_05, consomme par test_06.
        "run_id": None,
    }
    yield ctx

    server.stop()
    domain_core.MIN_VIDEO_BYTES = saved_min_video_bytes
    for key, value in saved_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    # #960 : le handle SQLite est tenu par les threads de fond de l'app. On
    # les joint d'abord, sinon le dossier reste dans %TEMP% pour de bon
    # (l'OS ne le purge pas).
    join_background_threads()
    with contextlib.suppress(OSError, PermissionError):
        tmp.cleanup()


# ---------------------------------------------------------------------------
# 01 — /api/health public
# ---------------------------------------------------------------------------


def test_01_health_public_sans_token(chain):
    status, body, headers = _request(chain["port"], "GET", "/api/health")
    assert status == 200
    assert isinstance(body, dict)
    assert body.get("ok") is True
    assert isinstance(body.get("version"), str) and body["version"]
    assert isinstance(body.get("ts"), (int, float))
    # Au repos : PAS de run actif -> la cle est absente (contrat health).
    assert "active_run_id" not in body
    # V3-04 : correlation requete/logs systematique.
    assert headers.get("X-Request-ID")


# ---------------------------------------------------------------------------
# 02 — /api/spec OpenAPI + 6 facades
# ---------------------------------------------------------------------------


def test_02_spec_openapi_6_facades(chain):
    status, spec, _ = _request(chain["port"], "GET", "/api/spec")
    assert status == 200
    assert isinstance(spec, dict), "le spec doit etre du JSON parseable"
    assert spec.get("openapi") == "3.0.3"
    assert spec.get("info", {}).get("title") == "CineSort REST API"
    schemes = spec.get("components", {}).get("securitySchemes", {})
    assert schemes.get("bearerAuth", {}).get("scheme") == "bearer"

    paths = spec.get("paths", {})
    assert isinstance(paths, dict) and paths, "spec sans paths"
    assert all(p.startswith("/api/") for p in paths)

    facades = {"run", "settings", "quality", "integrations", "library", "runtime"}
    seen = {p.split("/")[2] for p in paths if len(p.split("/")) >= 4}
    missing = facades - seen
    assert not missing, f"facades absentes du spec: {sorted(missing)}"
    # Pass 1 desactivee par defaut : AUCUN path direct /api/<methode> sans facade.
    directs = [p for p in paths if len(p.split("/")) < 4]
    assert directs == [], f"paths legacy directs inattendus: {directs}"


# ---------------------------------------------------------------------------
# 03 — auth Bearer avec CINESORT_DISABLE_LOCAL_AUTH=1
# ---------------------------------------------------------------------------


def test_03_auth_401_sans_token_200_avec(chain):
    port = chain["port"]

    # NB : probes 401 envoyees SANS body. Le serveur repond 401 avant de lire
    # le body ; avec un body non lu la fermeture provoque un RST qui peut
    # avaler la reponse ([BUG-LOTD-401-RST-BODY], garde dediee test_03b).
    status, body, headers = _request(port, "POST", "/api/settings/get_settings")
    assert status == 401
    assert body.get("ok") is False
    assert body.get("message") == "Cle d'acces invalide ou manquante."
    assert headers.get("X-Request-ID")

    status, body, _ = _request(port, "POST", "/api/settings/get_settings", token=_WRONG_TOKEN)
    assert status == 401
    assert body.get("ok") is False

    status, body, _ = _request(port, "POST", "/api/settings/get_settings", body={}, token=_TOKEN)
    assert status == 200
    assert isinstance(body, dict)
    # get_settings renvoie le payload settings canonique (root/state_dir presents).
    assert str(chain["root"]) in str(body.get("root") or body)


def test_03b_bug_guard_401_rst_body_non_draine(chain):
    """Garde nominative [BUG-LOTD-401-RST-BODY].

    Un POST avec un PETIT body et un mauvais token doit recevoir le JSON 401.
    Aujourd'hui le serveur repond sans drainer le body puis ferme -> RST ->
    le client peut subir ConnectionAbortedError et ne jamais voir le 401.
    Le declenchement est une course TCP (observe ~1 run sur 3) : on sonde 30
    fois ; le MOINDRE abort prouve le bug -> xfail nominatif. Une fois le bug
    corrige (drain du body ou keep-alive HTTP/1.1), plus aucun abort n'est
    possible et le test redevient passant de lui-meme.
    """
    port = chain["port"]
    aborts = 0
    for _ in range(30):
        try:
            status, _, _ = _request(port, "POST", "/api/settings/get_settings", body={}, token=_WRONG_TOKEN)
            assert status == 401
        except (ConnectionAbortedError, ConnectionResetError):
            aborts += 1
    if aborts:
        pytest.xfail(
            "[BUG-LOTD-401-RST-BODY] reponse 401 emise sans drainer le body "
            f"-> RST : {aborts}/30 requetes ont perdu la reponse "
            "(ConnectionAborted/Reset au lieu du JSON 401)"
        )


# ---------------------------------------------------------------------------
# 04 — legacy POST /api/<methode> -> 410 Gone
# ---------------------------------------------------------------------------


def test_04_legacy_post_410(chain):
    port = chain["port"]

    # NB : probes envoyees SANS body — les reponses 401/410/404 partent avant
    # la lecture du body (cf [BUG-LOTD-401-RST-BODY]).
    # L'auth passe AVANT le dispatch : sans token le legacy repond 401, pas 410.
    status, _, _ = _request(port, "POST", "/api/get_settings")
    assert status == 401

    for legacy in ("get_settings", "start_plan", "methode_inconnue_xyz"):
        status, body, _ = _request(port, "POST", f"/api/{legacy}", token=_TOKEN)
        assert status == 410, f"/api/{legacy} attendu 410, obtenu {status}"
        assert body.get("ok") is False
        assert body.get("message") == "Use /api/<facade>/<method> instead"

    # Methode inconnue AVEC prefixe facade valide -> 404 "Methode inconnue".
    status, body, _ = _request(port, "POST", "/api/run/methode_inconnue_xyz", token=_TOKEN)
    assert status == 404
    assert body.get("message") == "Methode inconnue"


# ---------------------------------------------------------------------------
# 05 — run reel : active_run_id dans health + 409 http_status opt-in
# ---------------------------------------------------------------------------


def test_05_run_active_run_id_et_409_double_start(chain):
    port = chain["port"]
    payload = {"settings": dict(chain["settings"])}

    status, body, _ = _request(port, "POST", "/api/run/start_plan", body=payload, token=_TOKEN)
    assert status == 200, f"start_plan #1 attendu 200, obtenu {status}: {body}"
    assert body.get("ok") is True
    run_ids = [body["run_id"]]

    # Double start immediat -> 409 metier via la convention http_status opt-in
    # (run_flow_support.start_plan renvoie http_status=409, le dispatch le
    # consomme et l'applique au code HTTP). Retry <= 3 au cas improbable ou un
    # run se terminerait avant l'arrivee de la 2e requete.
    conflict = None
    for _ in range(3):
        status, body, _ = _request(port, "POST", "/api/run/start_plan", body=payload, token=_TOKEN)
        if status == 409:
            conflict = body
            break
        assert status == 200, f"double start: statut inattendu {status}: {body}"
        run_ids.append(body["run_id"])
    assert conflict is not None, (
        f"jamais de 409 en 3 double-starts (runs demarres: {run_ids}) — "
        "bibliotheque virtuelle trop petite ? augmenter _N_FOLDERS"
    )
    assert conflict.get("ok") is False
    assert "deja en cours" in str(conflict.get("message") or "")
    # Le champ http_status est CONSOMME par le dispatch, jamais expose au client.
    assert "http_status" not in conflict

    active_run = run_ids[-1]
    chain["run_id"] = active_run

    # PENDANT le run : /api/health expose active_run_id.
    seen_active = None
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        status, health, _ = _request(port, "GET", "/api/health")
        assert status == 200
        if health.get("active_run_id"):
            seen_active = health["active_run_id"]
            break
        time.sleep(0.02)
    assert seen_active == active_run, (
        f"health n'a pas expose active_run_id={active_run} pendant le run (vu: {seen_active})"
    )

    # Attendre la fin du run (get_status facade).
    final_status = None
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        status, rs, _ = _request(port, "POST", "/api/run/get_status", body={"run_id": active_run}, token=_TOKEN)
        assert status == 200
        if isinstance(rs, dict) and rs.get("done"):
            final_status = rs
            break
        time.sleep(0.1)
    assert final_status is not None, "le run scan+plan n'a pas fini en 120 s"
    assert final_status.get("status") == "DONE"
    assert final_status.get("running") is False

    # APRES le run : active_run_id disparait du health (slot libere).
    deadline = time.monotonic() + 10.0
    gone = False
    while time.monotonic() < deadline:
        _, health, _ = _request(port, "GET", "/api/health")
        if not health.get("active_run_id"):
            gone = True
            break
        time.sleep(0.05)
    assert gone, "active_run_id encore present dans health apres la fin du run"


# ---------------------------------------------------------------------------
# 06 — garde xfail nominative [BUG-LOTD-ITERVIDEOS-KWARG]
# ---------------------------------------------------------------------------


def test_06_bug_guard_quality_iter_videos_kwarg(chain):
    """Chaine plan -> get_quality_report quand le fichier video a disparu.

    Attendu (une fois le bug corrige) : degradation propre {ok:false} type
    "media introuvable". Actuellement : TypeError iter_videos() remonte au
    boundary et fuit dans message -> xfail nominatif tant que present.
    """
    run_id = chain.get("run_id")
    if not run_id:
        pytest.skip("run du test_05 indisponible (test precedent en echec)")
    port = chain["port"]

    status, plan, _ = _request(port, "POST", "/api/run/get_plan", body={"run_id": run_id}, token=_TOKEN)
    assert status == 200 and plan.get("ok") is True
    rows = plan.get("rows") or []
    assert rows, "plan vide : la bibliotheque virtuelle n'a produit aucune row"

    row = rows[0]
    folder = Path(str(row["folder"])).resolve()
    root = chain["root"].resolve()
    # SECURITE ABSOLUE : ne JAMAIS toucher un chemin hors tempdir.
    assert str(folder).startswith(str(root)), f"row.folder hors tempdir: {folder}"
    video = folder / str(row["video"])
    assert video.is_file()
    video.unlink()  # simule un fichier deplace/supprime apres le plan

    status, report, _ = _request(
        port,
        "POST",
        "/api/quality/get_quality_report",
        body={"run_id": run_id, "row_id": row["row_id"]},
        token=_TOKEN,
    )
    assert status == 200
    assert isinstance(report, dict)
    message = str(report.get("message") or "")

    if report.get("ok") is False and "iter_videos" in message:
        pytest.xfail(
            "[BUG-LOTD-ITERVIDEOS-KWARG] run_read_support.py:100 appelle "
            "core.iter_videos(cfg, folder) sans le kwarg obligatoire "
            "min_video_bytes -> TypeError au lieu d'une degradation propre "
            f"(message: {message!r})"
        )

    # Comportement attendu apres correction : erreur metier propre, sans
    # fuite de TypeError interne.
    assert report.get("ok") is False
    assert "min_video_bytes" not in message
    assert "TypeError" not in message


# ---------------------------------------------------------------------------
# 07 — rate-limit 429 (seuils reels) + reset de fenetre
# ---------------------------------------------------------------------------


def test_07_rate_limit_429_seuils_reels(chain):
    import cinesort.infra.rest_server as rest_mod

    port = chain["port"]
    server = chain["server"]

    # Seuils REELS figes (si ces constantes changent, ce test doit être revu).
    assert rest_mod._RATE_LIMIT_MAX_FAILURES == 5
    assert rest_mod._RATE_LIMIT_WINDOW_S == 60.0
    assert server._rate_limiter._max_global == 20  # 4x per-IP (S6 audit)

    # LIMITE (voir docstring module) : loopback est exempte par design -> on
    # patch _LOCAL_CLIENT_IPS pour etre traite comme un client distant sur la
    # vraie pile HTTP. Restauration garantie en finally.
    saved_ips = rest_mod._LOCAL_CLIENT_IPS
    rest_mod._LOCAL_CLIENT_IPS = frozenset()
    try:
        server._rate_limiter.reset()

        # 5 echecs Bearer FAUX (header present -> record_failure) : 401 chacun.
        # Probes SANS body (cf [BUG-LOTD-401-RST-BODY]).
        statuses = []
        retry_after = None
        for _ in range(rest_mod._RATE_LIMIT_MAX_FAILURES + 1):
            status, _, headers = _request(port, "POST", "/api/settings/get_settings", token=_WRONG_TOKEN)
            statuses.append(status)
            if status == 429:
                retry_after = headers.get("Retry-After")
                break
        assert statuses == [401] * 5 + [429], f"sequence observee: {statuses}"
        assert retry_after == "60"  # ITER14 : Retry-After = window_s

        # Le blocage persiste tant que la fenetre n'est pas expiree.
        status, body, _ = _request(port, "POST", "/api/settings/get_settings", token=_WRONG_TOKEN)
        assert status == 429
        assert "Trop de tentatives" in str(body.get("message") or "")

        # Expiration de fenetre par time-travel : on vieillit les timestamps
        # au-dela de window_s -> la purge du limiter doit debloquer l'IP.
        with server._rate_limiter._lock:
            for ip in list(server._rate_limiter._failures):
                server._rate_limiter._failures[ip] = [
                    t - (rest_mod._RATE_LIMIT_WINDOW_S + 1.0) for t in server._rate_limiter._failures[ip]
                ]
        status, _, _ = _request(port, "POST", "/api/settings/get_settings", token=_WRONG_TOKEN)
        assert status == 401, "apres expiration de la fenetre, retour a 401 (pas 429)"

        # Auth reussie -> record_success purge le compteur de l'IP.
        status, _, _ = _request(port, "POST", "/api/settings/get_settings", body={}, token=_TOKEN)
        assert status == 200
        with server._rate_limiter._lock:
            assert server._rate_limiter._failures == {}
    finally:
        rest_mod._LOCAL_CLIENT_IPS = saved_ips
        server._rate_limiter.reset()


# ---------------------------------------------------------------------------
# 08 — _MAX_BODY_SIZE : body 17 Mo -> 413 propre, serveur toujours vivant
# ---------------------------------------------------------------------------


def test_08_max_body_size_17mo_rejet_propre(chain):
    from cinesort.infra import rest_server as rest_mod

    port = chain["port"]
    big_len = 17 * 1024 * 1024
    assert big_len > rest_mod._MAX_BODY_SIZE  # 16 Mo reels

    head = (
        f"POST /api/settings/get_settings HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        f"Authorization: Bearer {_TOKEN}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {big_len}\r\n"
        f"\r\n"
    ).encode("ascii")

    # Variante A : Content-Length annonce 17 Mo, AUCUN octet de body envoye.
    # Le serveur repond 413 sans lire le body ; comme rien ne traine dans son
    # buffer de reception, la fermeture est propre (FIN, pas RST) et le 413
    # est lisible de maniere deterministe.
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        sock.sendall(head)
        sock.settimeout(10)
        # HTTP/1.0 + close : on lit jusqu'a la fermeture (le JSON peut arriver
        # dans un segment TCP separe des headers).
        raw = b""
        while len(raw) < 65536:
            part = sock.recv(4096)
            if not part:
                break
            raw += part
    finally:
        sock.close()
    first_line = raw.split(b"\r\n", 1)[0]
    assert b" 413 " in first_line, f"attendu 413, recu: {first_line!r}"
    assert b'"ok": false' in raw or b'"ok":false' in raw

    status, body, _ = _request(port, "GET", "/api/health")
    assert status == 200 and body.get("ok") is True

    # Variante B : envoi REEL de 17 Mo complets. Le serveur repond 413 puis
    # ferme la connexion sans lire -> l'envoi client est interrompu (abort/
    # reset), ce qui est le rejet propre attendu. Aucun crash serveur.
    sock = socket.create_connection(("127.0.0.1", port), timeout=15)
    outcome = None
    try:
        sock.sendall(head)
        sock.settimeout(15)
        chunk = b"x" * (1024 * 1024)
        try:
            for _ in range(17):
                sock.sendall(chunk)
            raw = sock.recv(4096)
            if not raw:
                outcome = "aborted"  # connexion fermee, reponse perdue (RST)
            elif b" 413 " in raw.split(b"\r\n", 1)[0]:
                outcome = "response"
            else:
                outcome = f"unexpected:{raw[:80]!r}"
        except OSError:
            # ConnectionAbortedError/ConnectionResetError : le serveur a rejete
            # et ferme pendant l'envoi — rejet propre (anti-DoS, il ne lira
            # jamais les 17 Mo).
            outcome = "aborted"
    finally:
        sock.close()
    assert outcome in ("response", "aborted"), f"comportement inattendu: {outcome}"

    # Le serveur repond toujours, y compris sur un POST metier authentifie.
    status, body, _ = _request(port, "GET", "/api/health")
    assert status == 200 and body.get("ok") is True
    status, body, _ = _request(port, "POST", "/api/settings/get_settings", body={}, token=_TOKEN)
    assert status == 200
