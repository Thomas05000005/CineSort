"""Proxy HTTP TMDb pour posters de films — etape 1b (iter12).

Module de la couche `cinesort.infra` qui implemente le serveur d'images posters
TMDb avec validation stricte anti-SSRF / anti-open-relay et cache disque local.

Garde-fous (cf docs/internal/BILAN_ITER12_2026-06-08.md section 1) :
- AUCUN parametre URL libre accepte (pas de `url=`, `path=`, `poster_path=`).
- `id` valide par regex `^[1-9]\\d{0,9}$` (anti-SSRF / injection path).
- `size` valide par whitelist frozenset `{w92, w185, w342, w500}`.
- URL TMDb construite COTE SERVEUR via f-string apres validation.
- `poster_path` resolu via `TmdbClient.get_movie_poster_path(id)` (cache local).
- `allow_redirects=False`, `stream=True`, limit 5 MB (anti-DoS + anti-redirect).
- Cache disque : `<state_dir>/cache/posters/<size>/<id>.<ext>` (ext deduite
  Content-Type, whitelist {jpg, png, webp}).
- Ecriture cache atomique et durable via `cinesort.infra.state.atomic_write_bytes`.
- Defense en profondeur : `cache_file.resolve()` doit etre sous
  `cache_root.resolve()`.
- Cle TMDb scrubbee : `image.tmdb.org` est un CDN public, aucun secret
  transmis dans les URLs construites.

Couches : module strict `infra` — n'importe AUCUN module `ui/`, `app/`,
`domain/`. Reuse `cinesort.infra.tmdb_client.TmdbClient` (meme couche).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from cinesort.infra._circuit_breaker import CircuitOpenError
from cinesort.infra._http_utils import make_session_with_retry
from cinesort.infra.state import atomic_write_bytes
from cinesort.infra.tmdb_client import TmdbClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Construction du TmdbClient cote serveur (lecture settings.json + DPAPI)
# ---------------------------------------------------------------------------

#: Cache module-level du TmdbClient construit lazy. Re-initialise quand la
#: cle change (cf `_build_or_get_tmdb_client`).
_tmdb_client_cache: Dict[str, Any] = {
    "client": None,
    "api_key_hash": "",
    "state_dir": "",
}


def _hash_secret(value: str) -> str:
    """Cle de cache stable d'un secret (sans exposer le secret).

    Usage non-securite : juste detecter qu'un secret a change pour invalider
    le client cache.
    """
    if not value:
        return ""
    return hashlib.sha1(value.encode("utf-8"), usedforsecurity=False).hexdigest()  # noqa: S324


def _read_tmdb_api_key_from_settings(state_dir: Path) -> str:
    """Lit la cle TMDb depuis `<state_dir>/settings.json` (utf-8-sig).

    Strategie minimale pour rester en couche `infra` :
    1. Essayer le champ legacy `tmdb_api_key` (clair).
    2. Si vide, tenter le champ `tmdb_api_key_secret` (DPAPI / DPAPI-NG) via
       `cinesort.infra.security.secret_storage`.
    3. Sinon retourner "".

    Aucune exception leve : retour "" en cas de probleme (le caller construira
    un TmdbClient avec cle vide, lequel echouera sur fetch — comportement
    coherent avec le reste de l'app).
    """
    settings_file = state_dir / "settings.json"
    if not settings_file.exists():
        return ""
    try:
        # Memoire user : utf-8-sig OBLIGATOIRE pour tolerer le BOM PowerShell.
        raw = settings_file.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.debug("poster_proxy settings read warn: %s", exc)
        return ""
    if not isinstance(data, dict):
        return ""

    # 1. Legacy en clair.
    legacy = str(data.get("tmdb_api_key") or "").strip()
    if legacy:
        return legacy

    # 2. DPAPI / DPAPI-NG.
    secret_payload = data.get("tmdb_api_key_secret")
    if isinstance(secret_payload, dict):
        blob_b64 = str(secret_payload.get("blob_b64") or "").strip()
        if blob_b64:
            try:
                from cinesort.infra.security.secret_storage import (  # noqa: PLC0415
                    SecretStorageError,
                    load_secret,
                )

                result = load_secret("tmdb_api_key", blob_b64)
                return str(result.value or "").strip()
            except (ImportError, SecretStorageError) as exc:
                logger.warning("poster_proxy: chargement cle DPAPI echoue: %s", type(exc).__name__)
                return ""
    return ""


def _build_or_get_tmdb_client(state_dir: Path) -> Optional[TmdbClient]:
    """Construit (lazy) ou recupere depuis cache un TmdbClient pour le proxy.

    Le client est conserve module-level et reutilise tant que la cle API
    et le state_dir n'ont pas change. Cf #75/#76 pour la garantie de robustesse
    du client (LRU cache + circuit breaker).

    Returns
    -------
    `TmdbClient` instancie, ou `None` si la cle est vide / illisible.
    """
    api_key = _read_tmdb_api_key_from_settings(state_dir)
    if not api_key:
        return None

    api_key_hash = _hash_secret(api_key)
    state_dir_str = str(state_dir)
    cached_client = _tmdb_client_cache.get("client")
    if (
        cached_client is not None
        and _tmdb_client_cache.get("api_key_hash") == api_key_hash
        and _tmdb_client_cache.get("state_dir") == state_dir_str
    ):
        return cached_client  # type: ignore[no-any-return]

    try:
        client = TmdbClient(
            api_key=api_key,
            cache_path=state_dir / "tmdb_cache.json",
            timeout_s=10.0,
        )
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("poster_proxy TmdbClient init failed: %s", exc)
        return None

    _tmdb_client_cache["client"] = client
    _tmdb_client_cache["api_key_hash"] = api_key_hash
    _tmdb_client_cache["state_dir"] = state_dir_str
    return client


# ---------------------------------------------------------------------------
# Constantes FIGE (validation, whitelists, limites)
# ---------------------------------------------------------------------------

#: Whitelist des tailles TMDb autorisees (cf section 1.2 du bilan iter12).
#: Tout autre valeur (vide, "original", "w999", "W92") declenche un 400 immediat.
POSTER_SIZES_ALLOWED: frozenset = frozenset({"w92", "w185", "w342", "w500"})

#: Regex de validation de l'`id` TMDb (entier strictement positif, 1..9 999 999 999).
TMDB_ID_REGEX = re.compile(r"^[1-9]\d{0,9}$")

#: Regex de sanitize du `poster_path` retourne par le cache TMDb local. Si la
#: valeur ne matche pas (cache pollue) -> 502.
POSTER_PATH_REGEX = re.compile(r"^/[A-Za-z0-9_.-]+$")

#: Mapping Content-Type TMDb -> extension fichier (whitelist stricte).
POSTER_EXT_BY_CONTENT_TYPE: Dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

#: Liste des extensions a tester en cache hit (ordre = preference).
POSTER_EXT_WHITELIST: Tuple[str, ...] = ("jpg", "png", "webp")

#: Borne max du payload TMDb (anti-DoS memoire/disque) — 5 MB.
MAX_POSTER_BYTES = 5 * 1024 * 1024

#: TTL HTTP pour la cache-control client (30 jours, immutable).
CACHE_CONTROL_MAX_AGE = 30 * 24 * 3600

#: Timeout HTTP du fetch TMDb (secondes).
FETCH_TIMEOUT_S = 10.0

#: Categories d'erreur retournees par fetch_and_cache (utilisees par serve_poster
#: pour mapper vers les codes HTTP appropries).
ERR_NO_POSTER = "NO_POSTER"  # 404 — TMDb n'a pas de poster pour cet id
ERR_UPSTREAM_ERROR = "UPSTREAM_ERROR"  # 502 — TMDb 5xx/4xx, content-type inattendu, body > 5 MB
ERR_OFFLINE = "OFFLINE"  # 503 — reseau down, DNS fail, ConnectionError
ERR_CACHE_POLLUTED = "CACHE_POLLUTED"  # 502 — poster_path ne matche pas POSTER_PATH_REGEX


# ---------------------------------------------------------------------------
# Session HTTP partagee (lazy, reutilisee entre appels)
# ---------------------------------------------------------------------------

_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    """Retourne une session HTTP partagee (lazy init, idempotent).

    Reutilise le pattern `make_session_with_retry` deja en place dans
    `cinesort.infra.tmdb_client` (retry+backoff exponentiel, User-Agent).
    """
    global _session
    if _session is None:
        _session = make_session_with_retry(
            user_agent="CineSort/7.6 PosterProxy",
            max_attempts=2,  # 1 retry suffit, on est sur du CDN
            backoff_base=0.3,
        )
    return _session


# ---------------------------------------------------------------------------
# Validation des parametres de requete (anti-SSRF)
# ---------------------------------------------------------------------------


def validate_request(
    id_raw: Optional[str],
    size_raw: Optional[str],
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Valide les parametres `id` et `size` extraits de la query string.

    Returns
    -------
    (tmdb_id, size, error_message)
        - Si valide : `(int, str, None)`.
        - Si invalide : `(None, None, str)` ou `error_message` explique le
          probleme en francais (pas de fuite de valeur recue).

    Aucune autre information (id_raw, size_raw) n'est repercutee dans le message
    pour eviter l'attack vector "log reflection" cote client.
    """
    if id_raw is None or not isinstance(id_raw, str):
        return None, None, "Parametre 'id' manquant."
    if size_raw is None or not isinstance(size_raw, str):
        return None, None, "Parametre 'size' manquant."

    if not TMDB_ID_REGEX.match(id_raw):
        return None, None, "Parametre 'id' invalide."

    if size_raw not in POSTER_SIZES_ALLOWED:
        return None, None, "Parametre 'size' hors whitelist."

    try:
        tmdb_id = int(id_raw)
    except (TypeError, ValueError):
        # Defense en profondeur — la regex garantit deja un int valide.
        return None, None, "Parametre 'id' invalide."

    if tmdb_id <= 0:
        return None, None, "Parametre 'id' invalide."

    return tmdb_id, size_raw, None


# ---------------------------------------------------------------------------
# Resolution du cache disque
# ---------------------------------------------------------------------------


def _resolve_cache_root(cache_root: Path, size: str) -> Path:
    """Retourne le repertoire de cache pour une `size` donnee, le cree si absent.

    Garde anti path-traversal : `size` doit appartenir a la whitelist (verifie
    par le caller). Aucune valeur libre du client n'apparait dans le path.
    """
    if size not in POSTER_SIZES_ALLOWED:
        # Defense en profondeur — caller doit deja avoir valide.
        raise ValueError(f"size hors whitelist: {size!r}")
    target = cache_root / size
    target.mkdir(parents=True, exist_ok=True)
    return target


def _is_under_root(cache_file: Path, cache_root: Path) -> bool:
    """Defense en profondeur : verifie que `cache_file` est strictement sous
    `cache_root` (anti path-traversal residuel).
    """
    try:
        resolved_file = cache_file.resolve()
        resolved_root = cache_root.resolve()
    except (OSError, RuntimeError):
        return False
    try:
        resolved_file.relative_to(resolved_root)
        return True
    except ValueError:
        return False


def resolve_cache_file(cache_root: Path, size: str, tmdb_id: int) -> Optional[Tuple[Path, str]]:
    """Cherche un cache hit parmi les extensions autorisees.

    Returns
    -------
    (cache_file, ext)
        Si un fichier `<cache_root>/<size>/<id>.<ext>` existe (premiere ext
        rencontree dans `POSTER_EXT_WHITELIST`). Sinon `None`.
    """
    size_dir = cache_root / size
    if not size_dir.is_dir():
        return None
    for ext in POSTER_EXT_WHITELIST:
        candidate = size_dir / f"{tmdb_id}.{ext}"
        if candidate.is_file() and _is_under_root(candidate, cache_root):
            return candidate, ext
    return None


# ---------------------------------------------------------------------------
# Fetch TMDb + ecriture cache atomique
# ---------------------------------------------------------------------------


def _atomic_write(target: Path, payload: bytes) -> None:
    """Ecriture atomique ET durable d'un fichier binaire.

    Fix #712 : le `.tmp` etait nomme en dur (`target.suffix + '.tmp'`), donc
    identique pour tous les threads du `ThreadingHTTPServer`. Deux requetes
    concurrentes sur le MEME (tmdb_id, size) — cas courant : une grille de
    jaquettes qui se charge — s'ecrasaient mutuellement et pouvaient promouvoir
    un JPEG a moitie ecrit dans le cache, servi ensuite pendant 30 jours
    (Cache-Control immuable). Le helper unique fait le nom unique + le fsync +
    le controle de taille.

    Resolution du conflit avec `#718` (merge de main du 2026-08-04) : les deux
    branches corrigent la MEME course, main sur place et celle-ci en routant
    vers `state.atomic_write_bytes`. C'est cette derniere qui est retenue parce
    qu'elle SUBSUME l'autre — `state._replace_with_retry` porte exactement la
    politique de retentative mesuree par `#718` (12 tentatives, base 2 ms,
    plafond 50 ms, jitter par thread ; 19/32 echecs sans elle, 0/32 avec) et y
    ajoute le controle de taille ecrite. Garder les deux aurait duplique la
    politique en deux exemplaires qui divergent au premier reglage.
    """
    atomic_write_bytes(target, payload)


def fetch_and_cache(
    tmdb_client: Any,
    cache_root: Path,
    tmdb_id: int,
    size: str,
) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
    """Fetch un poster TMDb cote serveur et l'ecrit dans le cache disque.

    Parameters
    ----------
    tmdb_client : `cinesort.infra.tmdb_client.TmdbClient`
        Client TMDb avec cache JSON local (reuse de l'instance applicative).
    cache_root : Path
        Repertoire racine du cache poster (typiquement
        `<APP_DATA_DIR>/cache/posters/`).
    tmdb_id : int
        Identifiant TMDb deja valide.
    size : str
        Taille TMDb deja validee (`w92`, `w185`, `w342`, `w500`).

    Returns
    -------
    (cache_file, content_type, error_code)
        - Succes : `(Path, str, None)`.
        - Erreur : `(None, None, str)` avec `error_code` parmi
          `ERR_NO_POSTER`, `ERR_UPSTREAM_ERROR`, `ERR_OFFLINE`,
          `ERR_CACHE_POLLUTED`.

    Notes
    -----
    - La cle API TMDb n'est PAS necessaire pour fetcher `image.tmdb.org`
      (CDN public). Aucun secret n'est inclus dans l'URL ni les logs.
    - `allow_redirects=False` (TMDb ne redirige pas, defense en profondeur).
    - Stream lecture avec limit 5 MB (`MAX_POSTER_BYTES`) pour borner memoire.
    """
    # 1. Resoudre poster_path via le cache TMDb existant.
    try:
        poster_path = tmdb_client.get_movie_poster_path(tmdb_id)
    except Exception as exc:  # noqa: BLE001 — best-effort, on log et fallback
        logger.warning("poster_proxy resolve poster_path failed id=%d: %s", tmdb_id, exc)
        return None, None, ERR_UPSTREAM_ERROR

    if not poster_path:
        # TMDb n'a pas de poster pour cet id (ou id inexistant) -> 404 ephemere.
        return None, None, ERR_NO_POSTER

    # 2. Sanitize : doit matcher la regex stricte (no `..`, no slash multiple).
    if not POSTER_PATH_REGEX.match(poster_path):
        logger.warning(
            "poster_proxy cache pollue id=%d size=%s poster_path_invalide",
            tmdb_id,
            size,
        )
        return None, None, ERR_CACHE_POLLUTED

    # 3. Construire l'URL CDN cote serveur (jamais valeur libre client).
    url = f"https://image.tmdb.org/t/p/{size}{poster_path}"

    # 4. Fetch HTTP avec garde-fous.
    session = _get_session()
    _t0 = time.monotonic()
    try:
        response = session.get(
            url,
            timeout=FETCH_TIMEOUT_S,
            stream=True,
            allow_redirects=False,
        )
    except (requests.RequestException, CircuitOpenError, ConnectionError, TimeoutError) as exc:
        # Reseau down / DNS fail / timeout — 503 si pas de cache.
        logger.info("poster_proxy fetch network error id=%d size=%s err=%s", tmdb_id, size, type(exc).__name__)
        return None, None, ERR_OFFLINE
    except Exception as exc:  # noqa: BLE001 — boundary HTTP
        logger.warning("poster_proxy fetch unexpected error id=%d size=%s err=%s", tmdb_id, size, type(exc).__name__)
        return None, None, ERR_UPSTREAM_ERROR

    # Ne PAS logger response body ni headers complets (au cas ou TMDb echo
    # un parametre suspect). Logger uniquement status_code et content-type.
    status = response.status_code
    content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()

    if status == 404:
        with contextlib.suppress(Exception):
            response.close()
        logger.info("poster_proxy tmdb 404 id=%d size=%s", tmdb_id, size)
        return None, None, ERR_NO_POSTER

    if status != 200:
        with contextlib.suppress(Exception):
            response.close()
        logger.warning("poster_proxy tmdb error id=%d size=%s status=%d", tmdb_id, size, status)
        return None, None, ERR_UPSTREAM_ERROR

    ext = POSTER_EXT_BY_CONTENT_TYPE.get(content_type)
    if not ext:
        with contextlib.suppress(Exception):
            response.close()
        logger.warning(
            "poster_proxy content-type inattendu id=%d size=%s ct=%s",
            tmdb_id,
            size,
            content_type[:32],  # cap pour log
        )
        return None, None, ERR_UPSTREAM_ERROR

    # 5. Lire en streaming avec borne 5 MB (anti-DoS memoire).
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_POSTER_BYTES:
                with contextlib.suppress(Exception):
                    response.close()
                logger.warning(
                    "poster_proxy payload trop volumineux id=%d size=%s bytes=%d",
                    tmdb_id,
                    size,
                    total,
                )
                return None, None, ERR_UPSTREAM_ERROR
            chunks.append(chunk)
    except (requests.RequestException, ConnectionError, TimeoutError) as exc:
        logger.info(
            "poster_proxy stream read error id=%d size=%s err=%s",
            tmdb_id,
            size,
            type(exc).__name__,
        )
        return None, None, ERR_OFFLINE
    finally:
        with contextlib.suppress(Exception):
            response.close()

    payload = b"".join(chunks)
    if not payload:
        logger.warning("poster_proxy empty payload id=%d size=%s", tmdb_id, size)
        return None, None, ERR_UPSTREAM_ERROR

    # 6. Cache file path + defense en profondeur (sous cache_root.resolve()).
    try:
        size_dir = _resolve_cache_root(cache_root, size)
    except (OSError, ValueError) as exc:
        logger.warning("poster_proxy cache dir error id=%d size=%s err=%s", tmdb_id, size, exc)
        return None, None, ERR_UPSTREAM_ERROR

    cache_file = size_dir / f"{tmdb_id}.{ext}"
    if not _is_under_root(cache_file, cache_root):
        logger.error(
            "poster_proxy path traversal detecte id=%d size=%s",
            tmdb_id,
            size,
        )
        return None, None, ERR_UPSTREAM_ERROR

    # 7. Ecriture atomique.
    try:
        _atomic_write(cache_file, payload)
    except OSError as exc:
        logger.warning(
            "poster_proxy cache write error id=%d size=%s err=%s",
            tmdb_id,
            size,
            exc,
        )
        # Pas critique : on a quand meme la data en memoire, mais le caller
        # attend un path. On retourne UPSTREAM_ERROR pour ne pas mentir.
        return None, None, ERR_UPSTREAM_ERROR

    logger.info(
        "poster_proxy fetched id=%d size=%s ext=%s bytes=%d ms=%.0f",
        tmdb_id,
        size,
        ext,
        total,
        (time.monotonic() - _t0) * 1000,
    )
    return cache_file, content_type, None


# ---------------------------------------------------------------------------
# Helpers HTTP (ETag, Content-Type, codes erreur)
# ---------------------------------------------------------------------------


def compute_etag(tmdb_id: int, size: str, file_size_bytes: int) -> str:
    """Calcule un ETag deterministe pour la cache-control HTTP.

    `sha1` non utilise pour la securite ici (cf S324 mute via `usedforsecurity`
    sur Python >= 3.9).
    """
    raw = f"{tmdb_id}|{size}|{file_size_bytes}".encode("utf-8")
    digest = hashlib.sha1(raw, usedforsecurity=False).hexdigest()  # noqa: S324
    return f'"{digest}"'


def content_type_from_ext(ext: str) -> str:
    """Inverse du mapping POSTER_EXT_BY_CONTENT_TYPE (ext -> Content-Type)."""
    mapping = {
        "jpg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }
    return mapping.get(ext, "application/octet-stream")


# ---------------------------------------------------------------------------
# Orchestration get_or_fetch (cache hit -> fetch -> cache write)
# ---------------------------------------------------------------------------


def get_or_fetch(
    tmdb_client: Any,
    cache_root: Path,
    tmdb_id: int,
    size: str,
) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
    """Orchestre cache lookup + fetch TMDb si miss.

    Parameters
    ----------
    tmdb_client : `cinesort.infra.tmdb_client.TmdbClient`
        Client TMDb avec cache JSON local.
    cache_root : Path
        Repertoire racine du cache poster.
    tmdb_id : int
        Identifiant TMDb deja valide (cf `validate_request`).
    size : str
        Taille TMDb deja validee.

    Returns
    -------
    (cache_file, content_type, error_code)
        - Succes : `(Path, str, None)`.
        - Erreur : `(None, None, str)` avec `error_code` parmi
          `ERR_NO_POSTER`, `ERR_UPSTREAM_ERROR`, `ERR_OFFLINE`,
          `ERR_CACHE_POLLUTED`.

    Notes
    -----
    Cas fallback graceful : si fetch TMDb echoue (`ERR_OFFLINE`/`ERR_UPSTREAM_ERROR`)
    mais qu'un cache disque existe (meme ancien), on sert le cache.
    """
    # 1. Cache hit ?
    hit = resolve_cache_file(cache_root, size, tmdb_id)
    if hit is not None:
        cache_file, ext = hit
        content_type = content_type_from_ext(ext)
        logger.debug("poster_proxy cache hit id=%d size=%s ext=%s", tmdb_id, size, ext)
        return cache_file, content_type, None

    # 2. Cache miss -> fetch TMDb.
    logger.debug("poster_proxy cache miss id=%d size=%s", tmdb_id, size)
    cache_file, content_type, error_code = fetch_and_cache(tmdb_client, cache_root, tmdb_id, size)
    if error_code is None:
        return cache_file, content_type, None

    # 3. Fetch failed mais cache disque existe (cas tres improbable apres miss,
    #    safety net) — on a deja teste hit, mais on relit au cas ou un autre
    #    thread a ecrit entre temps.
    hit_retry = resolve_cache_file(cache_root, size, tmdb_id)
    if hit_retry is not None:
        cache_file_r, ext_r = hit_retry
        logger.info(
            "poster_proxy fetch failed, fallback cache hit id=%d size=%s ext=%s err=%s",
            tmdb_id,
            size,
            ext_r,
            error_code,
        )
        return cache_file_r, content_type_from_ext(ext_r), None

    return None, None, error_code


# ---------------------------------------------------------------------------
# Adapter HTTP : pilote un BaseHTTPRequestHandler
# ---------------------------------------------------------------------------

#: Mapping `error_code` -> (`http_status`, `category`, `message`).
_HTTP_ERROR_MAP: Dict[str, Tuple[int, str, str]] = {
    ERR_NO_POSTER: (404, "resource", "Poster not available"),
    ERR_UPSTREAM_ERROR: (502, "runtime", "Upstream error"),
    ERR_OFFLINE: (503, "runtime", "Cache miss offline"),
    ERR_CACHE_POLLUTED: (502, "runtime", "Upstream error"),
}


def serve_poster(
    handler: Any,
    state_dir: Path,
    cache_root: Path,
    query: Dict[str, str],
    allow_fetch: bool = True,
) -> None:
    """Orchestre la reponse HTTP complete pour `GET /api/poster?id=...&size=...`.

    Parameters
    ----------
    handler : `http.server.BaseHTTPRequestHandler`
        Le handler HTTP courant (utilise pour `send_response`, `send_header`,
        `wfile.write`, `_send_cors_headers`, `_send_request_id_header`).
    state_dir : Path
        Repertoire `default_state_dir()` (typiquement `%LOCALAPPDATA%/CineSort`).
        Sert a localiser `settings.json` (cle API) et `cache/posters/`.
    cache_root : Path
        Repertoire racine du cache poster (typiquement
        `<state_dir>/cache/posters/`). Doit etre fourni par le caller (qui
        peut tester avec un repertoire temporaire).
    query : Dict[str, str]
        Parametres de la query string deja decodes. Seuls `id` et `size`
        sont consideres. **Tout autre parametre (`url`, `path`, ...) est
        ignore silencieusement** (anti-enumeration).

    Side effects
    ------------
    Ecrit la reponse HTTP complete sur `handler.wfile`. Le handler ne doit
    plus ecrire apres cet appel.
    """
    # 1. Valider id + size.
    id_raw = query.get("id")
    size_raw = query.get("size")
    tmdb_id, size, error_msg = validate_request(id_raw, size_raw)
    if error_msg is not None:
        _respond_error_json(handler, 400, "validation", error_msg)
        return

    # `tmdb_id` et `size` sont non-None ici (mypy hint).
    assert tmdb_id is not None and size is not None

    if not allow_fetch:
        # R8-095 (filet F3) : appelant NON fiable (cross-site / client LAN
        # non-navigateur) -> CACHE SEUL. Aucune requete TMDb sortante, aucun
        # purge, aucune ecriture disque (anti-amplification : un <img>/curl tiers
        # ne peut pas bruler le quota de la cle API ni declencher d'I/O). La
        # LECTURE d'un poster deja en cache reste servie (img legitime non casse).
        hit = resolve_cache_file(cache_root, size, tmdb_id)
        if hit is None:
            _respond_error_json(handler, 404, "resource", "Poster not available")
            return
        cache_file, _ext = hit
        content_type = content_type_from_ext(_ext)
    else:
        # 2. Resoudre le TmdbClient (lazy depuis settings.json).
        tmdb_client = _build_or_get_tmdb_client(state_dir)
        if tmdb_client is None:
            # Pas de cle API configuree -> on retourne 503 (proxy non operationnel)
            # plutot que 502 (qui suggererait une erreur TMDb).
            _respond_error_json(handler, 503, "config", "Proxy TMDb non configure")
            return

        # AUDIT 2026-06-14 (R7-8) : `force` -> invalider le cache disque pour
        # (id, size) afin de re-telecharger depuis TMDb (bouton "Recuperer
        # jaquettes"). Sinon le fichier cache (immuable, Cache-Control 30j) etait
        # reservi tel quel -> le refresh n'avait aucun effet visuel.
        if str(query.get("force") or "").strip().lower() in ("1", "true", "yes"):
            try:
                for _f in (cache_root / size).glob(f"{tmdb_id}.*"):
                    _f.unlink()
            except (OSError, ValueError):
                pass

        # 3. Orchestrer cache hit / fetch.
        cache_file, content_type, error_code = get_or_fetch(tmdb_client, cache_root, tmdb_id, size)
        if error_code is not None:
            status, category, message = _HTTP_ERROR_MAP.get(error_code, (502, "runtime", "Upstream error"))
            _respond_error_json(handler, status, category, message)
            return

    assert cache_file is not None and content_type is not None

    # 4. Lire les bytes.
    try:
        payload = cache_file.read_bytes()
    except OSError as exc:
        logger.warning("poster_proxy cache read error file=%s err=%s", cache_file.name, exc)
        _respond_error_json(handler, 502, "runtime", "Upstream error")
        return

    # 5. ETag + If-None-Match (revalidation conditionnelle).
    etag = compute_etag(tmdb_id, size, len(payload))
    if_none_match = handler.headers.get("If-None-Match", "")
    if if_none_match and if_none_match.strip() == etag:
        handler.send_response(304)
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", f"public, max-age={CACHE_CONTROL_MAX_AGE}, immutable")
        _safe_call(handler, "_send_cors_headers")
        _safe_call(handler, "_send_request_id_header")
        handler.end_headers()
        return

    # 6. Reponse 200 avec headers complets.
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", f"public, max-age={CACHE_CONTROL_MAX_AGE}, immutable")
    handler.send_header("ETag", etag)
    handler.send_header("X-Content-Type-Options", "nosniff")
    _safe_call(handler, "_send_cors_headers")
    _safe_call(handler, "_send_request_id_header")
    handler.end_headers()
    handler.wfile.write(payload)


def _respond_error_json(
    handler: Any,
    status: int,
    category: str,
    message: str,
) -> None:
    """Reponse JSON d'erreur conforme au pattern `_err_response` de l'app."""
    body = json.dumps(
        {"ok": False, "category": category, "message": message},
        ensure_ascii=False,
    ).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    _safe_call(handler, "_send_cors_headers")
    _safe_call(handler, "_send_request_id_header")
    handler.end_headers()
    handler.wfile.write(body)


def _safe_call(handler: Any, method_name: str) -> None:
    """Appel best-effort d'une methode privee du handler (tests friendly)."""
    method = getattr(handler, method_name, None)
    if callable(method):
        with contextlib.suppress(Exception):
            method()
