"""Endpoints historique par film — item 9.13.

Expose get_film_history et list_films_with_history via l'API pywebview/REST.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import cinesort.infra.state as state
from cinesort.domain.film_history import get_film_timeline, list_films_overview
from cinesort.ui.api.settings_support import normalize_user_path
from cinesort.ui.api._responses import err as _err_response


def get_film_history(api: Any, film_id: str) -> Dict[str, Any]:
    """Retourne la timeline complete d'un film a travers tous les runs."""
    fid = str(film_id or "").strip()
    if not fid:
        return _err_response("film_id requis.", category="validation", level="info", log_module=__name__)

    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _runner = api._get_or_create_infra(state_dir)
        timeline = get_film_timeline(fid, Path(state_dir), store)
        return {"ok": True, **timeline}
    except (OSError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


def list_films_with_history(api: Any, limit: int = 50) -> Dict[str, Any]:
    """Retourne la liste des films du dernier run avec un resume."""
    lim = max(1, min(200, int(limit or 50)))
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _runner = api._get_or_create_infra(state_dir)
        films = list_films_overview(Path(state_dir), store, limit=lim)
        return {"ok": True, "films": films, "count": len(films)}
    except (OSError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
