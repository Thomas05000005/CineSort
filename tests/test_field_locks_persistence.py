"""Vague P / VP-C : persistance des field_locks via close/reopen.

Lecon bug Jellyfin #15549 : un lock pose en memoire (RAM cache) ne
survit pas a un restart. La migration 030 + le FieldLocksRepository
doivent garantir la persistance disque.

Ce test ferme et reouvre la connexion SQLite entre set_lock et
get_lock pour valider que le lock survit a close/reopen.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.infra.db.migration_manager import _split_sql_statements
from cinesort.infra.db.repositories.field_locks import FieldLocksRepository
from tests._helpers import _project_migrations_dir, existing_db_fixture


def _apply_migration_030(conn: sqlite3.Connection) -> None:
    sql = (_project_migrations_dir() / "030_field_locks.sql").read_text(encoding="utf-8")
    for stmt in _split_sql_statements(sql):
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 30")
    conn.commit()


class _FakeStore:
    """Stub SQLiteStore minimal pour FieldLocksRepository.

    Implementations requises : _managed_conn (contextmanager) +
    _ensure_schema_group (no-op si table deja la).
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._tables_ensured = False

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _managed_conn(self):
        from contextlib import closing, contextmanager

        @contextmanager
        def _ctx():
            with closing(self._connect()) as conn, conn:
                yield conn

        return _ctx()

    def _ensure_schema_group(self, group_name, *, min_user_version=None):
        # No-op : migration 030 a deja cree la table avant le test.
        return None


class FieldLocksPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = Path(tempfile.mkdtemp(prefix="cinesort_locks_persist_"))
        self.db_path = self.tmp_root / "store.sqlite3"
        # Fresh DB : on cree juste la table 030.
        conn = sqlite3.connect(str(self.db_path))
        _apply_migration_030(conn)
        conn.close()

    def _build_repo(self) -> FieldLocksRepository:
        return FieldLocksRepository(_FakeStore(self.db_path))

    def test_set_lock_persists_after_close_reopen(self):
        """Lecon Jellyfin #15549 : le lock doit survivre a close/reopen."""
        repo = self._build_repo()
        res = repo.set_lock(
            "tmdb:603",
            "title",
            "The Matrix",
            run_id="run-1",
            row_id="row-abc",
            source="user_edit",
        )
        self.assertTrue(res["ok"])
        self.assertGreater(res["locked_at"], 0)

        # Nouvelle instance (simule un restart) + nouveau Repository.
        repo2 = self._build_repo()
        lock = repo2.get_lock("tmdb:603", "title")
        self.assertIsNotNone(lock, "Lock doit etre persiste apres close/reopen")
        self.assertEqual(lock["locked_value"], "The Matrix")
        self.assertEqual(lock["source"], "user_edit")
        self.assertEqual(lock["run_id"], "run-1")
        self.assertEqual(lock["row_id"], "row-abc")

    def test_clear_lock_removes_persistence(self):
        repo = self._build_repo()
        repo.set_lock("tmdb:550", "year", 1999)
        self.assertTrue(repo.is_locked("tmdb:550", "year"))

        res = repo.clear_lock("tmdb:550", "year")
        self.assertTrue(res["ok"])
        self.assertTrue(res["removed"])

        # Apres restart, le lock doit etre absent.
        repo2 = self._build_repo()
        self.assertFalse(repo2.is_locked("tmdb:550", "year"))
        self.assertIsNone(repo2.get_lock("tmdb:550", "year"))

    def test_set_lock_idempotent_upsert(self):
        """Re-pose le meme lock 2x : pas d'erreur, valeur mise a jour."""
        repo = self._build_repo()
        repo.set_lock("tmdb:1", "title", "v1")
        repo.set_lock("tmdb:1", "title", "v2")

        repo2 = self._build_repo()
        lock = repo2.get_lock("tmdb:1", "title")
        self.assertEqual(lock["locked_value"], "v2", "Upsert doit ecraser")

        # Une seule ligne en DB
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.execute("SELECT COUNT(*) FROM film_field_locks WHERE film_id=? AND field_name=?", ("tmdb:1", "title"))
        self.assertEqual(int(cur.fetchone()[0]), 1)
        conn.close()

    def test_list_locks_returns_all_for_film(self):
        repo = self._build_repo()
        repo.set_lock("tmdb:42", "title", "Star Wars")
        repo.set_lock("tmdb:42", "year", 1977)
        repo.set_lock("tmdb:42", "overview", "Long ago in a galaxy far, far away...")
        # Lock different film pour verifier l'isolation
        repo.set_lock("tmdb:43", "title", "Other")

        # Reopen
        repo2 = self._build_repo()
        locks = repo2.list_locks("tmdb:42")
        self.assertEqual(len(locks), 3, "3 locks attendus pour tmdb:42")
        field_names = sorted(lk["field_name"] for lk in locks)
        self.assertEqual(field_names, ["overview", "title", "year"])

    def test_empty_film_id_or_field_returns_empty(self):
        repo = self._build_repo()
        self.assertFalse(repo.set_lock("", "title", "x")["ok"])
        self.assertFalse(repo.set_lock("tmdb:1", "", "x")["ok"])
        self.assertIsNone(repo.get_lock("", "title"))
        self.assertEqual(repo.list_locks(""), [])
        self.assertFalse(repo.is_locked("", "title"))


