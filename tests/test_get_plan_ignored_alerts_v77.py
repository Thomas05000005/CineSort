# -*- coding: utf-8 -*-
"""E2-bis (revue Lot E, verif totale 2026-07) : run/get_plan filtre les
alertes ignorees.

Avant : seul get_film_full filtrait warning_flags par ignored_alerts — le
bouton Ignorer de la vue Traitement persistait bien en DB mais l'alerte
re-apparaissait a chaque reload du plan (aucun effet visible).
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api.history_support import _subtract_ignored_flags


class ListIgnoredAlertsBulkTests(unittest.TestCase):
    def test_bulk_returns_codes_grouped_by_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "t.sqlite")
            store.film_modal.insert_ignored_alert("r1", "year_missing")
            store.film_modal.insert_ignored_alert("r1", "low_confidence")
            store.film_modal.insert_ignored_alert("r2", "year_missing")
            out = store.film_modal.list_ignored_alerts_bulk(["r1", "r2", "r3"])
            self.assertEqual(sorted(out["r1"]), ["low_confidence", "year_missing"])
            self.assertEqual(out["r2"], ["year_missing"])
            self.assertNotIn("r3", out)

    def test_bulk_empty_and_invalid_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "t.sqlite")
            self.assertEqual(store.film_modal.list_ignored_alerts_bulk([]), {})
            self.assertEqual(store.film_modal.list_ignored_alerts_bulk(["", None]), {})

    def test_bulk_chunking_over_500(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "t.sqlite")
            store.film_modal.insert_ignored_alert("r0", "c0")
            store.film_modal.insert_ignored_alert("r750", "c750")
            ids = [f"r{i}" for i in range(800)]
            out = store.film_modal.list_ignored_alerts_bulk(ids)
            self.assertEqual(out, {"r0": ["c0"], "r750": ["c750"]})


class SubtractIgnoredFlagsTests(unittest.TestCase):
    def _rows(self):
        return [
            {"row_id": "r1", "warning_flags": ["year_missing", "low_confidence"]},
            {"row_id": "r2", "warning_flags": ["year_missing"]},
        ]

    def test_ignored_flags_removed_from_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "t.sqlite")
            store.film_modal.insert_ignored_alert("r1", "year_missing")
            with patch("cinesort.ui.api.library_support._get_store", return_value=store):
                rows = _subtract_ignored_flags(object(), self._rows())
        self.assertEqual(rows[0]["warning_flags"], ["low_confidence"])
        self.assertEqual(rows[1]["warning_flags"], ["year_missing"])

    def test_store_unavailable_keeps_raw_flags(self):
        with patch("cinesort.ui.api.library_support._get_store", return_value=None):
            rows = _subtract_ignored_flags(object(), self._rows())
        self.assertEqual(rows[0]["warning_flags"], ["year_missing", "low_confidence"])

    def test_sqlite_error_keeps_raw_flags_best_effort(self):
        # R2 (revue Lot E round 2) : un 'database is locked' pendant un apply
        # concurrent ne doit PAS faire echouer get_plan — flags bruts servis.
        import sqlite3
        from unittest.mock import MagicMock

        store = MagicMock()
        store.film_modal.list_ignored_alerts_bulk.side_effect = sqlite3.OperationalError("database is locked")
        with patch("cinesort.ui.api.library_support._get_store", return_value=store):
            rows = _subtract_ignored_flags(object(), self._rows())
        self.assertEqual(rows[0]["warning_flags"], ["year_missing", "low_confidence"])
        self.assertEqual(rows[1]["warning_flags"], ["year_missing"])


if __name__ == "__main__":
    unittest.main()
