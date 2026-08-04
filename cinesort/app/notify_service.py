"""Notification service — dispatches balloon toasts based on settings and focus state.

Thread-safe: background threads enqueue, the drain timer thread delivers.

Contrat de thread (pywebview 6.2.1, backend EdgeChromium sous Windows) :
`window.evaluate_js()` NE DOIT PAS etre appele depuis le thread GUI. Il fait
`self.webview.Invoke(...)` puis `semaphore.acquire()`
(webview/platforms/edgechromium.py:152-160) : depuis le thread GUI il s'attendrait
lui-meme -> gel. pywebview impose `webview.start()` sur le MainThread
(webview/__init__.py:239-240) et execute le callback applicatif dans un thread
SEPARE (webview/__init__.py:293-301). Le drain depuis un thread `threading.Timer`
est donc le mode d'emploi normal, pas une violation.

Cycle de vie du drain (issues #543 / #616) : `_drain_active` est l'unique etat
d'arret, et il est lu sous `_drain_lock` DANS LA MEME SECTION CRITIQUE que la
publication du prochain timer. C'est ce qui rend la sequence
« shutdown observe -> replanification » indivisible : shutdown() voit donc
toujours le dernier timer publie, et aucun timer ne peut ressusciter apres lui.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
from typing import Any, Dict

from cinesort.infra.notifications import cleanup, show_balloon

logger = logging.getLogger(__name__)

# Event types that can be individually toggled.
EVENT_SCAN_TRIGGERED = "scan_triggered"  # cf #108 : watcher detecte un changement
EVENT_SCAN_DONE = "scan_done"
EVENT_APPLY_DONE = "apply_done"
EVENT_UNDO_DONE = "undo_done"
EVENT_ERROR = "error"

# Attente bornee, au shutdown, d'un tick de drain deja parti. Bornee car un
# evaluate_js peut rester bloque si la boucle GUI est deja morte : on prefere
# rendre la main (le timer est daemon) plutot que de figer la sortie de l'app.
_DRAIN_JOIN_TIMEOUT_S = 1.0

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
        #
        # #543/#616 : _drain_lock protege le COUPLE (_drain_active, _drain_timer).
        # Toute lecture de l'etat d'arret qui decide d'une replanification doit se
        # faire dans la meme section critique que la publication du timer.
        self._drain_lock = threading.Lock()
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
        """Check if DESKTOP toasts are globally enabled.

        R8-069 (F5) : le toast desktop (show_balloon) est gardé par le toggle UI
        "Activer les notifications desktop" (desktop_notifications_enabled). AVANT, il
        lisait notifications_enabled (toggle "notifications applicatives") -> le toggle
        desktop était un FANTÔME et le mauvais réglage gardait les toasts. Le miroir vers
        le centre de notifications reste inconditionnel (cf notify()), donc les
        notifications applicatives ne dépendent pas de ce gate.
        """
        return bool(self._settings.get("desktop_notifications_enabled", False))

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
        """Process queued notifications.

        A appeler depuis un thread NON-GUI (le drain timer, ou le thread de
        callback de `webview.start()`). Cf. le contrat de thread en tete de
        module : `evaluate_js` depuis le thread GUI se bloquerait lui-meme.
        """
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

        A appeler depuis app.py apres set_window(), donc depuis le thread de
        callback de `webview.start()` (qui n'est PAS le thread GUI).
        """
        with self._drain_lock:
            if self._drain_active:
                return
            self._drain_active = True
            self._drain_interval_s = max(0.1, float(interval_s))
            timer = self._new_drain_timer_locked()
        timer.start()

    def _new_drain_timer_locked(self) -> threading.Timer:
        """Cree et PUBLIE le prochain timer. `_drain_lock` doit etre detenu.

        La publication (`self._drain_timer = timer`) sous verrou est ce qui
        garantit a shutdown() de voir le dernier timer arme : sans elle, un timer
        cree apres le cancel de shutdown() survivrait (#616).
        """
        timer = threading.Timer(self._drain_interval_s, self._drain_tick)
        timer.daemon = True
        self._drain_timer = timer
        return timer

    def _drain_tick(self) -> None:
        # Garde d'ENTREE (#616) : un timer peut avoir demarre son callback juste
        # avant shutdown(). Sans ce test, il livrerait pendant le teardown
        # pywebview (evaluate_js sur une fenetre detruite) et concurrencerait
        # le cleanup() de l'icone tray.
        with self._drain_lock:
            if not self._drain_active:
                return
        try:
            self.drain_queue()
        except (OSError, RuntimeError) as exc:
            logger.debug("drain_tick error: %s", exc)
        # Garde de SORTIE (#543/#616) : relire l'etat d'arret et publier le
        # prochain timer dans la MEME section critique. shutdown() ne peut donc
        # pas s'intercaler entre les deux et laisser un timer orphelin.
        with self._drain_lock:
            if not self._drain_active:
                return
            timer = self._new_drain_timer_locked()
        timer.start()

    def shutdown(self) -> None:
        """Cleanup resources. Call at app shutdown. Idempotent."""
        # R5-CRIT-1 : stop drain timer first
        with self._drain_lock:
            self._drain_active = False
            timer = self._drain_timer
            self._drain_timer = None
        if timer is not None:
            with contextlib.suppress(RuntimeError, AttributeError):
                timer.cancel()
            # `timer` est aussi le thread du tick EN COURS le cas echeant (le tick
            # ne republie qu'apres avoir fini). On l'attend, borne, pour ne pas
            # detruire l'icone tray pendant qu'un ballon s'affiche. Pas de
            # self-join si shutdown() est appele depuis le tick lui-meme.
            if threading.current_thread() is not timer:
                with contextlib.suppress(RuntimeError):
                    timer.join(_DRAIN_JOIN_TIMEOUT_S)
        with contextlib.suppress(OSError, RuntimeError):
            cleanup()
