from __future__ import annotations

import contextlib
import csv
import dataclasses
import io
import json
import logging
import shutil
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import requests

# Cf issue #83 : import direct au lieu de via re-export domain.core (qui cree un
# cycle domain -> app). NB : find_duplicate_targets reste accede via core.X car
# c'est un wrapper qui injecte 7 helpers internes de domain/core.py — pas un
# simple re-export.
import cinesort.app.plan_support as _plan_support_mod
import cinesort.domain.core as core
import cinesort.infra.plex_client as _plex_mod
import cinesort.infra.state as state
from cinesort.app.apply_audit import ApplyAuditLogger, read_apply_audit
from cinesort.app.apply_core import apply_rows as _apply_rows_fn
from cinesort.app.apply_core import sha1_quick_cached, unique_bucket_path
from cinesort.app.apply_rollback import rollback_forward as _atomic_rollback_forward
from cinesort.app.disk_space_check import check_disk_space_for_apply
from cinesort.app.jellyfin_sync import restore_watched, snapshot_watched
from cinesort.app.move_journal import RecordOpWithJournal, journaled_move
from cinesort.app.quarantine_ttl import register_runs_root as _register_runs_root
from cinesort.domain.conversions import to_bool as _to_bool
from cinesort.domain.i18n_messages import t
from cinesort.infra.db import SQLiteStore
from cinesort.infra.integration_errors import IntegrationError
from cinesort.infra.jellyfin_client import JellyfinClient
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api._responses import safe_integration_error as _safe_integration_error
from cinesort.ui.api._validators import clamp_timeout, requires_valid_run_id
from cinesort.ui.api.run_data_support import PlanCorruptedError
from cinesort.ui.api.settings_support import normalize_user_path, read_settings

logger = logging.getLogger(__name__)

_log = logging.getLogger(__name__)


