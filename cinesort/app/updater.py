"""V1-M13 — Mecanisme update auto via GitHub Releases API.

Pattern check-only : interroge la derniere release publique, retourne un
UpdateInfo si une version plus recente est disponible. Aucune installation
automatique. Le cache local respecte le rate limit GitHub (60 req/h non
authentifie).

V3-12 : helpers complementaires pour le hook au boot et les endpoints UI :
- ``default_cache_path(state_dir)`` : emplacement standard du cache.
- ``force_check(...)`` : check immediat, ignore le cache (bouton "Verifier maintenant").
- ``get_cached_info(...)`` : lit le cache uniquement, sans appel reseau.
- ``info_to_dict(info)`` : serialise pour exposition JSON.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_CHECK_TIMEOUT_S = 5
DEFAULT_CACHE_TTL_S = 3600  # 1h — respecte le rate limit GitHub 60/h non authentifie
USER_AGENT = "CineSort-UpdateChecker/1.0"
CACHE_FILENAME = "update_cache.json"


@dataclass(frozen=True)
class UpdateInfo:
    """Description d'une nouvelle version disponible."""

    latest_version: str
    current_version: str
    release_url: str
    release_notes_excerpt: str
    download_url: Optional[str]
    published_at: str


def _parse_version(version: str) -> Tuple[int, ...]:
    """Parse 'X.Y.Z' ou 'X.Y.Z-suffix' en tuple comparable.

    Les suffixes pre-release ('-dev', '-rc1') sont ignores (la base numerique
    seule est consideree). Les segments non numeriques tombent sur 0.
    """
    base = (version or "").lstrip("v").split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for segment in base.split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0,)


def _compare_versions(current: str, latest: str) -> bool:
    """True si latest > current (semver-aware, sans dependance externe)."""
    try:
        return _parse_version(latest) > _parse_version(current)
    except (TypeError, AttributeError):
        return bool(latest) and latest != current and latest > (current or "")


def check_for_updates(
    current_version: str,
    github_repo: str,
    *,
    timeout_s: int = DEFAULT_CHECK_TIMEOUT_S,
    cache_path: Optional[Path] = None,
    cache_ttl_s: int = DEFAULT_CACHE_TTL_S,
) -> Optional[UpdateInfo]:
    """Verifie GitHub Releases pour une nouvelle version.

    Args:
        current_version: version actuelle (ex: '7.6.0' ou '7.6.0-dev').
        github_repo: 'owner/repo' (ex: 'foo/cinesort').
        timeout_s: timeout reseau (defaut 5s).
        cache_path: fichier de cache JSON optionnel pour limiter les appels.
        cache_ttl_s: duree de validite du cache (defaut 3600s = 1h).

    Returns:
        UpdateInfo si une version plus recente existe, None sinon.
    """
    cached = _read_cache(cache_path, cache_ttl_s)
    if cached is not None:
        return _build_update_info(cached, current_version)

    payload = _fetch_latest_release(github_repo, timeout_s)
    if payload is None:
        return None

    _write_cache(cache_path, payload)
    return _build_update_info(payload, current_version)


def _read_cache(cache_path: Optional[Path], cache_ttl_s: int) -> Optional[dict]:
    """Retourne le payload cache si encore valide, sinon None."""
    if not cache_path or not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Updater: cache illisible (%s)", exc)
        return None
    if not isinstance(data, dict):
        return None
    if time.time() - float(data.get("ts", 0)) >= cache_ttl_s:
        return None
    payload = data.get("payload")
    return payload if isinstance(payload, dict) else None


def _write_cache(cache_path: Optional[Path], payload: dict) -> None:
    if not cache_path:
        return
    try:
        cache_path.write_text(json.dumps({"ts": time.time(), "payload": payload}), encoding="utf-8")
    except OSError as exc:
        logger.debug("Updater: ecriture cache impossible (%s)", exc)


def _fetch_latest_release(github_repo: str, timeout_s: int) -> Optional[dict]:
    url = f"{GITHUB_API_BASE}/repos/{github_repo}/releases/latest"
    req = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            logger.info("Updater: aucune release publiee (404 sur %s)", github_repo)
        else:
            logger.warning("Updater: GitHub API HTTP %d sur %s", exc.code, github_repo)
        return None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Updater: erreur %s: %s", type(exc).__name__, exc)
        return None
    return payload if isinstance(payload, dict) else None


