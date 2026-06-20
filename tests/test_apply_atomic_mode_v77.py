"""VP-A migration 029 + apply atomic mode tests.

Couvre (memoire `feedback_sqlite_migration_test_existing_db`) :
  * Fresh DB : applique 001..029 -> table apply_batch_modes existe + 2 index.
  * DB pre-existante v28 (existing_db_fixture) : applique 029 sans erreur.
  * Idempotence : rejouer 029 deux fois ne casse rien.
  * Ordre strict respecte : CREATE TABLE avant CREATE INDEX (PAS d'ALTER).
  * Repository methods : upsert_atomic_mode, mark_rollback_status,
    get_atomic_mode, list_atomic_modes_for_run.

Backward compat AC-1 : la signature `apply_changes` retourne TOUJOURS
`{ok: bool}` meme avec apply_atomic=False/True (verifie indirectement par
test_apply_atomic_rollback_integration_v77).

Pas de modification tier_colors / dangerConfirmModal verifiee : cette
migration touche uniquement l'audit infra DB.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.infra.db.migration_manager import MigrationManager
from tests._helpers import _project_migrations_dir, existing_db_fixture

MIGRATION_FILENAME = "029_apply_atomic_mode.sql"
TARGET_VERSION = 29


def _read_migration_029() -> str:
    """Lit le contenu brut de la migration 029 depuis le repo."""
    path = _project_migrations_dir() / MIGRATION_FILENAME
    return path.read_text(encoding="utf-8")


def _exec_migration_029(conn: sqlite3.Connection) -> None:
    """Applique la migration 029 sur une connexion existante."""
    from cinesort.infra.db.migration_manager import _split_sql_statements

    sql = _read_migration_029()
    for stmt in _split_sql_statements(sql):
        conn.execute(stmt)
    conn.execute(f"PRAGMA user_version = {TARGET_VERSION}")
    conn.commit()


class Migration029SqlOrderTests(unittest.TestCase):
    """Memoire `feedback_sqlite_migration_test_existing_db` : ordre strict."""

    def test_migration_file_exists(self):
        path = _project_migrations_dir() / MIGRATION_FILENAME
        self.assertTrue(path.is_file(), f"Migration manquante : {path}")

    def test_no_alter_table_statements(self):
        """Regle dure : pas d'ALTER TABLE dans 029 (uniquement CREATE)."""
        sql = _read_migration_029().upper()
        self.assertNotIn("ALTER TABLE", sql, "Migration 029 ne doit PAS contenir ALTER TABLE")

    def test_create_table_before_create_index(self):
        """Ordre strict CREATE TABLE -> CREATE INDEX."""
        sql = _read_migration_029().upper()
        idx_table = sql.find("CREATE TABLE")
        idx_index = sql.find("CREATE INDEX")
        self.assertGreaterEqual(idx_table, 0, "Doit contenir CREATE TABLE")
        self.assertGreaterEqual(idx_index, 0, "Doit contenir CREATE INDEX")
        self.assertLess(idx_table, idx_index, "CREATE TABLE doit preceder CREATE INDEX")

    def test_if_not_exists_everywhere(self):
        """Idempotence : tout CREATE en IF NOT EXISTS."""
        sql = _read_migration_029()
        cleaned_lines = []
        for line in sql.splitlines():
            idx = line.find("--")
            if idx >= 0:
                line = line[:idx]
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines).upper()

        create_table_count = cleaned.count("CREATE TABLE")
        create_index_count = cleaned.count("CREATE INDEX")
        if_not_exists_count = cleaned.count("IF NOT EXISTS")
        expected = create_table_count + create_index_count
        self.assertGreaterEqual(
            if_not_exists_count,
            expected,
            f"Tous les CREATE doivent etre IF NOT EXISTS ({if_not_exists_count} vs {expected})",
        )


