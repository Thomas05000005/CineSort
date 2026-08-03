"""AUDIT ULTRA 2026-07-13 vague 2 — compteurs cote REPOSITORY.

H6 (HIGH-7) APPLIED_ROWS TOUJOURS 0 : le nombre de films appliques vit dans
apply_batches.summary_json.applied_count (ecrit par l'apply), PAS dans
runs.stats_json.applied_count (cle jamais ecrite). On teste la nouvelle source
de verite cote LECTURE : store.apply.get_applied_counts_for_runs (BULK) et le
"summary" de get_last_reversible_apply_batch.

H7 (HIGH-8) RESOLUTION DU DERNIER RUN : store.run.get_latest_run() doit SAUTER
les runs utilitaires de bulk re-scan (marqueur config_json rescan_run_id), sinon
les KPI Accueil + badges sidebar tombent a 0 apres un re-scan groupe.

Tests sur base SQLite REELLE (convention projet, pas de mock DB).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.infra.db.sqlite_store import SQLiteStore


class _StoreTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_wave2_"))
        self.state_dir = self._tmp / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(self.state_dir / "cinesort.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        try:
            self.store.close()
        except (OSError, AttributeError):
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _insert_run(self, run_id: str, *, config: dict, created_ts: float, done: bool = True) -> None:
        self.store.run.insert_run_pending(
            run_id=run_id,
            root="D:/Films",
            state_dir=str(self.state_dir),
            config=config,
            created_ts=created_ts,
        )
        self.store.run.mark_run_running(run_id, started_ts=created_ts)
        if done:
            self.store.run.mark_run_done(run_id, stats={"planned_rows": 1}, ended_ts=created_ts + 10.0)


class AppliedCountsFromBatchTests(_StoreTestBase):
    """H6 : la source de verite est apply_batches.summary_json, pas runs.stats_json."""

    def test_applied_count_read_from_apply_batch_summary(self) -> None:
        self._insert_run("run-1", config={"library_path": "D:/Films"}, created_ts=1000.0)
        # L'apply ecrit applied_count DANS summary_json (jamais dans runs.stats_json).
        bid = self.store.apply.insert_apply_batch(
            run_id="run-1",
            dry_run=False,
            quarantine_unapproved=False,
            status="PENDING",
            summary={"applied_count": 843, "total_rows": 905},
            started_ts=1010.0,
        )
        self.store.apply.close_apply_batch(
            batch_id=bid, status="DONE", summary={"applied_count": 843, "total_rows": 905}, ended_ts=1020.0
        )

        # Nouveau helper BULK (n'existait pas avant le fix -> AttributeError).
        counts = self.store.apply.get_applied_counts_for_runs(["run-1"])
        self.assertEqual(counts.get("run-1"), 843)

        # Et le "summary" du dernier batch reversible porte bien la cle (lu par history_support).
        batch = self.store.apply.get_last_reversible_apply_batch("run-1")
        self.assertIsNotNone(batch)
        self.assertEqual(int((batch.get("summary") or {}).get("applied_count") or 0), 843)

    def test_dry_run_batches_are_ignored(self) -> None:
        self._insert_run("run-1", config={"library_path": "D:/Films"}, created_ts=1000.0)
        bid = self.store.apply.insert_apply_batch(
            run_id="run-1",
            dry_run=True,  # dry-run -> NE doit PAS compter
            quarantine_unapproved=False,
            status="DONE",
            summary={"applied_count": 999},
            started_ts=1010.0,
        )
        self.assertTrue(bid)
        counts = self.store.apply.get_applied_counts_for_runs(["run-1"])
        self.assertEqual(counts.get("run-1", 0), 0)

    def test_latest_done_batch_wins_over_older(self) -> None:
        self._insert_run("run-1", config={"library_path": "D:/Films"}, created_ts=1000.0)
        for started, applied in ((1010.0, 100), (1050.0, 200)):
            bid = self.store.apply.insert_apply_batch(
                run_id="run-1",
                dry_run=False,
                quarantine_unapproved=False,
                status="PENDING",
                summary={"applied_count": applied},
                started_ts=started,
            )
            self.store.apply.close_apply_batch(
                batch_id=bid, status="DONE", summary={"applied_count": applied}, ended_ts=started + 5.0
            )
        counts = self.store.apply.get_applied_counts_for_runs(["run-1"])
        self.assertEqual(counts.get("run-1"), 200)  # dernier batch DONE

    def test_empty_ids_returns_empty(self) -> None:
        self.assertEqual(self.store.apply.get_applied_counts_for_runs([]), {})


class GetLatestRunExcludesRescanTests(_StoreTestBase):
    """H7 : get_latest_run saute les runs de tracking bulk-rescan (marqueur config)."""

    def test_rescan_parasite_is_skipped(self) -> None:
        self._insert_run("run-scan-1", config={"library_path": "D:/Films"}, created_ts=1000.0)
        # Exactement le config pose par library_actions_support.rescan_rows_bulk.
        self._insert_run(
            "run-parasite-1",
            config={"rescan_run_id": "run-scan-1", "rescan_row_ids": ["row-1"]},
            created_ts=2000.0,
        )
        # Pre-condition : le parasite EST bien le dernier run (list_runs, sans filtre).
        self.assertEqual(self.store.run.list_runs(limit=1)[0]["run_id"], "run-parasite-1")
        # get_latest_run (filtre) doit renvoyer le run de SCAN.
        latest = self.store.run.get_latest_run()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["run_id"], "run-scan-1")

    def test_multiple_parasites_still_resolve_scan_run(self) -> None:
        self._insert_run("run-scan-1", config={"library_path": "D:/Films"}, created_ts=1000.0)
        for i in range(3):
            self._insert_run(
                f"run-parasite-{i}",
                config={"rescan_run_id": "run-scan-1", "rescan_row_ids": ["row-1"]},
                created_ts=2000.0 + i * 100,
            )
        self.assertEqual(self.store.run.get_latest_run()["run_id"], "run-scan-1")

    def test_normal_latest_run_unchanged(self) -> None:
        self._insert_run("run-scan-1", config={"library_path": "D:/Films"}, created_ts=1000.0)
        self._insert_run("run-scan-2", config={"library_path": "D:/Films"}, created_ts=2000.0)
        self.assertEqual(self.store.run.get_latest_run()["run_id"], "run-scan-2")


if __name__ == "__main__":
    unittest.main()
