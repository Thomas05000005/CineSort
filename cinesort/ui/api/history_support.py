from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cinesort.infra.state as state
from cinesort.domain.i18n_messages import t
from cinesort.domain.run_models import RunStatus
from cinesort.ui.api._validators import requires_valid_run_id
from cinesort.ui.api._responses import err as _err_response

logger = logging.getLogger(__name__)


@requires_valid_run_id
def get_plan(api: Any, run_id: str, *, normalize_user_path: Any) -> Dict[str, Any]:
    logger.debug("api: get_plan run_id=%s", run_id)
    rs = api._get_run(run_id)
    if rs:
        if not rs.done:
            return _err_response("Plan pas pret.", category="state", level="info", log_module=__name__)
        rows = rs.rows
        if not rows:
            try:
                rows = api._load_rows_from_plan_jsonl(rs.paths)
            except (ImportError, OSError) as exc:
                return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
        return {"ok": True, "rows": api._serialize_rows_for_payload(rows)}

    found = api._find_run_row(run_id)
    if not found:
        return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__)
    row, _store = found
    status_text = str(row.get("status") or "")
    if status_text not in {RunStatus.DONE.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
        return _err_response("Plan pas pret.", category="state", level="info", log_module=__name__)
    run_paths = api._run_paths_for(
        normalize_user_path(row.get("state_dir"), api._state_dir), run_id, ensure_exists=False
    )
    try:
        rows = api._load_rows_from_plan_jsonl(run_paths)
        return {"ok": True, "rows": api._serialize_rows_for_payload(rows)}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


@requires_valid_run_id
def load_validation(api: Any, run_id: str, *, normalize_user_path: Any) -> Dict[str, Any]:
    rs = api._get_run(run_id)
    if rs:
        path = rs.paths.validation_json
        if not path.exists():
            return {"ok": True, "decisions": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                rows = rs.rows
                if not rows:
                    rows = api._load_rows_from_plan_jsonl(rs.paths)
                return {"ok": True, "decisions": api._normalize_decisions_for_rows(rows, data)}
            return {"ok": True, "decisions": {}}
        except (KeyError, OSError, PermissionError, TypeError, ValueError, json.JSONDecodeError) as exc:
            api._debug_log(
                state_dir=api._state_dir,
                run_id=run_id,
                enabled=api._debug_enabled(),
                message=f"load_validation(memory) warning run_id={run_id} error={exc}",
            )
            logger.debug("load_validation(memory) ignoree run_id=%s err=%s", run_id, exc)
            return {"ok": True, "decisions": {}}

    found = api._find_run_row(run_id)
    if not found:
        return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__)
    row, _store = found
    state_dir = normalize_user_path(row.get("state_dir"), api._state_dir)
    run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
    data = api._load_decisions_from_validation(run_paths)
    try:
        rows = api._load_rows_from_plan_jsonl(run_paths)
        return {"ok": True, "decisions": api._normalize_decisions_for_rows(rows, data)}
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        api._debug_log(
            state_dir=state_dir,
            run_id=run_id,
            enabled=api._debug_enabled(),
            message=f"load_validation(disk) warning run_id={run_id} error={exc}",
        )
        logger.debug("load_validation(disk) ignoree run_id=%s err=%s", run_id, exc)
        return {"ok": True, "decisions": {}}


@requires_valid_run_id
def cancel_run(api: Any, run_id: str) -> Dict[str, Any]:
    rs = api._get_run(run_id)
    if not rs:
        return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__, run_id=run_id)

    accepted = rs.runner.request_cancel(run_id)
    snap = rs.runner.get_status(run_id)
    return {
        "ok": bool(accepted),
        "run_id": run_id,
        "status": snap.status.value if snap else None,
        "cancel_requested": bool(snap.cancel_requested) if snap else bool(accepted),
        "done": bool(snap.done) if snap else False,
    }


def _store_for_run(api: Any, run_id: str) -> Tuple[Dict[str, Any], Any] | None:
    """Resout (row, store) pour un run_id. Wrapper trivial autour de _find_run_row."""
    found = api._find_run_row(run_id)
    if not found:
        return None
    return found[0], found[1]


