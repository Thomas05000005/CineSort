"""Client Plex minimal — connexion, validation, refresh, liste films.

HTTP direct avec X-Plex-Token, pas de dependance plexapi.
Symetrique a jellyfin_client.py.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

import requests

from cinesort.infra._http_utils import ResponseTooLargeError, make_session_with_retry, request_bounded
from cinesort.infra.network_utils import is_safe_external_url

_log = logging.getLogger(__name__)

_PLEX_HEADERS = {
    "Accept": "application/json",
    "X-Plex-Client-Identifier": "cinesort-desktop",
    "X-Plex-Product": "CineSort",
    "X-Plex-Version": "1.0",
}

# Audit C5 P0 #3 : validation stricte du library section id (anti path injection)
# avant interpolation dans /library/sections/{lid}/...
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")

# Pagination de get_movies (regression signalee sur la PR #756).
#
# Mesure sur un item realiste du listing /library/sections/{id}/all?type=1
# (blocs Media/Part/Guid imbriques, JSON compact) :
#   - minimal (sans Guid ni people)                    ~1 926 octets/film
#   - defaut PMS + Guid                                ~2 001 octets/film
#   - complet (Guid + Genre/Country/Director/.../Role) ~2 580 octets/film
#   - complet + resume long                            ~2 860 octets/film
# La borne anti-OOM de 10 Mo appliquee dans _get etait donc franchie par une
# bibliotheque LEGITIME de ~3 500 a ~5 200 films : le sync Plex serait passe
# d'un succes a un echec dur « Reponse Plex trop volumineuse ».
#
# Plex expose la pagination via DEUX en-tetes HTTP a envoyer ensemble
# (X-Plex-Container-Start + X-Plex-Container-Size) — ce sont bien des
# en-tetes et pas des query params, cf le fix Vague H sur get_movies_count.
# 500 films/page = ~1,3 Mo dans le pire cas mesure, soit une marge x7 sous la
# borne, qui redevient valable PAR PAGE.
_MOVIES_PAGE_SIZE = 500
# Garde-fou anti-boucle : 400 pages = 200 000 films, trois ordres de grandeur
# au-dessus d'une bibliotheque personnelle.
_MOVIES_MAX_PAGES = 400


from cinesort.infra.integration_errors import IntegrationError


class PlexError(IntegrationError):
    """Erreur liee a l'API Plex.

    Herite de IntegrationError (BUG-1 v7.8.0) pour catch uniforme cross-clients.
    """


def _normalize_url(url: str) -> str:
    """Normalise l'URL du serveur Plex.

    Cf issue #70 : valide aussi que l'URL ne pointe pas vers un endpoint
    cloud metadata. Leve PlexError si invalide.
    """
    url = (url or "").strip().rstrip("/")
    if url and "://" not in url:
        url = f"http://{url}"
    if url:
        # `resolve_dns=False` : ce constructeur est appele quand l'utilisateur
        # enregistre ses parametres. Resoudre le DNS ici rendrait cet appel
        # BLOQUANT — `socket.getaddrinfo` ne respecte pas
        # `socket.setdefaulttimeout` et peut tenir des dizaines de secondes sur
        # un hote injoignable, ce qui est exactement le cas ou l'on configure
        # une URL. La protection contre le DNS rebinding n'est pas perdue : elle
        # est portee par `SsrfGuardHTTPAdapter`, qui verifie l'IP au moment de
        # la CONNEXION — le seul instant ou la verification ne peut pas etre
        # contournee par un changement de DNS entre-temps (TOCTOU).
        # Releve par CodeRabbit sur la PR#898.
        ok, reason = is_safe_external_url(url, resolve_dns=False)
        if not ok:
            raise PlexError(f"URL Plex refusee : {reason}")
    return url


class PlexClient:
    """Client pour l'API REST Plex."""

    def __init__(self, base_url: str, token: str, *, timeout_s: float = 10.0):
        self.base_url = _normalize_url(base_url)
        self.token = (token or "").strip()
        self.timeout_s = max(1.0, min(60.0, float(timeout_s)))
        self._session = make_session_with_retry(
            user_agent="CineSort/7.6 PlexClient",
            max_attempts=3,
            backoff_base=0.5,
        )
        self._session.headers.update(
            {
                **_PLEX_HEADERS,
                "X-Plex-Token": self.token,
            }
        )

    # ------------------------------------------------------------------
    # Resource management (BUG H9 / hotfix2)
    # ------------------------------------------------------------------
    # H9 : sans close() explicite, le pool de connexions de requests.Session
    # garde N sockets TIME_WAIT a chaque polling dashboard. On expose CM +
    # close() + __del__ best-effort.

    def close(self) -> None:
        """Ferme la session HTTP sous-jacente (idempotent)."""
        session = getattr(self, "_session", None)
        if session is not None:
            try:  # noqa: SIM105 - contextlib.suppress ferait perdre la justification du catch
                session.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "PlexClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:  # noqa: SIM105 - contextlib.suppress ferait perdre la justification du catch
            self.close()
        except Exception:  # noqa: BLE001
            pass

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        """GET avec gestion d'erreurs standardisee.

        La borne anti-OOM du corps est appliquee ICI, au transport (cf
        `request_bounded`), donc A LA LECTURE du flux et non apres que
        `requests` ait deja alloue tout le corps (issues #433 / #753).
        PlexClient etait le dernier client sans cette borne : ses quatre
        `resp.json()` (`validate_connection`, `get_libraries`, `get_movies`,
        `get_movies_count`) sont couverts d'un coup, `refresh_library` avec.
        """
        url = f"{self.base_url}{path}"
        _t0 = time.monotonic()
        try:
            resp = request_bounded(self._session, "GET", url, timeout=self.timeout_s, verify=True, **kwargs)
            resp.raise_for_status()
            # Borne anti-OOM alignee sur les clients freres (jellyfin/radarr/tmdb/omdb) :
            # un serveur Plex usurpe/on-path ou une tres grosse bibliotheque ne doit
            # pas forcer le parse JSON d'un body non borne dans le thread scan.
            _body = getattr(resp, "content", b"")
            if _body and len(_body) > 10_000_000:
                raise PlexError("Reponse Plex trop volumineuse")
            _log.debug("Plex: GET %s -> %d (%.1fs)", path, resp.status_code, time.monotonic() - _t0)
            return resp
        except ResponseTooLargeError as exc:
            # Converti en PlexError : c'est le seul type d'erreur que les cinq
            # appelants traitent (`refresh_library` n'attrape QUE PlexError).
            # Laisser fuir un ValueError le ferait remonter brut jusqu'a l'UI.
            _log.warning("Plex: GET %s -> corps hors borne (%s)", path, exc)
            raise PlexError(f"Reponse Plex trop volumineuse sur {path} : {exc}") from exc
        except requests.ConnectionError as exc:
            _log.debug("Plex: GET %s -> connexion impossible (%.1fs)", path, time.monotonic() - _t0)
            raise PlexError(f"Connexion impossible a {self.base_url} : {exc}") from exc
        except requests.Timeout as exc:
            _log.debug("Plex: GET %s -> timeout (%.1fs)", path, time.monotonic() - _t0)
            raise PlexError(f"Timeout apres {self.timeout_s}s : {exc}") from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            _log.debug("Plex: GET %s -> HTTP %s (%.1fs)", path, status, time.monotonic() - _t0)
            raise PlexError(f"Erreur HTTP {status} sur {path}") from exc

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def validate_connection(self) -> Dict[str, Any]:
        """Teste la connexion au serveur Plex. Retourne {ok, server_name, version}."""
        if not self.base_url:
            return {"ok": False, "error": "URL du serveur non configuree"}
        if not self.token:
            return {"ok": False, "error": "Token Plex non configure"}
        try:
            resp = self._get("/identity")
            data = resp.json()
        except PlexError as exc:
            return {"ok": False, "error": str(exc)}
        except (ValueError, KeyError) as exc:
            return {"ok": False, "error": f"Reponse serveur invalide : {exc}"}

        # Fix audit 2026-05-25 (v1.5.3) Vague H : guard sur le fallback
        # data->mc. Si la reponse n'est pas un dict (ex: serveur renvoie une
        # liste ou un None), on retourne un payload structure plutot que de
        # KeyError sur .get("version").
        mc_raw = data.get("MediaContainer") if isinstance(data, dict) else None
        if isinstance(mc_raw, dict):
            mc = mc_raw
        elif isinstance(data, dict):
            mc = data
        else:
            return {"ok": False, "error": "Reponse serveur invalide : structure inattendue"}
        return {
            "ok": True,
            "server_name": mc.get("friendlyName") or mc.get("machineIdentifier") or "Plex",
            "version": mc.get("version") or "?",
        }

    def get_libraries(self, library_type: str = "movie") -> List[Dict[str, Any]]:
        """Retourne les sections de bibliotheque (filtrees par type)."""
        try:
            resp = self._get("/library/sections")
            data = resp.json()
        except PlexError:
            raise
        except (ValueError, KeyError) as exc:
            raise PlexError(f"Reponse sections invalide : {exc}") from exc

        mc = data.get("MediaContainer") or {}
        dirs = mc.get("Directory") or []
        result: List[Dict[str, Any]] = []
        for d in dirs:
            if not isinstance(d, dict):
                continue
            sec_type = str(d.get("type") or "").strip().lower()
            if library_type and sec_type != library_type:
                continue
            result.append(
                {
                    "id": str(d.get("key") or ""),
                    "name": str(d.get("title") or ""),
                    "type": sec_type,
                }
            )
        return result

    @staticmethod
    def _parse_movie(item: Dict[str, Any]) -> Dict[str, Any]:
        """Convertit un Metadata Plex en dict CineSort {id, name, year, path, tmdb_id, played}."""
        # Extraire le chemin depuis Media.Part.file
        path = ""
        for media in item.get("Media") or []:
            for part in media.get("Part") or []:
                p = str(part.get("file") or "").strip()
                if p:
                    path = p
                    break
            if path:
                break
        # Extraire tmdb_id depuis Guid
        tmdb_id: Optional[str] = None
        for guid in item.get("Guid") or []:
            gid = str(guid.get("id") or "")
            if gid.startswith("tmdb://"):
                tmdb_id = gid[7:]
                break
        return {
            "id": str(item.get("ratingKey") or ""),
            "name": str(item.get("title") or ""),
            "year": int(item.get("year") or 0),
            "path": path,
            "tmdb_id": tmdb_id,
            "played": bool(item.get("viewCount") and int(item.get("viewCount", 0)) > 0),
        }

    def get_movies(self, library_id: str) -> List[Dict[str, Any]]:
        """Retourne tous les films d'une section avec path, year, tmdb_id.

        Pagine via les en-tetes X-Plex-Container-Start / X-Plex-Container-Size
        (cf _MOVIES_PAGE_SIZE) : la reponse non paginee depassait la borne
        anti-OOM de 10 Mo de `_get` des ~4 000 films, transformant le sync
        d'une grosse bibliotheque en echec dur.

        Un serveur peut ignorer la pagination (la doc Plex previent que la
        reponse « might not be paginated at all ») : on le detecte et on
        s'arrete apres la premiere page plutot que de rejouer le meme offset.
        """
        lid = str(library_id or "").strip()
        if not lid:
            raise PlexError("library_id requis")
        if not _SAFE_ID_RE.match(lid):
            raise PlexError(f"Invalid library section id: {lid!r}")

        result: List[Dict[str, Any]] = []
        start = 0
        page_num = 0
        total_size: Optional[int] = None

        while True:
            page_num += 1
            try:
                resp = self._get(
                    f"/library/sections/{lid}/all",
                    # `includeGuids=1` est INDISPENSABLE : le parsing lit
                    # `item["Guid"]` pour en extraire le tmdb_id, mais Plex ne
                    # joint le tableau Guid a un listing de section QUE si ce
                    # parametre est passe. Sans lui le tmdb_id remontait
                    # TOUJOURS None et le rapport de sync appariait les films
                    # sur le seul chemin de fichier.
                    # Cout mesure : ~+4 % de payload. C'est la pagination
                    # ci-dessous qui rend cet ajout sans risque — sans elle il
                    # rapprochait la reponse de la borne des 10 Mo.
                    params={"type": "1", "includeGuids": "1"},
                    headers={
                        "X-Plex-Container-Start": str(start),
                        "X-Plex-Container-Size": str(_MOVIES_PAGE_SIZE),
                    },
                )
                data = resp.json()
            except PlexError:
                raise
            except (ValueError, KeyError) as exc:
                raise PlexError(f"Reponse films invalide : {exc}") from exc

            mc = data.get("MediaContainer") or {}
            items = mc.get("Metadata") or []
            if total_size is None:
                try:
                    total_size = int(mc.get("totalSize") or 0) or None
                except (TypeError, ValueError):
                    total_size = None

            for item in items:
                if not isinstance(item, dict):
                    continue
                result.append(self._parse_movie(item))

            page_count = len(items)
            _log.debug(
                "plex pagination page=%d start=%d recu=%d total=%s (cumule=%d)",
                page_num,
                start,
                page_count,
                total_size,
                len(result),
            )

            if page_count == 0:
                break
            # Serveur qui ignore les en-tetes : il a renvoye TOUTE la section.
            # Redemander une page produirait des doublons a l'infini.
            if page_count > _MOVIES_PAGE_SIZE:
                _log.warning(
                    "plex pagination ignoree par le serveur (recu %d > demande %d) : arret apres la premiere page",
                    page_count,
                    _MOVIES_PAGE_SIZE,
                )
                break
            start += page_count
            if total_size and start >= total_size:
                break
            # Page incomplete = derniere page (fallback quand totalSize est absent).
            if page_count < _MOVIES_PAGE_SIZE:
                break
            if page_num >= _MOVIES_MAX_PAGES:
                _log.warning(
                    "plex pagination : garde-fou atteint (page=%d start=%d), arret",
                    page_num,
                    start,
                )
                break

        _log.info(
            "plex get_movies : %d/%s films en %d page(s) (section=%s)",
            len(result),
            total_size if total_size is not None else "?",
            page_num,
            lid,
        )
        return result

    def get_movies_count(self, library_id: str) -> int:
        """Retourne le nombre de films dans une section."""
        lid = str(library_id or "").strip()
        if not lid:
            return 0
        if not _SAFE_ID_RE.match(lid):
            raise PlexError(f"Invalid library section id: {lid!r}")
        try:
            # Fix audit 2026-05-25 (v1.5.3) Vague H : X-Plex-Container-Size
            # est un HEADER HTTP cote Plex, pas un query param. En le passant
            # via params il etait silencieusement ignore -> Plex renvoyait la
            # liste complete (100 par defaut) et `totalSize` restait juste,
            # mais la requete tirait gratuitement tout le payload films au
            # lieu d'un comptage rapide. On le passe en header desormais.
            resp = self._get(
                f"/library/sections/{lid}/all",
                params={"type": "1"},
                headers={"X-Plex-Container-Size": "0"},
            )
            data = resp.json()
            mc = data.get("MediaContainer") or {}
            return int(mc.get("totalSize") or mc.get("size") or 0)
        except (PlexError, ValueError, KeyError):
            return 0

    def refresh_library(self, library_id: str) -> bool:
        """Declenche un refresh d'une section Plex."""
        lid = str(library_id or "").strip()
        if not lid:
            raise PlexError("library_id requis")
        if not _SAFE_ID_RE.match(lid):
            raise PlexError(f"Invalid library section id: {lid!r}")
        try:
            self._get(f"/library/sections/{lid}/refresh")
            _log.info("Plex : refresh section %s declenche", lid)
            return True
        except PlexError as exc:
            _log.warning("Plex : echec refresh section %s — %s", lid, exc)
            raise
