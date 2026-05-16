"""_PerceptualMixin : thin wrapper backward-compat (issue #85 phase B4).

Migration #85 phase B4 (2026-05-16) : code metier deplace dans
`cinesort.infra.db.repositories.perceptual.PerceptualRepository`. Ce mixin
delegue a `self.perceptual.X()`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class _PerceptualMixin:
    """Backward-compat wrappers : delegue a self.perceptual (PerceptualRepository)."""

    def _ensure_perceptual_tables(self) -> None:
        self.perceptual._ensure_perceptual_tables()

    def upsert_perceptual_report(
        self,
        *,
        run_id: str,
        row_id: str,
        visual_score: int,
        audio_score: int,
        global_score: int,
        global_tier: str,
        metrics: Dict[str, Any],
        settings_used: Dict[str, Any],
        audio_fingerprint: Optional[str] = None,
        spectral_cutoff_hz: Optional[float] = None,
        lossy_verdict: Optional[str] = None,
        ssim_self_ref: Optional[float] = None,
        upscale_verdict: Optional[str] = None,
        global_score_v2: Optional[float] = None,
        global_tier_v2: Optional[str] = None,
        global_score_v2_payload: Optional[Dict[str, Any]] = None,
        ts: Optional[float] = None,
    ) -> None:
        self.perceptual.upsert_perceptual_report(
            run_id=run_id,
            row_id=row_id,
            visual_score=visual_score,
            audio_score=audio_score,
            global_score=global_score,
            global_tier=global_tier,
            metrics=metrics,
            settings_used=settings_used,
            audio_fingerprint=audio_fingerprint,
            spectral_cutoff_hz=spectral_cutoff_hz,
            lossy_verdict=lossy_verdict,
            ssim_self_ref=ssim_self_ref,
            upscale_verdict=upscale_verdict,
            global_score_v2=global_score_v2,
            global_tier_v2=global_tier_v2,
            global_score_v2_payload=global_score_v2_payload,
            ts=ts,
        )

    def get_perceptual_report(self, *, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        return self.perceptual.get_perceptual_report(run_id=run_id, row_id=row_id)

    def list_perceptual_reports(self, *, run_id: str) -> List[Dict[str, Any]]:
        return self.perceptual.list_perceptual_reports(run_id=run_id)

    def get_global_tier_v2_distribution(self, *, run_ids: List[str]) -> Dict[str, int]:
        return self.perceptual.get_global_tier_v2_distribution(run_ids=run_ids)

    def get_global_score_v2_trend(self, *, since_ts: float, until_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        return self.perceptual.get_global_score_v2_trend(since_ts=since_ts, until_ts=until_ts)

    def count_v2_tier_since(self, *, tier: str, since_ts: float) -> int:
        return self.perceptual.count_v2_tier_since(tier=tier, since_ts=since_ts)

    def count_v2_warnings_flag(self, *, flag: str, run_ids: List[str]) -> int:
        return self.perceptual.count_v2_warnings_flag(flag=flag, run_ids=run_ids)

    def _parse_perceptual_row(self, row: Any) -> Dict[str, Any]:
        return self.perceptual._parse_perceptual_row(row)
