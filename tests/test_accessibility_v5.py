"""Tests Vague 10 v7.6.0 — Audit accessibilite statique des composants v5.

Verifie que chaque composant v5 expose :
- aria-label / aria-labelledby sur les zones interactives
- role approprie (tab, tablist, button, dialog, menu, listitem...)
- aria-hidden sur les overlays fermes
- support clavier (tabindex, key handlers)
- focus management (focus first el, restore focus)

On ne lance pas de navigateur : on lit le source et on verifie les patterns.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_COMPONENTS = _ROOT / "web" / "components"
_VIEWS = _ROOT / "web" / "views"
# V2-D : composants/vues du dashboard distant (SPA web).
_DASH_COMPONENTS = _ROOT / "web" / "dashboard" / "components"
_DASH_VIEWS = _ROOT / "web" / "dashboard" / "views"
_DASH_INDEX = _ROOT / "web" / "dashboard" / "index.html"
_DASH_DOM = _ROOT / "web" / "dashboard" / "core" / "dom.js"


class SidebarV5AccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_COMPONENTS / "sidebar-v5.js").read_text(encoding="utf-8")

    def test_has_role_tab(self) -> None:
        self.assertIn('role="tab"', self.js)

    def test_has_aria_selected(self) -> None:
        self.assertIn("aria-selected", self.js)

    def test_has_aria_label(self) -> None:
        self.assertIn("aria-label", self.js)

    def test_keyboard_arrow_support(self) -> None:
        for key in ("ArrowDown", "ArrowUp", "Home", "End"):
            self.assertIn(f'"{key}"', self.js)


class TopBarV5AccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_COMPONENTS / "top-bar-v5.js").read_text(encoding="utf-8")

    def test_search_button_aria_label(self) -> None:
        self.assertIn("aria-label", self.js)
        self.assertIn("recherche", self.js.lower())

    def test_theme_button_aria_haspopup(self) -> None:
        self.assertIn("aria-haspopup", self.js)

    def test_theme_menu_role(self) -> None:
        self.assertIn('role="menu"', self.js)

    def test_theme_items_role(self) -> None:
        self.assertIn('role="menuitemradio"', self.js)
        self.assertIn("aria-checked", self.js)

    def test_banner_role(self) -> None:
        self.assertIn('role="banner"', self.js)


class BreadcrumbAccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_COMPONENTS / "breadcrumb.js").read_text(encoding="utf-8")

    def test_aria_current(self) -> None:
        self.assertIn("aria-current", self.js)

    def test_aria_label(self) -> None:
        self.assertIn("aria-label", self.js)


class NotificationCenterAccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_COMPONENTS / "notification-center.js").read_text(encoding="utf-8")

    def test_drawer_role_complementary(self) -> None:
        self.assertIn('"role"', self.js)
        self.assertIn("complementary", self.js)

    def test_drawer_aria_hidden(self) -> None:
        self.assertIn("aria-hidden", self.js)

    def test_drawer_aria_label(self) -> None:
        self.assertIn("Centre de notifications", self.js)

    def test_filters_role_tablist(self) -> None:
        self.assertIn('role="tablist"', self.js)

    def test_filter_buttons_role_tab(self) -> None:
        self.assertIn('role="tab"', self.js)
        self.assertIn("aria-selected", self.js)

    def test_items_role_listitem(self) -> None:
        self.assertIn('role="listitem"', self.js)

    def test_dismiss_button_aria_label(self) -> None:
        self.assertIn('aria-label="Supprimer', self.js)

    def test_focus_first_element_on_open(self) -> None:
        # Verification que le drawer focus un element au open (a11y)
        self.assertTrue(re.search(r"\.focus\(\)", self.js), "notification-center.js doit focus un element au open()")

    def test_escape_closes_drawer(self) -> None:
        self.assertIn('e.key === "Escape"', self.js)


class LibraryV5AccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_VIEWS / "library-v5.js").read_text(encoding="utf-8")

    def test_has_aria_attributes(self) -> None:
        # Au moins un aria-* doit etre present
        self.assertTrue(re.search(r"aria-\w+", self.js), "library-v5.js devrait avoir des attributs aria")


class FilmDetailAccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_VIEWS / "film-detail.js").read_text(encoding="utf-8")

    def test_has_tablist_or_navigation(self) -> None:
        # Les tabs Apercu/Analyse/Historique/Comparaison doivent etre accessibles
        has_aria = bool(re.search(r"aria-\w+", self.js))
        has_role = bool(re.search(r'role="(tab|tablist|navigation|main)"', self.js))
        self.assertTrue(has_aria or has_role, "film-detail doit avoir aria-* ou role tab/tablist")


class ProcessingV5AccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_VIEWS / "processing.js").read_text(encoding="utf-8")

    def test_has_aria_attributes(self) -> None:
        self.assertTrue(re.search(r"aria-\w+", self.js), "processing doit avoir des attributs aria (stepper + boutons)")


class SettingsV5AccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_VIEWS / "settings-v5.js").read_text(encoding="utf-8")

    def test_fields_have_labels(self) -> None:
        self.assertTrue(re.search(r"<label|aria-label", self.js), "settings-v5 doit exposer des labels aux fields")


class QijV5AccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_VIEWS / "qij-v5.js").read_text(encoding="utf-8")

    def test_has_aria_attributes(self) -> None:
        self.assertTrue(re.search(r"aria-\w+", self.js), "qij-v5 doit avoir des attributs aria")


# ---------------------------------------------------------------------------
# CSS accessibility : reduced motion + focus outline
# ---------------------------------------------------------------------------


class CssAccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")
        self.anim = (_ROOT / "web" / "shared" / "animations.css").read_text(encoding="utf-8")

    def test_reduced_motion_support(self) -> None:
        # Les animations doivent etre desactivables
        has_reduced = "prefers-reduced-motion" in self.anim or "prefers-reduced-motion" in self.css
        self.assertTrue(has_reduced, "Support prefers-reduced-motion requis")

    def test_focus_visible_styles(self) -> None:
        # Au moins un :focus-visible ou outline custom doit etre defini
        has_focus = ":focus-visible" in self.css or ":focus" in self.css
        self.assertTrue(has_focus, "Styles de focus requis")


# ---------------------------------------------------------------------------
# Global : nombre minimum d'aria-* par composant v5
# ---------------------------------------------------------------------------


class ComponentsAriaBaselineTests(unittest.TestCase):
    V5_COMPONENTS = [
        "sidebar-v5.js",
        "top-bar-v5.js",
        "breadcrumb.js",
        "notification-center.js",
    ]

    def test_all_v5_components_have_aria(self) -> None:
        for fname in self.V5_COMPONENTS:
            src = (_COMPONENTS / fname).read_text(encoding="utf-8")
            aria_count = len(re.findall(r"aria-\w+", src))
            self.assertGreaterEqual(
                aria_count, 2, f"{fname} doit avoir au moins 2 attributs aria-*, trouve {aria_count}"
            )


# ---------------------------------------------------------------------------
# V2-D — Tests WCAG 2.2 AA pour le dashboard SPA (Polish Total v7.7.0)
# ---------------------------------------------------------------------------


class DashboardModalFocusTrapTests(unittest.TestCase):
    """V2-D Fix 1 : modal.js du dashboard doit exposer trapFocus() (WCAG 2.1.2)."""

    def setUp(self) -> None:
        self.js = (_DASH_COMPONENTS / "modal.js").read_text(encoding="utf-8")

    def test_trap_focus_exported(self) -> None:
        self.assertIn("export function trapFocus", self.js)

    def test_trap_focus_handles_tab_and_shift(self) -> None:
        self.assertIn('e.key !== "Tab"', self.js)
        self.assertIn("shiftKey", self.js)

    def test_focusable_selector_defined(self) -> None:
        # Selecteur des elements focusables (a, button, input, select, textarea, [tabindex]).
        for token in ("button:not([disabled])", "[tabindex]"):
            self.assertIn(token, self.js)

    def test_show_modal_calls_trap_focus(self) -> None:
        self.assertIn("trapFocus(overlay)", self.js)

    def test_close_modal_restores_focus(self) -> None:
        self.assertIn("_previouslyFocused", self.js)


class DashboardAriaLiveAtomicTests(unittest.TestCase):
    """V2-D Fix 2 : conteneurs aria-live doivent avoir aria-atomic='true'."""

    def setUp(self) -> None:
        self.html = _DASH_INDEX.read_text(encoding="utf-8")

    def test_all_aria_live_have_aria_atomic(self) -> None:
        # Compter aria-live="polite" vs aria-atomic="true" — ils doivent matcher.
        live_count = self.html.count('aria-live="polite"')
        atomic_count = self.html.count('aria-atomic="true"')
        self.assertGreater(live_count, 0, "Il doit y avoir au moins un conteneur aria-live")
        self.assertGreaterEqual(
            atomic_count,
            live_count,
            f"aria-atomic='true' ({atomic_count}) doit etre present sur chaque "
            f"aria-live ({live_count}) pour annonces completes",
        )


class DashboardAriaBusyHelperTests(unittest.TestCase):
    """V2-D Fix 3 : core/dom.js doit exporter setBusy / withBusy."""

    def setUp(self) -> None:
        self.js = _DASH_DOM.read_text(encoding="utf-8")

    def test_set_busy_exported(self) -> None:
        self.assertIn("export function setBusy", self.js)

    def test_with_busy_exported(self) -> None:
        self.assertIn("export async function withBusy", self.js)

    def test_with_busy_uses_finally(self) -> None:
        # Garantit aria-busy=false meme en cas d'erreur du fetch.
        self.assertIn("finally", self.js)


class DashboardAriaBusyViewsTests(unittest.TestCase):
    """V2-D Fix 3 : les vues critiques doivent toggle aria-busy autour des fetches."""

    def test_status_toggles_aria_busy(self) -> None:
        js = (_DASH_VIEWS / "status.js").read_text(encoding="utf-8")
        self.assertIn('setAttribute("aria-busy"', js)

    def test_library_toggles_aria_busy(self) -> None:
        js = (_DASH_VIEWS / "library.js").read_text(encoding="utf-8")
        self.assertIn('setAttribute("aria-busy"', js)

    def test_qij_toggles_aria_busy(self) -> None:
        js = (_DASH_VIEWS / "qij.js").read_text(encoding="utf-8")
        self.assertIn('setAttribute("aria-busy"', js)

    def test_settings_toggles_aria_busy(self) -> None:
        js = (_DASH_VIEWS / "settings.js").read_text(encoding="utf-8")
        self.assertIn('setAttribute("aria-busy"', js)


class DashboardThemeMenuAccessibilityTests(unittest.TestCase):
    """V2-D Fix 4 + Fix 5 : top-bar-v5.js dropdown theme."""

    def setUp(self) -> None:
        self.js = (_DASH_COMPONENTS / "top-bar-v5.js").read_text(encoding="utf-8")

    def test_theme_button_has_aria_expanded(self) -> None:
        # Initial render : aria-expanded="false"
        self.assertIn('aria-expanded="false"', self.js)

    def test_aria_expanded_toggled_on_click(self) -> None:
        # Le helper setMenuOpen doit synchroniser aria-expanded.
        self.assertIn('setAttribute("aria-expanded"', self.js)

    def test_arrow_keys_navigation(self) -> None:
        for key in ("ArrowDown", "ArrowUp", "Home", "End"):
            self.assertIn(f'"{key}"', self.js)

    def test_escape_closes_menu(self) -> None:
        self.assertIn('"Escape"', self.js)

    def test_enter_or_space_activates(self) -> None:
        # Activation Enter ou Space doit declencher le click sur l'item courant.
        self.assertTrue('"Enter"' in self.js or '" "' in self.js)

    def test_roving_tabindex(self) -> None:
        # Pattern roving tabindex : un seul tabindex=0 a la fois sur les items.
        # Initial render dans un template literal : tabindex="${i === 0 ? "0" : "-1"}"
        self.assertIn('"-1"', self.js)
        # Reaffectation dynamique via setAttribute("tabindex", ...)
        self.assertIn('setAttribute("tabindex"', self.js)


class DashboardTableSortableKeyboardTests(unittest.TestCase):
    """V2-D Fix 6 : table.js .th-sortable doit accepter Space/Enter au clavier."""

    def setUp(self) -> None:
        self.js = (_DASH_COMPONENTS / "table.js").read_text(encoding="utf-8")

    def test_th_sortable_has_keydown_handler(self) -> None:
        self.assertIn('addEventListener("keydown"', self.js)

    def test_handles_enter_and_space(self) -> None:
        # Active sur Enter ou Space (avec preventDefault pour eviter scroll).
        self.assertIn('"Enter"', self.js)
        self.assertIn("preventDefault", self.js)

    def test_th_sortable_is_focusable(self) -> None:
        # tabindex="0" + role columnheader pour l'accessibilite clavier.
        self.assertIn('tabindex="0"', self.js)
        self.assertIn('role="columnheader"', self.js)


class DashboardSettingsRequiredFieldsTests(unittest.TestCase):
    """V2-D Fix 7 : champs obligatoires marques aria-required + asterisque rouge."""

    def setUp(self) -> None:
        self.js = (_DASH_VIEWS / "settings.js").read_text(encoding="utf-8")

    def test_roots_field_marked_required(self) -> None:
        # Le champ roots doit avoir required: true dans le schema.
        self.assertRegex(self.js, r'key:\s*"roots".*required:\s*true', "Le champ 'roots' doit etre required")

    def test_tmdb_api_key_marked_required(self) -> None:
        # Le champ tmdb_api_key est defini sur plusieurs lignes — match multi-ligne.
        self.assertRegex(
            self.js,
            r'key:\s*"tmdb_api_key"[\s\S]*?required:\s*true',
            "tmdb_api_key doit etre required",
        )

    def test_renderer_emits_aria_required(self) -> None:
        self.assertIn('aria-required="true"', self.js)

    def test_renderer_emits_required_attr(self) -> None:
        # required HTML attribute pour validation native du browser.
        self.assertIn('aria-required="true" required', self.js)

    def test_renderer_emits_red_asterisk(self) -> None:
        # Marque visuelle * en rouge (aria-hidden pour eviter double annonce).
        self.assertIn("v5-settings-required", self.js)
        self.assertIn('aria-hidden="true"', self.js)


if __name__ == "__main__":
    unittest.main()
