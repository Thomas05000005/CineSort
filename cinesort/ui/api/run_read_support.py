from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import cinesort.domain.core as core
from cinesort.app.cleanup import preview_cleanup_residual_folders as _preview_cleanup_fn
from cinesort.domain.run_models import RunStatus
from cinesort.ui.api._validators import requires_valid_run_id


@requires_valid_run_id
def get_cleanup_residual_preview(api: Any, run_id: str) -> Dict[str, Any]:
    rs = api._get_run(run_id)
    if rs and not rs.done:
        return {"ok": False, "message": "Plan pas pret."}

    found = api._find_run_row(run_id)
    if not rs and not found:
        return {"ok": False, "message": "Run introuvable."}
    if found and not rs:
        row, _store = found
        status_text = str(row.get("status") or "")
        if status_text not in {RunStatus.DONE.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
            return {"ok": False, "message": "Plan pas pret."}

    ctx = api._run_context_for_apply(run_id)
    if not ctx:
        return {"ok": False, "message": "Plan indisponible."}

    cfg, _run_paths, rows, _log_fn, _store = ctx
    preview = _preview_cleanup_fn(cfg, api._touched_top_level_dirs_for_rows(cfg, rows))
    return {
        "ok": True,
        "run_id": run_id,
        "preview": preview,
    }


def resolve_media_path_for_row(
    api: Any,
    cfg: core.Config,
    row: core.PlanRow,
    *,
    env_truthy_fn: Any,
) -> Optional[Path]:
    folder = Path(str(row.folder or ""))
    if not folder.exists() or not folder.is_dir():
        return None

    video_name = str(row.video or "").strip()
    candidates: List[Path] = []
    if video_name:
        direct = folder / video_name
        candidates.append(direct)
        found_in_iterdir = False
        try:
            for path in folder.iterdir():
                if path.is_file() and path.name.lower() == video_name.lower():
                    candidates.append(path)
                    found_in_iterdir = True
        except (OSError, PermissionError, TypeError, ValueError) as exc:
            if env_truthy_fn("CINESORT_DEBUG"):
                api._debug_log(
                    state_dir=api._state_dir,
                    run_id=None,
                    enabled=True,
                    message=f"_resolve_media_path_for_row iterdir warning folder={folder}: {exc}",
                )
        # Audit 2026-05-14 : rglob recursif est lourd sur grosses arborescences NAS.
        # On ne descend dans les sous-dossiers que si iterdir n'a rien trouve.
        if not found_in_iterdir:
            try:
                for path in folder.rglob("*"):
                    if path.is_file() and path.name.lower() == video_name.lower():
                        candidates.append(path)
                        break
            except (OSError, PermissionError) as exc:
                if env_truthy_fn("CINESORT_DEBUG"):
                    api._debug_log(
                        state_dir=api._state_dir,
                        run_id=None,
                        enabled=True,
                        message=f"_resolve_media_path_for_row rglob warning folder={folder}: {exc}",
                    )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    try:
        videos = core.iter_videos(cfg, folder)
        if videos:
            return videos[0]
    except (OSError, PermissionError):
        return None
    return None


def touched_top_level_dirs_for_rows(
    cfg: core.Config,
    rows: List[core.PlanRow],
) -> Set[Path]:
    touched: Set[Path] = set()
    for row in rows:
        try:
            folder = Path(row.folder)
        except (OSError, PermissionError, ValueError):
            continue
        if folder.parent == cfg.root:
            touched.add(folder)
    return touched


@requires_valid_run_id
def get_auto_approved_summary(
    api: Any,
    run_id: str,
    threshold: int = 85,
    enabled: bool = False,
    quarantine_corrupted: bool = False,
) -> Dict[str, Any]:
    """Analyse rows for auto-approval: high confidence + no critical warnings.

    M-2 audit QA 20260429 : si quarantine_corrupted=True, les rows avec un
    warning d'integrite (integrity_header_invalid / integrity_probe_failed)
    sont auto-marquees pour quarantine et exclues de l'auto-approbation.
    Le frontend peut utiliser auto_quarantine_row_ids pour pre-cocher la
    decision "reject" sur ces films.
    """
    rs = api._get_run(run_id)
    if not rs or not rs.done:
        return {"ok": False, "message": "Plan pas pret."}
    rows = rs.rows if rs.rows else api._load_rows_from_plan_jsonl(rs.paths)
    if not rows:
        return {
            "ok": True,
            "auto_approved": 0,
            "manual_review": 0,
            "auto_quarantine": 0,
            "threshold": threshold,
            "enabled": enabled,
            "quarantine_corrupted": quarantine_corrupted,
        }

    critical_warnings = {"nfo_title_mismatch", "nfo_year_mismatch", "year_conflict_folder_file"}
    # M-2 : flags d'integrite qui declenchent l'auto-quarantine si setting actif
    integrity_warnings = {"integrity_header_invalid", "integrity_probe_failed"}
    auto_approved = 0
    manual_review = 0
    auto_quarantine = 0
    auto_row_ids: List[str] = []
    auto_quarantine_row_ids: List[str] = []

    for row in rows:
        confidence = int(row.confidence or 0)
        flags = set(row.warning_flags or [])
        has_integrity_issue = bool(flags & integrity_warnings)
        has_critical = bool(flags & critical_warnings)
        has_title = bool(row.proposed_title and str(row.proposed_title).strip())
        has_year = bool(row.proposed_year and int(row.proposed_year) >= 1900)

        # M-2 : auto-quarantine prioritaire sur auto-approve
        if quarantine_corrupted and has_integrity_issue:
            auto_quarantine += 1
            auto_quarantine_row_ids.append(str(row.row_id))
            continue

        if (
            enabled
            and confidence >= threshold
            and not has_critical
            and not has_integrity_issue
            and has_title
            and has_year
        ):
            auto_approved += 1
            auto_row_ids.append(str(row.row_id))
        else:
            manual_review += 1

    return {
        "ok": True,
        "auto_approved": auto_approved,
        "manual_review": manual_review,
        "auto_quarantine": auto_quarantine,
        "total": len(rows),
        "threshold": threshold,
        "enabled": enabled,
        "quarantine_corrupted": quarantine_corrupted,
        "auto_row_ids": auto_row_ids,
        "auto_quarantine_row_ids": auto_quarantine_row_ids,
    }
