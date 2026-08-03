"""Migration 025 (V8-01 spec 08 Traitement) — recreate-table runs SANS perte enfants.

Source : audit Vague H.2 (2026-05-25).

Contexte :
- Depuis migration 021, errors/quality_reports/anomalies ont ON DELETE CASCADE sur runs.
- Migration 025 fait un DROP TABLE runs (recreate-table pattern pour etendre CHECK status).
- Sans le marqueur `-- @manager: disable_fk`, le DROP propagerait CASCADE et viderait
  toutes les rows enfants -> perte de donnees utilisateur silencieuse.

Ce test verifie que :
1. Le marqueur est present dans le fichier 025.
2. Le manager le detecte (`in sql`).
3. Apres migration v24 -> v25, les rows enfants (errors, quality_reports, anomalies)
   sont toujours presentes : COUNT(*) identique avant/apres.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.infra.db.connection import connect_sqlite
from cinesort.infra.db.migration_manager import MigrationManager

_REAL_MIG_DIR = Path("cinesort/infra/db/migrations")


class Migration025NoDataLossTests(unittest.TestCase):
    """v24 -> v25 ne doit PAS perdre les rows enfants des runs."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_mig025_")
        self.db_path = Path(self._tmp) / "t.db"
        # Repertoire de migrations limite a 1-24 (pre-025)
        self._mig_v24 = Path(self._tmp) / "mig_v24"
        self._mig_v24.mkdir()
        for f in sorted(_REAL_MIG_DIR.glob("*.sql")):
            try:
                version = int(f.stem.split("_")[0])
            except ValueError:
                continue
            if version <= 24:
                shutil.copy(f, self._mig_v24 / f.name)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_marker_present_in_migration_025(self) -> None:
        """Le marqueur disable_fk doit etre present dans le fichier 025."""
        sql = (_REAL_MIG_DIR / "025_run_pause_status.sql").read_text(encoding="utf-8")
        self.assertIn(
            "@manager: disable_fk",
            sql,
            "Migration 025 fait un DROP TABLE runs et DOIT contenir le marker disable_fk "
            "sinon la CASCADE des FK enfants (errors, quality_reports, anomalies) "
            "viderait silencieusement leurs rows.",
        )

    def test_v24_to_v25_preserves_run_children(self) -> None:
        """Migration 024->025 : errors/quality_reports/anomalies preserves."""
        # 1) DB initialisee a v24
        mgr = MigrationManager(self.db_path, self._mig_v24)
        v = mgr.apply()
        self.assertEqual(v, 24)

        # 2) Seed : 1 run + 3 errors + 2 quality_reports + 2 anomalies
        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            conn.execute(
                "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                "VALUES ('R25', 'DONE', ?, '/root', '/state', '{}')",
                (ts,),
            )
            for i in range(3):
                conn.execute(
                    "INSERT INTO errors(run_id, ts, step, code, message) VALUES ('R25', ?, 'scan', ?, 'm')",
                    (ts, f"E{i}"),
                )
            for i in range(2):
                conn.execute(
                    "INSERT INTO quality_reports VALUES ('R25', ?, ?, 'Gold', '[]', '{}', 'p1', 1, ?)",
                    (f"row{i}", 80 + i, ts),
                )
            for i in range(2):
                conn.execute(
                    "INSERT INTO anomalies(run_id, severity, code, message, ts) VALUES ('R25', 'WARN', ?, 'm', ?)",
                    (f"A{i}", ts),
                )
            conn.commit()

            # Sanity : compter avant migration
            errors_before = int(conn.execute("SELECT COUNT(*) FROM errors WHERE run_id='R25'").fetchone()[0])
            qr_before = int(conn.execute("SELECT COUNT(*) FROM quality_reports WHERE run_id='R25'").fetchone()[0])
            anom_before = int(conn.execute("SELECT COUNT(*) FROM anomalies WHERE run_id='R25'").fetchone()[0])
            self.assertEqual(errors_before, 3)
            self.assertEqual(qr_before, 2)
            self.assertEqual(anom_before, 2)

        # 3) Migration vers v25 (repertoire reel inclut 025)
        mgr_v25 = MigrationManager(self.db_path, _REAL_MIG_DIR)
        v = mgr_v25.apply()
        self.assertGreaterEqual(v, 25)

        # 4) Verifier que tout est preserve
        with closing(connect_sqlite(str(self.db_path))) as conn:
            # Le run lui-meme est toujours la (recree par INSERT SELECT)
            self.assertEqual(
                int(conn.execute("SELECT COUNT(*) FROM runs WHERE run_id='R25'").fetchone()[0]),
                1,
                "Le run R25 doit etre re-insere par INSERT SELECT dans runs_new",
            )
            # Les enfants ne doivent PAS avoir ete cascades
            self.assertEqual(
                int(conn.execute("SELECT COUNT(*) FROM errors WHERE run_id='R25'").fetchone()[0]),
                3,
                "CASCADE silencieuse : 3 errors auraient ete supprimees sans disable_fk",
            )
            self.assertEqual(
                int(conn.execute("SELECT COUNT(*) FROM quality_reports WHERE run_id='R25'").fetchone()[0]),
                2,
                "CASCADE silencieuse : 2 quality_reports auraient ete supprimes sans disable_fk",
            )
            self.assertEqual(
                int(conn.execute("SELECT COUNT(*) FROM anomalies WHERE run_id='R25'").fetchone()[0]),
                2,
                "CASCADE silencieuse : 2 anomalies auraient ete supprimees sans disable_fk",
            )

    def test_v25_schema_has_new_status_values(self) -> None:
        """Apres v25, la CHECK runs.status accepte bien PAUSED/SAVED/AWAITING_VALIDATION."""
        mgr = MigrationManager(self.db_path, _REAL_MIG_DIR)
        mgr.apply()
        ts = time.time()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            for status in ("PAUSED", "SAVED", "AWAITING_VALIDATION"):
                conn.execute(
                    "INSERT INTO runs(run_id, status, created_ts, root, state_dir, config_json) "
                    "VALUES (?, ?, ?, '/r', '/s', '{}')",
                    (f"RUN_{status}", status, ts),
                )
            conn.commit()
            self.assertEqual(
                int(
                    conn.execute(
                        "SELECT COUNT(*) FROM runs WHERE status IN ('PAUSED', 'SAVED', 'AWAITING_VALIDATION')"
                    ).fetchone()[0]
                ),
                3,
            )

    def test_foreign_keys_re_enabled_after_migration(self) -> None:
        """Apres la migration 025, PRAGMA foreign_keys doit etre re-active."""
        mgr = MigrationManager(self.db_path, _REAL_MIG_DIR)
        mgr.apply()
        with closing(connect_sqlite(str(self.db_path))) as conn:
            # connect_sqlite reactive normalement les FK ; on verifie que le code
            # PRAGMA foreign_keys=ON dans le manager ne casse rien.
            fk_state = int(conn.execute("PRAGMA foreign_keys").fetchone()[0])
            self.assertEqual(fk_state, 1, "FK doivent etre ON apres la migration")


if __name__ == "__main__":
    unittest.main()
