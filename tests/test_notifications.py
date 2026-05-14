"""Tests for desktop notification system."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest import mock

from cinesort.app.notify_service import NotifyService, EVENT_SCAN_DONE, EVENT_APPLY_DONE, EVENT_UNDO_DONE, EVENT_ERROR


class NotifyServiceSettingsTests(unittest.TestCase):
    """Test settings-based enable/disable logic."""

    def test_disabled_by_default(self) -> None:
        ns = NotifyService()
        self.assertFalse(ns.enabled)

    def test_enabled_via_settings(self) -> None:
        ns = NotifyService()
        ns.update_settings({"notifications_enabled": True})
        self.assertTrue(ns.enabled)

    def test_individual_events_default_true(self) -> None:
        ns = NotifyService()
        ns.update_settings({"notifications_enabled": True})
        self.assertTrue(ns._is_event_enabled(EVENT_SCAN_DONE))
        self.assertTrue(ns._is_event_enabled(EVENT_APPLY_DONE))
        self.assertTrue(ns._is_event_enabled(EVENT_UNDO_DONE))
        self.assertTrue(ns._is_event_enabled(EVENT_ERROR))

    def test_individual_event_disabled(self) -> None:
        ns = NotifyService()
        ns.update_settings({"notifications_enabled": True, "notifications_scan_done": False})
        self.assertFalse(ns._is_event_enabled(EVENT_SCAN_DONE))
        self.assertTrue(ns._is_event_enabled(EVENT_APPLY_DONE))

    def test_global_disable_overrides_individual(self) -> None:
        ns = NotifyService()
        ns.update_settings({"notifications_enabled": False, "notifications_scan_done": True})
        self.assertFalse(ns._is_event_enabled(EVENT_SCAN_DONE))


class NotifyServiceFocusTests(unittest.TestCase):
    """Test focus detection logic."""

    def test_no_window_returns_not_focused(self) -> None:
        ns = NotifyService()
        self.assertFalse(ns._is_window_focused())

    def test_should_notify_when_enabled_and_not_focused(self) -> None:
        ns = NotifyService()
        ns.update_settings({"notifications_enabled": True})
        # No window → not focused → should notify
        self.assertTrue(ns._should_notify(EVENT_SCAN_DONE))

    def test_should_not_notify_when_focused(self) -> None:
        ns = NotifyService()
        ns.update_settings({"notifications_enabled": True})
        mock_window = mock.MagicMock()
        mock_window.evaluate_js.return_value = True
        ns.set_window(mock_window)
        self.assertFalse(ns._should_notify(EVENT_SCAN_DONE))

    def test_should_notify_when_window_not_focused(self) -> None:
        ns = NotifyService()
        ns.update_settings({"notifications_enabled": True})
        mock_window = mock.MagicMock()
        mock_window.evaluate_js.return_value = False
        ns.set_window(mock_window)
        self.assertTrue(ns._should_notify(EVENT_SCAN_DONE))


class NotifyServiceQueueTests(unittest.TestCase):
    """Test thread-safe queue mechanism."""

    def test_main_thread_delivers_directly(self) -> None:
        ns = NotifyService()
        ns.update_settings({"notifications_enabled": True})
        with mock.patch("cinesort.app.notify_service.show_balloon") as mock_show:
            ns.notify(EVENT_SCAN_DONE, "Test", "Body")
            mock_show.assert_called_once()

    def test_background_thread_queues(self) -> None:
        ns = NotifyService()
        ns.update_settings({"notifications_enabled": True})

        with mock.patch("cinesort.app.notify_service.show_balloon") as mock_show:
            # Call from a different thread
            t = threading.Thread(target=lambda: ns.notify(EVENT_SCAN_DONE, "BG", "body"))
            t.start()
            t.join()
            # Should NOT have been delivered yet (queued)
            mock_show.assert_not_called()

            # Drain from main thread
            ns.drain_queue()
            mock_show.assert_called_once()

    def test_drain_empty_queue(self) -> None:
        ns = NotifyService()
        ns.drain_queue()  # should not raise


class NotifyServiceDeliveryTests(unittest.TestCase):
    """Test delivery filtering."""

    def test_no_delivery_when_disabled(self) -> None:
        ns = NotifyService()
        ns.update_settings({"notifications_enabled": False})
        with mock.patch("cinesort.app.notify_service.show_balloon") as mock_show:
            ns.notify(EVENT_SCAN_DONE, "Test", "Body")
            mock_show.assert_not_called()

    def test_no_delivery_when_event_disabled(self) -> None:
        ns = NotifyService()
        ns.update_settings({"notifications_enabled": True, "notifications_scan_done": False})
        with mock.patch("cinesort.app.notify_service.show_balloon") as mock_show:
            ns.notify(EVENT_SCAN_DONE, "Test", "Body")
            mock_show.assert_not_called()


class NotificationsModuleTests(unittest.TestCase):
    """Test the low-level notifications module."""

    def test_import_works(self) -> None:
        from cinesort.infra.notifications import show_balloon, cleanup

        self.assertTrue(callable(show_balloon))
        self.assertTrue(callable(cleanup))

    def test_cleanup_does_not_raise(self) -> None:
        from cinesort.infra.notifications import cleanup

        cleanup()  # should not raise even if nothing was added


class NotificationsUiContractTests(unittest.TestCase):
    """UI contract: settings fields exist in HTML and JS."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.index_html = (root / "web" / "index.html").read_text(encoding="utf-8")
        js_files = []
        for d in ["core", "components", "views"]:
            p = root / "web" / d
            if p.is_dir():
                for f in sorted(p.glob("*.js")):
                    js_files.append(f.read_text(encoding="utf-8"))
        js_files.append((root / "web" / "app.js").read_text(encoding="utf-8"))
        cls.front_js = "\n".join(js_files)

    def test_notification_toggles_in_html(self) -> None:
        self.assertIn('id="ckNotificationsEnabled"', self.index_html)
        self.assertIn('id="ckNotifScanDone"', self.index_html)
        self.assertIn('id="ckNotifApplyDone"', self.index_html)
        self.assertIn('id="ckNotifUndoDone"', self.index_html)
        self.assertIn('id="ckNotifErrors"', self.index_html)

    def test_notification_settings_in_js(self) -> None:
        self.assertIn("notifications_enabled", self.front_js)
        self.assertIn("notifications_scan_done", self.front_js)
        self.assertIn("ckNotificationsEnabled", self.front_js)


