from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cinesort.domain.conversions import to_bool
from cinesort.domain.i18n_messages import t

logger = logging.getLogger(__name__)


def _validate_inputs(api: Any, run_id: str, row_ids: Any) -> Optional[Dict[str, Any]]:
    if not run_id:
        return {"ok": False, "message": t("errors.run_id_required")}
    if not api._is_valid_run_id(run_id):
        return {"ok": False, "message": t("errors.run_invalid_id")}
    if not isinstance(row_ids, list):
        return {"ok": False, "message": t("errors.payload_row_ids_invalid")}
    return None


def _parse_options(options: Optional[Dict[str, Any]]) -> Tuple[bool, bool, str]:
    opts = options if isinstance(options, dict) else {}
    reuse_existing = to_bool(opts.get("reuse_existing"), True)
    continue_on_error = to_bool(opts.get("continue_on_error"), True)
    scope = str(opts.get("scope") or "").strip().lower()
    return reuse_existing, continue_on_error, scope


def _clean_row_ids(row_ids: List[Any]) -> List[str]:
    cleaned: List[str] = []
    for rid in row_ids:
        val = str(rid or "").strip()
        if val:
            cleaned.append(val)
    return list(dict.fromkeys(cleaned))


def _extract_validated_ids(val_payload: Any) -> Optional[set]:
    if not isinstance(val_payload, dict) or not val_payload.get("ok"):
        return None
    decisions = val_payload.get("decisions") or {}
    if not isinstance(decisions, dict):
        return None
    return {
        str(rid) for rid, decision in decisions.items() if isinstance(decision, dict) and decision.get("ok") is True
    }


def _resolve_ids_from_scope(api: Any, run_id: str, scope: str) -> Dict[str, Any]:
    """Charge les row_ids depuis le plan du run pour scope=all ou validated."""
    try:
        plan_payload = api.get_plan(run_id)
    except (OSError, TypeError, ValueError) as exc:
        return {"ok": False, "message": t("errors.cannot_load_plan", detail=str(exc))}
    if not plan_payload.get("ok"):
        return {"ok": False, "message": plan_payload.get("message") or t("errors.plan_not_found")}
    rows = plan_payload.get("rows") or []
    validated_ids: Optional[set] = None
    if scope == "validated":
        try:
            val_payload = api.load_validation(run_id)
        except (OSError, TypeError, ValueError):
            val_payload = None
        validated_ids = _extract_validated_ids(val_payload)
    collected: List[str] = []
    for row in rows:
        rid = str((row or {}).get("row_id") or "").strip()
        if not rid:
            continue
        if validated_ids is not None and rid not in validated_ids:
            continue
        collected.append(rid)
    return {"ok": True, "row_ids": list(dict.fromkeys(collected))}


def _process_one_row(api: Any, run_id: str, row_id: str, reuse_existing: bool) -> Dict[str, Any]:
    one = api.get_quality_report(run_id, row_id, {"reuse_existing": reuse_existing})
    if one.get("ok"):
        status = str(one.get("status") or "analyzed")
        return {
            "ok": True,
            "status": status,
            "result": {
                "row_id": str(row_id),
                "status": status,
                "score": one.get("score"),
                "tier": one.get("tier"),
                "cache_hit_probe": bool(one.get("cache_hit_probe")),
                "cache_hit_quality": bool(one.get("cache_hit_quality")),
            },
        }
    return {
        "ok": False,
        "result": {
            "row_id": str(row_id),
            "status": "error",
            "message": str(one.get("message") or t("errors.unknown_error")),
        },
    }


def _run_batch(
    api: Any, run_id: str, row_ids: List[str], reuse_existing: bool, continue_on_error: bool
) -> Tuple[int, int, int, List[Dict[str, Any]]]:
    analyzed = 0
    ignored = 0
    errors = 0
    results: List[Dict[str, Any]] = []
    for row_id in row_ids:
        outcome = _process_one_row(api, run_id, row_id, reuse_existing)
        results.append(outcome["result"])
        if outcome["ok"]:
            if outcome["status"] == "ignored_existing":
                ignored += 1
            else:
                analyzed += 1
            continue
        errors += 1
        if not continue_on_error:
            break
    return analyzed, ignored, errors, results


