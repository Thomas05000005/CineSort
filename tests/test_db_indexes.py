"""Audit perf 2026-05-01 — verifie que les indexes 020 sont crees et utilises."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.infra.db.sqlite_store import SQLiteStore


class QualityReportsIndexesTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.mkdtemp()
        self.db = Path(tmp) / "t.db"
        SQLiteStore(self.db).initialize()
        self.conn = sqlite3.connect(self.db)

    def tearDown(self) -> None:
        self.conn.close()

    def _list_indexes(self) -> list[str]:
        return [r[1] for r in self.conn.execute("PRAGMA index_list(quality_reports)").fetchall()]

    def test_idx_tier_exists(self) -> None:
        self.assertIn("idx_quality_reports_tier", self._list_indexes())

    def test_idx_score_exists(self) -> None:
        self.assertIn("idx_quality_reports_score", self._list_indexes())

    def test_schema_version_at_least_20(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertGreaterEqual(int(version), 20)

    def _seed(self, n: int = 100) -> None:
        tiers = ["gold", "silver", "bronze"]
        for i in range(n):
            self.conn.execute(
                "INSERT INTO quality_reports "
                "(run_id, row_id, score, tier, reasons_json, metrics_json, profile_id, profile_version, ts) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (f"r{i // 10}", f"row_{i}", i, tiers[i % 3], "[]", "{}", "default", 1, time.time()),
            )
        self.conn.commit()

    def test_group_by_tier_uses_index(self) -> None:
        self._seed()
        plan = self.conn.execute(
            "EXPLAIN QUERY PLAN SELECT tier, COUNT(*) FROM quality_reports GROUP BY tier"
        ).fetchall()
        plan_text = " ".join(str(r) for r in plan).lower()
        self.assertIn("idx_quality_reports_tier", plan_text)

    def test_order_by_score_uses_index(self) -> None:
        self._seed()
        plan = self.conn.execute(
            "EXPLAIN QUERY PLAN SELECT row_id FROM quality_reports ORDER BY score DESC LIMIT 10"
        ).fetchall()
        plan_text = " ".join(str(r) for r in plan).lower()
        self.assertIn("idx_quality_reports_score", plan_text)


if __name__ == "__main__":
    unittest.main()
