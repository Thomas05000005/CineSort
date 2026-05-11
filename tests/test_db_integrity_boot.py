"""V1-09 audit ID-Y-001 — DB integrity check au demarrage.

Verifie que SQLiteStore.initialize() execute PRAGMA integrity_check et
expose le resultat via la property integrity_status (consommable par l'UI).
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cinesort.infra.db.sqlite_store import SQLiteStore


class IntegrityCheckBootTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_integrity_boot_")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_fresh_db_integrity_ok(self) -> None:
        """Fresh install : status doit etre 'ok' apres initialize."""
        db = Path(self._tmp) / "fresh.sqlite"
        store = SQLiteStore(db)
        store.initialize()
        self.assertEqual(store.integrity_status, "ok")

    def test_integrity_status_unknown_before_initialize(self) -> None:
        """Avant initialize(), status = 'unknown' (pas encore mesure)."""
        db = Path(self._tmp) / "noinit.sqlite"
        store = SQLiteStore(db)
        self.assertEqual(store.integrity_status, "unknown")

    def test_corrupted_header_detected(self) -> None:
        """Magic bytes corrompus (offset 0-15) : status != 'ok' OU init raise."""
        db = Path(self._tmp) / "corrupt_header.sqlite"
        SQLiteStore(db).initialize()
        # Corrompre le SQLite header magic string ("SQLite format 3\0").
        with open(db, "r+b") as f:
            f.seek(0)
            f.write(b"BADBADBAD\x00\x00\x00\x00\x00\x00\x00")
        store = SQLiteStore(db)
        try:
            store.initialize()
            self.assertNotEqual(store.integrity_status, "ok")
        except (sqlite3.DatabaseError, RuntimeError):
            # DB tellement cassee que l'open ou les migrations echouent :
            # comportement acceptable, l'utilisateur sera quand meme alerte.
            pass

    def test_corrupted_page_detected(self) -> None:
        """Page corrompue (offset 4096+) : status != 'ok' OU init raise."""
        db = Path(self._tmp) / "corrupt_page.sqlite"
        SQLiteStore(db).initialize()
        # Ecrire des octets aberrants dans la 2e page (offset 4096).
        with open(db, "r+b") as f:
            f.seek(4096)
            f.write(b"\xff" * 100)
        store = SQLiteStore(db)
        try:
            store.initialize()
            self.assertNotEqual(store.integrity_status, "ok")
        except (sqlite3.DatabaseError, RuntimeError):
            pass


if __name__ == "__main__":
    unittest.main()
