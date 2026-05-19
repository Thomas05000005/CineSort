"""Tests Phase 3.2 : Bibliothèque squelette (spec 07)."""

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


class StructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_toolbar_and_search(self) -> None:
        self.assertIn("data-bibliotheque-search", self.js)
        self.assertIn('data-bibliotheque-action="filters"', self.js)

    def test_legacy_link_present(self) -> None:
        # Squelette : on redirige vers la vue legacy en attendant le portage complet.
        self.assertIn('href="#/library"', self.js)


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
            ".bibliotheque-coming-soon",
        ):
            self.assertIn(cls, self.css)


if __name__ == "__main__":
    unittest.main()