class FieldLocksMigration030PersistenceTests(unittest.TestCase):
    """Test AC-1 : migration 030 testee sur fixture v29 reelle."""

    def test_v29_to_v30_real_migration_030(self):
        """AC-1 : DB pre-existante v29 (post-VP-A) + apply 030 reelle."""
        db_path, conn = existing_db_fixture(29)
        try:
            cur = conn.execute("PRAGMA user_version")
            self.assertEqual(int(cur.fetchone()[0]), 29, "Fixture doit etre v29")

            tables_before = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertNotIn("film_field_locks", tables_before, "Table absente avant 030")
            # AC-4 : film_tmdb_overrides existe deja (migration 023)
            self.assertIn("film_tmdb_overrides", tables_before, "film_tmdb_overrides doit coexister")

            sql_path = _project_migrations_dir() / "030_field_locks.sql"
            self.assertTrue(sql_path.is_file(), "Migration 030 doit exister")
            sql = sql_path.read_text(encoding="utf-8")

            # AC-2 ordre strict CREATE TABLE -> CREATE INDEX, pas d'ALTER
            upper = sql.upper()
            self.assertLess(upper.find("CREATE TABLE"), upper.find("CREATE INDEX"))
            self.assertNotIn("ALTER TABLE", upper, "Pas d'ALTER TABLE en 030")

            # Tous les CREATE doivent etre IF NOT EXISTS (idempotence)
            cleaned_lines = []
            for line in sql.splitlines():
                idx = line.find("--")
                if idx >= 0:
                    line = line[:idx]
                cleaned_lines.append(line)
            cleaned = "\n".join(cleaned_lines).upper()
            create_count = cleaned.count("CREATE TABLE") + cleaned.count("CREATE INDEX")
            if_not_exists_count = cleaned.count("IF NOT EXISTS")
            self.assertEqual(create_count, if_not_exists_count, "Tous les CREATE doivent etre IF NOT EXISTS")

            for stmt in _split_sql_statements(sql):
                conn.execute(stmt)
            conn.execute("PRAGMA user_version = 30")
            conn.commit()

            tables_after = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertIn("film_field_locks", tables_after)
            # AC-4 : film_tmdb_overrides coexiste (pas regresse)
            self.assertIn("film_tmdb_overrides", tables_after)

            cur = conn.execute("PRAGMA user_version")
            self.assertEqual(int(cur.fetchone()[0]), 30)

            # Verifier les 3 index (idx_film, idx_field, idx_film_id)
            indexes = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='film_field_locks'"
                )
            }
            self.assertIn("idx_film_field_locks_film", indexes)
            self.assertIn("idx_film_field_locks_field", indexes)
            self.assertIn("idx_film_field_locks_film_id", indexes)
        finally:
            conn.close()

    def test_migration_030_idempotent(self):
        """Rejouer 030 deux fois doit etre safe (IF NOT EXISTS)."""
        db_path, conn = existing_db_fixture(29)
        try:
            sql = (_project_migrations_dir() / "030_field_locks.sql").read_text(encoding="utf-8")
            for _round in range(2):
                for stmt in _split_sql_statements(sql):
                    conn.execute(stmt)
                conn.execute("PRAGMA user_version = 30")
                conn.commit()

            cur = conn.execute("PRAGMA user_version")
            self.assertEqual(int(cur.fetchone()[0]), 30)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
