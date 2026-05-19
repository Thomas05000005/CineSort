"""Tests Phase 3.3 : nouvelle vue Traitement workflow 5 etapes (spec 08, squelette)."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TRAITEMENT_JS = _ROOT / "web" / "dashboard" / "views" / "traitement.js"
_APP_JS = _ROOT / "web" / "dashboard" / "app.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FileExistsTests(unittest.TestCase):
    def test_view_exists(self) -> None:
        self.assertTrue(_TRAITEMENT_JS.is_file())


class EsModuleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_exports_init(self) -> None:
        self.assertIn("export function initTraitement(", self.js)

    def test_exports_unmount(self) -> None:
        self.assertIn("export function unmountTraitement(", self.js)


class FiveStepsTests(unittest.TestCase):
    """Spec 08 §1 : workflow 5 etapes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_all_5_steps_defined(self) -> None:
        for step in ("analyse", "verification", "validation", "doublons", "apply"):
            self.assertIn(f'id: "{step}"', self.js, f"étape {step} manquante")

    def test_step_labels_french(self) -> None:
        for label in ("Analyse", "Vérification", "Validation", "Doublons", "Apply"):
            self.assertIn(f'label: "{label}"', self.js)

    def test_render_breadcrumb_function(self) -> None:
        self.assertIn("function _renderBreadcrumb(currentStep)", self.js)

    def test_render_step_panel_function(self) -> None:
        self.assertIn("function _renderStepPanel(stepId)", self.js)


class NavigationTests(unittest.TestCase):
    """Spec 08 : navigation libre entre étapes passées via fragment #step-X."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_reads_step_from_hash(self) -> None:
        self.assertIn("function _readStep()", self.js)
        self.assertIn("#step-", self.js)

    def test_writes_step_to_hash(self) -> None:
        self.assertIn("function _writeStep(stepId)", self.js)

    def test_hashchange_listener(self) -> None:
        self.assertIn("hashchange", self.js)


class AppJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_imports(self) -> None:
        self.assertIn('from "./views/traitement.js"', self.js)
        self.assertIn("initTraitement", self.js)
        self.assertIn("unmountTraitement", self.js)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_classes(self) -> None:
        for cls in (
            ".traitement-view",
            ".traitement-breadcrumb",
            ".traitement-step",
            ".traitement-step.is-current",
            ".traitement-step.is-past",
            ".traitement-panel",
        ):
            self.assertIn(cls, self.css)


if __name__ == "__main__":
    unittest.main()
