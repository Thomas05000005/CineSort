"""Tests Phase 3.4 : Qualité — sagas + decades enrichis (spec 10 §3, §5)."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_QUALITE_JS = _ROOT / "web" / "dashboard" / "views" / "qualite.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class SagasSectionTests(unittest.TestCase):
    """Spec 10 §3 : Sagas incompletes - lit librarian.suggestions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_sagas_reads_librarian(self) -> None:
        self.assertIn("librarian", self.js)
        self.assertIn("sagaSug", self.js)

    def test_sagas_link_to_library(self) -> None:
        self.assertIn("sagas_incomplete", self.js)


class DecadesSectionTests(unittest.TestCase):
    """Spec 10 §5 : Decennies - lit stats.by_decade si dispo."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_decades_reads_by_decade(self) -> None:
        self.assertIn("by_decade", self.js)

    def test_decade_row_clickable(self) -> None:
        self.assertIn('href="#/bibliotheque?filter=decade_', self.js)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_decades_classes(self) -> None:
        for cls in (
            ".qualite-decades-list",
            ".qualite-decade-row",
            ".qualite-decade-bar",
            ".qualite-decade-fill",
            ".qualite-decade-count",
        ):
            self.assertIn(cls, self.css)


if __name__ == "__main__":
    unittest.main()
