"""Tests pour le decorateur boundary (audit B1)."""

from __future__ import annotations

import logging
import unittest

from cinesort.infra.errors import boundary


class BoundaryDecoratorTests(unittest.TestCase):
    def test_passes_through_on_success(self) -> None:
        @boundary(log_name="test.unit.success", default="fallback")
        def normal() -> str:
            return "ok"

        self.assertEqual(normal(), "ok")

    def test_returns_default_on_exception(self) -> None:
        @boundary(log_name="test.unit.fail", default={"ok": False, "message": "generic"})
        def raises() -> None:
            raise ValueError("should be swallowed")

        self.assertEqual(raises(), {"ok": False, "message": "generic"})

    def test_logs_exception_with_trace(self) -> None:
        with self.assertLogs("test.unit.logs", level=logging.ERROR) as cm:

            @boundary(log_name="test.unit.logs", default=None)
            def raises() -> None:
                raise RuntimeError("boom")

            raises()

        # `logger.exception` produit le message + le traceback
        self.assertTrue(any("boundary[test.unit.logs]" in line for line in cm.output))

    def test_preserves_wrapped_metadata(self) -> None:
        @boundary(log_name="test.unit.meta", default=None)
        def my_function_with_specific_name(x: int) -> int:
            """docstring specifique."""
            return x * 2

        self.assertEqual(my_function_with_specific_name.__name__, "my_function_with_specific_name")
        self.assertEqual(my_function_with_specific_name.__doc__, "docstring specifique.")

    def test_does_not_catch_system_exit(self) -> None:
        """Le boundary ne doit pas avaler SystemExit ou KeyboardInterrupt."""

        @boundary(log_name="test.unit.sysexit", default="swallowed")
        def raises() -> None:
            raise SystemExit(1)

        with self.assertRaises(SystemExit):
            raises()

    def test_reraise_still_logs(self) -> None:
        with self.assertLogs("test.unit.reraise", level=logging.ERROR):

            @boundary(log_name="test.unit.reraise", default=None, reraise=True)
            def raises() -> None:
                raise ValueError("boom")

            with self.assertRaises(ValueError):
                raises()

    def test_typed_exception_in_fn_handled_first(self) -> None:
        """Si la fonction attrape elle-meme une exception typee, boundary ne la voit pas."""

        @boundary(log_name="test.unit.typed", default="boundary-fallback")
        def handles_value_error() -> str:
            try:
                raise ValueError("inner")
            except ValueError:
                return "handled-in-fn"

        self.assertEqual(handles_value_error(), "handled-in-fn")


class BoundaryIntegrationHintTests(unittest.TestCase):
    """Verifie que le module est importable et exporte boundary comme API publique."""

    def test_boundary_is_exported(self) -> None:
        import cinesort.infra.errors as errors_mod

        self.assertIn("boundary", errors_mod.__all__)
        self.assertTrue(callable(errors_mod.boundary))

    def test_callable_without_arguments_raises_type_error(self) -> None:
        """boundary sans log_name doit echouer (kwarg obligatoire)."""
        with self.assertRaises(TypeError):
            boundary()  # type: ignore[call-arg]


if __name__ == "__main__":
    unittest.main(verbosity=2)
