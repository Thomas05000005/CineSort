"""Tests Vague 1 v7.6.0 — Navigation v5 + Command Palette.

Couvre :
- 3 composants desktop IIFE : sidebar-v5.js, top-bar-v5.js, breadcrumb.js
- 3 versions ES module dashboard equivalentes
- API window.SidebarV5 / window.TopBarV5 / window.BreadcrumbV5
- window.CommandPalette wrapper autour de l'existant
- router.js : route /film/:id, /settings/:cat, aliases processing/journal/integrations
- CSS v5 des composants (classes + animations)
- Integration index.html (scripts charges)
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Desktop IIFE components
# ---------------------------------------------------------------------------


class SidebarV5DesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "components" / "sidebar-v5.js").read_text(encoding="utf-8")

    def test_file_exists(self) -> None:
        self.assertTrue((_ROOT / "web" / "components" / "sidebar-v5.js").exists())

    def test_exposes_sidebar_v5_global(self) -> None:
        self.assertIn("window.SidebarV5", self.js)

    def test_api_methods_exposed(self) -> None:
        for fn in ("render", "setActive", "toggleCollapsed", "isCollapsed"):
            self.assertIn(fn, self.js)

    def test_7_nav_items_defined(self) -> None:
        for route in ("home", "processing", "library", "quality", "journal", "integrations", "settings"):
            self.assertIn(f'id: "{route}"', self.js)

    def test_each_item_has_shortcut(self) -> None:
        for i in range(1, 8):
            self.assertIn(f'"Alt+{i}"', self.js)

    def test_collapse_persisted_localStorage(self) -> None:
        self.assertIn("cinesort.sidebar.collapsed", self.js)
        self.assertIn("localStorage", self.js)

    def test_keyboard_arrow_navigation(self) -> None:
        for key in ("ArrowDown", "ArrowUp", "Home", "End"):
            self.assertIn(f'"{key}"', self.js)

    def test_accessibility(self) -> None:
        self.assertIn('role="tab"', self.js)
        self.assertIn("aria-selected", self.js)
        self.assertIn("aria-label", self.js)


class TopBarV5DesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "components" / "top-bar-v5.js").read_text(encoding="utf-8")

    def test_exposes_top_bar_v5_global(self) -> None:
        self.assertIn("window.TopBarV5", self.js)

    def test_api_methods_exposed(self) -> None:
        for fn in ("render", "setNotificationCount", "setTheme"):
            self.assertIn(fn, self.js)

    def test_4_themes_defined(self) -> None:
        for t in ("studio", "cinema", "luxe", "neon"):
            self.assertIn(f'"{t}"', self.js)

    def test_search_trigger_with_cmdk_hint(self) -> None:
        self.assertIn("Cmd+K", self.js)
        self.assertIn("data-v5-search-trigger", self.js)

    def test_notification_badge_dynamic(self) -> None:
        self.assertIn("data-v5-notif-badge", self.js)
        self.assertIn("99+", self.js)

    def test_theme_menu_aria(self) -> None:
        self.assertIn('role="menu"', self.js)
        self.assertIn("aria-haspopup", self.js)


class BreadcrumbDesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "components" / "breadcrumb.js").read_text(encoding="utf-8")

    def test_exposes_breadcrumb_v5_global(self) -> None:
        self.assertIn("window.BreadcrumbV5", self.js)

    def test_render_function(self) -> None:
        self.assertIn("function render", self.js)

    def test_accessibility(self) -> None:
        self.assertIn("aria-label", self.js)
        self.assertIn("aria-current", self.js)


# ---------------------------------------------------------------------------
# Dashboard ES modules
# ---------------------------------------------------------------------------


class SidebarV5DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "dashboard" / "components" / "sidebar-v5.js").read_text(encoding="utf-8")

    def test_es_module_exports(self) -> None:
        for exp in (
            "export function render",
            "export function setActive",
            "export function toggleCollapsed",
            "export function isCollapsed",
            "export const NAV_ITEMS",
        ):
            self.assertIn(exp, self.js)

    def test_imports_escapeHtml(self) -> None:
        self.assertIn('import { escapeHtml } from "../core/dom.js"', self.js)

    def test_nav_items_parity(self) -> None:
        # V5A-01 : "integrations" avait ete eclate en jellyfin/plex/radarr +
        # entree "help" (Alt+8).
        # V7-fusion Phase 3 : QIJ remplace 5 items distincts (Quality, Journal,
        # Jellyfin, Plex, Radarr). La sidebar a 6 items : home, processing,
        # library, qij, settings, help. Cf commentaire dans sidebar-v5.js.
        for route in (
            "home",
            "processing",
            "library",
            "qij",
            "settings",
            "help",
        ):
            self.assertIn(f'id: "{route}"', self.js)
        # Les anciens items consolides ne doivent plus etre presents en
        # tant qu'entrees sidebar.
        for removed in ("journal", "jellyfin", "plex", "radarr"):
            self.assertNotIn(f'id: "{removed}"', self.js)


class TopBarV5DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "dashboard" / "components" / "top-bar-v5.js").read_text(encoding="utf-8")

    def test_es_module_exports(self) -> None:
        for exp in (
            "export function render",
            "export function setNotificationCount",
            "export function setTheme",
            "export const THEMES",
        ):
            self.assertIn(exp, self.js)


class BreadcrumbDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "dashboard" / "components" / "breadcrumb.js").read_text(encoding="utf-8")

    def test_es_module_export(self) -> None:
        self.assertIn("export function render", self.js)


# ---------------------------------------------------------------------------
# Command Palette v5 wrapper
# ---------------------------------------------------------------------------


class CommandPaletteV5WrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "components" / "command-palette.js").read_text(encoding="utf-8")

    def test_window_command_palette_api(self) -> None:
        self.assertIn("window.CommandPalette", self.js)
        self.assertIn("open:", self.js)
        self.assertIn("close:", self.js)
        self.assertIn("isOpen:", self.js)

    def test_legacy_open_preserved(self) -> None:
        self.assertIn("window.openCommandPalette", self.js)

    def test_cmdk_hotkey_still_global(self) -> None:
        # Backward compat : Cmd+K / Ctrl+K continue de fonctionner
        self.assertIn("ctrlKey || e.metaKey", self.js)
        self.assertIn('e.key === "k"', self.js)


# ---------------------------------------------------------------------------
# Router (route /film/:id, aliases, breadcrumb)
# ---------------------------------------------------------------------------


class RouterV5Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "core" / "router.js").read_text(encoding="utf-8")

    def test_new_view_labels_v5(self) -> None:
        for v in ("processing", "journal", "integrations"):
            self.assertIn(f"{v}:", self.js)

    def test_parse_route_function(self) -> None:
        self.assertIn("function parseRoute", self.js)
        self.assertIn('view: "film"', self.js)

    def test_build_breadcrumb_function(self) -> None:
        self.assertIn("function buildBreadcrumb", self.js)

    def test_route_aliases_transitoires(self) -> None:
        self.assertIn("ROUTE_ALIASES", self.js)
        # Vague 5 : processing n'est plus un alias (vraie vue dediee)
        self.assertNotIn('processing: "validation"', self.js)
        # Vague 7 : journal et integrations sont des vraies vues QIJ V5
        self.assertNotIn('journal: "history"', self.js)
        self.assertNotIn('integrations: "jellyfin"', self.js)

    def test_navigateTo_handles_aliases(self) -> None:
        # verifier qu'on utilise ROUTE_ALIASES dans navigateTo
        self.assertIn("ROUTE_ALIASES[view]", self.js)


# ---------------------------------------------------------------------------
# CSS shared/components.css — classes Vague 1
# ---------------------------------------------------------------------------


class CssVague1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")

    def test_sidebar_classes(self) -> None:
        for cls in (
            ".v5-sidebar",
            ".v5-sidebar-item",
            ".v5-sidebar-nav",
            ".v5-sidebar.is-collapsed",
            ".v5-sidebar-item.is-active",
        ):
            self.assertIn(cls, self.css)

    def test_top_bar_classes(self) -> None:
        for cls in (".v5-top-bar", ".v5-top-bar-search", ".v5-top-bar-notif-badge", ".v5-top-bar-theme-menu"):
            self.assertIn(cls, self.css)

    def test_breadcrumb_classes(self) -> None:
        for cls in (".v5-breadcrumb", ".v5-breadcrumb-link", ".v5-breadcrumb-current", ".v5-breadcrumb-sep"):
            self.assertIn(cls, self.css)

    def test_palette_v5_classes(self) -> None:
        for cls in (
            ".v5-palette-overlay",
            ".v5-palette",
            ".v5-palette-input",
            ".v5-palette-item",
            ".v5-palette-category",
        ):
            self.assertIn(cls, self.css)

    def test_collapsed_sidebar_has_transition(self) -> None:
        # La transition width doit etre presente pour le collapse anime
        self.assertIn("transition: width", self.css)


# ---------------------------------------------------------------------------
# Integration index.html
# ---------------------------------------------------------------------------


class IndexHtmlVague1Tests(unittest.TestCase):
    def test_desktop_loads_nav_v5_scripts(self) -> None:
        html = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for src in ("sidebar-v5.js", "top-bar-v5.js", "breadcrumb.js"):
            self.assertIn(src, html)


# ---------------------------------------------------------------------------
# Node smoke test : exports dashboard ES modules
# ---------------------------------------------------------------------------


class DashboardSmokeTests(unittest.TestCase):
    def test_dashboard_modules_import_cleanly(self) -> None:
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
                "Promise.all(["
                "import('./web/dashboard/components/sidebar-v5.js'),"
                "import('./web/dashboard/components/top-bar-v5.js'),"
                "import('./web/dashboard/components/breadcrumb.js'),"
                "]).then(([s,t,b]) => {"
                "console.log('S:' + Object.keys(s).sort().join(','));"
                "console.log('T:' + Object.keys(t).sort().join(','));"
                "console.log('B:' + Object.keys(b).sort().join(','));"
                "})",
            ],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # V5A-01 : exports enrichis (markIntegrationState/setUpdateBadge/updateSidebarBadges).
        self.assertIn(
            "S:NAV_ITEMS,isCollapsed,markIntegrationState,render,setActive,"
            "setUpdateBadge,toggleCollapsed,updateSidebarBadges",
            result.stdout,
        )
        # V5A-02 : exports top-bar enrichis (mountHelpFab, updateNotificationBadge, etc.)
        self.assertIn(
            "T:THEMES,mountHelpFab,render,setNotificationCount,setTheme,unmountHelpFab,updateNotificationBadge",
            result.stdout,
        )
        self.assertIn("B:render", result.stdout)


if __name__ == "__main__":
    unittest.main()
