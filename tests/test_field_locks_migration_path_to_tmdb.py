"""Vague P / VP-C : fix #5 transition film_id `path:<sha1>` -> `tmdb:<id>`.

AC-3 : lors de l'Identify manuel (ou rematch automatique reussi), TOUS
les locks de l'ancien film_id (path:...) doivent etre migres vers le
nouveau (tmdb:...). C'est `FieldLocksRepository.migrate_locks`.

On teste :
    1. migrate_locks deplace effectivement les locks.
    2. L'ancien film_id n'a plus de locks apres migration.
    3. Si le nouveau film_id avait deja un lock sur le meme field,
       le lock migre depuis path: l'ecrase (le user-manual prime).
    4. compute_film_id produit bien path:<sha1> / tmdb:<id> selon row.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.domain.film_identity import (
    compute_film_id,
    extract_tmdb_id,
    is_path_film_id,
    is_tmdb_film_id,
)
from cinesort.infra.db.migration_manager import _split_sql_statements
from cinesort.infra.db.repositories.field_locks import FieldLocksRepository
from tests._helpers import _project_migrations_dir


class _FakeStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _managed_conn(self):
        @contextmanager
        def _ctx():
            with closing(self._connect()) as conn, conn:
                yield conn

        return _ctx()

    def _ensure_schema_group(self, group_name, *, min_user_version=None):
        return None


def _setup_db_with_030() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="cinesort_locks_migrate_"))
    db_path = tmp / "store.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        sql = (_project_migrations_dir() / "030_field_locks.sql").read_text(encoding="utf-8")
        for stmt in _split_sql_statements(sql):
            conn.execute(stmt)
        conn.execute("PRAGMA user_version = 30")
        conn.commit()
    finally:
        conn.close()
    return db_path


class FilmIdentityTests(unittest.TestCase):
    def test_tmdb_id_present_returns_tmdb_form(self):
        row = {"tmdb_id": 603, "folder": "/x", "video": "matrix.mkv"}
        fid = compute_film_id(row)
        self.assertEqual(fid, "tmdb:603")
        self.assertTrue(is_tmdb_film_id(fid))
        self.assertFalse(is_path_film_id(fid))
        self.assertEqual(extract_tmdb_id(fid), 603)

    def test_no_tmdb_id_returns_path_form(self):
        row = {"folder": "/Films/Matrix", "video": "Matrix.mkv"}
        fid = compute_film_id(row)
        self.assertTrue(is_path_film_id(fid))
        self.assertFalse(is_tmdb_film_id(fid))
        self.assertEqual(len(fid), len("path:") + 40, "sha1 = 40 hex chars")

    def test_path_form_deterministic(self):
        """Meme row -> meme film_id (idempotence cle stable)."""
        row1 = {"folder": "/A", "video": "B.mkv"}
        row2 = {"folder": "/A", "video": "B.mkv", "extra": "ignored"}
        self.assertEqual(compute_film_id(row1), compute_film_id(row2))

    def test_proposed_tmdb_id_fallback(self):
        row = {"proposed_tmdb_id": 550, "folder": "/x", "video": "y.mkv"}
        self.assertEqual(compute_film_id(row), "tmdb:550")

    def test_tmdb_id_zero_falls_back_to_path(self):
        row = {"tmdb_id": 0, "folder": "/x", "video": "y.mkv"}
        self.assertTrue(is_path_film_id(compute_film_id(row)))

    def test_empty_row_returns_path_unknown(self):
        self.assertEqual(compute_film_id({}), "path:unknown")


class MigrateLocksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = _setup_db_with_030()
        self.addCleanup(shutil.rmtree, self.db_path.parent, ignore_errors=True)
        self.repo = FieldLocksRepository(_FakeStore(self.db_path))

    def test_migrate_all_locks_from_path_to_tmdb(self):
        """Fix #5 : 3 locks sur path:abc migres vers tmdb:603."""
        old = "path:abc1234567"
        new = "tmdb:603"

        self.repo.set_lock(old, "proposed_title", "The Matrix", source="manual_identify")
        self.repo.set_lock(old, "proposed_year", 1999, source="user_edit")
        self.repo.set_lock(old, "overview", "Custom synopsis", source="user_edit")

        migrated = self.repo.migrate_locks(old, new)
        self.assertEqual(migrated, 3, "3 locks doivent etre migres")

        # Ancien film_id : plus de locks
        self.assertEqual(self.repo.list_locks(old), [])
        # Nouveau : 3 locks transferes
        new_locks = self.repo.list_locks(new)
        self.assertEqual(len(new_locks), 3)
        new_locks_by_field = {lk["field_name"]: lk for lk in new_locks}
        self.assertEqual(new_locks_by_field["proposed_title"]["locked_value"], "The Matrix")
        self.assertEqual(new_locks_by_field["proposed_year"]["locked_value"], 1999)
        self.assertEqual(new_locks_by_field["overview"]["locked_value"], "Custom synopsis")
        self.assertEqual(new_locks_by_field["proposed_title"]["source"], "manual_identify")

    def test_migrate_zero_locks_returns_zero(self):
        """Pas de lock a migrer -> retourne 0 sans erreur."""
        n = self.repo.migrate_locks("path:never_locked", "tmdb:999")
        self.assertEqual(n, 0)

    def test_migrate_same_id_returns_zero(self):
        """old == new -> no-op."""
        self.repo.set_lock("tmdb:1", "title", "x")
        n = self.repo.migrate_locks("tmdb:1", "tmdb:1")
        self.assertEqual(n, 0)
        self.assertTrue(self.repo.is_locked("tmdb:1", "title"), "Lock toujours present")

    def test_migrate_overwrites_existing_target_lock(self):
        """Si tmdb:603 avait deja un lock title, le manuel ecrase."""
        old = "path:abc"
        new = "tmdb:603"
        # Lock pre-existant cote nouveau (ex. auto-lock OMDb)
        self.repo.set_lock(new, "title", "old_value", source="auto")
        # Lock manuel cote path
        self.repo.set_lock(old, "title", "user_value", source="manual_identify")

        migrated = self.repo.migrate_locks(old, new)
        self.assertEqual(migrated, 1)

        lock = self.repo.get_lock(new, "title")
        self.assertEqual(lock["locked_value"], "user_value", "Manuel doit ecraser auto")
        self.assertEqual(lock["source"], "manual_identify")

    def test_migrate_with_empty_args_returns_zero(self):
        self.assertEqual(self.repo.migrate_locks("", "tmdb:1"), 0)
        self.assertEqual(self.repo.migrate_locks("path:a", ""), 0)
        self.assertEqual(self.repo.migrate_locks("", ""), 0)

    def test_migrate_does_not_affect_other_films(self):
        """Migration n'affecte que les locks du film_id source."""
        self.repo.set_lock("path:A", "title", "A_title")
        self.repo.set_lock("path:B", "title", "B_title")  # autre film
        self.repo.set_lock("tmdb:42", "year", 2000)  # autre film deja en tmdb:

        n = self.repo.migrate_locks("path:A", "tmdb:1")
        self.assertEqual(n, 1)

        self.assertEqual(self.repo.list_locks("path:A"), [])
        self.assertEqual(len(self.repo.list_locks("path:B")), 1, "B intact")
        self.assertEqual(len(self.repo.list_locks("tmdb:42")), 1, "Autre tmdb intact")
        self.assertEqual(len(self.repo.list_locks("tmdb:1")), 1)


if __name__ == "__main__":
    unittest.main()
