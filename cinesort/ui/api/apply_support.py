from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import logging

import requests

import cinesort.domain.core as core
import cinesort.infra.state as state
from cinesort.ui.api._validators import requires_valid_run_id
from cinesort.app.apply_audit import ApplyAuditLogger, read_apply_audit

# Cf issue #83 : import direct au lieu de via re-export domain.core (qui cree un
# cycle domain -> app). NB : find_duplicate_targets reste accede via core.X car
# c'est un wrapper qui injecte 7 helpers internes de domain/core.py — pas un
# simple re-export.
from cinesort.app.apply_core import apply_rows as _apply_rows_fn
from cinesort.app.disk_space_check import check_disk_space_for_apply
from cinesort.app.move_journal import RecordOpWithJournal, journaled_move
from cinesort.domain.i18n_messages import t
from cinesort.infra.db import SQLiteStore
from cinesort.infra.integration_errors import IntegrationError
from cinesort.domain.conversions import to_bool as _to_bool
from cinesort.ui.api.settings_support import normalize_user_path, read_settings
from cinesort.ui.api._responses import err as _err_response
import contextlib

_log = logging.getLogger(__name__)


class _DuplicateCheckError(Exception):
    pass


def _resolve_hashed_target(dst: Path, op_type: str) -> Optional[Path]:
    """P1.2 : localise le fichier a hasher pour une op.

    MOVE_FILE : dst_path est directement le fichier.
    MOVE_DIR  : dst_path est un dossier -> trouver le plus gros video a l'interieur
                (meme logique qu'au moment de l'apply via find_main_video_in_folder).
    """
    if op_type == "MOVE_FILE":
        return dst if dst.is_file() else None
    if op_type == "MOVE_DIR":
        if not dst.is_dir():
            return None
        # On ne peut pas appeler find_main_video_in_folder sans cfg, on fait
        # une heuristique equivalente : le plus gros fichier video du dossier.
        # Phase 6 v7.8.0 : VIDEO_EXTS_ALL au lieu du 5eme set hardcode divergent
        video_exts = core.VIDEO_EXTS_ALL
        best: Optional[Path] = None
        best_size = 0
        try:
            for entry in dst.iterdir():
                if not entry.is_file() or entry.suffix.lower() not in video_exts:
                    continue
                try:
                    size = entry.stat().st_size
                except (OSError, PermissionError):
                    continue
                if size > best_size:
                    best = entry
                    best_size = size
        except (OSError, PermissionError):
            return None
        return best
    return None


