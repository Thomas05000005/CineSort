"""Tests Phase 3.3 : Vue Doublons refondue (spec 01)."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DOUBLONS_JS = _ROOT / "web" / "dashboard" / "views" / "doublons.js"
_APP_JS = _ROOT / "web" / "dashboard" / "app.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FileExistsTests(unittest.TestCase):
    def test_view_exists(self) -> None:
        self.assertTrue(_DOUBLONS_JS.is_file())


class EsModuleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DOUBLONS_JS.read_text(encoding="utf-8")

    def test_exports_init(self) -> None:
        self.assertIn("export async function initDoublons(", self.js)

    def test_exports_unmount(self) -> None:
        self.assertIn("export function unmountDoublons(", self.js)


class DataLoadingTests(unittest.TestCase):
    """Spec 01 §1 : utilise check_duplicates."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DOUBLONS_JS.read_text(encoding="utf-8")

    def test_uses_check_duplicates(self) -> None:
        self.assertIn("check_duplicates", self.js)

    def test_resolves_run_id(self) -> None:
        self.assertIn("get_dashboard", self.js)


class GroupCardTests(unittest.TestCase):
    """Spec 01 §1 : cartes A/B avec scores + alertes humanisees."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DOUBLONS_JS.read_text(encoding="utf-8")

    def test_render_group_card(self) -> None:
        self.assertIn("function _renderGroupCard(group)", self.js)

    def test_uses_alert_labels(self) -> None:
        self.assertIn("alert-labels.js", self.js)
        self.assertIn("labelsForFlags", self.js)

    def test_uses_perceptual_modal(self) -> None:
        self.assertIn("perceptual-modal.js", self.js)
        self.assertIn("openPerceptualModal", self.js)

    def test_versions_a_and_b(self) -> None:
        self.assertIn("doublons-version", self.js)
        self.assertIn('winner === "a"', self.js)
        self.assertIn('winner === "b"', self.js)


class ToolbarAndFiltersTests(unittest.TestCase):
    """Spec 01 §1 : toolbar avec refresh + filter."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DOUBLONS_JS.read_text(encoding="utf-8")

    def test_filter_options(self) -> None:
        for f in ('"all"', '"conflict"', '"pending"', '"decided"'):
            self.assertIn(f, self.js)

    def test_refresh_action(self) -> None:
        self.assertIn('data-doublons-action="refresh"', self.js)

    def test_legacy_fallback(self) -> None:
        """Spec 01 : Modal Comparateur differe -> fallback vers #/library legacy."""
        self.assertIn("#/library", self.js)


class AppJsRoutingTests(unittest.TestCase):
    """Phase 3.3 : route /doublons cablee."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_import_doublons(self) -> None:
        self.assertIn('from "./views/doublons.js"', self.js)
        self.assertIn("initDoublons", self.js)
        self.assertIn("unmountDoublons", self.js)

    def test_doublons_route_registered(self) -> None:
        self.assertIn('registerRoute("/doublons"', self.js)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_doublons_classes(self) -> None:
        for cls in (
            ".doublons-view",
            ".doublons-header",
            ".doublons-toolbar",
            ".doublons-card",
            ".doublons-card.is-selected",
            ".doublons-card-versions",
            ".doublons-version",
            ".doublons-version.is-winner",
            ".doublons-card-alert",
            ".doublons-card-alert--warning",
            ".doublons-card-alert--critical",
        ):
            self.assertIn(cls, self.css)


if __name__ == "__main__":
    unittest.main()
