"""AUDIT ULTRA 2026-07-13 (HIGH-8 residu) — page Qualite + get_global_stats.

La vague 2 a corrige get_latest_run (Accueil/sidebar) pour SAUTER les runs
utilitaires de bulk re-scan (marqueur config_json rescan_run_id), mais PAS :
  - get_global_stats (dashboard_support.py) qui prenait run_ids[0] brut ;
  - get_global_tier_distribution (repositories/quality.py) dont la sous-requete
    "dernier run" ne filtrait pas les rescans.

Consequence reproduite : apres un re-scan groupe, le run de tracking parasite
(sans plan ni quality_reports) devient le plus recent -> total_films / tier
distribution de la page Qualite tombent a 0, alors que la Bibliotheque reste
correcte.

Tests sur base SQLite REELLE + CineSortApi reel (convention projet, pas de mock).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend
from cinesort.infra.db.sqlite_store import SQLiteStore

# Config EXACT pose par library_actions_support.rescan_rows_bulk pour le run de tracking.
_RESCAN_CFG = {"rescan_run_id": "run-scan", "rescan_row_ids": ["row-0"]}


def _insert_run(store: SQLiteStore, run_id: str, *, config: dict, ts: float, total: int) -> None:
    store.run.insert_run_pending(run_id=run_id, root="D:/Films", state_dir="X", config=config, created_ts=ts - 1)
    store.run.mark_run_running(run_id, started_ts=ts)
    store.run.mark_run_done(run_id, stats={"planned_rows": total}, ended_ts=ts + 10.0)


def _insert_quality(store: SQLiteStore, run_id: str, row_id: str, tier: str) -> None:
    store.quality.upsert_quality_report(
        run_id=run_id,
        row_id=row_id,
        score=80,
        tier=tier,
        reasons=[],
        metrics={},
        profile_id="default",
        profile_version=1,
    )


class GlobalTierDistributionExcludesRescanTests(unittest.TestCase):
    """Repo : get_global_tier_distribution saute le run de tracking parasite."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_high8_repo_"))
        self.store = SQLiteStore(self._tmp / "cinesort.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        try:
            self.store.close()
        except (OSError, AttributeError):
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_latest_run_distribution_skips_rescan_parasite(self) -> None:
        _insert_run(self.store, "run-scan", config={"library_path": "D:/Films"}, ts=1000.0, total=5)
        for i in range(5):
            _insert_quality(self.store, "run-scan", f"row-{i}", "platinum")
        # Parasite bulk-rescan, plus recent, SANS quality_reports.
        _insert_run(self.store, "run-parasite", config=_RESCAN_CFG, ts=2000.0, total=0)

        dist = self.store.quality.get_global_tier_distribution(limit_runs=1)
        # AVANT le fix : {} / total_scored=0 (le parasite est le "dernier run").
        self.assertEqual(dist["tiers"].get("platinum", 0), 5, dist)
        self.assertEqual(dist["total_scored"], 5, dist)

    def test_no_rescan_still_targets_latest_scan(self) -> None:
        # Deux vrais scans : le plus recent doit gagner (pas de regression R6-F cumul).
        _insert_run(self.store, "run-scan-old", config={}, ts=1000.0, total=3)
        for i in range(3):
            _insert_quality(self.store, "run-scan-old", f"o-{i}", "bronze")
        _insert_run(self.store, "run-scan-new", config={}, ts=2000.0, total=2)
        for i in range(2):
            _insert_quality(self.store, "run-scan-new", f"n-{i}", "gold")

        dist = self.store.quality.get_global_tier_distribution(limit_runs=1)
        self.assertEqual(dist["tiers"].get("gold", 0), 2, dist)
        self.assertNotIn("bronze", dist["tiers"], dist)  # pas de cumul du run precedent
        self.assertEqual(dist["total_scored"], 2, dist)


class GlobalStatsExcludesRescanTests(unittest.TestCase):
    """API : get_global_stats reste sur le dernier run de SCAN apres un re-scan groupe."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_high8_api_"))
        self.root = self._tmp / "root"
        self.state_dir = self._tmp / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api.settings.save_settings(
            {"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False}
        )
        self.store, _ = self.api._get_or_create_infra(self.state_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_global_stats_unchanged_after_bulk_rescan(self) -> None:
        _insert_run(self.store, "run-scan", config={}, ts=1000.0, total=5)
        for i in range(5):
            _insert_quality(self.store, "run-scan", f"row-{i}", "platinum")

        before = self.api._get_global_stats_impl(20)
        self.assertTrue(before["ok"])
        self.assertEqual(before["summary"]["total_films"], 5)
        self.assertEqual(before["tier_distribution"].get("platinum", 0), 5)

        # Re-scan groupe -> run de tracking parasite (plus recent, sans plan/reports).
        _insert_run(self.store, "run-parasite", config=_RESCAN_CFG, ts=2000.0, total=0)

        after = self.api._get_global_stats_impl(20)
        self.assertTrue(after["ok"])
        # AVANT le fix : total_films=0 et tier_distribution={} (parasite pris comme dernier run).
        self.assertEqual(after["summary"]["total_films"], 5, after["summary"])
        self.assertEqual(after["tier_distribution"].get("platinum", 0), 5, after["tier_distribution"])


if __name__ == "__main__":
    unittest.main()