class NotificationsIntegrationTests(unittest.TestCase):
    """Test that notify_service is accessible from the API."""

    def test_api_has_notify_service(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        self.assertIsInstance(api._notify, NotifyService)

    def test_api_notify_settings_synced_on_save(self) -> None:
        import shutil
        import tempfile
        import cinesort.ui.api.cinesort_api as backend

        tmp = tempfile.mkdtemp(prefix="cinesort_notif_")
        try:
            root = Path(tmp) / "root"
            sd = Path(tmp) / "state"
            root.mkdir()
            sd.mkdir()
            api = backend.CineSortApi()
            api.settings.save_settings(
                {
                    "root": str(root),
                    "state_dir": str(sd),
                    "tmdb_enabled": False,
                    "notifications_enabled": True,
                    "notifications_scan_done": False,
                }
            )
            self.assertTrue(api._notify.enabled)
            self.assertFalse(api._notify._is_event_enabled(EVENT_SCAN_DONE))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class NotificationsSettingsPersistenceTests(unittest.TestCase):
    """Test that notification settings survive save/load cycle."""

    def test_settings_round_trip(self) -> None:
        import shutil
        import tempfile
        import cinesort.ui.api.cinesort_api as backend

        tmp = tempfile.mkdtemp(prefix="cinesort_notif_rt_")
        try:
            root = Path(tmp) / "root"
            sd = Path(tmp) / "state"
            root.mkdir()
            sd.mkdir()
            api = backend.CineSortApi()
            api.settings.save_settings(
                {
                    "root": str(root),
                    "state_dir": str(sd),
                    "tmdb_enabled": False,
                    "notifications_enabled": True,
                    "notifications_scan_done": False,
                    "notifications_apply_done": True,
                    "notifications_undo_done": False,
                    "notifications_errors": True,
                }
            )
            loaded = api.settings.get_settings()
            self.assertTrue(loaded["notifications_enabled"])
            self.assertFalse(loaded["notifications_scan_done"])
            self.assertTrue(loaded["notifications_apply_done"])
            self.assertFalse(loaded["notifications_undo_done"])
            self.assertTrue(loaded["notifications_errors"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
