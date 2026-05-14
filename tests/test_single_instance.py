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
