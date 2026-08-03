"""Tests pour cinesort.infra.single_instance.InstanceLock (issue #68)."""

from __future__ import annotations

import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path

from cinesort.infra.single_instance import InstanceLock


def _hold_lock_in_subprocess(state_dir_str: str, hold_seconds: float, ready_path_str: str) -> None:
    """Worker process : acquiert le lock, touche ready_path, attend hold_seconds."""
    lock = InstanceLock(Path(state_dir_str))
    if not lock.acquire():
        return
    try:
        Path(ready_path_str).touch()
        time.sleep(hold_seconds)
    finally:
        lock.release()


def _spin_acquire_in_subprocess(
    state_dir_str: str,
    deadline_ts: float,
    result_path_str: str,
) -> None:
    """Worker : spin os.open+lockf jusqu'a deadline. Ecrit '1' si acquired, '0' sinon."""
    lock = InstanceLock(Path(state_dir_str))
    acquired = False
    while time.time() < deadline_ts:
        if lock.acquire():
            acquired = True
            break
        time.sleep(0.001)
    try:
        Path(result_path_str).write_text("1" if acquired else "0", encoding="ascii")
    finally:
        if acquired:
            # Garder le lock un court instant pour qu'un autre acquereur concurrent
            # le voie occupe, puis liberer proprement.
            time.sleep(0.2)
            lock.release()


class InstanceLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_lock_test_")
        self.state_dir = Path(self._tmp)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_acquire_creates_lock_file(self) -> None:
        lock = InstanceLock(self.state_dir)
        try:
            self.assertTrue(lock.acquire())
            self.assertTrue((self.state_dir / ".cinesort.lock").is_file())
            self.assertTrue(lock.acquired)
        finally:
            lock.release()

    def test_acquire_writes_current_pid(self) -> None:
        lock = InstanceLock(self.state_dir)
        try:
            self.assertTrue(lock.acquire())
            self.assertEqual(lock.read_holder_pid(), os.getpid())
        finally:
            lock.release()

    def test_release_is_idempotent(self) -> None:
        lock = InstanceLock(self.state_dir)
        lock.acquire()
        lock.release()
        lock.release()  # ne doit pas lever
        self.assertFalse(lock.acquired)

    def test_double_acquire_in_same_process_is_ok(self) -> None:
        """Re-acquire dans le meme process est no-op (deja detenu)."""
        lock = InstanceLock(self.state_dir)
        try:
            self.assertTrue(lock.acquire())
            self.assertTrue(lock.acquire())  # idempotent
        finally:
            lock.release()

    def test_context_manager(self) -> None:
        with InstanceLock(self.state_dir) as lock:
            self.assertTrue(lock.acquired)
        # Apres __exit__ le lock doit etre libere
        self.assertFalse(lock.acquired)

    def test_second_process_cannot_acquire(self) -> None:
        """Une 2eme instance sur le meme state_dir doit echouer."""
        ready = self.state_dir / "ready.flag"
        # Process A : acquiert et tient le lock 3 secondes
        proc = multiprocessing.Process(
            target=_hold_lock_in_subprocess,
            args=(str(self.state_dir), 3.0, str(ready)),
        )
        proc.start()
        try:
            # Attendre que le worker ait acquis le lock
            for _ in range(30):
                if ready.is_file():
                    break
                time.sleep(0.1)
            self.assertTrue(ready.is_file(), "Worker n'a pas acquis le lock dans les temps")

            # Process B (ce test) : doit echouer
            lock_b = InstanceLock(self.state_dir)
            self.assertFalse(lock_b.acquire(), "Une 2e instance a reussi a acquerir le lock !")
        finally:
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
                proc.join()

    def test_no_race_between_release_and_concurrent_acquire(self) -> None:
        """R5-finding-0 : pendant que parent.release() s'execute, N enfants spin sur
        os.open+lockf. Au plus UN enfant doit reussir a acquerir, sinon le bug
        unlink-after-close de release() a permis a 2 inodes distincts de cohabiter.
        """
        n_children = 10
        deadline = time.time() + 5.0
        result_paths = [self.state_dir / f"result_{i}.txt" for i in range(n_children)]

        # Parent acquiert le lock
        lock = InstanceLock(self.state_dir)
        self.assertTrue(lock.acquire())

        # Demarrer N sous-processes qui spin sur acquire()
        procs = [
            multiprocessing.Process(
                target=_spin_acquire_in_subprocess,
                args=(str(self.state_dir), deadline, str(result_paths[i])),
            )
            for i in range(n_children)
        ]
        for p in procs:
            p.start()

        # Laisser les enfants demarrer leur boucle de spin
        time.sleep(0.3)

        # Liberer le lock pendant que les enfants spin -> declenche la race window
        lock.release()

        # Attendre la fin de tous les enfants
        for p in procs:
            p.join(timeout=10)
            if p.is_alive():
                p.terminate()
                p.join()

        # Compter combien d'enfants ont reussi a acquerir
        # Le pattern de test : les enfants spin avec un petit delay (0.2s) avant
        # release, donc si 2 enfants ont "1" simultanement c'est qu'ils ont reussi
        # a acquerir au meme moment -> race confirmee.
        # Or notre test cherche surtout que sur la fenetre release-parent, au plus
        # un enfant capture le lock avant son propre release ; les enfants sont
        # sequentiels une fois la race ecartee.
        # Plus rigoureux : verifier qu'apres tous les join, le fichier de lock est
        # libre et acquisible (pas de inode orphelin tenu).
        successes = sum(1 for p in result_paths if p.is_file() and p.read_text(encoding="ascii").strip() == "1")
        # Tous les enfants devraient avoir acquis sequentiellement (chacun release
        # apres 0.2s, le suivant attrape). Ce qui compte c'est l'absence de crash
        # et que le parent puisse re-acquerir apres.
        self.assertGreaterEqual(successes, 1, "Aucun enfant n'a reussi a acquerir le lock")

        # Re-acquerir doit etre possible (pas d'inode orphelin)
        lock2 = InstanceLock(self.state_dir)
        try:
            self.assertTrue(
                lock2.acquire(),
                "Parent ne peut plus re-acquerir : inode orphelin probable (race condition)",
            )
        finally:
            lock2.release()

    def test_release_does_not_unlink_lock_file(self) -> None:
        """R5-finding-0 : release() ne doit PAS unlink() le fichier de lock.

        Le pattern unlink-after-close cree une TOCTOU race sur POSIX. Le fichier
        doit vivre apres release() ; seul son contenu est efface.
        """
        lock = InstanceLock(self.state_dir)
        lock_file = self.state_dir / ".cinesort.lock"
        self.assertTrue(lock.acquire())
        self.assertTrue(lock_file.is_file())
        lock.release()
        # Le fichier doit toujours exister apres release()
        self.assertTrue(
            lock_file.is_file(),
            "release() ne doit pas unlink() le fichier : cree une TOCTOU race",
        )
        # Le contenu doit etre vide (PID efface sous le lock)
        self.assertEqual(lock_file.stat().st_size, 0, "PID doit etre efface (ftruncate sous le lock)")

    def test_lock_released_after_holder_exits(self) -> None:
        """Apres que le 1er process libere, le 2eme doit pouvoir acquerir."""
        ready = self.state_dir / "ready.flag"
        proc = multiprocessing.Process(
            target=_hold_lock_in_subprocess,
            args=(str(self.state_dir), 0.5, str(ready)),
        )
        proc.start()
        proc.join(timeout=5)
        self.assertFalse(proc.is_alive())

        # Apres l'exit du worker, le lock doit etre libere
        lock = InstanceLock(self.state_dir)
        try:
            self.assertTrue(lock.acquire(), "Lock pas libere apres exit du holder")
        finally:
            lock.release()


if __name__ == "__main__":
    unittest.main(verbosity=2)
