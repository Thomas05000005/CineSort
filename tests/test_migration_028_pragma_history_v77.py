"""VO-A migration -- tests migration 028 pragma_history.

Couvre (memoire `feedback_sqlite_migration_test_existing_db`) :
  * Fresh DB : applique 001..028 -> table pragma_history existe + index.
  * DB pre-existante v27 (existing_db_fixture) : applique 028 sans erreur.
  * Idempotence : rejouer 028 deux fois ne casse rien (CREATE IF NOT EXISTS).
  * apply_pragmas insere une ligne d'audit apres migration 028 appliquee.
  * Ordre strict respecte : CREATE TABLE avant CREATE INDEX (PAS d'ALTER).

Pas de modification a la procedure tier_colors / dangerConfirmModal :
cette migration touche uniquement l'audit infra DB.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.infra.db.migration_manager import MigrationManager
from cinesort.infra.db.pragma_profile import apply_pragmas
from tests._helpers import _project_migrations_dir, existing_db_fixture

MIGRATION_FILENAME = "028_pragma_history.sql"
TARGET_VERSION = 28


def _read_migration_028() -> str:
    """Lit le contenu brut de la migration 028 depuis le repo."""
    path = _project_migrations_dir() / MIGRATION_FILENAME
    return path.read_text(encoding="utf-8")


def _exec_migration_028(conn: sqlite3.Connection) -> None:
    """Applique la migration 028 sur une connexion existante.

    Utilise le splitter du MigrationManager pour respecter le parsing reel
    (commentaires `--`, PRAGMA user_version filtre). Cf docstring
    `MigrationManager._split_sql_statements`.
    """
    from cinesort.infra.db.migration_manager import _split_sql_statements

    sql = _read_migration_028()
    for stmt in _split_sql_statements(sql):
        conn.execute(stmt)
    # PRAGMA user_version est filtre par le splitter (cf docstring) -> on le
    # repositionne explicitement pour rester fidele au comportement du manager.
    conn.execute(f"PRAGMA user_version = {TARGET_VERSION}")
    conn.commit()


class Migration028SqlOrderTests(unittest.TestCase):
    """Memoire `feedback_sqlite_migration_test_existing_db` : ordre strict."""

    def test_migration_file_exists(self):
        path = _project_migrations_dir() / MIGRATION_FILENAME
        self.assertTrue(path.is_file(), f"Migration manquante : {path}")

    def test_no_alter_table_statements(self):
        """Regle dure : pas d'ALTER TABLE dans 028 (uniquement CREATE)."""
        sql = _read_migration_028().upper()
        self.assertNotIn("ALTER TABLE", sql, "Migration 028 ne doit PAS contenir ALTER TABLE")

    def test_create_table_before_create_index(self):
        """Ordre strict CREATE TABLE -> CREATE INDEX (sinon SQLite plante)."""
        sql = _read_migration_028().upper()
        idx_table = sql.find("CREATE TABLE")
        idx_index = sql.find("CREATE INDEX")
        self.assertGreaterEqual(idx_table, 0, "Doit contenir CREATE TABLE")
        self.assertGreaterEqual(idx_index, 0, "Doit contenir CREATE INDEX")
        self.assertLess(idx_table, idx_index, "CREATE TABLE doit preceder CREATE INDEX")

    def test_if_not_exists_everywhere(self):
        """Idempotence garantie : tout CREATE en IF NOT EXISTS.

        On ignore les commentaires (-- ...) pour ne pas compter les CREATE
        cites dans la documentation interne.
        """
        sql = _read_migration_028()
        # Filtrer les commentaires ligne-par-ligne (cf. MigrationManager).
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


