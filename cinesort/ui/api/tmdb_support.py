from __future__ import annotations

from typing import Any, Dict, List

import cinesort.infra.state as state
from cinesort.domain.i18n_messages import t
from cinesort.infra.tmdb_client import TmdbClient


def get_tmdb_posters(api: Any, tmdb_ids: List[int], size: str = "w92") -> Dict[str, Any]:
    if not isinstance(tmdb_ids, list):
        return {"ok": False, "message": t("errors.payload_tmdb_ids_invalid")}
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
        return {"ok": False, "message": str(exc)}
