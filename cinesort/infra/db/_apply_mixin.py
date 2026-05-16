"""_ApplyMixin : thin wrapper backward-compat (issue #85 phase B7).

Migration #85 phase B7 (2026-05-16) : code metier deplace dans
`cinesort.infra.db.repositories.apply.ApplyRepository`. Ce mixin delegue
a `self.apply.X()`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class _ApplyMixin:
    """Backward-compat wrappers : delegue a self.apply (ApplyRepository)."""

    def _ensure_apply_journal_tables(self) -> None:
        self.apply._ensure_apply_journal_tables()

    def _ensure_apply_pending_tables(self) -> None:
        self.apply._ensure_apply_pending_tables()

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
        return self.apply.insert_apply_batch(
            run_id=run_id,
            dry_run=dry_run,
            quarantine_unapproved=quarantine_unapproved,
            status=status,
            summary=summary,
            app_version=app_version,
            started_ts=started_ts,
            batch_id=batch_id,
        )

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
        return self.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=op_index,
            op_type=op_type,
            src_path=src_path,
            dst_path=dst_path,
            reversible=reversible,
            ts=ts,
            row_id=row_id,
            src_sha1=src_sha1,
            src_size=src_size,
        )

    def close_apply_batch(
        self,
        *,
        batch_id: str,
        status: str,
        summary: Optional[Dict[str, Any]] = None,
        ended_ts: Optional[float] = None,
    ) -> None:
        self.apply.close_apply_batch(batch_id=batch_id, status=status, summary=summary, ended_ts=ended_ts)

    def get_last_reversible_apply_batch(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self.apply.get_last_reversible_apply_batch(run_id)

    def list_apply_operations(self, *, batch_id: str) -> List[Dict[str, Any]]:
        return self.apply.list_apply_operations(batch_id=batch_id)

    def mark_apply_operation_undo_status(
        self,
        *,
        op_id: int,
        undo_status: str,
        error_message: Optional[str] = None,
    ) -> None:
        self.apply.mark_apply_operation_undo_status(op_id=op_id, undo_status=undo_status, error_message=error_message)

    def mark_apply_batch_undo_status(
        self,
        *,
        batch_id: str,
        status: str,
        summary: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.apply.mark_apply_batch_undo_status(batch_id=batch_id, status=status, summary=summary)

    def list_apply_batches_for_run(self, *, run_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self.apply.list_apply_batches_for_run(run_id=run_id, limit=limit)

    def get_batch_rows_summary(self, *, batch_id: str) -> List[Dict[str, Any]]:
        return self.apply.get_batch_rows_summary(batch_id=batch_id)

    def list_apply_operations_by_row(self, *, batch_id: str, row_id: str) -> List[Dict[str, Any]]:
        return self.apply.list_apply_operations_by_row(batch_id=batch_id, row_id=row_id)

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
        return self.apply.insert_pending_move(
            op_type=op_type,
            src_path=src_path,
            dst_path=dst_path,
            batch_id=batch_id,
            src_sha1=src_sha1,
            src_size=src_size,
            row_id=row_id,
            ts=ts,
        )

    def delete_pending_move(self, pending_id: int) -> None:
        self.apply.delete_pending_move(pending_id)

    def list_pending_moves(self, *, batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.apply.list_pending_moves(batch_id=batch_id)

    def count_pending_moves(self) -> int:
        return self.apply.count_pending_moves()
