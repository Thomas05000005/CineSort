"""Tests Phase 4 — Backend Historique (spec 09-historique.md §6, §7).

Couvre les 3 nouveaux endpoints + le cron retention :
- `run.get_history_stats(run_id)` : detail complet d'un run pour l'inspecteur
- `run.delete_run(run_id)` : suppression DB (sans toucher aux fichiers video)
- `run.cleanup_old_runs(retention_days)` : purge des runs > N jours
- `cinesort.app.retention_cleanup.start_retention_cron` : cron 24h
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from cinesort.app.retention_cleanup import start_retention_cron, trigger_now
from cinesort.infra.db.migration_manager import MigrationManager
from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api.cinesort_api import CineSortApi

_ROOT = Path(__file__).resolve().parents[1]
_MIGRATIONS_DIR = _ROOT / "cinesort" / "infra" / "db" / "migrations"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api_with_store(tmp_dir: Path) -> tuple[CineSortApi, SQLiteStore, Path]:
    """Cree une CineSortApi configuree sur tmp_dir + le store initialise.

    Retourne (api, store, state_dir).
    """
    state_dir = tmp_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    api = CineSortApi()
    saved = api.settings.save_settings(
        {
            "root": str(tmp_dir / "root"),
            "state_dir": str(state_dir),
            "tmdb_enabled": False,
        }
    )
    assert saved.get("ok"), saved
    # Recupere le store du state_dir via _get_or_create_infra (memes paths)
    store, _runner = api._get_or_create_infra(api._state_dir)
    return api, store, state_dir


def _insert_run(
    store: SQLiteStore,
    run_id: str,
    *,
    started_ts: float,
    ended_ts: float | None = None,
    status: str = "DONE",
    total: int = 10,
    applied: int = 0,
) -> None:
    """Insere un run complet dans la DB pour les tests."""
    store.run.insert_run_pending(
        run_id=run_id,
        root="X:/movies",
        state_dir="C:/state",
        config={"dry_run": True},
        created_ts=started_ts,
    )
    store.run.mark_run_running(run_id, started_ts=started_ts)
    store.run.update_run_progress(run_id, idx=total, total=total, current_folder="done")
    if status == "DONE":
        store.run.mark_run_done(
            run_id,
            stats={"planned_rows": total, "applied_count": applied},
            ended_ts=ended_ts or started_ts + 60,
        )
    elif status == "CANCELLED":
        store.run.mark_run_cancelled(
            run_id,
            stats={"planned_rows": total},
            ended_ts=ended_ts or started_ts + 30,
        )
    elif status == "FAILED":
        store.run.mark_run_failed(run_id, error_message="boom", ended_ts=ended_ts or started_ts + 10)


# ---------------------------------------------------------------------------
# get_history_stats
# ---------------------------------------------------------------------------


class GetHistoryStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_hist_stats_"))
        self.api, self.store, self.state_dir = _make_api_with_store(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_returns_full_payload_for_existing_run(self) -> None:
        now = time.time()
        _insert_run(self.store, "20260517_151001", started_ts=now - 600, ended_ts=now - 540, total=40, applied=40)

        # Ajout de quality reports (2 platinum, 1 gold, 1 reject)
        for rid, tier, score in [
            ("r1", "platinum", 92),
            ("r2", "platinum", 95),
            ("r3", "gold", 80),
            ("r4", "reject", 30),
        ]:
            self.store.quality.upsert_quality_report(
                run_id="20260517_151001",
                row_id=rid,
                score=score,
                tier=tier,
                reasons=[],
                metrics={},
                profile_id="default",
                profile_version=1,
                ts=now,
            )

        resp = self.api.run.get_history_stats("20260517_151001")
        self.assertTrue(resp.get("ok"), resp)
        run = resp["run"]
        self.assertEqual(run["run_id"], "20260517_151001")
        self.assertEqual(run["status"], "DONE")
        self.assertEqual(run["total_rows"], 40)
        self.assertEqual(run["applied_rows"], 40)
        self.assertEqual(run["validated_count"], 3)  # platinum x2 + gold
        self.assertEqual(run["rejected_count"], 1)
        self.assertEqual(run["films_by_tier"].get("platinum"), 2)
        self.assertEqual(run["films_by_tier"].get("gold"), 1)
        self.assertEqual(run["films_by_tier"].get("reject"), 1)
        # (92 + 95 + 80 + 30) / 4 = 74.25
        self.assertAlmostEqual(run["score_avg"], 74.25, places=1)
        self.assertGreaterEqual(run["duration_s"], 50.0)
        self.assertIsInstance(run["apply_operations"], list)

    def test_returns_error_for_unknown_run(self) -> None:
        resp = self.api.run.get_history_stats("UNKNOWN_RUN_ID")
        self.assertFalse(resp.get("ok"))
        self.assertIn("introuvable", resp.get("message", "").lower())

    def test_returns_error_for_invalid_run_id(self) -> None:
        resp = self.api.run.get_history_stats("")
        self.assertFalse(resp.get("ok"))

    def test_fallback_when_no_quality_reports(self) -> None:
        """Pas de quality reports : les champs valent 0/{} mais ok=True."""
        now = time.time()
        _insert_run(self.store, "20260517_152002", started_ts=now - 300, ended_ts=now - 240, total=5, applied=0)

        resp = self.api.run.get_history_stats("20260517_152002")
        self.assertTrue(resp.get("ok"), resp)
        run = resp["run"]
        self.assertEqual(run["validated_count"], 0)
        self.assertEqual(run["rejected_count"], 0)
        self.assertEqual(run["films_by_tier"], {})
        self.assertIsNone(run["score_avg"])


# ---------------------------------------------------------------------------
# delete_run
# ---------------------------------------------------------------------------


class DeleteRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_hist_delete_"))
        self.api, self.store, self.state_dir = _make_api_with_store(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_delete_existing_run_returns_count(self) -> None:
        now = time.time()
        _insert_run(self.store, "20260517_153003", started_ts=now - 600, ended_ts=now - 540)
        # 2 quality reports + 1 perceptual report + 1 error pour avoir un compteur > 1.
        for rid, tier, score in [("a", "platinum", 90), ("b", "gold", 80)]:
            self.store.quality.upsert_quality_report(
                run_id="20260517_153003",
                row_id=rid,
                score=score,
                tier=tier,
                reasons=[],
                metrics={},
                profile_id="default",
                profile_version=1,
                ts=now,
            )
        self.store.perceptual.upsert_perceptual_report(
            run_id="20260517_153003",
            row_id="a",
            visual_score=50,
            audio_score=50,
            global_score=50,
            global_tier="bon",
            metrics={},
            settings_used={},
        )
        self.store.run.insert_error(
            run_id="20260517_153003",
            step="scan",
            code="WARN",
            message="warn",
        )

        resp = self.api.run.delete_run("20260517_153003")
        self.assertTrue(resp.get("ok"), resp)
        # 1 run + 2 quality + 1 perceptual + 1 error = 5
        self.assertGreaterEqual(resp["deleted_records"], 5)
        # Verifie que les enregistrements sont bien partis de la DB.
        self.assertIsNone(self.store.run.get_run("20260517_153003"))
        self.assertEqual(self.store.quality.list_quality_reports(run_id="20260517_153003"), [])
        self.assertEqual(self.store.perceptual.list_perceptual_reports(run_id="20260517_153003"), [])
        self.assertEqual(self.store.run.list_errors("20260517_153003"), [])

    def test_delete_unknown_run_returns_error(self) -> None:
        resp = self.api.run.delete_run("UNKNOWN_RID_999")
        self.assertFalse(resp.get("ok"))
        self.assertIn("introuvable", resp.get("message", "").lower())

    def test_delete_cascades_apply_batches_and_operations(self) -> None:
        now = time.time()
        _insert_run(self.store, "20260517_154004", started_ts=now - 600, ended_ts=now - 540)
        batch_id = self.store.apply.insert_apply_batch(
            run_id="20260517_154004",
            dry_run=False,
            quarantine_unapproved=False,
            status="DONE",
        )
        self.store.apply.append_apply_operation(
            batch_id=batch_id,
            op_index=0,
            op_type="MOVE_FILE",
            src_path="/src/a.mkv",
            dst_path="/dst/a.mkv",
            reversible=True,
        )

        resp = self.api.run.delete_run("20260517_154004")
        self.assertTrue(resp.get("ok"), resp)
        # Verifie que apply_batches et apply_operations sont bien purges.
        self.assertEqual(self.store.apply.list_apply_batches_for_run(run_id="20260517_154004"), [])
        self.assertEqual(self.store.apply.list_apply_operations(batch_id=batch_id), [])

    def test_delete_does_not_touch_video_files(self) -> None:
        """Les fichiers du root ne doivent JAMAIS etre supprimes."""
        now = time.time()
        _insert_run(self.store, "20260517_155005", started_ts=now - 600, ended_ts=now - 540)
        # Cree un fichier video factice sous le root, pour verifier qu'il survit.
        video_root = self._tmp / "root"
        video_root.mkdir(parents=True, exist_ok=True)
        video = video_root / "movie.mkv"
        video.write_bytes(b"x" * 2048)
        self.assertTrue(video.is_file())

        resp = self.api.run.delete_run("20260517_155005")
        self.assertTrue(resp.get("ok"), resp)
        self.assertTrue(video.is_file(), "Le fichier video ne doit PAS etre supprime")


# ---------------------------------------------------------------------------
# cleanup_old_runs
# ---------------------------------------------------------------------------


class CleanupOldRunsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_hist_cleanup_"))
        self.api, self.store, self.state_dir = _make_api_with_store(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_cleanup_respects_threshold(self) -> None:
        """Runs > 90j sont supprimes, runs <= 90j sont conserves."""
        now = time.time()
        # 2 runs anciens (120j et 100j)
        _insert_run(self.store, "old_run_120", started_ts=now - 120 * 86400, ended_ts=now - 120 * 86400 + 60)
        _insert_run(self.store, "old_run_100", started_ts=now - 100 * 86400, ended_ts=now - 100 * 86400 + 60)
        # 2 runs recents (30j et 5j)
        _insert_run(self.store, "recent_30", started_ts=now - 30 * 86400, ended_ts=now - 30 * 86400 + 60)
        _insert_run(self.store, "recent_5", started_ts=now - 5 * 86400, ended_ts=now - 5 * 86400 + 60)

        # `dry_run=False` EXPLICITE : ce test asserte plus bas que les runs ont
        # DISPARU de la base. Depuis #1022, la route est en apercu par defaut
        # comme ses jumelles destructives — un appel nu ne supprime plus rien.
        resp = self.api.run.cleanup_old_runs(retention_days=90, dry_run=False)
        self.assertTrue(resp.get("ok"), resp)
        self.assertEqual(resp["deleted_count"], 2)
        self.assertIn("old_run_120", resp["deleted_run_ids"])
        self.assertIn("old_run_100", resp["deleted_run_ids"])
        # Les recents doivent etre conserves
        self.assertIsNotNone(self.store.run.get_run("recent_30"))
        self.assertIsNotNone(self.store.run.get_run("recent_5"))
        self.assertIsNone(self.store.run.get_run("old_run_120"))
        self.assertIsNone(self.store.run.get_run("old_run_100"))

    def test_cleanup_empty_when_no_old_runs(self) -> None:
        now = time.time()
        _insert_run(self.store, "fresh_run", started_ts=now - 86400, ended_ts=now - 86000)

        resp = self.api.run.cleanup_old_runs(retention_days=90)
        self.assertTrue(resp.get("ok"), resp)
        self.assertEqual(resp["deleted_count"], 0)
        self.assertEqual(resp["deleted_run_ids"], [])

    def test_cleanup_custom_threshold(self) -> None:
        """Un threshold custom (7j) permet de purger plus aggressivement."""
        now = time.time()
        _insert_run(self.store, "ten_days_old", started_ts=now - 10 * 86400, ended_ts=now - 10 * 86400 + 60)
        _insert_run(self.store, "two_days_old", started_ts=now - 2 * 86400, ended_ts=now - 2 * 86400 + 60)

        resp = self.api.run.cleanup_old_runs(retention_days=7)
        self.assertTrue(resp.get("ok"), resp)
        self.assertEqual(resp["deleted_count"], 1)
        self.assertIn("ten_days_old", resp["deleted_run_ids"])

    def test_cleanup_invalid_retention_falls_back_to_default(self) -> None:
        """retention_days invalide tombe sur 90 jours par defaut."""
        resp = self.api.run.cleanup_old_runs(retention_days=0)  # type: ignore[arg-type]
        self.assertTrue(resp.get("ok"), resp)
        # 0 -> clamp a 1 (au moins 1 jour)
        self.assertGreaterEqual(int(resp.get("retention_days") or 0), 1)


# ---------------------------------------------------------------------------
# retention_cleanup cron
# ---------------------------------------------------------------------------


class RetentionCronTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_hist_cron_"))
        self.api, self.store, self.state_dir = _make_api_with_store(self._tmp)

    def tearDown(self) -> None:
        # Stopper le cron eventuel
        stop = getattr(self.api, "_retention_stop", None)
        if stop:
            stop.set()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_trigger_now_runs_cleanup(self) -> None:
        """trigger_now appelle bien cleanup_old_runs et purge les vieux runs."""
        now = time.time()
        _insert_run(self.store, "ancient_run", started_ts=now - 200 * 86400, ended_ts=now - 200 * 86400 + 60)

        trigger_now(self.api, retention_days=90)
        self.assertIsNone(self.store.run.get_run("ancient_run"))

    def test_start_retention_cron_disabled_when_days_zero(self) -> None:
        """retention_days <= 0 retourne None (cron desactive)."""
        thread = start_retention_cron(self.api, retention_days=0)
        self.assertIsNone(thread)

    def test_start_retention_cron_returns_daemon_thread(self) -> None:
        """retention_days > 0 retourne un thread daemon demarre."""
        thread = start_retention_cron(
            self.api,
            retention_days=90,
            initial_delay_s=0.01,
            interval_s=3600,
        )
        self.assertIsNotNone(thread)
        self.assertTrue(thread.daemon)
        # Laisser le worker faire son premier cycle, puis le stopper.
        time.sleep(0.3)
        stop = getattr(self.api, "_retention_stop", None)
        self.assertIsNotNone(stop)
        stop.set()
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())


# ---------------------------------------------------------------------------
# RunRepository.delete_run / list_runs_older_than (unit tests directs)
# ---------------------------------------------------------------------------


class RunRepoUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_repo_unit_"))
        db = self._tmp / "test.db"
        MigrationManager(db, _MIGRATIONS_DIR).apply()
        self.store = SQLiteStore(db)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_delete_run_on_missing_returns_zero(self) -> None:
        self.assertEqual(self.store.run.delete_run("does_not_exist"), 0)

    def test_list_runs_older_than_orders_by_oldest_first(self) -> None:
        now = time.time()
        _insert_run(self.store, "r_old", started_ts=now - 200 * 86400, ended_ts=now - 200 * 86400 + 60)
        _insert_run(self.store, "r_mid", started_ts=now - 150 * 86400, ended_ts=now - 150 * 86400 + 60)
        _insert_run(self.store, "r_recent", started_ts=now - 5 * 86400, ended_ts=now - 5 * 86400 + 60)

        cutoff = now - 90 * 86400
        olds = self.store.run.list_runs_older_than(cutoff_ts=cutoff)
        self.assertEqual(olds, ["r_old", "r_mid"])

    def test_delete_run_cascade_via_fk(self) -> None:
        """errors/quality_reports/anomalies sont CASCADE via FK (migration 021)."""
        now = time.time()
        _insert_run(self.store, "cascade_test", started_ts=now, ended_ts=now + 10)
        self.store.run.insert_error(
            run_id="cascade_test",
            step="scan",
            code="X",
            message="y",
        )
        self.store.quality.upsert_quality_report(
            run_id="cascade_test",
            row_id="r1",
            score=80,
            tier="gold",
            reasons=[],
            metrics={},
            profile_id="default",
            profile_version=1,
            ts=now,
        )

        n = self.store.run.delete_run("cascade_test")
        self.assertGreaterEqual(n, 3)  # 1 run + 1 error + 1 quality_report
        self.assertEqual(self.store.run.list_errors("cascade_test"), [])
        self.assertEqual(self.store.quality.list_quality_reports(run_id="cascade_test"), [])


if __name__ == "__main__":
    unittest.main()
