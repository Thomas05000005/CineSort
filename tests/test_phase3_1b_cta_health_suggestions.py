"""Tests Phase 3.1-B : Accueil — CTA Scan + Santé biblio + Suggestions.

Etend les tests Phase 3.1-A. Couvre les sections 3, 4, 5 de la spec
05-accueil.md.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ACCUEIL_JS = _ROOT / "web" / "dashboard" / "views" / "accueil.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class CtaScanSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_cta_scan_section_function_present(self) -> None:
        self.assertIn("function _renderCtaScan(roots)", self.js)

    def test_cta_scan_title(self) -> None:
        self.assertIn("Lancer un nouveau scan", self.js)

    def test_cta_scan_lists_roots(self) -> None:
        # Doit afficher les roots actifs ou un message si aucun.
        self.assertIn("Aucun root configuré", self.js)

    def test_cta_scan_action_buttons(self) -> None:
        self.assertIn('data-accueil-action="start-scan"', self.js)
        self.assertIn('data-accueil-action="open-scan-options"', self.js)
        self.assertIn("▶ Démarrer", self.js)
        self.assertIn("Options", self.js)


class HealthBargraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_health_section_function_present(self) -> None:
        self.assertIn("function _renderHealth(stats)", self.js)

    def test_5_tiers_ordered(self) -> None:
        # Spec : ordre platinum > gold > silver > bronze > reject.
        self.assertIn('_TIER_ORDER = ["platinum", "gold", "silver", "bronze", "reject"]', self.js)

    def test_renders_progressbar_aria(self) -> None:
        self.assertIn('role="progressbar"', self.js)
        self.assertIn('aria-valuenow=', self.js)

    def test_empty_state_message(self) -> None:
        # Spec : "Lance ton premier scan pour voir la distribution."
        self.assertIn("Lance ton premier scan pour voir la distribution", self.js)

    def test_action_view_qualite(self) -> None:
        self.assertIn("Audit qualité complet", self.js)
        self.assertIn('data-accueil-action="view-qualite"', self.js)


class SuggestionsSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_suggestions_function_present(self) -> None:
        self.assertIn("function _renderSuggestions(stats)", self.js)

    def test_empty_state_positive_message(self) -> None:
        # Spec §4 : "Aucun point à traiter. Tout va bien."
        self.assertIn("Aucun point à traiter", self.js)

    def test_renders_severity_classes(self) -> None:
        # 3 severites cf spec §4 : danger / warning / info.
        self.assertIn("is-danger", self.js)
        self.assertIn("is-warning", self.js)
        self.assertIn("is-info", self.js)

    def test_renders_severity_emojis(self) -> None:
        # Pour les utilisateurs : 🔴 / 🟡 / 🔵.
        self.assertIn('"🔴"', self.js)
        self.assertIn('"🟡"', self.js)
        self.assertIn('"🔵"', self.js)

    def test_route_map_covers_spec_codes(self) -> None:
        # Spec §4 : 8 codes -> routes connues.
        for code in [
            "duplicates_probable",
            "films_not_identified",
            "films_low_confidence",
            "subs_missing_fr",
            "omdb_disagreements",
            "quality_reject",
            "health_low",
            "sagas_incomplete",
        ]:
            self.assertIn(code, self.js, f"code suggestion {code} non mappe")

    def test_open_insight_action_present(self) -> None:
        self.assertIn('data-accueil-action="open-insight"', self.js)


class IntegrationTests(unittest.TestCase):
    """initAccueil doit charger 3 endpoints en parallele."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_fetches_dashboard_and_stats_and_settings(self) -> None:
        self.assertIn("get_dashboard", self.js)
        self.assertIn("get_global_stats", self.js)
        self.assertIn("settings/get_settings", self.js)

    def test_uses_promise_all(self) -> None:
        self.assertIn("Promise.all([", self.js)

    def test_stats_and_settings_failure_does_not_kill_accueil(self) -> None:
        # On veut .catch(() => null) pour stats + settings : si l'un fail,
        # on ne plante pas tout l'accueil.
        self.assertIn(".catch(() => null)", self.js)

    def test_render_accueil_passes_3_args(self) -> None:
        self.assertIn("_renderAccueil(dashboardData, stats, settings)", self.js)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_cta_scan_class(self) -> None:
        self.assertIn(".accueil-cta-scan", self.css)

    def test_health_classes(self) -> None:
        self.assertIn(".accueil-health-bar", self.css)
        self.assertIn(".accueil-health-fill", self.css)

    def test_tier_fill_classes_all_5(self) -> None:
        # Une couleur par tier (mappe sur les tokens tier-*-solid).
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f".accueil-health-fill--{tier}", self.css)

    def test_uses_tier_solid_tokens(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f"var(--tier-{tier}-solid", self.css)

    def test_suggestion_classes(self) -> None:
        self.assertIn(".accueil-suggestion-list", self.css)
        self.assertIn(".accueil-suggestion-row", self.css)
        self.assertIn(".accueil-suggestion-dot", self.css)

    def test_suggestion_severity_borders(self) -> None:
        # Border-left colore par severite.
        self.assertIn(".accueil-suggestion-row.is-danger", self.css)
        self.assertIn(".accueil-suggestion-row.is-warning", self.css)
        self.assertIn(".accueil-suggestion-row.is-info", self.css)


if __name__ == "__main__":
    unittest.main()
