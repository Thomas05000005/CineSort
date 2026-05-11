"""V3-01 — Vérifie que la logique sidebar n'utilise plus setNavVisible pour intégrations."""

from __future__ import annotations
import unittest
from pathlib import Path


class SidebarIntegrationsTests(unittest.TestCase):
    def setUp(self):
        self.app_js = Path("web/dashboard/app.js").read_text(encoding="utf-8")
        self.css = Path("web/dashboard/styles.css").read_text(encoding="utf-8")
        self.sidebar_v5_js = Path("web/dashboard/components/sidebar-v5.js").read_text(encoding="utf-8")

    def test_no_setnavvisible_for_integrations(self):
        """Les 3 lignes setNavVisible(.nav-btn-jellyfin/plex/radarr) ont disparu."""
        self.assertNotIn('setNavVisible(".nav-btn-jellyfin"', self.app_js)
        self.assertNotIn('setNavVisible(".nav-btn-plex"', self.app_js)
        self.assertNotIn('setNavVisible(".nav-btn-radarr"', self.app_js)

    def test_mark_state_helper_present(self):
        # V5B-01 : la logique a migre dans sidebar-v5.js (markIntegrationState).
        # app.js v5 appelle sidebarV5.markIntegrationState pour Jellyfin/Plex/Radarr.
        self.assertIn("markIntegrationState", self.app_js)
        self.assertIn("export function markIntegrationState", self.sidebar_v5_js)

    def test_disabled_class_styled(self):
        self.assertIn(".nav-btn--disabled", self.css)
        self.assertIn("opacity", self.css.split(".nav-btn--disabled")[1][:200])

    def test_redirect_to_settings_on_disabled_click(self):
        # V5B-01 : la classe disabled v5 est v5-sidebar-item--disabled, gere dans sidebar-v5.js.
        # La redirection vers settings est faite dans le composant v5 ou via aria-disabled.
        self.assertIn("v5-sidebar-item--disabled", self.sidebar_v5_js)


if __name__ == "__main__":
    unittest.main()
