"""_QualityMixin : thin wrapper backward-compat (issue #85 phase B5).

Migration #85 phase B5 (2026-05-16) : code metier deplace dans
`cinesort.infra.db.repositories.quality.QualityRepository`. Ce mixin delegue
a `self.quality.X()`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class _QualityMixin:
    """Backward-compat wrappers : delegue a self.quality (QualityRepository)."""

    def _ensure_quality_tables(self) -> None:
        self.quality._ensure_quality_tables()

    def get_active_quality_profile(self) -> Optional[Dict[str, Any]]:
        return self.quality.get_active_quality_profile()

    def save_quality_profile(
        self,
        *,
        profile_id: str,
        version: int,
        profile_json: Dict[str, Any],
        is_active: bool = True,
        ts: Optional[float] = None,
    ) -> None:
        self.quality.save_quality_profile(
            profile_id=profile_id,
            version=version,
            profile_json=profile_json,
            is_active=is_active,
            ts=ts,
        )

    def get_quality_report(self, *, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        return self.quality.get_quality_report(run_id=run_id, row_id=row_id)

    def upsert_quality_report(
        self,
        *,
        run_id: str,
        row_id: str,
        score: int,
        tier: str,
        reasons: List[str],
        metrics: Dict[str, Any],
        profile_id: str,
        profile_version: int,
        ts: Optional[float] = None,
    ) -> None:
        self.quality.upsert_quality_report(
            run_id=run_id,
            row_id=row_id,
            score=score,
            tier=tier,
            reasons=reasons,
            metrics=metrics,
            profile_id=profile_id,
            profile_version=profile_version,
            ts=ts,
        )

    def list_quality_reports(self, *, run_id: str) -> List[Dict[str, Any]]:
        return self.quality.list_quality_reports(run_id=run_id)

    def insert_user_quality_feedback(
        self,
        *,
        run_id: str,
        row_id: str,
        computed_score: int,
        computed_tier: str,
        user_tier: str,
        tier_delta: int,
        category_focus: Optional[str] = None,
        comment: Optional[str] = None,
        app_version: str = "",
    ) -> int:
        return self.quality.insert_user_quality_feedback(
            run_id=run_id,
            row_id=row_id,
            computed_score=computed_score,
            computed_tier=computed_tier,
            user_tier=user_tier,
            tier_delta=tier_delta,
            category_focus=category_focus,
            comment=comment,
            app_version=app_version,
        )

    def list_user_quality_feedback(
        self,
        *,
        run_id: Optional[str] = None,
        row_id: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        return self.quality.list_user_quality_feedback(run_id=run_id, row_id=row_id, limit=limit)

    def delete_user_quality_feedback(self, *, feedback_id: int) -> int:
        return self.quality.delete_user_quality_feedback(feedback_id=feedback_id)

    def get_quality_report_stats(self, *, run_id: str) -> Dict[str, Any]:
        return self.quality.get_quality_report_stats(run_id=run_id)

    def get_global_tier_distribution(self, *, limit_runs: int = 20) -> Dict[str, Any]:
        return self.quality.get_global_tier_distribution(limit_runs=limit_runs)

    def get_unscored_film_count(self, *, run_id: str, total_rows: int) -> int:
        return self.quality.get_unscored_film_count(run_id=run_id, total_rows=total_rows)

    def get_quality_counts_for_runs(self, run_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        return self.quality.get_quality_counts_for_runs(run_ids)
