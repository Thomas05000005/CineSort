"""Vague H audit v1.5.3 — tests du RepeatedExceptionDedupFilter.

Verifie que le filter rate-limite les exceptions repetees (max N par minute),
sans bloquer les LogRecord sans exc_info, et qu'il differencie les exception
types.
"""

from __future__ import annotations

import logging
import unittest

from cinesort.infra.log_context import (
    RepeatedExceptionDedupFilter,
    install_repeated_exception_dedup,
    reset_for_tests,
)


def _make_record(name: str, msg: str, exc: Exception | None) -> logging.LogRecord:
    """Construit un LogRecord avec exc_info reel (sys.exc_info-like tuple)."""
    if exc is not None:
        exc_info = (type(exc), exc, exc.__traceback__)
    else:
        exc_info = None
    return logging.LogRecord(
        name=name,
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,  # type: ignore[arg-type]
    )


class RepeatedExceptionDedupFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_for_tests()

    def tearDown(self) -> None:
        reset_for_tests()

    def test_dedup_filter_blocks_after_max(self) -> None:
        """10x meme exception -> 5 passent (max=5), 5 sont bloques."""
        flt = RepeatedExceptionDedupFilter(max_per_minute=5)
        exc = ValueError("boom")
        passed = 0
        blocked = 0
        for _ in range(10):
            rec = _make_record("cinesort.test", "operation echec %s", exc)
            if flt.filter(rec):
                passed += 1
            else:
                blocked += 1
        self.assertEqual(passed, 5)
        self.assertEqual(blocked, 5)

    def test_dedup_filter_lets_records_without_exc_info_pass(self) -> None:
        """Les records sans exc_info passent toujours (le filter n'enrichit pas)."""
        flt = RepeatedExceptionDedupFilter(max_per_minute=2)
        for _ in range(20):
            rec = _make_record("cinesort.test", "info message", None)
            self.assertTrue(flt.filter(rec))

    def test_dedup_filter_differentiates_exception_types(self) -> None:
        """Deux types d'exception differents -> compteurs separes."""
        flt = RepeatedExceptionDedupFilter(max_per_minute=2)
        exc_a = ValueError("a")
        exc_b = OSError("b")
        # 2 ValueError -> ok, 3eme bloque
        self.assertTrue(flt.filter(_make_record("cs", "msg", exc_a)))
        self.assertTrue(flt.filter(_make_record("cs", "msg", exc_a)))
        self.assertFalse(flt.filter(_make_record("cs", "msg", exc_a)))
        # OSError independant : 2 passent
        self.assertTrue(flt.filter(_make_record("cs", "msg", exc_b)))
        self.assertTrue(flt.filter(_make_record("cs", "msg", exc_b)))
        self.assertFalse(flt.filter(_make_record("cs", "msg", exc_b)))

    def test_dedup_filter_differentiates_logger_names(self) -> None:
        """Deux loggers differents -> compteurs separes meme si meme exception."""
        flt = RepeatedExceptionDedupFilter(max_per_minute=1)
        exc = RuntimeError("x")
        self.assertTrue(flt.filter(_make_record("cs.a", "msg", exc)))
        self.assertFalse(flt.filter(_make_record("cs.a", "msg", exc)))
        # autre logger -> ok
        self.assertTrue(flt.filter(_make_record("cs.b", "msg", exc)))

    def test_install_repeated_exception_dedup_idempotent(self) -> None:
        """install_repeated_exception_dedup attache un filter une seule fois."""
        root = logging.getLogger()
        before = sum(isinstance(f, RepeatedExceptionDedupFilter) for f in root.filters)
        try:
            install_repeated_exception_dedup(max_per_minute=3)
            install_repeated_exception_dedup(max_per_minute=3)
            install_repeated_exception_dedup(max_per_minute=3)
            after = sum(isinstance(f, RepeatedExceptionDedupFilter) for f in root.filters)
            self.assertEqual(after - before, 1)
        finally:
            # cleanup : retirer tous les filters installes pour ne pas polluer
            # les autres tests qui partagent le root logger
            for f in list(root.filters):
                if isinstance(f, RepeatedExceptionDedupFilter):
                    root.removeFilter(f)
            reset_for_tests()


if __name__ == "__main__":
    unittest.main()