# Fix audit 2026-05-24 (v1.5.2) : delai d'annulation post-apply enforce
# cote backend. La promesse "Annulation possible pendant 24h" (Spec 08 §3.5,
# PR #394) etait cosmetique : la carte UI affichait un countdown mais le
# backend acceptait toujours l'undo. On refuse desormais avec 410 Gone une
# fois passe ce delai. Constante en miroir de dashboard_support._UNDO_DEADLINE_SECONDS
# pour eviter une dependance circulaire entre modules ui.api.
_UNDO_DEADLINE_SECONDS = 24 * 3600


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

    batch = store.apply.get_last_reversible_apply_batch(run_id)
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
    ops = store.apply.list_apply_operations(batch_id=batch_id) if batch_id else []
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

    # Spec 08 §3.5 : echantillon d'operations (max 20) pour la modale preview
    # de l'annulation post-apply cote UI Traitement. On retourne avant/apres
    # pour chaque op (dst_path = etat actuel sur disque, src_path = cible undo).
    samples: List[Dict[str, Any]] = []
    for op in reversible_ops[:20]:
        samples.append(
            {
                "op_type": str(op.get("op_type") or ""),
                "current_path": str(op.get("dst_path") or ""),
                "restore_path": str(op.get("src_path") or ""),
            }
        )

    apply_ts = float(batch.get("started_ts") or 0.0) if batch else 0.0
    # Fix audit 2026-05-24 (v1.5.2) : expose `expired` aussi dans la reponse
    # de la preview undo, pas seulement dans le dashboard. La carte UI peut
    # ainsi rejeter localement un click utilisateur tardif sans aller-retour.
    now_ts = time.time()
    expired = bool(apply_ts > 0 and (now_ts - apply_ts) > _UNDO_DEADLINE_SECONDS)

    payload = {
        "ok": True,
        "run_id": run_id,
        "batch_id": batch_id,
        "apply_ts": apply_ts,
        "expired": expired,
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
        "samples": samples,
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


def _mark_undo_status(
    store: Any,
    log_fn: Callable[[str, str], None],
    *,
    op_id: int,
    undo_status: str,
    error_message: Optional[str] = None,
) -> None:
    """F31 — persiste le statut d'undo d'une operation sans jamais interrompre l'undo.

    Le statut en base est un ARTEFACT DE RAPPORT : quand on l'ecrit, la decision
    filesystem est deja prise (fichier restaure, saute ou en echec). Son echec ne
    doit donc jamais interrompre la boucle, sinon on laisse le disque a moitie
    restaure — meme invariant que move_journal.py:13-15 pour le journal des moves.

    Avant ce correctif, `sqlite3.Error` (qui n'herite PAS de OSError) traversait le
    filet per-op : un "database is locked" sortait de _execute_undo_ops, les ops
    suivantes n'etaient jamais reverties, le rapport done/skipped/failed n'etait
    jamais construit (500 generique cote REST) et le batch restait affiche comme
    annulable alors que le FS etait a moitie restaure.

    Revue R1 : `AttributeError` a ete RETIRE du tuple. Un store dont la surface
    `apply.mark_apply_operation_undo_status` est absente/renommee (ou dont
    `store.apply` vaut None) n'est PAS une indisponibilite transitoire, c'est une
    erreur de programmation. L'avaler rendait les 11 marks silencieusement no-op,
    donc `all_resolved` toujours False et le batch classe UNDONE_PARTIAL a chaque
    passage : exactement le "batch mensonger" que F31 devait supprimer, deplace
    du lock vers le drift d'API. Meme regle que TypeError (spec F31, point d).
    """
    try:
        store.apply.mark_apply_operation_undo_status(
            op_id=int(op_id),
            undo_status=str(undo_status),
            error_message=error_message,
        )
    except (sqlite3.Error, OSError) as exc:
        _log.warning("undo: statut op %s -> %s non persiste: %s", op_id, undo_status, exc)
        log_fn("WARN", f"UNDO statut non persiste (op {op_id} -> {undo_status}) : {exc}")


def _require_undo_status_api(store: Any) -> None:
    """F31 (revue R1) : le store sait-il persister un statut d'undo ? Verifie AVANT tout move.

    `_mark_undo_status` ne rattrape QUE les indisponibilites TRANSITOIRES
    (sqlite3.Error / OSError) : un drift d'API (methode absente/renommee,
    `store.apply` a None) est une erreur de programmation et doit echouer
    bruyamment. Mais le laisser echouer au 1er mark abandonnerait l'undo avec un
    filesystem A MOITIE restaure. On le detecte donc ici, avant le premier
    deplacement, la ou l'echec n'a AUCUNE consequence sur le disque.
    """
    if not callable(getattr(getattr(store, "apply", None), "mark_apply_operation_undo_status", None)):
        raise AttributeError(
            "store.apply.mark_apply_operation_undo_status est introuvable : undo refuse, aucun fichier deplace."
        )


def _batch_all_ops_resolved(
    store: Any,
    log_fn: Callable[[str, str], None],
    *,
    batch_id: str,
) -> bool:
    """F31 (revue R1) : les ops reversibles du batch sont-elles toutes resolues ?

    `list_apply_operations` est un appel SQLite NU sur le chemin de finalisation
    de l'undo, execute APRES que le filesystem a deja ete restaure. Une DB
    verrouillee — le declencheur meme de F31, qui verrouille TOUS les appels, pas
    seulement les marks per-op — y levait une `sqlite3.Error` remontee jusqu'au
    boundary REST : 500 generique, rapport done/skipped/failed perdu.

    En cas d'indisponibilite on rend False = "on ne peut pas prouver que tout est
    resolu", ce qui classe le batch UNDONE_PARTIAL : degradation CONSERVATRICE
    (le batch reste proposable a l'annulation) plutot qu'un UNDONE_DONE menteur.
    """
    try:
        remaining = store.apply.list_apply_operations(batch_id=str(batch_id))
    except (sqlite3.Error, OSError) as exc:
        _log.warning("undo: relecture des ops du batch %s indisponible: %s", batch_id, exc)
        log_fn("WARN", f"UNDO statut du batch non verifiable ({batch_id}) : {exc}")
        return False
    return all(str(op.get("undo_status")) != "PENDING" for op in remaining if int(op.get("reversible") or 0) == 1)


def _finalize_batch_undo_status(
    store: Any,
    log_fn: Callable[[str, str], None],
    *,
    batch_id: str,
    status: str,
    summary: Dict[str, Any],
) -> bool:
    """F31 (revue R1) : persiste le statut d'undo du BATCH sans perdre le rapport.

    Meme invariant que `_mark_undo_status`, un cran plus haut : quand on ecrit ce
    statut, l'undo filesystem est TERMINE. Laisser une `sqlite3.Error` remonter
    ne protegeait rien (l'etat DB est identique dans les deux cas : batch non
    finalise) et supprimait en plus le rapport done/skipped/failed rendu a
    l'utilisateur. On logue donc un WARN et on rend le rapport.
    """
    try:
        store.apply.mark_apply_batch_undo_status(batch_id=str(batch_id), status=str(status), summary=summary)
        return True
    except (sqlite3.Error, OSError) as exc:
        _log.warning("undo: statut batch %s -> %s non persiste: %s", batch_id, status, exc)
        log_fn("WARN", f"UNDO statut du batch non persiste ({batch_id} -> {status}) : {exc}")
        return False


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
    # F31 (revue R1) : fail-closed AVANT le premier move (cf. helper).
    _require_undo_status_api(store)
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
            _mark_undo_status(
                store,
                log_fn,
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
                _mark_undo_status(
                    store,
                    log_fn,
                    op_id=op_id,
                    undo_status="SKIPPED",
                    error_message=f"Source inverse introuvable: {current_path}",
                )
                log_fn("WARN", f"UNDO skip {idx}/{len(reversible_ops)}: source inverse introuvable {current_path}")
                continue

            if target_path.exists():
                # R8-011 (F2-c) : sur FS INSENSIBLE A LA CASSE (Windows/SMB),
                # target_path.exists() est VRAI quand current_path et target_path
                # designent le MEME fichier physique en ne differant QUE par la casse
                # (undo d'un rename casse-seule : "film" -> "Film"). Ce n'est PAS un
                # conflit -> on fait le rename casse-seule au lieu de classer CONFLIT/
                # FAILED. Sur FS SENSIBLE A LA CASSE (Linux), "Film" != "film" sont des
                # fichiers distincts -> samefile()=False -> on retombe sur le vrai
                # chemin conflit (comportement correct preserve sur les deux plateformes).
                _case_only_same = False
                # NB : on compare les STR (sensible a la casse) — l'egalite Path est
                # insensible a la casse sur Windows (PureWindowsPath) et masquerait la
                # difference de casse. samefile() confirme ensuite le meme fichier physique.
                if str(current_path) != str(target_path):
                    try:
                        _case_only_same = current_path.samefile(target_path)
                    except OSError:
                        _case_only_same = False
                if _case_only_same:
                    try:
                        from cinesort.app.apply_core import _case_only_rename_with_rollback

                        # R8-089 (filet F2-c) : PAS de journaled_move ici. Le rename
                        # casse-seule se fait en 2 temps (current -> .__tmp_ren -> target).
                        # journaled_move ne peut PAS encadrer l'etat intermediaire .__tmp_ren
                        # (ni src ni dst journalises) -> un hard-kill entre les 2 renames
                        # ferait une FAUSSE alarme "FICHIER PERDU" au reconcile (src+dst
                        # absents). _case_only_rename_with_rollback a son propre rollback
                        # (tmp -> current) sur echec ; on reste coherent avec le site apply
                        # (apply_core.py _case_only_rename_with_rollback, non journalise lui aussi).
                        _case_only_rename_with_rollback(current_path, target_path)
                        done += 1
                        _mark_undo_status(store, log_fn, op_id=op_id, undo_status="DONE", error_message=None)
                        log_fn(
                            "INFO",
                            f"UNDO casse-seule {idx}/{len(reversible_ops)}: {current_path} -> {target_path}",
                        )
                    except (OSError, PermissionError, FileExistsError) as case_exc:
                        failed += 1
                        _mark_undo_status(
                            store,
                            log_fn,
                            op_id=op_id,
                            undo_status="FAILED",
                            error_message=f"Undo casse-seule echoue: {case_exc}",
                        )
                        log_fn(
                            "ERROR",
                            f"UNDO casse-seule echec {idx}/{len(reversible_ops)}: {current_path} -> {target_path}: {case_exc}",
                        )
                    continue

                undo_conflicts_root.mkdir(parents=True, exist_ok=True)
                # REGLE INVIOLABLE n1 : le nom du fichier reste INTACT. L'ancien
                # `api._unique_path` resolvait une collision dans le bac en
                # renommant le FICHIER (`Rocky.1976.1080p.mkv` ->
                # `Rocky.1976.1080p_2.mkv`) — 4e site de renommage du depot,
                # celui-ci sur le chemin de l'UNDO, donc sur le filet de secours.
                # `unique_bucket_path` porte l'index sur un DOSSIER a la place.
                conflict_dst = unique_bucket_path(
                    undo_conflicts_root / current_path.name,
                    bucket_root=undo_conflicts_root,
                    use_dup_suffix=False,
                )
                if conflict_dst is None:
                    # Aucune desambiguisation de dossier possible. On REFUSE le
                    # deplacement plutot que d'ecraser la cible ou de renommer le
                    # fichier : sur un chemin destructif l'erreur va dans le sens
                    # restrictif, et le fichier source reste ou il est.
                    _log.error(
                        "undo: quarantaine impossible sans renommer le fichier, abandon: %s",
                        current_path,
                    )
                    failed += 1
                    _mark_undo_status(
                        store,
                        log_fn,
                        op_id=op_id,
                        undo_status="FAILED",
                        error_message=(
                            "Quarantaine d'undo impossible sans renommer le fichier video "
                            f"({current_path.name}) : deplacement refuse, le fichier est laisse en place."
                        ),
                    )
                    continue
                # `unique_bucket_path` INSERE un dossier d'index quand la cible est
                # prise ; ce dossier n'existe pas encore. Sans ce mkdir, `shutil.move`
                # leve FileNotFoundError, que la branche ci-dessous interprete comme
                # « fichier disparu » et compte en SKIPPED — le fichier serait reste
                # en place sans que rien ne signale d'echec. Constate par le test du
                # site d'appel, avec deux conflits homonymes.
                conflict_dst.parent.mkdir(parents=True, exist_ok=True)
                # M3 : TOCTOU possible — current_path peut disparaitre entre exists() et move()
                # CR-1 : journal write-ahead pour atomicite undo (cf move_journal.py)
                try:
                    with journaled_move(store, src=current_path, dst=conflict_dst, op_type="UNDO_QUARANTINE"):
                        shutil.move(str(current_path), str(conflict_dst))
                except FileNotFoundError:
                    _log.warning("undo: fichier disparu entre check et move (conflict): %s", current_path)
                    skipped += 1
                    _mark_undo_status(
                        store,
                        log_fn,
                        op_id=op_id,
                        undo_status="SKIPPED",
                        error_message=f"Fichier disparu entre check et move: {current_path}",
                    )
                    continue
                except PermissionError as perm_err:
                    _log.error("undo: permission refusee: %s -> %s: %s", current_path, conflict_dst, perm_err)
                    failed += 1
                    _mark_undo_status(
                        store,
                        log_fn,
                        op_id=op_id,
                        undo_status="FAILED",
                        error_message=str(perm_err),
                    )
                    continue
                conflict_moves += 1
                failed += 1
                _mark_undo_status(
                    store,
                    log_fn,
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
                _mark_undo_status(
                    store,
                    log_fn,
                    op_id=op_id,
                    undo_status="SKIPPED",
                    error_message=f"Fichier disparu entre check et move: {current_path}",
                )
                continue
            except PermissionError as perm_err:
                _log.error("undo: permission refusee: %s -> %s: %s", current_path, target_path, perm_err)
                failed += 1
                _mark_undo_status(
                    store,
                    log_fn,
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
            _mark_undo_status(
                store,
                log_fn,
                op_id=op_id,
                undo_status="DONE",
                error_message=None,
            )
            log_fn("INFO", f"UNDO {idx}/{len(reversible_ops)}: {current_path} -> {target_path}")
        except (sqlite3.Error, OSError, FileExistsError, ValueError, TypeError) as exc:
            # F31 : sqlite3.Error ajoutee — aucun appel DB futur dans le corps de la
            # boucle ne doit pouvoir avorter la restauration des ops suivantes.
            failed += 1
            _mark_undo_status(
                store,
                log_fn,
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


def _collect_pending_mkdir_ops(
    store: Any,
    batch_id: str,
    run_id: Optional[str],
    log_fn: Callable[[str, str], None],
) -> List[Dict[str, Any]]:
    """FIX #9 : rassemble les ops MKDIR encore PENDING a nettoyer.

    Quand `run_id` est fourni ET que le store sait lister les batches du run,
    on balaye les MKDIR PENDING de TOUS les batches (pas seulement `batch_id`).
    C'est necessaire car `mkdir_counted` ne rejournalise PAS un dossier saga
    deja existant : l'op MKDIR qui "possede" `_Collection/<Saga>/` vit dans le
    1er batch qui l'a cree, pas dans le 2e qui l'a reutilise. Sinon (run_id
    absent, ou store legacy sans `list_apply_batches_for_run`), on retombe sur
    le seul `batch_id` (comportement historique R8-085 B).

    Ne renvoie que des ops `op_type == "MKDIR"` et `undo_status == "PENDING"`
    (une op deja DONE = dossier deja supprime lors d'un undo precedent).
    """
    batch_ids: List[str] = []
    if run_id:
        lister = getattr(store.apply, "list_apply_batches_for_run", None)
        if callable(lister):
            try:
                # R2 : limit=0 = TOUS les batches du run (borne naturelle) —
                # l'ancien cap DESC jetait les PLUS ANCIENS, laissant orphelin
                # un dossier saga cree par un vieux batch.
                batches = lister(run_id=run_id, limit=0)
                batch_ids = [str(b.get("batch_id") or "") for b in batches if b.get("batch_id")]
            except (OSError, TypeError, ValueError, sqlite3.Error, AttributeError) as exc:
                log_fn("WARN", f"UNDO MKDIR: liste des batches indisponible run={run_id}: {exc}")
                batch_ids = []
    if not batch_ids:
        batch_ids = [str(batch_id)] if batch_id else []
    # Defensif : garantir que le batch courant est balaye meme s'il n'apparait
    # pas (encore) dans la liste retournee par le store.
    if batch_id and str(batch_id) not in batch_ids:
        batch_ids.append(str(batch_id))

    collected: List[Dict[str, Any]] = []
    for bid in batch_ids:
        try:
            ops = store.apply.list_apply_operations(batch_id=bid)
        except (OSError, TypeError, ValueError, sqlite3.Error) as exc:
            log_fn("WARN", f"UNDO MKDIR: liste des ops indisponible batch={bid}: {exc}")
            continue
        for op in ops:
            if str(op.get("op_type") or "") != "MKDIR":
                continue
            if str(op.get("undo_status") or "PENDING") != "PENDING":
                continue
            collected.append(op)
    return collected


def _undo_mkdir_ops(
    store: Any,
    batch_id: str,
    log_fn: Callable[[str, str], None],
    *,
    run_id: Optional[str] = None,
) -> int:
    """R8-085 B + FIX #9 : supprime (rmdir) les dossiers crees par des ops MKDIR
    redevenus VIDES apres restauration des moves.

    Sans ce nettoyage, l'undo restaurait les films mais laissait les dossiers
    saga `_Collection/<Saga>/` en orphelins vides (restauration PAS a
    l'identique).

    FIX #9 (orphelin saga inter-batch) : on ne se limite plus aux MKDIR du
    `batch_id` en cours. Scenario du bug : un 1er apply cree `_Collection/<Saga>`
    (MKDIR journalise dans batch 1) puis un 2e apply y range un autre film SANS
    rejournaliser le dossier (mkdir_counted saute un dossier existant). Si le
    batch 1 est annule d'abord, son MKDIR ne peut pas rmdir le dossier encore
    occupe par le film du batch 2 et reste donc PENDING ; l'annulation du batch 2
    videait alors le dossier mais l'ancien code, ne regardant que les MKDIR du
    batch 2 (aucun), laissait `_Collection/<Saga>/` vide a jamais. On balaye
    desormais les MKDIR PENDING de TOUS les batches du run (via `run_id`).

    rmdir echoue silencieusement si non vide : jamais destructif, un dossier
    encore occupe (undo selectif, autre film de la saga) est garde -> l'undo
    selectif n'est pas casse. Les plus PROFONDS d'abord (tri par profondeur de
    chemin decroissante), pour que l'enfant parte avant son parent meme quand
    les niveaux viennent de batches differents.
    """
    removed = 0
    mkdir_ops = _collect_pending_mkdir_ops(store, batch_id, run_id, log_fn)

    def _depth(op: Dict[str, Any]) -> int:
        raw = str(op.get("dst_path") or op.get("src_path") or "")
        return len(Path(raw).parts) if raw else 0

    for op in sorted(mkdir_ops, key=_depth, reverse=True):
        raw = str(op.get("dst_path") or op.get("src_path") or "")
        if not raw:
            continue
        path = Path(raw)
        try:
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
                removed += 1
                log_fn("INFO", f"UNDO MKDIR: dossier vide supprime {path}")
                # F31 (revue R1) : ce mark etait le 12e appel DB de l'undo, reste
                # NU sous un suppress SANS sqlite3.Error (qui n'herite PAS de
                # OSError) — le trou exact du finding, en AVAL du perimetre
                # patche. Il s'execute APRES le rmdir : une DB verrouillee
                # laissait le dossier supprime, l'op PENDING, et l'exception
                # remontait au boundary REST (500, rapport d'undo perdu).
                _mark_undo_status(store, log_fn, op_id=int(op.get("id") or 0), undo_status="DONE")
        except (OSError, PermissionError) as exc:
            _log.debug("undo mkdir: rmdir %s skip: %s", path, exc)
    return removed


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
        batches = store.apply.list_apply_batches_for_run(run_id=run_id, limit=50)
        batch = next((b for b in batches if b["batch_id"] == batch_id), None)
    else:
        batch = store.apply.get_last_reversible_apply_batch(run_id)
    if not batch:
        return {"ok": True, "batch_id": None, "can_undo": False, "rows": [], "message": t("errors.no_reversible_batch")}

    bid = str(batch["batch_id"])
    rows_summary = store.apply.get_batch_rows_summary(batch_id=bid)

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

    # Ultra-audit 2026-08 (N25) : cette boucle appelait
    # `list_apply_operations_by_row` PAR ROW. Chaque appel repo ouvre 2
    # connexions SQLite neuves (_ensure_apply_journal_tables -> _existing_tables,
    # puis la requete), soit 2N connexions pour N films. Mesure sur un batch de
    # 5000 films : 165 s, contre 88 ms pour la requete unique + regroupement
    # Python. `list_apply_operations` selectionne les MEMES colonnes avec le
    # MEME `ORDER BY op_index ASC, id ASC` (repositories/apply.py:314-346 vs
    # :460-489), donc l'ordre et le contenu des `ops` sont inchanges.
    # Seule la convention du row_id NULL differe : le repo serialise NULL en ""
    # (:341) alors que `get_batch_rows_summary` groupe sur
    # COALESCE(row_id, '__legacy__') (:433). On realigne donc "" -> "__legacy__".
    # Aucune ambiguite : `record_apply_operation` ecrit `str(row_id) if row_id
    # else None` (:176), une chaine vide est donc stockee NULL, jamais "".
    ops_by_row: Dict[str, List[Dict[str, Any]]] = {}
    for op in store.apply.list_apply_operations(batch_id=bid):
        ops_by_row.setdefault(str(op.get("row_id") or "") or "__legacy__", []).append(op)

    rows_out: List[Dict[str, Any]] = []
    for summary in rows_summary:
        rid = str(summary["row_id"])
        ops = ops_by_row.get(rid, [])
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
        batches = store.apply.list_apply_batches_for_run(run_id=run_id, limit=50)
        batch = next((b for b in batches if b["batch_id"] == batch_id), None)
    else:
        batch = store.apply.get_last_reversible_apply_batch(run_id)
    if not batch:
        return _err_response(t("errors.no_reversible_batch"), category="state", level="info", log_module=__name__)

    bid = str(batch["batch_id"])
    # Issue #593 : une SEULE coercition, partagee par la branche dry_run et par
    # l'undo reel. Avant, le dry_run testait `r["row_id"] in row_ids` :
    #   - `row_ids` etant une LISTE, chaque test etait O(M) -> O(N*M) au total ;
    #   - et surtout SANS `str()`, alors que l'undo reel comparait
    #     `set(str(r) for r in row_ids)`. Le corps REST est decode par
    #     `json.loads` (rest_server.py:1267) : des row_ids envoyes en NOMBRES
    #     JSON ne matchaient AUCUNE ligne du preview (ou `row_id` est toujours
    #     une chaine, cf build_undo_by_row_preview:972) alors que l'undo reel,
    #     lui, les retrouvait. L'apercu d'une action destructive annoncait donc
    #     « 0 ligne » avant d'en annuler N.
    target_row_ids = {str(r) for r in row_ids}
    if bool(dry_run):
        preview = build_undo_by_row_preview(api, run_id, batch_id=bid)
        selected = [r for r in preview.get("rows", []) if str(r["row_id"]) in target_row_ids]
        return {
            "ok": True,
            "batch_id": bid,
            "dry_run": True,
            "status": "PREVIEW_ONLY",
            "selected_rows": selected,
            "message": t("errors.preview_undo_selective"),
        }

    # AUDIT 2026-06-11 (R3d, gap[5]) : enforcement backend du delai 24h sur
    # l'undo SELECTIF aussi. La garde n'existait que dans undo_last_apply
    # (L1018) ; undo_selected_rows allait directement de la selection a
    # _execute_undo_ops, permettant un undo reel apres expiration. La dry_run
    # au-dessus reste autorisee meme expiree (apercu UI). Miroir exact 410.
    apply_ts = float(batch.get("started_ts") or 0.0)
    if apply_ts > 0 and (time.time() - apply_ts) > _UNDO_DEADLINE_SECONDS:
        return _err_response(
            "L'annulation n'est plus possible (delai 24h depasse).",
            category="state",
            level="info",
            log_module=__name__,
            http_status=410,
        )

    # Collect all reversible PENDING ops for the selected row_ids.
    # `target_row_ids` est construit plus haut (cf #593), partage avec le dry_run.
    all_ops = store.apply.list_apply_operations(batch_id=bid)
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

    # AUDIT 2026-06-11 (R3d, gap[6]) : l'undo selectif mute FS+DB du meme run
    # que l'apply ; il DOIT acquerir le slot apply pour ne pas courir avec un
    # apply concurrent (avant, seuls apply_changes/build_apply_preview le
    # prenaient). Slot occupe -> 409.
    with api._apply_slot_guard(run_id) as acquired:
        if not acquired:
            return _err_response(
                t("errors.apply_already_in_progress"),
                category="state",
                level="info",
                log_module=__name__,
                http_status=409,
            )

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

        # R8-085 B (parite avec l'undo complet) : rmdir des dossiers MKDIR
        # journalises redevenus vides. Sans risque en selectif : un dossier
        # saga encore occupe par d'autres films n'est pas vide -> conserve.
        # FIX #9 : run_id -> balaye les MKDIR PENDING de TOUS les batches du run
        # (dossier saga cree par un batch, vide par l'annulation d'un autre).
        _undo_mkdir_ops(store, bid, log_fn, run_id=run_id)

        # Determine batch-level status: check if ALL ops in the batch are now non-PENDING.
        # F31 (revue R1) : relecture + finalisation tolerantes a une DB
        # indisponible — le FS est deja restaure, perdre le rapport en plus
        # (500 REST) n'apporte aucune protection.
        all_resolved = _batch_all_ops_resolved(store, log_fn, batch_id=bid)
        if all_resolved:
            batch_status = "UNDONE_DONE" if undo_counts["failed"] == 0 else "UNDONE_PARTIAL"
        else:
            batch_status = "UNDONE_PARTIAL"
        _finalize_batch_undo_status(
            store,
            log_fn,
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
    # Fix audit 2026-05-25 (v1.5.3) Vague G : wrap global pour eviter HTTP 500
    # sur cet endpoint d'historique.
    try:
        return _list_apply_history_impl(api, run_id)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("list_apply_history failed for run_id=%s", run_id)
        return {
            "ok": False,
            "error": "apply_history_failed",
            "message": str(exc),
            "user_message": "Impossible de charger l'historique d'application.",
        }


def _list_apply_history_impl(api: Any, run_id: str) -> Dict[str, Any]:
    """Implementation reelle de list_apply_history, sans wrap global (Vague G)."""
    found = api._find_run_row(run_id)
    if not found:
        return _err_response(t("errors.run_not_found"), category="resource", level="info", log_module=__name__)
    _row, store = found
    # Fix audit 2026-05-24 : store.apply.list_apply_batches_for_run touche SQLite,
    # peut lever sqlite3.Error (DB corrompue / verrouillee), AttributeError
    # (store.apply absent sur vieux runs) ou OSError (FS) -> 500 UI. On wrappe.
    try:
        batches = store.apply.list_apply_batches_for_run(run_id=run_id, limit=20)
    except (sqlite3.Error, AttributeError, OSError):
        return _err_response("Historique apply indisponible.", category="state", level="warning", log_module=__name__)

    # Vague P / VP-A : annoter chaque batch avec mode atomique + rollback status
    # (badge "Mode atomique" + indicateur rollback dans UI historique).
    # Tolerant si la table n'existe pas (DB pre-migration 029) : on retourne
    # les batches non annotes — UI affichera "mode standard".
    try:
        atomic_modes = store.apply.list_atomic_modes_for_run(run_id=run_id)
    except (sqlite3.Error, AttributeError, OSError):
        atomic_modes = {}
    if atomic_modes:
        for batch in batches:
            bid = str(batch.get("batch_id") or "")
            mode = atomic_modes.get(bid)
            if mode is not None:
                batch["atomic_mode"] = mode

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

    # R8-085 B : apres restauration des moves, retirer les dossiers MKDIR
    # journalises redevenus vides (ex. _Collection/<Saga>) — sinon l'undo
    # laisse des orphelins et la restauration n'est pas a l'identique.
    # FIX #9 : run_id -> balaye les MKDIR PENDING de TOUS les batches du run
    # (saga reutilisee entre batches, MKDIR non rejournalise par le 2e apply).
    mkdir_dirs_removed = _undo_mkdir_ops(store, batch_id, log_fn, run_id=run_id)

    status = "UNDONE_DONE" if failed == 0 else "UNDONE_PARTIAL"
    # F31 (revue R1) : finalisation tolerante (cf. _finalize_batch_undo_status).
    _finalize_batch_undo_status(
        store,
        log_fn,
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
                "mkdir_dirs_removed": mkdir_dirs_removed,
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
        api._dispatch_plugin_hook(
            "post_undo",
            {
                "run_id": run_id,
                "ts": time.time(),
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

    # Fix audit 2026-05-24 (v1.5.2) : enforcement backend du delai 24h.
    # On refuse l'execution reelle apres _UNDO_DEADLINE_SECONDS — la dry_run
    # reste autorisee pour que l'UI puisse afficher l'apercu meme expire.
    if not bool(dry_run):
        apply_ts = float(batch.get("started_ts") or 0.0)
        if apply_ts > 0 and (time.time() - apply_ts) > _UNDO_DEADLINE_SECONDS:
            return _err_response(
                "L'annulation n'est plus possible (delai 24h depasse).",
                category="state",
                level="info",
                log_module=__name__,
                http_status=410,
            )

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

    # AUDIT 2026-06-11 (R3d, gap[6]) : l'undo reel mute FS+DB du meme run que
    # l'apply ; il DOIT acquerir le slot apply pour ne pas courir avec un
    # apply concurrent (avant, seuls apply_changes/build_apply_preview le
    # prenaient). Slot occupe -> 409, comme apply.
    with api._apply_slot_guard(run_id) as acquired:
        if not acquired:
            return _err_response(
                t("errors.apply_already_in_progress"),
                category="state",
                level="info",
                log_module=__name__,
                http_status=409,
            )
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
    """Valide le contexte d'apply (rows, decisions, disk space).

    Fix audit 2026-05-25 (v1.5.3) Vague H : l'acquisition/release du
    ``_apply_slot`` n'est plus geree ici — c'est la responsabilite du caller
    via ``api._apply_slot_guard(run_id)`` (context manager qui libere le
    slot meme en cas d'exception). Cf ``apply_changes`` et
    ``build_apply_preview``.
    """
    if not isinstance(decisions, dict):
        return _err_response(
            t("errors.payload_decisions_invalid"), category="validation", level="info", log_module=__name__
        )
    try:
        ctx = api._run_context_for_apply(run_id)
    except PlanCorruptedError as exc:
        # Issue #519 : le refus etait deja acquis (PlanCorruptedError herite de
        # ValueError, donc de la branche ci-dessous), mais l'utilisateur lisait
        # "Impossible d'appliquer les changements." — un message qui ne distingue
        # pas un plan CORROMPU d'un run introuvable ou d'un disque plein. Sur le
        # chemin destructif, la perte doit etre NOMMEE : combien de lignes du
        # plan sont illisibles, et lesquelles.
        api.log_api_exception(
            "apply",
            exc,
            run_id=run_id,
            extra={
                "dry_run": bool(dry_run),
                "quarantine_unapproved": bool(quarantine_unapproved),
                "decision_count": len(decisions),
                "phase": "load_context",
                "invalid_plan_lines": exc.invalid_count,
            },
        )
        return _err_response(
            t("errors.plan_corrupted", detail=str(exc)),
            category="state",
            level="error",
            log_module=__name__,
        )
    except (OSError, PermissionError, KeyError, TypeError, ValueError) as exc:
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
        return _err_response(t("errors.plan_unavailable"), category="state", level="warning", log_module=__name__)
    cfg, run_paths, rows, log_fn, store = ctx

    if not rows:
        return _err_response(t("errors.plan_empty_or_missing"), category="state", level="warning", log_module=__name__)

    incoming = decisions if isinstance(decisions, dict) else {}
    # Fix R6-02 : projette le tri-etat `decision` -> `ok` AVANT _merge_decisions
    # et _normalize_decisions_for_rows, sinon un client API qui envoie
    # `{decision: "accepted"}` sans `ok` voit tous ses films traites comme
    # rejected (run_data_support.py:292 lit raw.get("ok", False)).
    # Import tardif pour eviter un cycle au chargement du module.
    try:
        from cinesort.ui.api.run_flow_support import (
            _project_decisions_ok_from_tri_state,
        )

        incoming = _project_decisions_ok_from_tri_state(incoming)
    except ImportError:
        # Environnement degrade : on continue sans projection (shape legacy
        # {ok: bool} reste fonctionnelle, backward compat ABSOLUE).
        pass
    disk_decisions = api._load_decisions_from_validation(run_paths)
    merged_decisions = api._merge_decisions(incoming, disk_decisions)
    # AUDIT 2026-07-13 (HIGH-14) : l'override TMDb manuel (film_tmdb_overrides) est
    # la DERNIERE volonte explicite de l'utilisateur -> il prime sur le title/year
    # de la decision, seedee par traitement.js depuis le plan PERIME (run/get_plan
    # ne l'overlayait pas au seed). Sans ca, _normalize_decisions_for_rows
    # materialise le title/year perime et apply_core (la decision gagne sur la row)
    # rend l'overlay R7-3 (dans _execute_apply) inoperant sur le nommage disque :
    # le TITRE et l'ANNEE etaient tous deux mutiles. On n'overlaye QUE les rows
    # ayant deja une decision (un override sans approbation ne s'applique pas).
    try:
        for _ovr_row in rows:
            _ovr_rid = str(getattr(_ovr_row, "row_id", "") or "")
            if not _ovr_rid:
                continue
            _ovr_dec = merged_decisions.get(_ovr_rid)
            if not isinstance(_ovr_dec, dict):
                continue
            _ovr = store.film_modal.get_tmdb_override(run_id=run_id, row_id=_ovr_rid)
            if not _ovr:
                continue
            if _ovr.get("proposed_title"):
                _ovr_dec["title"] = str(_ovr["proposed_title"])
            if int(_ovr.get("proposed_year") or 0) > 0:
                _ovr_dec["year"] = int(_ovr["proposed_year"])
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        log_fn("WARN", f"Overlay overrides TMDb (decisions) impossible: {exc}")
    # NB : `decision_presence` (presence = any decided row, approved OR
    # rejected) reste tel quel car _apply_rows_fn s'en sert pour distinguer
    # "validation_absente" (pas decidee) de "user_rejected" (decidee mais
    # ok=False). Changer sa semantique casserait apply_core.py:1296,1436.
    decision_presence = {key for key, value in merged_decisions.items() if isinstance(value, dict)}
    safe_decisions = api._normalize_decisions_for_rows(rows, merged_decisions)
    # Fix R6-04 : pour le pre-check espace disque, on ne sommerait que les
    # films APPROUVES (ok=True). Sinon estimate_apply_size inclut les
    # rejected/deferred (cf disk_space_check.py:67-77) et peut faussement
    # refuser un apply avec "Espace disque insuffisant" sur un run a 990
    # rejected + 10 approved. Calcule apres _normalize_decisions_for_rows
    # qui resout le tri-etat (les decisions deferred deviennent ok=False).
    approved_keys = {
        key for key, value in safe_decisions.items() if isinstance(value, dict) and value.get("ok") is True
    }
    try:
        state.atomic_write_json(run_paths.validation_json, safe_decisions)
    except (OSError, PermissionError) as exc:
        log_fn("WARN", f"Validation auto-save non ecrite: {exc}")

    # H-2 audit QA 20260428 : pre-check espace disque (uniquement apply reel).
    # Refuser si le volume cible n'a pas assez de place pour absorber la somme
    # des fichiers a deplacer (avec marge 10%). Evite l'apply qui s'arrete a
    # mi-parcours, laissant DB/FS dans un etat partiel (cf CR-1).
    if not dry_run:
        ok_disk, disk_info = check_disk_space_for_apply(cfg, rows, approved_keys)
        if not ok_disk:
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


def _resolve_duplicate_loser_row_ids(
    decisions: Any,
    log_fn: Callable[[str, str], None],
) -> Set[str]:
    """F07 : reconcilie les decisions doublons d'un run en un set de perdants.

    La table `duplicate_decisions` est upsert-only sur (run_id, group_key) et sa
    cle derive de `titre|annee` (domain/duplicate_support.py) : des que
    l'utilisateur corrige l'annee ou le titre en Validation, la cle change, la
    decision precedente SURVIT (aucun DELETE nulle part) et l'union brute des
    `loser_row_ids` faisait partir les DEUX exemplaires au bucket
    `_review/_duplicates_user_decided/` — le film quittait entierement la
    bibliotheque.

    Regle : la decision la PLUS RECENTE gagne. Un row_id declare gagnant par une
    decision recente ne peut plus etre declare perdant par une decision plus
    ancienne (le role est attribue une seule fois, en parcourant du plus recent
    au plus ancien).

    Revue R1 : une decision dont `loser_row_ids` est VIDE n'ARBITRE rien et est
    donc entierement ignoree. Sans ce garde, elle conferait une immunite a son
    "gagnant" et ANNULAIT une decision anterieure legitime qui, elle, designait
    ce row comme perdant : le set de perdants devenait vide et l'apply ne
    deplacait plus rien, alors que l'union brute d'avant deplacait correctement
    le perdant choisi par l'utilisateur. Cas reel : `mark_duplicate_winner`
    (run_flow_support.py) persiste `loser_row_ids=[]` avec un `decided_ts` FRAIS
    des que le groupe recharge n'a plus qu'UNE row (une copie deja presente sur
    disque suffit a emettre un tel groupe, duplicate_support.py).

    NB `decided_ts` ex-aequo (deux upserts dans le meme tick d'horloge) : le tri
    Python est stable, donc l'ordre de lecture du repo (ORDER BY decided_ts DESC)
    tranche. Cas theorique, non deterministe, assume.
    """
    usable = [dec for dec in (decisions or []) if isinstance(dec, dict)]
    try:
        ordered = sorted(usable, key=lambda d: float(d.get("decided_ts") or 0.0), reverse=True)
    except (TypeError, ValueError):
        # decided_ts illisible : on garde l'ordre du repo (deja DESC).
        ordered = usable

    role_by_row: Dict[str, str] = {}
    for dec in ordered:
        winner_id = str(dec.get("winner_row_id") or "").strip()
        losers_of_dec = [str(lid or "").strip() for lid in (dec.get("loser_row_ids") or [])]
        losers_of_dec = [lid for lid in losers_of_dec if lid and lid != winner_id]
        if not losers_of_dec:
            # Decision sans perdant : n'arbitre rien, ne confere aucune immunite.
            continue
        if winner_id:
            role_by_row.setdefault(winner_id, "winner")
        for loser_id in losers_of_dec:
            if role_by_row.setdefault(loser_id, "loser") == "winner":
                log_fn(
                    "WARN",
                    f"Doublons : row {loser_id} est perdant d'une decision perimee "
                    "mais gagnant d'une decision plus recente -> conserve (non deplace).",
                )
    return {row_id for row_id, role in role_by_row.items() if role == "loser"}


# F17 : cles du diagnostic de nettoyage residuel produites par
# cleanup.preview_cleanup_residual_folders + apply_core (moved_count /
# left_in_place_count / status_post). Utilisees pour fusionner les diagnostics
# des roots 2..N au lieu de ne garder que celui du root 1.
_CLEANUP_DIAG_COUNTER_KEYS = (
    "candidates_considered",
    "probable_eligible_count",
    "empty_dir_count",
    "has_video_count",
    "ambiguous_count",
    "symlink_count",
    "no_files_count",
    "moved_count",
    "left_in_place_count",
)
_CLEANUP_DIAG_LIST_KEYS = (
    "families",
    "sample_eligible_dirs",
    "sample_video_blocked_dirs",
    "sample_ambiguous_dirs",
    "sample_empty_dirs",
    "sample_symlink_dirs",
)
# Rang de "severite d'activite" : le root le plus actif l'emporte, sinon un
# moved_count somme > 0 coexisterait avec un status_post "executed_no_move".
_CLEANUP_DIAG_STATUS_RANK = {"disabled": 0, "no_action_likely": 1, "ready": 2}
_CLEANUP_DIAG_STATUS_POST_RANK = {
    "disabled": 0,
    "not_executed": 1,
    "executed_no_move": 2,
    "executed": 3,
}
_CLEANUP_DIAG_SAMPLE_MAX = 20


def _is_plain_int(value: Any) -> bool:
    """int VRAI (bool exclu : bool est une sous-classe de int)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _cleanup_diag_rank(ranks: Dict[str, int], value: Any) -> int:
    """Rang d'activite d'un statut de nettoyage (-1 = statut inconnu)."""
    return ranks.get(str(value or ""), -1)


def _merge_cleanup_residual_diagnostic(
    base: Any,
    extra: Any,
    *,
    root_label: str,
    base_root_label: Optional[str] = None,
) -> Dict[str, Any]:
    """F17 : agrege deux diagnostics de nettoyage residuel (multi-root).

    Compteurs sommes, listes concatenees/dedupliquees/bornees, statuts arbitres
    par rang d'activite, et detail par root conserve sous la cle purement
    additive `per_root` (tous les lecteurs font des `.get()` sur des cles
    nommees : aucune casse de forme).

    Revue R1 : `per_root` est desormais alimente pour TOUS les roots, y compris
    celui dont le diagnostic est vide. Avant, un root 1 sans diagnostic sortait
    de la fonction par le raccourci `if not base_d` et son entree etait perdue —
    le detail par root promis etait incomplet exactement dans le cas ou on en a
    besoin (savoir QUEL root a produit les dossiers deplaces). Seul le cas ou
    AUCUN root n'a de diagnostic reste rendu tel quel : sinon le resume
    imprimerait un bloc "DETAIL NETTOYAGE RESIDUEL" entierement a zero.
    """
    base_d = dict(base) if isinstance(base, dict) else {}
    extra_d = {k: v for k, v in dict(extra).items() if k != "per_root"} if isinstance(extra, dict) else {}
    base_per_root: Dict[str, Any] = (
        dict(base_d.get("per_root") or {}) if isinstance(base_d.get("per_root"), dict) else {}
    )
    base_own = {k: v for k, v in base_d.items() if k != "per_root"}
    if not base_own and not base_per_root and not extra_d:
        return base_d

    per_root: Dict[str, Any] = base_per_root
    if not per_root and base_root_label is not None:
        per_root[str(base_root_label)] = dict(base_own)
    per_root[str(root_label)] = dict(extra_d)

    if not extra_d:
        # Root secondaire muet : diagnostic de base inchange, mais on TRACE que
        # ce root n'a rien produit (sinon son absence de per_root se lit comme
        # "root jamais traite").
        merged = dict(base_own)
        merged["per_root"] = per_root
        return merged
    if not base_own:
        merged = dict(extra_d)
        merged["per_root"] = per_root
        return merged

    merged = dict(base_own)

    for key in _CLEANUP_DIAG_COUNTER_KEYS:
        base_val, extra_val = base_d.get(key), extra_d.get(key)
        if _is_plain_int(base_val) or _is_plain_int(extra_val):
            merged[key] = (int(base_val) if _is_plain_int(base_val) else 0) + (
                int(extra_val) if _is_plain_int(extra_val) else 0
            )
    # `enabled` est un bool : OR, surtout pas une somme (True + True == 2).
    if "enabled" in base_d or "enabled" in extra_d:
        merged["enabled"] = bool(base_d.get("enabled")) or bool(extra_d.get("enabled"))

    for key in _CLEANUP_DIAG_LIST_KEYS:
        base_list = base_d.get(key) if isinstance(base_d.get(key), list) else []
        extra_list = extra_d.get(key) if isinstance(extra_d.get(key), list) else []
        if not base_list and not extra_list:
            continue
        deduped: List[Any] = []
        for item in list(base_list) + list(extra_list):
            if item not in deduped:
                deduped.append(item)
            if len(deduped) >= _CLEANUP_DIAG_SAMPLE_MAX:
                break
        merged[key] = deduped

    pre_base = _cleanup_diag_rank(_CLEANUP_DIAG_STATUS_RANK, base_d.get("status"))
    pre_extra = _cleanup_diag_rank(_CLEANUP_DIAG_STATUS_RANK, extra_d.get("status"))
    if pre_extra > pre_base:
        merged["status"] = extra_d.get("status")
        merged["reason_code"] = extra_d.get("reason_code")
        merged["message"] = extra_d.get("message")
    post_base = _cleanup_diag_rank(_CLEANUP_DIAG_STATUS_POST_RANK, base_d.get("status_post"))
    post_extra = _cleanup_diag_rank(_CLEANUP_DIAG_STATUS_POST_RANK, extra_d.get("status_post"))
    if post_extra > post_base:
        merged["status_post"] = extra_d.get("status_post")
        merged["message_post"] = extra_d.get("message_post")

    per_root[str(root_label)] = dict(extra_d)
    merged["per_root"] = per_root
    return merged


def _merge_apply_results(
    result: Any,
    partial: Any,
    *,
    root_label: str,
    base_root_label: Optional[str] = None,
) -> Any:
    """F17 : fusionne l'ApplyResult d'un root secondaire dans l'agregat.

    Avant ce fix, seuls les champs `int` et le dict `skip_reasons` etaient
    fusionnes : `error_messages` (list) et `cleanup_residual_diagnostic` (dict)
    des roots 2..N etaient JETES. Consequence observable : le resume affichait
    "Erreurs : 1" SANS la section "ABANDONNE / EN ERREUR", et concluait
    "Aucun point d'attention bloquant apres apply." — exactement le silence que
    le fix RELECTURE R2 [D2] devait supprimer.

    `result` ALIASE l'ApplyResult du root 1 : les branches list/dict
    reconstruisent une nouvelle liste / un nouveau dict avant `setattr`, donc
    aucun aliasing cross-root n'est introduit.
    """
    for f in dataclasses.fields(partial):
        val = getattr(partial, f.name, None)
        if isinstance(val, bool):
            # bool est une sous-classe de int : sans cette branche AVANT celle
            # des int, un futur champ bool serait silencieusement somme a 2.
            # Aucun champ bool dans ApplyResult a ce jour -> garde anti-drift.
            setattr(result, f.name, bool(getattr(result, f.name, False)) or val)
        elif isinstance(val, int):
            setattr(result, f.name, int(getattr(result, f.name, 0) or 0) + val)
        elif isinstance(val, list):
            merged_list = list(getattr(result, f.name, None) or [])
            merged_list.extend(val)
            setattr(result, f.name, merged_list)
        elif isinstance(val, dict) and f.name == "cleanup_residual_diagnostic":
            setattr(
                result,
                f.name,
                _merge_cleanup_residual_diagnostic(
                    getattr(result, f.name, None),
                    val,
                    root_label=root_label,
                    base_root_label=base_root_label,
                ),
            )
        elif isinstance(val, dict) and f.name == "skip_reasons":
            merged_counts = dict(getattr(result, f.name, None) or {})
            for key, count in val.items():
                merged_counts[key] = merged_counts.get(key, 0) + int(count)
            setattr(result, f.name, merged_counts)
    return result


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
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    apply_atomic: bool = False,
) -> Tuple[Any, Optional[str], int]:
    """Applique un batch.

    P1.3 : `preview_ops_out` (si fournie) collecte les ops même en dry_run pour
    permettre à l'UI de construire une vue "avant/après" structurée sans
    toucher au filesystem. Ne change rien quand le caller ne la fournit pas.
    """
    try:
        # NB : accede via module pour permettre le mocking par patch.object(plan_support, ...).
        _plan_support_mod.find_duplicate_targets(cfg, rows, safe_decisions)
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
            store.apply.append_apply_operation(
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
        except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
            # F11 : sqlite3.Error n'herite PAS de OSError. Sans cette entree, un
            # "database is locked" avortait TOUT le batch APRES un move deja fait
            # sur disque -> etat mixte et rows restantes jamais traitees. Le type est
            # logue pour distinguer un lock transitoire d'une corruption reelle.
            log_fn("WARN", f"Journal operation apply ignoree ({type(exc).__name__}): {exc}")

    if not bool(dry_run):
        try:
            apply_batch_id = store.apply.insert_apply_batch(
                run_id=run_id,
                dry_run=False,
                quarantine_unapproved=bool(quarantine_unapproved),
                status="PENDING",
                summary={},
                app_version=api._app_version,
            )
            batch_state[0] = apply_batch_id
        except (OSError, TypeError, ValueError) as exc:
            # F11 — NE PAS ajouter sqlite3.Error ici (revue adversaire R1).
            #
            # L'invariant "un echec de journal n'empeche jamais un move" (cf.
            # move_journal.py:13-15) ne vaut QUE pour les operations journalisees
            # APRES un deplacement deja effectue. `insert_apply_batch` est appele
            # AVANT tout deplacement : si le batch ne peut pas etre cree, l'apply
            # s'executerait integralement sans aucune operation journalisee
            # (record_apply_op retourne tot quand apply_batch_id est None), donc
            # SANS AUCUN UNDO POSSIBLE — et serait rapporte ok. Un lock DB doit
            # ici faire echouer l'apply AVANT qu'il touche au disque.
            apply_batch_id = None
            log_fn("WARN", f"Journal apply indisponible: {exc}")

        # Vague P / VP-A : memoriser le mode atomique pour ce batch (opt-in
        # strict, default False). Tolerant : un echec n'empeche pas l'apply
        # de continuer — au pire on perd le badge UI "mode atomique" mais le
        # rollback_forward est toujours declenchable manuellement.
        if apply_batch_id is not None and bool(apply_atomic):
            try:
                store.apply.upsert_atomic_mode(str(apply_batch_id), True)
                log_fn("INFO", f"Mode atomique active pour batch {apply_batch_id}")
            except (sqlite3.Error, AttributeError, OSError, TypeError) as exc:
                log_fn("WARN", f"Mode atomique non persiste batch {apply_batch_id}: {exc}")
        elif apply_batch_id is None and bool(apply_atomic):
            # MEGA-HOTFIX bug #2 : avant ce fix, le mode atomique demande par
            # l'utilisateur etait silencieusement ignore quand insert_apply_batch
            # echouait (apply_batch_id reste None). Resultat : l'apply s'execute
            # en mode NON-atomique sans aucune trace dans les logs, et le
            # rollback_forward n'est plus declenchable (pas de batch_id pour
            # tracer les operations). Fallback explicite : on log un WARN clair
            # indiquant que le mode atomique est desactive faute de batch
            # persiste, et l'apply continue en mode best-effort (backward compat).
            log_fn(
                "WARN",
                "Mode atomique demande mais desactive : "
                "insert_apply_batch a echoue (apply_batch_id=None), "
                "le rollback_forward ne sera pas disponible pour ce batch. "
                "L'apply continue en mode non-atomique (best-effort).",
            )

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

    # Phase 6 doublons (spec 01-doublons.md §3.7) : recuperer la liste des losers
    # depuis la table duplicate_decisions pour les deplacer dans le bucket
    # `_duplicates_user_decided/` avant l'apply principal (cf
    # cinesort.app.apply_core.move_duplicate_losers_to_user_decided).
    #
    # F07 : la reconciliation (decision la plus recente prioritaire) est
    # deleguee a _resolve_duplicate_loser_row_ids — l'union brute des
    # loser_row_ids pouvait envoyer TOUTES les copies d'un film au bucket.
    # sqlite3.Error ajoute a l'except : il n'herite PAS d'OSError, donc une DB
    # verrouillee faisait CRASHER l'apply depuis un simple filet best-effort.
    duplicate_losers: Set[str] = set()
    try:
        decisions_db = store.apply.list_duplicate_decisions(run_id=run_id)
        duplicate_losers = _resolve_duplicate_loser_row_ids(decisions_db, log_fn)
    except (sqlite3.Error, AttributeError, OSError, TypeError, ValueError) as exc:
        log_fn("WARN", f"Lecture duplicate_decisions impossible: {exc}")

    # AUDIT 2026-06-14 (R7-3) : appliquer les overrides TMDb manuels (choix d'un
    # autre candidat via set_film_tmdb_candidate, table film_tmdb_overrides) sur
    # les PlanRows AVANT le calcul des destinations. Sans ca, l'apply renommait
    # avec le match auto et le choix utilisateur etait silencieusement perdu.
    # No-op si aucun override (comportement inchange pour le cas courant).
    try:
        for _r in rows:
            _rid_row = str(getattr(_r, "row_id", "") or "")
            if not _rid_row:
                continue
            _ov = store.film_modal.get_tmdb_override(run_id=run_id, row_id=_rid_row)
            if not _ov:
                continue
            if int(_ov.get("tmdb_id") or 0) > 0:
                _r.tmdb_id = int(_ov["tmdb_id"])
            if _ov.get("proposed_title"):
                _r.proposed_title = str(_ov["proposed_title"])
            if int(_ov.get("proposed_year") or 0) > 0:
                _r.proposed_year = int(_ov["proposed_year"])
    # Ultra-audit 2026-08 (N31) — l'absence de `sqlite3.Error` dans l'except
    # ci-dessous est DELIBEREE, contrairement au bloc duplicate_decisions
    # juste au-dessus. Ne pas « aligner » les deux tuples.
    #
    # Cet overlay materialise la DERNIERE volonte explicite de l'utilisateur, et
    # la boucle porte sur TOUTES les rows. Degrader une sqlite3.Error en WARN
    # ferait continuer l'apply avec un overlay PARTIEL (rows 0..k-1 overridees,
    # k..n non) et renommerait des dossiers avec le titre auto-matche, en
    # ecrasant silencieusement le choix manuel.
    #
    # Laisser remonter est fail-closed et sans perte : ce bloc s'execute AVANT
    # tout appel a `_apply_rows_fn`, et les deux appelants de `_execute_apply`
    # l'encadrent d'un try ; la boundary d'`apply_changes` clot alors le batch
    # en FAILED. Aucun fichier n'a bouge, rien n'est a annuler.
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        log_fn("WARN", f"Overlay overrides TMDb impossible: {exc}")

    # AUDIT 2026-06-14 (R7-4) : collecter les films marques pour suppression pour
    # les router vers _review/_user_marked_for_deletion/ a l'apply.
    #
    # AUDIT 2026-07-13 (HIGH-18) : le store de verite est desormais UNIQUE (table
    # DB film_marked_for_deletion) — le seul que l'UI sache annuler. L'ancien
    # store bulk (deletion_marks.json) n'est plus ecrit ; migrate_legacy_deletion_marks
    # le draine vers la DB (et retourne les row_ids concernes tant que la DB est
    # indisponible, pour ne rien perdre). Sans ce drain, un film demarque par
    # l'utilisateur repartait au bucket parce que le JSON, lui, ne connait aucun
    # retrait.
    #
    # Revue adversaire 2026-07-13 (defaut 3) : + sqlite3.Error (n'herite PAS
    # d'OSError) et RuntimeError — une DB verrouillee faisait sinon CRASHER
    # l'apply entier depuis un simple filet best-effort.
    marked_for_deletion: Set[str] = set()
    try:
        from cinesort.ui.api.library_actions_support import migrate_legacy_deletion_marks

        for _mid in migrate_legacy_deletion_marks(api, run_id):
            if _mid:
                marked_for_deletion.add(str(_mid))
    except (
        ImportError,
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
    ) as exc:
        log_fn("WARN", f"Migration deletion_marks.json impossible: {exc}")
    try:
        for _m in store.film_modal.list_marked_for_deletion(run_id=run_id) or []:
            _mid = str(_m.get("row_id") or "").strip()
            if _mid:
                marked_for_deletion.add(_mid)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
        log_fn("WARN", f"Lecture marked_for_deletion (DB) impossible: {exc}")

    # LOTD-DUP-BUCKET-VIEWER : les buckets quarantaine de l'apply vivent sous
    # <run_dir>/_review (ecritures conservees la, decision R8-002). On declare
    # ce runs root au viewer quarantaine pour que les losers y soient VISIBLES.
    with contextlib.suppress(AttributeError, OSError, TypeError, ValueError):
        _register_runs_root(Path(run_paths.run_dir).parent)

    # Multi-root : grouper les rows par source_root et appeler apply_rows par root
    rows_by_root: Dict[str, List[Any]] = {}
    for row in rows:
        rk = getattr(row, "source_root", None) or str(cfg.root)
        rows_by_root.setdefault(rk, []).append(row)

    root_keys = list(rows_by_root.keys())
    result = None
    result_root_label: Optional[str] = None

    for root_str in root_keys:
        root_rows = rows_by_root[root_str]
        root_path = Path(root_str)
        # Creer un cfg avec le bon root pour ce groupe.
        #
        # F06 : copie EXHAUSTIVE par dataclasses.replace. La recopie manuelle
        # des 28 kwargs qui vivait ici a derive TROIS fois (rustines ITER7
        # lowercase_extensions puis separator, puis naming_movie_template /
        # naming_tv_template / min_video_bytes / scan_max_workers oublies) :
        # tout root SECONDAIRE retombait sur les defaults dataclass
        # "{title} ({year})" / "{series} ({year})" et amputait le nom de dossier
        # du preset de nommage de l'utilisateur (dossiers uniquement — le
        # fichier video n'est jamais renomme). Ne JAMAIS re-lister les champs a
        # la main : tout champ ajoute a core.Config doit suivre automatiquement.
        #
        # NB : replace() ne rejoue pas Config.normalized() — comportement
        # strictement identique a la recopie manuelle qu'il remplace.
        if root_path != cfg.root and root_path.exists():
            cfg_for_root = dataclasses.replace(cfg, root=root_path)
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
            duplicate_loser_row_ids=duplicate_losers if duplicate_losers else None,
            marked_for_deletion_row_ids=marked_for_deletion if marked_for_deletion else None,
            progress_cb=progress_cb,
            audit_logger=auditor,
        )

        if result is None:
            result = partial
            result_root_label = root_str
        else:
            # F17 : merge complet (compteurs + error_messages + diagnostic de
            # nettoyage residuel), extrait en helper module-level pour etre
            # testable sans monter un apply entier.
            result = _merge_apply_results(
                result,
                partial,
                root_label=root_str,
                base_root_label=result_root_label,
            )

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
) -> Tuple[Dict[str, int], int, int, Dict[str, Any], bool]:
    """Finalise le batch et resume l'apply.

    Le 5e element du tuple, `journal_finalized`, dit si `close_apply_batch(DONE)`
    a REELLEMENT abouti. Il vaut False des que la finalisation a echoue : le
    batch reste alors `PENDING`, donc `get_last_reversible_apply_batch`
    (filtre `status='DONE'`) ne le verra pas et l'undo de cet apply est perdu.
    Le caller doit le remonter dans la reponse — un apply destructif dont le
    filet de securite a disparu ne peut pas etre annonce comme un succes muet.
    """
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
    journal_finalized = True
    if apply_batch_id is not None:
        try:
            store.apply.close_apply_batch(
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
        except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
            # F11 (suite) : sqlite3.Error n'herite PAS de OSError. `close_apply_batch`
            # est appelee APRES que tous les deplacements ont ete faits sur disque —
            # c'est exactement le cas ou l'invariant « un echec de journal n'empeche
            # jamais un move » s'applique (contrairement a `insert_apply_batch`
            # ci-dessus, volontairement fail-closed). Sans cette entree, un
            # « database is locked » (ThreadingHTTPServer du dashboard + threads de
            # fond concurrents, disque plein, disk I/O error) s'echappait de
            # _cleanup_apply, faisait remonter un apply REUSSI en HTTP 500 et — en
            # mode atomique — declenchait un rollback destructif.
            journal_finalized = False
            log_fn(
                "WARN",
                f"Journal apply non finalise ({type(exc).__name__}, batch_id={apply_batch_id}) : {exc} "
                "— l'apply disque est termine, mais le batch reste PENDING donc l'undo peut etre indisponible.",
            )
        except RuntimeError as exc:
            # MEGA-HOTFIX bug #1 : close_apply_batch leve ApplyBatchStateError
            # (sous-classe de RuntimeError, definie dans
            # cinesort.infra.db.repositories.apply) en cas de transition d'etat
            # invalide (ex : batch deja CLOSED ou ROLLED_BACK, batch_id
            # inexistant en base). Avant ce fix, l'exception remontait au
            # caller et faisait crasher l'apply ALORS QUE l'apply lui-meme
            # s'est deroule correctement — bug critique : utilisateur voit une
            # erreur 500 sur un apply reussi. On attrape via la classe parente
            # RuntimeError (ApplyBatchStateError n'est pas exportee via le
            # public API du module repositories) et on log un WARN explicite :
            # le batch est peut-etre deja finalise ailleurs, l'apply reel a
            # reussi, on preserve la backward compat.
            #
            # REVUE ADVERSAIRE PR#852 : ce chemin non plus n'a pas abouti a un
            # batch `DONE` (transition refusee = batch absent, ou deja dans un
            # etat terminal non reversible). L'undo n'est donc pas plus arme
            # ici que dans l'except ci-dessus -> meme drapeau.
            journal_finalized = False
            log_fn(
                "WARN",
                f"Journal apply non finalise (transition d'etat refusee, batch_id={apply_batch_id}) : {exc}",
            )
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
    return skip_counts, applied_count, total_rows, cleanup_diag, journal_finalized


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
            f"- Doublons (decision utilisateur) deplaces : {result.duplicates_user_decided_moved_count}\n"
            f"- Films marques pour suppression deplaces : {result.marked_for_deletion_moved_count}\n"
            f"- Conflits isoles en _review : {result.conflicts_quarantined_count}\n"
            f"- Conflits sidecars gardes des deux cotes : {result.sidecar_conflicts_kept_both_count}\n"
            f"- Conflits sidecars isoles : {result.conflicts_sidecars_quarantined_count}\n"
            f"- Leftovers deplaces : {result.leftovers_moved_count}\n"
            f"- Dossiers sources supprimes : {result.source_dirs_deleted_count}\n"
            f"- Dossiers vides deplaces (_Vide) : {result.empty_folders_moved_count}\n"
            f"- Dossiers residuels deplaces (_Dossier Nettoyage) : {result.cleanup_residual_folders_moved_count}\n"
        )

        # RELECTURE R2 [D2] : `result.error_messages` n'avait AUCUN lecteur. Les abandons
        # fail-closed (row_id ambigu -> operation destructive NON executee) et les echecs
        # filesystem n'apparaissaient nulle part : l'utilisateur lisait "Erreurs : 0 /
        # Films marques deplaces : 0" alors que son action n'avait tout simplement pas eu
        # lieu. On expose les messages dans le resume (surface lue par l'utilisateur).
        error_messages = [str(msg) for msg in (getattr(result, "error_messages", None) or []) if str(msg).strip()]
        if error_messages:
            shown = error_messages[:20]
            summary_block += "\nABANDONNE / EN ERREUR (a verifier)\n" + "".join(f"- {msg}\n" for msg in shown)
            if len(error_messages) > len(shown):
                summary_block += f"- ... et {len(error_messages) - len(shown)} autre(s) message(s) dans le journal\n"

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
            # F17 (revue R1) : en multi-root les compteurs sont SOMMES sur tous
            # les roots alors que `target_folder_*` reste celui du root 1. Un
            # total sous un seul bucket est trompeur : des que `per_root` existe,
            # on enumere le bucket ET le compte de CHAQUE root.
            per_root_diag = cleanup_diag.get("per_root") if isinstance(cleanup_diag.get("per_root"), dict) else {}
            default_bucket = cleanup_diag.get("target_folder_name") or cfg.cleanup_residual_folders_folder_name
            if per_root_diag:
                target_block = "- Dossiers cibles par root :\n"
                for root_label, root_diag in per_root_diag.items():
                    root_d = root_diag if isinstance(root_diag, dict) else {}
                    bucket = root_d.get("target_folder_path") or root_d.get("target_folder_name") or default_bucket
                    target_block += f"  - {root_label} -> {bucket} : {int(root_d.get('moved_count') or 0)} dossier(s)\n"
            else:
                target_block = f"- Dossier cible : {default_bucket}\n"
            summary_block += (
                "\n"
                "DETAIL NETTOYAGE RESIDUEL\n"
                f"- Active : {'oui' if bool(cleanup_diag.get('enabled')) else 'non'}\n"
                f"{target_block}"
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
        if error_messages:
            # [D2] : un abandon ne doit jamais tomber dans "Aucun point d'attention bloquant".
            # [R3] Formulation prudente : selon le message, une action DESTRUCTIVE demandee
            # (mise au bucket suppression / doublon) n'a pas ete appliquee, OU un fichier
            # n'a pu etre traite. Une row abandonnee cote destructif peut avoir ete
            # rangee/renommee par la boucle d'apply normale (cf. [D3]) : on n'affirme donc
            # PAS "rien n'a bouge", on renvoie vers le detail.
            action_lines.append(f"- {len(error_messages)} message(s) a verifier (cf. section ABANDONNE / EN ERREUR).")
        if result.conflicts_quarantined_count > 0:
            action_lines.append(f"- Conflits fichiers a verifier: {review_root / '_conflicts'}")
        if result.conflicts_sidecars_quarantined_count > 0:
            action_lines.append(f"- Conflits sidecars conserves: {review_root / '_conflicts_sidecars'}")
        if result.duplicates_identical_moved_count > 0:
            action_lines.append(f"- Duplicates identiques deplaces: {review_root / '_duplicates_identical'}")
        if result.duplicates_user_decided_moved_count > 0:
            # R8-018 : chemin de recuperation REEL des perdants d'une decision utilisateur
            # (avant, ces fichiers etaient comptes en _duplicates_identical -> chemin mensonger).
            action_lines.append(f"- Doublons decides (perdants) deplaces: {review_root / '_duplicates_user_decided'}")
        if result.marked_for_deletion_moved_count > 0:
            # R8-087 (filet F2-b) : le compteur marked existait (R7-4) mais n'avait NI ligne de
            # synthese NI chemin de recuperation -> bucket silencieux dans le rapport d'apply
            # (asymetrie aggravee par l'ajout du chemin loser R8-018). On expose le bucket reel.
            action_lines.append(
                f"- Films marques pour suppression deplaces: {review_root / '_user_marked_for_deletion'}"
            )
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
    url = str(data.get("jellyfin_url") or "").strip()
    api_key = str(data.get("jellyfin_api_key") or "").strip()
    # Cf issue #434 : clamp_timeout coherent avec cinesort_api.py (endpoints de test).
    timeout_s = clamp_timeout(data.get("jellyfin_timeout_s"), default=10.0)
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
        # Cf issue #434 : clamp_timeout coherent avec cinesort_api.py (endpoints de test).
        timeout_s = clamp_timeout(settings.get("plex_timeout_s"), default=10.0)
        # NB : accede via module pour permettre patch("cinesort.infra.plex_client.PlexClient").
        client = _plex_mod.PlexClient(plex_url, plex_token, timeout_s=timeout_s)
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
        return _safe_integration_error(exc, category="resource", log_module=__name__)


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
        # Cf issue #434 : clamp_timeout coherent avec cinesort_api.py (endpoints de test).
        timeout_s = clamp_timeout(settings.get("plex_timeout_s"), default=10.0)
        # NB : accede via module pour permettre patch("cinesort.infra.plex_client.PlexClient").
        client = _plex_mod.PlexClient(plex_url, plex_token, timeout_s=timeout_s)
        client.refresh_library(plex_lib)
        _log.info("api: refresh_plex_library_now declenche")
        return {"ok": True, "message": "Refresh Plex declenche."}
    except (IntegrationError, OSError, requests.RequestException) as exc:
        _log.warning("refresh_plex_library_now echoue: %s", exc)
        return _safe_integration_error(exc, category="resource", log_module=__name__)


def _snapshot_jellyfin_watched(api: Any, log_fn: Callable[[str, str], None]) -> Optional[Dict[str, Any]]:
    """Capture les statuts watched Jellyfin avant apply. Retourne None si desactive."""
    data = _read_jellyfin_settings(api)
    if not data:
        return None
    if not _to_bool(data.get("jellyfin_sync_watched"), True):
        return None
    try:
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
        client = _make_jellyfin_client(data)
        operations = store.apply.list_apply_operations(batch_id=apply_batch_id)
        result = restore_watched(client, user_id, snapshot, operations)
        if result.restored > 0:
            log_fn("INFO", f"Jellyfin sync : {result.restored} statut(s) vu restauré(s).")
        if result.counters_lost > 0:
            # #535 : le statut vu est revenu, mais pas le nombre de lectures ni
            # la date. Silencieux jusqu'ici, c'etait une perte de donnees
            # invisible pour l'utilisateur.
            log_fn(
                "WARN",
                f"Jellyfin sync : {result.counters_lost} film(s) restauré(s) SANS leur historique "
                "(nombre de lectures et date perdus — serveur trop ancien pour l'API UserData ?).",
            )
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
    apply_atomic: bool = False,
) -> Dict[str, Any]:
    """Applique les decisions.

    Vague P / VP-A : `apply_atomic` kwarg OPT-IN strict (default False).
    Si True ET apply reel (non dry-run), une exception en cours de batch
    declenche un `rollback_forward` (revert FS+DB du journal). La signature
    de retour reste `{ok: bool, ...}` (backward compat ABSOLUE — AC-1).
    """
    _log.info("api: apply run_id=%s dry_run=%s atomic=%s", run_id, dry_run, bool(apply_atomic))
    # Fix audit 2026-05-25 (v1.5.3) Vague H : context manager pour garantir
    # le release du slot meme si une exception se propage au-dela des except
    # locaux (avant ce fix, un crash inattendu laissait le slot bloque).
    with api._apply_slot_guard(run_id) as acquired:
        if not acquired:
            # R6-HTTP409-001 : conflit de concurrence (slot deja occupe) ->
            # HTTP 409 (opt-in Phase 11 v7.8.0). Backward compat : data.ok=false
            # reste inchange, seul le code HTTP change.
            return _err_response(
                t("errors.apply_already_in_progress"),
                category="state",
                level="info",
                log_module=__name__,
                http_status=409,
            )
        return _apply_changes_body(
            api,
            run_id,
            decisions,
            dry_run,
            quarantine_unapproved,
            cleanup_scope_label=cleanup_scope_label,
            cleanup_status_label=cleanup_status_label,
            cleanup_reason_label=cleanup_reason_label,
            apply_atomic=bool(apply_atomic),
        )


def _apply_changes_body(
    api: Any,
    run_id: str,
    decisions: Dict[str, Dict[str, Any]],
    dry_run: bool,
    quarantine_unapproved: bool,
    *,
    cleanup_scope_label: Callable[[str], str],
    cleanup_status_label: Callable[..., str],
    cleanup_reason_label: Callable[[str], str],
    apply_atomic: bool = False,
) -> Dict[str, Any]:
    """Corps de ``apply_changes`` une fois le slot apply acquis (cf
    ``_apply_slot_guard``). Le release est gere par le context manager
    parent — pas de ``finally`` ici.

    Vague P / VP-A : `apply_atomic` declenche un `rollback_forward` si le
    batch crashe APRES journalisation (cf. except Exception en bas).
    """
    validation = _validate_apply(api, run_id, decisions, dry_run, quarantine_unapproved)
    if not validation.get("ok"):
        return validation
    cfg, run_paths, rows, log_fn, store, safe_decisions, decision_presence = validation["_ctx"]

    log_fn("INFO", f"=== APPLY start (dry_run={dry_run}, quarantine={quarantine_unapproved}) ===")
    batch_state: List[Any] = [None, 0]  # [apply_batch_id, op_index] — mutable for _execute_apply

    # Progress apply : on attache un callback au RunState si present (run en
    # memoire). En mode DB-only, rs vaut None et le callback aussi : pas de
    # polling temps reel possible mais l'apply fonctionne quand meme.
    rs = None
    try:
        rs = api._get_run(run_id)
    except Exception:
        rs = None
    if rs is not None:
        try:
            rs.apply_begin(total=len(rows), dry_run=bool(dry_run), phase="rows")
        except Exception:
            _log.debug("apply_begin a echoue, on continue sans progress", exc_info=True)
    _apply_cb: Optional[Callable[[int, int, str], None]] = None
    if rs is not None:

        def _apply_cb(idx: int, total: int, current: str, _rs: Any = rs) -> None:  # noqa: E306
            try:
                _rs.apply_progress(idx, total, current, "rows")
            except Exception:
                _log.debug("apply_progress a echoue", exc_info=True)

    # Jellyfin Phase 2 : snapshot watched AVANT apply
    watched_ctx = None
    if not dry_run:
        watched_ctx = _snapshot_jellyfin_watched(api, log_fn)

    # Le rollback atomique ne doit rejouer QUE l'echec d'un apply incomplet. Ce
    # drapeau passe a True des que `_execute_apply` a rendu la main : au-dela, le
    # disque est dans l'etat voulu et toute exception ulterieure (finalisation du
    # journal, resume, notifications, sync Jellyfin/Plex) ne justifie plus de
    # defaire les deplacements — cf. le garde-fou plus bas.
    apply_execution_completed = False
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
                progress_cb=_apply_cb,
                apply_atomic=bool(apply_atomic),
            )
        except _DuplicateCheckError as exc:
            if rs is not None:
                try:
                    rs.apply_end(error=str(exc))
                except Exception:
                    _log.debug("apply_end a echoue", exc_info=True)
            return _err_response(str(exc), category="runtime", level="error", log_module=__name__)
        apply_batch_id = batch_id
        op_index = ops
        apply_execution_completed = True

        skip_counts, applied_count, total_rows, cleanup_diag, journal_finalized = _cleanup_apply(
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

        if rs is not None:
            try:
                rs.apply_progress(
                    int(getattr(rs, "apply_total", 0) or 0),
                    int(getattr(rs, "apply_total", 0) or 0),
                    "Synchronisation Jellyfin...",
                    "jellyfin",
                )
            except Exception:
                _log.debug("apply_progress phase jellyfin a echoue", exc_info=True)
        _trigger_jellyfin_refresh(api, log_fn, dry_run=dry_run)
        if rs is not None:
            try:
                rs.apply_progress(
                    int(getattr(rs, "apply_total", 0) or 0),
                    int(getattr(rs, "apply_total", 0) or 0),
                    "Synchronisation Plex...",
                    "plex",
                )
            except Exception:
                _log.debug("apply_progress phase plex a echoue", exc_info=True)
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
            _hook_data = {
                "run_id": run_id,
                "ts": time.time(),
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

        if rs is not None:
            try:
                rs.apply_end(error=None)
            except Exception:
                _log.debug("apply_end OK a echoue", exc_info=True)
        # REVUE ADVERSAIRE PR#852 — le silence etait le vrai defaut.
        #
        # Rendre `close_apply_batch` tolerante aux erreurs SQLite (F11) evite de
        # transformer un apply reussi en HTTP 500 et de declencher un rollback
        # destructif a tort. Mais elle transforme aussi un apply DONT L'UNDO EST
        # MORT en un `{"ok": True}` totalement muet : le batch reste `PENDING`,
        # `get_last_reversible_apply_batch` filtre `status='DONE'`, et
        # l'utilisateur ne l'apprend qu'en cliquant « Annuler » (message
        # generique « aucun apply annulable », sans lien avec l'apply qu'on
        # vient de lui annoncer comme reussi). Un WARN dans le log technique
        # n'est ni une information utilisateur ni une donnee exploitable par
        # l'UI. Sur le chemin destructif, perdre l'annulation de 500 films DOIT
        # etre une donnee de la reponse.
        #
        # `undo_available` couvre aussi le cas ou `insert_apply_batch` a echoue
        # (OSError/TypeError/ValueError -> apply_batch_id None, apply poursuivi
        # sans journal) et le dry-run (rien a annuler). Il exige EN PLUS au moins
        # une operation journalisee (`op_index`) : un batch clos DONE mais vide
        # n'est pas plus annulable qu'un batch PENDING, et annoncer
        # `undo_available: True` a une UI qui proposerait alors un bouton
        # « Annuler » inoperant serait le meme mensonge dans l'autre sens.
        undo_available = bool(
            not dry_run and apply_batch_id is not None and journal_finalized and int(op_index or 0) > 0
        )
        payload: Dict[str, Any] = {
            "ok": True,
            "result": result.__dict__,
            "apply_batch_id": apply_batch_id,
            "journal_finalized": bool(journal_finalized),
            "undo_available": undo_available,
        }
        # L'alerte ne se declenche que si l'apply a REELLEMENT touche au disque :
        # `applied_count` vient du resultat (donc reste vrai quand
        # `insert_apply_batch` a echoue et que `op_index` est reste a 0), et
        # `op_index` couvre les operations journalisees hors rows (nettoyage
        # residuel). Un apply qui n'a rien deplace n'a rien perdu : crier au loup
        # sur ce cas-la userait l'alerte exactement quand elle doit porter.
        disk_touched = int(applied_count or 0) > 0 or int(op_index or 0) > 0
        if not dry_run and disk_touched and not undo_available:
            warning = t("errors.undo_unavailable_after_apply")
            payload["journal_warning"] = warning
            log_fn("WARN", warning)
            # Un champ de payload que personne n'affiche serait un troisieme
            # silence. Le centre de notifications (la cloche) est le seul canal
            # qui SURVIT a la fermeture de l'ecran d'apply, et le miroir vers lui
            # est inconditionnel (NotifyService.notify) : il ne depend d'aucun
            # reglage de toasts desktop.
            try:
                api._notify.notify(
                    "error",
                    t("notifications.title_undo_unavailable"),
                    warning,
                    level="error",
                )
            except Exception:
                # Un echec de notification ne doit pas transformer un apply
                # disque REUSSI en HTTP 500 (ce serait re-creer le defaut F11).
                _log.debug("notification 'undo indisponible' non publiee", exc_info=True)
        return payload
    # except Exception intentionnel : boundary API endpoint apply_changes
    except Exception as exc:
        apply_batch_id = batch_state[0]
        op_index = batch_state[1]
        if apply_batch_id is not None:
            try:
                store.apply.close_apply_batch(
                    batch_id=apply_batch_id,
                    status="FAILED",
                    summary={
                        "run_id": run_id,
                        "dry_run": False,
                        "error": str(exc),
                        "ops_count": int(op_index),
                    },
                )
            except (sqlite3.Error, OSError, RuntimeError, TypeError, ValueError) as close_exc:
                # F11 (suite) : sans sqlite3.Error, un lock DB ici relevait une
                # exception DEPUIS le handler d'erreur — elle sortait de
                # _apply_changes_body avant meme le log « Echec application » et
                # avant le rollback, ne laissant qu'un HTTP 500 generique.
                log_fn(
                    "WARN",
                    f"Journal apply FAILED non finalise run_id={run_id} batch_id={apply_batch_id}: {close_exc}",
                )
        log_fn("ERROR", f"Echec application : {exc}")

        # Vague P / VP-A : rollback forward atomique si opt-in active.
        # AC-3 : rollback FS+DB coordonne — si DB rollback echoue, FS revert
        # tente quand meme + log d'audit. La fonction retourne toujours un
        # dict synthese qu'on logge sans propager (le caller recoit l'erreur
        # initiale via _err_response).
        atomic_rollback_summary: Optional[Dict[str, Any]] = None
        if bool(apply_atomic) and apply_batch_id is not None and apply_execution_completed:
            # L'apply lui-meme est alle au bout : le disque est dans l'etat
            # demande et defaire 500 deplacements reussis a cause d'un echec de
            # finalisation (journal verrouille, ecriture du resume, notification)
            # serait la pire issue possible. On le dit explicitement dans le log
            # d'apply pour que l'utilisateur sache pourquoi le badge « rollback
            # atomique » n'apparait pas.
            log_fn(
                "WARN",
                f"Mode atomique : rollback NON declenche batch={apply_batch_id} — l'apply s'est "
                f"execute jusqu'au bout, l'echec est posterieur aux deplacements ({exc}).",
            )
        elif bool(apply_atomic) and apply_batch_id is not None:
            try:
                atomic_rollback_summary = _atomic_rollback_forward(
                    store,
                    str(apply_batch_id),
                    audit_fn=log_fn,
                )
                log_fn(
                    "INFO",
                    f"Rollback atomique batch={apply_batch_id} status="
                    f"{atomic_rollback_summary.get('rollback_status')} "
                    f"counts={atomic_rollback_summary.get('counts')}",
                )
            except Exception as rb_exc:  # noqa: BLE001 - rollback must never re-raise
                log_fn(
                    "ERROR",
                    f"Rollback atomique a leve une exception batch={apply_batch_id}: {rb_exc}",
                )

            # R8-015 (F2-c) : refleter le resultat du rollback dans apply_batches.status.
            # Le batch a ete clos FAILED ci-dessus AVANT le revert ; si le revert a
            # COMPLETEMENT restaure le FS, le statut doit passer a ROLLED_BACK_BY_ATOMIC
            # (sinon apply_batches.status reste FAILED et ne dit pas si le FS est restaure).
            # Un revert partiel/echoue reste FAILED (l'etat est ambigu, garde la trace
            # rollback_status=ROLLBACK_PARTIAL/FAILED dans apply_batch_modes). Tolerant.
            if (
                atomic_rollback_summary is not None
                and bool(atomic_rollback_summary.get("ok"))
                and str(atomic_rollback_summary.get("rollback_status") or "") == "ROLLED_BACK_BY_ATOMIC"
                and apply_batch_id is not None
            ):
                try:
                    store.apply.close_apply_batch(
                        batch_id=str(apply_batch_id),
                        status="ROLLED_BACK_BY_ATOMIC",
                        summary={
                            "run_id": run_id,
                            "dry_run": False,
                            "error": str(exc),
                            "ops_count": int(op_index),
                            "rollback_status": "ROLLED_BACK_BY_ATOMIC",
                            "rollback_counts": atomic_rollback_summary.get("counts"),
                        },
                    )
                except (sqlite3.Error, OSError, RuntimeError, TypeError, ValueError) as st_exc:
                    # F11 (suite) : meme raison qu'aux deux except ci-dessus — le FS
                    # est deja restaure, un lock DB ne doit pas transformer ce simple
                    # marquage de statut en exception non rattrapee.
                    log_fn(
                        "WARN",
                        f"apply_batches.status non mis a jour vers ROLLED_BACK_BY_ATOMIC "
                        f"batch={apply_batch_id}: {st_exc}",
                    )

        api.log_api_exception(
            "apply",
            exc,
            run_id=run_id,
            store=store,
            extra={
                "dry_run": bool(dry_run),
                "quarantine_unapproved": bool(quarantine_unapproved),
                "decision_count": len(decisions),
                "apply_atomic": bool(apply_atomic),
                "atomic_rollback_status": (
                    str((atomic_rollback_summary or {}).get("rollback_status") or "") if atomic_rollback_summary else ""
                ),
            },
        )
        if rs is not None:
            try:
                rs.apply_end(error=str(exc))
            except Exception:
                _log.debug("apply_end KO a echoue", exc_info=True)
        err_payload = _err_response(
            t("errors.cannot_apply_changes"), category="state", level="warning", log_module=__name__
        )
        # AC-1 : on ENRICHIT le payload {ok: False, ...} avec la synthese
        # du rollback sans casser la signature (champ optionnel).
        if atomic_rollback_summary is not None:
            err_payload["atomic_rollback"] = atomic_rollback_summary
        if apply_batch_id is not None:
            err_payload["apply_batch_id"] = apply_batch_id
        return err_payload
    # Fix audit 2026-05-25 (v1.5.3) Vague H : plus de `finally:
    # api._release_apply_slot(run_id)` ici — gere par `_apply_slot_guard`
    # dans `apply_changes`.


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
        content = "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in events)
        return {"ok": True, "format": "jsonl", "content": content, "count": len(events)}
    if fmt == "csv":
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
        buf = io.StringIO()
        writer = csv.writer(buf)
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
    # Fix audit 2026-05-25 (v1.5.3) Vague H : utilise le context manager
    # pour eviter qu'un crash laisse le slot bloque (le code precedent
    # acquerait le slot via _validate_apply mais ne le liberait JAMAIS
    # — leak permanent du run_id).
    with api._apply_slot_guard(run_id) as acquired:
        if not acquired:
            # R6-HTTP409-001 : conflit de concurrence (slot deja occupe) ->
            # HTTP 409 (opt-in Phase 11 v7.8.0). Backward compat : data.ok=false
            # reste inchange, seul le code HTTP change.
            return _err_response(
                t("errors.apply_already_in_progress"),
                category="state",
                level="info",
                log_module=__name__,
                http_status=409,
            )
        return _build_apply_preview_body(
            api,
            run_id,
            decisions,
            cleanup_scope_label=cleanup_scope_label,
            cleanup_status_label=cleanup_status_label,
            cleanup_reason_label=cleanup_reason_label,
        )


def _build_apply_preview_body(
    api: Any,
    run_id: str,
    decisions: Dict[str, Dict[str, Any]],
    *,
    cleanup_scope_label: Callable[[str], str],
    cleanup_status_label: Callable[..., str],
    cleanup_reason_label: Callable[[str], str],
) -> Dict[str, Any]:
    """Corps de ``build_apply_preview`` une fois le slot acquis."""
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
        # Fix audit 2026-05-25 (v1.5.3) Vague F : enrichissement de chaque op
        # avec une decomposition dossier/fichier pour eviter d'afficher dans
        # l'UI un src->dst brut qui suggere a tort un renommage du fichier
        # video. apply_core.py ne renomme JAMAIS les fichiers video : seul
        # le dossier parent est renomme/deplace.
        src_path = str(op.get("src_path") or "")
        dst_path = str(op.get("dst_path") or "")
        op_type = str(op.get("op_type") or "")
        try:
            src_p = Path(src_path) if src_path else None
            dst_p = Path(dst_path) if dst_path else None
        except (ValueError, OSError):  # chemins malformes : best-effort
            src_p = None
            dst_p = None
        folder_old_name = src_p.parent.name if src_p is not None else ""
        folder_new_name = dst_p.parent.name if dst_p is not None else ""
        video_filename = src_p.name if src_p is not None else ""
        dst_filename = dst_p.name if dst_p is not None else ""
        # Determiner le type d'action pour le rendu UI
        if op_type == "MOVE_DIR":
            # Renommage de dossier : on deplace le dossier lui-meme,
            # les fichiers video a l'interieur conservent leur nom.
            action_summary = "folder_rename"
            # Pour un MOVE_DIR, src/dst sont des dossiers : folder_old/new_name
            # est le nom du dossier lui-meme (pas du parent).
            folder_old_name = src_p.name if src_p is not None else folder_old_name
            folder_new_name = dst_p.name if dst_p is not None else folder_new_name
            video_filename = ""  # un MOVE_DIR ne concerne pas un fichier specifique
        elif op_type == "MOVE_FILE":
            # Deplacement de fichier : nom de fichier conserve par apply_core,
            # seul le dossier parent change. Si le nom change quand meme
            # (TV episodes), on l'indique distinctement.
            if video_filename and dst_filename and video_filename != dst_filename:
                action_summary = "video_rename_tv"
            elif folder_old_name != folder_new_name:
                action_summary = "folder_rename_and_video_move"
            else:
                action_summary = "video_move"
        else:
            action_summary = op_type.lower() or "unknown"

        # Fix audit 2026-05-30 (APPLY-1) Vague J — defense en profondeur cote UI :
        # meme si une op a echappe au backend (regression future), on ne doit
        # PAS la presenter comme un rename si folder_old_name et folder_new_name
        # sont equivalents au sens filesystem Windows/SMB (case-insensitive +
        # NFC/NFD insensitive). Pour MOVE_FILE, on verifie en plus que le nom
        # de fichier video reste identique (sinon c'est un vrai rename TV).
        def _fs_equivalent_name(a: str, b: str) -> bool:
            if not a or not b:
                return False
            return unicodedata.normalize("NFC", a).casefold() == unicodedata.normalize("NFC", b).casefold()

        if op_type == "MOVE_DIR" and _fs_equivalent_name(folder_old_name, folder_new_name):
            action_summary = "noop_equivalent_fs"
        elif (
            op_type == "MOVE_FILE"
            and _fs_equivalent_name(folder_old_name, folder_new_name)
            and (not video_filename or not dst_filename or video_filename == dst_filename)
        ):
            action_summary = "noop_equivalent_fs"
        slim_op = {
            "op_type": op_type,
            "src_path": src_path,  # preserve pour retro-compat
            "dst_path": dst_path,  # preserve pour retro-compat
            "reversible": bool(op.get("reversible")),
            "folder_old_name": folder_old_name,
            "folder_new_name": folder_new_name,
            "video_filename": video_filename,
            "action_summary": action_summary,
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
    # Fix audit 2026-05-30 (APPLY-1) : on exclut les ops marquees
    # "noop_equivalent_fs" du decompte des ops effectives. Un film
    # dont TOUTES les ops sont equivalentes FS doit etre classe "noop"
    # pour ne pas apparaitre comme un changement dans l'UI.
    for film in films_list:
        effective_ops = [op for op in film["ops"] if op.get("action_summary") != "noop_equivalent_fs"]
        n_move_dir = sum(1 for op in effective_ops if op["op_type"] == "MOVE_DIR")
        n_move_file = sum(1 for op in effective_ops if op["op_type"] == "MOVE_FILE")
        if n_move_dir + n_move_file == 0:
            film["change_type"] = "noop"
        elif n_move_dir > 0 and n_move_file == 0:
            film["change_type"] = "rename_folder"
        elif n_move_file > 0 and n_move_dir == 0:
            film["change_type"] = "move_files"
        else:
            film["change_type"] = "move_mixed"

    # Stats globales à partir du résultat dry-run
    # Fix audit 2026-05-30 (APPLY-1) : nouveau compteur `noop_equivalent_fs`
    # pour observability des ops detectees comme equivalentes FS cote UI.
    noop_equivalent_fs_count = sum(
        1 for f in films_list for op in f["ops"] if op.get("action_summary") == "noop_equivalent_fs"
    )
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
        "noop_equivalent_fs": noop_equivalent_fs_count,
    }

    return {
        "ok": True,
        "films": films_list,
        "totals": totals,
        "orphan_ops": orphan_ops,  # ops système (buckets, nettoyage)
    }
