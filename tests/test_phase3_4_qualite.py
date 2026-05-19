"""Tests Phase 3.4 : nouvelle vue Qualité audit transverse (spec 10-qualite.md)."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_QUALITE_JS = _ROOT / "web" / "dashboard" / "views" / "qualite.js"
_APP_JS = _ROOT / "web" / "dashboard" / "app.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FileExistsTests(unittest.TestCase):
    def test_view_exists(self) -> None:
        self.assertTrue(_QUALITE_JS.is_file())


class EsModuleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_exports_init(self) -> None:
        self.assertIn("export async function initQualite(", self.js)

    def test_exports_unmount(self) -> None:
        self.assertIn("export function unmountQualite(", self.js)


class SixSectionsTests(unittest.TestCase):
    """Spec 10 §1 : 6 sections obligatoires."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_distribution_section(self) -> None:
        self.assertIn("function _renderDistributionSection(", self.js)

    def test_reject_section(self) -> None:
        self.assertIn("function _renderRejectSection(", self.js)

    def test_sagas_section(self) -> None:
        self.assertIn("function _renderSagasSection(", self.js)

    def test_subs_section(self) -> None:
        self.assertIn("function _renderSubsSection(", self.js)

    def test_decades_section(self) -> None:
        self.assertIn("function _renderDecadesSection(", self.js)

    def test_evolution_section(self) -> None:
        self.assertIn("function _renderEvolutionSection(", self.js)


class TierDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_normalize_function(self) -> None:
        self.assertIn("function _normalizeTierDist(", self.js)

    def test_resolve_function(self) -> None:
        self.assertIn("function _resolveTierDist(", self.js)

    def test_5_tiers_order(self) -> None:
        self.assertIn('"platinum", "gold", "silver", "bronze", "reject"', self.js)

    def test_v2_priority_fallback(self) -> None:
        self.assertIn("v2_tier_distribution", self.js)
        self.assertIn("tier_distribution", self.js)


class ActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_filters_action(self) -> None:
        self.assertIn('data-qualite-action="filters"', self.js)

    def test_recompute_action(self) -> None:
        self.assertIn('data-qualite-action="recompute"', self.js)

    def test_configure_subs_action(self) -> None:
        self.assertIn('data-qualite-action="configure-subs"', self.js)

    def test_tier_click_navigation(self) -> None:
        self.assertIn("data-qualite-tier", self.js)
        self.assertIn("/bibliotheque?filter=tier_", self.js)


class InspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_imports_right_panel(self) -> None:
        self.assertIn('from "../components/right-panel.js"', self.js)

    def test_dominant_tier_computation(self) -> None:
        self.assertIn("function _dominantTier(", self.js)


class AppJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_imports(self) -> None:
        self.assertIn('from "./views/qualite.js"', self.js)
        self.assertIn("initQualite", self.js)
        self.assertIn("unmountQualite", self.js)

    def test_route_uses_init(self) -> None:
        line_start = self.js.find('registerRoute("/qualite"')
        self.assertNotEqual(line_start, -1)
        line_end = self.js.find("\n", line_start)
        snippet = self.js[line_start:line_end]
        self.assertIn("initQualite", snippet)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_root_class(self) -> None:
        self.assertIn(".qualite-view", self.css)

    def test_tier_bar_classes(self) -> None:
        self.assertIn(".qualite-tier-bar", self.css)
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f".qualite-tier-fill--{tier}", self.css)

    def test_uses_tier_solid_tokens(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f"var(--tier-{tier}-solid", self.css)

    def test_evolution_kpis_class(self) -> None:
        self.assertIn(".qualite-evolution-kpis", self.css)

    def test_inspector_classes(self) -> None:
        self.assertIn(".qualite-inspector-dl", self.css)


if __name__ == "__main__":
    unittest.main()
