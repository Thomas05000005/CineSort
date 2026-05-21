"""Tests pour cinesort.infra._circuit_breaker (issue #76).

Audit C5 P1 (B1) : le breaker ne doit s'ouvrir QUE sur des echecs reseau
ou serveur (ConnectionError, Timeout, HTTPError 5xx/429). Les erreurs
applicatives (ValueError, JSONDecodeError, KeyError, TypeError,
HTTPError 4xx) ne signalent PAS que le service est en panne — elles
sont remontees au caller telle quelles sans toucher au compteur.
"""

from __future__ import annotations

import json
import threading
import time
import unittest
from unittest import mock

import requests
from requests.exceptions import ConnectionError as ReqConnectionError
from requests.exceptions import HTTPError, Timeout

from cinesort.infra._circuit_breaker import CircuitBreaker, CircuitOpenError


def _raise(exc: BaseException):
    """Helper : retourne un lambda qui leve `exc` quand appele."""

    def _fn():
        raise exc

    return _fn


def _http_error(status_code: int) -> HTTPError:
    """Construit une HTTPError avec un Response simule a `status_code`."""
    resp = requests.Response()
    resp.status_code = status_code
    err = HTTPError(f"HTTP {status_code}")
    err.response = resp
    return err


class CircuitBreakerBasicTests(unittest.TestCase):
    def test_passes_calls_when_closed(self) -> None:
        b = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        self.assertFalse(b.is_open)
        self.assertEqual(b.call(lambda: "ok"), "ok")
        self.assertEqual(b.failures, 0)

    def test_increments_failures_on_connection_error(self) -> None:
        b = CircuitBreaker(failure_threshold=5, recovery_timeout=1.0)
        for i in range(3):
            with self.assertRaises(ReqConnectionError):
                b.call(_raise(ReqConnectionError("down")))
            self.assertEqual(b.failures, i + 1)
        self.assertFalse(b.is_open)

    def test_resets_failures_on_success(self) -> None:
        b = CircuitBreaker(failure_threshold=5, recovery_timeout=1.0)
        with self.assertRaises(ReqConnectionError):
            b.call(_raise(ReqConnectionError("nope")))
        self.assertEqual(b.failures, 1)
        b.call(lambda: "ok")
        self.assertEqual(b.failures, 0)


class CircuitBreakerOpenTests(unittest.TestCase):
    def test_opens_after_threshold_consecutive_connection_errors(self) -> None:
        b = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        for _ in range(3):
            with self.assertRaises(ReqConnectionError):
                b.call(_raise(ReqConnectionError("down")))
        self.assertTrue(b.is_open)

    def test_opens_after_threshold_consecutive_timeouts(self) -> None:
        b = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        for _ in range(3):
            with self.assertRaises(Timeout):
                b.call(_raise(Timeout("slow")))
        self.assertTrue(b.is_open)

    def test_open_circuit_raises_without_calling_fn(self) -> None:
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(2):
            with self.assertRaises(ReqConnectionError):
                b.call(_raise(ReqConnectionError("down")))
        # circuit ouvert : fn ne doit PAS etre appele
        fn = mock.Mock(return_value="should not call")
        with self.assertRaises(CircuitOpenError):
            b.call(fn)
        fn.assert_not_called()

    def test_open_circuit_message_mentions_remaining_time(self) -> None:
        b = CircuitBreaker(failure_threshold=1, recovery_timeout=300.0)
        with self.assertRaises(ReqConnectionError):
            b.call(_raise(ReqConnectionError("down")))
        with self.assertRaises(CircuitOpenError) as ctx:
            b.call(lambda: "ok")
        msg = str(ctx.exception)
        self.assertIn("Circuit ouvert", msg)
        self.assertIn("retry", msg.lower())

    def test_closes_after_recovery_timeout(self) -> None:
        b = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        with self.assertRaises(ReqConnectionError):
            b.call(_raise(ReqConnectionError("down")))
        self.assertTrue(b.is_open)
        time.sleep(0.08)
        self.assertFalse(b.is_open)
        # un appel apres timeout doit etre tente
        self.assertEqual(b.call(lambda: "back"), "back")


class CircuitBreakerHTTPErrorTests(unittest.TestCase):
    """HTTPError : on ouvre sur 5xx et 429, PAS sur 4xx (hors 429).

    Cf audit C5 P1 : un 401/404 signale une erreur cote caller (mauvais
    token, mauvais id), pas que le service distant est en panne.
    """

    def test_http_500_increments_failures(self) -> None:
        b = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        for i in range(3):
            with self.assertRaises(HTTPError):
                b.call(_raise(_http_error(500)))
            self.assertEqual(b.failures, i + 1)
        self.assertTrue(b.is_open)

    def test_http_503_increments_failures(self) -> None:
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(2):
            with self.assertRaises(HTTPError):
                b.call(_raise(_http_error(503)))
        self.assertTrue(b.is_open)

    def test_http_429_increments_failures(self) -> None:
        # Rate-limit : le serveur nous dit explicitement de ralentir.
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(2):
            with self.assertRaises(HTTPError):
                b.call(_raise(_http_error(429)))
        self.assertTrue(b.is_open)

    def test_http_404_does_not_increment_failures(self) -> None:
        # Mauvais id : c'est notre requete qui est mauvaise, pas le serveur.
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(5):
            with self.assertRaises(HTTPError):
                b.call(_raise(_http_error(404)))
        self.assertFalse(b.is_open)
        self.assertEqual(b.failures, 0)

    def test_http_401_does_not_increment_failures(self) -> None:
        # Auth invalide : pas un signal de panne.
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(5):
            with self.assertRaises(HTTPError):
                b.call(_raise(_http_error(401)))
        self.assertFalse(b.is_open)
        self.assertEqual(b.failures, 0)

    def test_http_400_does_not_increment_failures(self) -> None:
        # Requete malformee : faute du caller.
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(5):
            with self.assertRaises(HTTPError):
                b.call(_raise(_http_error(400)))
        self.assertFalse(b.is_open)
        self.assertEqual(b.failures, 0)

    def test_http_error_without_response_increments_failures(self) -> None:
        # Cas degenere : HTTPError sans response attache. On preferer
        # ouvrir le circuit (defensive) plutot que masquer un probleme.
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        err = HTTPError("no response attached")  # response=None par defaut
        for _ in range(2):
            with self.assertRaises(HTTPError):
                b.call(_raise(err))
        self.assertTrue(b.is_open)


