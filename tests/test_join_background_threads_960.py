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

import contextlib
import threading
import time
import unittest
import unittest.mock
from types import SimpleNamespace

from tests._helpers import is_service_thread, join_background_threads


def _arreter(api: SimpleNamespace, attribut: str, thread: threading.Thread | None) -> None:
    """Pose l'evenement d'arret du cron et attend sa mort.

    Sans cela le cron survit a la session entiere — c'est exactement le defaut
    mesure dans `tests/test_quarantaine_ttl_v77.py`.
    """
    stop = getattr(api, attribut, None)
    if isinstance(stop, threading.Event):
        stop.set()
    if thread is not None:
        thread.join(timeout=5.0)


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


@contextlib.contextmanager
def _seuls_ces_threads(*threads: threading.Thread):
    """Restreint ce que `join_background_threads` voit aux threads donnes.

    POURQUOI, et c'est le coeur de ce fichier : la fonction parcourt TOUS les
    threads du processus, avec un plafond de 2 s chacun. Chronometrer son appel
    sans borner cette population mesure donc la sante des voisins, pas le code
    teste. MESURE : un fichier sonde demarrant le cron `cinesort-quarantine-ttl`
    — copie conforme de ce que fait deja `tests/test_quarantaine_ttl_v77.py` —
    place avant ce fichier dans l'ordre alphabetique faisait tomber TROIS de ces
    tests (`2.001 s not less than 1.0`, et `'worker960' not found in
    ['cinesort-quarantine-ttl']`). Ils passaient seuls. Ils etaient verts
    uniquement parce que ce fichier tombe, en `j`, dans un trou entre les
    orphelins de `test_fs_safety.py` (`f`) et le cron de `test_quarantaine` (`q`).

    C'est le piege du chronometre que ce depot a deja paye, et « rejouer en
    isolation » aurait declare ces tests sains.
    """
    reference = threading.main_thread()
    with unittest.mock.patch.object(threading, "enumerate", lambda: [reference, *threads]):
        yield


class JoinBackgroundThreadsTests(unittest.TestCase):
    def test_waits_for_a_worker_thread(self) -> None:
        worker = _WorkerThread(0.3)
        self.addCleanup(worker.join, 5)
        worker.start()

        with _seuls_ces_threads(worker):
            joined = join_background_threads(timeout_s=5.0)

        self.assertFalse(worker.is_alive(), "le thread de travail devait etre attendu")
        self.assertIn("worker960", joined)

    def test_enumerates_real_threads_by_default(self) -> None:
        """Sans le bornage ci-dessus : la fonction voit bien les vrais threads.

        Ce test doit rester vrai quel que soit l'etat du processus, donc :
          - assertion d'APPARTENANCE, jamais d'egalite ni de duree ;
          - le travailleur ne se termine QUE sur ordre. Une premiere version le
            faisait dormir 0,1 s et devenait rouge des qu'un voisin retenait
            l'appel : le thread mourait avant d'etre atteint, la boucle le
            sautait comme deja fini, et son nom n'apparaissait jamais. Mesure
            faite avec un voisin bloque — le defaut meme que ce fichier corrige,
            reproduit dans un test que je venais d'ecrire ;
          - `per_thread_s` minuscule, pour que N voisins bloques coutent N x 50 ms
            et non N x 2 s.
        """
        fini = threading.Event()
        worker = threading.Thread(target=fini.wait, name="worker960", daemon=True)
        self.addCleanup(worker.join, 5)
        self.addCleanup(fini.set)
        worker.start()

        joined = join_background_threads(timeout_s=5.0, per_thread_s=0.05)

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

        with _seuls_ces_threads(service):
            start = time.monotonic()
            joined = join_background_threads(timeout_s=5.0)
            elapsed = time.monotonic() - start

        self.assertNotIn("service960", joined)
        self.assertTrue(service.is_alive(), "le service ne doit pas avoir ete arrete")
        # Le service est desormais SEUL candidat : sans l'exclusion, l'appel
        # durerait le plafond par thread (2 s). La borne mesure donc bien ce
        # qu'elle pretend mesurer.
        self.assertLess(elapsed, 1.0, f"l'appel a bloque {elapsed:.2f}s sur un thread de service")

    def test_single_thread_cannot_eat_the_whole_budget(self) -> None:
        """Un thread inconnu qui ne finit pas coute `per_thread_s`, pas tout."""
        worker = _WorkerThread(5.0)
        self.addCleanup(worker.join, 10)
        worker.start()

        with _seuls_ces_threads(worker):
            start = time.monotonic()
            join_background_threads(timeout_s=5.0, per_thread_s=0.2)
            elapsed = time.monotonic() - start

        self.assertLess(elapsed, 1.5, f"le plafond par thread n'a pas tenu : {elapsed:.2f}s")

    def test_an_unresponsive_thread_is_paid_once_and_never_again(self) -> None:
        """Un thread qui a deja epuise son budget ne doit plus rien couter.

        MESURE qui motive la memoire : `tests/test_fs_safety.py` abandonne 3
        threads anonymes qui restent vivants pendant 221 tests. Ils ne portent
        aucun nom de service, donc rien ne les distingue d'un travailleur lent —
        et chaque `cleanup_test_tree` de cette fenetre payait le budget entier.
        """
        bloque = _WorkerThread(30.0)
        self.addCleanup(bloque.join, 0.1)
        bloque.start()

        with _seuls_ces_threads(bloque):
            debut_premier = time.monotonic()
            premier = join_background_threads(timeout_s=5.0, per_thread_s=0.4)
            duree_premier = time.monotonic() - debut_premier

            debut_second = time.monotonic()
            second = join_background_threads(timeout_s=5.0, per_thread_s=0.4)
            duree_second = time.monotonic() - debut_second

        self.assertIn("worker960", premier, "le premier appel doit bien tenter l'attente")
        self.assertGreaterEqual(duree_premier, 0.3, f"le premier appel n'a pas attendu : {duree_premier:.2f}s")
        self.assertNotIn("worker960", second, "le second appel a re-attendu un thread deja declare insensible")
        self.assertLess(duree_second, 0.2, f"le second appel a coute {duree_second:.2f}s")

    def test_returns_nothing_when_no_candidate_thread_runs(self) -> None:
        """Aucun candidat : l'appel ne joint rien et ne coute rien.

        Ancien nom : « when only the main thread runs ». Il etait FAUX — mesure
        sur 2 650 tests, le thread principal n'est jamais seul en session
        complete (pic a 9 threads etrangers simultanes).
        """
        with _seuls_ces_threads():
            start = time.monotonic()
            joined = join_background_threads(timeout_s=5.0)
            elapsed = time.monotonic() - start

        self.assertEqual(joined, [])
        self.assertLess(elapsed, 1.0)