class Migration029FreshDbTests(unittest.TestCase):
    """Fresh DB : applique 001..029 d'un coup -> verifie la table + index."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="cinesort_mig029_fresh_"))
        self.db_path = self.tmpdir / "store.sqlite3"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fresh_db_applies_029(self):
        manager = MigrationManager(
            db_path=self.db_path,
            migrations_dir=_project_migrations_dir(),
        )
        final_version = manager.apply()
        self.assertGreaterEqual(final_version, TARGET_VERSION)

        conn = sqlite3.connect(str(self.db_path))
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("apply_batch_modes", tables)

            cur = conn.execute("PRAGMA table_info(apply_batch_modes)")
            cols = {row[1] for row in cur.fetchall()}
            expected_cols = {
                "batch_id",
                "atomic_enabled",
                "rollback_status",
                "rolled_back_at",
            }
            self.assertEqual(cols, expected_cols)

            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='apply_batch_modes'"
                )
            }
            self.assertIn("idx_apply_batch_modes_status", indexes)
            self.assertIn("idx_apply_batch_modes_atomic", indexes)
        finally:
            conn.close()


class Migration029ExistingDbV28Tests(unittest.TestCase):
    """AC-2 : DB pre-existante v28 : applique uniquement 029 par dessus."""

    def test_existing_v28_then_apply_029(self):
        db_path, conn = existing_db_fixture(28)
        try:
            cur = conn.execute("PRAGMA user_version")
            self.assertEqual(int(cur.fetchone()[0]), 28, "Pre-cond : DB doit etre v28")

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertNotIn(
                "apply_batch_modes",
                tables,
                "Pre-cond : table absente avant 029",
            )

            _exec_migration_029(conn)

            tables_after = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("apply_batch_modes", tables_after)

            cur = conn.execute("PRAGMA user_version")
            self.assertEqual(int(cur.fetchone()[0]), TARGET_VERSION)
        finally:
            conn.close()

    def test_idempotence_double_apply_029(self):
        """AC-2 : rejouer 029 deux fois ne doit JAMAIS lever."""
        db_path, conn = existing_db_fixture(28)
        try:
            _exec_migration_029(conn)
            count_first = conn.execute(
                "SELECT COUNT(*) FROM apply_batch_modes"
            ).fetchone()[0]
            self.assertEqual(count_first, 0)

            # Re-apply : ne doit pas lever, ne doit pas reinitialiser
            _exec_migration_029(conn)
            count_second = conn.execute(
                "SELECT COUNT(*) FROM apply_batch_modes"
            ).fetchone()[0]
            self.assertEqual(count_second, 0)
        finally:
            conn.close()


class ApplyRepositoryAtomicModeTests(unittest.TestCase):
    """Tests des methodes ApplyRepository pour le mode atomique."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="cinesort_repo_atomic_"))
        self.db_path = self.tmpdir / "store.sqlite3"
        # Migrations completes (001..029) pour avoir tout le contexte apply_batches.
        manager = MigrationManager(
            db_path=self.db_path,
            migrations_dir=_project_migrations_dir(),
        )
        manager.apply()

        from cinesort.infra.db.sqlite_store import SQLiteStore

        self.store = SQLiteStore(db_path=self.db_path)
        self.store.initialize()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_upsert_atomic_mode_default_disabled(self):
        self.store.apply.upsert_atomic_mode("batch-A", False)
        mode = self.store.apply.get_atomic_mode("batch-A")
        self.assertIsNotNone(mode)
        self.assertEqual(mode["atomic_enabled"], 0)
        self.assertEqual(mode["rollback_status"], "NONE")
        self.assertIsNone(mode["rolled_back_at"])

    def test_upsert_atomic_mode_enabled(self):
        self.store.apply.upsert_atomic_mode("batch-B", True)
        mode = self.store.apply.get_atomic_mode("batch-B")
        self.assertEqual(mode["atomic_enabled"], 1)
        self.assertEqual(mode["rollback_status"], "NONE")

    def test_upsert_atomic_mode_idempotent(self):
        """Un re-appel met juste a jour atomic_enabled sans toucher rollback_status."""
        self.store.apply.upsert_atomic_mode("batch-C", True)
        self.store.apply.mark_rollback_status("batch-C", "ROLLED_BACK_BY_ATOMIC")

        # Re-upsert : ne doit PAS reset le rollback_status
        self.store.apply.upsert_atomic_mode("batch-C", True)
        mode = self.store.apply.get_atomic_mode("batch-C")
        self.assertEqual(mode["rollback_status"], "ROLLED_BACK_BY_ATOMIC")

    def test_mark_rollback_status_creates_row_if_missing(self):
        """Si le batch n'existe pas en `apply_batch_modes`, on cree quand meme la ligne (audit)."""
        self.store.apply.mark_rollback_status("batch-orphan", "ROLLBACK_FAILED")
        mode = self.store.apply.get_atomic_mode("batch-orphan")
        self.assertIsNotNone(mode)
        self.assertEqual(mode["atomic_enabled"], 0)  # par defaut sans upsert prealable
        self.assertEqual(mode["rollback_status"], "ROLLBACK_FAILED")
        self.assertIsNotNone(mode["rolled_back_at"])  # auto-fill ts

    def test_mark_rollback_status_preserves_atomic_enabled(self):
        """Marker rollback ne doit PAS toggler atomic_enabled = 0."""
        self.store.apply.upsert_atomic_mode("batch-D", True)
        self.store.apply.mark_rollback_status("batch-D", "ROLLED_BACK_BY_ATOMIC")
        mode = self.store.apply.get_atomic_mode("batch-D")
        self.assertEqual(mode["atomic_enabled"], 1, "atomic_enabled doit etre preserve")
        self.assertEqual(mode["rollback_status"], "ROLLED_BACK_BY_ATOMIC")

    def test_get_atomic_mode_missing(self):
        mode = self.store.apply.get_atomic_mode("batch-inexistant")
        self.assertIsNone(mode)

    def test_list_atomic_modes_for_run(self):
        """Annoter les batches d'un run avec leur mode atomique."""
        # On insere d'abord des batches pour ce run
        bid_a = self.store.apply.insert_apply_batch(
            run_id="run-1", dry_run=False, quarantine_unapproved=False,
        )
        bid_b = self.store.apply.insert_apply_batch(
            run_id="run-1", dry_run=False, quarantine_unapproved=False,
        )
        bid_c = self.store.apply.insert_apply_batch(
            run_id="run-2", dry_run=False, quarantine_unapproved=False,
        )
        self.store.apply.upsert_atomic_mode(bid_a, True)
        self.store.apply.upsert_atomic_mode(bid_b, False)
        self.store.apply.upsert_atomic_mode(bid_c, True)

        modes_run1 = self.store.apply.list_atomic_modes_for_run(run_id="run-1")
        self.assertEqual(len(modes_run1), 2)
        self.assertIn(bid_a, modes_run1)
        self.assertIn(bid_b, modes_run1)
        self.assertNotIn(bid_c, modes_run1)  # run-2 exclu
        self.assertEqual(modes_run1[bid_a]["atomic_enabled"], 1)
        self.assertEqual(modes_run1[bid_b]["atomic_enabled"], 0)


if __name__ == "__main__":
    unittest.main()
