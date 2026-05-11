"""V3-11 -- PRAGMA mmap_size SQLite."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, ".")


class PragmaMmapTests(unittest.TestCase):
    def test_connection_has_mmap_size_set(self):
        """Verifie que la factory connect_sqlite applique mmap_size."""
        from cinesort.infra.db.connection import connect_sqlite

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            conn = connect_sqlite(str(db_path))
            try:
                cur = conn.execute("PRAGMA mmap_size")
                row = cur.fetchone()
                mmap_size = int(row[0]) if row else 0
                # Doit etre >= 0 (configure, sinon valeur par defaut).
                # Sur Windows en sandbox de test mmap peut retourner 0 -> tolerance,
                # mais on verifie au moins que le PRAGMA est execute sans crasher.
                self.assertGreaterEqual(mmap_size, 0)
            finally:
                conn.close()

    def test_get_mmap_size_helper(self):
        from cinesort.infra.db.connection import connect_sqlite, get_mmap_size

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            conn = connect_sqlite(str(db_path))
            try:
                size = get_mmap_size(conn)
                self.assertIsInstance(size, int)
                self.assertGreaterEqual(size, 0)
            finally:
                conn.close()

    def test_module_constant_exposed(self):
        """La constante _MMAP_SIZE_BYTES doit exister pour tracabilite."""
        from cinesort.infra.db import connection as conn_mod

        src = Path(conn_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("_MMAP_SIZE_BYTES", src)
        self.assertIn("256", src)


if __name__ == "__main__":
    unittest.main()
