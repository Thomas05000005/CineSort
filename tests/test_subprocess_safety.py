"""Tests pour `cinesort.infra.subprocess_safety` — V1-03 (R5-CRASH-2 + R4-PERC-4).

Couvre :
- Cleanup normal : process termine seul, registre vide, pas de zombie.
- Cleanup sur exception : exception remontee depuis le with -> kill + wait + unregister.
- Cleanup atexit : tous les processes du registre tues quand _cleanup_at_exit() appele.
- Reentrance : tracked_popen imbrique fonctionne (chaque process trace independamment).
- TimeoutExpired : signature compatible subprocess.run.
- Drop-in tracked_run : capture_output, text, returncode.
"""

from __future__ import annotations

import subprocess
import sys
import time
import unittest

from cinesort.infra import subprocess_safety
from cinesort.infra.subprocess_safety import (
    _ACTIVE_PROCESSES,
    _cleanup_at_exit,
    active_process_count,
    tracked_popen,
    tracked_run,
)


def _python_sleep_cmd(seconds: float) -> list[str]:
    """Commande pour lancer un python qui dort N secondes (cross-platform)."""
    return [sys.executable, "-c", f"import time; time.sleep({float(seconds)})"]


def _python_echo_cmd(text: str) -> list[str]:
    """Commande pour lancer un python qui ecrit text sur stdout."""
    # Repr pour echapper proprement les guillemets/quotes.
    return [sys.executable, "-c", f"import sys; sys.stdout.write({text!r})"]


class TrackedRunNormalCleanupTests(unittest.TestCase):
    """Cleanup normal : process termine seul, registre vide."""

    def setUp(self) -> None:
        # Sanity : registre clean au depart de chaque test.
        with subprocess_safety._REGISTRY_LOCK:
            _ACTIVE_PROCESSES.clear()

    def test_normal_completion_unregisters(self) -> None:
        """Process qui termine normalement -> registre vide a la sortie."""
        result = tracked_run(_python_echo_cmd("hello"), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "hello")
        self.assertEqual(active_process_count(), 0)

    def test_returncode_propagated(self) -> None:
        """Le returncode est correctement propage."""
        cmd = [sys.executable, "-c", "import sys; sys.exit(7)"]
        result = tracked_run(cmd, capture_output=True)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(active_process_count(), 0)

    def test_capture_output_returns_bytes_by_default(self) -> None:
        """Sans text=True, stdout/stderr sont en bytes (parite subprocess.run)."""
        result = tracked_run(_python_echo_cmd("bytes_test"), capture_output=True)
        self.assertIsInstance(result.stdout, bytes)
        self.assertEqual(result.stdout, b"bytes_test")

    def test_text_mode_returns_strings(self) -> None:
        """Avec text=True, stdout/stderr sont des str."""
        result = tracked_run(_python_echo_cmd("str_test"), capture_output=True, text=True)
        self.assertIsInstance(result.stdout, str)
        self.assertEqual(result.stdout, "str_test")


class TrackedPopenExceptionCleanupTests(unittest.TestCase):
    """Cleanup sur exception : kill + wait garantis meme si exception remontee."""

    def setUp(self) -> None:
        with subprocess_safety._REGISTRY_LOCK:
            _ACTIVE_PROCESSES.clear()

    def test_exception_in_with_kills_process(self) -> None:
        """Si une exception remonte depuis le with-block, le process est tue."""

        class _Boom(RuntimeError):
            pass

        proc_ref: list[subprocess.Popen] = []
        try:
            with tracked_popen(_python_sleep_cmd(30.0)) as proc:
                proc_ref.append(proc)
                # Simule une exception non rattrapee dans le code metier.
                raise _Boom("simulated crash mid-perceptual")
        except _Boom:
            pass

        # Le process doit etre termine et plus dans le registre.
        self.assertEqual(active_process_count(), 0)
        self.assertEqual(len(proc_ref), 1)
        rc = proc_ref[0].poll()
        self.assertIsNotNone(rc, "process devait etre termine apres exception")

    def test_timeout_propagated_with_partial_output(self) -> None:
        """tracked_run leve TimeoutExpired comme subprocess.run."""
        # Sleep 30s mais timeout 0.5s : doit lever, et tuer le child.
        with self.assertRaises(subprocess.TimeoutExpired):
            tracked_run(_python_sleep_cmd(30.0), timeout=0.5, capture_output=True)
        # Cleanup garanti.
        self.assertEqual(active_process_count(), 0)


class CleanupAtExitTests(unittest.TestCase):
    """`_cleanup_at_exit` tue tous les processes encore actifs."""

    def setUp(self) -> None:
        with subprocess_safety._REGISTRY_LOCK:
            _ACTIVE_PROCESSES.clear()

    def tearDown(self) -> None:
        # Defensive : si un test laisse fuiter un process, on cleanup.
        with subprocess_safety._REGISTRY_LOCK:
            leaks = list(_ACTIVE_PROCESSES)
        for p in leaks:
            try:
                p.kill()
                p.wait(timeout=1.0)
            except Exception:  # noqa: BLE001 (best-effort teardown)
                pass
        with subprocess_safety._REGISTRY_LOCK:
            _ACTIVE_PROCESSES.clear()

    def test_cleanup_at_exit_kills_all_active(self) -> None:
        """Plusieurs processes actifs -> tous tues + registre vide apres cleanup."""
        # Lance 3 process longs SANS context manager pour simuler des
        # processes orphelins du registre au moment du shutdown.
        procs = [
            subprocess.Popen(_python_sleep_cmd(60.0), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(3)
        ]
        for p in procs:
            subprocess_safety._register(p)

        self.assertEqual(active_process_count(), 3)

        # Appel direct du cleanup (atexit hook).
        _cleanup_at_exit()

        # Tous tues + registre vide.
        self.assertEqual(active_process_count(), 0)
        # Petit delai OS pour laisser le poll() observer la mort.
        time.sleep(0.1)
        for p in procs:
            self.assertIsNotNone(p.poll(), "process devait etre tue par cleanup")

    def test_cleanup_at_exit_noop_if_empty(self) -> None:
        """Cleanup sur registre vide : no-op silencieux, pas d'erreur."""
        self.assertEqual(active_process_count(), 0)
        # Ne doit rien lever.
        _cleanup_at_exit()
        self.assertEqual(active_process_count(), 0)


class ReentrantTests(unittest.TestCase):
    """tracked_popen imbrique : chaque process est trace independamment."""

    def setUp(self) -> None:
        with subprocess_safety._REGISTRY_LOCK:
            _ACTIVE_PROCESSES.clear()

    def test_nested_tracked_popen(self) -> None:
        """tracked_popen imbrique : count grimpe puis redescend."""
        with tracked_popen(_python_sleep_cmd(5.0), stdout=subprocess.DEVNULL) as outer:
            self.assertEqual(active_process_count(), 1)
            with tracked_popen(_python_sleep_cmd(5.0), stdout=subprocess.DEVNULL) as inner:
                self.assertEqual(active_process_count(), 2)
                self.assertNotEqual(outer.pid, inner.pid)
            # Sortie du with interne -> kill + unregister.
            self.assertEqual(active_process_count(), 1)
        # Sortie du with externe -> kill + unregister.
        self.assertEqual(active_process_count(), 0)


if __name__ == "__main__":
    unittest.main()
