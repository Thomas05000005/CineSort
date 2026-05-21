from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import cinesort.infra.state as state
from cinesort.domain.i18n_messages import t
from cinesort.infra.tmdb_client import TmdbClient
from cinesort.ui.api._responses import err as _err_response

logger = logging.getLogger(__name__)


def get_tmdb_posters(api: Any, tmdb_ids: List[int], size: str = "w92") -> Dict[str, Any]:
    if not isinstance(tmdb_ids, list):
        return _err_response(
            t("errors.payload_tmdb_ids_invalid"), category="validation", level="info", log_module=__name__
        )
    try:
        ids: List[int] = []
        for item in tmdb_ids or []:
            try:
                value = int(item)
            except (ImportError, OSError, TypeError, ValueError):
                continue
            if value > 0:
                ids.append(value)
        ids = sorted(set(ids))[:20]
        if not ids:
            return {"ok": True, "posters": {}}

        settings = api.settings.get_settings()
        api_key = str(settings.get("tmdb_api_key") or "").strip()
        if not api_key:
            return {"ok": True, "posters": {}}

        state_dir = api._normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        # V5-03 polish v7.7.0 : propager le TTL configurable.
        try:
            cache_ttl_days = int(settings.get("tmdb_cache_ttl_days") or 30)
        except (TypeError, ValueError):
            cache_ttl_days = 30
        tmdb = TmdbClient(
            api_key=api_key,
            cache_path=state_dir / "tmdb_cache.json",
            timeout_s=float(settings.get("tmdb_timeout_s") or 10.0),
            cache_ttl_days=cache_ttl_days,
        )
        posters: Dict[str, str] = {}
        for movie_id in ids:
            url = tmdb.get_movie_poster_thumb_url(movie_id, size=size or "w92")
            if url:
                posters[str(movie_id)] = url
        tmdb.flush()
        return {"ok": True, "posters": posters}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


# Spec 06 3.4 : poster size servi a l'UI pour la recherche manuelle TMDb.
# w185 = compromis lisibilite / poids (~15 Ko/poster) pour des vignettes
# 92 px x 138 px dans le sous-modal.
_SEARCH_POSTER_SIZE = "w185"
# Hard cap defensif : on n'envoie jamais > N resultats au front pour eviter
# d'inonder le DOM si TMDb retourne 20 hits sur une requete generique.
_SEARCH_MAX_RESULTS = 10


def search_tmdb(
    api: Any,
    query: str,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """Spec 06 3.4 : recherche manuelle TMDb pour le Modal Film.

    Quand les candidats auto-detectes du film ne contiennent pas le bon
    match (titre exotique, faute de scan, etc.), l'utilisateur peut taper
    une requete libre et choisir un resultat -> appel de
    set_film_tmdb_candidate ensuite.

    Returns
    -------
    dict
        - {"ok": True, "results": [...], "query": str, "year": int|None, "count": int}
        - {"ok": False, "message": str} si validation/runtime echoue

    Chaque resultat contient :
        - tmdb_id (int)
        - title (str)
        - original_title (str|None)
        - year (int|None)
        - poster_url (str|None) - URL w185 prete a afficher
        - overview (str) - tronquee a 240 chars
        - vote_average (float|None)
        - vote_count (int|None)
        - popularity (float|None)
    """
    q = str(query or "").strip()
    if not q:
        return _err_response("Requete vide.", category="validation", level="info", log_module=__name__)
    if len(q) < 2:
        return _err_response(
            "Requete trop courte (2 caracteres minimum).",
            category="validation",
            level="info",
            log_module=__name__,
        )

    year_int: Optional[int] = None
    if year is not None and year != "":
        try:
            year_int = int(year)
            if year_int < 1870 or year_int > 2100:
                year_int = None
        except (TypeError, ValueError):
            year_int = None

    try:
        settings = api.settings.get_settings()
        api_key = str(settings.get("tmdb_api_key") or "").strip()
        if not api_key:
            return _err_response(
                "Cle TMDb non configuree (Parametres).",
                category="config",
                level="info",
                log_module=__name__,
            )

        state_dir = api._normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        try:
            cache_ttl_days = int(settings.get("tmdb_cache_ttl_days") or 30)
        except (TypeError, ValueError):
            cache_ttl_days = 30
        tmdb = TmdbClient(
            api_key=api_key,
            cache_path=state_dir / "tmdb_cache.json",
            timeout_s=float(settings.get("tmdb_timeout_s") or 10.0),
            cache_ttl_days=cache_ttl_days,
        )

        raw = tmdb.search_movie(q, year=year_int, max_results=_SEARCH_MAX_RESULTS)
        results = []
        for r in raw:
            poster_url = None
            if r.poster_path:
                path = str(r.poster_path).strip()
                if path:
                    if not path.startswith("/"):
                        path = "/" + path
                    poster_url = f"https://image.tmdb.org/t/p/{_SEARCH_POSTER_SIZE}{path}"
            overview = ""
            # Tier 2 audit : _get_movie_detail_cached peut lever (HTTP, timeout,
            # rate limit). On degrade gracieusement plutot que de crasher toute
            # la recherche pour un detail manquant.
            try:
                detail = tmdb._get_movie_detail_cached(int(r.id))
            except (OSError, AttributeError, KeyError, TypeError, ValueError) as detail_exc:
                logger.debug("search_tmdb: detail fetch failed for tmdb_id=%s: %s", r.id, detail_exc)
                detail = None
            if isinstance(detail, dict):
                overview = str(detail.get("overview") or "")
            if overview and len(overview) > 240:
                overview = overview[:237].rstrip() + "..."
            results.append(
                {
                    "tmdb_id": int(r.id),
                    "title": r.title,
                    "original_title": r.original_title,
                    "year": r.year,
                    "poster_url": poster_url,
                    "overview": overview,
                    "vote_average": r.vote_average,
                    "vote_count": r.vote_count,
                    "popularity": r.popularity,
                }
            )
        tmdb.flush()
        return {
            "ok": True,
            "results": results,
            "query": q,
            "year": year_int,
            "count": len(results),
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