@requires_valid_run_id
def get_history_stats(api: Any, run_id: str) -> Dict[str, Any]:
    """Retourne le detail complet d'un run pour l'inspecteur Historique (spec 09).

    Format attendu :
        {ok, run: {run_id, started_ts, duration_s, status, total_rows,
                   applied_rows, validated_count, rejected_count,
                   errors_count, conflicts_count, duplicates_groups,
                   score_avg, films_by_tier, apply_operations: [...]}}

    Fallback gracieux : si certaines tables/JSON ne sont pas disponibles, les
    champs concernes valent 0 / [] / None plutot que d'echouer.
    """
    logger.debug("api: get_history_stats run_id=%s", run_id)
    found = _store_for_run(api, run_id)
    if not found:
        return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__, run_id=run_id)
    row, store = found

    started_ts = float(row.get("started_ts") or row.get("created_ts") or 0.0)
    ended_ts = float(row.get("ended_ts") or 0.0)
    duration_s = round(ended_ts - started_ts, 1) if (started_ts and ended_ts) else 0.0
    status = str(row.get("status") or "PENDING")

    # stats_json contient le snapshot fin de run (planned_rows, applied_count, ...).
    stats_obj: Dict[str, Any] = {}
    raw_stats = row.get("stats_json")
    if isinstance(raw_stats, str) and raw_stats:
        try:
            parsed = json.loads(raw_stats)
            if isinstance(parsed, dict):
                stats_obj = parsed
        except (ValueError, json.JSONDecodeError) as exc:
            logger.debug("get_history_stats: stats_json invalide run_id=%s err=%s", run_id, exc)

    total_rows = int(row.get("total") or stats_obj.get("planned_rows", 0) or 0)
    applied_rows = int(stats_obj.get("applied_count") or 0)

    # Quality reports : count + tier distribution + score moyen.
    validated_count = 0
    rejected_count = 0
    score_avg: float | None = None
    films_by_tier: Dict[str, int] = {}
    try:
        quality_reports = store.quality.list_quality_reports(run_id=run_id) if store else []
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("get_history_stats: list_quality_reports err run_id=%s err=%s", run_id, exc)
        quality_reports = []
    if quality_reports:
        scores: List[float] = []
        for rep in quality_reports:
            tier = str(rep.get("tier") or "").strip().lower()
            if tier:
                films_by_tier[tier] = films_by_tier.get(tier, 0) + 1
            score = rep.get("score")
            if score is not None:
                with contextlib.suppress(TypeError, ValueError):
                    scores.append(float(score))
            # "reject" tier = rejected, anything else with score > 0 = validated.
            if tier == "reject":
                rejected_count += 1
            elif tier:
                validated_count += 1
        if scores:
            score_avg = round(sum(scores) / len(scores), 1)

    # Errors associes au run.
    errors_count = 0
    try:
        errs = store.run.list_errors(run_id) if store else []
        errors_count = len(errs) if errs else 0
    except (OSError, AttributeError, TypeError) as exc:
        logger.debug("get_history_stats: list_errors err run_id=%s err=%s", run_id, exc)

    # Conflicts (anomalies severity != info) si presents dans stats_obj, sinon 0.
    conflicts_count = int(stats_obj.get("conflicts_count") or stats_obj.get("anomalies_total") or 0)

    # Duplicates groups : on lit depuis stats_obj si dispo, sinon 0.
    duplicates_groups = int(stats_obj.get("duplicates_groups") or 0)

    # Apply operations : derniere batch reel (non dry-run) DONE.
    apply_operations: List[Dict[str, Any]] = []
    try:
        if store:
            last_batch = store.apply.get_last_reversible_apply_batch(run_id)
            if last_batch:
                ops = store.apply.list_apply_operations(batch_id=last_batch.get("batch_id"))
                apply_operations = [
                    {
                        "op_index": int(op.get("op_index") or 0),
                        "op_type": str(op.get("op_type") or ""),
                        "src_path": str(op.get("src_path") or ""),
                        "dst_path": str(op.get("dst_path") or ""),
                        "reversible": bool(int(op.get("reversible") or 0)),
                        "undo_status": str(op.get("undo_status") or "PENDING"),
                    }
                    for op in ops
                ]
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.debug("get_history_stats: apply_operations err run_id=%s err=%s", run_id, exc)

    return {
        "ok": True,
        "run": {
            "run_id": run_id,
            "started_ts": started_ts,
            "ended_ts": ended_ts,
            "duration_s": duration_s,
            "status": status,
            "total_rows": total_rows,
            "applied_rows": applied_rows,
            "validated_count": validated_count,
            "rejected_count": rejected_count,
            "errors_count": errors_count,
            "conflicts_count": conflicts_count,
            "duplicates_groups": duplicates_groups,
            "score_avg": score_avg,
            "films_by_tier": films_by_tier,
            "apply_operations": apply_operations,
        },
    }


