from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import cinesort.infra.state as state
from cinesort.domain.run_models import RunStatus

logger = logging.getLogger(__name__)


def get_plan(api: Any, run_id: str, *, normalize_user_path: Any) -> Dict[str, Any]:
    logger.debug("api: get_plan run_id=%s", run_id)
    if not api._is_valid_run_id(run_id):
        return {"ok": False, "message": "run_id invalide."}
    rs = api._get_run(run_id)
    if rs:
        if not rs.done:
            return {"ok": False, "message": "Plan pas pret."}
        rows = rs.rows
        if not rows:
            try:
                rows = api._load_rows_from_plan_jsonl(rs.paths)
            except (ImportError, OSError) as exc:
                return {"ok": False, "message": str(exc)}
        return {"ok": True, "rows": api._serialize_rows_for_payload(rows)}

    found = api._find_run_row(run_id)
    if not found:
        return {"ok": False, "message": "Run introuvable."}
    row, _store = found
    status_text = str(row.get("status") or "")
    if status_text not in {RunStatus.DONE.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
        return {"ok": False, "message": "Plan pas pret."}
    run_paths = api._run_paths_for(
        normalize_user_path(row.get("state_dir"), api._state_dir), run_id, ensure_exists=False
    )
    try:
        rows = api._load_rows_from_plan_jsonl(run_paths)
        return {"ok": True, "rows": api._serialize_rows_for_payload(rows)}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "message": str(exc)}


def load_validation(api: Any, run_id: str, *, normalize_user_path: Any) -> Dict[str, Any]:
    if not api._is_valid_run_id(run_id):
        return {"ok": False, "message": "run_id invalide."}
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
        return {"ok": False, "message": "Run introuvable."}
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


def cancel_run(api: Any, run_id: str) -> Dict[str, Any]:
    if not api._is_valid_run_id(run_id):
        return {"ok": False, "run_id": str(run_id or ""), "message": "run_id invalide."}
    rs = api._get_run(run_id)
    if not rs:
        return {"ok": False, "run_id": run_id, "message": "Run introuvable."}

    accepted = rs.runner.request_cancel(run_id)
    snap = rs.runner.get_status(run_id)
    return {
        "ok": bool(accepted),
        "run_id": run_id,
        "status": snap.status.value if snap else None,
        "cancel_requested": bool(snap.cancel_requested) if snap else bool(accepted),
        "done": bool(snap.done) if snap else False,
    }


def open_path(api: Any, path: str, *, default_root: str, normalize_user_path: Any) -> Dict[str, Any]:
    try:
        raw_path = str(path or "").strip()
        if not raw_path:
            return {"ok": False, "message": "Chemin vide."}

        candidate = Path(raw_path)
        if not candidate.exists():
            return {"ok": False, "message": "Chemin introuvable."}

        settings = api.get_settings()
        root_raw = str(settings.get("root") or "").strip()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())

        resolved_path = candidate.resolve()
        open_target = candidate
        resolved_to_check = resolved_path
        if resolved_path.is_file():
            open_target = candidate.parent
            resolved_to_check = resolved_path.parent
        elif not resolved_path.is_dir():
            return {"ok": False, "message": "Chemin invalide (ni fichier ni dossier)."}

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
            return {"ok": False, "message": "Chemin non autorise."}

        os.startfile(str(open_target))  # type: ignore[attr-defined]
        return {"ok": True}
    except (OSError, TypeError, ValueError) as exc:
        return {"ok": False, "message": str(exc)}
