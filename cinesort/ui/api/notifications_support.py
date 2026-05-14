"""v7.6.0 Vague 9 — Notification Center server-side store.

Captures les evenements produits par NotifyService (scan_done, apply_done,
undo_done, error) + insights V2 + watchlist matches, les retient en memoire
avec cap (200 items), permet a l'UI de lister / filtrer / marquer lu / supprimer.

Contrat :
    get_notifications(api, unread_only=False, limit=100, category=None)
        -> { ok, notifications: [...], unread_count }
    add_notification(api, event_type, title, body, level="info", category="event", data=None)
        -> { ok, notification }
    dismiss_notification(api, notification_id)
        -> { ok }
    mark_all_read(api)
        -> { ok, marked }
    clear_all(api)
        -> { ok, cleared }

Le store expose aussi `get_unread_count()` pour le badge top-bar.

Thread-safe: tous les acces passent par _lock.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, List, Optional
import contextlib

logger = logging.getLogger(__name__)

_MAX_NOTIFICATIONS = 200
_VALID_LEVELS = {"info", "success", "warning", "error"}
_VALID_CATEGORIES = {"event", "insight", "watchlist", "integration", "system"}
_EVENT_TO_LEVEL = {
    "scan_triggered": "info",  # cf #108 : watcher a detecte un changement
    "scan_done": "success",
    "apply_done": "success",
    "undo_done": "info",
    "error": "error",
    "scan_error": "error",
}


class NotificationStore:
    """In-memory ring buffer for notifications with read-state tracking."""

    def __init__(self, max_items: int = _MAX_NOTIFICATIONS) -> None:
        self._items: Deque[Dict[str, Any]] = deque(maxlen=max_items)
        self._lock = threading.Lock()
        self._counter = itertools.count(1)

    def add(
        self,
        event_type: str,
        title: str,
        body: str = "",
        level: str = "info",
        category: str = "event",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        lvl = level if level in _VALID_LEVELS else "info"
        cat = category if category in _VALID_CATEGORIES else "event"
        if lvl == "info" and event_type in _EVENT_TO_LEVEL:
            lvl = _EVENT_TO_LEVEL[event_type]
        item: Dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "seq": next(self._counter),
            "event_type": str(event_type or "event"),
            "title": str(title or ""),
            "body": str(body or ""),
            "level": lvl,
            "category": cat,
            "data": dict(data) if isinstance(data, dict) else {},
            "created_ts": time.time(),
            "read": False,
            "dismissed": False,
        }
        with self._lock:
            self._items.append(item)
        return dict(item)

    def list(
        self,
        unread_only: bool = False,
        limit: int = 100,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            snapshot = list(self._items)
        out: List[Dict[str, Any]] = []
        for it in reversed(snapshot):
            if it.get("dismissed"):
                continue
            if unread_only and it.get("read"):
                continue
            if category and it.get("category") != category:
                continue
            out.append(dict(it))
            if limit and len(out) >= int(limit):
                break
        return out

    def unread_count(self) -> int:
        with self._lock:
            return sum(1 for it in self._items if not it.get("read") and not it.get("dismissed"))

    def mark_read(self, notification_id: str) -> bool:
        with self._lock:
            for it in self._items:
                if it.get("id") == notification_id:
                    it["read"] = True
                    return True
        return False

    def mark_all_read(self) -> int:
        marked = 0
        with self._lock:
            for it in self._items:
                if not it.get("read") and not it.get("dismissed"):
                    it["read"] = True
                    marked += 1
        return marked

    def dismiss(self, notification_id: str) -> bool:
        with self._lock:
            for it in self._items:
                if it.get("id") == notification_id:
                    it["dismissed"] = True
                    it["read"] = True
                    return True
        return False

    def clear(self) -> int:
        with self._lock:
            cleared = sum(1 for it in self._items if not it.get("dismissed"))
            for it in self._items:
                it["dismissed"] = True
                it["read"] = True
        return cleared


def _get_or_create_store(api: Any) -> NotificationStore:
    """Return the singleton store attached to the CineSortApi instance."""
    store = getattr(api, "_notification_store", None)
    if not isinstance(store, NotificationStore):
        store = NotificationStore()
        try:
            api._notification_store = store
        except AttributeError:
            logger.debug("Could not attach notification store to api instance")
    return store


def add_notification(
    api: Any,
    event_type: str,
    title: str,
    body: str = "",
    level: str = "info",
    category: str = "event",
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    store = _get_or_create_store(api)
    item = store.add(event_type, title, body, level=level, category=category, data=data)
    logger.debug("Notification added: [%s] %s", event_type, title)
    return {"ok": True, "notification": item, "unread_count": store.unread_count()}


def get_notifications(
    api: Any,
    unread_only: bool = False,
    limit: int = 100,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    store = _get_or_create_store(api)
    items = store.list(unread_only=bool(unread_only), limit=int(limit or 100), category=category)
    return {
        "ok": True,
        "notifications": items,
        "unread_count": store.unread_count(),
        "total": len(items),
    }


def dismiss_notification(api: Any, notification_id: str) -> Dict[str, Any]:
    store = _get_or_create_store(api)
    ok = store.dismiss(str(notification_id or ""))
    return {"ok": bool(ok), "unread_count": store.unread_count()}


def mark_all_read(api: Any) -> Dict[str, Any]:
    store = _get_or_create_store(api)
    marked = store.mark_all_read()
    return {"ok": True, "marked": marked, "unread_count": store.unread_count()}


def mark_read(api: Any, notification_id: str) -> Dict[str, Any]:
    store = _get_or_create_store(api)
    ok = store.mark_read(str(notification_id or ""))
    return {"ok": bool(ok), "unread_count": store.unread_count()}


def clear_all_notifications(api: Any) -> Dict[str, Any]:
    store = _get_or_create_store(api)
    cleared = store.clear()
    return {"ok": True, "cleared": cleared, "unread_count": 0}


def get_unread_count(api: Any) -> int:
    store = _get_or_create_store(api)
    return store.unread_count()


# --------------------------------------------------------------------------
# Insights V2 capture
# --------------------------------------------------------------------------


def emit_from_insights(api: Any, insights: List[Dict[str, Any]], *, source: str = "dashboard") -> int:
    """Cree une notification par insight actif (non emis pendant cette session).

    Deduplication par (code, source) dans la session courante via set attache a l'api.
    """
    if not isinstance(insights, list):
        return 0
    emitted_set = getattr(api, "_emitted_insight_codes", None)
    if not isinstance(emitted_set, set):
        emitted_set = set()
        with contextlib.suppress(AttributeError):
            api._emitted_insight_codes = emitted_set
    # R5-MEM-3 fix : cap a 10 000 tuples pour eviter growth indefini sur sessions
    # tres longues (plusieurs mois sans restart). Au-dela, clear le set (les
    # insights seront a nouveau emis comme "nouveaux" — acceptable car rare).
    _MAX_EMITTED_INSIGHTS = 10_000
    if len(emitted_set) > _MAX_EMITTED_INSIGHTS:
        try:
            emitted_set.clear()
            logger.info(
                "_emitted_insight_codes cap reached (%d), cleared",
                _MAX_EMITTED_INSIGHTS,
            )
        except (AttributeError, RuntimeError):
            pass
    created = 0
    for ins in insights:
        if not isinstance(ins, dict):
            continue
        code = str(ins.get("code") or "").strip()
        if not code:
            continue
        key = (code, source)
        if key in emitted_set:
            continue
        emitted_set.add(key)
        title = str(ins.get("title") or code)
        body = str(ins.get("message") or "")
        severity = str(ins.get("severity") or "info")
        level = "warning" if severity in ("warn", "warning") else ("error" if severity == "critical" else "info")
        add_notification(
            api,
            event_type="insight",
            title=title,
            body=body,
            level=level,
            category="insight",
            data={"code": code, "source": source, "raw": ins},
        )
        created += 1
    return created
