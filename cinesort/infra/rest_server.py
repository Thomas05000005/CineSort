"""REST API server — exposes CineSortApi over HTTP.

Uses stdlib http.server only — zero external dependencies.
All endpoints: POST /api/{method_name} with JSON body.
Public endpoints: GET /api/health, GET /api/spec.
Static files: GET /dashboard/* (web dashboard distant).
"""

from __future__ import annotations

import hmac
import inspect
import json
import logging
import mimetypes
import os
import ssl
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlsplit

from cinesort.infra.log_context import (
    clear_request_id,
    get_request_id,
    reset_remote_request,
    set_remote_request,
    set_request_id,
)
from cinesort.infra.network_utils import build_dashboard_url, get_local_ip

# Cf issues #72 + #73 : IPs considerees locales (loopback IPv4 + IPv6). Toute
# autre IP declenche le flag remote_request via ContextVar pour que les handlers
# sensibles (open_logs_folder, normalize_user_path) puissent reagir.
_LOCAL_CLIENT_IPS = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})
import contextlib

logger = logging.getLogger(__name__)

# Methods excluded from REST exposure (local-only or internal).
#
# V2-09 (4 mai 2026, polish v7.7.0) : `open_logs_folder` a ete RETIREE de cette
# liste pour fixer H18. Le bouton "Ouvrir les logs" de la vue Aide en mode
# supervision web (web/dashboard/views/help.js) ecouait sur "Endpoint inconnu"
# car le dispatch REST refusait la methode.
#
# Implication securite : `open_logs_folder` invoque `os.startfile(...)` cote
# SERVEUR (machine ou tourne CineSort). Si le navigateur supervision est sur une
# machine differente du serveur, l'explorateur s'ouvrira sur le serveur, pas chez
# l'utilisateur — ce qui est le comportement attendu en supervision LAN classique
# (l'utilisateur supervise sa propre instance). En LAN partage non-trust, la
# combinaison auth Bearer + token >= 32 chars + rate-limiter + bind 127.0.0.1
# par defaut limite le risque a un acteur deja authentifie. `open_path` reste
# exclu car prend un chemin arbitraire en parametre (vector path-traversal).
_EXCLUDED_METHODS: Set[str] = {
    "open_path",
    "log_api_exception",
    "log",
    "progress",
}

# Issue #84 PR 8 : noms des 5 facades introduites par le refactor god class.
# Le dispatcher REST decouvre les methodes de chaque facade et les expose sous
# l'URL "/api/{facade_name}/{method_name}" en plus des methodes directes
# (backward-compat preservee jusqu'a la PR 10).
# Cf docs/internal/REFACTOR_PLAN_84.md.
_FACADE_ATTR_NAMES: tuple = ("run", "settings", "quality", "integrations", "library", "runtime")

# Separateur dans l'URL pour distinguer facade et methode (ex: "run/start_plan").
_FACADE_SEPARATOR = "/"


# P0 #233 : kill switch pour Pass 1 (methodes directes "/api/<method>" sans
# facade). Quand desactivee, Pass 1 n'enregistre plus les methodes directes
# dans le dispatcher, et toute requete POST /api/<method> non prefixee par
# une facade reconnue renvoie 410 Gone avec le message
# "Use /api/<facade>/<method> instead".
#
# Defaut (FINAL phase migration 2026-05) : Pass 1 est DESACTIVEE par defaut.
# Le dashboard a ete migre sur "/api/<facade>/<method>" (run, settings, quality,
# integrations, library, runtime), donc le format legacy n'est plus necessaire
# en production. Le kill switch protege ainsi contre les regressions d'appel
# direct (audit + 410 Gone explicite).
#
# Pour RE-ACTIVER Pass 1 (cas E2E pywebview natif ou debug), positionner
# CINESORT_REST_LEGACY_PASS1_ENABLED=1 dans l'environnement avant lancement.
# L'ancienne variable CINESORT_REST_LEGACY_PASS1_DISABLED=1 reste lue pour
# forcer explicitement la desactivation (compat retro avec scripts existants).
def _legacy_pass1_disabled() -> bool:
    """Vrai si Pass 1 (legacy direct methods) doit etre desactivee.

    Defaut : True (Pass 1 desactivee par defaut a partir de la refonte 2026-05).

    Variables d'environnement :
    - CINESORT_REST_LEGACY_PASS1_ENABLED=1 : RE-active Pass 1 (debug, E2E natif).
    - CINESORT_REST_LEGACY_PASS1_DISABLED=1 : force la desactivation (compat retro).

    Si les deux sont positionnees, ENABLED gagne (re-activation explicite).
    """
    enabled_val = os.environ.get("CINESORT_REST_LEGACY_PASS1_ENABLED", "").strip().lower()
    if enabled_val in ("1", "true", "yes", "on"):
        return False  # explicitement re-active

    # Compat retro : si l'ancienne var est positionnee explicitement (n'importe
    # quelle valeur reconnue), on respecte sa semantique d'origine.
    disabled_val = os.environ.get("CINESORT_REST_LEGACY_PASS1_DISABLED", "").strip().lower()
    if disabled_val in ("1", "true", "yes", "on"):
        return True

    # Defaut final : Pass 1 desactivee.
    return True


# Maximum request body size (16 MB).
_MAX_BODY_SIZE = 16 * 1024 * 1024

# --- Rate limiting 401 ---------------------------------------------------
# Apres _RATE_LIMIT_MAX_FAILURES echecs d'auth depuis la meme IP en
# _RATE_LIMIT_WINDOW_S secondes, on repond 429.
_RATE_LIMIT_MAX_FAILURES = 5
_RATE_LIMIT_WINDOW_S = 60.0

# --- Dashboard statique ---------------------------------------------------
# Repertoire racine des fichiers statiques du dashboard distant.
_DASHBOARD_PREFIX = "/dashboard"
# §16b / Vague 0 v7.6.0 : shared design system servi par le REST pour le dashboard distant.
_SHARED_PREFIX = "/shared"
# V6-01 Polish Total v7.7.0 : fichiers de traduction servis via /locales/<locale>.json.
# Lus par web/dashboard/core/i18n.js au boot et a chaque setLocale().
_LOCALES_PREFIX = "/locales"
# Types MIME supplementaires (mimetypes stdlib ne couvre pas tout).
_EXTRA_MIME: Dict[str, str] = {
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".json": "application/json",
    ".map": "application/json",
}


def _resolve_dashboard_root() -> Path:
    """Localise le repertoire web/dashboard/ a cote du code source ou dans le bundle PyInstaller."""
    # PyInstaller : les datas sont extraites dans sys._MEIPASS
    base = Path(getattr(__import__("sys"), "_MEIPASS", ""))
    candidate = base / "web" / "dashboard"
    if candidate.is_dir():
        return candidate.resolve()
    # Dev : remonter depuis cinesort/infra/ vers la racine du projet
    project_root = Path(__file__).resolve().parents[2]
    candidate = project_root / "web" / "dashboard"
    if candidate.is_dir():
        return candidate.resolve()
    # Fallback : cwd
    return (Path.cwd() / "web" / "dashboard").resolve()


def _resolve_shared_root() -> Path:
    """Localise web/shared/ (design system v5, partage desktop + dashboard)."""
    base = Path(getattr(__import__("sys"), "_MEIPASS", ""))
    candidate = base / "web" / "shared"
    if candidate.is_dir():
        return candidate.resolve()
    project_root = Path(__file__).resolve().parents[2]
    candidate = project_root / "web" / "shared"
    if candidate.is_dir():
        return candidate.resolve()
    return (Path.cwd() / "web" / "shared").resolve()


