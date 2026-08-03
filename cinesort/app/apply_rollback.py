"""Apply atomic forward rollback (Vague P / VP-A).

Lorsqu'un batch apply est lance avec le flag `apply_atomic=True` et qu'une
exception interrompt le flux APRES que certaines operations aient deja ete
journalisees + executees sur le filesystem, on declenche un `rollback_forward` :
le journal `apply_operations` est replay en sens inverse (dst -> src) en
respectant le pattern `connect(autocommit=False)` PEP 249 pour coordonner
FS et DB.

Differences avec l'undo manuel :
- L'undo classique (`apply_support.undo_last_apply`) cible un batch DONE et
  est declenche par l'utilisateur ; il consulte `get_last_reversible_apply_batch`
  qui filtre sur `status='DONE'`.
- Le `rollback_forward` cible un batch FAILED in-flight (status='PENDING'
  ou 'FAILED') et est declenche par le code lui-meme. Il ecrit dans la
  table dediee `apply_batch_modes.rollback_status` pour ne PAS percuter la
  chaine undo manuelle (`apply_operations.undo_status`).

Acceptance criteria (plan VP-A) :
- AC-3 : rollback FS+DB atomique — si DB rollback echoue, FS revert tente
  avec log d'audit, status='ROLLBACK_FAILED' ou 'ROLLBACK_PARTIAL'.

Design notes :
- Le module est tolerant aux fichiers manquants (move source absent ou
  destination renommee entre l'apply et le rollback) — on log et on continue,
  status final 'ROLLBACK_PARTIAL'.
- On NE TOUCHE PAS aux operations dont `undo_status='DONE'` (deja annulees
  par un undo manuel concurrent — peu probable mais memo M-00 nous oblige
  a etre defensif).
- On utilise `shutil.move` direct (subprocess hors propos pour FS), pas
  `safe_move`/`journaled_move` (on est DEJA dans un rollback — pas de
  nouveau journal a empiler).
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_logger = logging.getLogger(__name__)

# Status values pour `apply_batch_modes.rollback_status`
ROLLBACK_NONE = "NONE"
ROLLBACK_IN_PROGRESS = "IN_PROGRESS"
ROLLBACK_DONE = "ROLLED_BACK_BY_ATOMIC"
ROLLBACK_FAILED = "ROLLBACK_FAILED"
ROLLBACK_PARTIAL = "ROLLBACK_PARTIAL"


def _audit_log(
    audit_fn: Optional[Callable[[str, str], None]],
    level: str,
    message: str,
) -> None:
    """Helper : log via callback fourni OU logger module sinon."""
    if audit_fn is not None:
        try:
            audit_fn(level, message)
            return
        except Exception:  # noqa: BLE001 - audit must never break rollback
            _logger.debug("audit_fn failed", exc_info=True)
    if level == "ERROR":
        _logger.error("%s", message)
    elif level == "WARN":
        _logger.warning("%s", message)
    else:
        _logger.info("%s", message)


def _revert_one_op(
    op: Dict[str, Any],
    *,
    audit_fn: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """Tente de revert une op individuelle (dst -> src). Retourne un dict resultat.

    Resultat : {"id": int, "op_index": int, "status": "DONE"|"SKIPPED"|"FAILED",
                "reason": str}
    """
    op_id = int(op.get("id") or 0)
    op_index = int(op.get("op_index") or 0)
    op_type = str(op.get("op_type") or "").upper()
    src_path = str(op.get("src_path") or "")
    dst_path = str(op.get("dst_path") or "")
    reversible = int(op.get("reversible") or 0)
    undo_status = str(op.get("undo_status") or "PENDING")
    # Hotfix2 H6 : src_sha1 = hash du fichier original avant le move (peut etre
    # None si journal anterieur a la migration 013 ou si calcul a echoue).
    expected_src_sha1 = op.get("src_sha1")
    if expected_src_sha1 is not None:
        expected_src_sha1 = str(expected_src_sha1) or None

    if not reversible:
        return {
            "id": op_id,
            "op_index": op_index,
            "status": "SKIPPED",
            "reason": "irreversible",
        }
    if undo_status in ("DONE", "FAILED", "SKIPPED"):
        # deja traite par undo manuel ou cycle precedent
        return {
            "id": op_id,
            "op_index": op_index,
            "status": "SKIPPED",
            "reason": f"undo_status={undo_status}",
        }

    # AUDIT 2026-06-10 (HIGH, REAL 2/2) : QUARANTINE_FILE/QUARANTINE_DIR sont
    # journalisees avec reversible=True et src_path/dst_path de meme semantique
    # que les MOVE (origine -> _review/...). Les exclure ici laissait les
    # fichiers en quarantaine apres un rollback atomique tout en retournant
    # ok=True (FS non restaure). Le revert dst->src est strictement identique.
    if op_type not in ("MOVE_FILE", "MOVE_DIR", "QUARANTINE_FILE", "QUARANTINE_DIR"):
        return {
            "id": op_id,
            "op_index": op_index,
            "status": "SKIPPED",
            "reason": f"op_type={op_type or 'EMPTY'} non revert-able",
        }

    if not src_path or not dst_path:
        return {
            "id": op_id,
            "op_index": op_index,
            "status": "SKIPPED",
            "reason": "src/dst vides",
        }

    dst = Path(dst_path)
    src = Path(src_path)

    if not dst.exists():
        _audit_log(
            audit_fn,
            "WARN",
            f"rollback_forward: dst manquant op_id={op_id} dst={dst_path} — skipped",
        )
        return {
            "id": op_id,
            "op_index": op_index,
            "status": "SKIPPED",
            "reason": "dst_missing",
        }

    if src.exists():
        _audit_log(
            audit_fn,
            "WARN",
            f"rollback_forward: src deja present op_id={op_id} src={src_path} — skipped",
        )
        return {
            "id": op_id,
            "op_index": op_index,
            "status": "SKIPPED",
            "reason": "src_already_exists",
        }

    backup_tmp: Optional[Path] = None
    try:
        src.parent.mkdir(parents=True, exist_ok=True)
        # Hotfix2 H6 : defense TOCTOU. Si src est apparu entre la verification
        # ligne ~140 et maintenant (course user copie/cree fichier au meme path),
        # shutil.move ECRASERAIT silencieusement le fichier user (data loss).
        # On re-check et si le hash differe du src_sha1 journalise (ou si on
        # n'a pas de hash de reference), on SKIP au lieu d'ecraser.
        if src.exists():
            user_file_safe = False
            if expected_src_sha1:
                try:
                    # Import local : evite cycle au module-load et garde
                    # apply_rollback utilisable meme si apply_core indisponible.
                    from cinesort.app.apply_core import sha1_quick

                    actual_src_sha1 = sha1_quick(src)
                    if actual_src_sha1 and actual_src_sha1 == expected_src_sha1:
                        # Meme contenu qu'avant l'apply : on peut ecraser sans
                        # risque de data loss (c'est une copie/restauration
                        # identique du fichier originel).
                        user_file_safe = True
                except (OSError, ImportError) as hash_exc:  # noqa: BLE001
                    _audit_log(
                        audit_fn,
                        "WARN",
                        f"rollback_forward: hash check FAILED op_id={op_id} "
                        f"src={src_path}: {hash_exc} — assume user file, skip",
                    )
            if not user_file_safe:
                _audit_log(
                    audit_fn,
                    "WARN",
                    f"rollback_forward: src apparu pendant rollback op_id={op_id} "
                    f"src={src_path} — fichier user different, skipped (no overwrite)",
                )
                return {
                    "id": op_id,
                    "op_index": op_index,
                    "status": "SKIPPED",
                    "reason": "src_appeared_during_rollback",
                }
            # Hash identique : on retire le fichier present pour permettre move
            # (shutil.move sur Windows refuse l'ecrasement, on doit unlink).
            # HOTFIX data-loss : on backup vers tmp AVANT unlink, et on restaure
            # si shutil.move echoue ensuite (sinon perte definitive du fichier
            # user meme s'il etait byte-identique au src originel).
            backup_tmp = src.with_suffix(src.suffix + ".rollback_bak")
            # Si un backup_tmp orphelin traine (ancien rollback interrompu),
            # on le retire d'abord pour eviter conflit sur le rename.
            # REG-DATA-001 : avant d'unlink, on verifie que c'est bien un
            # backup d'un rollback precedent (hash match expected_src_sha1)
            # et PAS un fichier user portant fortuitement ce suffixe.
            if backup_tmp.exists():
                orphan_is_safe = False
                if expected_src_sha1:
                    try:
                        from cinesort.app.apply_core import sha1_quick

                        orphan_sha1 = sha1_quick(backup_tmp)
                        if orphan_sha1 and orphan_sha1 == expected_src_sha1:
                            orphan_is_safe = True
                    except (OSError, ImportError) as orphan_hash_exc:
                        _audit_log(
                            audit_fn,
                            "WARN",
                            f"rollback_forward: orphan backup hash check FAILED op_id={op_id} "
                            f"backup={backup_tmp}: {orphan_hash_exc} — assume user file",
                        )
                if not orphan_is_safe:
                    # Soit pas de hash de reference (op anterieure migration 013),
                    # soit hash different : on REFUSE d'effacer un fichier user
                    # potentiel. On abort cette op, le rollback de cette entree
                    # est skipped (memo cohesion avec L194-198).
                    _audit_log(
                        audit_fn,
                        "ERROR",
                        f"rollback_forward: orphan backup present with unknown content op_id={op_id} "
                        f"backup={backup_tmp} — refusing to unlink (potential user file), skipped",
                    )
                    return {
                        "id": op_id,
                        "op_index": op_index,
                        "status": "SKIPPED",
                        "reason": "orphan_backup_present",
                    }
                try:
                    backup_tmp.unlink()
                except OSError as orphan_exc:
                    _audit_log(
                        audit_fn,
                        "WARN",
                        f"rollback_forward: orphan backup unlink FAILED op_id={op_id} "
                        f"backup={backup_tmp}: {orphan_exc}",
                    )
            try:
                # rename atomique src -> backup_tmp (preserve les donnees)
                src.rename(backup_tmp)
            except OSError as unlink_exc:
                _audit_log(
                    audit_fn,
                    "ERROR",
                    f"rollback_forward: backup dup src FAILED op_id={op_id} src={src_path}: {unlink_exc}",
                )
                return {
                    "id": op_id,
                    "op_index": op_index,
                    "status": "FAILED",
                    "reason": f"backup_dup_src: {unlink_exc}",
                }
        try:
            shutil.move(str(dst), str(src))
        except (OSError, PermissionError) as move_exc:
            # HOTFIX data-loss : restauration du backup si on en a cree un.
            # Si on a renomme src -> backup_tmp puis que shutil.move a echoue,
            # le fichier user serait perdu sans cette restauration.
            if backup_tmp is not None and backup_tmp.exists():
                try:
                    if not src.exists():
                        backup_tmp.rename(src)
                        _audit_log(
                            audit_fn,
                            "WARN",
                            f"rollback_forward: move FAILED, backup restored op_id={op_id} src={src_path}: {move_exc}",
                        )
                    else:
                        # src reapparu (course rare) : on preserve le backup
                        # sous le suffix .rollback_bak plutot que d'ecraser.
                        _audit_log(
                            audit_fn,
                            "ERROR",
                            f"rollback_forward: move FAILED and src reappeared op_id={op_id} "
                            f"src={src_path}: backup preserved at {backup_tmp}: {move_exc}",
                        )
                except OSError as restore_exc:
                    _audit_log(
                        audit_fn,
                        "ERROR",
                        f"rollback_forward: backup restore FAILED op_id={op_id} "
                        f"backup={backup_tmp} -> src={src_path}: {restore_exc} "
                        f"(original move error: {move_exc})",
                    )
            raise
        else:
            # Move succes : on peut retirer le backup_tmp (les donnees du
            # backup_tmp etaient identiques au contenu maintenant restaure
            # depuis dst, hash deja verifie ligne ~174).
            if backup_tmp is not None and backup_tmp.exists():
                try:
                    backup_tmp.unlink()
                except OSError as cleanup_exc:
                    _audit_log(
                        audit_fn,
                        "WARN",
                        f"rollback_forward: backup cleanup FAILED op_id={op_id} "
                        f"backup={backup_tmp}: {cleanup_exc} (non-fatal)",
                    )
    except (OSError, PermissionError) as exc:
        _audit_log(
            audit_fn,
            "ERROR",
            f"rollback_forward: revert FAILED op_id={op_id} dst={dst_path} -> src={src_path}: {exc}",
        )
        return {
            "id": op_id,
            "op_index": op_index,
            "status": "FAILED",
            "reason": str(exc),
        }

    return {
        "id": op_id,
        "op_index": op_index,
        "status": "DONE",
        "reason": "",
    }


def rollback_forward(
    store: Any,
    batch_id: str,
    *,
    audit_fn: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """Replay inverse du journal `apply_operations` pour un batch in-flight.

    Coordonne FS+DB via `connect(autocommit=False)` PEP 249 (pattern SQLite
    2026). Retourne un dict synthese :
        {
            "ok": bool,
            "batch_id": str,
            "rollback_status": "ROLLED_BACK_BY_ATOMIC"|"ROLLBACK_FAILED"|"ROLLBACK_PARTIAL",
            "counts": {"done": int, "skipped": int, "failed": int},
            "details": [<dict per op>],
            "message": str,
        }

    AC-3 : si la mise a jour DB du `rollback_status` echoue APRES revert FS
    reussi, on log l'audit mais on retourne quand meme ok=True avec status
    'ROLLBACK_PARTIAL' (le FS est dans l'etat voulu, juste la DB n'a pas pu
    le tracer — le caller decidera quoi en faire).
    """
    bid = str(batch_id or "").strip()
    if not bid:
        return {
            "ok": False,
            "batch_id": "",
            "rollback_status": ROLLBACK_FAILED,
            "counts": {"done": 0, "skipped": 0, "failed": 0},
            "details": [],
            "message": "batch_id vide",
        }

    # Marquer en cours immediatement (idempotent)
    try:
        store.apply.mark_rollback_status(bid, ROLLBACK_IN_PROGRESS)
    except (sqlite3.Error, AttributeError, OSError) as exc:
        _audit_log(
            audit_fn,
            "WARN",
            f"rollback_forward: mark IN_PROGRESS impossible batch={bid}: {exc}",
        )
        # On continue quand meme : l'objectif est de revert le FS.

    # Charger les ops dans l'ordre de creation (op_index croissant) puis
    # inverser : on revert d'abord la derniere op effectuee.
    try:
        ops = store.apply.list_apply_operations(batch_id=bid)
    except (sqlite3.Error, AttributeError, OSError) as exc:
        _audit_log(
            audit_fn,
            "ERROR",
            f"rollback_forward: list_apply_operations FAILED batch={bid}: {exc}",
        )
        return {
            "ok": False,
            "batch_id": bid,
            "rollback_status": ROLLBACK_FAILED,
            "counts": {"done": 0, "skipped": 0, "failed": 0},
            "details": [],
            "message": f"list_apply_operations failed: {exc}",
        }

    if not ops:
        # Aucune op a revert — succes immediat
        _final_status_attempt(store, bid, ROLLBACK_DONE, audit_fn)
        return {
            "ok": True,
            "batch_id": bid,
            "rollback_status": ROLLBACK_DONE,
            "counts": {"done": 0, "skipped": 0, "failed": 0},
            "details": [],
            "message": "no ops to rollback",
        }

    # Reverse order : la derniere op faite est annulee en premier.
    ops_reversed: List[Dict[str, Any]] = list(reversed(ops))

    details: List[Dict[str, Any]] = []
    done = 0
    skipped = 0
    failed = 0

    for op in ops_reversed:
        result = _revert_one_op(op, audit_fn=audit_fn)
        details.append(result)
        if result["status"] == "DONE":
            done += 1
        elif result["status"] == "SKIPPED":
            skipped += 1
        elif result["status"] == "FAILED":
            failed += 1

        # R8-012 (F2-c) : marquer le statut undo OP-LEVEL apres le revert. Avant,
        # rollback_forward revertait le FS mais ne touchait jamais
        # apply_operations.undo_status -> un batch atomiquement reverti apparaissait
        # "pending_ops=total, undone_ops=0" (entierement annulable) alors que le FS
        # etait deja revenu a src. Marquer ici rend l'etat op-level coherent ET
        # rollback_forward idempotent/reprenable (un re-run skippe les undo_status=DONE,
        # cf R8-013). On NE retrograde PAS une op deja terminale (skip "undo_status=...").
        _new_undo: Optional[str] = None
        if result["status"] == "DONE":
            _new_undo = "DONE"
        elif result["status"] == "FAILED":
            _new_undo = "FAILED"
        elif result["status"] == "SKIPPED" and not str(result.get("reason") or "").startswith("undo_status="):
            _new_undo = "SKIPPED"
        if _new_undo is not None and result.get("id"):
            try:
                store.apply.mark_apply_operation_undo_status(
                    op_id=int(result["id"]),
                    undo_status=_new_undo,
                    error_message=(str(result.get("reason") or "") if _new_undo == "FAILED" else None),
                )
            except (sqlite3.Error, AttributeError, OSError) as _mark_exc:
                _audit_log(
                    audit_fn,
                    "WARN",
                    f"rollback_forward: mark undo_status={_new_undo} impossible op_id={result.get('id')}: {_mark_exc}",
                )

    # Final status logique
    if failed == 0:
        final_status = ROLLBACK_DONE
        ok = True
        message = f"rollback_forward: {done} revert / {skipped} skipped — batch={bid}"
    elif done == 0:
        final_status = ROLLBACK_FAILED
        ok = False
        message = f"rollback_forward: {failed} echec(s), aucun revert reussi — batch={bid}"
    else:
        final_status = ROLLBACK_PARTIAL
        ok = False
        message = f"rollback_forward: PARTIEL — {done} revert, {failed} echec(s), {skipped} skipped — batch={bid}"

    # AC-3 : la mise a jour DB peut echouer, on log mais le FS est dans
    # l'etat post-revert. On retourne quand meme la synthese (ok reste true
    # si le FS est OK).
    db_mark_ok = _final_status_attempt(store, bid, final_status, audit_fn)
    if not db_mark_ok and ok:
        # FS reverti, DB pas marque -> on degrade en ROLLBACK_PARTIAL pour
        # signaler au caller que la trace persistante est incomplete.
        final_status = ROLLBACK_PARTIAL
        message = f"{message} (DB tracking failed, FS revert reussi)"

    return {
        "ok": ok,
        "batch_id": bid,
        "rollback_status": final_status,
        "counts": {"done": done, "skipped": skipped, "failed": failed},
        "details": details,
        "message": message,
    }


def _final_status_attempt(
    store: Any,
    batch_id: str,
    status: str,
    audit_fn: Optional[Callable[[str, str], None]],
) -> bool:
    """Marque le rollback_status final. True si la DB a pu etre mise a jour."""
    try:
        store.apply.mark_rollback_status(
            batch_id,
            status,
            rolled_back_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        return True
    except (sqlite3.Error, AttributeError, OSError) as exc:
        _audit_log(
            audit_fn,
            "ERROR",
            f"rollback_forward: mark {status} FAILED batch={batch_id}: {exc}",
        )
        return False
