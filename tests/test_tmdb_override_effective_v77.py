"""GATE AUDIT 2026-06-14 (R7-3) — l'override TMDb manuel devient effectif.

set_film_tmdb_candidate persiste le choix dans film_tmdb_overrides mais aucun
consommateur de prod ne la lisait : biblio, fiche film et apply retombaient sur
le match auto (choix perdu au reload, rename avec l'ancien match). overlay_tmdb_
override applique l'override sur une row ; il est appele dans _build_library_rows,
get_film_full et la boucle apply (apply_support).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api.film_support import overlay_tmdb_override

_ROOT = Path(__file__).resolve().parents[1]


class TmdbOverrideEffectiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="ovr_")
        self.store = SQLiteStore(Path(self._tmp) / "t.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_overlay_applies_override(self) -> None:
        self.store.film_modal.upsert_tmdb_override(
            run_id="R1", row_id="r1", tmdb_id=999, new_confidence=88,
            proposed_title="Chosen Title", proposed_year=2021,
        )
        row = {"row_id": "r1", "tmdb_id": 111, "proposed_title": "Auto", "proposed_year": 1999, "confidence": 50}
        self.assertTrue(overlay_tmdb_override(self.store, "R1", row))
        self.assertEqual(row["tmdb_id"], 999)
        self.assertEqual(row["chosen_tmdb_id"], 999)
        self.assertEqual(row["proposed_title"], "Chosen Title")
        self.assertEqual(row["proposed_year"], 2021)
        self.assertEqual(row["confidence"], 88)

    def test_no_override_is_noop(self) -> None:
        row = {"row_id": "rX", "tmdb_id": 111, "proposed_title": "Auto"}
        self.assertFalse(overlay_tmdb_override(self.store, "R1", row))
        self.assertEqual(row["tmdb_id"], 111)
        self.assertEqual(row["proposed_title"], "Auto")

    def test_consumers_call_overlay(self) -> None:
        apply_src = (_ROOT / "cinesort" / "ui" / "api" / "apply_support.py").read_text(encoding="utf-8")
        lib_src = (_ROOT / "cinesort" / "ui" / "api" / "library_support.py").read_text(encoding="utf-8")
        film_src = (_ROOT / "cinesort" / "ui" / "api" / "film_support.py").read_text(encoding="utf-8")
        self.assertIn("get_tmdb_override(run_id=run_id, row_id=_rid_row)", apply_src)
        self.assertIn("overlay_tmdb_override(store, run_id, _r)", lib_src)
        self.assertIn("overlay_tmdb_override(store, resolved_rid, row)", film_src)


if __name__ == "__main__":
    unittest.main()
