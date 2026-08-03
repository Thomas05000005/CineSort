"""Tests Phase 3.2 : Bibliothèque grille complète (spec 07)."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BIBLIOTHEQUE_JS = _ROOT / "web" / "dashboard" / "views" / "bibliotheque.js"
_APP_JS = _ROOT / "web" / "dashboard" / "app.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FileExistsTests(unittest.TestCase):
    def test_view_exists(self) -> None:
        self.assertTrue(_BIBLIOTHEQUE_JS.is_file())


class EsModuleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_exports_init(self) -> None:
        self.assertIn("export async function initBibliotheque(", self.js)

    def test_exports_unmount(self) -> None:
        self.assertIn("export function unmountBibliotheque(", self.js)


class ToolbarTests(unittest.TestCase):
    """Spec 07 §1 : recherche, tri, toggle vue."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_search_input(self) -> None:
        self.assertIn("data-bibliotheque-search", self.js)

    def test_sort_dropdown(self) -> None:
        self.assertIn("data-bibliotheque-sort", self.js)

    def test_view_toggle_grid_table(self) -> None:
        self.assertIn('data-bibliotheque-view="grid"', self.js)
        self.assertIn('data-bibliotheque-view="table"', self.js)

    def test_filters_button(self) -> None:
        self.assertIn('data-bibliotheque-action="filters"', self.js)


class TierChipsTests(unittest.TestCase):
    """Spec 07 §2 : chips de filtres tier (5 tiers + Tous)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_tier_attribute(self) -> None:
        self.assertIn("data-bibliotheque-tier", self.js)

    def test_tier_order_contains_main_tiers(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject", "unknown"):
            self.assertIn(f'"{tier}"', self.js, f"tier {tier} manquant")


class GridAndSelectionTests(unittest.TestCase):
    """Spec 07 §5 : sélection multi + toolbar bulk."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_select_checkbox(self) -> None:
        self.assertIn("data-bibliotheque-select", self.js)

    def test_bulk_actions_present(self) -> None:
        for action in ("perceptual", "rescan", "export", "delete", "clear"):
            self.assertIn(f'data-bibliotheque-bulk="{action}"', self.js)

    def test_film_card_renders(self) -> None:
        self.assertIn("function _renderFilmCard(row)", self.js)

    def test_navigates_to_film_detail(self) -> None:
        # Phase 5 spec 06 : clic carte -> renderFilmDetail(mode A/C) au lieu
        # de navigateTo("/film/:id"). Le composant film-detail est utilise.
        self.assertIn("renderFilmDetail", self.js)
        self.assertIn('mode: "A"', self.js)


class PaginationTests(unittest.TestCase):
    """Spec 07 §8 : Phase 5 - remplace prev/next par scroll infini (IntersectionObserver)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_infinite_scroll_observer(self) -> None:
        self.assertIn("IntersectionObserver", self.js)
        self.assertIn("data-bibliotheque-sentinel", self.js)

    def test_page_size_constant(self) -> None:
        self.assertIn("PAGE_SIZE = 200", self.js)


class DataFetchTests(unittest.TestCase):
    """Spec 07 §7 : utilise library/get_library_filtered."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_endpoint(self) -> None:
        self.assertIn("library/get_library_filtered", self.js)

    def test_filters_payload(self) -> None:
        self.assertIn("tier_v2", self.js)


class AppJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_imports(self) -> None:
        self.assertIn('from "./views/bibliotheque.js"', self.js)
        self.assertIn("initBibliotheque", self.js)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_classes(self) -> None:
        for cls in (
            ".bibliotheque-view",
            ".bibliotheque-header",
            ".bibliotheque-toolbar",
            ".bibliotheque-search",
            ".bibliotheque-grid",
            ".bibliotheque-card",
            ".bibliotheque-card-poster",
            ".bibliotheque-chips",
            ".bibliotheque-chip",
            ".bibliotheque-bulk-toolbar",
            ".bibliotheque-pagination",
            ".bibliotheque-tier-badge",
        ):
            self.assertIn(cls, self.css)

    def test_tier_badge_variants(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject", "unknown"):
            self.assertIn(f".bibliotheque-tier-badge--{tier}", self.css)


if __name__ == "__main__":
    unittest.main()
