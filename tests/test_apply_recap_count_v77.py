"""GATE AUDIT 2026-06-14 (R7-14) — recap Apply compte les vraies operations.

run/apply renvoie {ok, result: ApplyResult.__dict__, apply_batch_id} ; le front
lisait res.data.done (inexistant) -> "0 operation" systematique. Il somme
desormais renames+moves+collection_moves.
"""
from __future__ import annotations
import unittest
from pathlib import Path

_PROC = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "processing.js"
_APPLY = Path(__file__).resolve().parents[1] / "cinesort" / "ui" / "api" / "apply_support.py"


class ApplyRecapCountTests(unittest.TestCase):
    def test_backend_returns_result_dict(self):
        self.assertIn('"result": result.__dict__', _APPLY.read_text(encoding="utf-8"))

    def test_front_sums_real_ops(self):
        js = _PROC.read_text(encoding="utf-8")
        self.assertIn("res.data?.result || {}", js)
        self.assertIn("r.renames", js)
        self.assertIn("r.collection_moves", js)
        self.assertNotIn("res.data?.done || 0", js)


if __name__ == "__main__":
    unittest.main()
