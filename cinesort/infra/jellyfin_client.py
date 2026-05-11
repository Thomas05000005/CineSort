"""Client Jellyfin minimal — connexion, validation, refresh bibliothèque."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests

from cinesort.infra._http_utils import make_session_with_retry

_JELLYFIN_CLIENT_NAME = "CineSort"
_JELLYFIN_CLIENT_VERSION = "1.0"
_JELLYFIN_DEVICE_NAME = "Desktop"
_JELLYFIN_DEVICE_ID = "cinesort-desktop-001"

_log = logging.getLogger(__name__)


from cinesort.infra.integration_errors import IntegrationError


class JellyfinError(IntegrationError):
    """Erreur liée à l'API Jellyfin.

    Herite de IntegrationError (BUG-1 v7.8.0) pour permettre un catch uniforme
    cross-clients sans recourir a `except Exception`.
    """


def _normalize_url(url: str) -> str:
    """Normalise l'URL du serveur Jellyfin (strip, trailing slash)."""
    url = (url or "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    return url


def _build_auth_header(api_key: str) -> str:
    """Construit le header Authorization MediaBrowser (format simple, compatible toutes versions)."""
    return f'MediaBrowser Token="{api_key}"'


class JellyfinClient:
    """Client pour l'API REST Jellyfin.

    Fonctionnalités MVP :
    - Validation de connexion (info serveur + utilisateur)
    - Liste des bibliothèques
    - Refresh de bibliothèque (post-apply)
    - Comptage des films
    """

    def __init__(self, base_url: str, api_key: str, *, timeout_s: float = 10.0):
        self.base_url = _normalize_url(base_url)
        self.api_key = (api_key or "").strip()
        self.timeout_s = max(1.0, min(60.0, float(timeout_s)))
        # Audit ID-ROB-001 : Session avec retry/backoff automatique pour erreurs
        # transitoires (429/5xx). Le retry custom watched-state restore reste gere
        # ailleurs (backoff exponentiel cap 60s, total max 135s — H-11) et n'est
        # pas couvert par ce retry de Session.
        self._session = make_session_with_retry(
            user_agent="CineSort/7.6 JellyfinClient",
            max_attempts=3,
            backoff_base=0.5,
        )
        self._session.headers.update(
            {
                "Authorization": _build_auth_header(self.api_key),
                "X-Emby-Token": self.api_key,
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        """GET avec gestion d'erreurs standardisée."""
        url = f"{self.base_url}{path}"
        _t0 = time.monotonic()
        try:
            resp = self._session.get(url, timeout=self.timeout_s, **kwargs)
            resp.raise_for_status()
            _log.debug("Jellyfin: GET %s -> %d (%.1fs)", path, resp.status_code, time.monotonic() - _t0)
            return resp
        except requests.ConnectionError as exc:
            _log.debug("Jellyfin: GET %s -> connexion impossible (%.1fs)", path, time.monotonic() - _t0)
            raise JellyfinError(f"Connexion impossible à {self.base_url} : {exc}") from exc
        except requests.Timeout as exc:
            _log.debug("Jellyfin: GET %s -> timeout (%.1fs)", path, time.monotonic() - _t0)
            raise JellyfinError(f"Timeout après {self.timeout_s}s : {exc}") from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            _log.debug("Jellyfin: GET %s -> HTTP %s (%.1fs)", path, status, time.monotonic() - _t0)
            raise JellyfinError(f"Erreur HTTP {status} sur {path}") from exc

    def _post(self, path: str, **kwargs: Any) -> requests.Response:
        """POST avec gestion d'erreurs standardisée."""
        url = f"{self.base_url}{path}"
        _t0 = time.monotonic()
        try:
            resp = self._session.post(url, timeout=self.timeout_s, **kwargs)
            resp.raise_for_status()
            _log.debug("Jellyfin: POST %s -> %d (%.1fs)", path, resp.status_code, time.monotonic() - _t0)
            return resp
        except requests.ConnectionError as exc:
            _log.debug("Jellyfin: POST %s -> connexion impossible (%.1fs)", path, time.monotonic() - _t0)
            raise JellyfinError(f"Connexion impossible à {self.base_url} : {exc}") from exc
        except requests.Timeout as exc:
            _log.debug("Jellyfin: POST %s -> timeout (%.1fs)", path, time.monotonic() - _t0)
            raise JellyfinError(f"Timeout après {self.timeout_s}s : {exc}") from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            _log.debug("Jellyfin: POST %s -> HTTP %s (%.1fs)", path, status, time.monotonic() - _t0)
            raise JellyfinError(f"Erreur HTTP {status} sur {path}") from exc

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def validate_connection(self) -> dict:
        """Teste la connexion au serveur Jellyfin.

        Retourne un dict avec les infos serveur et utilisateur :
        {ok, server_name, version, user_id, user_name, is_admin, error?}

        Utilise /System/Info pour le serveur et /Users pour trouver
        l'utilisateur admin (au lieu de /Users/Me qui requiert un token
        de session utilisateur et retourne 400 avec une API key admin).
        """
        if not self.base_url:
            return {"ok": False, "error": "URL du serveur non configurée"}
        if not self.api_key:
            return {"ok": False, "error": "Clé API non configurée"}

        # Etape 1 : info serveur (endpoint public, pas d'auth requise)
        try:
            resp = self._get("/System/Info/Public")
            server_info = resp.json()
        except JellyfinError as exc:
            return {"ok": False, "error": str(exc)}
        except (ValueError, KeyError) as exc:
            return {"ok": False, "error": f"Réponse serveur invalide : {exc}"}

        server_name = server_info.get("ServerName", "Inconnu")
        version = server_info.get("Version", "?")

        # Etape 2 : lister les utilisateurs via GET /Users (API key admin)
        # /Users/Me retourne 400 avec une API key car elle n'a pas d'identite
        # utilisateur. GET /Users fonctionne avec une API key admin.
        try:
            resp = self._get("/Users")
            users = resp.json()
        except JellyfinError as exc:
            return {
                "ok": False,
                "server_name": server_name,
                "version": version,
                "error": f"Authentification échouée : {exc}",
            }
        except (ValueError, KeyError) as exc:
            return {
                "ok": False,
                "server_name": server_name,
                "version": version,
                "error": f"Réponse utilisateurs invalide : {exc}",
            }

        if not isinstance(users, list) or not users:
            return {
                "ok": False,
                "server_name": server_name,
                "version": version,
                "error": "Aucun utilisateur trouvé sur le serveur.",
            }

        # Chercher le premier admin, sinon prendre le premier utilisateur
        user_info = next(
            (u for u in users if u.get("Policy", {}).get("IsAdministrator")),
            users[0],
        )

        user_id = user_info.get("Id", "")
        user_name = user_info.get("Name", "Inconnu")
        policy = user_info.get("Policy", {})
        is_admin = policy.get("IsAdministrator", False)

        return {
            "ok": True,
            "server_name": server_name,
            "version": version,
            "user_id": user_id,
            "user_name": user_name,
            "is_admin": is_admin,
        }

    def get_libraries(self, user_id: str) -> list[dict]:
        """Retourne la liste des bibliothèques visibles par l'utilisateur.

        Chaque élément : {id, name, collection_type}
        """
        try:
            resp = self._get(f"/Users/{user_id}/Views")
            data = resp.json()
        except JellyfinError:
            raise
        except (ValueError, KeyError) as exc:
            raise JellyfinError(f"Réponse bibliothèques invalide : {exc}") from exc

        items = data.get("Items", [])
        return [
            {
                "id": item.get("Id", ""),
                "name": item.get("Name", ""),
                "collection_type": item.get("CollectionType", ""),
            }
            for item in items
        ]

    def get_movies_count(self, user_id: str) -> int:
        """Retourne le nombre total de films dans la bibliothèque."""
        try:
            resp = self._get(
                f"/Users/{user_id}/Items",
                params={"IncludeItemTypes": "Movie", "Limit": "0", "Recursive": "true"},
            )
            data = resp.json()
        except JellyfinError:
            raise
        except (ValueError, KeyError) as exc:
            raise JellyfinError(f"Réponse comptage invalide : {exc}") from exc

        return data.get("TotalRecordCount", 0)

    def refresh_library(self) -> bool:
        """Déclenche un rescan complet des bibliothèques Jellyfin.

        Retourne True si le refresh a été accepté (204).
        Nécessite un utilisateur administrateur.
        """
        try:
            self._post("/Library/Refresh")
            _log.info("Jellyfin : refresh bibliothèque déclenché")
            return True
        except JellyfinError as exc:
            _log.warning("Jellyfin : échec refresh — %s", exc)
            raise

    # ------------------------------------------------------------------
    # Phase 2 — Sync watched
    # ------------------------------------------------------------------

    def get_all_movies(self, user_id: str, library_id: Optional[str] = None) -> list[dict]:
        """Retourne tous les films avec leur chemin et statut watched.

        BUG 2 (fix 2) : pagination stricte via StartIndex+Limit. On continue tant
        que Jellyfin renvoie au moins 1 item et que l'avancement est effectif.
        Logs detailles par page pour diagnostic : taille/total/progression.

        Si library_id est fourni, la requete est limitee a cette bibliotheque
        (parametre ParentId). Sinon, toutes les bibliotheques accessibles.

        Chaque élément : {id, name, path, played, play_count, last_played_date}
        """
        result: list[dict] = []
        start_index = 0
        page_size = 1000  # Jellyfin accepte jusqu'a 10000, 1000 est sur
        total_record_count: Optional[int] = None
        page_num = 0

        while True:
            page_num += 1
            params: dict = {
                "IncludeItemTypes": "Movie",
                "Recursive": "true",
                "Fields": "Path,MediaSources,ProviderIds",
                "StartIndex": str(start_index),
                "Limit": str(page_size),
                "SortBy": "SortName",
                "SortOrder": "Ascending",
            }
            if library_id:
                params["ParentId"] = str(library_id)
            try:
                resp = self._get(f"/Users/{user_id}/Items", params=params)
                data = resp.json()
            except JellyfinError:
                raise
            except (ValueError, KeyError) as exc:
                raise JellyfinError(f"Réponse liste films invalide : {exc}") from exc

            items = data.get("Items") or []
            page_total = int(data.get("TotalRecordCount") or 0)
            if total_record_count is None:
                total_record_count = page_total

            # LOG DIAGNOSTIC : chaque page, avec la progression
            _log.info(
                "jellyfin pagination page=%d start=%d got=%d total=%d (cumule=%d)",
                page_num,
                start_index,
                len(items),
                page_total,
                len(result) + len(items),
            )

            for item in items:
                user_data = item.get("UserData") or {}
                provider_ids = item.get("ProviderIds") or {}
                tmdb_raw = provider_ids.get("Tmdb") or provider_ids.get("tmdb")
                result.append(
                    {
                        "id": item.get("Id", ""),
                        "name": item.get("Name", ""),
                        "path": item.get("Path", ""),
                        "year": item.get("ProductionYear") or 0,
                        "tmdb_id": str(tmdb_raw) if tmdb_raw else None,
                        "played": user_data.get("Played", False),
                        "play_count": user_data.get("PlayCount", 0),
                        "last_played_date": user_data.get("LastPlayedDate", ""),
                    }
                )

            page_count = len(items)
            # Condition 1 : page vide = fin
            if page_count == 0:
                _log.info("jellyfin pagination: fin (page vide)")
                break

            start_index += page_count

            # Condition 2 : total annonce atteint
            if total_record_count and start_index >= total_record_count:
                _log.info(
                    "jellyfin pagination: fin (start_index %d >= total %d)",
                    start_index,
                    total_record_count,
                )
                break

            # Condition 3 : page incomplete = fin (Jellyfin retourne moins que demande)
            # NB: si TotalRecordCount est 0 dans la reponse (certains mocks/serveurs),
            # cette condition sert de fallback. En production Jellyfin renvoie toujours
            # un TotalRecordCount precis.
            if page_count < page_size:
                _log.info(
                    "jellyfin pagination: fin (page incomplete %d < %d)",
                    page_count,
                    page_size,
                )
                break

            # Garde-fou : evitons une boucle infinie si Jellyfin bave
            if page_num > 200 or start_index > 100000:
                _log.warning(
                    "jellyfin pagination: garde-fou (page=%d start=%d) arret",
                    page_num,
                    start_index,
                )
                break

        _log.info(
            "jellyfin get_all_movies: recupere %d/%d films en %d page(s) (lib=%s)",
            len(result),
            total_record_count or 0,
            page_num,
            library_id or "all",
        )
        if total_record_count and len(result) != total_record_count:
            _log.warning(
                "jellyfin get_all_movies: ECART entre total annonce (%d) et "
                "recupere (%d). Verifiez les permissions utilisateur ou les bibliotheques.",
                total_record_count,
                len(result),
            )
        return result

    def get_all_movies_from_all_libraries(self, user_id: str) -> list[dict]:
        """BUG 2 : recupere les films de TOUTES les libraries movie du serveur,
        deduplique par Id. Contourne les cas ou la requete globale Recursive
        retourne moins d'items que la somme des libraries individuelles
        (filtrage interne Jellyfin, permissions, collections partagees).
        """
        try:
            libraries = self.get_libraries(user_id)
        except JellyfinError as exc:
            _log.warning("jellyfin get_libraries a echoue, fallback sur get_all_movies global: %s", exc)
            return self.get_all_movies(user_id)

        movie_libs = [lib for lib in libraries if str(lib.get("collection_type", "")).lower() == "movies"]
        _log.info(
            "jellyfin: %d bibliotheque(s) movie trouvee(s) : %s",
            len(movie_libs),
            [lib.get("name") for lib in movie_libs],
        )

        # Premiere passe : recuperation globale (permet de comparer)
        global_movies = self.get_all_movies(user_id)
        global_ids = {m["id"] for m in global_movies if m.get("id")}

        # Seconde passe : requete par library pour detecter les films manquants
        combined: dict = {m["id"]: m for m in global_movies if m.get("id")}
        for lib in movie_libs:
            lib_id = lib.get("id")
            if not lib_id:
                continue
            try:
                lib_movies = self.get_all_movies(user_id, library_id=str(lib_id))
            except JellyfinError as exc:
                _log.warning(
                    "jellyfin get_all_movies(lib=%s) a echoue: %s",
                    lib.get("name"),
                    exc,
                )
                continue
            added = 0
            for m in lib_movies:
                mid = m.get("id")
                if mid and mid not in combined:
                    combined[mid] = m
                    added += 1
            _log.info(
                "jellyfin lib '%s' : %d films recuperes, +%d nouveaux",
                lib.get("name"),
                len(lib_movies),
                added,
            )

        total = len(combined)
        diff = total - len(global_ids)
        _log.info(
            "jellyfin get_all_movies_from_all_libraries: %d films total (global=%d, +%d via libs)",
            total,
            len(global_ids),
            diff,
        )
        return list(combined.values())

    def mark_played(self, user_id: str, item_id: str) -> bool:
        """Marque un film comme vu. Retourne True si succès."""
        try:
            self._post(f"/Users/{user_id}/PlayedItems/{item_id}")
            return True
        except JellyfinError as exc:
            _log.warning("Jellyfin : échec mark_played(%s) — %s", item_id, exc)
            return False

    def mark_unplayed(self, user_id: str, item_id: str) -> bool:
        """Marque un film comme non vu. Retourne True si succès."""
        url = f"{self.base_url}/Users/{user_id}/PlayedItems/{item_id}"
        try:
            resp = self._session.delete(url, timeout=self.timeout_s)
            resp.raise_for_status()
            return True
        except requests.ConnectionError as exc:
            _log.warning("Jellyfin : échec mark_unplayed(%s) — %s", item_id, exc)
            return False
        except requests.Timeout as exc:
            _log.warning("Jellyfin : timeout mark_unplayed(%s) — %s", item_id, exc)
            return False
        except requests.HTTPError as exc:
            _log.warning("Jellyfin : échec mark_unplayed(%s) — HTTP %s", item_id, exc)
            return False
