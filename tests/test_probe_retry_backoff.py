"""ITER13 - Test du retry exponentiel sur echec transitoire de probe.

Objectif (BILAN_ITER13 section 3.b) : prouver que
`cinesort/infra/probe/_retry_backoff.py::retry_with_backoff` :
1. Respecte la sequence 1s/2s/4s/8s (plafond) entre les tentatives.
2. Borne le nombre max de retries (defaut 3 = total 4 tentatives).
3. Ne retry PAS sur les exceptions non-transitoires (RuntimeError, ValueError).
4. Ne retry PAS sur KeyboardInterrupt / SystemExit (signal admin).
5. Reset le compteur sur succes.
6. Re-leve la derniere exception apres epuisement.

Test family B : panne SIMULEE (sleep_fn mocke pour ne pas attendre 8s
reels). Le contrat de delais est verifie via la capture des delais
recus par sleep_fn.

Identification DECOUPLEE du probe : le retry n'altere QUE l'execution
subprocess. Les couches domain/app/ui restent intactes.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from typing import List

from cinesort.infra.probe._retry_backoff import (
    DEFAULT_BASE_DELAY_S,
    DEFAULT_MAX_DELAY_S,
    DEFAULT_MAX_RETRIES,
    MAX_RETRIES_HARD_CAP,
    retry_with_backoff,
)


class _SleepRecorder:
    """Capture les delais passes a sleep_fn sans bloquer le test."""

    def __init__(self) -> None:
        self.delays: List[float] = []

    def __call__(self, d: float) -> None:
        self.delays.append(float(d))


def _timeout_exc(label: str = "ffprobe") -> subprocess.TimeoutExpired:
    return subprocess.TimeoutExpired(cmd=[label, "-version"], timeout=8.0)


class TestSequenceBackoff(unittest.TestCase):
    """Sequence 1s/2s/4s/8s (plafond) entre tentatives."""

    def test_3_retries_donnent_delais_1_2_4(self) -> None:
        """Pattern attendu : 1ere attente=1s, 2eme=2s, 3eme=4s.

        Avec max_retries=3, on a 4 tentatives au total, donc 3 sleeps.
        """
        sleeper = _SleepRecorder()
        attempts: List[int] = []

        def fn() -> str:
            attempts.append(1)
            raise _timeout_exc()

        with self.assertRaises(subprocess.TimeoutExpired):
            retry_with_backoff(
                fn,
                max_retries=3,
                base_delay_s=1.0,
                max_delay_s=8.0,
                sleep_fn=sleeper,
            )
        self.assertEqual(len(attempts), 4, "3 retries -> 4 tentatives au total")
        self.assertEqual(sleeper.delays, [1.0, 2.0, 4.0],
                         "Sequence backoff 1s, 2s, 4s")

    def test_max_delay_plafonne_a_8s(self) -> None:
        """Avec base=1 et 5 retries, 2^5=32 mais cape a 8s (plafond)."""
        sleeper = _SleepRecorder()

        def fn() -> str:
            raise _timeout_exc()

        with self.assertRaises(subprocess.TimeoutExpired):
            retry_with_backoff(
                fn,
                max_retries=5,
                base_delay_s=1.0,
                max_delay_s=8.0,
                sleep_fn=sleeper,
            )
        # 5 retries -> 5 sleeps : 1, 2, 4, 8, 8 (plafond).
        self.assertEqual(len(sleeper.delays), 5)
        self.assertEqual(sleeper.delays[0], 1.0)
        self.assertEqual(sleeper.delays[1], 2.0)
        self.assertEqual(sleeper.delays[2], 4.0)
        self.assertEqual(sleeper.delays[3], 8.0)
        self.assertEqual(sleeper.delays[4], 8.0,
                         "Plafond 8s ne doit JAMAIS etre depasse")


class TestBorneMaxRetries(unittest.TestCase):
    """Le nombre de retries doit etre borne."""

    def test_default_max_retries_egale_3(self) -> None:
        """Defaut documente : 3 retries (4 tentatives au total)."""
        self.assertEqual(DEFAULT_MAX_RETRIES, 3)

    def test_hard_cap_10(self) -> None:
        """Memoire : pas plus de 10 retries meme si l'env est malveillant."""
        self.assertEqual(MAX_RETRIES_HARD_CAP, 10)

    def test_clamp_env_au_hard_cap(self) -> None:
        """CINESORT_PROBE_RETRY_MAX=999 -> clamp a 10."""
        sleeper = _SleepRecorder()
        os.environ["CINESORT_PROBE_RETRY_MAX"] = "999"
        try:
            def fn() -> str:
                raise _timeout_exc()

            with self.assertRaises(subprocess.TimeoutExpired):
                retry_with_backoff(fn, sleep_fn=sleeper)
            # 10 retries (max) -> 10 sleeps.
            self.assertEqual(len(sleeper.delays), 10)
        finally:
            os.environ.pop("CINESORT_PROBE_RETRY_MAX", None)

    def test_zero_retry_donne_un_seul_essai(self) -> None:
        """max_retries=0 -> 1 essai, 0 sleep."""
        sleeper = _SleepRecorder()
        attempts: List[int] = []

        def fn() -> str:
            attempts.append(1)
            raise _timeout_exc()

        with self.assertRaises(subprocess.TimeoutExpired):
            retry_with_backoff(fn, max_retries=0, sleep_fn=sleeper)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(sleeper.delays, [])