def _resolve_locales_root() -> Path:
    """Localise locales/ (V6-01 i18n : fichiers JSON fr/en).

    Strategie identique aux autres _resolve_*_root : bundle puis dev puis cwd.
    """
    base = Path(getattr(__import__("sys"), "_MEIPASS", ""))
    candidate = base / "locales"
    if candidate.is_dir():
        return candidate.resolve()
    project_root = Path(__file__).resolve().parents[2]
    candidate = project_root / "locales"
    if candidate.is_dir():
        return candidate.resolve()
    return (Path.cwd() / "locales").resolve()


def _get_api_methods(api: Any) -> Dict[str, Any]:
    """Discover public callable methods on the API object.

    Issue #84 PR 8 : decouvre aussi les methodes des 5 facades (api.run,
    api.settings, ...) et les expose sous le path "{facade}/{method}".

    Resultat : les 2 voies sont actives simultanement, sans rupture
    de backward-compat :
    - "/api/start_plan" -> api.run.start_plan(...)
    - "/api/run/start_plan" -> api.run.start_plan(...)

    Quand la PR 10 supprimera les methodes directes de CineSortApi, seuls
    les paths "/api/{facade}/{method}" continueront a fonctionner.
    """
    methods: Dict[str, Any] = {}

    # Pass 1 : methodes directes sur l'API (comportement legacy).
    # P0 #233 (finalise 2026-05) : kill switch DESACTIVE PAR DEFAUT => Pass 1
    # n'enregistre rien sauf si CINESORT_REST_LEGACY_PASS1_ENABLED=1.
    # Le dispatcher renverra 410 Gone pour les appels legacy (cf RestRequestHandler).
    if not _legacy_pass1_disabled():
        for name in dir(api):
            if name.startswith("_"):
                continue
            if name in _EXCLUDED_METHODS:
                continue
            if name in _FACADE_ATTR_NAMES:
                # La facade elle-meme n'est pas un endpoint ; on walk dans la pass 2.
                continue
            attr = getattr(api, name, None)
            if callable(attr):
                methods[name] = attr

    # Pass 2 : methodes exposees par les facades (route "/api/{facade}/{method}").
    for facade_name in _FACADE_ATTR_NAMES:
        facade = getattr(api, facade_name, None)
        if facade is None:
            continue
        for method_name in dir(facade):
            if method_name.startswith("_"):
                continue
            if method_name in _EXCLUDED_METHODS:
                continue
            method = getattr(facade, method_name, None)
            if callable(method):
                methods[f"{facade_name}{_FACADE_SEPARATOR}{method_name}"] = method

    return methods


def generate_openapi_spec(api: Any, *, port: int = 8642) -> Dict[str, Any]:
    """Generate a minimal OpenAPI 3.0 spec from API introspection."""
    methods = _get_api_methods(api)
    paths: Dict[str, Any] = {}

    for name, method in sorted(methods.items()):
        sig = inspect.signature(method)
        params_schema: Dict[str, Any] = {"type": "object", "properties": {}}
        for pname, param in sig.parameters.items():
            if pname == "self":
                continue
            ptype = "string"
            if param.annotation == int:
                ptype = "integer"
            elif param.annotation == float:
                ptype = "number"
            elif param.annotation == bool:
                ptype = "boolean"
            elif param.annotation in (dict, Dict):
                ptype = "object"
            elif param.annotation in (list,):
                ptype = "array"
            params_schema["properties"][pname] = {"type": ptype}
            if param.default is inspect.Parameter.empty:
                params_schema.setdefault("required", []).append(pname)

        paths[f"/api/{name}"] = {
            "post": {
                "summary": name.replace("_", " ").capitalize(),
                "operationId": name,
                "requestBody": {
                    "required": bool(params_schema.get("required")),
                    "content": {"application/json": {"schema": params_schema}},
                },
                "responses": {
                    "200": {
                        "description": "Resultat JSON",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                },
                "security": [{"bearerAuth": []}],
            },
        }

    version = getattr(api, "_app_version", "0.0.0")
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "CineSort REST API",
            "version": str(version),
            "description": "API de pilotage CineSort.",
        },
        "servers": [{"url": f"http://localhost:{port}"}],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Cle d'acces (token Bearer) configuree dans les reglages CineSort.",
                },
            },
        },
    }


class _RateLimiter:
    """Limite le nombre d'echecs d'authentification par IP et globalement.

    Per-IP : apres *max_failures* echecs depuis la meme IP dans une fenetre
    de *window_s* secondes, les requetes suivantes sont rejetees 429.

    S6 audit — global : on ajoute un plafond agrege (toutes IPs confondues)
    a 4x le max per-IP par defaut, pour contrer la rotation d'IP sur un
    LAN partage. L'IP-rotation peut contourner le per-IP (5 IPs = 25 essais/
    min) mais pas le global.

    Purge des timestamps expires : a chaque appel (cout O(n) amorti
    negligeable car le dict est petit en usage reseau local).
    """

    def __init__(
        self,
        *,
        max_failures: int = _RATE_LIMIT_MAX_FAILURES,
        window_s: float = _RATE_LIMIT_WINDOW_S,
        global_multiplier: int = 4,
    ):
        self._max = max_failures
        self._window = window_s
        self._max_global = max_failures * max(1, int(global_multiplier))
        self._lock = threading.Lock()
        self._failures: Dict[str, List[float]] = {}

    def record_failure(self, ip: str) -> None:
        """Enregistre un echec d'auth pour cette IP."""
        now = time.time()
        with self._lock:
            self._purge_expired(now)
            self._failures.setdefault(ip, []).append(now)

    def record_success(self, ip: str) -> None:
        """Efface les echecs de cette IP (auth reussie) — S6 audit.

        Sans ca, un client avec 4 echecs recents reste proche du plafond
        meme apres avoir trouve le bon token, et peut s'auto-ban en cas de
        hickup reseau ulterieur.
        """
        with self._lock:
            self._failures.pop(ip, None)

    def is_blocked(self, ip: str) -> bool:
        """True si l'IP a depasse le seuil per-IP OU le seuil global."""
        now = time.time()
        with self._lock:
            self._purge_expired(now)
            timestamps = self._failures.get(ip, [])
            if len(timestamps) >= self._max:
                return True
            total = sum(len(ts) for ts in self._failures.values())
            return total >= self._max_global

    def reset(self) -> None:
        """Vide tous les compteurs (utile pour les tests)."""
        with self._lock:
            self._failures.clear()

    def _purge_expired(self, now: float) -> None:
        """Supprime les timestamps expires (> window_s) pour toutes les IPs."""
        cutoff = now - self._window
        expired_ips: List[str] = []
        for ip, timestamps in self._failures.items():
            self._failures[ip] = [t for t in timestamps if t > cutoff]
            if not self._failures[ip]:
                expired_ips.append(ip)
        for ip in expired_ips:
            del self._failures[ip]


