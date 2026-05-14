"""Tests pour le rollback DB apres migration ratee (issue #80).

Verifie que si une migration leve pendant SQLiteStore.initialize(), la DB est
restauree automatiquement depuis le backup pre_migration cree juste avant.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from cinesort.infra.db.sqlite_store import SQLiteStore


class MigrationRollbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_rollback_"))
        self.db_path = self._tmp / "cinesort.sqlite"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _seed_db(self) -> None:
        """Cree une DB initiale avec quelques migrations appliquees."""
        store = SQLiteStore(self.db_path, busy_timeout_ms=2000)
        store.initialize()
        # Ecrit une row sentinelle pour pouvoir verifier le rollback
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('sentinel', 'DONE', 0, '', '', '{}')"
            )
            conn.commit()

    def test_no_pre_migration_backup_on_fresh_install(self) -> None:
        """Fresh install : pas de backup pre_migration cree (rien a sauver)."""
        store = SQLiteStore(self.db_path, busy_timeout_ms=2000)
        store.initialize()
        backups = store.list_db_backups()
        pre_migration = [p for p in backups if ".pre_migration." in p.name]
        self.assertEqual(len(pre_migration), 0)

    def test_pre_migration_backup_created_on_subsequent_init(self) -> None:
        """Sur DB existante, _backup_before_migrations cree un backup pre_migration."""
        self._seed_db()
        # 2eme initialize() → backup pre_migration cree
        store = SQLiteStore(self.db_path, busy_timeout_ms=2000)
        store.initialize()
        backups = store.list_db_backups()
        pre_migration = [p for p in backups if ".pre_migration." in p.name]
        self.assertGreaterEqual(len(pre_migration), 1)

    def test_failed_migration_triggers_restore(self) -> None:
        """Si _apply_schema_migrations leve, la DB doit etre restauree depuis le backup."""
        self._seed_db()

        # Capture le contenu de la DB avant la tentative de migration ratee
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            sentinel_before = conn.execute("SELECT run_id FROM runs WHERE run_id='sentinel'").fetchone()
        self.assertEqual(sentinel_before[0], "sentinel")

        store = SQLiteStore(self.db_path, busy_timeout_ms=2000)

        # Mock pour simuler une migration ratee + corruption pre-restore
        # On corrompt la DB juste apres backup_before_migrations puis on leve
        def _broken_apply(self_store) -> int:
            # Simule une corruption partielle de la DB (ALTER TABLE applique
            # mais CREATE INDEX qui crashe au milieu)
            with closing(sqlite3.connect(str(self_store.db_path))) as c:
                c.execute("DROP TABLE IF EXISTS runs")
                c.commit()
            raise sqlite3.DatabaseError("Migration boom (test)")

        with patch.object(SQLiteStore, "_apply_schema_migrations", _broken_apply):
            with self.assertRaises(RuntimeError) as ctx:
                store.initialize()

        # Verifier que l'erreur mentionne le rollback
        self.assertIn("restauree", str(ctx.exception).lower())

        # La DB doit etre restauree : la table runs doit exister + sentinel present
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            sentinel_after = conn.execute("SELECT run_id FROM runs WHERE run_id='sentinel'").fetchone()
        self.assertIsNotNone(sentinel_after, "DB pas restauree — sentinel disparue")
        self.assertEqual(sentinel_after[0], "sentinel")

        # L'integrity_event doit refleter le rollback
        self.assertEqual(store.integrity_event["status"], "migration_rolled_back")
        self.assertIn("pre_migration", store.integrity_event["backup_used"])

    def test_failed_migration_without_backup_raises_raw(self) -> None:
        """Si pas de backup pre_migration (fresh install), la migration ratee remonte tel quel."""
        # Fresh install + migration mockee qui rate
        store = SQLiteStore(self.db_path, busy_timeout_ms=2000)

        def _broken_apply(self_store) -> int:
            raise sqlite3.DatabaseError("Boom (no backup case)")

        with patch.object(SQLiteStore, "_apply_schema_migrations", _broken_apply):
            with self.assertRaises(sqlite3.DatabaseError) as ctx:
                store.initialize()
        self.assertIn("Boom", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