@requires_valid_run_id
def delete_run(api: Any, run_id: str) -> Dict[str, Any]:
    """Supprime un run de l'historique (DB seulement, pas les fichiers video).

    Cf spec 09 §4 : action dangereuse. Le frontend a deja affiche une modale
    de confirmation avant d'appeler cet endpoint.

    Cascade :
    - runs (1 row)
    - errors, quality_reports, anomalies (FK CASCADE)
    - perceptual_reports, apply_batches + apply_operations (cascade manuelle)

    Les fichiers d'etat sur disque (plan.jsonl, validation.json, ui_log.txt)
    NE sont PAS touches — ils seront elimines a la rotation par retention.
    """
    logger.debug("api: delete_run run_id=%s", run_id)
    found = _store_for_run(api, run_id)
    if not found:
        return _err_response("Run introuvable.", category="resource", level="info", log_module=__name__, run_id=run_id)
    _row, store = found
    try:
        deleted = store.run.delete_run(run_id)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        return _err_response(
            t("errors.run_deletion_failed", detail=str(exc)),
            category="runtime",
            level="error",
            log_module=__name__,
            run_id=run_id,
        )

    # Purge aussi le RunState en memoire si present (sinon on garde une coquille
    # vide qui pointe vers une row supprimee).
    try:
        with api._runs_lock:
            api._runs.pop(run_id, None)
    except (AttributeError, KeyError) as exc:
        logger.debug("delete_run: purge runs memoire ignoree run_id=%s err=%s", run_id, exc)

    logger.info("delete_run: run_id=%s deleted_records=%d", run_id, deleted)
    return {"ok": True, "run_id": run_id, "deleted_records": int(deleted)}


def cleanup_old_runs(api: Any, retention_days: int = 90) -> Dict[str, Any]:
    """Supprime tous les runs dont la date la plus recente est > N jours.

    Iteration sur tous les stores actifs (multi state_dir). Retourne le
    nombre total de runs supprimes + la liste des run_ids.

    Cette fonction est appelable :
    - Manuellement via l'API (debug / forcer la purge)
    - Automatiquement au boot par le cron retention_cleanup (cf
      cinesort.app.retention_cleanup.start_retention_cron)
    """
    try:
        days = max(1, int(retention_days or 0))
    except (TypeError, ValueError):
        days = 90
    cutoff_ts = time.time() - (days * 86400.0)

    deleted_ids: List[str] = []
    # Iteration sur tous les stores connus (multi state_dir, cas tests + LAN).
    try:
        with api._runs_lock:
            stores = [store for store, _runner in api._infra_by_state_dir.values()]
    except AttributeError:
        stores = []
    # S'assurer que le store par defaut est inclus meme si pas encore initialise.
    try:
        default_store, _runner = api._get_or_create_infra(api._state_dir)
        if default_store not in stores:
            stores.append(default_store)
    except (AttributeError, OSError, RuntimeError) as exc:
        logger.debug("cleanup_old_runs: default store lookup err: %s", exc)

    for store in stores:
        try:
            run_ids = store.run.list_runs_older_than(cutoff_ts=cutoff_ts)
        except (OSError, AttributeError, TypeError, ValueError) as exc:
            logger.warning("cleanup_old_runs: list_runs_older_than err: %s", exc)
            continue
        for rid in run_ids:
            try:
                store.run.delete_run(rid)
                deleted_ids.append(rid)
            except (OSError, AttributeError, TypeError, ValueError) as exc:
                logger.warning("cleanup_old_runs: delete_run err run_id=%s err=%s", rid, exc)

    logger.info("cleanup_old_runs: deleted %d runs older than %d days", len(deleted_ids), days)
    return {
        "ok": True,
        "deleted_count": len(deleted_ids),
        "deleted_run_ids": deleted_ids,
        "retention_days": days,
    }


def open_path(api: Any, path: str, *, default_root: str, normalize_user_path: Any) -> Dict[str, Any]:
    try:
        raw_path = str(path or "").strip()
        if not raw_path:
            return _err_response("Chemin vide.", category="validation", level="info", log_module=__name__)

        candidate = Path(raw_path)
        if not candidate.exists():
            return _err_response("Chemin introuvable.", category="resource", level="warning", log_module=__name__)

        settings = api.settings.get_settings()
        root_raw = str(settings.get("root") or "").strip()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())

        resolved_path = candidate.resolve()
        open_target = candidate
        resolved_to_check = resolved_path
        if resolved_path.is_file():
            open_target = candidate.parent
            resolved_to_check = resolved_path.parent
        elif not resolved_path.is_dir():
            return _err_response(
                "Chemin invalide (ni fichier ni dossier).", category="validation", level="warning", log_module=__name__
            )

        allowed = False
        allowed_bases: List[Path] = [state_dir]
        if root_raw:
            allowed_bases.append(normalize_user_path(root_raw, Path(default_root)))

        for base in allowed_bases:
            try:
                resolved_to_check.relative_to(base.resolve())
                allowed = True
                break
            except (OSError, ValueError):
                continue
        if not allowed:
            return _err_response("Chemin non autorise.", category="permission", level="warning", log_module=__name__)

        os.startfile(str(open_target))  # type: ignore[attr-defined]
        return {"ok": True}
    except (OSError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