class Migration028FreshDbTests(unittest.TestCase):
    """Fresh DB : applique toutes les migrations 001..028 d'un coup."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="cinesort_mig028_fresh_"))
        self.db_path = self.tmpdir / "store.sqlite3"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fresh_db_applies_028(self):
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
            self.assertIn("pragma_history", tables)

            cur = conn.execute("PRAGMA table_info(pragma_history)")
            cols = {row[1] for row in cur.fetchall()}
            expected_cols = {
                "id",
                "applied_at",
                "profile_name",
                "db_path",
                "storage_type_detected",
                "pragmas_json",
                "source",
            }
            self.assertEqual(cols, expected_cols)

            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='pragma_history'"
                )
            }
            self.assertIn("idx_pragma_history_applied_at", indexes)
            self.assertIn("idx_pragma_history_db_path", indexes)
        finally:
            conn.close()


class Migration028ExistingDbTests(unittest.TestCase):
    """DB pre-existante v27 : applique uniquement 028 par dessus."""

    def test_existing_v27_then_apply_028(self):
        db_path, conn = existing_db_fixture(27)
        try:
            cur = conn.execute("PRAGMA user_version")
            self.assertEqual(int(cur.fetchone()[0]), 27, "Pre-cond : DB doit etre v27")

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertNotIn("pragma_history", tables, "Pre-cond : table absente avant 028")

            _exec_migration_028(conn)

            tables_after = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("pragma_history", tables_after)

            cur = conn.execute("PRAGMA user_version")
            self.assertEqual(int(cur.fetchone()[0]), TARGET_VERSION)
        finally:
            conn.close()

    def test_idempotence_double_apply_028(self):
        """Rejouer 028 deux fois ne doit JAMAIS lever (IF NOT EXISTS partout)."""
        db_path, conn = existing_db_fixture(27)
        try:
            _exec_migration_028(conn)
            # Premier apply : la table doit etre vide.
            count_first = conn.execute(
                "SELECT COUNT(*) FROM pragma_history"
            ).fetchone()[0]
            self.assertEqual(count_first, 0)

            # Deuxieme apply : ne doit pas lever, et ne doit pas reinitialiser
            # la table existante (DROP TABLE absent du script).
            _exec_migration_028(conn)
            count_second = conn.execute(
                "SELECT COUNT(*) FROM pragma_history"
            ).fetchone()[0]
            self.assertEqual(count_second, 0, "Re-apply ne doit pas modifier les donnees")
        finally:
            conn.close()


class ApplyPragmasRecordsHistoryTests(unittest.TestCase):
    """apply_pragmas() doit inserer une ligne dans pragma_history apres 028."""

    def test_apply_pragmas_records_after_028(self):
        db_path, conn = existing_db_fixture(27)
        try:
            _exec_migration_028(conn)

            snapshot = apply_pragmas(
                conn,
                "local_ssd",
                db_path=str(db_path),
                storage_type_detected="local_ssd",
                source="auto",
            )
            self.assertIsInstance(snapshot, dict)
            self.assertIn("journal_mode", snapshot)

            rows = conn.execute(
                "SELECT profile_name, db_path, storage_type_detected, "
                "pragmas_json, source FROM pragma_history"
            ).fetchall()
            self.assertEqual(len(rows), 1, "Une ligne d'audit attendue apres apply_pragmas")

            profile_name, recorded_path, recorded_storage, payload, source = rows[0]
            self.assertEqual(profile_name, "local_ssd")
            self.assertEqual(recorded_path, str(db_path))
            self.assertEqual(recorded_storage, "local_ssd")
            self.assertEqual(source, "auto")

            payload_dict = json.loads(payload)
            self.assertIn("journal_mode", payload_dict)
        finally:
            conn.close()

    def test_apply_pragmas_no_history_if_table_missing(self):
        """DB v27 sans 028 : apply_pragmas ne doit JAMAIS lever (audit best-effort)."""
        db_path, conn = existing_db_fixture(27)
        try:
            # Table pragma_history n'existe pas (migration 028 non appliquee).
            snapshot = apply_pragmas(
                conn,
                "local_ssd",
                db_path=str(db_path),
                storage_type_detected="local_ssd",
                source="auto",
            )
            self.assertIsInstance(snapshot, dict)
            # Pas de crash = succes.
        finally:
            conn.close()

    def test_apply_pragmas_backward_compat_signature(self):
        """L'appel historique `apply_pragmas(conn, name)` continue de marcher."""
        db_path, conn = existing_db_fixture(0)
        try:
            snapshot = apply_pragmas(conn, "local_ssd")
            self.assertIsInstance(snapshot, dict)
            self.assertIn("journal_mode", snapshot)
        finally:
            conn.close()

    def test_apply_pragmas_record_history_false_skips_insert(self):
        """`record_history=False` : pas d'insert meme si 028 applique."""
        db_path, conn = existing_db_fixture(27)
        try:
            _exec_migration_028(conn)
            apply_pragmas(
                conn,
                "local_ssd",
                db_path=str(db_path),
                storage_type_detected="local_ssd",
                source="auto",
                record_history=False,
            )
            count = conn.execute(
                "SELECT COUNT(*) FROM pragma_history"
            ).fetchone()[0]
            self.assertEqual(count, 0, "record_history=False doit court-circuiter l'insert")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
