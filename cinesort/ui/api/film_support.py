"""§v7.6.0 Vague 4 — Film detail standalone page backend.

Endpoint unique : get_film_full(run_id, row_id)

Consolide en 1 seul appel :
    - metadata PlanRow (titre, annee, source path, collection, edition, ...)
    - probe technique (codec, resolution, HDR, audio tracks, subs)
    - perceptual result complet (V1 + V2 si dispo)
    - history timeline (via film_history_support)
    - poster TMDb URL
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from cinesort.infra import state
from cinesort.ui.api import film_history_support
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)


def _resolve_run_id(api: Any, run_id: Optional[str]) -> Optional[str]:
    if run_id:
        return str(run_id)
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
        runs = store.list_runs(limit=1)
        if runs:
            return str(runs[0].get("run_id") or "")
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        pass
    return None


def _find_plan_row(api: Any, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
    try:
        plan = api.run.get_plan(run_id)
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        return None
    if not plan or not plan.get("ok"):
        return None
    for r in plan.get("rows") or []:
        if str(r.get("row_id") or "") == str(row_id):
            return r
    return None


def _fetch_poster_url(api: Any, tmdb_id: int) -> Optional[str]:
    if not tmdb_id or int(tmdb_id) <= 0:
        return None
    try:
        result = api.integrations.get_tmdb_posters([int(tmdb_id)], "w342")
        if result and result.get("ok"):
            return result.get("posters", {}).get(str(int(tmdb_id)))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("poster fetch error: %s", exc)
    return None


def _film_identity_key(row: Dict[str, Any]) -> str:
    """Reproduit film_identity_key depuis film_history module (tmdb ou title+year)."""
    ed = str(row.get("edition") or "").strip().lower()
    ed_suffix = ("|" + ed) if ed else ""
    candidates = row.get("candidates") or []
    for c in candidates:
        tid = int(c.get("tmdb_id") or 0)
        if tid > 0:
            return f"tmdb:{tid}{ed_suffix}"
    title = str(row.get("proposed_title") or "").strip().lower()
    year = int(row.get("proposed_year") or 0)
    return f"title:{title}|{year}{ed_suffix}"


def get_film_full(api: Any, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
    """Retourne la totalite des informations d'un film pour la page standalone.

    Response :
      {
        ok: bool,
        run_id: str,
        row_id: str,
        row: {...},                // PlanRow complet
        probe: {...} | None,       // normalized probe (video+audio+subs)
        perceptual: {...} | None,  // PerceptualResult incl. global_score_v2_payload
        history: [...] | [],       // timeline events
        poster_url: str | None,
        tmdb_id: int,
      }
    """
    resolved_rid = _resolve_run_id(api, run_id)
    if not resolved_rid:
        return {"ok": False, "message": "Aucun run disponible."}

    row = _find_plan_row(api, resolved_rid, row_id)
    if not row:
        return {"ok": False, "message": f"Film introuvable (row_id={row_id})."}

    # Probe (via quality_reports store)
    probe_dict = None
    perceptual_dict = None
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)

        # Perceptual
        try:
            perc = store.get_perceptual_report(run_id=resolved_rid, row_id=str(row_id))
            if perc:
                perceptual_dict = perc
                # Attach global_score_v2 payload pour le frontend
                gv2_payload = perc.get("global_score_v2_payload")
                if gv2_payload:
                    perceptual_dict["global_score_v2"] = gv2_payload
        except (AttributeError, OSError, TypeError, ValueError):
            pass

        # Probe via quality_reports (metrics)
        try:
            quality = store.get_quality_report(run_id=resolved_rid, row_id=str(row_id))
            if quality and quality.get("metrics"):
                probe_dict = quality.get("metrics")
        except (AttributeError, OSError, TypeError, ValueError):
            pass
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("get_film_full infra error: %s", exc)

    # History timeline
    history = []
    try:
        fid = _film_identity_key(row)
        h_res = film_history_support.get_film_history(api, fid)
        if h_res and h_res.get("ok"):
            history = h_res.get("history") or []
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("history fetch error: %s", exc)

    # TMDb poster
    tmdb_id = 0
    candidates = row.get("candidates") or []
    if candidates:
        tmdb_id = int(candidates[0].get("tmdb_id") or 0)
    poster_url = _fetch_poster_url(api, tmdb_id) if tmdb_id > 0 else None

    return {
        "ok": True,
        "run_id": resolved_rid,
        "row_id": str(row_id),
        "row": row,
        "probe": probe_dict,
        "perceptual": perceptual_dict,
        "history": history,
        "poster_url": poster_url,
        "tmdb_id": tmdb_id,
    }
