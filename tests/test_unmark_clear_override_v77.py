"""GATE AUDIT 2026-06-14 (R7-12) — annulation marquage suppression / override TMDb.

Les methodes repo unmark_for_deletion / clear_tmdb_override existaient sans aucun
appelant (reversibilite promise mais impossible). Wiring complet : library_support
+ impl cinesort_api + LibraryFacade + flags get_film_full + boutons/handlers UI.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_LIB = _ROOT / "cinesort/ui/api/library_support.py"
_API = _ROOT / "cinesort/ui/api/cinesort_api.py"
_FAC = _ROOT / "cinesort/ui/api/facades/library_facade.py"
_FILMPY = _ROOT / "cinesort/ui/api/film_support.py"
_FILMJS = _ROOT / "web/dashboard/components/film-detail.js"


class UnmarkClearOverrideTests(unittest.TestCase):
    def test_library_support_functions(self):
        s = _LIB.read_text(encoding="utf-8")
        self.assertIn("def clear_tmdb_override(api", s)
        self.assertIn("def unmark_for_deletion(api", s)
        self.assertIn("store.film_modal.clear_tmdb_override(", s)
        self.assertIn("store.film_modal.unmark_for_deletion(", s)

    def test_impl_and_facade(self):
        self.assertIn("def _clear_tmdb_override_impl", _API.read_text(encoding="utf-8"))
        self.assertIn("def _unmark_for_deletion_impl", _API.read_text(encoding="utf-8"))
        fac = _FAC.read_text(encoding="utf-8")
        self.assertIn("def clear_tmdb_override(self", fac)
        self.assertIn("def unmark_for_deletion(self", fac)

    def test_get_film_full_flags(self):
        s = _FILMPY.read_text(encoding="utf-8")
        self.assertIn('"has_tmdb_override": _has_override', s)
        self.assertIn('"is_marked_for_deletion": _is_marked', s)

    def test_ui_buttons_and_handlers(self):
        js = _FILMJS.read_text(encoding="utf-8")
        self.assertIn('data-film-action="clear-override"', js)
        self.assertIn('data-film-action="unmark-delete"', js)
        self.assertIn('apiPost("library/clear_tmdb_override"', js)
        self.assertIn('apiPost("library/unmark_for_deletion"', js)


if __name__ == "__main__":
    unittest.main()
