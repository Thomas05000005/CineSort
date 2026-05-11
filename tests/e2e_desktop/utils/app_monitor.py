"""Monitoring de l'app pendant les tests E2E (CPU, RAM, crash)."""

from __future__ import annotations

import logging
import threading

_log = logging.getLogger(__name__)


class AppMonitor:
    """Thread daemon qui logge les metriques du processus toutes les N secondes."""

    def __init__(self, pid: int, interval_s: float = 2.0):
        self.pid = pid
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.crashed = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        try:
            import psutil
        except ImportError:
            _log.warning("psutil non installe — monitoring desactive")
            return

        try:
            proc = psutil.Process(self.pid)
        except psutil.NoSuchProcess:
            self.crashed = True
            _log.error("Processus %d introuvable au demarrage du monitoring", self.pid)
            return

        while not self._stop.is_set():
            try:
                mem = proc.memory_info().rss / (1024 * 1024)
                cpu = proc.cpu_percent(interval=0.1)
                threads = proc.num_threads()
                _log.debug("PID %d: CPU=%.1f%% RAM=%.1fMB Threads=%d", self.pid, cpu, mem, threads)
            except psutil.NoSuchProcess:
                self.crashed = True
                _log.error("Processus %d a crashe", self.pid)
                break
            self._stop.wait(self.interval_s)
