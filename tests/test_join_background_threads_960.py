"""Tests de `join_background_threads` (issue #960).

Le helper attend les threads de fond de l'app avant de supprimer un dossier
temporaire, sinon ils recreent l'arborescence juste apres. Mais il ne doit PAS
attendre un thread de SERVICE : celui-la ne se termine que sur demande, et
l'attendre coute le budget entier pour rien.

MESURE qui motive ce fichier : sans l'exclusion des services, le thread
`cinesort-watcher` (poll toutes les 300 s) produisait 107 joins de 5 s, soit
535 s ajoutees a une seule execution de la suite — l'integralite du surcout
observe. Un test qui verrouille cela vaut 9 minutes par execution.
"""

from __future__ import annotations

import threading
import time
import unittest

from tests._helpers import is_service_thread, join_background_threads


class _WorkerThread(threading.Thread):
    """Thread de travail : il finit tout seul."""

    def __init__(self, duration_s: float) -> None:
        super().__init__(name="worker960", daemon=True)
        self.duration_s = duration_s

    def run(self) -> None:
        time.sleep(self.duration_s)


class _ServiceThread(threading.Thread):
    """Thread de service : il tourne jusqu'a ce qu'on lui demande d'arreter.

    Reproduit le contrat de `cinesort/app/watcher.py` : un `_stop_event` et une
    boucle qui l'attend.
    """

    def __init__(self) -> None:
        super().__init__(name="service960", daemon=True)
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=0.05)

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=5)


class IsServiceThreadTests(unittest.TestCase):
    def test_thread_with_a_stop_event_is_a_service(self) -> None:
        service = _ServiceThread()
        self.assertTrue(is_service_thread(service))

    def test_plain_worker_is_not_a_service(self) -> None:
        self.assertFalse(is_service_thread(_WorkerThread(0.0)))

    def test_main_thread_is_not_a_service(self) -> None:
        self.assertFalse(is_service_thread(threading.main_thread()))


class JoinBackgroundThreadsTests(unittest.TestCase):
    def test_waits_for_a_worker_thread(self) -> None:
        worker = _WorkerThread(0.3)
        self.addCleanup(worker.join, 5)
        worker.start()

        joined = join_background_threads(timeout_s=5.0)

        self.assertFalse(worker.is_alive(), "le thread de travail devait etre attendu")
        self.assertIn("worker960", joined)

    def test_does_not_wait_for_a_service_thread(self) -> None:
        """Le point qui vaut 9 minutes : on ne bloque pas sur un service."""
        service = _ServiceThread()
        self.addCleanup(service.stop)
        service.start()
        # Laisse le thread demarrer pour de bon, sinon `is_alive()` peut etre
        # False et le test passerait sans rien prouver.
        for _ in range(100):
            if service.is_alive():
                break
            time.sleep(0.01)
        self.assertTrue(service.is_alive(), "pre-condition : le service tourne")

        start = time.monotonic()
        joined = join_background_threads(timeout_s=5.0)
        elapsed = time.monotonic() - start

        self.assertNotIn("service960", joined)
        self.assertTrue(service.is_alive(), "le service ne doit pas avoir ete arrete")
        # Borne large mais decisive : sans l'exclusion, l'appel durerait 5 s.
        self.assertLess(elapsed, 1.0, f"l'appel a bloque {elapsed:.2f}s sur un thread de service")

    def test_single_thread_cannot_eat_the_whole_budget(self) -> None:
        """Un thread inconnu qui ne finit pas coute `per_thread_s`, pas tout."""
        worker = _WorkerThread(5.0)
        self.addCleanup(worker.join, 10)
        worker.start()

        start = time.monotonic()
        join_background_threads(timeout_s=5.0, per_thread_s=0.2)
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 1.5, f"le plafond par thread n'a pas tenu : {elapsed:.2f}s")

    def test_returns_empty_when_only_the_main_thread_runs(self) -> None:
        # Aucun thread de travail lance ici : l'appel doit etre immediat.
        start = time.monotonic()
        join_background_threads(timeout_s=5.0)
        self.assertLess(time.monotonic() - start, 1.0)


if __name__ == "__main__":
    unittest.main()
