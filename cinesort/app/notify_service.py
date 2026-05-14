"""Notification service — dispatches balloon toasts based on settings and focus state.

Thread-safe: background threads enqueue, main thread drains.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Dict

from cinesort.infra.notifications import show_balloon, cleanup
import contextlib

logger = logging.getLogger(__name__)

# Event types that can be individually toggled.
EVENT_SCAN_TRIGGERED = "scan_triggered"  # cf #108 : watcher detecte un changement
EVENT_SCAN_DONE = "scan_done"
EVENT_APPLY_DONE = "apply_done"
EVENT_UNDO_DONE = "undo_done"
EVENT_ERROR = "error"

_SETTING_KEYS = {
    EVENT_SCAN_TRIGGERED: "notifications_scan_triggered",
    EVENT_SCAN_DONE: "notifications_scan_done",
    EVENT_APPLY_DONE: "notifications_apply_done",
    EVENT_UNDO_DONE: "notifications_undo_done",
    EVENT_ERROR: "notifications_errors",
}


class NotifyService:
    """Desktop notification service with queue for background threads."""

    def __init__(self, window: Any = None) -> None:
        self._window = window
        self._settings: Dict[str, Any] = {}
        self._queue: queue.Queue[tuple[str, str, str, str]] = queue.Queue()
        self._main_thread_id = threading.get_ident()
        # v7.6.0 Vague 9 : optional hook mirroring events into the in-app
        # notification center. Set by CineSortApi once the store is built.
        self._center_hook: Any = None
        # R5-CRIT-1 fix : auto drain timer (jamais appele auparavant en prod →
        # notifications scan_done depuis threads background JAMAIS livrees).
        # Timer relancable, daemon, peut etre stoppe via shutdown().
        self._drain_timer: threading.Timer | None = None
        self._drain_interval_s: float = 0.5
        self._drain_active: bool = False

    def set_center_hook(self, hook: Any) -> None:
        """Register a callable(event_type, title, body, level) to mirror events."""
        self._center_hook = hook if callable(hook) else None

    def set_window(self, window: Any) -> None:
        """Set pywebview window reference (for focus detection)."""
        self._window = window

    def update_settings(self, settings: Dict[str, Any]) -> None:
        """Update the cached settings (called after save_settings)."""
        self._settings = dict(settings) if settings else {}

    @property
    def enabled(self) -> bool:
        """Check if notifications are globally enabled."""
        return bool(self._settings.get("notifications_enabled", False))

    def _is_event_enabled(self, event_type: str) -> bool:
        """Check if a specific event type is enabled."""
        if not self.enabled:
            return False
        key = _SETTING_KEYS.get(event_type, "")
        if not key:
            return self.enabled
        return bool(self._settings.get(key, True))

    def _is_window_focused(self) -> bool:
        """Check if the pywebview window has focus."""
        if not self._window:
            return False
        try:
            result = self._window.evaluate_js("document.hasFocus()")
            return bool(result)
        except (AttributeError, RuntimeError, TypeError):
            return False

    def _should_notify(self, event_type: str) -> bool:
        """Determine if a notification should be shown."""
        if not self._is_event_enabled(event_type):
            return False
        if self._is_window_focused():
            return False
        return True

    def notify(self, event_type: str, title: str, body: str, level: str = "info") -> None:
        """Send a notification. Thread-safe.

        If called from a background thread, the notification is queued
        and will be delivered on the next drain_queue() call.
        """
        # v7.6.0 Vague 9 : miroir inconditionnel vers le notification center
        # (independant du reglage notifications_enabled qui ne concerne que
        # les toasts Windows).
        hook = self._center_hook
        if hook is not None:
            try:
                hook(event_type, title, body, level)
            except (AttributeError, TypeError, RuntimeError) as exc:
                logger.debug("Notification center hook failed: %s", exc)

        if not self._is_event_enabled(event_type):
            return

        if threading.get_ident() == self._main_thread_id:
            self._deliver(event_type, title, body, level)
        else:
            self._queue.put((event_type, title, body, level))

    def drain_queue(self) -> None:
        """Process queued notifications. Call from the main thread."""
        while True:
            try:
                event_type, title, body, level = self._queue.get_nowait()
                self._deliver(event_type, title, body, level)
            except queue.Empty:
                break

    def _deliver(self, event_type: str, title: str, body: str, level: str) -> None:
        """Actually show the notification if conditions are met."""
        if not self._should_notify(event_type):
            return
        try:
            shown = show_balloon(title, body, level)
            if shown:
                logger.debug("Notification shown: [%s] %s", event_type, title)
        except (OSError, ValueError) as exc:
            logger.debug("Notification delivery failed: %s", exc)

    def start_drain_timer(self, interval_s: float = 0.5) -> None:
        """R5-CRIT-1 fix : demarre un timer auto-relancable qui drain la queue.

        Sans cet appel, les notifications enquetees depuis les threads background
        (job_runner scan/apply) restent dans la queue et ne sont jamais livrees.

        A appeler depuis app.py apres set_window() (donc depuis le main thread).
        """
        if self._drain_active:
            return
        self._drain_active = True
        self._drain_interval_s = max(0.1, float(interval_s))
        self._schedule_next_drain()

    def _schedule_next_drain(self) -> None:
        if not self._drain_active:
            return
        timer = threading.Timer(self._drain_interval_s, self._drain_tick)
        timer.daemon = True
        self._drain_timer = timer
        timer.start()

    def _drain_tick(self) -> None:
        try:
            self.drain_queue()
        except (OSError, RuntimeError) as exc:
            logger.debug("drain_tick error: %s", exc)
        if self._drain_active:
            self._schedule_next_drain()

    def shutdown(self) -> None:
        """Cleanup resources. Call at app shutdown."""
        # R5-CRIT-1 : stop drain timer first
        self._drain_active = False
        if self._drain_timer is not None:
            with contextlib.suppress(RuntimeError, AttributeError):
                self._drain_timer.cancel()
            self._drain_timer = None
        with contextlib.suppress(OSError, RuntimeError):
            cleanup()
