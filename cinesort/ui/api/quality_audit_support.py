"""Quality Audit endpoints — Vue Qualite (spec 10).

Endpoints :
    get_films_by_tier(tier, limit=8)      — top N films par tier (default Reject ascendant)
    get_history(period_days=30)           — points evolution score V2 + KPIs delta
    recompute_all_scores()                — lance recalcul background, retourne job_id
    get_recompute_job_status(job_id)      — polling status du job de recalcul

Cf docs/internal/design/refonte_2026_05_17/screens/10-qualite.md
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from cinesort.domain.conversions import to_bool
from cinesort.infra import state
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_latest_run_id(api: Any) -> Optional[str]:
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
        runs = store.run.list_runs(limit=1)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("quality_audit cannot resolve latest run: %s", exc)
        return None
    if not runs:
        return None
    return str(runs[0].get("run_id") or "") or None


def _extract_warnings_from_payload(payload: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(payload, dict):
        return []
    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        return []
    return [str(w) for w in warnings if str(w).strip()]


# ---------------------------------------------------------------------------
# Endpoint 1 : get_films_by_tier
# ---------------------------------------------------------------------------


_VALID_TIERS = {"platinum", "gold", "silver", "bronze", "reject"}
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 8


def get_films_by_tier(api: Any, tier: str, limit: int = _DEFAULT_LIMIT) -> Dict[str, Any]:
    """Liste les films d'un tier V2 (default top 8 pires Reject par score V2 asc).

    Args:
        tier: "platinum" | "gold" | "silver" | "bronze" | "reject"
        limit: nombre max de films (default 8, cap 100)

    Returns:
        {
            "ok": True,
            "run_id": "...",
            "tier": "reject",
            "films": [
                {row_id, title, year, score_v2, tier, poster_url, warnings: [...]},
                ...
            ],
            "total": N
        }
    """
    # Fix audit 2026-05-25 (v1.5.3) Vague G : wrap global pour eviter HTTP 500
    # sur cet endpoint d'audit Qualite.
    try:
        return _get_films_by_tier_impl(api, tier, limit)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("get_films_by_tier failed for tier=%s limit=%s", tier, limit)
        return {
            "ok": False,
            "error": "films_by_tier_failed",
            "message": str(exc),
            "user_message": "Impossible de recuperer la liste des films par tier.",
        }


def _get_films_by_tier_impl(api: Any, tier: str, limit: int = _DEFAULT_LIMIT) -> Dict[str, Any]:
    """Implementation reelle de get_films_by_tier, sans wrap global (Vague G)."""
    tier_norm = str(tier or "").strip().lower()
    if tier_norm not in _VALID_TIERS:
        return _err_response(
            f"Tier invalide. Valeurs : {sorted(_VALID_TIERS)}.",
            category="validation",
            level="info",
            log_module=__name__,
        )

    try:
        lim = int(limit) if limit else _DEFAULT_LIMIT
    except (TypeError, ValueError):
        lim = _DEFAULT_LIMIT
    lim = max(1, min(_MAX_LIMIT, lim))

    resolved_rid = _resolve_latest_run_id(api)
    if not resolved_rid:
        return {"ok": True, "run_id": None, "tier": tier_norm, "films": [], "total": 0}

    try:
        # Import paresseux car library_support importe deja state/settings
        from cinesort.ui.api import library_support

        rows = library_support._build_library_rows(api, resolved_rid)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("get_films_by_tier cannot build rows for %s: %s", resolved_rid, exc)
        return _err_response(
            f"Impossible de charger la bibliotheque: {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    # Filtrer par tier
    filtered = [r for r in rows if str(r.get("tier_v2") or "").lower() == tier_norm]

    # Tri : Reject = score ASC (les pires d'abord), autres = score DESC (les meilleurs)
    if tier_norm == "reject":
        filtered.sort(key=lambda r: r.get("score_v2") if r.get("score_v2") is not None else 0)
    else:
        filtered.sort(key=lambda r: -(r.get("score_v2") if r.get("score_v2") is not None else 0))

    films_out: List[Dict[str, Any]] = []
    for r in filtered[:lim]:
        # Iter13 etape 4 (2026-06-10) : propager probe_quality / quality_unavailable
        # depuis library_support pour que l'UI Qualite distingue un score reel
        # mesure d'un score base sur le nom seul (probe FAILED apres retry+breaker).
        # Sans cette propagation, get_films_by_tier renvoyait un score numerique
        # nu - l'UI affichait un score Silver-cap comme si c'etait une mesure
        # fiable (degradation silencieuse, contraire a l'acquis iter4).
        films_out.append(
            {
                "row_id": str(r.get("row_id") or ""),
                "title": str(r.get("title") or ""),
                "year": int(r.get("year") or 0),
                "score_v2": r.get("score_v2"),
                "tier": str(r.get("tier_v2") or "unknown").lower(),
                "poster_url": r.get("poster_url"),
                "warnings": list(r.get("warnings") or []),
                "probe_quality": str(r.get("probe_quality") or "UNKNOWN").upper(),
                "quality_unavailable": bool(r.get("quality_unavailable")),
            }
        )

    return {
        "ok": True,
        "run_id": resolved_rid,
        "tier": tier_norm,
        "films": films_out,
        "total": len(filtered),
    }


# ---------------------------------------------------------------------------
# Endpoint 4 : get_history
# ---------------------------------------------------------------------------


def get_history(api: Any, period_days: int = 30) -> Dict[str, Any]:
    """KPIs evolution sur N derniers jours.

    Args:
        period_days: 7 / 30 / 90 / 0 (=all). Default 30.

    Returns:
        {
            "ok": True,
            "period_days": 30,
            "points": [
                {date, avg_score, count_films, count_reject, count_subs_missing},
                ...
            ],
            "delta_score": float,
            "delta_films": int,
            "delta_reject": int,
        }
    """
    try:
        period = int(period_days) if period_days is not None else 30
    except (TypeError, ValueError):
        period = 30
    # 0 = all (cap raisonnable a 365 j pour eviter scan trop large)
    if period <= 0:
        period = 365
    period = max(1, min(365, period))

    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("get_history cannot init store: %s", exc)
        return _err_response(
            f"Impossible d'initialiser le store: {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    now = time.time()
    since = now - period * 86400.0

    # Recuperer les data raw du repository perceptual
    try:
        raw_trend = store.perceptual.get_global_score_v2_trend(since_ts=since, until_ts=now)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("get_history trend error: %s", exc)
        raw_trend = []

    # Index by date
    by_date: Dict[str, Dict[str, Any]] = {r["date"]: r for r in raw_trend if isinstance(r, dict)}

    # Generer N+1 points consecutifs (du plus ancien au plus recent)
    points: List[Dict[str, Any]] = []
    for i in range(period, -1, -1):
        ts = now - i * 86400.0
        date_str = time.strftime("%Y-%m-%d", time.localtime(ts))
        pt = by_date.get(date_str)
        points.append(
            {
                "date": date_str,
                "avg_score": pt["avg_score"] if pt else None,
                "count_films": int(pt["count"]) if pt else 0,
                # Reject + subs_missing : calcul approximatif (full scan trop lourd
                # ici, on les expose en None pour que l'UI fallback sur les KPIs
                # delta calcules ci-dessous via les agregats DB).
                "count_reject": None,
                "count_subs_missing": None,
            }
        )

    # Calcul des deltas (recent vs older half)
    delta_score = 0.0
    delta_films = 0
    delta_reject = 0

    if len(points) >= 2:
        half = len(points) // 2
        older = [p for p in points[:half] if p.get("avg_score") is not None]
        recent = [p for p in points[half:] if p.get("avg_score") is not None]
        if older and recent:
            avg_older = sum(float(p["avg_score"]) for p in older) / len(older)
            avg_recent = sum(float(p["avg_score"]) for p in recent) / len(recent)
            delta_score = round(avg_recent - avg_older, 1)
        delta_films = sum(int(p.get("count_films") or 0) for p in recent) - sum(
            int(p.get("count_films") or 0) for p in older
        )

    # Reject count : compter les films Reject ajoutes pendant la periode
    try:
        reject_recent = store.perceptual.count_v2_tier_since(tier="reject", since_ts=now - (period // 2) * 86400.0)
        reject_older = store.perceptual.count_v2_tier_since(tier="reject", since_ts=since) - reject_recent
        delta_reject = reject_recent - reject_older
    except (OSError, AttributeError, TypeError, ValueError):
        delta_reject = 0

    return {
        "ok": True,
        "period_days": period,
        "points": points,
        "delta_score": delta_score,
        "delta_films": int(delta_films),
        "delta_reject": int(delta_reject),
    }


# ---------------------------------------------------------------------------
# Endpoint 5 : recompute_all_scores (background job)
# ---------------------------------------------------------------------------

# Registry global des jobs de recalcul. Cle = job_id, valeur = dict avec :
#   status: "pending" | "running" | "done" | "failed" | "cancelled"
#   progress: int (films traites)
#   total: int (films a traiter)
#   started_ts, ended_ts, error
_RECOMPUTE_JOBS: Dict[str, Dict[str, Any]] = {}
_RECOMPUTE_JOBS_LOCK = threading.RLock()
_RECOMPUTE_JOBS_MAX_KEEP = 5  # garde les 5 derniers jobs en memoire


def _cleanup_old_jobs() -> None:
    """Garde les N derniers jobs (FIFO sur started_ts)."""
    with _RECOMPUTE_JOBS_LOCK:
        if len(_RECOMPUTE_JOBS) <= _RECOMPUTE_JOBS_MAX_KEEP:
            return
        ordered = sorted(_RECOMPUTE_JOBS.items(), key=lambda kv: float(kv[1].get("started_ts") or 0.0))
        to_drop = ordered[: max(0, len(ordered) - _RECOMPUTE_JOBS_MAX_KEEP)]
        for jid, _meta in to_drop:
            _RECOMPUTE_JOBS.pop(jid, None)


def _set_job_status(job_id: str, **changes: Any) -> None:
    with _RECOMPUTE_JOBS_LOCK:
        meta = _RECOMPUTE_JOBS.get(job_id)
        if not meta:
            return
        meta.update(changes)


def _recompute_worker(api: Any, job_id: str, run_id: str, row_ids: List[str]) -> None:
    """Thread worker qui rescore tous les films d'un run via la facade quality."""
    total = len(row_ids)
    _set_job_status(job_id, status="running", started_ts=time.time(), progress=0, total=total)

    processed = 0
    errors = 0
    try:
        # Reuse_existing=False pour forcer le re-calcul depuis le profil actuel.
        for rid in row_ids:
            try:
                res = api.quality.get_quality_report(run_id, rid, {"reuse_existing": False})
                # AUDIT 2026-06-14 (R7-11) : get_quality_report renvoie {ok:False}
                # sans lever (probe ffprobe absent, media deplace) -> avant,
                # errors restait 0 et le toast vert annoncait "N/N re-calcules"
                # meme quand tout echouait. On compte les echecs metier.
                if isinstance(res, dict) and res.get("ok") is False:
                    errors += 1
            # except Exception large : on continue en cas d'erreur sur un film
            except (OSError, KeyError, TypeError, ValueError) as exc:
                logger.debug("recompute_worker error row_id=%s: %s", rid, exc)
                errors += 1
            processed += 1
            if processed % 10 == 0 or processed == total:
                _set_job_status(job_id, progress=processed, errors=errors)

        # ITER8 cluster settings — fix `perceptual_auto_on_quality` no-op silencieux.
        # Toggle UI Parametres > "Analyse perceptuelle apres recompute qualite"
        # etait sauvegarde par _save_section_perceptual (L1523) et expose par
        # _build_settings_dict (perceptual_support L1433 alias `auto_on_quality`)
        # mais ZERO lecture dans le chemin reel (_recompute_worker / run_flow_support
        # apres recompute_all_scores). Pattern : meme contrat que perceptual_auto_on_scan
        # fixe en 12b3721 (background, best-effort, log WARN bruyant si echec
        # d'approvisionnement, silencieux si toggle=OFF). Lance analyze_perceptual_batch
        # sur les row_ids du run. Pre-requis `perceptual_enabled` (false par defaut)
        # car le moteur n'est pas operationnel sans la cle activee : WARN explicite
        # si l'utilisateur a active l'auto sans avoir active le moteur, pour honorer
        # le contrat ii.b (echec d'approvisionnement bruyant).
        try:
            # AUDIT 2026-06-11 (R3) : get_settings() retourne un dict PLAT (pas de
            # cle "settings", cf call sites L35/L208). Le .get("settings") rendait
            # settings={} toujours -> perceptual_enabled lu False -> l'analyse
            # perceptuelle auto post-recompute (fix ITER8) ne se lancait JAMAIS.
            settings = api.settings.get_settings() or {}
            auto_perc_q = to_bool(settings.get("perceptual_auto_on_quality"), True)
            if auto_perc_q and row_ids:
                perc_enabled = to_bool(settings.get("perceptual_enabled"), False)
                if not perc_enabled:
                    logger.warning(
                        "perceptual_auto_on_quality active mais perceptual_enabled=False "
                        "-> analyse perceptuelle skip (active aussi le moteur)."
                    )
                else:
                    from cinesort.ui.api import perceptual_support

                    logger.info(
                        "recompute_worker launching auto perceptual batch (%d films)",
                        len(row_ids),
                    )
                    perc_result = perceptual_support.analyze_perceptual_batch(
                        api, run_id, row_ids, options=None
                    )
                    if isinstance(perc_result, dict) and perc_result.get("ok"):
                        logger.info(
                            "recompute_worker auto perceptual started success_count=%s",
                            perc_result.get("success_count"),
                        )
                    else:
                        logger.debug("recompute_worker auto perceptual skipped: %s", perc_result)
        except (ImportError, KeyError, OSError, TypeError, ValueError) as exc:
            logger.warning("recompute_worker auto perceptual warning: %s", exc)

        _set_job_status(
            job_id,
            status="done",
            progress=processed,
            errors=errors,
            ended_ts=time.time(),
        )
    # except Exception intentionnel : boundary top-level worker thread
    except Exception as exc:  # noqa: BLE001
        logger.warning("recompute_worker fatal: %s", exc)
        _set_job_status(
            job_id,
            status="failed",
            error=str(exc),
            progress=processed,
            errors=errors,
            ended_ts=time.time(),
        )