class _CineSortHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the CineSort REST API."""

    # Set by RestApiServer before serving.
    api: Any = None
    api_methods: Dict[str, Any] = {}
    auth_token: str = ""
    cors_origin: str = "*"
    openapi_spec: Dict[str, Any] = {}
    rate_limiter: Optional[_RateLimiter] = None
    dashboard_root: Optional[Path] = None
    # V6-01 : root des fichiers locales/. Initialise par RestApiServer (cf
    # `locales_root = _resolve_locales_root()` plus bas).
    locales_root: Optional[Path] = None
    # 2026-06-08 : adresse de bind effective ("127.0.0.1" ou "0.0.0.0"). Utilisee
    # par _check_auth pour decider si le bypass d'auth localhost est sur (cf
    # plus bas). Initialisee par RestApiServer.start() depuis self._host.
    bind_host: str = "127.0.0.1"

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("REST %s", format % args)

    # --- CORS / CSRF --------------------------------------------------------

    def _allowed_origin(self, origin: Optional[str]) -> Optional[str]:
        """Retourne l'Origin a refleter dans ACAO si elle est autorisee, sinon None.

        Autorise : localhost (127.0.0.1 / localhost / ::1, tout port et scheme),
        l'origine PROPRE du serveur (meme Host -> dashboard LAN auto-servi), ou
        la `cors_origin` explicitement configuree (non '*'). Toute autre origine
        (un site web externe) est refusee : ferme la lecture cross-site et, via
        `_is_forbidden_cross_site`, la CSRF possible par le bypass auth loopback.
        """
        o = (origin or "").strip()
        if not o or o.lower() == "null":
            return None
        try:
            host = (urlsplit(o).hostname or "").lower()
        except ValueError:
            return None
        if host in {"127.0.0.1", "localhost", "::1"}:
            return o
        # Same-origin : Origin == scheme://<Host> (cas du dashboard servi en LAN
        # depuis 0.0.0.0 ou l'utilisateur ouvre http://<ip-lan>:8642).
        own_host = (self.headers.get("Host") or "").strip().lower()
        if own_host and o.split("://", 1)[-1].lower() == own_host:
            return o
        cfg = (self.cors_origin or "").strip()
        if cfg and cfg != "*" and o == cfg:
            return o
        return None

    def _is_forbidden_cross_site(self) -> bool:
        """Garde CSRF : True si la requete vient d'un navigateur sur une origine
        non autorisee. Un navigateur envoie TOUJOURS `Origin` sur une requete
        cross-origin (et sur les POST same-origin) ; un client non-navigateur
        (curl, cron, code natif) n'en envoie pas. Sans ce garde, n'importe quel
        site visite par l'utilisateur peut POSTer sur l'API locale et le bypass
        auth loopback l'autoriserait (AUDIT 2026-06-10, REAL 2/2)."""
        origin = self.headers.get("Origin")
        if not origin:
            return False
        return self._allowed_origin(origin) is None

    def _send_cors_headers(self) -> None:
        # On ne renvoie JAMAIS ACAO:* par defaut (lecture cross-site / CSRF).
        # On reflete uniquement une origine autorisee (localhost / same-origin /
        # cors_origin configuree). Cf issue #69 : Vary: Origin obligatoire quand
        # on echo une origine specifique (cache HTTP correcte browser/proxy).
        allowed = self._allowed_origin(self.headers.get("Origin"))
        if allowed is not None:
            self.send_header("Access-Control-Allow-Origin", allowed)
            self.send_header("Vary", "Origin")
        elif self.cors_origin and self.cors_origin != "*":
            # Origine LAN explicitement configuree : comportement existant conserve.
            self.send_header("Access-Control-Allow-Origin", self.cors_origin)
            self.send_header("Vary", "Origin")
        # Sinon : aucune ACAO emise. Les requetes same-origin (sans Origin) n'en
        # ont pas besoin ; les requetes cross-site ne peuvent pas lire la reponse.
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        # NB : pas de "Access-Control-Allow-Credentials: true" — l'auth Bearer
        # passe par header Authorization, pas par cookie.

    def do_OPTIONS(self) -> None:
        # V3-04 polish v7.7.0 : positionner aussi un request_id pour les
        # preflight CORS, au cas ou un debug logger se reveille.
        token = set_request_id(uuid.uuid4().hex[:8])
        try:
            self.send_response(204)
            self._send_cors_headers()
            self._send_request_id_header()
            self.end_headers()
        finally:
            clear_request_id()
            del token

    # --- Auth ---------------------------------------------------------------

    def _check_auth(self) -> bool:
        # 2026-06-08 — BYPASS LOCALHOST DESKTOP TRUSTED
        # Cause racine : 4 hotfixes successifs (_mask_secrets, _safeBearer,
        # utf-8-sig, native_boot) n'ont pas fait disparaitre les 401 silencieux
        # en local. Tant que le token transitant par PowerShell/JS storage subit
        # une mutation invisible (BOM U+FEFF, percent-decode, normalisation
        # unicode), l'auth Bearer echoue de facon non-reproductible.
        # Approche radicale : en mode desktop pywebview (bind 127.0.0.1), le
        # process REST tourne dans le meme contexte utilisateur que le client.
        # Un attaquant local a deja le shell — l'auth Bearer ne protege rien.
        # On bypass donc l'auth quand TOUS les criteres sont reunis :
        #   1. client_ip ∈ _LOCAL_CLIENT_IPS (loopback v4/v6)
        #   2. bind_host == "127.0.0.1" (PAS 0.0.0.0 / expose LAN)
        #   3. feature flag CINESORT_DISABLE_LOCAL_AUTH != "1" (kill-switch)
        # Le bypass est volontairement DESACTIVE quand bind 0.0.0.0 : on ne
        # peut pas distinguer un client LAN qui spoof 127.0.0.1 dans son
        # interface vs un vrai loopback. Securite critique.
        client_ip = self.client_address[0] if self.client_address else ""
        bypass_disabled = os.environ.get("CINESORT_DISABLE_LOCAL_AUTH", "0").strip() == "1"
        if (
            not bypass_disabled
            and client_ip in _LOCAL_CLIENT_IPS
            and self.bind_host == "127.0.0.1"
        ):
            logger.info(
                "Auth bypass localhost (client=%s, bind=%s) — desktop trusted mode",
                client_ip,
                self.bind_host,
            )
            return True
        if not self.auth_token:
            return False
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            # DEBUG VERBOSE 2026-06-08 : signaler header manquant/malforme.
            if os.environ.get("CINESORT_DEBUG", "").strip().lower() in {"1", "true", "yes", "on", "debug"}:
                logger.warning(
                    "[DEBUG-AUTH] header Authorization absent ou non-Bearer: %r",
                    auth[:40] if auth else "<empty>",
                )
            return False
        bearer = auth[7:].strip()
        match = hmac.compare_digest(bearer.encode(), self.auth_token.encode())
        # DEBUG VERBOSE 2026-06-08 : si mismatch, dump codepoints des deux cotes
        # pour identifier la divergence exacte (BOM, trailing whitespace, etc.).
        if not match and os.environ.get("CINESORT_DEBUG", "").strip().lower() in {"1", "true", "yes", "on", "debug"}:
            try:
                bearer_cps = [f"U+{ord(c):04X}" for c in bearer]
                token_cps = [f"U+{ord(c):04X}" for c in self.auth_token]
                bearer_non_ascii = [(i, ord(c)) for i, c in enumerate(bearer) if ord(c) > 0x7F]
                token_non_ascii = [(i, ord(c)) for i, c in enumerate(self.auth_token) if ord(c) > 0x7F]
                logger.warning(
                    "[DEBUG-AUTH] MISMATCH bearer_len=%d token_len=%d",
                    len(bearer),
                    len(self.auth_token),
                )
                logger.warning("[DEBUG-AUTH] bearer codepoints=%s", bearer_cps)
                logger.warning("[DEBUG-AUTH] server token codepoints=%s", token_cps)
                if bearer_non_ascii:
                    logger.warning("[DEBUG-AUTH] bearer NON-ASCII pos+cp=%s", bearer_non_ascii)
                if token_non_ascii:
                    logger.warning("[DEBUG-AUTH] server token NON-ASCII pos+cp=%s", token_non_ascii)
                # Comparaison char-par-char pour pointer la 1ere divergence
                for i in range(max(len(bearer), len(self.auth_token))):
                    b = bearer[i] if i < len(bearer) else None
                    t = self.auth_token[i] if i < len(self.auth_token) else None
                    if b != t:
                        bo = f"U+{ord(b):04X}" if b is not None else "<EOS>"
                        to_ = f"U+{ord(t):04X}" if t is not None else "<EOS>"
                        logger.warning(
                            "[DEBUG-AUTH] 1ere divergence pos=%d bearer=%s server=%s", i, bo, to_,
                        )
                        break
            except Exception as _dbg_exc:  # noqa: BLE001 — debug only
                logger.warning("[DEBUG-AUTH] dump failed: %s", _dbg_exc)
        return match

    def _has_bearer_header(self) -> bool:
        """True si la requete porte un header Authorization Bearer non-vide.

        FIX 2026-06-07 (faux 429 TMDb test) : on doit distinguer deux cas d'echec
        d'auth qui produisent tous deux un 401 cote handler legacy :

        1. Token ABSENT/MALFORME (header omis par _safeBearer cote front quand le
           token storage contient un codepoint non-ASCII type BOM U+FEFF). C'est
           un bug client/config, pas une tentative d'attaque -> on NE doit PAS
           incrementer le compteur du rate-limiter, sinon les 5 pings parallels
           de l'Accueil saturent immediatement le seuil (5/60s) et le 1er click
           "Tester" sur Parametres tombe en 429 "Trop de tentatives" avant meme
           de toucher la logique auth/TMDb. L'utilisateur croit avoir fait 1
           requete, en realite 5 401 silencieux ont deja epuise le quota.

        2. Token PRESENT mais FAUX : vrai vecteur d'attaque -> on garde le
           comptage record_failure() comme avant.
        """
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return bool(auth[7:].strip())

    def _client_ip(self) -> str:
        """Retourne l'adresse IP du client (premier element du tuple)."""
        return self.client_address[0] if self.client_address else "unknown"

    def _is_rate_limited(self) -> bool:
        """Verifie si l'IP du client est bloquee par le rate limiter.

        FIX DEFINITIF 2026-06-07 (saturation 5/60s par 401 silents en local) :
        on exempte TOTALEMENT les IPs locales (_LOCAL_CLIENT_IPS). Cause racine
        documentee : quand le storage frontend contient un codepoint non-ASCII
        (BOM U+FEFF injecte via PowerShell ?ntoken=..., ou URL-decode incorrect),
        _safeBearer() omet silencieusement le header Authorization. Les 5 pings
        parallels de l'Accueil saturent alors le compteur per-IP (5/60s) en moins
        d'une seconde, et chaque action utilisateur suivante tombe en 429
        "Trop de tentatives" avant meme d'atteindre la logique auth.
        En contexte desktop pywebview (bind 127.0.0.1 par defaut), il n'y a
        AUCUNE surface d'attaque a proteger via rate-limit : un attaquant local
        a deja le shell. Le rate-limit reste pleinement actif pour les IPs
        distantes (supervision LAN, dashboard distant).
        """
        client_ip = self._client_ip()
        if client_ip in _LOCAL_CLIENT_IPS:
            return False
        if self.rate_limiter and self.rate_limiter.is_blocked(client_ip):
            # ITER14 RATE_LIMIT_429_FACADE : Retry-After indique au client le delai
            # avant retry (RFC 7231 §7.1.3). Valeur = window_s (60s par defaut)
            # = duree maximale residuelle avant que le compteur per-IP se vide.
            # Seuil 5 echecs / 60s INCHANGE (cf _RATE_LIMIT_MAX_FAILURES / _RATE_LIMIT_WINDOW_S).
            retry_after = str(int(self.rate_limiter._window))
            self._respond_json(
                429,
                {"ok": False, "message": "Trop de tentatives. Reessayez dans 60 secondes."},
                extra_headers={"Retry-After": retry_after},
            )
            return True
        return False

    def _send_unauthorized(self) -> None:
        # FIX 2026-06-07 (faux 429 TMDb test) : on ne comptabilise pas les 401
        # causes par un header Authorization manquant/malforme (token absent ou
        # vide). Voir _has_bearer_header() pour la justification detaillee.
        # Backward compat : un vrai mauvais token continue d'incrementer le
        # compteur (comportement antérieur preserve pour les attaquants reels).
        #
        # FIX DEFINITIF 2026-06-07 (suite) : meme reflexion que _is_rate_limited
        # — on n'enregistre AUCUN echec pour les IPs locales, sinon le compteur
        # pourrait encore servir a calculer is_blocked sur un autre handler si
        # un futur refactor oublie l'exemption a l'entree. Defense en profondeur.
        client_ip = self._client_ip()
        if (
            self.rate_limiter
            and self._has_bearer_header()
            and client_ip not in _LOCAL_CLIENT_IPS
        ):
            self.rate_limiter.record_failure(client_ip)
        self._respond_json(401, {"ok": False, "message": "Cle d'acces invalide ou manquante."})

    # --- Response helpers ---------------------------------------------------

    def _send_request_id_header(self) -> None:
        """V3-04 polish v7.7.0 — emet l'en-tete X-Request-ID.

        Permet au client de correler sa requete avec les logs serveur. Si le
        ContextVar est vide (cas anormal : appel direct de _respond_json hors
        do_GET/do_POST), on emet quand meme un id genere a la volee pour ne
        jamais omettre le header.
        """
        rid = get_request_id() or uuid.uuid4().hex[:8]
        with contextlib.suppress(AttributeError, OSError):
            self.send_header("X-Request-ID", rid)

    def _respond_json(self, status: int, data: Any, extra_headers: Optional[Dict[str, str]] = None) -> None:
        try:
            body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        except (TypeError, ValueError) as exc:
            body = json.dumps({"ok": False, "message": f"Erreur de serialisation: {exc}"}).encode("utf-8")
            status = 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        # V3-04 : header X-Request-ID systematique sur les reponses JSON
        # (succes ET erreurs 4xx/5xx).
        self._send_request_id_header()
        # ITER14 RATE_LIMIT_429_FACADE : extra headers optionnels (ex: Retry-After
        # sur les 429). Backward compat : extra_headers=None ne change rien.
        if extra_headers:
            for hname, hvalue in extra_headers.items():
                self.send_header(hname, hvalue)
        self.end_headers()
        self.wfile.write(body)

    # --- Dashboard static files ---------------------------------------------

    def _guess_mime(self, filepath: str) -> str:
        """Determine le type MIME d'un fichier statique."""
        ext = os.path.splitext(filepath)[1].lower()
        if ext in _EXTRA_MIME:
            return _EXTRA_MIME[ext]
        guessed, _ = mimetypes.guess_type(filepath)
        return guessed or "application/octet-stream"

    def _resolve_static_path(self, url_path: str, prefix: str, root, default_relative: str = "") -> Any:
        """Helper #174 : resolution + path-traversal pour les statics.

        Retourne le `Path` resolu si OK, ou `None` apres avoir deja repondu
        (404 root absente, 400 chemin invalide, 403 traversal, 404 file).
        Le caller peut donc faire `resolved = self._resolve_static_path(...)`
        puis `if resolved is None: return`.

        Mutualise les 4 verifications dupliquees entre les 4 handlers
        `_serve_*_file` (cf audit-bot 2026-05-16 issue #174).
        """
        if root is None or not root.is_dir():
            label = prefix.strip("/") or "static"
            self._respond_json(404, {"ok": False, "message": f"{label.capitalize()} non disponible."})
            return None

        relative = url_path[len(prefix) :]
        if (not relative or relative == "/") and default_relative:
            relative = default_relative
        relative = relative.lstrip("/")
        if not relative:
            self._respond_json(404, {"ok": False, "message": "Fichier introuvable."})
            return None

        try:
            resolved = (root / relative).resolve()
        except (OSError, ValueError):
            self._respond_json(400, {"ok": False, "message": "Chemin invalide."})
            return None

        try:
            resolved.relative_to(root)
        except ValueError:
            self._respond_json(403, {"ok": False, "message": "Acces interdit."})
            return None

        if not resolved.is_file():
            # S7 : reponse generique — ne pas refleter l'entree utilisateur dans les 404.
            # CodeQL py/log-injection : sanitize newlines/control chars du path
            # utilisateur avant log (sinon possibilite forger lignes de log fakes).
            safe_relative = str(relative).replace("\r", "").replace("\n", "")[:200]
            logger.debug("Static miss (%s): %s", prefix, safe_relative)
            self._respond_json(404, {"ok": False, "message": "Fichier introuvable."})
            return None

        return resolved

    def _read_static_bytes(self, resolved, scope: str) -> Any:
        """Helper #174 : lit le fichier resolu, gere les erreurs IO uniformement."""
        try:
            return resolved.read_bytes()
        except (OSError, PermissionError) as exc:
            logger.warning("%s static read error: %s", scope, exc)
            self._respond_json(500, {"ok": False, "message": "Erreur de lecture."})
            return None

    def _serve_dashboard_file(self, url_path: str) -> None:
        """Sert un fichier statique depuis web/dashboard/ avec garde anti path-traversal."""
        resolved = self._resolve_static_path(
            url_path, _DASHBOARD_PREFIX, self.dashboard_root, default_relative="/index.html"
        )
        if resolved is None:
            return
        content = self._read_static_bytes(resolved, "Dashboard")
        if content is None:
            return

        mime = self._guess_mime(str(resolved))
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        # F2 : Content-Security-Policy sur les reponses HTML du dashboard pour mitiger
        # tout innerHTML non echappe. Les API /api/* continuent d'emettre du JSON pur.
        #
        # V2-08 (4 mai 2026, polish v7.7.0) — finding H17 :
        # `style-src 'unsafe-inline'` est conserve a dessein. Le frontend CineSort
        # utilise des attributs `style="..."` inline statiques (web/dashboard/* +
        # processing.js + film-detail.js residuels) plus des mutations `.style.`
        # programmatiques. Migrer vers
        # nonce/hash demanderait un refactor massif (rendu serveur des nonces +
        # remplacement de tous les style inline par des classes CSS) avec un
        # risque de regression visuelle eleve, totalement disproportionne pour la
        # Vague 2 (UX/A11y polish, pas refactor frontend).
        # Mitigation actuelle : XSS hardening (V2-02) escape systematique de toute
        # entree utilisateur dans innerHTML via escapeHtml(). Le risque XSS via
        # `style=` reste donc theorique tant que cet invariant tient.
        # Header Content-Security-Policy-Report-Only ajoute en parallele avec la
        # version stricte (sans 'unsafe-inline') pour observation. Reporte a
        # Vague 3+ : refactor styles inline -> classes CSS utilitaires, puis
        # bascule sur la version stricte.
        if mime.startswith("text/html"):
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'",
            )
            # V2-08 : CSP stricte en mode Report-Only pour mesurer le volume
            # reel de violations avant migration future. Aucun blocage. Pas
            # de report-uri pour l'instant (collecter via DevTools console).
            self.send_header(
                "Content-Security-Policy-Report-Only",
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self'; "
                "font-src 'self'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
        self._send_cors_headers()
        # V3-04 : header X-Request-ID aussi sur les statics
        self._send_request_id_header()
        self.end_headers()
        self.wfile.write(content)

    def _serve_shared_file(self, url_path: str) -> None:
        """Sert un fichier statique depuis web/shared/ (design system v5).

        Vague 0 v7.6.0 : permet au dashboard distant de partager les CSS
        `tokens.css`, `themes.css`, `animations.css`, `components.css`,
        `utilities.css` avec le desktop. Meme garde anti path-traversal que
        _serve_dashboard_file.
        """
        resolved = self._resolve_static_path(url_path, _SHARED_PREFIX, getattr(self, "shared_root", None))
        if resolved is None:
            return
        content = self._read_static_bytes(resolved, "Shared")
        if content is None:
            return

        mime = self._guess_mime(str(resolved))
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self._send_cors_headers()
        self._send_request_id_header()
        self.end_headers()
        self.wfile.write(content)

    def _serve_locale_file(self, url_path: str) -> None:
        """Sert un fichier de traduction depuis `locales/<locale>.json`.

        V6-01 Polish Total v7.7.0 (R4-I18N-4) : alimente `web/dashboard/core/i18n.js`.
        Garde anti path-traversal symetrique aux autres `_serve_*_file`.
        Cache-Control 5 min (les locales bougent rarement, mais on autorise un
        rechargement raisonnable apres edition manuelle des JSON).
        """
        resolved = self._resolve_static_path(url_path, _LOCALES_PREFIX, getattr(self, "locales_root", None))
        if resolved is None:
            return
        content = self._read_static_bytes(resolved, "Locales")
        if content is None:
            return

        # Force application/json (les fichiers .json sont les seuls servis ici,
        # mais on ne se fie pas a l'extension cote MIME pour eviter les surprises
        # si un fichier non-JSON traine dans le dossier).
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        # Cache-Control modere : 5 min suffisent. Apres edition manuelle d'un
        # JSON, l'utilisateur peut hard-refresh ou attendre 5 min.
        self.send_header("Cache-Control", "public, max-age=300")
        self._send_cors_headers()
        self._send_request_id_header()
        self.end_headers()
        self.wfile.write(content)

    # --- Request lifecycle (V3-04 polish v7.7.0) ----------------------------

    def _new_request_id(self) -> str:
        """Genere un request_id court (8 hex chars). Format compact pour les logs."""
        return uuid.uuid4().hex[:8]

    # --- GET ----------------------------------------------------------------

    def do_GET(self) -> None:
        # V3-04 polish v7.7.0 (R4-LOG-2) : positionner request_id dans
        # ContextVar pour enrichir tous les logs emis pendant cette requete.
        token = set_request_id(self._new_request_id())
        # Cf issues #72 + #73 : flag is_remote_request si l'IP n'est pas locale.
        remote_token = set_remote_request(self._client_ip() not in _LOCAL_CLIENT_IPS)
        try:
            self._handle_get()
        finally:
            reset_remote_request(remote_token)
            clear_request_id()
            del token  # explicit (le clear suffit, mais lisible)

    def _handle_get(self) -> None:
        _t0 = time.monotonic()
        path = self.path.split("?")[0]
        clean = path.rstrip("/")

        # Health enrichi avec active_run_id
        if clean == "/api/health":
            version = getattr(self.api, "_app_version", "?")
            active_run_id = _find_active_run_id(self.api)
            last_event_ts = getattr(self.api, "_last_event_ts", None)
            payload: Dict[str, Any] = {"ok": True, "version": version, "ts": time.time()}
            if last_event_ts is not None:
                payload["last_event_ts"] = last_event_ts
            last_settings_ts = getattr(self.api, "_last_settings_ts", None)
            if last_settings_ts is not None:
                payload["last_settings_ts"] = last_settings_ts
            if active_run_id:
                payload["active_run_id"] = active_run_id
            self._respond_json(200, payload)
            return

        if clean == "/api/spec":
            self._respond_json(200, self.openapi_spec)
            return

        # Iter12 / ETAPE 1b : proxy poster TMDb avec validation stricte
        # anti-SSRF/anti-open-relay + cache disque local.
        # Cf cinesort/infra/integrations/poster_proxy.py (whitelist sizes,
        # regex id, scrub cle API). Pas d'auth Bearer requise sur cette
        # route : sert directement <img src="/api/poster?id=...&size=..."> et
        # le bypass loopback du _check_auth de cette classe couvre deja le
        # cas pywebview natif. Note : on n'invoque PAS self._check_auth ici
        # car le navigateur ne peut pas mettre d'header Authorization sur
        # un <img>, et qu'en bind 127.0.0.1 (defaut desktop) le bypass
        # serait de toute facon active.
        if clean == "/api/poster":
            from urllib.parse import parse_qs  # noqa: PLC0415

            from cinesort.infra.integrations import poster_proxy  # noqa: PLC0415
            from cinesort.infra.state import default_state_dir  # noqa: PLC0415
            # Resoudre state_dir : preferer l'API si disponible, sinon
            # default_state_dir() (compat tests sans API monte).
            api = getattr(self, "api", None)
            state_dir = None
            if api is not None:
                get_state = getattr(api, "_get_state_dir", None)
                if callable(get_state):
                    try:
                        state_dir = get_state()
                    except Exception:  # noqa: BLE001 — boundary
                        state_dir = None
            if state_dir is None:
                state_dir = default_state_dir()
            cache_root = Path(state_dir) / "cache" / "posters"
            # Parser la query string (premier raw seulement, jamais liste).
            raw_query = self.path.split("?", 1)[1] if "?" in self.path else ""
            parsed = parse_qs(raw_query, keep_blank_values=True)
            flat_query: Dict[str, str] = {}
            for key, values in parsed.items():
                if values:
                    flat_query[key] = values[0]
            try:
                poster_proxy.serve_poster(self, Path(state_dir), cache_root, flat_query)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError) as exc:
                logger.debug(
                    "REST GET /api/poster client disconnect (%s, %.0fms)",
                    type(exc).__name__,
                    (time.monotonic() - _t0) * 1000,
                )
            except Exception as exc:  # noqa: BLE001 — boundary
                logger.exception("REST 500 /api/poster: %s", exc)
                with contextlib.suppress(ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    self._respond_json(500, {"ok": False, "category": "runtime", "message": "Erreur interne"})
            return

        # Fichiers statiques du dashboard distant
        # FIX bug CSS 2026-06-05 : "/dashboard" (sans slash final) doit rediriger
        # vers "/dashboard/" (avec slash) pour que le navigateur resolve correctement
        # les chemins relatifs des assets dans index.html (./styles.css, ./app.js, etc.).
        # Sans cette redirection, ./styles.css est resolu en /styles.css (au lieu de
        # /dashboard/styles.css) car la base URL "/dashboard" n'a pas de segment final,
        # donc le navigateur retombe sur la racine "/" et tous les assets renvoient 404
        # (page HTML brute sans CSS).
        # On compare sur `path` (et non `clean`) car `clean = path.rstrip("/")`
        # supprimerait le slash final qui distingue justement les 2 cas.
        if path == _DASHBOARD_PREFIX:
            # Preserver la query string eventuelle
            query = ""
            if "?" in self.path:
                query = "?" + self.path.split("?", 1)[1]
            self.send_response(301)
            self.send_header("Location", _DASHBOARD_PREFIX + "/" + query)
            self.send_header("Content-Length", "0")
            self._send_cors_headers()
            self._send_request_id_header()
            self.end_headers()
            return
        if path == _DASHBOARD_PREFIX + "/" or path.startswith(_DASHBOARD_PREFIX + "/"):
            self._serve_dashboard_file(path.split("?")[0])
            return

        # v7.6.0 Vague 0 : design system v5 partage (web/shared/) pour le dashboard distant
        if clean == _SHARED_PREFIX or path.startswith(_SHARED_PREFIX + "/"):
            self._serve_shared_file(path.split("?")[0])
            return

        # V6-01 Polish Total v7.7.0 : fichiers de traduction (locales/<locale>.json)
        if clean == _LOCALES_PREFIX or path.startswith(_LOCALES_PREFIX + "/"):
            self._serve_locale_file(path.split("?")[0])
            return

        # M9 : ne pas refleter le path dans la reponse (eviter les reflexions d'entree)
        self._respond_json(404, {"ok": False, "message": "Endpoint inconnu"})
        logger.debug("REST GET %s -> 404 (%.0fms)", path, (time.monotonic() - _t0) * 1000)

    # --- POST ---------------------------------------------------------------

    def do_POST(self) -> None:
        # V3-04 polish v7.7.0 (R4-LOG-2) : meme principe que do_GET.
        token = set_request_id(self._new_request_id())
        # Cf issues #72 + #73 : flag is_remote_request si l'IP n'est pas locale.
        remote_token = set_remote_request(self._client_ip() not in _LOCAL_CLIENT_IPS)
        try:
            self._handle_post()
        finally:
            reset_remote_request(remote_token)
            clear_request_id()
            del token

    def _handle_post(self) -> None:
        _t0 = time.monotonic()
        path = self.path.split("?")[0].rstrip("/")

        if not path.startswith("/api/"):
            # M9 : ne pas refleter le path dans la reponse
            self._respond_json(404, {"ok": False, "message": "Endpoint inconnu"})
            return

        # Garde CSRF : rejette les POST cross-site venant d'un navigateur AVANT
        # toute action. Indispensable car le bypass auth loopback autoriserait
        # sinon une page malveillante a piloter l'API locale (start_plan/apply).
        if self._is_forbidden_cross_site():
            logger.warning("REST 403 cross-site POST from origin=%r", self.headers.get("Origin"))
            self._respond_json(403, {"ok": False, "message": "Origine non autorisee"})
            return

        # Rate limiting : bloquer avant meme de verifier le token
        if self._is_rate_limited():
            logger.warning("REST 429 rate limit %s", self._client_ip())
            return

        if not self._check_auth():
            logger.warning("REST auth failure from %s for %s", self._client_ip(), path)
            self._send_unauthorized()
            return
        # B05-401-INCOHERENT (Fix B / S6 audit) : auth ok -> reset compteur
        # d'echecs pour cette IP. Sans cet appel, un client qui a fait 4 echecs
        # recents reste au bord du plafond meme apres avoir trouve le bon token
        # et peut s'auto-ban au moindre hickup reseau ulterieur. Le commentaire
        # de record_success() decrivait deja l'intention, mais le hookup
        # manquait.
        if self.rate_limiter:
            self.rate_limiter.record_success(self._client_ip())

        method_name = path[5:]  # strip "/api/"
        method = self.api_methods.get(method_name)
        if not method:
            # P0 #233 (finalise 2026-05 : Pass 1 desactivee par defaut) :
            # appel legacy direct (pas de "/" dans method_name = pas de prefixe
            # facade) renvoie 410 Gone avec message guidant vers le nouveau
            # format /api/<facade>/<method>.
            if (
                _legacy_pass1_disabled()
                and method_name
                and _FACADE_SEPARATOR not in method_name
                and method_name.split(_FACADE_SEPARATOR, 1)[0] not in _FACADE_ATTR_NAMES
            ):
                self._respond_json(
                    410,
                    {
                        "ok": False,
                        "message": "Use /api/<facade>/<method> instead",
                    },
                )
                # CodeQL py/log-injection : method_name vient de l'URL HTTP.
                # repr() escape automatiquement \n, \r et caracteres de controle
                # qui pourraient forger de fausses entrees de log.
                logger.warning("REST POST legacy method 410 Gone: %r", method_name)
                return
            # M9 : ne pas refleter method_name dans la reponse
            self._respond_json(404, {"ok": False, "message": "Methode inconnue"})
            logger.warning("REST POST method inconnue: %r", method_name)
            return

        # Parse body
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            self._respond_json(400, {"ok": False, "message": "En-tete Content-Length invalide."})
            return
        if content_length < 0 or content_length > _MAX_BODY_SIZE:
            self._respond_json(413, {"ok": False, "message": "Corps de requete trop volumineux."})
            return

        params: Dict[str, Any] = {}
        if content_length > 0:
            raw = self.rfile.read(content_length)
            try:
                parsed = json.loads(raw.decode("utf-8"))
                if isinstance(parsed, dict):
                    params = parsed
                else:
                    self._respond_json(400, {"ok": False, "message": "Le corps doit etre un objet JSON."})
                    return
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._respond_json(400, {"ok": False, "message": f"JSON invalide: {exc}"})
                return

        # Dispatch
        try:
            result = method(**params)
            # Phase 11 v7.8.0 : convention opt-in `http_status` permettant aux
            # handlers de signaler un code HTTP metier (404/403/409/...) sans
            # casser les clients existants qui lisent `data.ok`. Si le champ
            # n'est pas fourni, le defaut reste 200 (backwards compat totale).
            # Le champ est retire avant serialisation pour ne pas polluer le
            # payload retourne.
            status = 200
            if isinstance(result, dict) and "http_status" in result:
                try:
                    candidate = int(result.pop("http_status"))
                    if 200 <= candidate < 600:
                        status = candidate
                except (TypeError, ValueError):
                    pass
            self._respond_json(status, result)
            logger.info("REST POST /api/%s -> %d (%.0fms)", method_name, status, (time.monotonic() - _t0) * 1000)
        except TypeError as exc:
            self._respond_json(400, {"ok": False, "message": f"Parametres invalides: {exc}"})
            logger.warning(
                "REST POST /api/%s -> 400 params invalides (%.0fms)", method_name, (time.monotonic() - _t0) * 1000
            )
        # Fix audit 2026-05-24 : ConnectionAbortedError/ConnectionResetError
        # arrivent quand le client (WebView2) ferme la socket avant que le
        # serveur ait fini d'ecrire la reponse (ex: utilisateur navigue vers
        # une autre vue pendant qu'un get_library_filtered tourne). C'est un
        # comportement client legitime, pas un bug serveur -> log debug, pas
        # ERROR avec traceback complet inutile.
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError) as exc:
            logger.debug(
                "REST POST /api/%s : client disconnect avant fin reponse (%s, %.0fms)",
                method_name,
                type(exc).__name__,
                (time.monotonic() - _t0) * 1000,
            )
        # except Exception intentionnel : boundary top-level
        except Exception as exc:
            # M8 : ne pas exposer le message d'exception au client (peut contenir des chemins, SQL, etc.)
            logger.exception("REST 500 method=%s (%.0fms): %s", method_name, (time.monotonic() - _t0) * 1000, exc)
            # Client deja parti -> on ne peut plus repondre, on ignore.
            with contextlib.suppress(ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                self._respond_json(500, {"ok": False, "message": "Erreur interne"})


def _find_active_run_id(api: Any) -> Optional[str]:
    """Trouve le run_id du run actuellement en cours (running et pas done)."""
    runs = getattr(api, "_runs", None)
    runs_lock = getattr(api, "_runs_lock", None)
    if not runs or not runs_lock:
        return None
    with runs_lock:
        for run_id, rs in runs.items():
            if getattr(rs, "running", False) and not getattr(rs, "done", False):
                return run_id
    return None


class RestApiServer:
    """REST API server wrapping CineSortApi."""

    # H-4 audit QA 20260428 : longueur minimale du token requise pour autoriser
    # un bind sur 0.0.0.0 (exposition LAN). En-dessous, le serveur retombe en
    # localhost-only avec un warning visible.
    MIN_LAN_TOKEN_LENGTH = 32

    def __init__(
        self,
        api: Any,
        *,
        port: int = 8642,
        token: str = "",
        cors_origin: str = "",
        https_enabled: bool = False,
        cert_path: str = "",
        key_path: str = "",
        host: str = "127.0.0.1",
    ) -> None:
        self._api = api
        self._port = int(port)
        self._token = str(token or "")
        # BUG 2 : le dashboard distant est concu pour le reseau local (LAN). L'acces
        # depuis 192.168.x.x:port doit fonctionner. Le default "*" permet cet acces.
        # L'auth Bearer token reste la barriere principale. Pour restreindre, l'utilisateur
        # peut definir rest_api_cors_origin dans les settings (ex: "http://192.168.1.50:8642").
        self._cors_origin = str(cors_origin or "").strip() or "*"
        self._https_enabled = bool(https_enabled)
        self._cert_path = str(cert_path or "").strip()
        self._key_path = str(key_path or "").strip()
        # host="127.0.0.1" (DEFAUT) limite l'acces au localhost (desktop pywebview).
        # host="0.0.0.0" expose sur toutes les interfaces (acces LAN distant) — doit etre
        # choisi explicitement par l'appelant via rest_api_enabled=true en settings.
        # Securite : defaut restrictif pour eviter toute exposition non-voulue.
        requested_host = str(host or "127.0.0.1").strip() or "127.0.0.1"
        # H-4 : si exposition LAN demandee mais token trop court, on retrograde
        # silencieusement vers localhost AU MOMENT DE L'INSTANCIATION pour que
        # l'appelant puisse lire host_effective et lan_demoted avant start().
        self._host_requested = requested_host
        if requested_host == "0.0.0.0" and len(self._token) < self.MIN_LAN_TOKEN_LENGTH:
            self._host = "127.0.0.1"
            self._lan_demoted = True
            self._lan_demotion_reason = (
                f"Token REST trop court ({len(self._token)} caracteres) pour exposition LAN. "
                f"Minimum requis : {self.MIN_LAN_TOKEN_LENGTH}. "
                "Le serveur reste accessible uniquement depuis localhost."
            )
        else:
            self._host = requested_host
            self._lan_demoted = False
            self._lan_demotion_reason = ""
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._rate_limiter = _RateLimiter()
        # FIX DEFINITIF 2026-06-07 : log d'observabilite au boot pour distinguer
        # rapidement saturation (X/N) vs token absent vs autre cause.
        logger.info(
            "REST rate-limiter init: %d failures / %.0fs window (global cap %d), localhost exempted",
            self._rate_limiter._max,
            self._rate_limiter._window,
            self._rate_limiter._max_global,
        )
        self._is_https = False  # True si le serveur tourne effectivement en HTTPS
        self.dashboard_url: str = ""  # URL publique du dashboard, remplie au start()
        # B05-401-INCOHERENT (Fix A) : on garde une ref a la classe handler
        # creee dynamiquement dans start() pour pouvoir hot-swap le token
        # sans redemarrer le serveur. L'absence de cette ref etait la cause
        # racine de l'incoherence 401 apres save_settings.
        self._handler_cls: Optional[type] = None

    @property
    def host(self) -> str:
        """Adresse de bind effective (peut differer du host demande si lan_demoted)."""
        return self._host

    @property
    def host_requested(self) -> str:
        """Adresse de bind initialement demandee par l'appelant."""
        return self._host_requested

    @property
    def lan_demoted(self) -> bool:
        """True si le bind 0.0.0.0 a ete retrograde en 127.0.0.1 par securite (token court)."""
        return self._lan_demoted

    @property
    def lan_demotion_reason(self) -> str:
        """Message FR explicitant la retrogradation si lan_demoted == True."""
        return self._lan_demotion_reason

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the HTTP server in a daemon thread."""
        if self.is_running:
            logger.warning("REST server already running on port %d", self._port)
            return

        if not self._token:
            logger.warning("REST server token is empty — all requests will be rejected.")

        # H-4 audit QA 20260428 : signaler clairement les expositions reseau.
        if self._lan_demoted:
            logger.warning(
                "REST: %s",
                self._lan_demotion_reason,
            )
        elif self._host == "0.0.0.0":
            logger.warning(
                "REST: serveur expose sur 0.0.0.0:%d (acces LAN). "
                "Verifiez votre reseau de confiance et utilisez HTTPS pour l'exposition externe.",
                self._port,
            )

        methods = _get_api_methods(self._api)
        spec = generate_openapi_spec(self._api, port=self._port)
        dashboard_root = _resolve_dashboard_root()
        shared_root = _resolve_shared_root()
        locales_root = _resolve_locales_root()  # V6-01 i18n

        # Configure handler class attributes.
        handler = type(
            "Handler",
            (_CineSortHandler,),
            {
                "api": self._api,
                "api_methods": methods,
                "auth_token": self._token,
                "cors_origin": self._cors_origin,
                "openapi_spec": spec,
                "rate_limiter": self._rate_limiter,
                "dashboard_root": dashboard_root,
                "shared_root": shared_root,
                "locales_root": locales_root,
                # 2026-06-08 : expose le bind effectif au handler pour que
                # _check_auth puisse decider si le bypass localhost est sur
                # (uniquement vrai bind 127.0.0.1, pas 0.0.0.0 expose LAN).
                "bind_host": self._host,
            },
        )
        # B05-401-INCOHERENT (Fix A) : conserver la ref pour permettre la
        # mutation runtime du token via update_auth_token().
        self._handler_cls = handler

        self._server = ThreadingHTTPServer((self._host, self._port), handler)
        self._server.daemon_threads = True

        # --- HTTPS : wrapper le socket avec SSL si active et cert/key valides ---
        # M1 : si HTTPS demande mais invalide, on leve une erreur visible au lieu
        # de fallback silencieux en HTTP (faille de configuration silencieuse).
        self._is_https = False
        self._start_error: Optional[str] = None
        if self._https_enabled:
            cert_ok = self._cert_path and Path(self._cert_path).is_file()
            key_ok = self._key_path and Path(self._key_path).is_file()
            if not (cert_ok and key_ok):
                msg = (
                    f"HTTPS demande mais cert/key manquants (cert={self._cert_path}, key={self._key_path}). "
                    "Serveur REST non demarre."
                )
                logger.error("REST: %s", msg)
                self._start_error = msg
                with contextlib.suppress(OSError):
                    self._server.server_close()
                self._server = None
                raise RuntimeError(msg)
            try:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(certfile=self._cert_path, keyfile=self._key_path)
            except (ssl.SSLError, OSError, PermissionError) as exc:
                msg = f"HTTPS demande mais certificat invalide: {exc}. Serveur REST non demarre."
                logger.error("REST: %s", msg, exc_info=True)
                self._start_error = msg
                with contextlib.suppress(OSError):
                    self._server.server_close()
                self._server = None
                raise RuntimeError(msg) from exc
            self._server.socket = ctx.wrap_socket(self._server.socket, server_side=True)
            self._is_https = True
            logger.info("REST API HTTPS active (cert=%s)", self._cert_path)

        protocol = "https" if self._is_https else "http"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="cinesort-rest-api",
            daemon=True,
        )
        self._thread.start()
        logger.info("REST API started on %s://%s:%d (%d endpoints)", protocol, self._host, self._port, len(methods))

        # Detecter l'IP locale et construire l'URL du dashboard
        local_ip = get_local_ip()
        self.dashboard_url = build_dashboard_url(local_ip, self._port, self._is_https)
        logger.info("REST: dashboard accessible a %s", self.dashboard_url)

    def stop(self) -> None:
        """Stop the HTTP server.

        H10 (hotfix2) : l'ancien code faisait join(timeout=5) puis NULL la ref
        sans verifier is_alive(). Si le thread refusait de mourir (handler bloque,
        socket non liberee), on se retrouvait avec un thread daemon orphelin
        tournant a vide et une socket potentiellement encore ouverte, ce qui
        faisait echouer le bind au prochain start().

        Nouveau pattern :
        - boucle de courts join(0.5) tant que is_alive() et timeout restant
        - si is_alive() apres timeout : force-close de la socket sous-jacente
          pour debloquer serve_forever() et liberer le port
        - les refs ne sont nullifiees qu'apres best-effort de nettoyage
        """
        server = self._server
        thread = self._thread
        if server is not None:
            with contextlib.suppress(Exception):
                server.shutdown()
            with contextlib.suppress(OSError):
                server.server_close()
        if thread is not None:
            timeout_remaining = 5.0
            step = 0.5
            while thread.is_alive() and timeout_remaining > 0:
                thread.join(step)
                timeout_remaining -= step
            if thread.is_alive():
                # Le thread refuse de mourir : on force-close la socket
                # sous-jacente pour debloquer serve_forever() et eviter de
                # garder le port occupe (regression bind au restart).
                logger.warning(
                    "REST: thread %s toujours vivant apres timeout, "
                    "force-close de la socket pour liberer le port.",
                    thread.name,
                )
                if server is not None:
                    sock = getattr(server, "socket", None)
                    if sock is not None:
                        with contextlib.suppress(OSError):
                            sock.close()
                # Dernier essai bref de join apres force-close
                thread.join(timeout=1.0)
                if thread.is_alive():
                    logger.error(
                        "REST: thread %s orphelin (daemon=%s) — la socket "
                        "a ete fermee mais le thread n'a pas pu etre joint.",
                        thread.name,
                        thread.daemon,
                    )
        self._server = None
        self._thread = None
        # B05-401-INCOHERENT (Fix A) : on jette la ref handler pour eviter
        # tout hot-swap de token apres stop() (no-op silencieux sinon).
        self._handler_cls = None
        logger.info("REST API stopped.")

    def update_auth_token(self, new_token: str) -> None:
        """Hot-swap du token Bearer sans redemarrage du serveur.

        B05-401-INCOHERENT (Fix A) : avant ce patch, le token etait fige a la
        creation du serveur. Apres save_settings (rest_api_token), le fichier
        settings.json contenait le nouveau token mais le handler en memoire
        validait encore avec l'ancien -> tout nouveau client recoit 401.

        On mute ici l'attribut de classe `auth_token` sur la sous-classe
        Handler creee dans start() ET on reset les compteurs rate-limit :
        un changement volontaire de token ne doit pas heriter des bans
        accumules sous l'ancien token.

        No-op si le serveur n'est pas demarre (handler_cls est None).

        R2-LAN-TOKEN-BYPASS-HOT-SWAP : si le serveur ecoute reellement sur 0.0.0.0
        (exposition LAN), on REFUSE le hot-swap vers un token plus court que
        MIN_LAN_TOKEN_LENGTH. Sans cette garde, un utilisateur pourrait demarrer
        avec un token long (passant la validation __init__), puis sauvegarder un
        token court via les settings : le bind 0.0.0.0 resterait actif avec un
        token faible, contournant silencieusement la protection lan_demoted.
        L'utilisateur doit restart avec une config valide.
        """
        new_token = str(new_token or "")
        # Garde anti-bypass LAN : si on ecoute sur 0.0.0.0 et le nouveau token
        # est trop court, on refuse le swap (ne pas degrader la posture de
        # securite d'un serveur deja expose au LAN).
        # DPAPI-R6-02 : EXCEPTION kill-switch — un token vide ("") est une
        # invalidation volontaire (rotation post-compromission). L'invalidation
        # immediate est plus prioritaire que la garde anti-degradation : on
        # autorise toujours le hot-swap vers "" meme sur 0.0.0.0.
        if (
            new_token
            and self._host == "0.0.0.0"
            and len(new_token) < self.MIN_LAN_TOKEN_LENGTH
        ):
            logger.warning(
                "REST: hot-swap du token REFUSE — le serveur ecoute sur 0.0.0.0 "
                "(exposition LAN) et le nouveau token est trop court "
                "(%d caracteres, minimum %d). Token et bind inchanges. "
                "Pour appliquer ce token, redemarrez le serveur avec une "
                "configuration valide (token >= %d caracteres ou bind 127.0.0.1).",
                len(new_token),
                self.MIN_LAN_TOKEN_LENGTH,
                self.MIN_LAN_TOKEN_LENGTH,
            )
            return
        self._token = new_token
        if self._handler_cls is not None:
            self._handler_cls.auth_token = new_token
            # Reset compteurs : un changement de token volontaire ne doit
            # pas heriter des bans accumules sous l'ancien token.
            with contextlib.suppress(Exception):
                self._rate_limiter.reset()
            if not new_token:
                logger.warning(
                    "REST: token REST efface — auth desactivee (kill-switch)"
                )
            else:
                logger.info(
                    "REST: auth token hot-swapped (len=%d)", len(new_token)
                )

    def join(self) -> None:
        """Block until the server thread ends (standalone mode)."""
        if self._thread:
            self._thread.join()