class CircuitBreakerApplicationErrorTests(unittest.TestCase):
    """Erreurs applicatives (parsing, contrat client) : remontees telles
    quelles SANS ouvrir le circuit. Audit C5 P1 : un JSON malforme ne
    doit pas bloquer 5 min toute la chaine.
    """

    def test_value_error_does_not_increment_failures(self) -> None:
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(5):
            with self.assertRaises(ValueError):
                b.call(_raise(ValueError("bad")))
        self.assertFalse(b.is_open)
        self.assertEqual(b.failures, 0)

    def test_json_decode_error_does_not_increment_failures(self) -> None:
        # Specifique au cas decrit dans l'audit C5 P1.
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(5):
            with self.assertRaises(json.JSONDecodeError):
                b.call(_raise(json.JSONDecodeError("bad json", "{", 0)))
        self.assertFalse(b.is_open)
        self.assertEqual(b.failures, 0)

    def test_key_error_does_not_increment_failures(self) -> None:
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(5):
            with self.assertRaises(KeyError):
                b.call(_raise(KeyError("missing")))
        self.assertFalse(b.is_open)
        self.assertEqual(b.failures, 0)

    def test_type_error_does_not_increment_failures(self) -> None:
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(5):
            with self.assertRaises(TypeError):
                b.call(_raise(TypeError("bad type")))
        self.assertFalse(b.is_open)
        self.assertEqual(b.failures, 0)

    def test_application_error_does_not_reset_failures(self) -> None:
        # Mix realiste : 1 ConnectionError -> compteur a 1.
        # Puis 5 ValueError -> compteur reste a 1 (ne reset PAS et n'incremente PAS).
        # Puis 1 ConnectionError de plus -> compteur a 2 -> seuil atteint -> ouvert.
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        with self.assertRaises(ReqConnectionError):
            b.call(_raise(ReqConnectionError("net down")))
        self.assertEqual(b.failures, 1)
        for _ in range(5):
            with self.assertRaises(ValueError):
                b.call(_raise(ValueError("bad json")))
        self.assertEqual(b.failures, 1)  # n'a NI incremente NI reset
        self.assertFalse(b.is_open)
        with self.assertRaises(ReqConnectionError):
            b.call(_raise(ReqConnectionError("net still down")))
        self.assertTrue(b.is_open)


class CircuitBreakerThreadSafetyTests(unittest.TestCase):
    def test_concurrent_failures_count_correctly(self) -> None:
        """50 threads font 1 echec reseau chacun -> compteur final = 50."""
        b = CircuitBreaker(failure_threshold=1000, recovery_timeout=10.0)
        n = 50

        def boom() -> None:
            try:
                b.call(_raise(ReqConnectionError("nope")))
            except ReqConnectionError:
                pass

        threads = [threading.Thread(target=boom) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(b.failures, n)


class CircuitBreakerBaseExceptionTests(unittest.TestCase):
    """Cf audit-bot 2026-05-16 issue #173 : BaseException non-Exception
    (KeyboardInterrupt, SystemExit, GeneratorExit) ne doit PAS incrementer
    le compteur d'echecs.
    """

    def test_keyboardinterrupt_does_not_increment_failures(self) -> None:
        b = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        with self.assertRaises(KeyboardInterrupt):
            b.call(_raise(KeyboardInterrupt()))
        self.assertEqual(b.failures, 0)
        self.assertFalse(b.is_open)

    def test_systemexit_does_not_increment_failures(self) -> None:
        b = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
        with self.assertRaises(SystemExit):
            b.call(_raise(SystemExit(0)))
        self.assertEqual(b.failures, 0)
        self.assertFalse(b.is_open)

    def test_keyboardinterrupt_does_not_open_breaker_after_threshold_hits(self) -> None:
        # Meme si on declenche N KeyboardInterrupt consecutifs (cas pratique :
        # utilisateur fait Ctrl+C plusieurs fois pour annuler), le breaker
        # ne doit pas s'ouvrir : ce sont des arrets administres, pas des
        # echecs du service distant.
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(5):
            with self.assertRaises(KeyboardInterrupt):
                b.call(_raise(KeyboardInterrupt()))
        self.assertFalse(b.is_open)
        self.assertEqual(b.failures, 0)

    def test_connection_error_still_opens_breaker(self) -> None:
        # Verif non-regression : une vraie ConnectionError ouvre toujours.
        b = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        for _ in range(2):
            with self.assertRaises(ReqConnectionError):
                b.call(_raise(ReqConnectionError("down")))
        self.assertTrue(b.is_open)


class CircuitBreakerControlTests(unittest.TestCase):
    def test_reset_clears_failures_and_closes(self) -> None:
        b = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
        with self.assertRaises(ReqConnectionError):
            b.call(_raise(ReqConnectionError("down")))
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
