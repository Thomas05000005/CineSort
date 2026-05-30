"""Fix audit 2026-05-30 (v1.5.8) tier_v2 fallback dashboard.

Verifie que get_global_tier_distribution applique le fallback
COALESCE(perceptual.global_tier_v2, quality.tier) -- meme pattern que
library_support._build_library_rows -- pour eviter que le dashboard affiche
0 Platinum quand le run n'a pas eu d'analyse perceptuelle (perceptual_reports
vide).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend


class TierFallbackDashboardTests(unittest.TestCase):
    """Repro du bug audit Discovery : 0 Platinum affiche alors que
    quality_reports.tier = 'platinum' pour plusieurs films."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_audit_2026_05_30_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.store, _ = self.api._get_or_create_infra(self.state_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _insert_run(self, run_id: str, ts: float, total: int = 5) -> None:
        self.store.run.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={},
            created_ts=ts - 1,
        )
        self.store.run.mark_run_running(run_id, started_ts=ts)
        self.store.run.mark_run_done(run_id, stats={"planned_rows": total}, ended_ts=ts + 10)

    def _insert_quality(self, run_id: str, row_id: str, score: int, tier: str) -> None:
        self.store.quality.upsert_quality_report(
            run_id=run_id,
            row_id=row_id,
            score=score,
            tier=tier,
            reasons=[],
            metrics={},
            profile_id="default",
            profile_version=1,
        )

    def test_dashboard_platinum_count_uses_fallback_quality_tier(self) -> None:
        """5 quality_reports tier='platinum', 0 perceptual_reports.

        Avant le fix : la requete groupait par perceptual.global_tier_v2 (ou
        equivalent) seulement -> 0 Platinum.
        Apres le fix : COALESCE(perceptual.global_tier_v2, quality.tier) ->
        5 Platinum (via le tier V1 conserve dans quality_reports).
        """
        self._insert_run("run_audit_2026_05_30", 1000.0, total=5)
        for i in range(5):
            self._insert_quality(
                run_id="run_audit_2026_05_30",
                row_id=f"row_{i}",
                score=80,
                tier="platinum",
            )

        # Sanity : aucun perceptual_report inseré (run_id absent).
        perc_count = self.store.perceptual.get_perceptual_count_for_run(
            run_id="run_audit_2026_05_30"
        ) if hasattr(self.store.perceptual, "get_perceptual_count_for_run") else 0
        self.assertEqual(perc_count, 0, "Setup invalide : perceptual_reports devrait etre vide")

        result = self.api._get_global_stats_impl(20)
        self.assertTrue(result["ok"])

        # tier_distribution est directement le dict {tier_key: count}
        # (cf dashboard_support.py:1421 -> tier_data.get("tiers", {})).
        tiers = result["tier_distribution"]
        # Le fix LOWER la cle -> "platinum" en minuscule.
        platinum_count = int(tiers.get("platinum", 0) or 0)
        self.assertGreaterEqual(
            platinum_count,
            1,
            f"Platinum devrait etre >= 1 (fallback quality.tier), got {platinum_count}. "
            f"Distribution complete: {tiers}",
        )
        # Verif plus stricte : on a insere 5 films platinum -> on doit en trouver 5.
        self.assertEqual(
            platinum_count,
            5,
            f"Tous les 5 films tier=platinum devraient etre comptes, got {platinum_count}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
