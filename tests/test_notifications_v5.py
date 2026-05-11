"""Tests Vague 9 v7.6.0 — Notification Center (drawer + endpoints + integration)."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Backend : NotificationStore
# ---------------------------------------------------------------------------


class NotificationStoreTests(unittest.TestCase):
    def _store(self):
        from cinesort.ui.api.notifications_support import NotificationStore

        return NotificationStore()

    def test_add_returns_item_with_id(self) -> None:
        store = self._store()
        it = store.add("scan_done", "Analyse terminee", "10 films")
        self.assertIn("id", it)
        self.assertEqual(it["title"], "Analyse terminee")
        self.assertEqual(it["event_type"], "scan_done")
        self.assertFalse(it["read"])
        self.assertFalse(it["dismissed"])

    def test_list_returns_lifo(self) -> None:
        store = self._store()
        store.add("scan_done", "A")
        store.add("apply_done", "B")
        store.add("error", "C")
        items = store.list()
        self.assertEqual([it["title"] for it in items], ["C", "B", "A"])

    def test_unread_only_filter(self) -> None:
        store = self._store()
        it1 = store.add("scan_done", "A")
        store.add("scan_done", "B")
        store.mark_read(it1["id"])
        items = store.list(unread_only=True)
        self.assertEqual([it["title"] for it in items], ["B"])

    def test_category_filter(self) -> None:
        store = self._store()
        store.add("scan_done", "Event A", category="event")
        store.add("insight", "Insight A", category="insight")
        items_ev = store.list(category="event")
        items_in = store.list(category="insight")
        self.assertEqual(len(items_ev), 1)
        self.assertEqual(len(items_in), 1)
        self.assertEqual(items_ev[0]["title"], "Event A")

    def test_unread_count(self) -> None:
        store = self._store()
        store.add("scan_done", "A")
        store.add("scan_done", "B")
        store.add("scan_done", "C")
        self.assertEqual(store.unread_count(), 3)
        store.mark_all_read()
        self.assertEqual(store.unread_count(), 0)

    def test_dismiss_removes_from_list(self) -> None:
        store = self._store()
        it = store.add("scan_done", "A")
        self.assertEqual(len(store.list()), 1)
        ok = store.dismiss(it["id"])
        self.assertTrue(ok)
        self.assertEqual(len(store.list()), 0)
        self.assertEqual(store.unread_count(), 0)

    def test_dismiss_unknown_id(self) -> None:
        store = self._store()
        ok = store.dismiss("nonexistent")
        self.assertFalse(ok)

    def test_clear_all(self) -> None:
        store = self._store()
        store.add("scan_done", "A")
        store.add("scan_done", "B")
        cleared = store.clear()
        self.assertEqual(cleared, 2)
        self.assertEqual(len(store.list()), 0)
        self.assertEqual(store.unread_count(), 0)

    def test_ring_buffer_cap(self) -> None:
        from cinesort.ui.api.notifications_support import NotificationStore

        store = NotificationStore(max_items=3)
        for i in range(5):
            store.add("scan_done", f"T{i}")
        items = store.list()
        self.assertEqual(len(items), 3)
        self.assertEqual([it["title"] for it in items], ["T4", "T3", "T2"])

    def test_auto_level_from_event_type(self) -> None:
        store = self._store()
        ok = store.add("scan_done", "T")
        err = store.add("error", "T")
        self.assertEqual(ok["level"], "success")
        self.assertEqual(err["level"], "error")

    def test_thread_safety(self) -> None:
        store = self._store()

        def worker():
            for i in range(50):
                store.add("scan_done", f"T{i}")

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 4 * 50 = 200 items, mais max_items default = 200 → on garde les 200 derniers
        self.assertLessEqual(len(store.list(limit=1000)), 200)


# ---------------------------------------------------------------------------
# Backend : support module (endpoints wrappers)
# ---------------------------------------------------------------------------


class NotificationsSupportApiTests(unittest.TestCase):
    def _make_api(self):
        api = MagicMock()
        api._notification_store = None
        return api

    def test_get_notifications_empty(self) -> None:
        from cinesort.ui.api import notifications_support

        api = self._make_api()
        res = notifications_support.get_notifications(api)
        self.assertTrue(res["ok"])
        self.assertEqual(res["notifications"], [])
        self.assertEqual(res["unread_count"], 0)

    def test_add_notification_persists(self) -> None:
        from cinesort.ui.api import notifications_support

        api = self._make_api()
        res = notifications_support.add_notification(api, "scan_done", "Test", "body")
        self.assertTrue(res["ok"])
        listed = notifications_support.get_notifications(api)
        self.assertEqual(len(listed["notifications"]), 1)
        self.assertEqual(listed["notifications"][0]["title"], "Test")

    def test_dismiss_roundtrip(self) -> None:
        from cinesort.ui.api import notifications_support

        api = self._make_api()
        added = notifications_support.add_notification(api, "scan_done", "Test")
        nid = added["notification"]["id"]
        res = notifications_support.dismiss_notification(api, nid)
        self.assertTrue(res["ok"])
        listed = notifications_support.get_notifications(api)
        self.assertEqual(len(listed["notifications"]), 0)

    def test_mark_all_read_roundtrip(self) -> None:
        from cinesort.ui.api import notifications_support

        api = self._make_api()
        notifications_support.add_notification(api, "scan_done", "A")
        notifications_support.add_notification(api, "scan_done", "B")
        res = notifications_support.mark_all_read(api)
        self.assertEqual(res["marked"], 2)
        self.assertEqual(res["unread_count"], 0)

    def test_emit_from_insights_dedupe(self) -> None:
        from cinesort.ui.api import notifications_support

        api = self._make_api()
        insights = [
            {"code": "dnr_suspect", "title": "DNR", "message": "5 films suspects", "severity": "warn"},
            {"code": "upscale_4k", "title": "Upscale", "message": "3 films", "severity": "warn"},
        ]
        n1 = notifications_support.emit_from_insights(api, insights, source="dashboard")
        self.assertEqual(n1, 2)
        # Second passage : aucun doublon
        n2 = notifications_support.emit_from_insights(api, insights, source="dashboard")
        self.assertEqual(n2, 0)
        # Source differente → reemis
        n3 = notifications_support.emit_from_insights(api, insights, source="library")
        self.assertEqual(n3, 2)


# ---------------------------------------------------------------------------
# Backend : endpoints exposes sur CineSortApi
# ---------------------------------------------------------------------------


class TrifilmsApiNotificationEndpointsTests(unittest.TestCase):
    def test_endpoints_exposed(self) -> None:
        src = (_ROOT / "cinesort" / "ui" / "api" / "cinesort_api.py").read_text(encoding="utf-8")
        for name in (
            "def get_notifications",
            "def dismiss_notification",
            "def mark_notification_read",
            "def mark_all_notifications_read",
            "def clear_notifications",
            "def get_notifications_unread_count",
        ):
            self.assertIn(name, src)

    def test_notify_service_center_hook_wired(self) -> None:
        src = (_ROOT / "cinesort" / "ui" / "api" / "cinesort_api.py").read_text(encoding="utf-8")
        self.assertIn("set_center_hook", src)
        self.assertIn("notifications_support.add_notification", src)


class NotifyServiceHookTests(unittest.TestCase):
    def test_notify_service_has_center_hook(self) -> None:
        from cinesort.app.notify_service import NotifyService

        svc = NotifyService()
        self.assertTrue(hasattr(svc, "set_center_hook"))

    def test_center_hook_called_on_notify(self) -> None:
        from cinesort.app.notify_service import NotifyService

        received = []
        svc = NotifyService()
        svc.set_center_hook(lambda et, t, b, l: received.append((et, t, b, l)))
        svc.notify("scan_done", "Titre", "Body", level="info")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "scan_done")
        self.assertEqual(received[0][1], "Titre")


# ---------------------------------------------------------------------------
# Frontend desktop : notification-center.js (IIFE)
# ---------------------------------------------------------------------------


class NotificationCenterDesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "components" / "notification-center.js").read_text(encoding="utf-8")

    def test_exposes_window_notification_center(self) -> None:
        self.assertIn("window.NotificationCenter", self.js)

    def test_public_api_methods(self) -> None:
        for fn in ("open", "close", "toggle", "refresh", "getUnreadCount", "startPolling", "stopPolling"):
            self.assertIn(f"{fn}", self.js)

    def test_uses_api_endpoints(self) -> None:
        for endpoint in (
            "get_notifications",
            "dismiss_notification",
            "mark_all_notifications_read",
            "mark_notification_read",
            "clear_notifications",
        ):
            self.assertIn(endpoint, self.js)

    def test_filter_states(self) -> None:
        for f in ('"all"', '"unread"', '"insight"', '"event"'):
            self.assertIn(f, self.js)

    def test_escape_key_closes_drawer(self) -> None:
        self.assertIn('e.key === "Escape"', self.js)

    def test_auto_poll_on_load(self) -> None:
        self.assertIn("DOMContentLoaded", self.js)
        self.assertIn("startPolling", self.js)

    def test_badge_updates_via_top_bar(self) -> None:
        self.assertIn("window.TopBarV5", self.js)
        self.assertIn("setNotificationCount", self.js)


class TopBarV5NotifIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "components" / "top-bar-v5.js").read_text(encoding="utf-8")

    def test_notif_trigger_opens_notification_center(self) -> None:
        self.assertIn("window.NotificationCenter", self.js)
        self.assertIn("toggle", self.js)


# ---------------------------------------------------------------------------
# Frontend dashboard : ES module equivalent
# ---------------------------------------------------------------------------


class NotificationCenterDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "dashboard" / "components" / "notification-center.js").read_text(encoding="utf-8")

    def test_es_module_exports(self) -> None:
        for exp in (
            "export function openNotifications",
            "export function closeNotifications",
            "export function toggleNotifications",
            "export function refreshNotifications",
            "export function getUnreadCount",
            "export function startNotificationPolling",
            "export function stopNotificationPolling",
        ):
            self.assertIn(exp, self.js)

    def test_imports_apiPost(self) -> None:
        self.assertIn('import { apiPost } from "../core/api.js"', self.js)

    def test_imports_escapeHtml(self) -> None:
        self.assertIn('import { escapeHtml } from "../core/dom.js"', self.js)

    def test_uses_custom_event_for_badge(self) -> None:
        self.assertIn("v5:notif-count", self.js)
        self.assertIn("CustomEvent", self.js)


# ---------------------------------------------------------------------------
# CSS v5 components
# ---------------------------------------------------------------------------


class NotifCssTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")

    def test_drawer_classes(self) -> None:
        for cls in (".v5-notif-overlay", ".v5-notif-drawer", ".v5-notif-header", ".v5-notif-body", ".v5-notif-actions"):
            self.assertIn(cls, self.css)

    def test_item_state_classes(self) -> None:
        for cls in (".v5-notif-item", ".v5-notif-item.is-read", ".v5-notif-item.is-unread"):
            self.assertIn(cls, self.css)

    def test_level_variants(self) -> None:
        for lvl in ("info", "success", "warning", "error"):
            self.assertIn(f".v5-notif-item--{lvl}", self.css)

    def test_filter_buttons(self) -> None:
        self.assertIn(".v5-notif-filter", self.css)
        self.assertIn(".v5-notif-filter.is-active", self.css)

    def test_drawer_has_transition(self) -> None:
        # Verifier que le drawer a bien une transition transform
        self.assertIn("transform: translateX(100%)", self.css)
        self.assertIn("transition: transform", self.css)


# ---------------------------------------------------------------------------
# Integration index.html desktop
# ---------------------------------------------------------------------------


class IndexHtmlNotifIntegrationTests(unittest.TestCase):
    def test_index_html_loads_notification_center(self) -> None:
        html = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("notification-center.js", html)


# ---------------------------------------------------------------------------
# Insights V2 mirror (dashboard_support)
# ---------------------------------------------------------------------------


class DashboardInsightsMirrorTests(unittest.TestCase):
    def test_global_stats_emits_insights(self) -> None:
        src = (_ROOT / "cinesort" / "ui" / "api" / "dashboard_support.py").read_text(encoding="utf-8")
        self.assertIn("notifications_support", src)
        self.assertIn("emit_from_insights", src)


# ---------------------------------------------------------------------------
# Smoke test Node : module dashboard s'importe proprement
# ---------------------------------------------------------------------------


class DashboardSmokeTests(unittest.TestCase):
    def test_dashboard_module_imports_cleanly(self) -> None:
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node non disponible")
        result = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                "import('./web/dashboard/components/notification-center.js').then("
                "(m) => { console.log('N:' + Object.keys(m).sort().join(',')); })",
            ],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("closeNotifications", result.stdout)
        self.assertIn("openNotifications", result.stdout)
        self.assertIn("refreshNotifications", result.stdout)


if __name__ == "__main__":
    unittest.main()
