"""Tests Phase 3.1-D : Paramètres squelette (sub-sidebar 10 catégories, spec 11).

Pose la nouvelle structure de la vue Paramètres. Le contenu détaillé de chaque
catégorie viendra en PRs ultérieures (Phase 3.4 pour Profils Qualité, etc.).
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PARAMETRES_JS = _ROOT / "web" / "dashboard" / "views" / "parametres.js"
_APP_JS = _ROOT / "web" / "dashboard" / "app.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FileExistsTests(unittest.TestCase):
    def test_parametres_view_exists(self) -> None:
        self.assertTrue(_PARAMETRES_JS.is_file(), f"manquant : {_PARAMETRES_JS}")


class EsModuleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PARAMETRES_JS.read_text(encoding="utf-8")

    def test_exports_init_parametres(self) -> None:
        self.assertIn("export async function initParametres(", self.js)

    def test_exports_unmount(self) -> None:
        self.assertIn("export function unmountParametres(", self.js)


class TenCategoriesTests(unittest.TestCase):
    """Spec 11 §2 : 10 catégories listées dans la sub-sidebar."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PARAMETRES_JS.read_text(encoding="utf-8")

    def test_all_10_categories_present(self) -> None:
        expected = [
            "sources",
            "analyse",
            "nommage",
            "bibliotheque",
            "integrations",
            "notifications",
            "serveur",
            "apparence",
            "profils-qualite",
            "avance",
        ]
        for cat in expected:
            self.assertIn(f'id: "{cat}"', self.js, f"catégorie {cat} manquante dans PARAMETRES_CATEGORIES")

    def test_categories_have_french_labels(self) -> None:
        for label in (
            "Sources",
            "Analyse",
            "Nommage",
            "Bibliothèque",
            "Intégrations",
            "Notifications",
            "Serveur distant",
            "Apparence",
            "Profils Qualité",
            "Avancé",
        ):
            self.assertIn(f'label: "{label}"', self.js, f"label {label} manquant")


class SubSidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PARAMETRES_JS.read_text(encoding="utf-8")

    def test_render_sub_sidebar_function(self) -> None:
        # Phase 5 : _renderSubSidebar() sans arg (utilise _state.activeCategory).
        self.assertIn("function _renderSubSidebar(", self.js)

    def test_sub_sidebar_role_navigation(self) -> None:
        self.assertIn('role="navigation"', self.js)

    def test_reset_button_in_footer(self) -> None:
        # Spec : un bouton [Reset] tout en bas de la sub-sidebar.
        self.assertIn('data-parametres-action="reset"', self.js)
        self.assertIn("Réinitialiser", self.js)


class CategoryPanelsTests(unittest.TestCase):
    """Chaque catégorie doit avoir un panneau avec ses champs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PARAMETRES_JS.read_text(encoding="utf-8")

    def test_category_panels_schema_present(self) -> None:
        # Phase 5 : schema declaratif PARAMETRES_GROUPS (au lieu de _CATEGORY_PLACEHOLDERS).
        self.assertIn("PARAMETRES_GROUPS", self.js)

    def test_render_category_panel_function(self) -> None:
        self.assertIn("function _renderCategoryPanel(categoryId)", self.js)

    def test_omdb_visible_in_integrations(self) -> None:
        # Spec 03 : OMDb visible dans integrations apres la migration.
        self.assertIn("OMDb", self.js)
        self.assertIn("omdb_api_key", self.js)


class ExpertModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PARAMETRES_JS.read_text(encoding="utf-8")

    def test_settings_expert_mode_key(self) -> None:
        # Phase 5 : persiste dans settings.expert_mode backend (plus localStorage).
        self.assertIn("expert_mode", self.js)

    def test_toggle_input_present(self) -> None:
        self.assertIn("data-parametres-expert", self.js)

    def test_default_off_via_settings(self) -> None:
        # Le defaut est null/false cote settings backend (apply_settings_defaults).
        # On verifie juste que le toggle lit settings.expert_mode.
        self.assertIn("_state.settings.expert_mode", self.js)


class SearchInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PARAMETRES_JS.read_text(encoding="utf-8")

    def test_search_input_present(self) -> None:
        self.assertIn("data-parametres-search", self.js)
        self.assertIn("Rechercher", self.js)


class StateRestorationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PARAMETRES_JS.read_text(encoding="utf-8")

    def test_remembers_last_category(self) -> None:
        self.assertIn("STORAGE_KEY_LAST_CATEGORY", self.js)
        self.assertIn("cinesort.parametres.last_category", self.js)


class AppJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_imports_init_parametres(self) -> None:
        self.assertIn('from "./views/parametres.js"', self.js)
        self.assertIn("initParametres", self.js)
        self.assertIn("unmountParametres", self.js)

    def test_route_parametres_uses_init_parametres(self) -> None:
        line_start = self.js.find('registerRoute("/parametres"')
        self.assertNotEqual(line_start, -1)
        line_end = self.js.find("\n", line_start)
        snippet = self.js[line_start:line_end]
        self.assertIn("initParametres", snippet)

    def test_legacy_settings_route_kept_for_compat(self) -> None:
        # /settings doit rester pour la retrocompat des bookmarks, mais
        # redirige desormais vers /parametres (la vue legacy settings.js a
        # ete supprimee — son contenu fonctionnel est porte dans parametres.js).
        self.assertIn('registerRoute("/settings"', self.js)
        # La route /settings ne doit plus appeler initSettings/unmountSettings :
        # la vue legacy est supprimee. Elle redirige vers /parametres.
        self.assertNotIn("initSettings", self.js)
        self.assertNotIn("unmountSettings", self.js)
        # Verifie la redirection vers /parametres avec preservation du fragment.
        line_start = self.js.find('registerRoute("/settings"')
        self.assertNotEqual(line_start, -1)
        # Le bloc d'init peut tenir sur plusieurs lignes (flecha fn multilignes).
        # On cherche la fermeture du registerRoute en repérant '});'.
        block_end = self.js.find("});", line_start)
        snippet = self.js[line_start:block_end]
        self.assertIn("#/parametres", snippet)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_root_class(self) -> None:
        self.assertIn(".parametres-view", self.css)

    def test_grid_layout(self) -> None:
        self.assertIn(".parametres-grid", self.css)
        # Sub-sidebar 220px + main flex.
        self.assertIn("grid-template-columns: 220px 1fr", self.css)

    def test_sub_sidebar_classes(self) -> None:
        self.assertIn(".parametres-sub-sidebar", self.css)
        self.assertIn(".parametres-sub-item", self.css)
        self.assertIn(".parametres-sub-item.is-active", self.css)

    def test_main_panel_class(self) -> None:
        self.assertIn(".parametres-main", self.css)
        self.assertIn(".parametres-panel-title", self.css)

    def test_responsive_breakpoint(self) -> None:
        # Sub-sidebar plus etroite < 1024px.
        self.assertIn("@media (max-width: 1024px)", self.css)

    def test_expert_mode_advanced_selector(self) -> None:
        # Mode expert masque les champs data-advanced="true".
        self.assertIn('.parametres-view:not(.is-expert) [data-advanced="true"]', self.css)


if __name__ == "__main__":
    unittest.main()
