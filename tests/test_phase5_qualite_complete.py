"""Tests Phase 5 : completion vue Qualite (spec 10-qualite.md).

Verifie que les 4 sections placeholders (Reject, Sagas, Decennies, Evolution)
sont desormais cablees sur les endpoints PR #304, que le drawer de filtres
globaux existe, et que le bouton Re-calculer scores utilise dangerConfirmModal
+ polling toast.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_QUALITE_JS = _ROOT / "web" / "dashboard" / "views" / "qualite.js"
_DRAWER_JS = _ROOT / "web" / "dashboard" / "components" / "qualite-filters-drawer.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FileExistsTests(unittest.TestCase):
    """Verifie que les fichiers cibles existent."""

    def test_view_exists(self) -> None:
        self.assertTrue(_QUALITE_JS.is_file())

    def test_drawer_component_exists(self) -> None:
        self.assertTrue(_DRAWER_JS.is_file())


class RejectSectionWiringTests(unittest.TestCase):
    """Section 2 Reject : grille 4x2 cablee sur get_films_by_tier."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_calls_get_films_by_tier(self) -> None:
        self.assertIn('apiPost("quality/get_films_by_tier"', self.js)

    def test_uses_limit_8(self) -> None:
        self.assertIn("limit: 8", self.js)

    def test_renders_grid(self) -> None:
        self.assertIn("qualite-reject-grid", self.js)

    def test_renders_cards(self) -> None:
        self.assertIn("qualite-reject-card", self.js)

    def test_empty_state_message(self) -> None:
        self.assertIn("Aucun Reject", self.js)

    def test_card_click_navigates_to_film(self) -> None:
        # Clic carte -> navigateTo /film/:id
        self.assertIn("data-qualite-reject-card", self.js)
        self.assertIn("/film/", self.js)

    def test_no_placeholder_text(self) -> None:
        # L'ancien placeholder "Liste des 8 films au pire score V2 a venir" ne doit plus etre la.
        self.assertNotIn("a venir (endpoint backend", self.js)


class SagasSectionWiringTests(unittest.TestCase):
    """Section 3 Sagas : cards + barre progression + bouton TMDb."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_calls_get_incomplete_sagas(self) -> None:
        self.assertIn('apiPost("library/get_incomplete_sagas"', self.js)

    def test_renders_saga_card(self) -> None:
        self.assertIn("qualite-saga-card", self.js)

    def test_renders_progress_bar(self) -> None:
        self.assertIn("qualite-saga-progress", self.js)

    def test_tmdb_link(self) -> None:
        self.assertIn("themoviedb.org/collection/", self.js)

    def test_renders_missing_films_list(self) -> None:
        self.assertIn("missing_films", self.js)

    def test_renders_owned_films_list(self) -> None:
        self.assertIn("owned_films", self.js)


class DecadesSectionWiringTests(unittest.TestCase):
    """Section 5 Decennies : histogramme cliquable sur by_decade."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_calls_get_films_by_decade(self) -> None:
        self.assertIn('apiPost("library/get_films_by_decade"', self.js)

    def test_decade_click_navigates(self) -> None:
        self.assertIn("data-qualite-decade", self.js)
        self.assertIn("/bibliotheque?filter=decade_", self.js)

    def test_renders_decade_count_label(self) -> None:
        # "1930s : 12" pattern (spec §1)
        self.assertIn("qualite-decade-label", self.js)


class EvolutionSectionWiringTests(unittest.TestCase):
    """Section 6 Evolution : SVG + 3 KPIs delta + filtre periode."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_calls_get_history(self) -> None:
        self.assertIn('apiPost("quality/get_history"', self.js)

    def test_three_delta_kpis(self) -> None:
        for kpi in ("delta_score", "delta_films", "delta_reject"):
            self.assertIn(kpi, self.js)

    def test_period_switch_buttons(self) -> None:
        self.assertIn("data-qualite-period", self.js)
        # 7 / 30 / 90 / 0 (Tout)
        for p in ("7", "30", "90"):
            self.assertIn(p, self.js)

    def test_svg_chart_render(self) -> None:
        self.assertIn("qualite-evolution-svg", self.js)
        self.assertIn("<svg", self.js)
        self.assertIn("<path", self.js)


class FiltersDrawerTests(unittest.TestCase):
    """Drawer filtres globaux (decennie / genre / source / audio / periode)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DRAWER_JS.read_text(encoding="utf-8")
        cls.view = _QUALITE_JS.read_text(encoding="utf-8")

    def test_drawer_exports_open(self) -> None:
        self.assertIn("export function openQualiteFiltersDrawer", self.js)

    def test_drawer_exports_close(self) -> None:
        self.assertIn("export function closeQualiteFiltersDrawer", self.js)

    def test_drawer_exports_empty_filters(self) -> None:
        self.assertIn("export function emptyFilters", self.js)

    def test_decade_filter_options(self) -> None:
        for d in ("1930", "1950", "2000", "2020"):
            self.assertIn(d, self.js)

    def test_genre_filter_options(self) -> None:
        for g in ("Action", "Comédie", "Drame", "Science-Fiction"):
            self.assertIn(g, self.js)

    def test_source_filter_options(self) -> None:
        for s in ("BluRay", "WEB-DL", "DVD"):
            self.assertIn(s, self.js)

    def test_audio_filter_options(self) -> None:
        for a in ("FR", "EN"):
            self.assertIn(a, self.js)

    def test_period_filter_options(self) -> None:
        for p in ("7", "30", "90"):
            self.assertIn(p, self.js)

    def test_reset_button(self) -> None:
        self.assertIn("data-qualite-drawer-reset", self.js)

    def test_apply_button(self) -> None:
        self.assertIn("data-qualite-drawer-apply", self.js)

    def test_view_imports_drawer(self) -> None:
        self.assertIn("qualite-filters-drawer", self.view)
        self.assertIn("openQualiteFiltersDrawer", self.view)


