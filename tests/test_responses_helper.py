"""Tests pour cinesort.ui.api._responses (helper err + ok)."""

from __future__ import annotations

import logging
import unittest

from cinesort.ui.api._responses import KNOWN_CATEGORIES, err, ok


class ErrHelperTests(unittest.TestCase):
    def test_returns_ok_false_with_message(self) -> None:
        r = err("Test message")
        self.assertFalse(r["ok"])
        self.assertEqual(r["message"], "Test message")

    def test_extra_fields_merged(self) -> None:
        r = err("Test", run_id="abc", row_id="42")
        self.assertEqual(r["run_id"], "abc")
        self.assertEqual(r["row_id"], "42")

    def test_logs_at_specified_level(self) -> None:
        with self.assertLogs("cinesort.ui.api", level="WARNING") as captured:
            err("Test warning", category="validation", level="warning")
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].levelname, "WARNING")
        self.assertIn("validation", captured.records[0].getMessage())
        self.assertIn("Test warning", captured.records[0].getMessage())

    def test_unknown_level_falls_back_to_warning(self) -> None:
        with self.assertLogs("cinesort.ui.api", level="WARNING") as captured:
            err("Test", level="invalid_level")
        self.assertEqual(captured.records[0].levelname, "WARNING")

    def test_custom_log_module(self) -> None:
        with self.assertLogs("cinesort.custom", level="INFO") as captured:
            err("Test", level="info", log_module="cinesort.custom")
        self.assertEqual(captured.records[0].name, "cinesort.custom")

    def test_known_categories_documented(self) -> None:
        # Sanity check : les categories conventionnelles sont presentes
        self.assertIn("validation", KNOWN_CATEGORIES)
        self.assertIn("state", KNOWN_CATEGORIES)
        self.assertIn("resource", KNOWN_CATEGORIES)
        self.assertIn("runtime", KNOWN_CATEGORIES)

    def test_custom_key_replaces_message(self) -> None:
        # Endpoints historiques (demo/reset/log_dir) renvoient "error" au lieu
        # de "message" — le parametre `key` evite de casser leur contrat JSON.
        r = err("boom", key="error")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "boom")
        self.assertNotIn("message", r)

    def test_custom_key_with_extra(self) -> None:
        r = err("not found", key="error", log_dir="/tmp/x")
        self.assertEqual(r["error"], "not found")
        self.assertEqual(r["log_dir"], "/tmp/x")


class OkHelperTests(unittest.TestCase):
    def test_returns_ok_true_with_fields(self) -> None:
        r = ok(run_id="xyz", count=42)
        self.assertTrue(r["ok"])
        self.assertEqual(r["run_id"], "xyz")
        self.assertEqual(r["count"], 42)

    def test_ok_does_not_log(self) -> None:
        # Pas de log sur le happy path
        logger = logging.getLogger("cinesort.ui.api")
        handler_count_before = len(logger.handlers)
        ok(data="x")
        self.assertEqual(len(logger.handlers), handler_count_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
