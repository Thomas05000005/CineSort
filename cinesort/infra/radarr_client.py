"""Client Radarr v3 minimal — connexion, liste films, profils qualite, recherche upgrade.

HTTP direct avec X-Api-Key, pas de dependance externe.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List

import requests

from cinesort.infra._http_utils import make_session_with_retry

_log = logging.getLogger(__name__)


from cinesort.infra.integration_errors import IntegrationError


class RadarrError(IntegrationError):
    """Erreur liee a l'API Radarr.

    Herite de IntegrationError (BUG-1 v7.8.0) pour catch uniforme cross-clients.
    """


def _normalize_url(url: str) -> str:
    """Cf issue #70 : valide qu'on ne cible pas un endpoint cloud metadata
    (169.254.169.254 etc.). Leve RadarrError si invalide.
    """
    from cinesort.infra.network_utils import is_safe_external_url

    url = (url or "").strip().rstrip("/")
    if url and "://" not in url:
        url = f"http://{url}"
    if url:
        ok, reason = is_safe_external_url(url)
        if not ok:
            raise RadarrError(f"URL Radarr refusee : {reason}")
    return url


class RadarrClient:
    """Client pour l'API REST Radarr v3."""

    def __init__(self, base_url: str, api_key: str, *, timeout_s: float = 10.0):
        self.base_url = _normalize_url(base_url)
        self.api_key = (api_key or "").strip()
        self.timeout_s = max(1.0, min(60.0, float(timeout_s)))
        self._session = make_session_with_retry(
            user_agent="CineSort/7.6 RadarrClient",
            max_attempts=3,
            backoff_base=0.5,
        )
        self._session.headers.update(
            {
                "X-Api-Key": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}{path}"
        _t0 = time.monotonic()
        try:
            resp = self._session.get(url, timeout=self.timeout_s, **kwargs)
            resp.raise_for_status()
            _log.debug("Radarr: GET %s -> %d (%.1fs)", path, resp.status_code, time.monotonic() - _t0)
            return resp
        except requests.ConnectionError as exc:
            _log.debug("Radarr: GET %s -> connexion impossible (%.1fs)", path, time.monotonic() - _t0)
            raise RadarrError(f"Connexion impossible a {self.base_url} : {exc}") from exc
        except requests.Timeout as exc:
            _log.debug("Radarr: GET %s -> timeout (%.1fs)", path, time.monotonic() - _t0)
            raise RadarrError(f"Timeout apres {self.timeout_s}s : {exc}") from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            _log.debug("Radarr: GET %s -> HTTP %s (%.1fs)", path, status, time.monotonic() - _t0)
            raise RadarrError(f"Erreur HTTP {status} sur {path}") from exc

    def _post(self, path: str, payload: Any = None, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}{path}"
        _t0 = time.monotonic()
        try:
            resp = self._session.post(
                url,
                data=json.dumps(payload) if payload else None,
                timeout=self.timeout_s,
                **kwargs,
            )
            resp.raise_for_status()
            _log.debug("Radarr: POST %s -> %d (%.1fs)", path, resp.status_code, time.monotonic() - _t0)
            return resp
        except requests.ConnectionError as exc:
            _log.debug("Radarr: POST %s -> connexion impossible (%.1fs)", path, time.monotonic() - _t0)
            raise RadarrError(f"Connexion impossible a {self.base_url} : {exc}") from exc
        except requests.Timeout as exc:
            _log.debug("Radarr: POST %s -> timeout (%.1fs)", path, time.monotonic() - _t0)
            raise RadarrError(f"Timeout apres {self.timeout_s}s : {exc}") from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            _log.debug("Radarr: POST %s -> HTTP %s (%.1fs)", path, status, time.monotonic() - _t0)
            raise RadarrError(f"Erreur HTTP {status} sur {path}") from exc

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def validate_connection(self) -> Dict[str, Any]:
        """Teste la connexion au serveur Radarr."""
        if not self.base_url:
            return {"ok": False, "error": "URL du serveur non configuree"}
        if not self.api_key:
            return {"ok": False, "error": "Cle API non configuree"}
        try:
            resp = self._get("/api/v3/system/status")
            data = resp.json()
        except RadarrError as exc:
            return {"ok": False, "error": str(exc)}
        except (ValueError, KeyError) as exc:
            return {"ok": False, "error": f"Reponse invalide : {exc}"}
        return {
            "ok": True,
            "server_name": data.get("instanceName") or data.get("appName") or "Radarr",
            "version": data.get("version") or "?",
        }

    def get_movies(self) -> List[Dict[str, Any]]:
        """Retourne tous les films Radarr avec metadonnees et fichier."""
        try:
            resp = self._get("/api/v3/movie")
            items = resp.json()
        except RadarrError:
            raise
        except (ValueError, KeyError) as exc:
            raise RadarrError(f"Reponse films invalide : {exc}") from exc
        if not isinstance(items, list):
            return []
        result: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            mf = item.get("movieFile") or {}
            quality_obj = (mf.get("quality") or {}).get("quality") or {}
            result.append(
                {
                    "id": int(item.get("id") or 0),
                    "title": str(item.get("title") or ""),
                    "year": int(item.get("year") or 0),
                    "tmdb_id": int(item.get("tmdbId") or 0),
                    "monitored": bool(item.get("monitored")),
                    "has_file": bool(item.get("hasFile")),
                    "quality_profile_id": int(item.get("qualityProfileId") or 0),
                    "path": str(mf.get("path") or ""),
                    "quality_name": str(quality_obj.get("name") or ""),
                }
            )
        return result

    def get_quality_profiles(self) -> List[Dict[str, Any]]:
        """Retourne les profils qualite Radarr."""
        try:
            resp = self._get("/api/v3/qualityprofile")
            items = resp.json()
        except RadarrError:
            raise
        except (ValueError, KeyError) as exc:
            raise RadarrError(f"Reponse profils invalide : {exc}") from exc
        if not isinstance(items, list):
            return []
        return [{"id": int(p.get("id") or 0), "name": str(p.get("name") or "")} for p in items if isinstance(p, dict)]

    def search_movie(self, movie_id: int) -> bool:
        """Lance une recherche automatique pour un film (commande MoviesSearch)."""
        mid = int(movie_id or 0)
        if mid <= 0:
            raise RadarrError("movie_id invalide")
        try:
            self._post("/api/v3/command", {"name": "MoviesSearch", "movieIds": [mid]})
            _log.info("Radarr : recherche lancee pour movie_id=%d", mid)
            return True
        except RadarrError as exc:
            _log.warning("Radarr : echec recherche movie_id=%d — %s", mid, exc)
            raise
