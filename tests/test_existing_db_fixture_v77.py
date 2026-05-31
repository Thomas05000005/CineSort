"""Tests pour la fixture mutualisee `existing_db_fixture` (item M-00 Vague M).

Memoire `feedback_sqlite_migration_test_existing_db` : valider qu'on peut
arreter le schema a une version donnee, puis enchainer une migration
suivante sans casser l'ordre CREATE TABLE -> ALTER TABLE -> CREATE INDEX
ni l'idempotence.
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from tests._helpers import existing_db_fixture


class ExistingDbFixtureTests(unittest.TestCase):
    def test_target_version_5_apply_undo_journal_present(self):
        """A v5, les tables `apply_batches` + `apply_operations` doivent exister."""
        db_path, conn = existing_db_fixture(5)
        try:
            self.assertTrue(db_path.exists(), "DB sqlite doit etre cree sur disque")
            cur = conn.execute("PRAGMA user_version")
            user_version = int(cur.fetchone()[0])
            self.assertEqual(user_version, 5, "user_version doit valoir 5 apres apply")

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            # Migration 005 cree apply_batches + apply_operations
            self.assertIn("apply_batches", tables)
            self.assertIn("apply_operations", tables)
        finally:
            conn.close()

    def test_target_version_0_returns_empty_db(self):
        """target=0 : DB vierge, aucune table applicative."""
        db_path, conn = existing_db_fixture(0)
        try:
            self.assertTrue(db_path.exists())
            cur = conn.execute("PRAGMA user_version")
            self.assertEqual(int(cur.fetchone()[0]), 0)
            user_tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            self.assertEqual(user_tables, [], "DB v0 ne doit avoir aucune user-table")
        finally:
            conn.close()

    def test_target_version_latest_applies_all_migrations(self):
        """target=27 (latest reel post-v166) : toutes les migrations appliquees."""
        db_path, conn = existing_db_fixture(27)
        try:
            cur = conn.execute("PRAGMA user_version")
            user_version = int(cur.fetchone()[0])
            self.assertEqual(user_version, 27)

            # Migration 012 cree schema_migrations -> 12..27 enregistrees
            rows = conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
            versions = [int(r[0]) for r in rows]
            # Au moins 12..27 doivent y etre (les < 12 sont retroactives, INSERT OR IGNORE)
            self.assertIn(27, versions)
            self.assertIn(12, versions)
        finally:
            conn.close()

    def test_apply_next_migration_on_existing_db(self):
        """Cas d'usage cible : appliquer migration N+1 sur DB pre-existante.

        On simule en applliquant manuellement une migration custom apres
        avoir arrete a v5. C'est l'ordre que P-04/P-05/O-06/R-04 vont suivre.
        """
        db_path, conn = existing_db_fixture(5)
        try:
            # ALTER TABLE EXTEND (ce que fera la migration 029 P-04 sur apply_operations)
            # Pour ce test on simule une simple colonne ajoutee.
            conn.execute(
                "ALTER TABLE apply_operations ADD COLUMN committed_at TIMESTAMP"
            )
            conn.execute("PRAGMA user_version = 29")
            conn.commit()

            cur = conn.execute("PRAGMA table_info(apply_operations)")
            cols = {row[1] for row in cur.fetchall()}
            self.assertIn("committed_at", cols)

            cur = conn.execute("PRAGMA user_version")
            self.assertEqual(int(cur.fetchone()[0]), 29)
        finally:
            conn.close()

    def test_migrations_dir_override(self):
        """On peut passer un dossier de migrations custom (tests isoles)."""
        from cinesort.infra.db.migration_manager import MigrationManager

        # Dossier de migrations standard valide via repo
        from tests._helpers import _project_migrations_dir

        src = _project_migrations_dir()
        self.assertTrue(src.is_dir(), "Repo doit contenir cinesort/infra/db/migrations/")

        # Verifier nb de fichiers SQL (sanity check)
        sql_files = list(src.glob("*.sql"))
        self.assertGreaterEqual(len(sql_files), 27, "Au moins 27 migrations attendues post-v166")

        db_path, conn = existing_db_fixture(3, migrations_dir=src)
        try:
            cur = conn.execute("PRAGMA user_version")
            self.assertEqual(int(cur.fetchone()[0]), 3)
        finally:
            conn.close()

    def test_invalid_migrations_dir_raises(self):
        """migrations_dir inexistant -> FileNotFoundError clair."""
        with self.assertRaises(FileNotFoundError):
            existing_db_fixture(5, migrations_dir=Path("/no/such/dir/cinesort_xxx"))


if __name__ == "__main__":
    unittest.main()
