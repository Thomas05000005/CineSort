"""VO-A-NAS -- tests nas_validation.py.

Couvre :
  * ``db_local_guard`` refuse les chemins UNC par defaut (fail-closed).
  * ``db_local_guard`` accepte les chemins UNC avec ``allow_unc=True``.
  * ``db_local_guard`` accepte les chemins UNC si ``CINESORT_ALLOW_UNC_DB=1``.
  * ``db_local_guard`` no-op sur chemin local.
  * ``run_nas_benchmark`` renvoie la structure attendue (toutes les cles
    percentiles + WAL + duration).
  * ``run_nas_benchmark`` ne laisse pas la table bench dans la DB (DROP
    garanti).
  * ``write_benchmark_report`` ecrit un JSON serialisable et cree
    ``diagnostics/`` si absent.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.infra.db.nas_validation import (
    db_local_guard,
    run_nas_benchmark,
    write_benchmark_report,
)


class DbLocalGuardTests(unittest.TestCase):
    """Garde fail-closed : refus UNC sauf override explicite."""

    def setUp(self):
        # Nettoyer l'env var pour eviter qu'un test precedent ne fasse leak.
        self._env_backup = os.environ.pop("CINESORT_ALLOW_UNC_DB", None)

    def tearDown(self):
        if self._env_backup is not None:
            os.environ["CINESORT_ALLOW_UNC_DB"] = self._env_backup
        else:
            os.environ.pop("CINESORT_ALLOW_UNC_DB", None)

    def test_unc_path_refused_by_default(self):
        """Chemin UNC sans override : doit lever RuntimeError."""
        unc_path = Path("\\\\nas01\\films\\cinesort\\db\\data.db")
        with self.assertRaises(RuntimeError) as cm:
            db_local_guard(unc_path)
        msg = str(cm.exception)
        self.assertIn("UNC", msg.upper())
        # Le message doit etre actionnable : mentionner la variable env de
        # bypass.
        self.assertIn("CINESORT_ALLOW_UNC_DB", msg)

    def test_unc_path_accepted_with_allow_unc_true(self):
        """Chemin UNC + allow_unc=True : pas d'exception."""
        unc_path = Path("\\\\nas01\\films\\cinesort\\db\\data.db")
        # Ne doit PAS lever.
        db_local_guard(unc_path, allow_unc=True)

    def test_unc_path_accepted_via_env_var(self):
        """Chemin UNC + env var CINESORT_ALLOW_UNC_DB=1 : pas d'exception."""
        os.environ["CINESORT_ALLOW_UNC_DB"] = "1"
        try:
            unc_path = Path("\\\\nas01\\films\\cinesort\\db\\data.db")
            db_local_guard(unc_path)  # ne doit PAS lever
        finally:
            os.environ.pop("CINESORT_ALLOW_UNC_DB", None)

    def test_unc_path_env_var_truthy_variants(self):
        """L'env var doit accepter 1/true/yes/on (case-insensitive)."""
        unc_path = Path("\\\\nas01\\films\\cinesort\\db\\data.db")
        for value in ("1", "true", "TRUE", "yes", "Yes", "on", "ON"):
            with self.subTest(value=value):
                os.environ["CINESORT_ALLOW_UNC_DB"] = value
                try:
                    db_local_guard(unc_path)  # ne doit PAS lever
                finally:
                    os.environ.pop("CINESORT_ALLOW_UNC_DB", None)

    def test_unc_path_env_var_falsy_still_refuses(self):
        """L'env var avec valeur falsy ne doit PAS suffire."""
        unc_path = Path("\\\\nas01\\films\\cinesort\\db\\data.db")
        for value in ("0", "false", "no", "off", ""):
            with self.subTest(value=value):
                os.environ["CINESORT_ALLOW_UNC_DB"] = value
                try:
                    with self.assertRaises(RuntimeError):
                        db_local_guard(unc_path)
                finally:
                    os.environ.pop("CINESORT_ALLOW_UNC_DB", None)

    def test_local_path_no_op(self):
        """Chemin local : doit retourner silencieusement."""
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "db" / "data.db"
            db_local_guard(local_path)  # ne doit PAS lever

    def test_unc_long_path_variant_refused(self):
        # Variante long-path Windows backslash-backslash-?-backslash-UNC...
        # egalement refusee.
        unc_path = Path("\\\\?\\UNC\\nas01\\films\\db\\data.db")
        with self.assertRaises(RuntimeError):
            db_local_guard(unc_path)