class ServicesReelsDeLAppTests(unittest.TestCase):
    """Les services REELS de l'app doivent etre reconnus — pas seulement un mock.

    Le `_ServiceThread` de ce fichier est une sous-classe de `Thread` qui porte
    son propre `_stop_event`, comme `FolderWatcher`. Or trois des quatre
    services de l'app ne sont PAS des sous-classes : ils sont construits par
    `threading.Thread(target=...)` et posent leur evenement d'arret sur l'objet
    `api`. La regle par capacite ne pouvait structurellement pas les voir, et le
    mock ne pouvait pas le reveler. MESURE avant correction :
    `join_background_threads(5.0)` coutait 4,02 s et laissait les deux crons
    vivants.
    """

    def test_the_quarantine_cron_is_recognised_as_a_service(self) -> None:
        from cinesort.app.quarantine_ttl import start_quarantine_ttl_cron

        api = SimpleNamespace()
        thread = start_quarantine_ttl_cron(api, ttl_days=30, initial_delay_s=600.0, interval_s=3600.0)
        self.assertIsNotNone(thread)
        self.addCleanup(_arreter, api, "_quarantine_ttl_stop", thread)

        self.assertTrue(is_service_thread(thread), f"cron non reconnu comme service : {thread.name}")

    def test_the_retention_cron_is_recognised_as_a_service(self) -> None:
        from cinesort.app.retention_cleanup import start_retention_cron

        api = SimpleNamespace()
        thread = start_retention_cron(api, retention_days=30, initial_delay_s=600.0, interval_s=3600.0)
        self.assertIsNotNone(thread)
        self.addCleanup(_arreter, api, "_retention_stop", thread)

        self.assertTrue(is_service_thread(thread), f"cron non reconnu comme service : {thread.name}")

    def test_no_budget_is_spent_on_the_app_crons(self) -> None:
        """La consequence chiffree : ces threads ne doivent plus rien couter."""
        from cinesort.app.quarantine_ttl import start_quarantine_ttl_cron

        api = SimpleNamespace()
        cron = start_quarantine_ttl_cron(api, ttl_days=30, initial_delay_s=600.0, interval_s=3600.0)
        self.addCleanup(_arreter, api, "_quarantine_ttl_stop", cron)
        for _ in range(100):
            if cron.is_alive():
                break
            time.sleep(0.01)
        self.assertTrue(cron.is_alive(), "pre-condition : le cron tourne")

        with _seuls_ces_threads(cron):
            start = time.monotonic()
            joined = join_background_threads(timeout_s=5.0)
            elapsed = time.monotonic() - start

        self.assertEqual(joined, [], "le cron a ete attendu alors qu'il ne se termine jamais seul")
        self.assertLess(elapsed, 1.0, f"l'appel a bloque {elapsed:.2f}s sur un cron de l'app")


if __name__ == "__main__":
    unittest.main()
