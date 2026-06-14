"""GATE AUDIT 2026-06-14 (R7-11) — recalcul scores compte les echecs metier.

Le worker incrementait processed meme en cas d'echec (status='done') et
get_quality_report renvoie {ok:False} sans lever -> errors restait 0, toast vert
"N/N re-calcules" meme quand tous les films echouaient. Backend compte
{ok:False} ; front lit data.errors et choisit error/warn/success.
"""
from __future__ import annotations
import unittest
from pathlib import Path

_QA = Path(__file__).resolve().parents[1] / "cinesort" / "ui" / "api" / "quality_audit_support.py"
_QJS = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "qualite.js"


class RecomputeErrorsTests(unittest.TestCase):
    def test_backend_counts_ok_false(self):
        src = _QA.read_text(encoding="utf-8")
        self.assertIn('res.get("ok") is False', src)

    def test_front_uses_errors(self):
        js = _QJS.read_text(encoding="utf-8")
        self.assertIn("Number(data.errors || 0)", js)
        self.assertIn("en échec", js)


if __name__ == "__main__":
    unittest.main()