def _build_update_info(payload: dict, current_version: str) -> Optional[UpdateInfo]:
    """Construit UpdateInfo si la release est plus recente que current_version."""
    latest_tag = str(payload.get("tag_name") or "").lstrip("v")
    if not latest_tag or not _compare_versions(current_version, latest_tag):
        return None

    download_url: Optional[str] = None
    for asset in payload.get("assets") or []:
        if isinstance(asset, dict) and str(asset.get("name", "")).lower().endswith(".exe"):
            download_url = asset.get("browser_download_url")
            break

    return UpdateInfo(
        latest_version=latest_tag,
        current_version=current_version,
        release_url=str(payload.get("html_url") or ""),
        release_notes_excerpt=str(payload.get("body") or "")[:500],
        download_url=download_url,
        published_at=str(payload.get("published_at") or ""),
    )


# ---------------------------------------------------------------------------
# V3-12 — helpers pour le hook au boot et les endpoints UI
# ---------------------------------------------------------------------------


def default_cache_path(state_dir: Path) -> Path:
    """Emplacement standard du cache update dans le state_dir CineSort."""
    return Path(state_dir) / CACHE_FILENAME


def info_to_dict(info: Optional[UpdateInfo], current_version: str) -> Dict[str, Any]:
    """Serialise UpdateInfo en dict JSON-friendly pour les endpoints API.

    Retourne un dict toujours non vide. ``update_available`` indique si une
    nouvelle version est disponible. ``current_version`` est toujours present.
    """
    if info is None:
        return {
            "update_available": False,
            "current_version": current_version,
            "latest_version": None,
            "release_url": None,
            "release_notes_short": None,
            "download_url": None,
            "published_at": None,
        }
    return {
        "update_available": True,
        "current_version": info.current_version,
        "latest_version": info.latest_version,
        "release_url": info.release_url or None,
        "release_notes_short": info.release_notes_excerpt or None,
        "download_url": info.download_url,
        "published_at": info.published_at or None,
    }


def force_check(
    current_version: str,
    github_repo: str,
    *,
    cache_path: Optional[Path] = None,
    timeout_s: int = DEFAULT_CHECK_TIMEOUT_S,
) -> Optional[UpdateInfo]:
    """Force un check reseau immediat (ignore le cache existant).

    Le cache est ecrit avec le nouveau payload pour les checks suivants.
    Retourne None si erreur reseau ou si pas de release plus recente.
    """
    if not github_repo:
        return None
    payload = _fetch_latest_release(github_repo, timeout_s)
    if payload is None:
        return None
    _write_cache(cache_path, payload)
    return _build_update_info(payload, current_version)


def get_cached_info(
    current_version: str,
    *,
    cache_path: Optional[Path] = None,
    cache_ttl_s: int = DEFAULT_CACHE_TTL_S,
) -> Optional[UpdateInfo]:
    """Retourne l'info update depuis le cache uniquement (pas d'appel reseau).

    Utilise par ``get_update_info`` pour servir un resultat instantane apres
    le check au boot. Renvoie None si pas de cache ou cache expire.
    """
    cached = _read_cache(cache_path, cache_ttl_s)
    if cached is None:
        return None
    return _build_update_info(cached, current_version)


def check_for_update_async(
    current_version: str,
    github_repo: str,
    *,
    cache_path: Optional[Path] = None,
    timeout_s: int = DEFAULT_CHECK_TIMEOUT_S,
    cache_ttl_s: int = DEFAULT_CACHE_TTL_S,
) -> Optional[UpdateInfo]:
    """Variante "boot hook" : utilise le cache si frais, sinon refetch.

    Equivalent a ``check_for_updates`` avec cache_path par defaut. Le nom
    "_async" est conventionnel : la fonction reste synchrone, mais elle est
    appelee depuis un thread daemon pour ne pas bloquer le boot.
    """
    if not github_repo:
        return None
    return check_for_updates(
        current_version,
        github_repo,
        timeout_s=timeout_s,
        cache_path=cache_path,
        cache_ttl_s=cache_ttl_s,
    )