class TestSucces(unittest.TestCase):
    """Sur succes, propage le resultat et stoppe les retries."""

    def test_succes_premier_essai(self) -> None:
        sleeper = _SleepRecorder()

        def fn() -> str:
            return "ok"

        result = retry_with_backoff(fn, sleep_fn=sleeper)
        self.assertEqual(result, "ok")
        self.assertEqual(sleeper.delays, [],
                         "Aucun sleep en cas de succes immediat")

    def test_succes_apres_2_echecs(self) -> None:
        sleeper = _SleepRecorder()
        calls = [0]

        def fn() -> str:
            calls[0] += 1
            if calls[0] < 3:
                raise _timeout_exc()
            return "recovered"

        result = retry_with_backoff(fn, max_retries=5, sleep_fn=sleeper)
        self.assertEqual(result, "recovered")
        self.assertEqual(calls[0], 3, "3 tentatives, dont 2 echecs avant succes")
        # 2 echecs -> 2 sleeps.
        self.assertEqual(sleeper.delays, [1.0, 2.0])


class TestNonTransientPasRetry(unittest.TestCase):
    """Les erreurs non transitoires remontent immediatement."""

    def test_runtime_error_pas_retry(self) -> None:
        sleeper = _SleepRecorder()
        attempts: List[int] = []

        def fn() -> str:
            attempts.append(1)
            raise RuntimeError("bug applicatif")

        with self.assertRaises(RuntimeError):
            retry_with_backoff(fn, max_retries=3, sleep_fn=sleeper)
        self.assertEqual(len(attempts), 1, "Aucun retry sur RuntimeError")
        self.assertEqual(sleeper.delays, [])

    def test_value_error_pas_retry(self) -> None:
        sleeper = _SleepRecorder()
        attempts: List[int] = []

        def fn() -> str:
            attempts.append(1)
            raise ValueError("JSON invalide")

        with self.assertRaises(ValueError):
            retry_with_backoff(fn, max_retries=3, sleep_fn=sleeper)
        self.assertEqual(len(attempts), 1)

    def test_keyboard_interrupt_remonte_immediat(self) -> None:
        """Signal administre ne doit JAMAIS etre retentee."""
        sleeper = _SleepRecorder()
        attempts: List[int] = []

        def fn() -> str:
            attempts.append(1)
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            retry_with_backoff(fn, max_retries=3, sleep_fn=sleeper)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(sleeper.delays, [])


class TestTransientRetry(unittest.TestCase):
    """Erreurs transitoires identifees sont retentees."""

    def test_broken_pipe_error_retentee(self) -> None:
        sleeper = _SleepRecorder()
        calls = [0]

        def fn() -> str:
            calls[0] += 1
            if calls[0] == 1:
                raise BrokenPipeError("pipe closed")
            return "ok"

        result = retry_with_backoff(fn, max_retries=2, sleep_fn=sleeper)
        self.assertEqual(result, "ok")
        self.assertEqual(calls[0], 2)

    def test_connection_error_retentee(self) -> None:
        sleeper = _SleepRecorder()
        calls = [0]

        def fn() -> str:
            calls[0] += 1
            if calls[0] == 1:
                raise ConnectionResetError("conn reset")
            return "ok"

        result = retry_with_backoff(fn, max_retries=2, sleep_fn=sleeper)
        self.assertEqual(result, "ok")
        self.assertEqual(calls[0], 2)


class TestDefaults(unittest.TestCase):
    """Constants documentees, pour eviter regressions silencieuses."""

    def test_default_base_delay_1s(self) -> None:
        self.assertEqual(DEFAULT_BASE_DELAY_S, 1.0)

    def test_default_max_delay_8s(self) -> None:
        self.assertEqual(DEFAULT_MAX_DELAY_S, 8.0)


if __name__ == "__main__":
    unittest.main()
