"""GATE AUDIT 2026-06-14 (R7-13) — preset playlist "DNR partiel" applique son filtre.

_applyPlaylist avait une boucle filters.warnings VIDE et _buildFilters n'emettait
jamais warnings -> le POST partait sans filtre (toast succes, grille non filtree).
Le backend filtre par filters.warnings (library_support.py:678).
"""

from __future__ import annotations

import unittest
from pathlib import Path

_BIB = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "bibliotheque.js"
_LIB = Path(__file__).resolve().parents[1] / "cinesort" / "ui" / "api" / "library_support.py"


class PlaylistWarningsFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = _BIB.read_text(encoding="utf-8")
        cls.lib = _LIB.read_text(encoding="utf-8")

    def test_backend_filters_by_warnings(self):
        self.assertIn('filters.get("warnings")', self.lib)

    def test_apply_stores_warnings(self):
        self.assertIn("_state.playlistWarnings = Array.isArray(filters.warnings)", self.js)

    def test_buildfilters_emits_warnings(self):
        self.assertIn("filters.warnings = _state.playlistWarnings.slice()", self.js)

    def test_reset_clears_warnings(self):
        self.assertIn("_state.playlistWarnings = []; // R7-13", self.js)


if __name__ == "__main__":
    unittest.main()