def _prewarm_probe_cache(api: Any, run_id: str, row_ids: List[str]) -> int:
    """V5-04 (Polish Total v7.7.0, R5-STRESS-1) : pre-warm le cache probe en parallele.

    Cible : 10k films probe < 1h (vs 7.6h mono-thread). Apres ce pre-warm, les
    appels serie de `_process_one_row -> get_quality_report -> probe.probe_file`
    hit le cache et evitent le subprocess.

    Retourne le nombre de probes lances en parallele (0 si saute / desactive).
    Echec silencieux : si quelque chose plante, on continue en mono-thread.
    """
    try:
        from cinesort.infra.probe import ProbeService

        if len(row_ids) <= 1:
            return 0  # mono-thread plus rapide pour un seul element
        found = api._find_run_row(run_id)
        if not found:
            return 0
        run_row, store = found
        rs = api._get_run(run_id)
        if rs and rs.rows:
            rows = rs.rows
        else:
            from cinesort.ui.api.settings_support import normalize_user_path

            state_dir = normalize_user_path(run_row.get("state_dir"), api._state_dir)
            run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
            rows = api._load_rows_from_plan_jsonl(run_paths)
        cfg = rs.cfg if rs else api._cfg_from_run_row(run_row)
        wanted = set(row_ids)
        media_paths: List[Path] = []
        for row in rows:
            if str(getattr(row, "row_id", "")) not in wanted:
                continue
            mp = api._resolve_media_path_for_row(cfg, row)
            if mp is None:
                continue
            try:
                if not mp.exists():
                    continue
            except OSError:
                continue
            media_paths.append(mp)
        if len(media_paths) <= 1:
            return 0  # rien a paralleliser
        probe_settings = api._effective_probe_settings_for_runtime(run_row)
        # V5-04 : si parallelism desactive en settings, on saute le pre-warm.
        if not bool(probe_settings.get("probe_parallelism_enabled", True)):
            return 0
        probe = ProbeService(store)
        results = probe.probe_files(media_paths=media_paths, settings=probe_settings)
        logger.info(
            "Prewarm probe cache: run_id=%s requested=%d probed=%d",
            run_id,
            len(media_paths),
            len(results),
        )
        return len(results)
    except (AttributeError, ImportError, KeyError, OSError, TypeError, ValueError) as exc:
        # Le pre-warm ne doit jamais casser le batch — on continue en mono-thread.
        logger.warning("Prewarm probe cache ignore run_id=%s err=%s", run_id, exc)
        return 0


def analyze_quality_batch(
    api: Any, run_id: str, row_ids: Any, options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    error = _validate_inputs(api, run_id, row_ids)
    if error is not None:
        return error

    reuse_existing, continue_on_error, scope = _parse_options(options)
    cleaned_ids = _clean_row_ids(row_ids)

    # Si row_ids vide et scope fourni → charger depuis le plan du run.
    # scope="all"       → tous les PlanRows
    # scope="validated" → uniquement ceux marques OK dans validation.json
    if not cleaned_ids and scope in ("all", "validated"):
        scoped = _resolve_ids_from_scope(api, run_id, scope)
        if not scoped["ok"]:
            return {"ok": False, "message": scoped["message"]}
        cleaned_ids = scoped["row_ids"]

    if not cleaned_ids:
        return {"ok": False, "message": t("errors.no_rows_for_quality")}

    if not api._acquire_quality_batch_slot(run_id):
        return {"ok": False, "message": t("errors.quality_already_running")}

    try:
        # V5-04 : pre-warm cache probe en parallele AVANT le scoring serie.
        # Le scoring qui suit hit alors le cache et evite le subprocess.
        # Skip si reuse_existing=True (les quality reports existants seront reutilises).
        if not reuse_existing:
            _prewarm_probe_cache(api, run_id, cleaned_ids)
        analyzed, ignored, errors, results = _run_batch(api, run_id, cleaned_ids, reuse_existing, continue_on_error)
        processed = analyzed + ignored + errors
        return {
            "ok": True,
            "run_id": run_id,
            "total_requested": len(cleaned_ids),
            "processed": processed,
            "analyzed": analyzed,
            "ignored": ignored,
            "errors": errors,
            "results": results,
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        api.log_api_exception(
            "analyze_quality_batch",
            exc,
            run_id=run_id,
            extra={
                "row_ids_count": len(cleaned_ids),
                "reuse_existing": reuse_existing,
                "continue_on_error": continue_on_error,
            },
        )
        return {"ok": False, "message": t("errors.cannot_finish_quality_analysis")}
    finally:
        api._release_quality_batch_slot(run_id)