def recompute_all_scores(api: Any) -> Dict[str, Any]:
    """Lance le recalcul background du Score V2 pour tous les films du dernier run.

    Returns:
        {"ok": True, "job_id": "...", "total": N, "run_id": "..."}
    """
    # Fix audit 2026-05-25 (v1.5.3) Vague G : wrap global pour eviter HTTP 500
    # sur ce trigger background. La fonction lance un thread Daemon donc on
    # protege la phase synchrone (validation + insertion job registry).
    try:
        return _recompute_all_scores_impl(api)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("recompute_all_scores failed")
        return {
            "ok": False,
            "error": "recompute_scores_failed",
            "message": str(exc),
            "user_message": (
                "Impossible de recalculer les scores. Reessaie ou redemarre."
            ),
        }


def _recompute_all_scores_impl(api: Any) -> Dict[str, Any]:
    """Implementation reelle de recompute_all_scores, sans wrap global (Vague G)."""
    resolved_rid = _resolve_latest_run_id(api)
    if not resolved_rid:
        return _err_response(
            "Aucun run disponible pour le recalcul.",
            category="state",
            level="info",
            log_module=__name__,
        )

    # Charger les row_ids du run (depuis le plan)
    row_ids: List[str] = []
    try:
        plan = api.run.get_plan(resolved_rid)
        if plan and plan.get("ok"):
            rows = plan.get("rows") or []
            row_ids = [str(r.get("row_id") or "") for r in rows if str(r.get("row_id") or "").strip()]
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("recompute_all_scores cannot load plan: %s", exc)
        return _err_response(
            f"Impossible de charger le plan: {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    if not row_ids:
        return _err_response(
            "Aucun film a recalculer dans le run actuel.",
            category="state",
            level="info",
            log_module=__name__,
        )

    job_id = f"recompute_{uuid.uuid4().hex[:12]}"
    now = time.time()
    with _RECOMPUTE_JOBS_LOCK:
        _RECOMPUTE_JOBS[job_id] = {
            "job_id": job_id,
            "run_id": resolved_rid,
            "status": "pending",
            "progress": 0,
            "total": len(row_ids),
            "errors": 0,
            "started_ts": now,
            "ended_ts": None,
            "error": None,
        }
        _cleanup_old_jobs()

    worker = threading.Thread(
        target=_recompute_worker,
        args=(api, job_id, resolved_rid, row_ids),
        daemon=True,
        name=f"recompute_{job_id}",
    )
    worker.start()

    return {
        "ok": True,
        "job_id": job_id,
        "total": len(row_ids),
        "run_id": resolved_rid,
    }


def get_recompute_job_status(api: Any, job_id: str) -> Dict[str, Any]:  # noqa: ARG001
    """Polling du status d'un job de recalcul lance par recompute_all_scores.

    Args:
        api: instance CineSortApi (non utilise — registry global thread-safe)
        job_id: identifiant retourne par recompute_all_scores()

    Returns:
        {"ok": True, "job_id": ..., "status": ..., "progress": int, "total": int,
         "errors": int, "started_ts": float, "ended_ts": float|None, "error": str|None}
    """
    jid = str(job_id or "").strip()
    if not jid:
        return _err_response("job_id requis.", category="validation", level="info", log_module=__name__)

    with _RECOMPUTE_JOBS_LOCK:
        meta = _RECOMPUTE_JOBS.get(jid)
        if not meta:
            return _err_response(f"Job introuvable: {jid}", category="resource", level="info", log_module=__name__)
        # Snapshot pour eviter exposer la reference interne
        return {"ok": True, **dict(meta)}
