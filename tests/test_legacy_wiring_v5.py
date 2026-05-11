"""Tests Vague 10 fix : wiring des boutons sidebar legacy vers les overlays v5.

Verifie que :
- router.js intercepte les routes legacy (validation/execution/settings/quality/
  history/jellyfin/plex/radarr) pour les rediriger vers les overlays v5
- un flag opts.legacy = true permet la backdoor dev pour revenir a l'ancienne UI
- index.html expose un bouton Notifications dans la sidebar-footer
- app.js cable ce bouton + ecoute v5:notif-count pour le badge
- notification-center.js emet v5:notif-count en plus de TopBarV5.setNotificationCount
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class RouterLegacyWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = (_ROOT / "web" / "core" / "router.js").read_text(encoding="utf-8")

    def test_legacy_flag_supported(self) -> None:
        self.assertIn("opts.legacy", self.router)

    def test_validation_redirects_to_processing(self) -> None:
        self.assertRegex(
            self.router,
            r'view\s*===\s*"validation"[^;]*(_navigateToProcessing|processing)',
        )

    def test_execution_redirects_to_processing(self) -> None:
        self.assertRegex(
            self.router,
            r'view\s*===\s*"execution"[^;]*(_navigateToProcessing|processing)',
        )

    def test_settings_redirects_to_settings_v5(self) -> None:
        # La ligne doit rediriger settings vers _navigateToSettingsV5
        self.assertIn('view === "settings"', self.router)
        # Verifier qu'apres la condition settings, on call _navigateToSettingsV5
        idx = self.router.find('if (view === "settings") {')
        self.assertGreater(idx, 0, "Le wiring 'settings -> settings-v5' doit exister")
        block = self.router[idx : idx + 300]
        self.assertIn("_navigateToSettingsV5", block)

    def test_quality_redirects_to_qij(self) -> None:
        idx = self.router.find('if (view === "quality") {')
        self.assertGreater(idx, 0)
        block = self.router[idx : idx + 200]
        self.assertIn("_navigateToQIJ", block)
        self.assertIn('"quality"', block)

    def test_history_redirects_to_journal(self) -> None:
        idx = self.router.find('if (view === "history") {')
        self.assertGreater(idx, 0)
        block = self.router[idx : idx + 200]
        self.assertIn("_navigateToQIJ", block)
        self.assertIn('"journal"', block)

    def test_jellyfin_plex_radarr_redirect_to_integrations(self) -> None:
        idx = self.router.find('view === "jellyfin"')
        self.assertGreater(idx, 0)
        block = self.router[idx : idx + 300]
        self.assertIn("plex", block)
        self.assertIn("radarr", block)
        self.assertIn("_navigateToQIJ", block)
        self.assertIn('"integrations"', block)


class IndexHtmlNotifButtonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")

    def test_notif_button_exists_in_sidebar(self) -> None:
        self.assertIn('id="btnNotifCenter"', self.html)
        self.assertIn('aria-label="Notifications"', self.html)

    def test_notif_button_in_sidebar_footer(self) -> None:
        # Le bouton doit etre dans sidebar-footer, pas n'importe ou
        idx_footer = self.html.find("sidebar-footer")
        idx_btn = self.html.find("btnNotifCenter")
        self.assertGreater(idx_footer, 0)
        self.assertGreater(idx_btn, idx_footer)
        # Distance raisonnable (< 1000 chars entre les deux)
        self.assertLess(idx_btn - idx_footer, 1000)

    def test_notif_button_has_label(self) -> None:
        self.assertIn('id="btnNotifCenterLabel"', self.html)


class AppJsWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_notif_button_bound(self) -> None:
        self.assertIn("btnNotifCenter", self.js)
        self.assertIn("NotificationCenter", self.js)
        self.assertIn("toggle", self.js)

    def test_listens_to_notif_count_event(self) -> None:
        self.assertIn("v5:notif-count", self.js)


class NotifCenterEmitsEventTests(unittest.TestCase):
    def test_desktop_center_emits_custom_event(self) -> None:
        js = (_ROOT / "web" / "components" / "notification-center.js").read_text(encoding="utf-8")
        self.assertIn("v5:notif-count", js)
        self.assertIn("CustomEvent", js)


class CssBadgeUnreadTests(unittest.TestCase):
    def test_has_unread_indicator_styled(self) -> None:
        css = (_ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")
        self.assertIn("#btnNotifCenter", css)
        self.assertIn(".has-unread", css)


if __name__ == "__main__":
    unittest.main()