class RecomputeScoresActionTests(unittest.TestCase):
    """Bouton Re-calculer : dangerConfirmModal + polling toast."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_imports_danger_modal(self) -> None:
        self.assertIn("dangerConfirmModal", self.js)
        self.assertIn('from "../components/modal.js"', self.js)

    def test_imports_toast(self) -> None:
        self.assertIn("showToast", self.js)
        self.assertIn('from "../components/toast.js"', self.js)

    def test_recompute_calls_endpoint(self) -> None:
        self.assertIn('apiPost("quality/recompute_all_scores"', self.js)

    def test_recompute_polls_status(self) -> None:
        self.assertIn('apiPost("quality/get_recompute_job_status"', self.js)

    def test_recompute_uses_setInterval(self) -> None:
        self.assertIn("setInterval", self.js)

    def test_no_old_alert_placeholder(self) -> None:
        # L'ancien placeholder alert("Re-calcul des scores...") doit etre supprime
        self.assertNotIn('alert("Re-calcul des scores', self.js)
        self.assertNotIn('alert("Filtres globaux', self.js)


class InspectorContextualTests(unittest.TestCase):
    """Inspecteur droit : 5 contextes (distribution / reject / saga / decade / evolution)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_inspector_section_state(self) -> None:
        # Doit memoriser quelle section est active
        self.assertIn("inspectorSection", self.js)

    def test_inspector_distribution_context(self) -> None:
        self.assertIn('"distribution"', self.js)

    def test_inspector_reject_context(self) -> None:
        self.assertIn('"reject_card"', self.js)

    def test_inspector_saga_context(self) -> None:
        self.assertIn('"saga"', self.js)

    def test_inspector_decade_context(self) -> None:
        self.assertIn('"decade"', self.js)

    def test_inspector_evolution_context(self) -> None:
        self.assertIn('"evolution"', self.js)


class CssTests(unittest.TestCase):
    """Verifie que les nouvelles classes CSS Phase 5 sont presentes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_reject_grid_class(self) -> None:
        self.assertIn(".qualite-reject-grid", self.css)

    def test_reject_card_class(self) -> None:
        self.assertIn(".qualite-reject-card", self.css)

    def test_saga_card_class(self) -> None:
        self.assertIn(".qualite-saga-card", self.css)

    def test_saga_progress_class(self) -> None:
        self.assertIn(".qualite-saga-progress", self.css)

    def test_evolution_chart_class(self) -> None:
        self.assertIn(".qualite-evolution-chart", self.css)

    def test_drawer_classes(self) -> None:
        self.assertIn(".qualite-drawer", self.css)
        self.assertIn(".qualite-drawer-backdrop", self.css)
        self.assertIn(".qualite-drawer-group", self.css)

    def test_period_switch_class(self) -> None:
        self.assertIn(".qualite-period-switch", self.css)

    def test_balance_braces(self) -> None:
        """Garde-fou : pas de regression sur le balance accolades CSS."""
        opens = self.css.count("{")
        closes = self.css.count("}")
        self.assertEqual(opens, closes, f"Imbalance: {opens} opens vs {closes} closes")


class TestHooksTests(unittest.TestCase):
    """Verifie que les hooks de test sont exposes pour debug."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_exports_testing_hook(self) -> None:
        self.assertIn("export const __testing__", self.js)

    def test_testing_exposes_state(self) -> None:
        self.assertIn("state: _state", self.js)


if __name__ == "__main__":
    unittest.main()
