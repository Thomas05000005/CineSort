"""Tests Phase 2-A : composant RightPanel (inspecteur droit du Shell 3 zones).

Spec : docs/internal/design/refonte_2026_05_17/screens/04-shell-3-zones.md §4.
Couvre :
- Existence du composant ESM web/dashboard/components/right-panel.js
- API publique exportee (render, setSections, setExpanded, adaptToRoute, ...)
- Mount point HTML present dans web/dashboard/index.html
- Styles CSS du right panel dans web/shared/components.css
- Integration dans web/dashboard/app.js (import + mount + sync route)
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_RIGHT_PANEL_JS = _ROOT / "web" / "dashboard" / "components" / "right-panel.js"
_DASHBOARD_HTML = _ROOT / "web" / "dashboard" / "index.html"
_DASHBOARD_APP_JS = _ROOT / "web" / "dashboard" / "app.js"
_SHARED_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class RightPanelFileTests(unittest.TestCase):
    def test_component_file_exists(self) -> None:
        self.assertTrue(_RIGHT_PANEL_JS.is_file(), f"manquant : {_RIGHT_PANEL_JS}")


class RightPanelApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _RIGHT_PANEL_JS.read_text(encoding="utf-8")

    def test_exports_render(self) -> None:
        self.assertIn("export function render(", self.js)

    def test_exports_set_sections(self) -> None:
        self.assertIn("export function setSections(", self.js)

    def test_exports_set_expanded(self) -> None:
        self.assertIn("export function setExpanded(", self.js)

    def test_exports_is_expanded(self) -> None:
        self.assertIn("export function isExpanded(", self.js)

    def test_exports_set_width(self) -> None:
        self.assertIn("export function setWidth(", self.js)

    def test_exports_reset(self) -> None:
        self.assertIn("export function reset(", self.js)

    def test_exports_adapt_to_route(self) -> None:
        self.assertIn("export function adaptToRoute(", self.js)

    def test_width_bounds_280_to_600(self) -> None:
        # Spec 06 Modal Detail Film : mode A peut aller jusqu'a 600px (au lieu
        # de 480 initialement) pour afficher hero + candidats TMDb confortablement.
        self.assertIn("MIN_WIDTH = 280", self.js)
        self.assertIn("MAX_WIDTH = 600", self.js)
        self.assertIn("DEFAULT_WIDTH = 360", self.js)

    def test_route_defaults_collapsed_on_synthese_views(self) -> None:
        # Spec 04 : Accueil / Parametres / Aide -> inspecteur replie par defaut.
        for route in ("/accueil", "/home", "/parametres", "/settings", "/aide", "/help", "/login"):
            self.assertIn(f'"{route}": false', self.js, f"route {route} doit etre collapsed par defaut")

    def test_route_defaults_expanded_on_expert_views(self) -> None:
        # Spec 04 : Traitement / Bibliotheque / Qualite / Historique -> visible.
        for route in ("/traitement", "/processing", "/bibliotheque", "/library", "/qualite", "/historique"):
            self.assertIn(f'"{route}": true', self.js, f"route {route} doit etre expanded par defaut")

    def test_localstorage_keys_namespaced(self) -> None:
        # Anti-collision avec d'autres composants : prefixe cinesort.rightpanel.*
        self.assertIn("cinesort.rightpanel.expanded", self.js)
        self.assertIn("cinesort.rightpanel.width", self.js)

    def test_uses_escape_html_for_user_content(self) -> None:
        # Garde XSS : sections.title doit etre echappe (sections.html est marque trusted).
        self.assertIn("escapeHtml(section.title)", self.js)


class DashboardHtmlMountPointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _DASHBOARD_HTML.read_text(encoding="utf-8")

    def test_mount_point_present(self) -> None:
        self.assertIn('id="v5RightPanelMount"', self.html)

    def test_mount_point_is_aside_with_role_complementary(self) -> None:
        self.assertIn('<aside id="v5RightPanelMount"', self.html)
        self.assertIn('role="complementary"', self.html)

    def test_mount_point_has_aria_label(self) -> None:
        self.assertIn('aria-label="Inspecteur"', self.html)

    def test_mount_point_inside_app_shell(self) -> None:
        # Doit etre dans <div id="app-shell"> avec sidebar et main.
        shell_start = self.html.find('id="app-shell"')
        mount_pos = self.html.find('id="v5RightPanelMount"')
        self.assertGreater(shell_start, 0)
        self.assertGreater(mount_pos, shell_start)


class DashboardAppJsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DASHBOARD_APP_JS.read_text(encoding="utf-8")

    def test_imports_right_panel(self) -> None:
        self.assertIn('from "./components/right-panel.js"', self.js)

    def test_calls_right_panel_render(self) -> None:
        self.assertIn("rightPanel.render(rightPanelMount)", self.js)

    def test_listens_hashchange_to_sync_route(self) -> None:
        self.assertIn("rightPanel.adaptToRoute(", self.js)

    def test_acquires_right_panel_mount_element(self) -> None:
        self.assertIn('getElementById("v5RightPanelMount")', self.js)


class RightPanelCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _SHARED_COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_root_class_defined(self) -> None:
        self.assertIn(".v5-right-panel {", self.css)

    def test_collapsed_state_defined(self) -> None:
        self.assertIn(".v5-right-panel.is-collapsed", self.css)

    def test_handle_for_resize_defined(self) -> None:
        self.assertIn(".v5-right-panel-handle", self.css)
        self.assertIn("cursor: col-resize", self.css)

    def test_default_width_360(self) -> None:
        # Le default width doit etre 360px pour matcher la spec et le JS.
        v5_block_start = self.css.find(".v5-right-panel {")
        v5_block_end = self.css.find("}", v5_block_start)
        block = self.css[v5_block_start:v5_block_end]
        self.assertIn("width: 360px", block)

    def test_bounds_match_js_constants(self) -> None:
        # min-width: 280px, max-width: 600px doivent correspondre aux constantes JS.
        # Spec 06 Modal Detail Film : MAX_WIDTH eleve de 480 a 600 pour mode A.
        self.assertIn("min-width: 280px", self.css)
        self.assertIn("max-width: 600px", self.css)

    def test_section_title_uppercase_label(self) -> None:
        # Convention design v5 : section title en uppercase pour la hierarchie visuelle.
        self.assertIn(".v5-right-panel-section-title", self.css)
        self.assertIn("text-transform: uppercase", self.css)


if __name__ == "__main__":
    unittest.main()