class RunNasBenchmarkTests(unittest.TestCase):
    """Benchmark doit retourner la structure complete + ne pas polluer la DB."""

    EXPECTED_KEYS = {
        "ok",
        "db_path",
        "n_writes",
        "n_reads",
        "p50_write_ms",
        "p95_write_ms",
        "p99_write_ms",
        "p50_read_ms",
        "p95_read_ms",
        "p99_read_ms",
        "wal_growth_kb",
        "checkpoint_count",
        "total_duration_s",
        "started_at",
        "finished_at",
    }

    def test_benchmark_returns_complete_structure(self):
        """Le dict resultat doit contenir toutes les cles documentees."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bench.db"
            # Pre-create la DB pour que le bench mesure une situation realiste.
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE existing (id INTEGER PRIMARY KEY)")
            conn.commit()
            conn.close()

            # Petit volume pour rester rapide.
            result = run_nas_benchmark(db_path, n_writes=50, n_reads=200)

            missing = self.EXPECTED_KEYS - set(result.keys())
            self.assertFalse(
                missing, f"Cles manquantes dans le resultat : {missing}"
            )
            self.assertTrue(result["ok"], f"ok=False : {result.get('error')}")
            self.assertEqual(result["n_writes"], 50)
            self.assertEqual(result["n_reads"], 200)
            self.assertGreaterEqual(result["p50_write_ms"], 0.0)
            self.assertGreaterEqual(result["p95_write_ms"], result["p50_write_ms"])
            self.assertGreaterEqual(result["p99_write_ms"], result["p95_write_ms"])
            self.assertGreaterEqual(result["p50_read_ms"], 0.0)
            self.assertGreaterEqual(result["p95_read_ms"], result["p50_read_ms"])
            self.assertGreaterEqual(result["p99_read_ms"], result["p95_read_ms"])
            self.assertGreaterEqual(result["total_duration_s"], 0.0)
            # started_at / finished_at doivent etre ISO-8601 UTC.
            self.assertTrue(
                result["started_at"].endswith("Z"),
                f"started_at doit etre UTC ISO-8601 : {result['started_at']}",
            )
            self.assertTrue(
                result["finished_at"].endswith("Z"),
                f"finished_at doit etre UTC ISO-8601 : {result['finished_at']}",
            )

    def test_benchmark_drops_temp_table(self):
        """La table bench doit etre DROP a la fin (non destructif)."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bench.db"
            result = run_nas_benchmark(db_path, n_writes=10, n_reads=20)
            self.assertTrue(result["ok"])

            # Inspecter le schema apres bench : aucune table residuelle.
            conn = sqlite3.connect(str(db_path))
            try:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name LIKE '__cinesort_nas_bench_%'"
                ).fetchall()
                self.assertEqual(
                    rows,
                    [],
                    f"Table bench residuelle apres run : {rows}",
                )
            finally:
                conn.close()

    def test_benchmark_result_is_json_serializable(self):
        """Le dict resultat doit etre json.dumps-able sans custom encoder."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bench.db"
            result = run_nas_benchmark(db_path, n_writes=10, n_reads=20)
            # Doit pas lever.
            payload = json.dumps(result)
            self.assertIn("p95_write_ms", payload)

    def test_benchmark_handles_existing_db(self):
        """Bench sur une DB pre-existante (memoire user M-00) doit fonctionner."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "preexisting.db"
            # Simuler un schema deja en place (ordre CREATE TABLE -> CREATE INDEX,
            # pas d'ALTER TABLE -- conforme memoire utilisateur).
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE films (id INTEGER PRIMARY KEY, title TEXT NOT NULL)"
            )
            conn.execute("CREATE INDEX idx_films_title ON films(title)")
            conn.execute("INSERT INTO films (id, title) VALUES (1, 'Inception')")
            conn.commit()
            conn.close()

            result = run_nas_benchmark(db_path, n_writes=20, n_reads=50)
            self.assertTrue(result["ok"])

            # La table d'origine doit etre intacte apres bench.
            conn = sqlite3.connect(str(db_path))
            try:
                row = conn.execute(
                    "SELECT title FROM films WHERE id = 1"
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "Inception")
            finally:
                conn.close()


class WriteBenchmarkReportTests(unittest.TestCase):
    """write_benchmark_report doit creer diagnostics/ + ecrire JSON valide."""

    def test_report_written_to_diagnostics_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            result = {
                "ok": True,
                "db_path": str(state_dir / "db" / "data.db"),
                "n_writes": 100,
                "n_reads": 1000,
                "p50_write_ms": 1.23,
                "p95_write_ms": 5.67,
                "p99_write_ms": 10.42,
                "p50_read_ms": 0.42,
                "p95_read_ms": 1.11,
                "p99_read_ms": 2.22,
                "wal_growth_kb": 42.0,
                "checkpoint_count": 1,
                "total_duration_s": 1.5,
                "started_at": "2026-06-01T00:00:00Z",
                "finished_at": "2026-06-01T00:00:01Z",
            }
            out_path = write_benchmark_report(result, state_dir)
            self.assertTrue(out_path.exists())
            self.assertEqual(out_path.parent.name, "diagnostics")
            self.assertTrue(out_path.name.startswith("nas_benchmark_"))
            self.assertTrue(out_path.name.endswith(".json"))

            # Le contenu doit etre du JSON parseable, conservant les cles.
            data = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(data["p95_write_ms"], 5.67)
            self.assertEqual(data["n_writes"], 100)

    def test_report_creates_diagnostics_dir_if_missing(self):
        """Si state_dir/diagnostics n'existe pas, il doit etre cree."""
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "nested" / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            self.assertFalse((state_dir / "diagnostics").exists())

            result = {
                "ok": True,
                "db_path": "x",
                "n_writes": 1,
                "n_reads": 1,
                "p50_write_ms": 0.0,
                "p95_write_ms": 0.0,
                "p99_write_ms": 0.0,
                "p50_read_ms": 0.0,
                "p95_read_ms": 0.0,
                "p99_read_ms": 0.0,
                "wal_growth_kb": 0.0,
                "checkpoint_count": 0,
                "total_duration_s": 0.0,
                "started_at": "2026-06-01T00:00:00Z",
                "finished_at": "2026-06-01T00:00:00Z",
            }
            out_path = write_benchmark_report(result, state_dir)
            self.assertTrue((state_dir / "diagnostics").is_dir())
            self.assertTrue(out_path.exists())


if __name__ == "__main__":
    unittest.main()
