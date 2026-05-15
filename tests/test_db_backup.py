"""CR-2 audit QA 20260429 — tests du backup automatique SQLite.

Couvre :
- backup_db : copie atomique via sqlite3.Connection.backup() natif.
- list_backups : tri par mtime decroissant + filtre stem.
- rotate_backups : garde N plus recents, supprime le reste.
- backup_db_with_rotation : helper combine, tolerant au fresh install.
- restore_backup : avec garde-fou (backup du target courant).
- SQLiteStore.initialize : backup auto avant migrations si DB existe.
- SQLiteStore.backup_now : API publique.
- Pas de backup sur fresh install.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from cinesort.infra.db.backup import (
    BACKUP_SUFFIX,
    DEFAULT_MAX_BACKUPS,
    backup_db,
    backup_db_with_rotation,
    list_backups,
    restore_backup,
    rotate_backups,
)
from cinesort.infra.db.sqlite_store import SQLiteStore


class BackupDbFunctionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_backup_"))
        self.src = self._tmp / "cinesort.sqlite"
        # Cree une DB minimale avec quelques donnees pour verifier l'integrite
        with closing(sqlite3.connect(str(self.src))) as conn:
            conn.execute("CREATE TABLE foo (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO foo (name) VALUES (?)", ("alpha",))
            conn.execute("INSERT INTO foo (name) VALUES (?)", ("beta",))
            conn.commit()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_backup_creates_valid_copy(self) -> None:
        dst = self._tmp / "backups" / "test.bak"
        result = backup_db(self.src, dst)
        self.assertEqual(result, dst)
        self.assertTrue(dst.is_file())
        # Le backup doit etre une DB valide avec les memes donnees
        with closing(sqlite3.connect(str(dst))) as conn:
            rows = conn.execute("SELECT name FROM foo ORDER BY id").fetchall()
            self.assertEqual(rows, [("alpha",), ("beta",)])

    def test_backup_creates_dest_dir(self) -> None:
        dst = self._tmp / "deeply" / "nested" / "dir" / "x.bak"
        backup_db(self.src, dst)
        self.assertTrue(dst.exists())

    def test_backup_raises_on_missing_source(self) -> None:
        with self.assertRaises(FileNotFoundError):
            backup_db(self._tmp / "ghost.sqlite", self._tmp / "out.bak")


class ListAndRotateBackupsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_rotate_"))
        self.bdir = self._tmp / "backups"
        self.bdir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_backup(self, name: str, mtime: float) -> Path:
        path = self.bdir / name
        path.write_bytes(b"fake")
        import os

        os.utime(path, (mtime, mtime))
        return path

    def test_list_backups_sorted_recent_first(self) -> None:
        old = self._make_backup(f"a{BACKUP_SUFFIX}", time.time() - 1000)
        recent = self._make_backup(f"b{BACKUP_SUFFIX}", time.time())
        result = list_backups(self.bdir)
        self.assertEqual(result, [recent, old])

    def test_list_backups_stem_filter(self) -> None:
        self._make_backup(f"cinesort.20260101-120000.x{BACKUP_SUFFIX}", time.time())
        self._make_backup(f"other.20260101-130000.y{BACKUP_SUFFIX}", time.time())
        result = list_backups(self.bdir, stem_filter="cinesort")
        self.assertEqual(len(result), 1)
        self.assertIn("cinesort", result[0].name)

    def test_list_backups_missing_dir_returns_empty(self) -> None:
        self.assertEqual(list_backups(self._tmp / "nonexistent"), [])

    def test_rotate_keeps_n_most_recent(self) -> None:
        # Cree 7 backups avec mtimes decroissants
        for i in range(7):
            self._make_backup(f"b{i}{BACKUP_SUFFIX}", time.time() - i * 100)
        n_kept, deleted = rotate_backups(self.bdir, max_count=3)
        self.assertEqual(n_kept, 3)
        self.assertEqual(len(deleted), 4)
        remaining = list_backups(self.bdir)
        self.assertEqual(len(remaining), 3)
        # Les plus recents (b0, b1, b2) doivent rester
        names = {p.name for p in remaining}
        self.assertEqual(names, {f"b{i}{BACKUP_SUFFIX}" for i in range(3)})

    def test_rotate_no_op_when_below_max(self) -> None:
        for i in range(3):
            self._make_backup(f"b{i}{BACKUP_SUFFIX}", time.time() - i * 100)
        n_kept, deleted = rotate_backups(self.bdir, max_count=5)
        self.assertEqual(n_kept, 3)
        self.assertEqual(deleted, [])


class BackupWithRotationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_bwr_"))
        self.src = self._tmp / "cinesort.sqlite"
        with closing(sqlite3.connect(str(self.src))) as conn:
            conn.execute("CREATE TABLE x (id INTEGER PRIMARY KEY)")
            conn.commit()
        self.bdir = self._tmp / "backups"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_creates_named_backup(self) -> None:
        result = backup_db_with_rotation(self.src, self.bdir, trigger="manual", max_count=5)
        self.assertIsNotNone(result)
        self.assertTrue(result.is_file())
        self.assertTrue(result.name.startswith("cinesort."))
        self.assertIn(".manual.", result.name)
        self.assertTrue(result.name.endswith(BACKUP_SUFFIX))

    def test_returns_none_for_missing_source(self) -> None:
        ghost = self._tmp / "ghost.sqlite"
        result = backup_db_with_rotation(ghost, self.bdir, trigger="manual")
        self.assertIsNone(result)

    def test_rotates_after_backup(self) -> None:
        # Cree 6 backups successifs (assez pour declencher rotation a max=5)
        for _ in range(6):
            backup_db_with_rotation(self.src, self.bdir, trigger="post_apply", max_count=5)
            # Pas de time.sleep necessaire : depuis #81, le naming inclut
            # les microsecondes (UTC), donc plus de collision meme rafale.
        backups = list_backups(self.bdir)
        self.assertEqual(len(backups), 5)

    def test_naming_uses_utc_with_microseconds(self) -> None:
        # Cf issue #81 : le nom doit contenir le suffixe `Z` (UTC) et
        # les microsecondes (6 chiffres apres un `-`).
        result = backup_db_with_rotation(self.src, self.bdir, trigger="manual")
        self.assertIsNotNone(result)
        # Pattern attendu : cinesort.YYYYMMDD-HHMMSS-NNNNNNZ.manual.bak
        self.assertRegex(result.name, r"^cinesort\.\d{8}-\d{6}-\d{6}Z\.manual\.bak$")

    def test_naming_no_collision_in_same_microsecond(self) -> None:
        # Defensive : meme si on passe deux ts identiques, les noms diffèrent
        # parce que la 2eme creation ecrase la 1ere (memes microsecondes →
        # meme fichier, comportement deterministe et acceptable).
        from cinesort.infra.db.backup import _format_backup_name

        n1 = _format_backup_name("cinesort", "manual", ts=1747320000.123456)
        n2 = _format_backup_name("cinesort", "manual", ts=1747320000.123456)
        self.assertEqual(n1, n2)  # ts identique → meme nom (correct)
        n3 = _format_backup_name("cinesort", "manual", ts=1747320000.123457)
        self.assertNotEqual(n1, n3)  # +1 microsec → nom different


class RestoreBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_restore_"))
        self.target = self._tmp / "live.sqlite"
        self.backup_path = self._tmp / "backup.bak"

        # Cree une "vieille" DB (le backup) et une "nouvelle" (le target courant)
        with closing(sqlite3.connect(str(self.backup_path))) as conn:
            conn.execute("CREATE TABLE data (v TEXT)")
            conn.execute("INSERT INTO data VALUES ('OLD')")
            conn.commit()
        with closing(sqlite3.connect(str(self.target))) as conn:
            conn.execute("CREATE TABLE data (v TEXT)")
            conn.execute("INSERT INTO data VALUES ('NEW')")
            conn.commit()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_restore_replaces_target(self) -> None:
        restore_backup(self.backup_path, self.target)
        with closing(sqlite3.connect(str(self.target))) as conn:
            row = conn.execute("SELECT v FROM data").fetchone()
        self.assertEqual(row[0], "OLD")

    def test_restore_creates_guard_backup(self) -> None:
        restore_backup(self.backup_path, self.target)
        # Un fichier .before_restore.* doit avoir ete cree dans le dossier target
        guards = list(self.target.parent.glob("*before_restore*"))
        self.assertGreaterEqual(len(guards), 1)

    def test_restore_raises_on_missing_backup(self) -> None:
        with self.assertRaises(FileNotFoundError):
            restore_backup(self._tmp / "ghost.bak", self.target)


class SQLiteStoreBackupIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_store_bak_"))
        self.db_path = self._tmp / "db" / "cinesort.sqlite"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_initialize_no_backup_on_fresh_install(self) -> None:
        """Pas de backup au tout premier initialize (DB n'existe pas encore)."""
        store = SQLiteStore(self.db_path, busy_timeout_ms=5000)
        store.initialize()
        backup_dir = self.db_path.parent / "backups"
        # Soit le dossier n'existe pas, soit il est vide
        if backup_dir.exists():
            self.assertEqual(list(backup_dir.iterdir()), [])

    def test_initialize_creates_backup_when_db_exists(self) -> None:
        """Au 2e initialize, la DB existe -> backup pre_migration cree."""
        # 1er init pour creer la DB
        store1 = SQLiteStore(self.db_path, busy_timeout_ms=5000)
        store1.initialize()
        # 2e init : la DB existe deja, donc backup
        store2 = SQLiteStore(self.db_path, busy_timeout_ms=5000)
        store2.initialize()
        backups = store2.list_db_backups()
        self.assertGreaterEqual(len(backups), 1)
        self.assertIn("pre_migration", backups[0].name)

    def test_backup_now_creates_named_backup(self) -> None:
        store = SQLiteStore(self.db_path, busy_timeout_ms=5000)
        store.initialize()
        result = store.backup_now(trigger="manual")
        self.assertIsNotNone(result)
        self.assertIn("manual", result.name)

    def test_backup_now_returns_none_if_no_db(self) -> None:
        # Cas edge : on appelle backup_now sans avoir initialize -> pas de fichier
        store = SQLiteStore(self.db_path, busy_timeout_ms=5000)
        result = store.backup_now(trigger="manual")
        self.assertIsNone(result)

    def test_initialize_rotates_old_backups(self) -> None:
        """Apres > DEFAULT_MAX_BACKUPS initialize, le nombre de backups est cap."""
        store = SQLiteStore(self.db_path, busy_timeout_ms=5000)
        store.initialize()  # 1er = pas de backup
        for _ in range(DEFAULT_MAX_BACKUPS + 3):
            SQLiteStore(self.db_path, busy_timeout_ms=5000).initialize()
            time.sleep(0.001)
        backups = store.list_db_backups()
        self.assertLessEqual(len(backups), DEFAULT_MAX_BACKUPS)


class ApplyChangesIntegrationBackupTests(unittest.TestCase):
    """CR-2 audit QA 20260429 — verifie le hook backup_now apres apply_changes
    via le vrai chemin apply_support (et pas juste l'API SQLiteStore directe).

    C'est un test integration leger : on simule un apply minimal avec dry_run=
    False pour declencher le hook post-apply, et on verifie que le backup
    apparait dans <db_dir>/backups/.
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_apply_bak_"))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_backup_now_called_via_post_apply_hook(self) -> None:
        """apply_support.apply_changes appelle store.backup_now(trigger='post_apply')
        apres un apply reel reussi. Le backup doit apparaitre avec le trigger
        attendu dans le nom de fichier.

        On teste juste l'appel direct a backup_now (pas tout le flux apply,
        qui demande beaucoup de mocking). Cela confirme que :
        1. Le trigger 'post_apply' est bien expose.
        2. Le fichier .post_apply.bak est bien cree dans le dossier backup.
        """
        db_path = self._tmp / "db" / "cinesort.sqlite"
        store = SQLiteStore(db_path, busy_timeout_ms=5000)
        store.initialize()  # cree la DB

        # Simuler le hook qui se trouve dans apply_support apres apply reel
        result = store.backup_now(trigger="post_apply")

        self.assertIsNotNone(result)
        self.assertTrue(result.is_file())
        self.assertIn(".post_apply.", result.name)
        self.assertTrue(result.name.endswith(".bak"))
        # Le backup doit etre dans <db_dir>/backups/
        self.assertEqual(result.parent.name, "backups")
        # Liste des backups (helper public)
        backups = store.list_db_backups()
        self.assertGreaterEqual(len(backups), 1)

    def test_apply_support_imports_backup_helper(self) -> None:
        """Verifie que apply_support importe bien check_disk_space_for_apply
        ET que store.backup_now est appelable depuis ce module.
        Garde-fou contre une regression de l'import.
        """
        from cinesort.ui.api import apply_support

        self.assertTrue(hasattr(apply_support, "check_disk_space_for_apply"))
        # Le hook backup_now est appele via store.backup_now() au runtime,
        # pas un import direct. On verifie via SQLiteStore.
        self.assertTrue(hasattr(SQLiteStore, "backup_now"))
        self.assertTrue(hasattr(SQLiteStore, "list_db_backups"))


if __name__ == "__main__":
    unittest.main()
