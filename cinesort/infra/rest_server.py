"""REST API server — exposes CineSortApi over HTTP.

Uses stdlib http.server only — zero external dependencies.
All endpoints: POST /api/{method_name} with JSON body.
Public endpoints: GET /api/health, GET /api/spec.
Static files: GET /dashboard/* (web dashboard distant).
"""

from __future__ import annotations

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

from cinesort.infra.log_context import (
    clear_request_id,
    reset_remote_request,
    set_remote_request,
    set_request_id,
)

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
# supervision web (web/dashboard/views/help.js, web/views/help.js) ecouait sur
# "Endpoint inconnu" car le dispatch REST refusait la methode.
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
_FACADE_ATTR_NAMES: tuple = ("run", "settings", "quality", "integrations", "library")

# Separateur dans l'URL pour distinguer facade et methode (ex: "run/start_plan").
_FACADE_SEPARATOR = "/"

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
# V5B-01 : vues v5 ESM (web/views/*.js) importees par le dashboard via "../views/...".
# Servi pour rendre /dashboard/?native=1 fonctionnel.
_VIEWS_PREFIX = "/views"
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


def _resolve_views_root() -> Path:
    """Localise web/views/ (vues v5 ESM portees, importees par le dashboard)."""
    base = Path(getattr(__import__("sys"), "_MEIPASS", ""))
    candidate = base / "web" / "views"
    if candidate.is_dir():
        return candidate.resolve()
    project_root = Path(__file__).resolve().parents[2]
    candidate = project_root / "web" / "views"
    if candidate.is_dir():
        return candidate.resolve()
    return (Path.cwd() / "web" / "views").resolve()


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

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("REST %s", format % args)

    # --- CORS ---------------------------------------------------------------

    def _send_cors_headers(self) -> None:
        # Cf issue #69 : Vary: Origin obligatoire quand on echo une origin
        # specifique (cache HTTP correcte cote browser/proxy). Pour le default
        # "*" on n'a pas besoin de Vary mais le mettre quand meme ne nuit pas
        # — il signale juste que la reponse depend de l'Origin (info honnete).
        self.send_header("Access-Control-Allow-Origin", self.cors_origin)
        if self.cors_origin != "*":
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        # NB : pas de "Access-Control-Allow-Credentials: true" — l'auth Bearer
        # passe par header Authorization, pas par cookie. Le combo "*" +
        # credentials est interdit par la spec CORS, on est conforme.

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
        if not self.auth_token:
            return False
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        import hmac

        return hmac.compare_digest(auth[7:].strip().encode(), self.auth_token.encode())

    def _client_ip(self) -> str:
        """Retourne l'adresse IP du client (premier element du tuple)."""
        return self.client_address[0] if self.client_address else "unknown"

    def _is_rate_limited(self) -> bool:
        """Verifie si l'IP du client est bloquee par le rate limiter."""
        if self.rate_limiter and self.rate_limiter.is_blocked(self._client_ip()):
            self._respond_json(429, {"ok": False, "message": "Trop de tentatives. Reessayez dans 60 secondes."})
            return True
        return False

    def _send_unauthorized(self) -> None:
        if self.rate_limiter:
            self.rate_limiter.record_failure(self._client_ip())
        self._respond_json(401, {"ok": False, "message": "Cle d'acces invalide ou manquante."})

    # --- Response helpers ---------------------------------------------------

    def _send_request_id_header(self) -> None:
        """V3-04 polish v7.7.0 — emet l'en-tete X-Request-ID.

        Permet au client de correler sa requete avec les logs serveur. Si le
        ContextVar est vide (cas anormal : appel direct de _respond_json hors
        do_GET/do_POST), on emet quand meme un id genere a la volee pour ne
        jamais omettre le header.
        """
        from cinesort.infra.log_context import get_request_id

        rid = get_request_id() or uuid.uuid4().hex[:8]
        with contextlib.suppress(AttributeError, OSError):
            self.send_header("X-Request-ID", rid)

    def _respond_json(self, status: int, data: Any) -> None:
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

    def _serve_dashboard_file(self, url_path: str) -> None:
        """Sert un fichier statique depuis web/dashboard/ avec garde anti path-traversal."""
        if self.dashboard_root is None or not self.dashboard_root.is_dir():
            self._respond_json(404, {"ok": False, "message": "Dashboard non disponible."})
            return

        # Normaliser le chemin demande (retirer le prefixe /dashboard)
        relative = url_path[len(_DASHBOARD_PREFIX) :]
        if not relative or relative == "/":
            relative = "/index.html"
        # Retirer le leading slash pour construire le chemin
        relative = relative.lstrip("/")

        # Resoudre et verifier que le chemin reste sous dashboard_root
        try:
            resolved = (self.dashboard_root / relative).resolve()
        except (OSError, ValueError):
            self._respond_json(400, {"ok": False, "message": "Chemin invalide."})
            return

        # Garde anti path-traversal : le chemin resolu doit etre un descendant de dashboard_root
        try:
            resolved.relative_to(self.dashboard_root)
        except ValueError:
            self._respond_json(403, {"ok": False, "message": "Acces interdit."})
            return

        if not resolved.is_file():
            # S7 : reponse generique — ne pas refleter l'entree utilisateur dans les 404.
            logger.debug("Dashboard static miss: %s", relative)
            self._respond_json(404, {"ok": False, "message": "Fichier introuvable."})
            return

        # Lire et servir le fichier
        try:
            content = resolved.read_bytes()
        except (OSError, PermissionError) as exc:
            logger.warning("Dashboard static read error: %s", exc)
            self._respond_json(500, {"ok": False, "message": "Erreur de lecture."})
            return

        mime = self._guess_mime(str(resolved))
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        # F2 : Content-Security-Policy sur les reponses HTML du dashboard pour mitiger
        # tout innerHTML non echappe. Les API /api/* continuent d'emettre du JSON pur.
        #
        # V2-08 (4 mai 2026, polish v7.7.0) — finding H17 :
        # `style-src 'unsafe-inline'` est conserve a dessein. Le frontend CineSort
        # utilise ~391 attributs `style="..."` inline statiques (web/dashboard/* +
        # web/views/*) plus ~81 mutations `.style.` programmatiques. Migrer vers
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
        shared_root = getattr(self, "shared_root", None)
        if shared_root is None or not shared_root.is_dir():
            self._respond_json(404, {"ok": False, "message": "Shared non disponible."})
            return

        relative = url_path[len(_SHARED_PREFIX) :].lstrip("/")
        if not relative:
            self._respond_json(404, {"ok": False, "message": "Fichier introuvable."})
            return

        try:
            resolved = (shared_root / relative).resolve()
        except (OSError, ValueError):
            self._respond_json(400, {"ok": False, "message": "Chemin invalide."})
            return

        try:
            resolved.relative_to(shared_root)
        except ValueError:
            self._respond_json(403, {"ok": False, "message": "Acces interdit."})
            return

        if not resolved.is_file():
            logger.debug("Shared static miss: %s", relative)
            self._respond_json(404, {"ok": False, "message": "Fichier introuvable."})
            return

        try:
            content = resolved.read_bytes()
        except (OSError, PermissionError) as exc:
            logger.warning("Shared static read error: %s", exc)
            self._respond_json(500, {"ok": False, "message": "Erreur de lecture."})
            return

        mime = self._guess_mime(str(resolved))
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self._send_cors_headers()
        self._send_request_id_header()
        self.end_headers()
        self.wfile.write(content)

    def _serve_views_file(self, url_path: str) -> None:
        """Sert un fichier statique depuis web/views/ (vues v5 ESM portees).

        V5B-01 : le dashboard /dashboard/app.js fait
            import { initHome } from "../views/home.js";
        ce qui resout en /views/home.js cote serveur. Meme garde anti
        path-traversal que _serve_shared_file.
        """
        views_root = getattr(self, "views_root", None)
        if views_root is None or not views_root.is_dir():
            self._respond_json(404, {"ok": False, "message": "Views non disponibles."})
            return

        relative = url_path[len(_VIEWS_PREFIX) :].lstrip("/")
        if not relative:
            self._respond_json(404, {"ok": False, "message": "Fichier introuvable."})
            return

        try:
            resolved = (views_root / relative).resolve()
        except (OSError, ValueError):
            self._respond_json(400, {"ok": False, "message": "Chemin invalide."})
            return

        try:
            resolved.relative_to(views_root)
        except ValueError:
            self._respond_json(403, {"ok": False, "message": "Acces interdit."})
            return

        if not resolved.is_file():
            logger.debug("Views static miss: %s", relative)
            self._respond_json(404, {"ok": False, "message": "Fichier introuvable."})
            return

        try:
            content = resolved.read_bytes()
        except (OSError, PermissionError) as exc:
            logger.warning("Views static read error: %s", exc)
            self._respond_json(500, {"ok": False, "message": "Erreur de lecture."})
            return

        mime = self._guess_mime(str(resolved))
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache, must-revalidate")
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
        locales_root = getattr(self, "locales_root", None)
        if locales_root is None or not locales_root.is_dir():
            self._respond_json(404, {"ok": False, "message": "Locales non disponibles."})
            return

        relative = url_path[len(_LOCALES_PREFIX) :].lstrip("/")
        if not relative:
            self._respond_json(404, {"ok": False, "message": "Fichier introuvable."})
            return

        try:
            resolved = (locales_root / relative).resolve()
        except (OSError, ValueError):
            self._respond_json(400, {"ok": False, "message": "Chemin invalide."})
            return

        try:
            resolved.relative_to(locales_root)
        except ValueError:
            self._respond_json(403, {"ok": False, "message": "Acces interdit."})
            return

        if not resolved.is_file():
            logger.debug("Locales static miss: %s", relative)
            self._respond_json(404, {"ok": False, "message": "Fichier introuvable."})
            return

        try:
            content = resolved.read_bytes()
        except (OSError, PermissionError) as exc:
            logger.warning("Locales static read error: %s", exc)
            self._respond_json(500, {"ok": False, "message": "Erreur de lecture."})
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

        # Fichiers statiques du dashboard distant
        if clean == _DASHBOARD_PREFIX or path.startswith(_DASHBOARD_PREFIX + "/"):
            self._serve_dashboard_file(path.split("?")[0])
            return

        # v7.6.0 Vague 0 : design system v5 partage (web/shared/) pour le dashboard distant
        if clean == _SHARED_PREFIX or path.startswith(_SHARED_PREFIX + "/"):
            self._serve_shared_file(path.split("?")[0])
            return

        # V5B-01 : vues v5 ESM (web/views/*.js) importees par le dashboard
        if clean == _VIEWS_PREFIX or path.startswith(_VIEWS_PREFIX + "/"):
            self._serve_views_file(path.split("?")[0])
            return

        # V6-01 Polish Total v7.7.0 : fichiers de traduction (locales/<locale>.json)
        if clean == _LOCALES_PREFIX or path.startswith(_LOCALES_PREFIX + "/"):
            self._serve_locale_file(path.split("?")[0])
            return

        # Fichiers partages web/ (themes.css charge via ../themes.css depuis le dashboard)
        if clean == "/themes.css" and self.dashboard_root:
            shared = self.dashboard_root.parent / "themes.css"
            if shared.is_file():
                try:
                    content = shared.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/css; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.send_header("Cache-Control", "no-cache, must-revalidate")
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except OSError:
                    pass

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

        # Rate limiting : bloquer avant meme de verifier le token
        if self._is_rate_limited():
            logger.warning("REST 429 rate limit %s", self._client_ip())
            return

        if not self._check_auth():
            logger.warning("REST auth failure from %s for %s", self._client_ip(), path)
            self._send_unauthorized()
            return

        method_name = path[5:]  # strip "/api/"
        method = self.api_methods.get(method_name)
        if not method:
            # M9 : ne pas refleter method_name dans la reponse
            self._respond_json(404, {"ok": False, "message": "Methode inconnue"})
            logger.warning("REST POST method inconnue: %s", method_name)
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
        # except Exception intentionnel : boundary top-level
        except Exception as exc:
            # M8 : ne pas exposer le message d'exception au client (peut contenir des chemins, SQL, etc.)
            logger.exception("REST 500 method=%s (%.0fms): %s", method_name, (time.monotonic() - _t0) * 1000, exc)
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
        self._is_https = False  # True si le serveur tourne effectivement en HTTPS
        self.dashboard_url: str = ""  # URL publique du dashboard, remplie au start()

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
        views_root = _resolve_views_root()
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
                "views_root": views_root,
                "locales_root": locales_root,
            },
        )

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
        from cinesort.infra.network_utils import build_dashboard_url, get_local_ip

        local_ip = get_local_ip()
        self.dashboard_url = build_dashboard_url(local_ip, self._port, self._is_https)
        logger.info("REST: dashboard accessible a %s", self.dashboard_url)

    def stop(self) -> None:
        """Stop the HTTP server."""
        if self._server:
            self._server.shutdown()
            with contextlib.suppress(OSError):
                self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("REST API stopped.")

    def join(self) -> None:
        """Block until the server thread ends (standalone mode)."""
        if self._thread:
            self._thread.join()
