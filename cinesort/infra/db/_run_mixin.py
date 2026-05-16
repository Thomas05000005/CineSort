"""_RunMixin : thin wrapper backward-compat (issue #85 phase B6).

Migration #85 phase B6 (2026-05-16) : code metier deplace dans
`cinesort.infra.db.repositories.run.RunRepository`. Ce mixin delegue
a `self.run.X()`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class _RunMixin:
    """Backward-compat wrappers : delegue a self.run (RunRepository)."""

    def _insert_pending_run_row(self, conn: Any, **kwargs: Any) -> None:
        # Helper interne — delegue au repo
        self.run._insert_pending_run_row(conn, **kwargs)

    def _ensure_runs_table(self) -> None:
        self.run._ensure_runs_table()

    def insert_run_pending(
        self,
        *,
        run_id: str,
        root: str,
        state_dir: str,
        config: Dict[str, Any],
        created_ts: Optional[float] = None,
    ) -> None:
        self.run.insert_run_pending(run_id=run_id, root=root, state_dir=state_dir, config=config, created_ts=created_ts)

    def mark_run_running(self, run_id: str, *, started_ts: Optional[float] = None) -> None:
        self.run.mark_run_running(run_id, started_ts=started_ts)

    def update_run_progress(self, run_id: str, *, idx: int, total: int, current_folder: str) -> None:
        self.run.update_run_progress(run_id, idx=idx, total=total, current_folder=current_folder)

    def mark_cancel_requested(self, run_id: str) -> None:
        self.run.mark_cancel_requested(run_id)

    def mark_run_done(
        self, run_id: str, *, stats: Optional[Dict[str, Any]] = None, ended_ts: Optional[float] = None
    ) -> None:
        self.run.mark_run_done(run_id, stats=stats, ended_ts=ended_ts)

    def mark_run_cancelled(
        self, run_id: str, *, stats: Optional[Dict[str, Any]] = None, ended_ts: Optional[float] = None
    ) -> None:
        self.run.mark_run_cancelled(run_id, stats=stats, ended_ts=ended_ts)

    def mark_run_failed(self, run_id: str, *, error_message: str, ended_ts: Optional[float] = None) -> None:
        self.run.mark_run_failed(run_id, error_message=error_message, ended_ts=ended_ts)

    def insert_error(
        self,
        *,
        run_id: str,
        step: str,
        code: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        ts: Optional[float] = None,
    ) -> None:
        self.run.insert_error(run_id=run_id, step=step, code=code, message=message, context=context, ts=ts)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self.run.get_run(run_id)

    def list_errors(self, run_id: str) -> List[Dict[str, Any]]:
        return self.run.list_errors(run_id)

    def get_latest_run(self) -> Optional[Dict[str, Any]]:
        return self.run.get_latest_run()

    def list_runs(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        return self.run.list_runs(limit=limit)

    def get_runs_summary(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        return self.run.get_runs_summary(limit=limit)

    def get_error_counts_for_runs(self, run_ids: List[str]) -> Dict[str, int]:
        return self.run.get_error_counts_for_runs(run_ids)
