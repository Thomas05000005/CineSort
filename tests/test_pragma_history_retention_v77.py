"""GATE — pragma_history est bornee (retention) apres chaque insert.

Bug (AUDIT REAL 2/2, pragma_profile.py:219) : _record_pragma_history inserait
une ligne a CHAQUE ouverture de connexion (chaque methode repository en ouvre
1 a 3) et AUCUNE purge n'existait nulle part -> croissance non bornee de la
table (des dizaines de milliers de lignes JSON par scan), chaque LECTURE
devenant une ECRITURE durable (contention write-lock WAL, synchronous=FULL sur
nas_smb).

Fix : purge bornee DANS la meme transaction que l'INSERT, gardant les
_PRAGMA_HISTORY_MAX_ROWS lignes les plus recentes (par id PK monotone).

GATE : apres N > cap inserts, la table contient exactement `cap` lignes, et ce
sont les plus recentes (les anciennes sont purgees).
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, ".")

import cinesort.infra.db.pragma_profile as _pp
from cinesort.infra.db.migration_manager import _split_sql_statements
from cinesort.infra.db.pragma_profile import apply_pragmas
from tests._helpers import _project_migrations_dir, existing_db_fixture

# Lecture defensive du plafond : si le fix n'est pas encore en place (constante
# absente), on retombe sur 500 pour que le GATE echoue sur l'ASSERTION (table
# non bornee) plutot que sur un ImportError -- preuve comportementale du bug.
_PRAGMA_HISTORY_MAX_ROWS = getattr(_pp, "_PRAGMA_HISTORY_MAX_ROWS", 500)


def _apply_migration_028(conn: sqlite3.Connection) -> None:
    sql = (_project_migrations_dir() / "028_pragma_history.sql").read_text(encoding="utf-8")
    for stmt in _split_sql_statements(sql):
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 28")
    conn.commit()


class PragmaHistoryRetentionTests(unittest.TestCase):
    def _seed(self, conn: sqlite3.Connection, db_path: Path, n: int) -> None:
        for _ in range(n):
            apply_pragmas(
                conn,
                "local_ssd",
                db_path=str(db_path),
                storage_type_detected="local_ssd",
                source="auto",
            )

    def test_table_is_bounded_after_many_inserts(self) -> None:
        db_path, conn = existing_db_fixture(27)
        try:
            _apply_migration_028(conn)
            cap = _PRAGMA_HISTORY_MAX_ROWS
            self._seed(conn, db_path, cap + 137)
            count = conn.execute("SELECT COUNT(*) FROM pragma_history").fetchone()[0]
            self.assertLessEqual(count, cap)
            self.assertEqual(count, cap, "doit garder exactement le plafond")
        finally:
            conn.close()

    def test_keeps_most_recent_rows(self) -> None:
        db_path, conn = existing_db_fixture(27)
        try:
            _apply_migration_028(conn)
            cap = _PRAGMA_HISTORY_MAX_ROWS
            n = cap + 50
            self._seed(conn, db_path, n)
            min_id, max_id = conn.execute("SELECT MIN(id), MAX(id) FROM pragma_history").fetchone()
            # Les anciennes lignes (id <= n-cap) ont ete purgees, les plus
            # recentes conservees.
            self.assertEqual(max_id, n)
            self.assertEqual(min_id, n - cap + 1)
        finally:
            conn.close()

    def test_under_cap_keeps_all(self) -> None:
        # Sous le plafond, aucune purge : usage normal (peu de connexions).
        db_path, conn = existing_db_fixture(27)
        try:
            _apply_migration_028(conn)
            self._seed(conn, db_path, 5)
            count = conn.execute("SELECT COUNT(*) FROM pragma_history").fetchone()[0]
            self.assertEqual(count, 5)
        finally:
            conn.close()

    def test_purge_does_not_break_when_table_missing(self) -> None:
        # DB v27 sans migration 028 : apply_pragmas reste best-effort (pas de crash).
        db_path, conn = existing_db_fixture(27)
        try:
            snapshot = apply_pragmas(
                conn,
                "local_ssd",
                db_path=str(db_path),
                storage_type_detected="local_ssd",
                source="auto",
            )
            self.assertIsInstance(snapshot, dict)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
