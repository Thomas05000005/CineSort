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

import contextlib
import logging
from typing import Any, Dict, List, Optional

from cinesort.infra import state
from cinesort.ui.api import film_history_support
from cinesort.ui.api.settings_support import normalize_user_path
from cinesort.ui.api._responses import err as _err_response

logger = logging.getLogger(__name__)


def _resolve_run_id(api: Any, run_id: Optional[str]) -> Optional[str]:
    if run_id:
        return str(run_id)
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
        runs = store.run.list_runs(limit=1)
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


def _fetch_poster_url(api: Any, tmdb_id: int, size: str = "w500") -> Optional[str]:
    """Spec 06 §3.1 : poster TMDb taille w500 par defaut (~200x300 affichage)."""
    if not tmdb_id or int(tmdb_id) <= 0:
        return None
    try:
        result = api.integrations.get_tmdb_posters([int(tmdb_id)], size)
        if result and result.get("ok"):
            return result.get("posters", {}).get(str(int(tmdb_id)))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("poster fetch error: %s", exc)
    return None


def _fetch_tmdb_extras(api: Any, tmdb_id: int) -> Dict[str, Any]:
    """Spec 06 §3.1 : recupere runtime (min) + director + overview via TmdbClient.

    Best-effort : retourne dict vide si TMDb pas configure ou indispo. Utilise
    le cache local TmdbClient.
    """
    out: Dict[str, Any] = {"runtime": None, "director": None, "overview": None}
    if not tmdb_id or int(tmdb_id) <= 0:
        return out
    # Import lazy : TmdbClient n'est pas necessaire si pas de cle TMDb.
    try:
        from cinesort.infra.tmdb_client import TmdbClient
    except ImportError:
        return out
    try:
        settings = api.settings.get_settings()
        api_key = str(settings.get("tmdb_api_key") or "").strip()
        if not api_key:
            return out
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        try:
            cache_ttl_days = int(settings.get("tmdb_cache_ttl_days") or 30)
        except (TypeError, ValueError):
            cache_ttl_days = 30
        client = TmdbClient(
            api_key=api_key,
            cache_path=state_dir / "tmdb_cache.json",
            timeout_s=float(settings.get("tmdb_timeout_s") or 10.0),
            cache_ttl_days=cache_ttl_days,
        )
        try:
            out["runtime"] = client.get_movie_runtime(int(tmdb_id))
        except (AttributeError, TypeError, ValueError) as exc:
            logger.debug("tmdb runtime fetch error: %s", exc)
        # Director : via _get_movie_detail_cached -> data["credits"]["crew"]
        # Le cache TmdbClient ne stocke pas le director ; on tape directement
        # le HTTP detail pour beneficier du cache local file-side.
        try:
            detail = client._get_movie_detail_cached(int(tmdb_id))
            if isinstance(detail, dict):
                # overview / director ne sont pas systematiquement caches : on
                # fait un appel direct si besoin.
                pass
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
        # Director + overview : appel HTTP frais (le cache _get_movie_detail_cached
        # ne stocke pas ces champs aujourd'hui). On utilise l'API requests
        # directement avec append_to_response=credits pour avoir crew.
        try:
            import requests as _req

            r = _req.get(
                f"https://api.themoviedb.org/3/movie/{int(tmdb_id)}",
                params={
                    "api_key": api_key,
                    "language": "fr-FR",
                    "append_to_response": "credits",
                },
                timeout=float(settings.get("tmdb_timeout_s") or 10.0),
            )
            if r.status_code == 200:
                data = r.json() or {}
                # Director : prend le premier crew member job=Director
                credits = data.get("credits") or {}
                crew = credits.get("crew") or []
                for c in crew:
                    if str(c.get("job") or "").lower() == "director":
                        out["director"] = str(c.get("name") or "").strip() or None
                        break
                out["overview"] = str(data.get("overview") or "").strip() or None
                # Runtime aussi en fallback si pas deja recupere
                if not out.get("runtime"):
                    try:
                        rt = int(data.get("runtime") or 0)
                        out["runtime"] = rt if rt > 0 else None
                    except (TypeError, ValueError):
                        pass
        except (OSError, ImportError, KeyError, TypeError, ValueError) as exc:
            logger.debug("tmdb extras http fetch error: %s", exc)
        with contextlib.suppress(OSError, AttributeError):
            client.flush()
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("_fetch_tmdb_extras error: %s", exc)
    return out


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
    # Fix audit 2026-05-25 (v1.5.3) Vague F : wrap global pour eviter HTTP 500
    # quand le run devient obsolete ou la base inaccessible. On retourne un
    # contrat JSON {ok: False, error, user_message} que le frontend peut afficher.
    try:
        return _get_film_full_impl(api, run_id, row_id)
    except Exception as exc:  # noqa: BLE001 - on doit attraper tout pour eviter HTTP 500
        logger.exception("get_film_full failed for run_id=%s row_id=%s", run_id, row_id)
        return {
            "ok": False,
            "error": "film_load_failed",
            "message": str(exc),
            "user_message": (
                "Impossible de charger ce film (run obsolete ou base inaccessible). "
                "Relance un scan ou redemarre l'app."
            ),
        }


def _get_film_full_impl(api: Any, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
    """Implementation reelle de get_film_full, sans wrap global.

    Extrait pour faciliter le wrap try/except dans get_film_full (Vague F Fix 3).
    """
    resolved_rid = _resolve_run_id(api, run_id)
    if not resolved_rid:
        return _err_response("Aucun run disponible.", category="state", level="info", log_module=__name__)

    row = _find_plan_row(api, resolved_rid, row_id)
    if not row:
        return _err_response(
            f"Film introuvable (row_id={row_id}).", category="runtime", level="error", log_module=__name__
        )

    # Probe (via quality_reports store)
    probe_dict = None
    perceptual_dict = None
    store: Any = None
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)

        # Perceptual
        try:
            perc = store.perceptual.get_perceptual_report(run_id=resolved_rid, row_id=str(row_id))
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
            quality = store.quality.get_quality_report(run_id=resolved_rid, row_id=str(row_id))
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

    # Spec 06 §3.3 : filtre des warning_flags par alertes ignorees persistees.
    # Persistance via film_modal.ignored_alerts (cf endpoint library/mark_alert_ignored).
    ignored_codes: List[str] = []
    try:
        if store is not None and hasattr(store, "film_modal"):
            ignored_codes = list(store.film_modal.list_ignored_alerts(str(row_id)))
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        logger.debug("ignored_alerts fetch error: %s", exc)
    if ignored_codes and isinstance(row, dict):
        flags = row.get("warning_flags") or []
        if isinstance(flags, list):
            row = dict(row)
            row["warning_flags"] = [f for f in flags if str(f) not in ignored_codes]
            row["_ignored_alerts"] = list(ignored_codes)

    # TMDb poster (taille w500 selon spec 06 §3.1)
    tmdb_id = 0
    candidates = row.get("candidates") or []
    if candidates:
        tmdb_id = int(candidates[0].get("tmdb_id") or 0)
    poster_url = _fetch_poster_url(api, tmdb_id, size="w500") if tmdb_id > 0 else None

    # Spec 06 §3.1 : enrichissement runtime + director + overview depuis TMDb
    extras = _fetch_tmdb_extras(api, tmdb_id) if tmdb_id > 0 else {}
    runtime = extras.get("runtime")
    director = extras.get("director")
    overview = extras.get("overview")

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
        # Spec 06 §3.1 : champs top-level pour le hero du Modal Film
        "runtime": runtime,
        "director": director,
        "overview": overview,
    }
