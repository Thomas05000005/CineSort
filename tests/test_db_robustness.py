"""LOT B — Tests de robustesse pour la couche DB et les migrations.

Couvre : migration partielle rollback, idempotence, DB ancienne, DB verrouillee,
creation concurrente de SQLiteStore, apply_operations orphelines, get_unscored_film_count.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path

from cinesort.infra.db.connection import connect_sqlite
from cinesort.infra.db.migration_manager import MigrationManager
from cinesort.infra.db.sqlite_store import SQLiteStore


class MigrationRobustnessTests(unittest.TestCase):
    """13-15 : migrations partielles, idempotence, DB ancienne."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_db_mig_")
        self.db_path = Path(self._tmp) / "test.sqlite"
        self.mig_dir = Path(self._tmp) / "migrations"
        self.mig_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_mig(self, name: str, sql: str) -> None:
        (self.mig_dir / name).write_text(sql, encoding="utf-8")

    # 13
    def test_migration_fails_midway_rollback(self) -> None:
        """Migration avec 3 instructions dont la 2e invalide : rollback et user_version=0."""
        self._write_mig(
            "001_partial.sql",
            """
            CREATE TABLE IF NOT EXISTS foo (id INTEGER PRIMARY KEY);
            CREATE TABLE THIS IS NOT VALID SQL;
            CREATE TABLE IF NOT EXISTS bar (id INTEGER PRIMARY KEY);
        """,
        )
        mgr = MigrationManager(self.db_path, self.mig_dir)
        with self.assertRaises(sqlite3.DatabaseError):
            mgr.apply()

        if self.db_path.exists():
            with closing(sqlite3.connect(str(self.db_path))) as conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                self.assertEqual(int(version), 0)
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertNotIn("foo", tables)
                self.assertNotIn("bar", tables)

    # 14
    def test_migration_idempotent(self) -> None:
        """Executer la meme migration 2 fois : passe sans erreur."""
        self._write_mig(
            "001_idem.sql",
            """
            CREATE TABLE IF NOT EXISTS foo (id INTEGER PRIMARY KEY, name TEXT);
            CREATE INDEX IF NOT EXISTS idx_foo_name ON foo(name);
            PRAGMA user_version = 1;
        """,
        )
        mgr = MigrationManager(self.db_path, self.mig_dir)
        v1 = mgr.apply()
        self.assertEqual(v1, 1)
        # Deuxieme passage
        v2 = mgr.apply()
        self.assertEqual(v2, 1)

    # 14b — H-1 audit QA 20260428 : idempotence des ALTER TABLE ADD COLUMN
    def test_migration_alter_table_add_column_already_exists(self) -> None:
        """Si une colonne ajoutee par ALTER TABLE existe deja (DB clonee,
        restauree, ou migration appliquee a la main), la migration doit
        continuer plutot que de planter. SQLite ne supporte pas
        ADD COLUMN IF NOT EXISTS avant 3.35.
        """
        # 2 migrations : la 1 cree la table, la 2 ajoute une colonne via ALTER
        self._write_mig(
            "001_create.sql",
            """
            CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT);
            PRAGMA user_version = 1;
            """,
        )
        self._write_mig(
            "002_alter.sql",
            """
            ALTER TABLE items ADD COLUMN extra TEXT DEFAULT NULL;
            CREATE INDEX IF NOT EXISTS idx_items_extra ON items(extra);
            """,
        )

        # Simule une DB ou la 002 a deja ete appliquee partiellement :
        # colonne `extra` deja la, mais user_version reste a 1 (ex: rollback
        # entre la creation de la colonne et le bump de user_version, ou DB
        # restauree d'une autre source).
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, extra TEXT DEFAULT NULL)")
            conn.execute("PRAGMA user_version = 1")
            conn.commit()

        mgr = MigrationManager(self.db_path, self.mig_dir)
        # Doit rejouer la 002 sans planter sur "duplicate column extra"
        version = mgr.apply()
        self.assertEqual(version, 2)
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
            self.assertEqual(cols, {"id", "name", "extra"})
            indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertIn("idx_items_extra", indexes)

    # 14c — H-1 : une vraie erreur SQL doit toujours planter
    def test_migration_real_sql_error_still_raises(self) -> None:
        """Si une migration contient une vraie erreur (pas une duplicate column),
        elle doit toujours planter et rollback."""
        self._write_mig(
            "001_create.sql",
            """
            CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY);
            PRAGMA user_version = 1;
            """,
        )
        self._write_mig(
            "002_bad.sql",
            """
            ALTER TABLE items ADD COLUMN extra TEXT;
            ALTER TABLE table_qui_nexiste_pas ADD COLUMN x TEXT;
            """,
        )

        mgr = MigrationManager(self.db_path, self.mig_dir)
        with self.assertRaises(sqlite3.DatabaseError):
            mgr.apply()
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            v = conn.execute("PRAGMA user_version").fetchone()[0]
            # La 001 a passe, la 002 a rollback : version = 1
            self.assertEqual(int(v), 1)

    # 15
    def test_migration_on_old_db(self) -> None:
        """Appliquer les migrations sur une DB qui a deja user_version=5."""
        # Cree 6 migrations (1-6), puis simule une DB ancienne a v3
        for i in range(1, 7):
            self._write_mig(f"{i:03d}_mig.sql", f"CREATE TABLE IF NOT EXISTS t{i} (id INTEGER PRIMARY KEY);")

        mgr = MigrationManager(self.db_path, self.mig_dir)
        # Simule une DB a v3 (pre-existe)
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("CREATE TABLE t1 (id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE t2 (id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE t3 (id INTEGER PRIMARY KEY)")
            conn.execute("PRAGMA user_version = 3")
            conn.commit()

        # Applique les migrations : doit migrer de 3 → 6
        version = mgr.apply()
        self.assertEqual(version, 6)
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for i in range(1, 7):
                self.assertIn(f"t{i}", tables, f"Table t{i} manquante apres migration")


