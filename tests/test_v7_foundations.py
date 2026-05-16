from __future__ import annotations

from contextlib import closing
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from cinesort.infra.run_id import RUN_ID_PATTERN, normalize_or_generate_run_id


class V7FoundationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_v7_")
        self.addCleanup(self._tmp.cleanup)

        self.state_dir = Path(self._tmp.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = db_path_for_state_dir(self.state_dir)
        self.store = SQLiteStore(self.db_path, busy_timeout_ms=8000)

    def test_initialize_applies_migrations_and_sets_schema_version(self) -> None:
        version = self.store.initialize()
        # Audit perf 2026-05-01 : migration 020 ajoute idx_quality_reports_tier + score.
        # V1-02 (Polish v7.7.0) : migration 021 ajoute ON DELETE CASCADE/RESTRICT
        # sur les FK runs/errors/quality_reports/anomalies/apply_operations.
        # Migration 022 drop indexes redondants — tolere migrations futures.
        self.assertGreaterEqual(version, 21)
        self.assertTrue(self.db_path.exists())

        with closing(sqlite3.connect(str(self.db_path))) as conn:
            table_names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("runs", table_names)
            self.assertIn("errors", table_names)
            self.assertIn("probe_cache", table_names)
            self.assertIn("quality_profiles", table_names)
            self.assertIn("quality_reports", table_names)
            self.assertIn("anomalies", table_names)
            self.assertIn("apply_batches", table_names)
            self.assertIn("apply_operations", table_names)
            self.assertIn("incremental_file_hashes", table_names)
            self.assertIn("incremental_scan_cache", table_names)
            # DB3 audit : table historique des migrations (v12)
            self.assertIn("schema_migrations", table_names)

            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertGreaterEqual(user_version, 21)
            # P4.1 : migration 014 crée la table user_quality_feedback
            self.assertIn("user_quality_feedback", table_names)
            # CR-1 audit QA 20260429 : migration 019 crée apply_pending_moves
            self.assertIn("apply_pending_moves", table_names)

            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(str(journal_mode).lower(), "wal")

            # DB3 : la migration 012 elle-meme doit avoir ete enregistree dans schema_migrations
            migrations_row = conn.execute("SELECT version, name FROM schema_migrations WHERE version = 12").fetchone()
            self.assertIsNotNone(migrations_row, "La migration 012 doit s'auto-enregistrer")
            self.assertEqual(int(migrations_row[0]), 12)
            self.assertIn("schema_history", migrations_row[1])

            # P1.2 : migration 013 ajoute src_sha1 + src_size dans apply_operations
            cols = {row[1] for row in conn.execute("PRAGMA table_info(apply_operations)")}
            self.assertIn("src_sha1", cols)
            self.assertIn("src_size", cols)
            migration_013 = conn.execute("SELECT version, name FROM schema_migrations WHERE version = 13").fetchone()
            self.assertIsNotNone(migration_013, "La migration 013 doit s'auto-enregistrer")

    def test_bootstrap_schema_latest_reads_ordered_migrations_as_single_source_of_truth(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        partial_migrations = Path(self._tmp.name) / "partial_migrations"
        partial_migrations.mkdir(parents=True, exist_ok=True)
        source_dir = repo_root / "cinesort" / "infra" / "db" / "migrations"
        shutil.copy(source_dir / "001_init_runs_errors.sql", partial_migrations / "001_init_runs_errors.sql")
        shutil.copy(source_dir / "002_probe_cache.sql", partial_migrations / "002_probe_cache.sql")

        partial_db = Path(self._tmp.name) / "partial_bootstrap.sqlite"
        partial_store = SQLiteStore(partial_db, migrations_dir=partial_migrations, busy_timeout_ms=8000)
        version = partial_store._bootstrap_schema_latest()

        self.assertEqual(version, 2)
        with closing(sqlite3.connect(str(partial_db))) as conn:
            table_names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("runs", table_names)
            self.assertIn("errors", table_names)
            self.assertIn("probe_cache", table_names)
            self.assertNotIn("quality_profiles", table_names)
            self.assertEqual(int(conn.execute("PRAGMA user_version").fetchone()[0]), 2)

    def test_store_connection_uses_busy_timeout_and_wal(self) -> None:
        self.store.initialize()

        with closing(self.store._connect()) as conn:
            busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

        self.assertEqual(int(busy), 8000)
        self.assertEqual(str(mode).lower(), "wal")

    def test_initialize_uses_bootstrap_fallback_when_required_schema_is_incomplete(self) -> None:
        with (
            mock.patch.object(self.store, "_apply_schema_migrations", return_value=3) as mocked_apply,
            mock.patch.object(
                self.store,
                "_missing_required_tables",
                side_effect=[{"quality_profiles", "quality_reports"}, set()],
            ) as mocked_missing,
            mock.patch.object(self.store, "_bootstrap_schema_latest", return_value=9) as mocked_bootstrap,
        ):
            version = self.store.initialize()

        self.assertEqual(version, 9)
        mocked_apply.assert_called_once_with()
        self.assertEqual(mocked_missing.call_count, 2)
        mocked_bootstrap.assert_called_once_with()

    def test_initialize_raises_when_bootstrap_cannot_produce_required_schema(self) -> None:
        with (
            mock.patch.object(self.store, "_apply_schema_migrations", return_value=2),
            mock.patch.object(
                self.store,
                "_missing_required_tables",
                side_effect=[{"quality_profiles"}, {"quality_profiles"}],
            ),
            mock.patch.object(self.store, "_bootstrap_schema_latest", return_value=2),
        ):
            with self.assertRaisesRegex(RuntimeError, "tables manquantes: quality_profiles"):
                self.store.initialize()

    def test_insert_run_pending_retries_once_when_runs_table_is_missing(self) -> None:
        self.store.initialize()
        run_id = "20260218_120000_124"

        # Cf #85 phase B6 : code metier dans RunRepository, le wrapper SQLiteStore
        # delegue a self.run.insert_run_pending qui appelle self._insert_pending_run_row
        # sur le repo. On mock store.run._insert_pending_run_row (pas store.X).
        with (
            mock.patch.object(
                self.store.run,
                "_insert_pending_run_row",
                side_effect=[sqlite3.OperationalError("no such table: runs"), None],
            ) as mocked_insert,
            mock.patch.object(self.store, "initialize", wraps=self.store.initialize) as mocked_initialize,
        ):
            self.store.insert_run_pending(
                run_id=run_id,
                root=r"D:\Films",
                state_dir=str(self.state_dir),
                config={"tmdb_enabled": False},
            )

        self.assertEqual(mocked_initialize.call_count, 1)
        self.assertEqual(mocked_insert.call_count, 2)

    def test_run_lifecycle_pending_running_cancelled(self) -> None:
        self.store.initialize()
        run_id = "20260218_120000_123"

        self.store.insert_run_pending(
            run_id=run_id,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={"tmdb_enabled": False},
        )
        self.store.mark_run_running(run_id)
        self.store.update_run_progress(run_id, idx=13, total=99, current_folder="FolderA")
        self.store.mark_cancel_requested(run_id)
        self.store.mark_run_cancelled(run_id, stats={"planned_rows": 42})

        row = self.store.get_run(run_id)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], "CANCELLED")
        self.assertEqual(int(row["cancel_requested"]), 1)
        self.assertEqual(int(row["idx"]), 13)
        self.assertEqual(int(row["total"]), 99)
        self.assertEqual(row["current_folder"], "FolderA")
        self.assertIn("planned_rows", row["stats_json"] or "")

    def test_insert_and_list_errors(self) -> None:
        self.store.initialize()
        run_id = "20260218_130000_777"
        self.store.insert_run_pending(
            run_id=run_id,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={"tmdb_enabled": True},
        )

        self.store.insert_error(
            run_id=run_id,
            step="scan",
            code="E_ROOT",
            message="ROOT missing",
            context={"root": r"D:\missing"},
        )
        self.store.insert_error(
            run_id=run_id,
            step="tmdb",
            code="E_TIMEOUT",
            message="TMDb timeout",
            context={"timeout_s": 10},
        )

        errs = self.store.list_errors(run_id)
        self.assertEqual(len(errs), 2)
        self.assertEqual(errs[0]["code"], "E_ROOT")
        self.assertEqual(errs[1]["code"], "E_TIMEOUT")

    def test_threaded_writes_do_not_raise_sqlite_thread_affinity_errors(self) -> None:
        self.store.initialize()
        run_id = "20260218_140000_555"
        self.store.insert_run_pending(
            run_id=run_id,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={},
        )

        failures = []

        def worker(i: int) -> None:
            try:
                self.store.insert_error(
                    run_id=run_id,
                    step="thread",
                    code=f"E{i}",
                    message=f"msg-{i}",
                    context={"i": i},
                )
            except Exception as exc:  # pragma: no cover - should not happen
                failures.append(str(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(failures, [])
        errs = self.store.list_errors(run_id)
        self.assertEqual(len(errs), 12)

    def test_run_id_normalization_or_uuid_fallback(self) -> None:
        current = "20260218_150500_321"
        kept = normalize_or_generate_run_id(current)
        self.assertEqual(kept, current)

        fallback = normalize_or_generate_run_id("invalid")
        self.assertRegex(fallback, r"^[0-9a-f]{32}$")
        self.assertFalse(bool(RUN_ID_PATTERN.match(fallback)))

    def test_apply_journal_insert_append_close_and_query(self) -> None:
        self.store.initialize()
        run_id = "20260219_101010_101"
        self.store.insert_run_pending(
            run_id=run_id,
            root=r"D:\Films",
            state_dir=str(self.state_dir),
            config={},
        )
        batch_id = self.store.insert_apply_batch(
            run_id=run_id,
            dry_run=False,
            quarantine_unapproved=True,
            app_version="7.2.0-A",
        )
        self.store.append_apply_operation(
            batch_id=batch_id,
            op_index=1,
            op_type="MOVE_FILE",
            src_path=r"D:\Films\A.mkv",
            dst_path=r"D:\Films\B.mkv",
            reversible=True,
        )
        self.store.close_apply_batch(
            batch_id=batch_id,
            status="DONE",
            summary={"ops_count": 1},
        )

        last = self.store.get_last_reversible_apply_batch(run_id)
        self.assertIsNotNone(last)
        assert last is not None
        self.assertEqual(last["batch_id"], batch_id)
        self.assertEqual(last["status"], "DONE")

        ops = self.store.list_apply_operations(batch_id=batch_id)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["op_type"], "MOVE_FILE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
