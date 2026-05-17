from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import cinesort.infra.state as state


def dashboard_cache_path(run_paths: state.RunPaths) -> Path:
    return run_paths.run_dir / "dashboard_cache.json"


def path_cache_signature(path: Path) -> Dict[str, Any]:
    try:
        stat_result = path.stat()
    except (ImportError, OSError, PermissionError):
        return {"exists": False, "size": 0, "mtime_ns": 0}
    return {"exists": True, "size": int(stat_result.st_size), "mtime_ns": int(stat_result.st_mtime_ns)}


def dashboard_cache_signature(
    api: Any,
    *,
    run_row: Dict[str, Any],
    run_paths: state.RunPaths,
    store: Any,
) -> Dict[str, Any]:
    run_id = str(run_row.get("run_id") or run_paths.run_id or "")
    return {
        "version": 1,
        "run_id": run_id,
        "status": str(run_row.get("status") or ""),
        "started_ts": float(run_row.get("started_ts") or run_row.get("created_ts") or 0.0),
        "ended_ts": float(run_row.get("ended_ts") or 0.0),
        "stats_json": str(run_row.get("stats_json") or ""),
        "plan_jsonl": api._path_cache_signature(run_paths.plan_jsonl),
        "quality_reports": store.get_quality_report_stats(run_id=run_id),
        "anomalies": store.anomaly.get_anomaly_stats(run_id=run_id),
    }


def load_dashboard_cache(
    api: Any,
    *,
    run_row: Dict[str, Any],
    run_paths: state.RunPaths,
    store: Any,
) -> Optional[Dict[str, Any]]:
    cache_path = api._dashboard_cache_path(run_paths)
    if not cache_path.exists():
        return None
    expected_signature = api._dashboard_cache_signature(run_row=run_row, run_paths=run_paths, store=store)
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (KeyError, OSError, PermissionError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("signature") != expected_signature:
        return None
    payload = raw.get("payload")
    return payload if isinstance(payload, dict) else None


def write_dashboard_cache(
    api: Any,
    *,
    run_row: Dict[str, Any],
    run_paths: state.RunPaths,
    store: Any,
    payload: Dict[str, Any],
) -> None:
    cache_payload = {
        "signature": api._dashboard_cache_signature(run_row=run_row, run_paths=run_paths, store=store),
        "payload": payload,
    }
    state.atomic_write_json(api._dashboard_cache_path(run_paths), cache_payload)
