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

from cinesort.domain.film_history import identity_key_from_dict
from cinesort.infra import state
from cinesort.ui.api import film_history_support
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api.settings_support import normalize_user_path

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


def _resolve_chosen_tmdb_id(row: Dict[str, Any], candidates: List[Dict[str, Any]]) -> int:
    """Fix audit 2026-05-25 (v1.5.4) Vague I : resolution canonique du candidat
    "chosen" pour le modal film.

    Priorite (high -> low) :
      1. row.chosen_tmdb_id (override utilisateur via set_film_tmdb_candidate)
      2. row.tmdb_id (TMDb match auto principal)
      3. candidates[0].tmdb_id (top match par defaut)
    Retourne 0 si aucun candidate exploitable.
    """
    for source_key in ("chosen_tmdb_id", "tmdb_id"):
        try:
            raw = row.get(source_key) if isinstance(row, dict) else None
        except AttributeError:
            raw = None
        if raw is None:
            continue
        try:
            val = int(raw)
        except (TypeError, ValueError):
            continue
        if val > 0:
            return val
    if candidates:
        try:
            return int(candidates[0].get("tmdb_id") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


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
        fid = identity_key_from_dict(row)
        h_res = film_history_support.get_film_history(api, fid)
        if h_res and h_res.get("ok"):
            # AUDIT 2026-06-10 (REAL 2/2) : get_film_history retourne la cle
            # "events" (domain/film_history.py:232), pas "history" -> la timeline
            # du Modal Film etait systematiquement vide.
            history = h_res.get("events") or []
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

    # Fix R5 bug 2 (verify-r5) : resoudre le chosen tmdb_id AVANT de fetch
    # poster + extras, sinon le Modal Film re-render avec les infos du candidat
    # auto (candidates[0]) au lieu de celui choisi par l'utilisateur via
    # set_film_tmdb_candidate. Le helper _resolve_chosen_tmdb_id applique la
    # priorite canonique : row.chosen_tmdb_id (override) > row.tmdb_id (auto)
    # > candidates[0].tmdb_id (fallback top match).
    candidates = row.get("candidates") or []
    chosen_tmdb_id = _resolve_chosen_tmdb_id(row, candidates)
    tmdb_id = int(chosen_tmdb_id or 0)

    # TMDb poster (taille w500 selon spec 06 §3.1) -> utilise le chosen tmdb_id
    poster_url = _fetch_poster_url(api, tmdb_id, size="w500") if tmdb_id > 0 else None

    # Fix audit 2026-05-25 (v1.5.4) Vague I : garantir UN SEUL candidat marque
    # comme "chosen" pour eviter le bug du double "Choisi" dans le modal film.
    # Cause racine : le frontend utilisait `candidates[0].tmdb_id` comme fallback
    # alors que l'override TMDb stocke peut ne pas etre le premier de la liste.
    # Si plusieurs candidats partageaient le meme tmdb_id (cas degrade), les
    # deux etaient highlightes. On expose desormais un seul `chosen_tmdb_id`
    # canonique cote backend, et on annote chaque candidate avec `chosen: bool`
    # (un seul True garanti). Log warning si etat incoherent detecte.
    if isinstance(row, dict) and chosen_tmdb_id:
        row = dict(row)  # copie defensive (deja peut-etre copiee plus haut)
        row["chosen_tmdb_id"] = int(chosen_tmdb_id)
        # Annoter les candidates : marquer le PREMIER candidat dont tmdb_id
        # matche chosen_tmdb_id (et un seul). Les doublons tmdb_id eventuels
        # voient leur chosen=False -> evite le double "Choisi" cote UI.
        new_candidates: List[Dict[str, Any]] = []
        already_marked = False
        multiple_match_count = 0
        for cand in candidates:
            try:
                cand_tid = int(cand.get("tmdb_id") or 0)
            except (TypeError, ValueError):
                cand_tid = 0
            is_chosen = False
            if not already_marked and cand_tid > 0 and cand_tid == int(chosen_tmdb_id):
                is_chosen = True
                already_marked = True
            elif already_marked and cand_tid > 0 and cand_tid == int(chosen_tmdb_id):
                multiple_match_count += 1
            new_cand = dict(cand)
            new_cand["chosen"] = is_chosen
            new_candidates.append(new_cand)
        if multiple_match_count > 0:
            logger.warning(
                "get_film_full: %d candidat(s) duplique(s) avec tmdb_id=%s "
                "pour row_id=%s — un seul marque chosen=True",
                multiple_match_count,
                chosen_tmdb_id,
                row_id,
            )
        row["candidates"] = new_candidates

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