def preverify_undo_operations(
    ops: List[Dict[str, Any]],
    *,
    hash_cache: Optional[Dict] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """P1.2 : vérifie l'intégrité des destinations avant de lancer un undo.

    Pour chaque op, classe dans :
      - "safe" : dst existe ET (sha1/size correspondent OU legacy sans sha1)
      - "hash_mismatch" : dst existe mais le fichier a changé (remplacement manuel)
      - "missing" : dst n'existe plus (fichier déjà bougé/supprimé)
      - "legacy_no_hash" : op pré-P1.2 sans sha1/size → traitée comme legacy (avant)

    Pour MOVE_DIR, on localise le fichier vidéo principal dans le dossier et on
    verifie son sha1. Les sidecars (nfo/srt/image) ne sont pas hashées à l'apply
    donc finissent toujours dans "legacy_no_hash".
    """
    from cinesort.app.apply_core import sha1_quick_cached

    report: Dict[str, List[Dict[str, Any]]] = {
        "safe": [],
        "hash_mismatch": [],
        "missing": [],
        "legacy_no_hash": [],
    }

    for op in ops:
        dst = Path(str(op.get("dst_path") or ""))
        expected_sha1 = op.get("src_sha1") or None
        expected_size = op.get("src_size")
        op_type = str(op.get("op_type") or "MOVE_FILE")

        if not dst.exists():
            report["missing"].append({**op, "preverify_reason": "destination absente"})
            continue

        if not expected_sha1:
            report["legacy_no_hash"].append(op)
            continue

        hashed_target = _resolve_hashed_target(dst, op_type)
        if hashed_target is None:
            # MOVE_DIR sans video a l'interieur, ou dst pas le type attendu
            report["missing"].append(
                {
                    **op,
                    "preverify_reason": f"impossible de localiser le fichier hashe ({op_type})",
                }
            )
            continue

        try:
            actual_size = hashed_target.stat().st_size
        except (OSError, PermissionError) as exc:
            report["missing"].append({**op, "preverify_reason": f"stat échouée: {exc}"})
            continue

        if expected_size is not None and int(actual_size) != int(expected_size):
            report["hash_mismatch"].append(
                {
                    **op,
                    "preverify_reason": f"taille différente: {actual_size} octets vs {expected_size} attendus",
                    "actual_size": int(actual_size),
                    "hashed_path": str(hashed_target),
                }
            )
            continue

        try:
            actual_sha1 = sha1_quick_cached(hashed_target, hash_cache)
        except (OSError, PermissionError) as exc:
            report["missing"].append({**op, "preverify_reason": f"hash impossible: {exc}"})
            continue

        if actual_sha1 != expected_sha1:
            report["hash_mismatch"].append(
                {
                    **op,
                    "preverify_reason": f"empreinte différente: {actual_sha1[:12]}... vs {expected_sha1[:12]}... attendu",
                    "actual_sha1": actual_sha1,
                    "hashed_path": str(hashed_target),
                }
            )
            continue

        report["safe"].append(op)

    return report


def run_context_for_apply(
    api: Any,
    run_id: str,
) -> Optional[Tuple[core.Config, state.RunPaths, List[core.PlanRow], Callable[[str, str], None], SQLiteStore]]:
    rs = api._get_run(run_id)
    if rs:
        rows = rs.rows
        if not rows:
            rows = api._load_rows_from_plan_jsonl(rs.paths)
        return rs.cfg, rs.paths, rows, rs.log, rs.store

    found = api._find_run_row(run_id)
    if not found:
        return None
    row, store = found
    state_dir = normalize_user_path(row.get("state_dir"), api._state_dir)
    run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
    rows = api._load_rows_from_plan_jsonl(run_paths)
    cfg = api._cfg_from_run_row(row)
    return cfg, run_paths, rows, api._file_logger(run_paths), store


def build_undo_preview_payload(
    api: Any,
    run_id: str,
) -> Tuple[
    Dict[str, Any],
    Optional[SQLiteStore],
    Optional[state.RunPaths],
    Optional[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    found = api._find_run_row(run_id)
    if not found:
        return (
            _err_response(t("errors.run_not_found"), category="resource", level="info", log_module=__name__),
            None,
            None,
            None,
            [],
        )
    row, store = found
    state_dir = normalize_user_path(row.get("state_dir"), api._state_dir)
    run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=True)

    batch = store.get_last_reversible_apply_batch(run_id)
    if not batch:
        return (
            {
                "ok": True,
                "run_id": run_id,
                "batch_id": None,
                "can_undo": False,
                "counts": {
                    "total": 0,
                    "reversible": 0,
                    "irreversible": 0,
                    "conflicts_predicted": 0,
                },
                "message": t("errors.no_reversible_apply"),
            },
            store,
            run_paths,
            None,
            [],
        )

    batch_id = str(batch.get("batch_id") or "")
    ops = store.list_apply_operations(batch_id=batch_id) if batch_id else []
    reversible_ops = [op for op in ops if int(op.get("reversible") or 0) == 1]
    conflicts_predicted = 0
    for op in reversible_ops:
        current_path = Path(str(op.get("dst_path") or ""))
        target_path = Path(str(op.get("src_path") or ""))
        if current_path.exists() and target_path.exists():
            conflicts_predicted += 1

    cfg = api._cfg_from_run_row(row)
    empty_bucket = cfg.root / cfg.empty_folders_folder_name
    residual_bucket = cfg.root / cfg.cleanup_residual_folders_folder_name
    empty_folder_dirs = 0
    cleanup_residual_dirs = 0
    for op in reversible_ops:
        if str(op.get("op_type") or "") != "MOVE_DIR":
            continue
        dst_path = Path(str(op.get("dst_path") or ""))
        try:
            dst_path.relative_to(empty_bucket)
            empty_folder_dirs += 1
            continue
        except ValueError:
            pass
        try:
            dst_path.relative_to(residual_bucket)
            cleanup_residual_dirs += 1
        except ValueError:
            pass

    payload = {
        "ok": True,
        "run_id": run_id,
        "batch_id": batch_id,
        "can_undo": bool(reversible_ops),
        "counts": {
            "total": int(len(ops)),
            "reversible": int(len(reversible_ops)),
            "irreversible": int(max(0, len(ops) - len(reversible_ops))),
            "conflicts_predicted": int(conflicts_predicted),
        },
        "categories": {
            "empty_folder_dirs": int(empty_folder_dirs),
            "cleanup_residual_dirs": int(cleanup_residual_dirs),
        },
        "paths": {
            "empty_folder_bucket": str(empty_bucket),
            "cleanup_residual_bucket": str(residual_bucket),
        },
        "message": t("errors.preview_undo_ready") if reversible_ops else t("errors.no_reversible_op_available"),
    }
    return payload, store, run_paths, batch, reversible_ops


@requires_valid_run_id
def undo_last_apply_preview(api: Any, run_id: str) -> Dict[str, Any]:
    try:
        payload, _store, _run_paths, _batch, _ops = api._build_undo_preview_payload(run_id)
        return payload
    except (OSError, PermissionError, KeyError, TypeError, ValueError) as exc:
        api.log_api_exception("undo_last_apply_preview", exc, run_id=run_id)
        return _err_response(t("errors.cannot_prepare_undo"), category="state", level="warning", log_module=__name__)


def _execute_undo_ops(
    api: Any,
    reversible_ops: List[Dict[str, Any]],
    store: Any,
    log_fn: Callable[[str, str], None],
    run_paths: Any,
    *,
    empty_bucket: Optional[Path],
    residual_bucket: Optional[Path],
    atomic: bool = True,
) -> Dict[str, Any]:
    """P1.2 : undo avec pré-vérification sha1/size.

    atomic=True (défaut) : si au moins une op a un fichier qui a été remplacé
    (hash_mismatch), on ABANDONNE tout l'undo — aucune modification filesystem —
    et on retourne un rapport détaillé. L'utilisateur peut alors décider :
    corriger manuellement, ou forcer avec atomic=False.

    atomic=False : best-effort — les ops safe sont exécutées, les hash_mismatch
    sont marquées SKIPPED avec raison claire, les missing SKIPPED aussi.
    """
    done = 0
    skipped = 0
    failed = 0
    conflict_moves = 0
    empty_folder_dirs_reversed = 0
    cleanup_residual_dirs_reversed = 0
    undo_conflicts_root = run_paths.run_dir / "_review" / "_undo_conflicts"

    hash_cache: Dict = {}
    preverify = preverify_undo_operations(reversible_ops, hash_cache=hash_cache)
    mismatch_ops = preverify["hash_mismatch"]
    if mismatch_ops and atomic:
        log_fn(
            "ERROR",
            f"UNDO atomique refusé: {len(mismatch_ops)} fichier(s) ont été "
            "modifiés depuis l'apply. Aucun move n'a été effectué.",
        )
        for op in mismatch_ops:
            reason = str(op.get("preverify_reason") or "empreinte modifiée")
            _log.warning(
                "undo: hash mismatch sur %s (%s) — abandon atomique",
                op.get("dst_path"),
                reason,
            )
        mismatch_ids = {int(op.get("id") or 0) for op in mismatch_ops}
        return {
            "done": 0,
            "skipped": 0,
            "failed": 0,
            "conflict_moves": 0,
            "empty_folder_dirs_reversed": 0,
            "cleanup_residual_dirs_reversed": 0,
            "aborted_atomic": True,
            "aborted_reason": "hash_mismatch",
            "preverify": {
                "safe_count": len(preverify["safe"]),
                "hash_mismatch_count": len(mismatch_ops),
                "missing_count": len(preverify["missing"]),
                "legacy_no_hash_count": len(preverify["legacy_no_hash"]),
                "mismatch_details": [
                    {
                        "dst_path": str(op.get("dst_path") or ""),
                        "src_path": str(op.get("src_path") or ""),
                        "reason": str(op.get("preverify_reason") or ""),
                    }
                    for op in mismatch_ops
                ],
            },
        }

    # best-effort : on skipe les mismatch et les missing, on traite les autres
    mismatch_ids = {int(op.get("id") or 0) for op in mismatch_ops}
    mismatch_reasons = {int(op.get("id") or 0): op.get("preverify_reason") for op in mismatch_ops}

    for idx, op in enumerate(reversed(reversible_ops), start=1):
        op_id_for_check = int(op.get("id") or 0)
        if op_id_for_check in mismatch_ids:
            skipped += 1
            store.mark_apply_operation_undo_status(
                op_id=op_id_for_check,
                undo_status="SKIPPED",
                error_message=f"Empreinte modifiee depuis apply: {mismatch_reasons.get(op_id_for_check) or ''}",
            )
            log_fn(
                "WARN",
                f"UNDO skip {idx}/{len(reversible_ops)}: empreinte modifiée — "
                f"{op.get('dst_path')} ({mismatch_reasons.get(op_id_for_check) or ''})",
            )
            continue
        op_id = int(op.get("id") or 0)
        current_path = Path(str(op.get("dst_path") or ""))
        target_path = Path(str(op.get("src_path") or ""))
        try:
            if not current_path.exists():
                skipped += 1
                store.mark_apply_operation_undo_status(
                    op_id=op_id,
                    undo_status="SKIPPED",
                    error_message=f"Source inverse introuvable: {current_path}",
                )
                log_fn("WARN", f"UNDO skip {idx}/{len(reversible_ops)}: source inverse introuvable {current_path}")
                continue

            if target_path.exists():
                undo_conflicts_root.mkdir(parents=True, exist_ok=True)
                conflict_dst = api._unique_path(undo_conflicts_root / current_path.name)
                # M3 : TOCTOU possible — current_path peut disparaitre entre exists() et move()
                # CR-1 : journal write-ahead pour atomicite undo (cf move_journal.py)
                try:
                    with journaled_move(store, src=current_path, dst=conflict_dst, op_type="UNDO_QUARANTINE"):
                        shutil.move(str(current_path), str(conflict_dst))
                except FileNotFoundError:
                    _log.warning("undo: fichier disparu entre check et move (conflict): %s", current_path)
                    skipped += 1
                    store.mark_apply_operation_undo_status(
                        op_id=op_id,
                        undo_status="SKIPPED",
                        error_message=f"Fichier disparu entre check et move: {current_path}",
                    )
                    continue
                except PermissionError as perm_err:
                    _log.error("undo: permission refusee: %s -> %s: %s", current_path, conflict_dst, perm_err)
                    failed += 1
                    store.mark_apply_operation_undo_status(
                        op_id=op_id,
                        undo_status="FAILED",
                        error_message=str(perm_err),
                    )
                    continue
                conflict_moves += 1
                failed += 1
                store.mark_apply_operation_undo_status(
                    op_id=op_id,
                    undo_status="FAILED",
                    error_message=f"Conflit cible existante, deplace vers {conflict_dst}",
                )
                log_fn(
                    "WARN",
                    f"UNDO conflit {idx}/{len(reversible_ops)}: {current_path} -> {conflict_dst} (cible existante: {target_path})",
                )
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            # M3 : TOCTOU possible ici aussi — raffinement du catch
            # CR-1 : journal write-ahead pour atomicite undo
            try:
                with journaled_move(store, src=current_path, dst=target_path, op_type="UNDO_RESTORE"):
                    shutil.move(str(current_path), str(target_path))
            except FileNotFoundError:
                _log.warning("undo: fichier disparu entre check et move: %s", current_path)
                skipped += 1
                store.mark_apply_operation_undo_status(
                    op_id=op_id,
                    undo_status="SKIPPED",
                    error_message=f"Fichier disparu entre check et move: {current_path}",
                )
                continue
            except PermissionError as perm_err:
                _log.error("undo: permission refusee: %s -> %s: %s", current_path, target_path, perm_err)
                failed += 1
                store.mark_apply_operation_undo_status(
                    op_id=op_id,
                    undo_status="FAILED",
                    error_message=str(perm_err),
                )
                continue
            done += 1
            if empty_bucket is not None:
                try:
                    current_path.relative_to(empty_bucket)
                    empty_folder_dirs_reversed += 1
                except ValueError:
                    pass
            if residual_bucket is not None:
                try:
                    current_path.relative_to(residual_bucket)
                    cleanup_residual_dirs_reversed += 1
                except ValueError:
                    pass
            store.mark_apply_operation_undo_status(op_id=op_id, undo_status="DONE", error_message=None)
            log_fn("INFO", f"UNDO {idx}/{len(reversible_ops)}: {current_path} -> {target_path}")
        except (OSError, FileExistsError, ValueError, TypeError) as exc:
            failed += 1
            store.mark_apply_operation_undo_status(
                op_id=op_id,
                undo_status="FAILED",
                error_message=str(exc),
            )
            log_fn("ERROR", f"UNDO echec {idx}/{len(reversible_ops)}: {exc}")

    return {
        "done": done,
        "skipped": skipped,
        "failed": failed,
        "conflict_moves": conflict_moves,
        "empty_folder_dirs_reversed": empty_folder_dirs_reversed,
        "cleanup_residual_dirs_reversed": cleanup_residual_dirs_reversed,
        "undo_conflicts_root": str(undo_conflicts_root),
        "aborted_atomic": False,
        "preverify": {
            "safe_count": len(preverify["safe"]),
            "hash_mismatch_count": len(preverify["hash_mismatch"]),
            "missing_count": len(preverify["missing"]),
            "legacy_no_hash_count": len(preverify["legacy_no_hash"]),
        },
    }


def _write_undo_summary(
    api: Any,
    run_paths: Any,
    log_fn: Callable[[str, str], None],
    *,
    batch_id: str,
    counts: Dict[str, int],
    preview_categories: Dict[str, Any],
) -> None:
    try:
        summary_lines = [
            f"Batch cible: {batch_id}",
            f"Operations restaurees: {counts['done']}",
            f"Operations skippees: {counts['skipped']}",
            f"Operations en echec: {counts['failed']}",
            f"Operations irreversibles: {counts.get('irreversible', 0)}",
        ]
        if int(preview_categories.get("empty_folder_dirs") or 0) > 0:
            summary_lines.append(
                f"Dossiers vides (_Vide) inclus dans l'undo: {int(preview_categories.get('empty_folder_dirs') or 0)}"
            )
        if int(preview_categories.get("cleanup_residual_dirs") or 0) > 0:
            summary_lines.append(
                "Dossiers residuels (_Dossier Nettoyage) inclus dans l'undo: "
                f"{int(preview_categories.get('cleanup_residual_dirs') or 0)}"
            )
        if counts.get("conflict_moves", 0) > 0:
            summary_lines.append(f"Conflits undo deplaces: {counts.get('undo_conflicts_root', '')}")
        api._write_summary_section(
            run_paths,
            marker="=== RESUME UNDO ===",
            section_body="\n".join(summary_lines),
        )
    except (OSError, PermissionError, KeyError, TypeError, ValueError) as exc:
        log_fn("WARN", f"Resume undo non ecrit: {exc}")


@requires_valid_run_id
def build_undo_by_row_preview(api: Any, run_id: str, batch_id: Optional[str] = None) -> Dict[str, Any]:
    """Preview undo detaille par film : pour chaque row_id, liste des operations et conflits predits."""
    found = api._find_run_row(run_id)
    if not found:
        return _err_response(t("errors.run_not_found"), category="resource", level="info", log_module=__name__)
    _row, store = found

    if batch_id:
        batches = store.list_apply_batches_for_run(run_id=run_id, limit=50)
        batch = next((b for b in batches if b["batch_id"] == batch_id), None)
    else:
        batch = store.get_last_reversible_apply_batch(run_id)
    if not batch:
        return {"ok": True, "batch_id": None, "can_undo": False, "rows": [], "message": t("errors.no_reversible_batch")}

    bid = str(batch["batch_id"])
    rows_summary = store.get_batch_rows_summary(batch_id=bid)

    # Load plan rows for titles.
    rs = api._get_run(run_id)
    plan_rows_by_id: Dict[str, Any] = {}
    try:
        state_dir = normalize_user_path(_row.get("state_dir"), api._state_dir)
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
        plan_rows = rs.rows if rs and rs.rows else api._load_rows_from_plan_jsonl(run_paths)
        plan_rows_by_id = {str(r.row_id): r for r in plan_rows}
    except (FileNotFoundError, OSError):
        pass

    rows_out: List[Dict[str, Any]] = []
    for summary in rows_summary:
        rid = str(summary["row_id"])
        ops = store.list_apply_operations_by_row(batch_id=bid, row_id=rid)
        reversible_pending = [
            op for op in ops if int(op.get("reversible") or 0) == 1 and str(op.get("undo_status")) == "PENDING"
        ]
        conflicts = 0
        ops_detail: List[Dict[str, Any]] = []
        for op in ops:
            current = Path(str(op.get("dst_path") or ""))
            target = Path(str(op.get("src_path") or ""))
            has_conflict = current.exists() and target.exists()
            if has_conflict:
                conflicts += 1
            ops_detail.append(
                {
                    "id": int(op.get("id") or 0),
                    "op_type": str(op.get("op_type") or ""),
                    "src_path": str(op.get("src_path") or ""),
                    "dst_path": str(op.get("dst_path") or ""),
                    "reversible": int(op.get("reversible") or 0),
                    "undo_status": str(op.get("undo_status") or "PENDING"),
                    "conflict": has_conflict,
                }
            )

        plan_row = plan_rows_by_id.get(rid)
        proposed_title = str(plan_row.proposed_title) if plan_row else ""
        folder = str(plan_row.folder) if plan_row else ""

        can_undo_row = len(reversible_pending) > 0
        rows_out.append(
            {
                "row_id": rid,
                "proposed_title": proposed_title,
                "folder": folder,
                "ops_total": int(summary["total_ops"]),
                "ops_reversible": int(summary["reversible_ops"]),
                "ops_undone": int(summary["undone_ops"]),
                "ops_pending": int(summary["pending_ops"]),
                "ops_failed": int(summary.get("failed_ops") or 0),
                "conflicts_predicted": conflicts,
                "can_undo": can_undo_row,
                "operations": ops_detail,
            }
        )

    return {
        "ok": True,
        "batch_id": bid,
        "batch_status": str(batch.get("status") or ""),
        "can_undo": any(r["can_undo"] for r in rows_out),
        "rows": rows_out,
        "message": t("errors.preview_undo_per_film_ready"),
    }


@requires_valid_run_id
def undo_selected_rows(
    api: Any,
    run_id: str,
    row_ids: List[str],
    dry_run: bool = True,
    batch_id: Optional[str] = None,
    atomic: bool = True,
) -> Dict[str, Any]:
    """Annule uniquement les operations des films selectionnes.

    atomic=True (défaut, P1.2) : si un fichier a été remplacé depuis l'apply
    (sha1 différent), l'undo entier est refusé avec un rapport. atomic=False
    force le best-effort (skipe les fichiers modifiés).
    """
    if not row_ids or not isinstance(row_ids, list):
        return _err_response(t("errors.row_ids_required"), category="validation", level="info", log_module=__name__)

    found = api._find_run_row(run_id)
    if not found:
        return _err_response(t("errors.run_not_found"), category="resource", level="info", log_module=__name__)
    _row, store = found
    state_dir = normalize_user_path(_row.get("state_dir"), api._state_dir)
    run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=True)

    if batch_id:
        batches = store.list_apply_batches_for_run(run_id=run_id, limit=50)
        batch = next((b for b in batches if b["batch_id"] == batch_id), None)
    else:
        batch = store.get_last_reversible_apply_batch(run_id)
    if not batch:
        return _err_response(t("errors.no_reversible_batch"), category="state", level="info", log_module=__name__)

    bid = str(batch["batch_id"])
    if bool(dry_run):
        preview = build_undo_by_row_preview(api, run_id, batch_id=bid)
        selected = [r for r in preview.get("rows", []) if r["row_id"] in row_ids]
        return {
            "ok": True,
            "batch_id": bid,
            "dry_run": True,
            "status": "PREVIEW_ONLY",
            "selected_rows": selected,
            "message": t("errors.preview_undo_selective"),
        }

    # Collect all reversible PENDING ops for the selected row_ids.
    target_row_ids = set(str(r) for r in row_ids)
    all_ops = store.list_apply_operations(batch_id=bid)
    selected_ops = [
        op
        for op in all_ops
        if str(op.get("row_id") or "") in target_row_ids
        and int(op.get("reversible") or 0) == 1
        and str(op.get("undo_status")) == "PENDING"
    ]

    if not selected_ops:
        return {
            "ok": True,
            "batch_id": bid,
            "dry_run": False,
            "status": "NOOP",
            "counts": {"done": 0, "skipped": 0, "failed": 0},
            "message": t("errors.no_reversible_op_pending"),
        }

    log_fn = api._file_logger(run_paths)
    log_fn("INFO", f"=== UNDO SELECTIVE start batch={bid} row_ids={row_ids} ===")

    cfg = api._cfg_from_run_row(_row)
    empty_bucket = cfg.root / cfg.empty_folders_folder_name
    residual_bucket = cfg.root / cfg.cleanup_residual_folders_folder_name

    undo_counts = _execute_undo_ops(
        api,
        selected_ops,
        store,
        log_fn,
        run_paths,
        empty_bucket=empty_bucket,
        residual_bucket=residual_bucket,
        atomic=bool(atomic),
    )

    # Si l'undo a été abandonné atomiquement (hash mismatch), remonter le rapport.
    if undo_counts.get("aborted_atomic"):
        log_fn("WARN", f"UNDO SELECTIVE atomique refuse batch={bid}: hash mismatch")
        return {
            "ok": False,
            "batch_id": bid,
            "dry_run": False,
            "status": "ABORTED_HASH_MISMATCH",
            "message": t("errors.undo_atomic_refused"),
            "preverify": undo_counts.get("preverify"),
        }

    # Determine batch-level status: check if ALL ops in the batch are now non-PENDING.
    remaining = store.list_apply_operations(batch_id=bid)
    all_resolved = all(
        str(op.get("undo_status")) != "PENDING" for op in remaining if int(op.get("reversible") or 0) == 1
    )
    if all_resolved:
        batch_status = "UNDONE_DONE" if undo_counts["failed"] == 0 else "UNDONE_PARTIAL"
    else:
        batch_status = "UNDONE_PARTIAL"
    store.mark_apply_batch_undo_status(
        batch_id=bid,
        status=batch_status,
        summary={
            "undo_selective": True,
            "row_ids": list(target_row_ids),
            **undo_counts,
        },
    )

    log_fn(
        "INFO",
        f"=== UNDO SELECTIVE done batch={bid} done={undo_counts['done']} failed={undo_counts['failed']} status={batch_status} ===",
    )

    return {
        "ok": True,
        "batch_id": bid,
        "dry_run": False,
        "status": batch_status,
        "counts": {
            "done": undo_counts["done"],
            "skipped": undo_counts["skipped"],
            "failed": undo_counts["failed"],
        },
        "row_ids": list(target_row_ids),
        "message": t("errors.undo_selective_done")
        if undo_counts["failed"] == 0
        else t("errors.undo_selective_done_with_anomalies"),
    }


@requires_valid_run_id
def list_apply_history(api: Any, run_id: str) -> Dict[str, Any]:
    """Historique de tous les applies d'un run."""
    found = api._find_run_row(run_id)
    if not found:
        return _err_response(t("errors.run_not_found"), category="resource", level="info", log_module=__name__)
    _row, store = found
    batches = store.list_apply_batches_for_run(run_id=run_id, limit=20)
    return {"ok": True, "run_id": run_id, "batches": batches}


def _extract_undo_context(preview: Dict[str, Any], batch: Any) -> Dict[str, Any]:
    """Extrait les donnees de contexte undo depuis la preview."""
    preview_categories = (preview.get("categories") or {}) if isinstance(preview.get("categories"), dict) else {}
    preview_paths = (preview.get("paths") or {}) if isinstance(preview.get("paths"), dict) else {}
    return {
        "irreversible_count": int((preview.get("counts") or {}).get("irreversible") or 0),
        "preview_categories": preview_categories,
        "batch_id": str(batch.get("batch_id") or ""),
        "empty_bucket": (
            Path(str(preview_paths.get("empty_folder_bucket") or ""))
            if preview_paths.get("empty_folder_bucket")
            else None
        ),
        "residual_bucket": (
            Path(str(preview_paths.get("cleanup_residual_bucket") or ""))
            if preview_paths.get("cleanup_residual_bucket")
            else None
        ),
        "preview_counts": preview.get("counts") or {},
    }


def _execute_and_finalize_undo(
    api: Any,
    run_id: str,
    uctx: Dict[str, Any],
    reversible_ops: list,
    store: Any,
    *,
    atomic: bool = True,
    run_paths: Any,
) -> Dict[str, Any]:
    """Execute les operations d'undo et finalise (journal, notification, retour)."""
    batch_id = uctx["batch_id"]
    irreversible_count = uctx["irreversible_count"]
    preview_categories = uctx["preview_categories"]

    log_fn = api._file_logger(run_paths)
    log_fn("INFO", f"=== UNDO start batch={batch_id} run_id={run_id} ===")

    undo_counts = _execute_undo_ops(
        api,
        reversible_ops,
        store,
        log_fn,
        run_paths,
        empty_bucket=uctx["empty_bucket"],
        residual_bucket=uctx["residual_bucket"],
        atomic=bool(atomic),
    )
    if undo_counts.get("aborted_atomic"):
        log_fn("WARN", f"UNDO atomique refuse batch={batch_id}: hash mismatch")
        return {
            "ok": False,
            "batch_id": batch_id,
            "dry_run": False,
            "status": "ABORTED_HASH_MISMATCH",
            "message": t("errors.undo_atomic_refused_detailed"),
            "preverify": undo_counts.get("preverify"),
        }
    done, skipped, failed = undo_counts["done"], undo_counts["skipped"], undo_counts["failed"]
    empty_reversed = undo_counts["empty_folder_dirs_reversed"]
    residual_reversed = undo_counts["cleanup_residual_dirs_reversed"]

    status = "UNDONE_DONE" if failed == 0 else "UNDONE_PARTIAL"
    store.mark_apply_batch_undo_status(
        batch_id=batch_id,
        status=status,
        summary={
            "run_id": run_id,
            "batch_id": batch_id,
            "undo": {
                "done": done,
                "skipped": skipped,
                "failed": failed,
                "irreversible": irreversible_count,
                "conflicts_moved": undo_counts["conflict_moves"],
                "empty_folder_dirs": int(preview_categories.get("empty_folder_dirs") or 0),
                "cleanup_residual_dirs": int(preview_categories.get("cleanup_residual_dirs") or 0),
                "empty_folder_dirs_reversed": empty_reversed,
                "cleanup_residual_dirs_reversed": residual_reversed,
            },
        },
    )

    all_counts = {**undo_counts, "irreversible": irreversible_count}
    _write_undo_summary(
        api, run_paths, log_fn, batch_id=batch_id, counts=all_counts, preview_categories=preview_categories
    )

    log_fn(
        "INFO",
        f"=== UNDO done batch={batch_id} done={done} skipped={skipped} failed={failed} "
        f"irreversible={irreversible_count} status={status} ===",
    )
    api._notify.notify(
        "undo_done",
        t("notifications.title_undo_done"),
        t("notifications.undo_done_body", done=done, failed=failed),
    )
    if done > 0:
        import time as _time

        api._dispatch_plugin_hook(
            "post_undo",
            {
                "run_id": run_id,
                "ts": _time.time(),
                "data": {"batch_id": batch_id, "done": done, "failed": failed, "skipped": skipped},
            },
        )

    return {
        "ok": True,
        "run_id": run_id,
        "batch_id": batch_id,
        "dry_run": False,
        "status": status,
        "counts": {"done": done, "skipped": skipped, "failed": failed, "irreversible": irreversible_count},
        "categories": {
            "empty_folder_dirs": int(preview_categories.get("empty_folder_dirs") or 0),
            "cleanup_residual_dirs": int(preview_categories.get("cleanup_residual_dirs") or 0),
            "empty_folder_dirs_reversed": empty_reversed,
            "cleanup_residual_dirs_reversed": residual_reversed,
        },
        "message": t("errors.undo_done") if failed == 0 else t("errors.undo_done_with_anomalies"),
    }


@requires_valid_run_id
def undo_last_apply(api: Any, run_id: str, dry_run: bool = True, atomic: bool = True) -> Dict[str, Any]:
    """Annule le dernier apply d'un run (dry-run ou reel).

    atomic=True (defaut, P1.2) : si un fichier a ete modifie depuis l'apply
    (sha1 different), l'undo est refuse avec un rapport detaille. Passer
    atomic=False pour forcer le best-effort.
    """
    _log.info("api: undo run_id=%s dry_run=%s atomic=%s", run_id, dry_run, atomic)
    try:
        preview, store, run_paths, batch, reversible_ops = api._build_undo_preview_payload(run_id)
    except (OSError, PermissionError, KeyError, TypeError, ValueError) as exc:
        api.log_api_exception("undo_last_apply", exc, run_id=run_id, extra={"dry_run": bool(dry_run)})
        return _err_response(t("errors.cannot_undo_last_apply"), category="state", level="warning", log_module=__name__)
    if not preview.get("ok"):
        return preview
    if batch is None or store is None or run_paths is None:
        return {
            "ok": False,
            "run_id": run_id,
            "batch_id": None,
            "dry_run": bool(dry_run),
            "status": "PREVIEW_ONLY" if bool(dry_run) else "NOOP",
            "counts": {"done": 0, "skipped": 0, "failed": 0, "irreversible": 0},
            "message": str(preview.get("message") or t("errors.no_reversible_apply_available")),
        }

    uctx = _extract_undo_context(preview, batch)

    if bool(dry_run):
        return {
            "ok": True,
            "run_id": run_id,
            "batch_id": uctx["batch_id"],
            "dry_run": True,
            "status": "PREVIEW_ONLY",
            "counts": {"done": 0, "skipped": 0, "failed": 0, "irreversible": uctx["irreversible_count"]},
            "categories": {
                "empty_folder_dirs": int(uctx["preview_categories"].get("empty_folder_dirs") or 0),
                "cleanup_residual_dirs": int(uctx["preview_categories"].get("cleanup_residual_dirs") or 0),
                "empty_folder_dirs_reversed": 0,
                "cleanup_residual_dirs_reversed": 0,
            },
            "preview": uctx["preview_counts"],
            "message": t("errors.preview_undo_only"),
        }

    if not reversible_ops:
        return {
            "ok": False,
            "run_id": run_id,
            "batch_id": uctx["batch_id"],
            "dry_run": False,
            "status": "NOOP",
            "counts": {"done": 0, "skipped": 0, "failed": 0, "irreversible": uctx["irreversible_count"]},
            "message": t("errors.no_reversible_op_to_undo"),
        }

    return _execute_and_finalize_undo(
        api, run_id, uctx, reversible_ops, store, run_paths=run_paths, atomic=bool(atomic)
    )


@requires_valid_run_id
def _validate_apply(
    api: Any,
    run_id: str,
    decisions: Dict[str, Dict[str, Any]],
    dry_run: bool,
    quarantine_unapproved: bool,
) -> Dict[str, Any]:
    if not isinstance(decisions, dict):
        return _err_response(
            t("errors.payload_decisions_invalid"), category="validation", level="info", log_module=__name__
        )
    if not api._acquire_apply_slot(run_id):
        return _err_response(t("errors.apply_already_in_progress"), category="state", level="info", log_module=__name__)
    try:
        ctx = api._run_context_for_apply(run_id)
    except (OSError, PermissionError, KeyError, TypeError, ValueError) as exc:
        api._release_apply_slot(run_id)
        api.log_api_exception(
            "apply",
            exc,
            run_id=run_id,
            extra={
                "dry_run": bool(dry_run),
                "quarantine_unapproved": bool(quarantine_unapproved),
                "decision_count": len(decisions),
                "phase": "load_context",
            },
        )
        return _err_response(t("errors.cannot_apply_changes"), category="state", level="warning", log_module=__name__)

    if not ctx:
        api._release_apply_slot(run_id)
        return _err_response(t("errors.plan_unavailable"), category="state", level="warning", log_module=__name__)
    cfg, run_paths, rows, log_fn, store = ctx

    if not rows:
        api._release_apply_slot(run_id)
        return _err_response(t("errors.plan_empty_or_missing"), category="state", level="warning", log_module=__name__)

    incoming = decisions if isinstance(decisions, dict) else {}
    disk_decisions = api._load_decisions_from_validation(run_paths)
    merged_decisions = api._merge_decisions(incoming, disk_decisions)
    decision_presence = {key for key, value in merged_decisions.items() if isinstance(value, dict)}
    safe_decisions = api._normalize_decisions_for_rows(rows, merged_decisions)
    try:
        state.atomic_write_json(run_paths.validation_json, safe_decisions)
    except (OSError, PermissionError) as exc:
        log_fn("WARN", f"Validation auto-save non ecrite: {exc}")

    # H-2 audit QA 20260428 : pre-check espace disque (uniquement apply reel).
    # Refuser si le volume cible n'a pas assez de place pour absorber la somme
    # des fichiers a deplacer (avec marge 10%). Evite l'apply qui s'arrete a
    # mi-parcours, laissant DB/FS dans un etat partiel (cf CR-1).
    if not dry_run:
        ok_disk, disk_info = check_disk_space_for_apply(cfg, rows, decision_presence)
        if not ok_disk:
            api._release_apply_slot(run_id)
            _disk_msg = disk_info.get("message") or t("errors.disk_space_insufficient")
            log_fn("ERROR", _disk_msg)
            return {
                "ok": False,
                "message": _disk_msg,
                "disk_check": disk_info,
            }
        log_fn("INFO", disk_info.get("message", "Espace disque verifie."))

    return {
        "ok": True,
        "_ctx": (cfg, run_paths, rows, log_fn, store, safe_decisions, decision_presence),
    }


def _execute_apply(
    cfg: Any,
    rows: List[Any],
    safe_decisions: Dict[str, Any],
    decision_presence: Any,
    *,
    dry_run: bool,
    quarantine_unapproved: bool,
    log_fn: Callable[[str, str], None],
    run_paths: Any,
    store: SQLiteStore,
    api: Any,
    run_id: str,
    batch_state: List[Any],
    preview_ops_out: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Any, Optional[str], int]:
    """Applique un batch.

    P1.3 : `preview_ops_out` (si fournie) collecte les ops même en dry_run pour
    permettre à l'UI de construire une vue "avant/après" structurée sans
    toucher au filesystem. Ne change rien quand le caller ne la fournit pas.
    """
    try:
        core.find_duplicate_targets(cfg, rows, safe_decisions)
    except (OSError, PermissionError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        msg = t("errors.duplicate_check_failed", detail=str(exc))
        log_fn("ERROR", msg)
        raise _DuplicateCheckError(msg) from exc

    apply_batch_id: Optional[str] = None
    op_index_holder = [0]
    auditor: Optional[ApplyAuditLogger] = None

    def record_apply_op(payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        # P1.3 : collecter les ops même en dry_run si une liste est fournie.
        if preview_ops_out is not None:
            with contextlib.suppress(TypeError, ValueError):
                preview_ops_out.append(dict(payload))
        # P2.3 : journal d'audit JSONL (seulement en apply réel, pas en dry_run)
        if auditor is not None:
            op_type = str(payload.get("op_type") or "").upper()
            row_id = str(payload.get("row_id") or "") or None
            if op_type == "MOVE_FILE":
                auditor.op_move_file(
                    row_id=row_id,
                    src=str(payload.get("src_path") or ""),
                    dst=str(payload.get("dst_path") or ""),
                    reversible=_to_bool(payload.get("reversible"), True),
                    sha1=(str(payload.get("src_sha1")) if payload.get("src_sha1") else None),
                    size=(int(payload["src_size"]) if payload.get("src_size") is not None else None),
                )
            elif op_type == "MOVE_DIR":
                auditor.op_move_dir(
                    row_id=row_id,
                    src=str(payload.get("src_path") or ""),
                    dst=str(payload.get("dst_path") or ""),
                    reversible=_to_bool(payload.get("reversible"), True),
                    sha1=(str(payload.get("src_sha1")) if payload.get("src_sha1") else None),
                    size=(int(payload["src_size"]) if payload.get("src_size") is not None else None),
                )
            elif op_type == "MKDIR":
                auditor.op_mkdir(path=str(payload.get("dst_path") or payload.get("src_path") or ""))
        if apply_batch_id is None:
            return
        try:
            op_index_holder[0] += 1
            store.append_apply_operation(
                batch_id=apply_batch_id,
                op_index=op_index_holder[0],
                op_type=str(payload.get("op_type") or "MOVE"),
                src_path=str(payload.get("src_path") or ""),
                dst_path=str(payload.get("dst_path") or ""),
                reversible=_to_bool(payload.get("reversible"), True),
                ts=float(payload.get("ts") or time.time()),
                row_id=str(payload.get("row_id") or "") or None,
                src_sha1=str(payload.get("src_sha1") or "") or None,
                src_size=int(payload["src_size"]) if payload.get("src_size") is not None else None,
            )
        except (OSError, TypeError, ValueError) as exc:
            log_fn("WARN", f"Journal operation apply ignoree: {exc}")

    if not bool(dry_run):
        try:
            apply_batch_id = store.insert_apply_batch(
                run_id=run_id,
                dry_run=False,
                quarantine_unapproved=bool(quarantine_unapproved),
                status="PENDING",
                summary={},
                app_version=api._app_version,
            )
            batch_state[0] = apply_batch_id
        except (OSError, TypeError, ValueError) as exc:
            apply_batch_id = None
            log_fn("WARN", f"Journal apply indisponible: {exc}")

        # P2.3 : ouvrir le journal d'audit JSONL pour ce batch (apply réel uniquement)
        try:
            auditor = ApplyAuditLogger.open_for_run(
                run_paths,
                batch_id=str(apply_batch_id or ""),
                run_id=run_id,
            )
            auditor.start(
                dry_run=False,
                total_rows=len(rows),
                quarantine_unapproved=bool(quarantine_unapproved),
            )
        except (OSError, TypeError, ValueError) as exc:
            log_fn("WARN", f"Journal audit apply indisponible : {exc}")
            auditor = None

    # Multi-root : grouper les rows par source_root et appeler apply_rows par root
    rows_by_root: Dict[str, List[Any]] = {}
    for row in rows:
        rk = getattr(row, "source_root", None) or str(cfg.root)
        rows_by_root.setdefault(rk, []).append(row)

    root_keys = list(rows_by_root.keys())
    result = None

    for root_str in root_keys:
        root_rows = rows_by_root[root_str]
        root_path = Path(root_str)
        # Creer un cfg avec le bon root pour ce groupe
        if root_path != cfg.root and root_path.exists():
            cfg_for_root = core.Config(
                root=root_path,
                enable_collection_folder=cfg.enable_collection_folder,
                collection_root_name=cfg.collection_root_name,
                empty_folders_folder_name=cfg.empty_folders_folder_name,
                move_empty_folders_enabled=cfg.move_empty_folders_enabled,
                empty_folders_scope=cfg.empty_folders_scope,
                cleanup_residual_folders_enabled=cfg.cleanup_residual_folders_enabled,
                cleanup_residual_folders_folder_name=cfg.cleanup_residual_folders_folder_name,
                cleanup_residual_folders_scope=cfg.cleanup_residual_folders_scope,
                cleanup_residual_include_nfo=cfg.cleanup_residual_include_nfo,
                cleanup_residual_include_images=cfg.cleanup_residual_include_images,
                cleanup_residual_include_subtitles=cfg.cleanup_residual_include_subtitles,
                cleanup_residual_include_texts=cfg.cleanup_residual_include_texts,
                video_exts=cfg.video_exts,
                side_exts=cfg.side_exts,
                generic_side_files=cfg.generic_side_files,
                detect_extras_in_single_folder=cfg.detect_extras_in_single_folder,
                extras_size_ratio=cfg.extras_size_ratio,
                skip_tv_like=cfg.skip_tv_like,
                enable_tv_detection=cfg.enable_tv_detection,
                title_match_min_cov=cfg.title_match_min_cov,
                title_match_min_seq=cfg.title_match_min_seq,
                max_year_delta_when_name_has_year=cfg.max_year_delta_when_name_has_year,
                enable_tmdb=cfg.enable_tmdb,
                tmdb_language=cfg.tmdb_language,
                incremental_scan_enabled=cfg.incremental_scan_enabled,
            )
        else:
            cfg_for_root = cfg

        if len(root_keys) > 1:
            log_fn("INFO", f"Apply root: {root_str} ({len(root_rows)} row(s))")

        # P1.3 : on passe toujours record_apply_op (même en dry_run) pour que
        # `preview_ops_out` puisse collecter les ops. La closure skipe elle-même
        # l'écriture BDD si apply_batch_id est None (cas du dry_run).
        # CR-1 audit QA 20260429 : en apply reel, on enrobe record_apply_op
        # dans un RecordOpWithJournal pour propager store + batch_id aux
        # sites de shutil.move via atomic_move() (cf cinesort.app.move_journal).
        record_op_for_apply: Any = record_apply_op
        if not dry_run and apply_batch_id is not None:
            record_op_for_apply = RecordOpWithJournal(
                record_apply_op,
                store=store,
                batch_id=str(apply_batch_id),
            )
        partial = _apply_rows_fn(
            cfg_for_root,
            root_rows,
            safe_decisions,
            dry_run=bool(dry_run),
            quarantine_unapproved=bool(quarantine_unapproved),
            log=log_fn,
            run_review_root=(run_paths.run_dir / "_review"),
            decision_presence=decision_presence,
            record_op=record_op_for_apply,
        )

        if result is None:
            result = partial
        else:
            # Merge les compteurs du résultat partiel
            from dataclasses import fields as _dc_fields

            for f in _dc_fields(partial):
                val = getattr(partial, f.name)
                if isinstance(val, int):
                    setattr(result, f.name, getattr(result, f.name, 0) + val)
                elif isinstance(val, dict) and f.name == "skip_reasons":
                    merged = dict(getattr(result, f.name, {}))
                    for k, v in val.items():
                        merged[k] = merged.get(k, 0) + int(v)
                    setattr(result, f.name, merged)

    if result is None:
        result = core.ApplyResult()
        result.total_rows = len(rows)

    # P2.3 : clore le journal d'audit avec les compteurs finaux.
    if auditor is not None:
        try:
            auditor.end(
                status="DONE" if getattr(result, "errors", 0) == 0 else "PARTIAL",
                counts={
                    "renames": int(getattr(result, "renames", 0) or 0),
                    "moves": int(getattr(result, "moves", 0) or 0),
                    "skipped": int(getattr(result, "skipped", 0) or 0),
                    "quarantined": int(getattr(result, "quarantined", 0) or 0),
                    "errors": int(getattr(result, "errors", 0) or 0),
                },
            )
        finally:
            auditor.close()

    batch_state[1] = op_index_holder[0]
    return result, apply_batch_id, op_index_holder[0]


def _cleanup_apply(
    result: Any,
    apply_batch_id: Optional[str],
    op_index: int,
    *,
    store: SQLiteStore,
    log_fn: Callable[[str, str], None],
    run_id: str,
    dry_run: bool,
    rows: List[Any],
) -> Tuple[Dict[str, int], int, int, Dict[str, Any]]:
    cleanup_diag = result.cleanup_residual_diagnostic if isinstance(result.cleanup_residual_diagnostic, dict) else {}
    skip_reason_order = [
        core.SKIP_REASON_NON_VALIDE,
        core.SKIP_REASON_VALIDATION_ABSENTE,
        core.SKIP_REASON_NOOP_DEJA_CONFORME,
        core.SKIP_REASON_OPTION_DESACTIVEE,
        core.SKIP_REASON_MERGED,
        core.SKIP_REASON_CONFLIT_QUARANTAINE,
        core.SKIP_REASON_ERREUR_PRECEDENTE,
        core.SKIP_REASON_AUTRE,
    ]
    skip_counts = {reason: int((result.skip_reasons or {}).get(reason, 0)) for reason in skip_reason_order}
    applied_count = int(result.applied_count or 0)
    total_rows = int(result.considered_rows or len(rows))
    if apply_batch_id is not None:
        try:
            store.close_apply_batch(
                batch_id=apply_batch_id,
                status="DONE",
                summary={
                    "run_id": run_id,
                    "dry_run": False,
                    "applied_count": applied_count,
                    "total_rows": total_rows,
                    "errors": int(result.errors or 0),
                    "skipped": int(result.skipped or 0),
                    "skip_reasons": skip_counts,
                    "ops_count": int(op_index),
                },
            )
        except (OSError, TypeError, ValueError) as exc:
            log_fn("WARN", f"Journal apply non finalise: {exc}")
    log_fn(
        "INFO",
        "=== APPLY done "
        f"renames={result.renames} moves={result.moves} mkdirs={result.mkdirs} "
        f"collection_moves={result.collection_moves} quarantined={result.quarantined} "
        f"skipped={result.skipped} errors={result.errors} "
        f"merges_count={result.merges_count} "
        f"duplicates_identical_moved_count={result.duplicates_identical_moved_count} "
        f"duplicates_identical_deleted_count={result.duplicates_identical_deleted_count} "
        f"conflicts_quarantined_count={result.conflicts_quarantined_count} "
        f"sidecar_conflicts_kept_both_count={result.sidecar_conflicts_kept_both_count} "
        f"conflicts_sidecars_quarantined_count={result.conflicts_sidecars_quarantined_count} "
        f"leftovers_moved_count={result.leftovers_moved_count} "
        f"source_dirs_deleted_count={result.source_dirs_deleted_count} "
        f"empty_folders_moved_count={result.empty_folders_moved_count} "
        f"cleanup_residual_folders_moved_count={result.cleanup_residual_folders_moved_count} ===",
    )
    log_fn(
        "INFO",
        "RESULTAT APPLY: "
        f"appliquees {applied_count}/{total_rows}, skippees {result.skipped} "
        "("
        f"non_valide={skip_counts[core.SKIP_REASON_NON_VALIDE]}, "
        f"validation_absente={skip_counts[core.SKIP_REASON_VALIDATION_ABSENTE]}, "
        f"deja_conforme={skip_counts[core.SKIP_REASON_NOOP_DEJA_CONFORME]}, "
        f"option_desactivee={skip_counts[core.SKIP_REASON_OPTION_DESACTIVEE]}, "
        f"fusionne={skip_counts[core.SKIP_REASON_MERGED]}, "
        f"conflit_quarantaine={skip_counts[core.SKIP_REASON_CONFLIT_QUARANTAINE]}, "
        f"erreur_precedente={skip_counts[core.SKIP_REASON_ERREUR_PRECEDENTE]}, "
        f"autre={skip_counts[core.SKIP_REASON_AUTRE]}"
        ").",
    )
    if cleanup_diag:
        log_fn(
            "INFO",
            "NETTOYAGE RESIDUEL: "
            f"enabled={bool(cleanup_diag.get('enabled'))} "
            f"scope={cleanup_diag.get('scope')} "
            f"status_pre={cleanup_diag.get('status')} "
            f"status_post={cleanup_diag.get('status_post')} "
            f"eligible={int(cleanup_diag.get('probable_eligible_count') or 0)} "
            f"moved={int(cleanup_diag.get('moved_count') or 0)} "
            f"video_blocked={int(cleanup_diag.get('has_video_count') or 0)} "
            f"ambiguous={int(cleanup_diag.get('ambiguous_count') or 0)}",
        )
    return skip_counts, applied_count, total_rows, cleanup_diag


def _summarize_apply(
    result: Any,
    skip_counts: Dict[str, int],
    applied_count: int,
    total_rows: int,
    cleanup_diag: Dict[str, Any],
    *,
    cfg: Any,
    run_paths: Any,
    log_fn: Callable[[str, str], None],
    dry_run: bool,
    rows: List[Any],
    cleanup_scope_label: Callable[[str], str],
    cleanup_status_label: Callable[..., str],
    cleanup_reason_label: Callable[[str], str],
) -> None:
    try:
        summary_marker = "\n=== RESUME APPLICATION ===\n"
        summary_block = (
            summary_marker + "SITUATION APPLICATION\n"
            f"- Lignes du plan : {len(rows)}\n"
            f"- Lignes considerees : {total_rows}\n"
            f"- Appliquees : {applied_count}/{total_rows}\n"
            f"- Restees a verifier / non appliquees : {result.skipped}\n"
            f"- Erreurs : {int(result.errors or 0)}\n"
            "\n"
            "CE QUI N'A PAS ETE APPLIQUE\n"
            f"- {core.SKIP_REASON_LABELS_FR[core.SKIP_REASON_NON_VALIDE]}: {skip_counts[core.SKIP_REASON_NON_VALIDE]}\n"
            f"- {core.SKIP_REASON_LABELS_FR[core.SKIP_REASON_VALIDATION_ABSENTE]}: {skip_counts[core.SKIP_REASON_VALIDATION_ABSENTE]}\n"
            f"- {core.SKIP_REASON_LABELS_FR[core.SKIP_REASON_NOOP_DEJA_CONFORME]}: {skip_counts[core.SKIP_REASON_NOOP_DEJA_CONFORME]}\n"
            f"- {core.SKIP_REASON_LABELS_FR[core.SKIP_REASON_OPTION_DESACTIVEE]}: {skip_counts[core.SKIP_REASON_OPTION_DESACTIVEE]}\n"
            f"- {core.SKIP_REASON_LABELS_FR[core.SKIP_REASON_MERGED]}: {skip_counts[core.SKIP_REASON_MERGED]}\n"
            f"- {core.SKIP_REASON_LABELS_FR[core.SKIP_REASON_CONFLIT_QUARANTAINE]}: {skip_counts[core.SKIP_REASON_CONFLIT_QUARANTAINE]}\n"
            f"- {core.SKIP_REASON_LABELS_FR[core.SKIP_REASON_ERREUR_PRECEDENTE]}: {skip_counts[core.SKIP_REASON_ERREUR_PRECEDENTE]}\n"
            f"- {core.SKIP_REASON_LABELS_FR[core.SKIP_REASON_AUTRE]}: {skip_counts[core.SKIP_REASON_AUTRE]}\n"
            "\n"
            "NETTOYAGE ET RANGEMENT\n"
            f"- Fusions realisees : {result.merges_count}\n"
            f"- Duplicats identiques deplaces : {result.duplicates_identical_moved_count}\n"
            f"- Duplicats identiques supprimes logiquement : {result.duplicates_identical_deleted_count}\n"
            f"- Conflits isoles en _review : {result.conflicts_quarantined_count}\n"
            f"- Conflits sidecars gardes des deux cotes : {result.sidecar_conflicts_kept_both_count}\n"
            f"- Conflits sidecars isoles : {result.conflicts_sidecars_quarantined_count}\n"
            f"- Leftovers deplaces : {result.leftovers_moved_count}\n"
            f"- Dossiers sources supprimes : {result.source_dirs_deleted_count}\n"
            f"- Dossiers vides deplaces (_Vide) : {result.empty_folders_moved_count}\n"
            f"- Dossiers residuels deplaces (_Dossier Nettoyage) : {result.cleanup_residual_folders_moved_count}\n"
        )
        if cleanup_diag:
            families = cleanup_diag.get("families") if isinstance(cleanup_diag.get("families"), list) else []
            families_label = ", ".join(str(item) for item in families if str(item).strip()) or "Aucune"
            sample_eligible = (
                cleanup_diag.get("sample_eligible_dirs")
                if isinstance(cleanup_diag.get("sample_eligible_dirs"), list)
                else []
            )
            sample_video = (
                cleanup_diag.get("sample_video_blocked_dirs")
                if isinstance(cleanup_diag.get("sample_video_blocked_dirs"), list)
                else []
            )
            sample_ambiguous = (
                cleanup_diag.get("sample_ambiguous_dirs")
                if isinstance(cleanup_diag.get("sample_ambiguous_dirs"), list)
                else []
            )
            summary_block += (
                "\n"
                "DETAIL NETTOYAGE RESIDUEL\n"
                f"- Active : {'oui' if bool(cleanup_diag.get('enabled')) else 'non'}\n"
                f"- Dossier cible : {cleanup_diag.get('target_folder_name') or cfg.cleanup_residual_folders_folder_name}\n"
                f"- Scope : {cleanup_scope_label(cleanup_diag.get('scope') or cfg.cleanup_residual_folders_scope)}\n"
                f"- Familles actives : {families_label}\n"
                f"- Statut avant application : {cleanup_status_label(cleanup_diag.get('status') or 'disabled')}\n"
                f"- Statut apres Apply : {cleanup_status_label(cleanup_diag.get('status_post') or 'disabled', dry_run=dry_run)}\n"
                f"- Raison principale : {cleanup_reason_label(cleanup_diag.get('reason_code') or 'disabled')}\n"
                f"- Probablement eligibles avant application : {int(cleanup_diag.get('probable_eligible_count') or 0)}\n"
                f"- Dossiers deplaces : {int(cleanup_diag.get('moved_count') or 0)}\n"
                f"- Dossiers laisses en place : {int(cleanup_diag.get('left_in_place_count') or 0)}\n"
                f"- Bloques par video : {int(cleanup_diag.get('has_video_count') or 0)}\n"
                f"- Bloques par ambiguite : {int(cleanup_diag.get('ambiguous_count') or 0)}\n"
                f"- Bloques par symlink : {int(cleanup_diag.get('symlink_count') or 0)}\n"
                f"- Relevent de _Vide : {int(cleanup_diag.get('empty_dir_count') or 0)}\n"
                f"- Diagnostic : {cleanup_diag.get('message_post') or cleanup_diag.get('message') or ''}\n"
            )
            if sample_eligible:
                summary_block += (
                    "- Exemples probablement eligibles : "
                    + " | ".join(str(item) for item in sample_eligible[:5])
                    + "\n"
                )
            if sample_video:
                summary_block += (
                    "- Exemples bloques par video : " + " | ".join(str(item) for item in sample_video[:5]) + "\n"
                )
            if sample_ambiguous:
                summary_block += (
                    "- Exemples bloques par ambiguite : "
                    + " | ".join(str(item) for item in sample_ambiguous[:5])
                    + "\n"
                )
        action_lines: List[str] = []
        review_root = run_paths.run_dir / "_review"
        if result.conflicts_quarantined_count > 0:
            action_lines.append(f"- Conflits fichiers a verifier: {review_root / '_conflicts'}")
        if result.conflicts_sidecars_quarantined_count > 0:
            action_lines.append(f"- Conflits sidecars conserves: {review_root / '_conflicts_sidecars'}")
        if result.duplicates_identical_moved_count > 0:
            action_lines.append(f"- Duplicates identiques deplaces: {review_root / '_duplicates_identical'}")
        if result.leftovers_moved_count > 0:
            action_lines.append(f"- Leftovers deplaces: {review_root / '_leftovers'}")
        if result.empty_folders_moved_count > 0:
            action_lines.append(
                f"- Dossiers vides deplaces (inclus dans l'undo du run): {cfg.root / cfg.empty_folders_folder_name}"
            )
        if result.cleanup_residual_folders_moved_count > 0:
            action_lines.append(
                "- Dossiers residuels deplaces (inclus dans l'undo du run): "
                f"{cfg.root / cfg.cleanup_residual_folders_folder_name}"
            )
        elif cleanup_diag and bool(cleanup_diag.get("enabled")):
            action_lines.append(
                "- Dossiers residuels: aucun deplacement. "
                f"{cleanup_diag.get('message_post') or cleanup_diag.get('message') or ''}"
            )
        if not action_lines:
            action_lines.append("- Aucun point d'attention bloquant apres apply.")
        summary_block += "\nA RETENIR AVANT LA SUITE\n" + "\n".join(action_lines) + "\n"

        existing_text = ""
        if run_paths.summary_txt.exists():
            existing_text = run_paths.summary_txt.read_text(encoding="utf-8")
        marker_idx = existing_text.find(summary_marker)
        if marker_idx >= 0:
            existing_text = existing_text[:marker_idx].rstrip() + "\n"

        final_text = existing_text.rstrip("\n")
        if final_text:
            final_text += "\n"
        final_text += summary_block.lstrip("\n")
        run_paths.summary_txt.write_text(final_text, encoding="utf-8")
    except (OSError, PermissionError, KeyError, TypeError, ValueError) as exc:
        log_fn("WARN", f"Resume application non ecrit: {exc}")


def _read_jellyfin_settings(api: Any) -> Dict[str, Any]:
    """Lit les settings Jellyfin. Retourne {} si indisponible ou desactive."""
    try:
        data = read_settings(api._state_dir)
    except (OSError, PermissionError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {}
    if not _to_bool(data.get("jellyfin_enabled"), False):
        return {}
    url = str(data.get("jellyfin_url") or "").strip()
    api_key = str(data.get("jellyfin_api_key") or "").strip()
    if not url or not api_key:
        return {}
    return data


def _make_jellyfin_client(data: Dict[str, Any]) -> Any:
    """Cree un JellyfinClient depuis les settings. Retourne None si impossible."""
    from cinesort.infra.jellyfin_client import JellyfinClient

    url = str(data.get("jellyfin_url") or "").strip()
    api_key = str(data.get("jellyfin_api_key") or "").strip()
    timeout_s = float(data.get("jellyfin_timeout_s") or 10.0)
    return JellyfinClient(url, api_key, timeout_s=timeout_s)


def _trigger_jellyfin_refresh(api: Any, log_fn: Callable[[str, str], None], *, dry_run: bool) -> None:
    """Déclenche un refresh Jellyfin post-apply si configuré. Jamais en dry-run."""
    if dry_run:
        return
    data = _read_jellyfin_settings(api)
    if not data:
        return
    if not _to_bool(data.get("jellyfin_refresh_on_apply"), True):
        return
    try:
        client = _make_jellyfin_client(data)
        client.refresh_library()
        log_fn("INFO", "Jellyfin : refresh bibliothèque déclenché avec succès.")
    # BUG-1 (v7.8.0) : IntegrationError remplace except Exception annote intentionnel.
    # OSError/RequestException couvrent les echecs reseau bruts non wrappes par le client.
    except (IntegrationError, OSError, requests.RequestException) as exc:
        _log.warning("Jellyfin refresh post-apply échoué: %s", exc)
        log_fn("WARN", f"Jellyfin : échec refresh bibliothèque — {exc}")


def _trigger_plex_refresh(api: Any, log_fn: Callable[[str, str], None], *, dry_run: bool) -> None:
    """Declenche un refresh Plex post-apply si configure. Jamais en dry-run."""
    if dry_run:
        return
    try:
        settings = api.settings.get_settings()
    except (OSError, PermissionError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return
    if not _to_bool(settings.get("plex_enabled"), False):
        return
    if not _to_bool(settings.get("plex_refresh_on_apply"), True):
        return
    plex_url = str(settings.get("plex_url") or "").strip()
    plex_token = str(settings.get("plex_token") or "").strip()
    plex_lib = str(settings.get("plex_library_id") or "").strip()
    if not plex_url or not plex_token or not plex_lib:
        return
    try:
        from cinesort.infra.plex_client import PlexClient

        timeout_s = float(settings.get("plex_timeout_s") or 10)
        client = PlexClient(plex_url, plex_token, timeout_s=timeout_s)
        client.refresh_library(plex_lib)
        log_fn("INFO", "Plex : refresh section declenche avec succes.")
    # BUG-1 (v7.8.0) : IntegrationError remplace except Exception annote intentionnel.
    except (IntegrationError, OSError, requests.RequestException) as exc:
        _log.warning("Plex refresh post-apply echoue: %s", exc)
        log_fn("WARN", f"Plex : echec refresh section — {exc}")


def refresh_jellyfin_library_now(api: Any) -> Dict[str, Any]:
    """Cf #92 quick win #1 : declenche un refresh Jellyfin a la demande.

    Difference avec `_trigger_jellyfin_refresh` (interne, post-apply) :
    - Ne respecte PAS `dry_run` (toujours execute)
    - Ne respecte PAS le toggle `jellyfin_refresh_on_apply` (l'utilisateur
      a explicitement clique le bouton)
    - Verifie seulement que Jellyfin est CONFIGURE (url + api_key)

    Le scenario : apres un apply, l'utilisateur veut forcer le refresh
    Jellyfin sans attendre le tick suivant ou re-lancer un apply.
    """
    data = _read_jellyfin_settings(api)
    if not data:
        return _err_response(
            "Jellyfin non configure ou desactive.", category="config", level="info", log_module=__name__
        )
    try:
        client = _make_jellyfin_client(data)
        client.refresh_library()
        _log.info("api: refresh_jellyfin_library_now declenche")
        return {"ok": True, "message": "Refresh Jellyfin declenche."}
    except (IntegrationError, OSError, requests.RequestException) as exc:
        _log.warning("refresh_jellyfin_library_now echoue: %s", exc)
        return _err_response(f"Echec refresh Jellyfin : {exc}", category="resource", level="error", log_module=__name__)


def refresh_plex_library_now(api: Any) -> Dict[str, Any]:
    """Cf #92 quick win #1 : declenche un refresh Plex a la demande.

    Symetrique de `refresh_jellyfin_library_now`. Verifie url + token +
    library_id (ce dernier n'est pas necessaire pour Jellyfin).
    """
    try:
        settings = api.settings.get_settings()
    except (OSError, PermissionError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(f"Echec lecture settings : {exc}", category="runtime", level="error", log_module=__name__)
    if not _to_bool(settings.get("plex_enabled"), False):
        return _err_response("Plex non configure ou desactive.", category="config", level="info", log_module=__name__)
    plex_url = str(settings.get("plex_url") or "").strip()
    plex_token = str(settings.get("plex_token") or "").strip()
    plex_lib = str(settings.get("plex_library_id") or "").strip()
    if not plex_url or not plex_token or not plex_lib:
        return _err_response(
            "Plex incomplet (URL, token ou library_id manquant).",
            category="config",
            level="info",
            log_module=__name__,
        )
    try:
        from cinesort.infra.plex_client import PlexClient

        timeout_s = float(settings.get("plex_timeout_s") or 10)
        client = PlexClient(plex_url, plex_token, timeout_s=timeout_s)
        client.refresh_library(plex_lib)
        _log.info("api: refresh_plex_library_now declenche")
        return {"ok": True, "message": "Refresh Plex declenche."}
    except (IntegrationError, OSError, requests.RequestException) as exc:
        _log.warning("refresh_plex_library_now echoue: %s", exc)
        return _err_response(f"Echec refresh Plex : {exc}", category="resource", level="error", log_module=__name__)


def _snapshot_jellyfin_watched(api: Any, log_fn: Callable[[str, str], None]) -> Optional[Dict[str, Any]]:
    """Capture les statuts watched Jellyfin avant apply. Retourne None si desactive."""
    data = _read_jellyfin_settings(api)
    if not data:
        return None
    if not _to_bool(data.get("jellyfin_sync_watched"), True):
        return None
    try:
        from cinesort.app.jellyfin_sync import snapshot_watched

        client = _make_jellyfin_client(data)
        user_id = str(data.get("jellyfin_user_id") or "").strip()
        if not user_id:
            info = client.validate_connection()
            user_id = info.get("user_id", "")
        if not user_id:
            return None
        snapshot = snapshot_watched(client, user_id)
        if snapshot:
            log_fn("INFO", f"Jellyfin sync : {len(snapshot)} film(s) vu(s) sauvegardé(s).")
        return {"snapshot": snapshot, "user_id": user_id, "settings": data}
    # BUG-1 (v7.8.0) : IntegrationError remplace except Exception annote intentionnel.
    except (IntegrationError, OSError, requests.RequestException) as exc:
        _log.warning("Jellyfin snapshot watched échoué: %s", exc)
        log_fn("WARN", f"Jellyfin sync : échec snapshot — {exc}")
        return None


def _restore_jellyfin_watched(
    api: Any,
    log_fn: Callable[[str, str], None],
    watched_ctx: Dict[str, Any],
    store: Any,
    apply_batch_id: Optional[str],
) -> None:
    """Restaure les statuts watched Jellyfin apres apply + refresh."""
    if not watched_ctx or not apply_batch_id:
        return
    snapshot = watched_ctx.get("snapshot", {})
    if not snapshot:
        return
    user_id = watched_ctx.get("user_id", "")
    data = watched_ctx.get("settings", {})
    if not user_id or not data:
        return

    try:
        from cinesort.app.jellyfin_sync import restore_watched

        client = _make_jellyfin_client(data)
        operations = store.list_apply_operations(batch_id=apply_batch_id)
        result = restore_watched(client, user_id, snapshot, operations)
        if result.restored > 0:
            log_fn("INFO", f"Jellyfin sync : {result.restored} statut(s) vu restauré(s).")
        if result.not_found > 0:
            log_fn("WARN", f"Jellyfin sync : {result.not_found} film(s) non retrouvé(s) après re-indexation.")
        if result.errors > 0:
            log_fn("WARN", f"Jellyfin sync : {result.errors} erreur(s) lors de la restauration.")
    # BUG-1 (v7.8.0) : IntegrationError remplace except Exception annote intentionnel.
    except (IntegrationError, OSError, requests.RequestException) as exc:
        _log.warning("Jellyfin restore watched échoué: %s", exc)
        log_fn("WARN", f"Jellyfin sync : échec restauration — {exc}")


def apply_changes(
    api: Any,
    run_id: str,
    decisions: Dict[str, Dict[str, Any]],
    dry_run: bool,
    quarantine_unapproved: bool,
    *,
    cleanup_scope_label: Callable[[str], str],
    cleanup_status_label: Callable[..., str],
    cleanup_reason_label: Callable[[str], str],
) -> Dict[str, Any]:
    _log.info("api: apply run_id=%s dry_run=%s", run_id, dry_run)
    validation = _validate_apply(api, run_id, decisions, dry_run, quarantine_unapproved)
    if not validation.get("ok"):
        return validation
    cfg, run_paths, rows, log_fn, store, safe_decisions, decision_presence = validation["_ctx"]

    log_fn("INFO", f"=== APPLY start (dry_run={dry_run}, quarantine={quarantine_unapproved}) ===")
    batch_state: List[Any] = [None, 0]  # [apply_batch_id, op_index] — mutable for _execute_apply

    # Jellyfin Phase 2 : snapshot watched AVANT apply
    watched_ctx = None
    if not dry_run:
        watched_ctx = _snapshot_jellyfin_watched(api, log_fn)

    try:
        try:
            result, batch_id, ops = _execute_apply(
                cfg,
                rows,
                safe_decisions,
                decision_presence,
                dry_run=dry_run,
                quarantine_unapproved=quarantine_unapproved,
                log_fn=log_fn,
                run_paths=run_paths,
                store=store,
                api=api,
                run_id=run_id,
                batch_state=batch_state,
            )
        except _DuplicateCheckError as exc:
            return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
        apply_batch_id = batch_id
        op_index = ops

        skip_counts, applied_count, total_rows, cleanup_diag = _cleanup_apply(
            result,
            apply_batch_id,
            op_index,
            store=store,
            log_fn=log_fn,
            run_id=run_id,
            dry_run=dry_run,
            rows=rows,
        )

        _summarize_apply(
            result,
            skip_counts,
            applied_count,
            total_rows,
            cleanup_diag,
            cfg=cfg,
            run_paths=run_paths,
            log_fn=log_fn,
            dry_run=dry_run,
            rows=rows,
            cleanup_scope_label=cleanup_scope_label,
            cleanup_status_label=cleanup_status_label,
            cleanup_reason_label=cleanup_reason_label,
        )

        _trigger_jellyfin_refresh(api, log_fn, dry_run=dry_run)
        _trigger_plex_refresh(api, log_fn, dry_run=dry_run)

        # Jellyfin Phase 2 : restore watched APRES refresh
        if watched_ctx:
            _restore_jellyfin_watched(api, log_fn, watched_ctx, store, apply_batch_id)

        if not dry_run:
            api._notify.notify(
                "apply_done",
                t("notifications.title_apply_done"),
                t(
                    "notifications.apply_done_body",
                    renames=result.renames,
                    moves=result.moves,
                    errors=result.errors,
                ),
            )
            import time as _time

            _hook_data = {
                "run_id": run_id,
                "ts": _time.time(),
                "data": {
                    "renames": result.renames,
                    "moves": result.moves,
                    "errors": result.errors,
                    "batch_id": apply_batch_id,
                },
            }
            api._dispatch_plugin_hook("post_apply", _hook_data)
            api._dispatch_email("post_apply", _hook_data)

            # CR-2 audit QA 20260429 : backup auto de la DB apres apply reel.
            # Tolerant — un echec n'empeche pas le retour du resultat applique.
            try:
                backup_path = store.backup_now(trigger="post_apply")
                if backup_path is not None:
                    log_fn("INFO", f"DB backup cree apres apply: {backup_path.name}")
            except Exception as backup_exc:
                log_fn("WARN", f"DB backup post-apply ignore: {backup_exc}")

        return {"ok": True, "result": result.__dict__, "apply_batch_id": apply_batch_id}
    # except Exception intentionnel : boundary API endpoint apply_changes
    except Exception as exc:
        apply_batch_id = batch_state[0]
        op_index = batch_state[1]
        if apply_batch_id is not None:
            try:
                store.close_apply_batch(
                    batch_id=apply_batch_id,
                    status="FAILED",
                    summary={
                        "run_id": run_id,
                        "dry_run": False,
                        "error": str(exc),
                        "ops_count": int(op_index),
                    },
                )
            except (OSError, RuntimeError, TypeError, ValueError) as close_exc:
                log_fn(
                    "WARN",
                    f"Journal apply FAILED non finalise run_id={run_id} batch_id={apply_batch_id}: {close_exc}",
                )
        log_fn("ERROR", f"Echec application : {exc}")
        api.log_api_exception(
            "apply",
            exc,
            run_id=run_id,
            store=store,
            extra={
                "dry_run": bool(dry_run),
                "quarantine_unapproved": bool(quarantine_unapproved),
                "decision_count": len(decisions),
            },
        )
        return _err_response(t("errors.cannot_apply_changes"), category="state", level="warning", log_module=__name__)
    finally:
        api._release_apply_slot(run_id)


@requires_valid_run_id
def export_apply_audit(
    api: Any,
    run_id: str,
    batch_id: Optional[str] = None,
    *,
    as_format: str = "json",
) -> Dict[str, Any]:
    """P2.3 : expose le journal d'audit JSONL d'un run pour l'UI.

    Retourne soit un dict structuré (format='json', défaut), soit une
    chaîne texte JSONL brute (format='jsonl'), soit un CSV ('csv').

    Filtrage optionnel par batch_id.
    """
    found = api._find_run_row(run_id)
    if not found:
        return _err_response(t("errors.run_not_found"), category="resource", level="info", log_module=__name__)
    row, _store = found
    state_dir = normalize_user_path(row.get("state_dir"), api._state_dir)
    run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)

    try:
        events = read_apply_audit(run_paths.run_dir, batch_id=batch_id)
    except (OSError, PermissionError, ValueError, TypeError) as exc:
        api.log_api_exception("export_apply_audit", exc, run_id=run_id, extra={"batch_id": batch_id})
        return _err_response(
            t("errors.audit_log_read_failed"), category="resource", level="warning", log_module=__name__
        )

    fmt = str(as_format or "json").lower()
    if fmt == "jsonl":
        import json as _json

        content = "\n".join(_json.dumps(e, ensure_ascii=False, sort_keys=True) for e in events)
        return {"ok": True, "format": "jsonl", "content": content, "count": len(events)}
    if fmt == "csv":
        import csv as _csv
        import io as _io

        keys = [
            "ts",
            "event",
            "batch_id",
            "row_id",
            "src",
            "dst",
            "reason",
            "detail",
            "conflict_type",
            "resolution",
            "sha1",
            "size",
        ]
        buf = _io.StringIO()
        writer = _csv.writer(buf)
        writer.writerow(keys)
        for ev in events:
            writer.writerow([str(ev.get(k, "")) for k in keys])
        return {"ok": True, "format": "csv", "content": buf.getvalue(), "count": len(events)}
    # default: json structure
    return {"ok": True, "format": "json", "events": events, "count": len(events)}


def build_apply_preview(
    api: Any,
    run_id: str,
    decisions: Dict[str, Dict[str, Any]],
    *,
    cleanup_scope_label: Callable[[str], str],
    cleanup_status_label: Callable[..., str],
    cleanup_reason_label: Callable[[str], str],
) -> Dict[str, Any]:
    """P1.3 : construit un plan structuré des déplacements avant apply.

    Ne touche NI le filesystem NI la BDD. Retourne une liste d'ops groupées
    par film, enrichies avec metadata (tier, confidence, warnings, sidecars),
    pour permettre à l'UI de montrer "avant → après" au lieu d'une simple
    liste de stats.

    Structure retournée :
        {
            "ok": true,
            "films": [
                {
                    "row_id": "S|abc123",
                    "title": "Inception",
                    "year": 2010,
                    "tier": "Platinum",
                    "confidence": 95,
                    "confidence_label": "high",
                    "warnings": ["nfo_file_mismatch"],
                    "change_type": "rename_only",
                    "from_path": "D:\\Films\\Inception.2010.1080p",
                    "to_path": "D:\\Films\\Inception (2010)",
                    "ops": [
                        {"op_type": "MOVE_DIR", "src": "...", "dst": "..."}
                    ]
                },
                ...
            ],
            "totals": {
                "films": 42,
                "moves": 87,
                "renames": 20,
                "total_ops": 107,
                "changes_count": 40,
                "noop_count": 2
            },
            "conflicts": [...]
        }
    """
    _log.info("api: build_apply_preview run_id=%s", run_id)
    validation = _validate_apply(api, run_id, decisions, dry_run=True, quarantine_unapproved=False)
    if not validation.get("ok"):
        return validation
    cfg, run_paths, rows, log_fn, store, safe_decisions, decision_presence = validation["_ctx"]

    preview_ops: List[Dict[str, Any]] = []
    batch_state: List[Any] = [None, 0]
    try:
        result, _batch_id, _ops_count = _execute_apply(
            cfg,
            rows,
            safe_decisions,
            decision_presence,
            dry_run=True,
            quarantine_unapproved=False,
            log_fn=log_fn,
            run_paths=run_paths,
            store=store,
            api=api,
            run_id=run_id,
            batch_state=batch_state,
            preview_ops_out=preview_ops,
        )
    except _DuplicateCheckError as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

    # Indexer les rows par row_id pour enrichir
    rows_by_id = {str(getattr(r, "row_id", "") or ""): r for r in rows}

    # Grouper les ops par row_id
    films_map: Dict[str, Dict[str, Any]] = {}
    orphan_ops: List[Dict[str, Any]] = []
    for op in preview_ops:
        rid = str(op.get("row_id") or "")
        if not rid:
            orphan_ops.append(op)
            continue
        if rid not in films_map:
            row = rows_by_id.get(rid)
            films_map[rid] = {
                "row_id": rid,
                "title": str(getattr(row, "proposed_title", "") or "") if row else "",
                "year": int(getattr(row, "proposed_year", 0) or 0) if row else 0,
                "folder": str(getattr(row, "folder", "") or "") if row else "",
                "video": str(getattr(row, "video", "") or "") if row else "",
                "confidence": int(getattr(row, "confidence", 0) or 0) if row else 0,
                "confidence_label": str(getattr(row, "confidence_label", "") or "") if row else "",
                "warnings": list(getattr(row, "warning_flags", []) or []) if row else [],
                "ops": [],
                "has_move_dir": False,
                "main_from": None,
                "main_to": None,
            }
        slim_op = {
            "op_type": str(op.get("op_type") or ""),
            "src_path": str(op.get("src_path") or ""),
            "dst_path": str(op.get("dst_path") or ""),
            "reversible": bool(op.get("reversible")),
        }
        films_map[rid]["ops"].append(slim_op)
        if slim_op["op_type"] == "MOVE_DIR" and not films_map[rid]["has_move_dir"]:
            films_map[rid]["has_move_dir"] = True
            films_map[rid]["main_from"] = slim_op["src_path"]
            films_map[rid]["main_to"] = slim_op["dst_path"]
        elif films_map[rid]["main_from"] is None and slim_op["op_type"] == "MOVE_FILE":
            films_map[rid]["main_from"] = slim_op["src_path"]
            films_map[rid]["main_to"] = slim_op["dst_path"]

    films_list = list(films_map.values())
    # Classifier chaque film par type de changement
    for film in films_list:
        n_move_dir = sum(1 for op in film["ops"] if op["op_type"] == "MOVE_DIR")
        n_move_file = sum(1 for op in film["ops"] if op["op_type"] == "MOVE_FILE")
        if n_move_dir + n_move_file == 0:
            film["change_type"] = "noop"
        elif n_move_dir > 0 and n_move_file == 0:
            film["change_type"] = "rename_folder"
        elif n_move_file > 0 and n_move_dir == 0:
            film["change_type"] = "move_files"
        else:
            film["change_type"] = "move_mixed"

    # Stats globales à partir du résultat dry-run
    totals = {
        "films": len(films_list),
        "moves": int(getattr(result, "moves", 0) or 0),
        "renames": int(getattr(result, "renames", 0) or 0),
        "quarantined": int(getattr(result, "quarantined", 0) or 0),
        "skipped": int(getattr(result, "skipped", 0) or 0),
        "errors": int(getattr(result, "errors", 0) or 0),
        "total_ops": len(preview_ops),
        "orphan_ops": len(orphan_ops),
        "changes_count": sum(1 for f in films_list if f["change_type"] != "noop"),
        "noop_count": sum(1 for f in films_list if f["change_type"] == "noop"),
    }

    return {
        "ok": True,
        "films": films_list,
        "totals": totals,
        "orphan_ops": orphan_ops,  # ops système (buckets, nettoyage)
    }