class DbLockingTests(unittest.TestCase):
    """16-17 : concurrence DB."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_db_lock_")
        self.db_path = Path(self._tmp) / "concurrent.sqlite"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    # 16
    def test_db_locked_busy_timeout_configured(self) -> None:
        """Verifie que connect_sqlite applique bien busy_timeout et que des ecritures
        concurrentes sequentielles fonctionnent (mode WAL).
        """
        # Cree la base
        with closing(connect_sqlite(str(self.db_path), busy_timeout_ms=3000)) as conn:
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, val TEXT)")
            conn.commit()
            # Verifie que busy_timeout est bien configure
            timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            self.assertEqual(int(timeout), 3000)
            # Verifie que journal_mode est WAL (permet lectures concurrentes)
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(str(mode).lower(), "wal")
            # P-4 audit QA 20260429 : pragmas perf appliques pour lectures rapides
            # synchronous = NORMAL : economise un fsync par commit en WAL
            sync = conn.execute("PRAGMA synchronous").fetchone()[0]
            self.assertEqual(int(sync), 1)  # 1 = NORMAL (0=OFF, 2=FULL, 3=EXTRA)
            # cache_size = -65536 : 64 MB de cache page (negatif = KB)
            cache = conn.execute("PRAGMA cache_size").fetchone()[0]
            self.assertEqual(int(cache), -65536)
            # temp_store = MEMORY : tables temp/index en RAM
            temp_store = conn.execute("PRAGMA temp_store").fetchone()[0]
            self.assertEqual(int(temp_store), 2)  # 2 = MEMORY (0=DEFAULT, 1=FILE)
            # foreign_keys ON : integrite referentielle
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            self.assertEqual(int(fk), 1)

        # 2 connexions sequentielles inserent : doit fonctionner en WAL
        with closing(connect_sqlite(str(self.db_path), busy_timeout_ms=3000)) as c1:
            c1.execute("INSERT INTO items (val) VALUES (?)", ("a",))
            c1.commit()
        with closing(connect_sqlite(str(self.db_path), busy_timeout_ms=3000)) as c2:
            c2.execute("INSERT INTO items (val) VALUES (?)", ("b",))
            c2.commit()
            rows = c2.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            self.assertEqual(rows, 2)

    # 17
    def test_concurrent_sqlite_store_creation(self) -> None:
        """Apres une initialisation prealable, 10 threads peuvent creer des SQLiteStore
        et appeler initialize() (idempotent grace a PRAGMA user_version)."""
        # Initialise d'abord la DB (single-writer)
        SQLiteStore(self.db_path, busy_timeout_ms=5000).initialize()

        errors: list = []

        def _worker():
            try:
                store = SQLiteStore(self.db_path, busy_timeout_ms=10000)
                store.initialize()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        self.assertEqual(errors, [], f"Erreurs concurrentes apres init initial : {errors}")
        self.assertTrue(self.db_path.exists())


class ApplyOperationsOrphanTests(unittest.TestCase):
    """18 : apply_operations orphelines (batch_id inexistant)."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_orphan_")
        self.db_path = Path(self._tmp) / "orphan.sqlite"
        self.store = SQLiteStore(self.db_path, busy_timeout_ms=5000)
        self.store.initialize()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_orphan_apply_operations_do_not_crash(self) -> None:
        """Une apply_operation avec batch_id inexistant ne doit pas crasher la lecture."""
        # Insere directement via sqlite3 pour bypasser la FK check (la FK n'est pas stricte)
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                """
                INSERT INTO apply_operations
                (batch_id, op_index, op_type, src_path, dst_path, reversible, undo_status, error_message, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                ("batch_inexistant", 0, "MOVE", "/a", "/b", 1, "PENDING", None, time.time()),
            )
            conn.commit()

        # Lire les ops via l'API du store ne doit pas crasher
        try:
            # Pas de methode directe, on interroge directement
            with closing(sqlite3.connect(str(self.db_path))) as conn:
                cur = conn.execute("SELECT COUNT(*) FROM apply_operations WHERE batch_id = ?", ("batch_inexistant",))
                count = cur.fetchone()[0]
                self.assertEqual(count, 1)
        except Exception as exc:
            self.fail(f"Lecture d'apply_operation orpheline crashe : {exc}")


class UnscoredFilmCountTests(unittest.TestCase):
    """19 : get_unscored_film_count retourne le bon nombre (bug d'inversion corrige)."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_unscored_")
        self.db_path = Path(self._tmp) / "unscored.sqlite"
        self.store = SQLiteStore(self.db_path, busy_timeout_ms=5000)
        self.store.initialize()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_unscored_count_returns_correct_value(self) -> None:
        """10 films total, 3 avec quality_report → get_unscored_film_count retourne 7."""
        run_id = "run-test-123"
        # Inserer 3 quality_reports directement via sqlite3
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            for i in range(3):
                conn.execute(
                    """
                    INSERT INTO quality_reports
                    (run_id, row_id, score, tier, reasons_json, metrics_json, profile_id, profile_version, ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (run_id, f"row-{i}", 75, "bon", "[]", "{}", "default", 1, time.time()),
                )
            conn.commit()

        # Appel : total=10 films → 10 - 3 = 7 unscored
        unscored = self.store.get_unscored_film_count(run_id=run_id, total_rows=10)
        self.assertEqual(unscored, 7)

        # Cas limite : total=3 (= scored)
        self.assertEqual(self.store.get_unscored_film_count(run_id=run_id, total_rows=3), 0)

        # Cas limite : total=0
        self.assertEqual(self.store.get_unscored_film_count(run_id=run_id, total_rows=0), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
