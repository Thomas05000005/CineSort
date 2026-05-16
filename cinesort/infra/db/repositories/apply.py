"""ApplyRepository : apply batches + operations + pending moves (issue #85 phase B7).

Migration #85 phase B7 (2026-05-16) : meme pattern que B1-B6 :
- Code metier vit DANS ApplyRepository
- _ApplyMixin devient thin wrapper backward-compat
- SQLiteStore conserve son inheritance

Note specifique B7 : `mark_apply_batch_undo_status` appelle `self.close_apply_batch`
en interne. Dans ApplyRepository, `self.close_apply_batch` est la methode locale
(meme classe) — pas d'indirection.

Methodes exposees :
    insert_apply_batch, append_apply_operation, close_apply_batch,
    get_last_reversible_apply_batch, list_apply_operations,
    mark_apply_operation_undo_status, mark_apply_batch_undo_status,
    list_apply_batches_for_run, get_batch_rows_summary,
    list_apply_operations_by_row, insert_pending_move, delete_pending_move,
    list_pending_moves, count_pending_moves
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from cinesort.infra.db.repositories._base import _BaseRepository


class ApplyRepository(_BaseRepository):
    """Repository pour les operations apply (batches + operations + pending moves)."""

    def _ensure_apply_journal_tables(self) -> None:
        self._ensure_schema_group("apply_journal")

    def insert_apply_batch(
        self,
        *,
        run_id: str,
        dry_run: bool,
        quarantine_unapproved: bool,
        status: str = "PENDING",
        summary: Optional[Dict[str, Any]] = None,
        app_version: str = "unknown",
        started_ts: Optional[float] = None,
        batch_id: Optional[str] = None,
    ) -> str:
        self._ensure_apply_journal_tables()
        now = float(started_ts if started_ts is not None else time.time())
        bid = str(batch_id or f"{int(now * 1000)}_{uuid4().hex}")
        payload = json.dumps(summary or {}, ensure_ascii=False, sort_keys=True)
        with self._managed_conn() as conn:
            conn.execute(
                """
                INSERT INTO apply_batches(
                  batch_id, run_id, started_ts, ended_ts, dry_run,
                  quarantine_unapproved, status, summary_json, app_version
                )
                VALUES(?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    bid,
                    str(run_id),
                    now,
                    1 if bool(dry_run) else 0,
                    1 if bool(quarantine_unapproved) else 0,
                    str(status or "PENDING"),
                    payload,
                    str(app_version or "unknown"),
                ),
            )
        return bid

    def append_apply_operation(
        self,
        *,
        batch_id: str,
        op_index: int,
        op_type: str,
        src_path: str,
        dst_path: str,
        reversible: bool,
        ts: Optional[float] = None,
        row_id: Optional[str] = None,
        src_sha1: Optional[str] = None,
        src_size: Optional[int] = None,
    ) -> int:
        """Enregistre une operation apply.

        P1.2 : `src_sha1` et `src_size` sont le fingerprint du fichier deplace
        (calcule avant le move, donc equivalent au fichier present a `dst_path`
        apres apply). Utilises par l'undo pour refuser de deplacer un fichier
        que l'utilisateur aurait remplace manuellement entre apply et undo.
        """
        self._ensure_apply_journal_tables()
        now = float(ts if ts is not None else time.time())
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO apply_operations(
                  batch_id, op_index, op_type, src_path, dst_path, reversible,
                  undo_status, error_message, ts, row_id, src_sha1, src_size
                )
                VALUES(?, ?, ?, ?, ?, ?, 'PENDING', NULL, ?, ?, ?, ?)
                """,
                (
                    str(batch_id),
                    int(op_index),
                    str(op_type or "MOVE"),
                    str(src_path),
                    str(dst_path),
                    1 if bool(reversible) else 0,
                    now,
                    str(row_id) if row_id else None,
                    str(src_sha1) if src_sha1 else None,
                    int(src_size) if src_size is not None else None,
                ),
            )
            return int(cur.lastrowid)

    def close_apply_batch(
        self,
        *,
        batch_id: str,
        status: str,
        summary: Optional[Dict[str, Any]] = None,
        ended_ts: Optional[float] = None,
    ) -> None:
        self._ensure_apply_journal_tables()
        now = float(ended_ts if ended_ts is not None else time.time())
        payload = json.dumps(summary or {}, ensure_ascii=False, sort_keys=True)
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE apply_batches
                SET status=?, ended_ts=?, summary_json=?
                WHERE batch_id=?
                """,
                (str(status), now, payload, str(batch_id)),
            )

    def get_last_reversible_apply_batch(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retourne le dernier batch apply reel (non dry-run) DONE pour ce run, sinon None."""
        self._ensure_apply_journal_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT batch_id, run_id, started_ts, ended_ts, dry_run, quarantine_unapproved, status, summary_json, app_version
                FROM apply_batches
                WHERE run_id=? AND dry_run=0 AND status='DONE'
                ORDER BY started_ts DESC
                LIMIT 1
                """,
                (str(run_id),),
            )
            row = cur.fetchone()
        if not row:
            return None
        summary = self._decode_row_json(row, "summary_json", default={}, expected_type=dict)
        return {
            "batch_id": str(row["batch_id"]),
            "run_id": str(row["run_id"]),
            "started_ts": float(row["started_ts"] or 0.0),
            "ended_ts": float(row["ended_ts"] or 0.0) if row["ended_ts"] is not None else None,
            "dry_run": int(row["dry_run"] or 0),
            "quarantine_unapproved": int(row["quarantine_unapproved"] or 0),
            "status": str(row["status"] or ""),
            "summary": summary,
            "app_version": str(row["app_version"] or ""),
        }

    def list_apply_operations(self, *, batch_id: str) -> List[Dict[str, Any]]:
        """Retourne les operations apply du batch dans l'ordre d'execution (op_index croissant)."""
        self._ensure_apply_journal_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT id, batch_id, op_index, op_type, src_path, dst_path, reversible,
                       undo_status, error_message, ts, row_id, src_sha1, src_size
                FROM apply_operations
                WHERE batch_id=?
                ORDER BY op_index ASC, id ASC
                """,
                (str(batch_id),),
            )
            rows = cur.fetchall()
        return [
            {
                "id": int(r["id"]),
                "batch_id": str(r["batch_id"]),
                "op_index": int(r["op_index"]),
                "op_type": str(r["op_type"]),
                "src_path": str(r["src_path"]),
                "dst_path": str(r["dst_path"]),
                "reversible": int(r["reversible"] or 0),
                "undo_status": str(r["undo_status"] or "PENDING"),
                "error_message": str(r["error_message"] or ""),
                "ts": float(r["ts"] or 0.0),
                "row_id": str(r["row_id"] or ""),
                "src_sha1": str(r["src_sha1"] or "") or None,
                "src_size": int(r["src_size"]) if r["src_size"] is not None else None,
            }
            for r in rows
        ]

    def mark_apply_operation_undo_status(
        self,
        *,
        op_id: int,
        undo_status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Met a jour le statut undo d'une operation (PENDING / DONE / FAILED / SKIPPED)."""
        self._ensure_apply_journal_tables()
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE apply_operations
                SET undo_status=?, error_message=?
                WHERE id=?
                """,
                (str(undo_status or "PENDING"), str(error_message or "") or None, int(op_id)),
            )

    def mark_apply_batch_undo_status(
        self,
        *,
        batch_id: str,
        status: str,
        summary: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Clot le batch cote undo en mettant a jour son statut + summary via `close_apply_batch`."""
        # self.close_apply_batch est la methode locale (meme classe)
        self.close_apply_batch(
            batch_id=batch_id,
            status=str(status),
            summary=summary or {},
            ended_ts=time.time(),
        )

    # --- Undo v5: per-row methods ---

    def list_apply_batches_for_run(self, *, run_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Return all batches for a run (not just the last DONE), most recent first."""
        self._ensure_apply_journal_tables()
        lim = max(1, int(limit))
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT batch_id, run_id, started_ts, ended_ts, dry_run,
                       quarantine_unapproved, status, summary_json, app_version
                FROM apply_batches
                WHERE run_id=?
                ORDER BY started_ts DESC
                LIMIT ?
                """,
                (str(run_id), lim),
            )
            rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            summary = self._decode_row_json(row, "summary_json", default={}, expected_type=dict)
            out.append(
                {
                    "batch_id": str(row["batch_id"]),
                    "run_id": str(row["run_id"]),
                    "started_ts": float(row["started_ts"] or 0.0),
                    "ended_ts": float(row["ended_ts"] or 0.0) if row["ended_ts"] is not None else None,
                    "dry_run": int(row["dry_run"] or 0),
                    "quarantine_unapproved": int(row["quarantine_unapproved"] or 0),
                    "status": str(row["status"] or ""),
                    "summary": summary,
                    "app_version": str(row["app_version"] or ""),
                }
            )
        return out

    def get_batch_rows_summary(self, *, batch_id: str) -> List[Dict[str, Any]]:
        """Per-row summary of a batch: for each row_id, count total/reversible/undone/pending ops."""
        self._ensure_apply_journal_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT
                  COALESCE(row_id, '__legacy__') AS row_id,
                  COUNT(*) AS total_ops,
                  SUM(CASE WHEN reversible = 1 THEN 1 ELSE 0 END) AS reversible_ops,
                  SUM(CASE WHEN undo_status = 'DONE' THEN 1 ELSE 0 END) AS undone_ops,
                  SUM(CASE WHEN undo_status = 'PENDING' THEN 1 ELSE 0 END) AS pending_ops,
                  SUM(CASE WHEN undo_status = 'FAILED' THEN 1 ELSE 0 END) AS failed_ops,
                  SUM(CASE WHEN undo_status = 'SKIPPED' THEN 1 ELSE 0 END) AS skipped_ops
                FROM apply_operations
                WHERE batch_id = ?
                GROUP BY COALESCE(row_id, '__legacy__')
                ORDER BY MIN(op_index)
                """,
                (str(batch_id),),
            )
            return [
                {
                    "row_id": str(r["row_id"]),
                    "total_ops": int(r["total_ops"] or 0),
                    "reversible_ops": int(r["reversible_ops"] or 0),
                    "undone_ops": int(r["undone_ops"] or 0),
                    "pending_ops": int(r["pending_ops"] or 0),
                    "failed_ops": int(r["failed_ops"] or 0),
                    "skipped_ops": int(r["skipped_ops"] or 0),
                }
                for r in cur.fetchall()
            ]

    def list_apply_operations_by_row(self, *, batch_id: str, row_id: str) -> List[Dict[str, Any]]:
        """Operations for a specific row_id within a batch."""
        self._ensure_apply_journal_tables()
        effective_row_id = None if row_id == "__legacy__" else str(row_id)
        with self._managed_conn() as conn:
            if effective_row_id is None:
                cur = conn.execute(
                    """
                    SELECT id, batch_id, op_index, op_type, src_path, dst_path,
                           reversible, undo_status, error_message, ts, row_id,
                           src_sha1, src_size
                    FROM apply_operations
                    WHERE batch_id=? AND row_id IS NULL
                    ORDER BY op_index ASC, id ASC
                    """,
                    (str(batch_id),),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, batch_id, op_index, op_type, src_path, dst_path,
                           reversible, undo_status, error_message, ts, row_id,
                           src_sha1, src_size
                    FROM apply_operations
                    WHERE batch_id=? AND row_id=?
                    ORDER BY op_index ASC, id ASC
                    """,
                    (str(batch_id), effective_row_id),
                )
            rows = cur.fetchall()
        return [
            {
                "id": int(r["id"]),
                "batch_id": str(r["batch_id"]),
                "op_index": int(r["op_index"]),
                "op_type": str(r["op_type"]),
                "src_path": str(r["src_path"]),
                "dst_path": str(r["dst_path"]),
                "reversible": int(r["reversible"] or 0),
                "undo_status": str(r["undo_status"] or "PENDING"),
                "error_message": str(r["error_message"] or ""),
                "ts": float(r["ts"] or 0.0),
                "row_id": str(r["row_id"] or ""),
                "src_sha1": str(r["src_sha1"] or "") or None,
                "src_size": int(r["src_size"]) if r["src_size"] is not None else None,
            }
            for r in rows
        ]

    # =====================================================================
    # CR-1 audit QA 20260429 : journal write-ahead pour atomicite shutil.move
    # =====================================================================
    # Pattern : INSERT pending AVANT shutil.move, DELETE pending APRES move
    # reussi. Si l'app crashe entre les deux, l'entree reste pour
    # reconciliation au prochain boot (cf cinesort.app.move_reconciliation).

    def _ensure_apply_pending_tables(self) -> None:
        self._ensure_schema_group("apply_pending")

    def insert_pending_move(
        self,
        *,
        op_type: str,
        src_path: str,
        dst_path: str,
        batch_id: Optional[str] = None,
        src_sha1: Optional[str] = None,
        src_size: Optional[int] = None,
        row_id: Optional[str] = None,
        ts: Optional[float] = None,
    ) -> int:
        """Enregistre un move en attente. Retourne le pending_id (lastrowid)."""
        self._ensure_apply_pending_tables()
        now = float(ts if ts is not None else time.time())
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO apply_pending_moves(
                  batch_id, op_type, src_path, dst_path,
                  src_sha1, src_size, row_id, ts
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(batch_id) if batch_id else None,
                    str(op_type or "MOVE_FILE"),
                    str(src_path),
                    str(dst_path),
                    str(src_sha1) if src_sha1 else None,
                    int(src_size) if src_size is not None else None,
                    str(row_id) if row_id else None,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def delete_pending_move(self, pending_id: int) -> None:
        """Supprime une entree pending apres move reussi. Tolere id inconnu."""
        self._ensure_apply_pending_tables()
        with self._managed_conn() as conn:
            conn.execute(
                "DELETE FROM apply_pending_moves WHERE id=?",
                (int(pending_id),),
            )

    def list_pending_moves(self, *, batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retourne les pending moves orphelins.

        A appeler au boot pour reconciliation : tout ce qui est en table est
        considere comme orphelin (un move qui s'est commit ou rollback proprement
        a deja ete supprime via delete_pending_move).
        """
        self._ensure_apply_pending_tables()
        with self._managed_conn() as conn:
            if batch_id is None:
                cur = conn.execute(
                    """
                    SELECT id, batch_id, op_type, src_path, dst_path,
                           src_sha1, src_size, row_id, ts
                    FROM apply_pending_moves
                    ORDER BY ts ASC, id ASC
                    """
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, batch_id, op_type, src_path, dst_path,
                           src_sha1, src_size, row_id, ts
                    FROM apply_pending_moves
                    WHERE batch_id=?
                    ORDER BY ts ASC, id ASC
                    """,
                    (str(batch_id),),
                )
            rows = cur.fetchall()
        return [
            {
                "id": int(r["id"]),
                "batch_id": str(r["batch_id"] or "") or None,
                "op_type": str(r["op_type"]),
                "src_path": str(r["src_path"]),
                "dst_path": str(r["dst_path"]),
                "src_sha1": str(r["src_sha1"] or "") or None,
                "src_size": int(r["src_size"]) if r["src_size"] is not None else None,
                "row_id": str(r["row_id"] or "") or None,
                "ts": float(r["ts"] or 0.0),
            }
            for r in rows
        ]

    def count_pending_moves(self) -> int:
        """Nombre de pending moves orphelins (utile pour metrics et health)."""
        self._ensure_apply_pending_tables()
        with self._managed_conn() as conn:
            cur = conn.execute("SELECT COUNT(*) AS n FROM apply_pending_moves")
            row = cur.fetchone()
        return int(row["n"]) if row else 0
