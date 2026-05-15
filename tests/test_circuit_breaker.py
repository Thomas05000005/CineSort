"""Tests pour cinesort.infra._circuit_breaker (issue #76)."""

from __future__ import annotations

import threading
import time
import unittest
from unittest import mock

from cinesort.infra._circuit_breaker import CircuitBreaker, CircuitOpenError


class _Boom(Exception):
    """Exception arbitraire utilisee pour simuler un echec HTTP."""


class CircuitBreakerBasicTests(unittest.TestCase):
    def test_passes_calls_when_closed(self) -> None:
        b = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        self.assertFalse(b.is_open)
        self.assertEqual(b.call(lambda: "ok"), "ok")
        self.assertEqual(b.failures, 0)

    def test_increments_failures_on_exception(self) -> None:
        b = CircuitBreaker(failure_threshold=5, recovery_timeout=1.0)
        for i in range(3):
            with self.assertRaises(_Boom):
                b.call(lambda: (_ for _ in ()).throw(_Boom("nope")))
            self.assertEqual(b.failures, i + 1)
        self.assertFalse(b.is_open)

    def test_resets_failures_on_success(self) -> None:
        b = CircuitBreaker(failure_threshold=5, recovery_timeout=1.0)
        with self.assertRaises(_Boom):
            b.call(lambda: (_ for _ in ()).throw(_Boom("nope")))
        self.assertEqual(b.failures, 1)
        b.call(lambda: "ok")
        self.assertEqual(b.failures, 0)


class CircuitBreakerOpenTests(unittest.TestCase):
    def test_opens_after_threshold_consecutive_failures(self) -> None:
        b = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        for _ in range(3):
            with self.assertRaises(_Boom):
                b.call(lambda: (_ for _ in ()).throw(_Boom("nope")))
        self.assertTrue(b.is_open)

    def test_open_circuit_raises_without_calling_fn(self) -> None:
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(2):
            with self.assertRaises(_Boom):
                b.call(lambda: (_ for _ in ()).throw(_Boom("nope")))
        # circuit ouvert : fn ne doit PAS etre appele
        fn = mock.Mock(return_value="should not call")
        with self.assertRaises(CircuitOpenError):
            b.call(fn)
        fn.assert_not_called()

    def test_open_circuit_message_mentions_remaining_time(self) -> None:
        b = CircuitBreaker(failure_threshold=1, recovery_timeout=300.0)
        with self.assertRaises(_Boom):
            b.call(lambda: (_ for _ in ()).throw(_Boom("down")))
        with self.assertRaises(CircuitOpenError) as ctx:
            b.call(lambda: "ok")
        msg = str(ctx.exception)
        self.assertIn("Circuit ouvert", msg)
        self.assertIn("retry", msg.lower())

    def test_closes_after_recovery_timeout(self) -> None:
        b = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        with self.assertRaises(_Boom):
            b.call(lambda: (_ for _ in ()).throw(_Boom("down")))
        self.assertTrue(b.is_open)
        time.sleep(0.08)
        self.assertFalse(b.is_open)
        # un appel apres timeout doit etre tente
        self.assertEqual(b.call(lambda: "back"), "back")


class CircuitBreakerThreadSafetyTests(unittest.TestCase):
    def test_concurrent_failures_count_correctly(self) -> None:
        """50 threads font 1 echec chacun -> compteur final = 50."""
        b = CircuitBreaker(failure_threshold=1000, recovery_timeout=10.0)
        n = 50

        def boom() -> None:
            try:
                b.call(lambda: (_ for _ in ()).throw(_Boom("nope")))
            except _Boom:
                pass

        threads = [threading.Thread(target=boom) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(b.failures, n)


class CircuitBreakerControlTests(unittest.TestCase):
    def test_reset_clears_failures_and_closes(self) -> None:
        b = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
        with self.assertRaises(_Boom):
            b.call(lambda: (_ for _ in ()).throw(_Boom("down")))
        self.assertTrue(b.is_open)
        b.reset()
        self.assertFalse(b.is_open)
        self.assertEqual(b.failures, 0)

    def test_rejects_invalid_threshold(self) -> None:
        with self.assertRaises(ValueError):
            CircuitBreaker(failure_threshold=0)

    def test_rejects_negative_recovery_timeout(self) -> None:
        with self.assertRaises(ValueError):
            CircuitBreaker(recovery_timeout=-1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
