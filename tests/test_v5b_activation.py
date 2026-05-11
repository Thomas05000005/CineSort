"""V5B-01 — Vérifie l'activation v5 dans app.js + index.html.

Tests structurels (lecture de fichiers, pas d'exécution JS) qui
constituent un garde-fou anti-régression sur l'activation v5 du
dashboard distant.
"""

from __future__ import annotations
import unittest
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DASH = _PROJECT_ROOT / "web" / "dashboard"


class V5BActivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (_DASH / "index.html").read_text(encoding="utf-8")
        cls.app = (_DASH / "app.js").read_text(encoding="utf-8")
        cls.router = (_DASH / "core" / "router.js").read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # HTML : shell v5 + suppression sidebar/topbar statiques
    # ------------------------------------------------------------------

    def test_html_has_v5_shell(self):
        self.assertIn('id="app-shell"', self.html)
        self.assertIn("v5-shell", self.html)
        self.assertIn('id="v5SidebarMount"', self.html)
        self.assertIn('id="v5TopBarMount"', self.html)
        self.assertIn('id="v5BreadcrumbMount"', self.html)

    def test_html_no_more_static_sidebar(self):
        # La sidebar legacy avait des `<div class="sidebar-group">` et
        # une cascade de `<button class="nav-btn" data-route=...>`. Apres
        # V5B-01 elles sont mountees dynamiquement — l'HTML statique ne
        # doit plus les contenir.
        self.assertNotIn('<div class="sidebar-group">', self.html)
        self.assertNotIn('class="nav-btn"', self.html)
        # Pas non plus de topbar legacy (titre/sous-titre statiques).
        self.assertNotIn('id="topbarTitle"', self.html)

    def test_html_login_preserved(self):
        # Le login reste en HTML statique (pas v5-ise).
        self.assertIn('id="view-login"', self.html)
        self.assertIn('id="loginForm"', self.html)
        self.assertIn('id="loginToken"', self.html)

    def test_html_v5_view_mount_points(self):
        # Mount points pour les 7 vues v5 portees.
        for view_id in (
            "view-home",
            "view-library",
            "view-processing",
            "view-quality",
            "view-settings",
            "view-help",
            "view-film-detail",
        ):
            self.assertIn(f'id="{view_id}"', self.html, f"Mount point manquant : {view_id}")

    def test_html_v4_views_kept(self):
        # Vues v4 conservees jusqu'a V5C.
        for view_id in ("view-jellyfin", "view-plex", "view-radarr", "view-logs"):
            self.assertIn(f'id="{view_id}"', self.html, f"Vue v4 manquante : {view_id}")

    def test_html_no_more_legacy_globals_shim(self):
        # V6 : le shim _legacy_globals.js a ete supprime, remplace par
        # _legacy_compat.js (ES module importe par home.js).
        self.assertNotIn("_legacy_globals.js", self.html)

    # ------------------------------------------------------------------
    # app.js : imports v5 shell + vues ESM + routes + features
    # ------------------------------------------------------------------

    def test_app_imports_v5_components(self):
        for comp in ("sidebar-v5.js", "top-bar-v5.js", "breadcrumb.js", "notification-center.js"):
            self.assertIn(comp, self.app, f"Composant v5 non importe : {comp}")

    def test_app_imports_v5_views(self):
        # V1-05 (post-revert V5) : seules processing/film-detail restent en v5
        # actif (pas d'equivalent v4). Les autres vues principales sont v4
        # RESTAUREES (cf commentaire app.js "Vues v4 RESTAUREES").
        for view_module in (
            "../views/processing.js",
            "../views/film-detail.js",
        ):
            self.assertIn(view_module, self.app, f"Vue v5 non importee : {view_module}")

    def test_app_imports_v4_views_restored_or_kept(self):
        # V1-05 : vues v4 RESTAUREES post-incident V5 + integrations conservees.
        for v4 in (
            "./views/login.js",
            "./views/status.js",
            "./views/library/library.js",
            "./views/quality.js",
            "./views/qij.js",
            "./views/settings.js",
            "./views/help.js",
            "./views/jellyfin.js",
            "./views/plex.js",
            "./views/radarr.js",
            "./views/logs.js",
        ):
            self.assertIn(v4, self.app, f"Vue v4 manquante : {v4}")

    def test_routes_v5_registered(self):
        for route in ('"/home"', '"/library"', '"/processing"', '"/quality"', '"/settings"', '"/help"', '"/film/:id"'):
            self.assertIn(route, self.app, f"Route v5 manquante : {route}")

    def test_routes_v4_kept(self):
        for route in ('"/jellyfin"', '"/plex"', '"/radarr"', '"/logs"', '"/login"'):
            self.assertIn(route, self.app, f"Route v4 manquante : {route}")

    def test_alias_status_to_home(self):
        # V7 (post-fix dashboard) : /status et /home pointent vers view-status
        # (mount #statusContent) avec initStatus pour conserver le dashboard v4
        # complet (KPIs/services/sante/activite/espace/suggestions/tendance).
        self.assertIn('"/status"', self.app)
        self.assertIn("view-status", self.app)
        self.assertIn("initStatus", self.app)

    def test_mount_v5_shell_function(self):
        self.assertIn("_mountV5Shell", self.app)

    def test_notification_polling(self):
        # Le polling 30s peut etre via startNotificationPolling(30000) ou via
        # le fallback get_notifications_unread_count + setInterval(..., 30000).
        self.assertIn("startNotificationPolling", self.app)
        self.assertIn("30000", self.app)

    def test_v3_04_sidebar_counters_active(self):
        self.assertIn("get_sidebar_counters", self.app)
        self.assertIn("updateSidebarBadges", self.app)

    def test_v3_01_integration_state_active(self):
        self.assertIn("markIntegrationState", self.app)
        # Les 3 integrations doivent etre marquees au boot.
        for label in ('"jellyfin"', '"plex"', '"radarr"'):
            self.assertIn(label, self.app, f"Integration non marquee : {label}")

    def test_v1_13_update_badge_active(self):
        self.assertIn("setUpdateBadge", self.app)
        self.assertIn("get_update_info", self.app)

    def test_v3_05_demo_wizard_init(self):
        self.assertIn("showDemoWizardIfFirstRun", self.app)
        self.assertIn("renderDemoBanner", self.app)

    def test_v3_08_help_fab_mount(self):
        self.assertIn("mountHelpFab", self.app)

    # ------------------------------------------------------------------
    # router.js : support routes parametrees /film/:id
    # ------------------------------------------------------------------

    def test_router_supports_parametrized_routes(self):
        # Le router enrichi doit gerer les patterns ":nom".
        self.assertIn(":", self.router)
        self.assertTrue(
            "_paramRoutes" in self.router or "_matchParamRoute" in self.router,
            "Router sans support routes parametrees (V5B-01 cassee)",
        )

    def test_router_passes_params_to_init(self):
        # init(viewEl, { params }) — pour /film/:id
        self.assertIn("params", self.router)


if __name__ == "__main__":
    unittest.main()
