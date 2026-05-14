"""Tests pour le decorateur requires_valid_run_id (issue #101)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from cinesort.ui.api._validators import requires_valid_run_id


class RequiresValidRunIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = MagicMock()

    def test_valid_run_id_calls_wrapped_function(self) -> None:
        self.api._is_valid_run_id.return_value = True
        called = []

        @requires_valid_run_id
        def f(api, run_id):
            called.append(run_id)
            return {"ok": True, "run_id": run_id}

        result = f(self.api, "20260101_120000_001")
        self.assertEqual(result["ok"], True)
        self.assertEqual(called, ["20260101_120000_001"])

    def test_invalid_run_id_returns_error_dict_without_calling_wrapped(self) -> None:
        self.api._is_valid_run_id.return_value = False
        called = []

        @requires_valid_run_id
        def f(api, run_id):
            called.append(run_id)
            return {"ok": True}

        result = f(self.api, "bad-id")
        self.assertFalse(result["ok"])
        self.assertEqual(result["run_id"], "bad-id")
        self.assertIn("message", result)
        self.assertEqual(called, [])

    def test_none_run_id_returns_error(self) -> None:
        self.api._is_valid_run_id.return_value = False

        @requires_valid_run_id
        def f(api, run_id):
            return {"ok": True}

        result = f(self.api, None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["run_id"], "")

    def test_keyword_run_id_works(self) -> None:
        self.api._is_valid_run_id.return_value = True

        @requires_valid_run_id
        def f(api, run_id):
            return {"ok": True, "rid": run_id}

        result = f(self.api, run_id="20260101_120000_001")
        self.assertEqual(result["rid"], "20260101_120000_001")

    def test_extra_args_passed_through(self) -> None:
        self.api._is_valid_run_id.return_value = True

        @requires_valid_run_id
        def f(api, run_id, extra, *, kw):
            return {"run_id": run_id, "extra": extra, "kw": kw}

        result = f(self.api, "20260101_120000_001", "abc", kw="def")
        self.assertEqual(result["extra"], "abc")
        self.assertEqual(result["kw"], "def")

    def test_preserves_function_metadata(self) -> None:
        @requires_valid_run_id
        def my_endpoint(api, run_id):
            """Doc string."""
            return {}

        self.assertEqual(my_endpoint.__name__, "my_endpoint")
        self.assertIn("Doc string", my_endpoint.__doc__ or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
