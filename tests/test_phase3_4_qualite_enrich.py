"""Tests Phase 3.4 : Qualité — sagas + decades enrichis (spec 10 §3, §5)."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_QUALITE_JS = _ROOT / "web" / "dashboard" / "views" / "qualite.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class SagasSectionTests(unittest.TestCase):
    """Spec 10 §3 : Sagas incompletes - Phase 5 lit l'endpoint dedie."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_sagas_calls_endpoint(self) -> None:
        # Phase 5 : cable sur l'endpoint dedie au lieu de librarian.suggestions
        self.assertIn("library/get_incomplete_sagas", self.js)

    def test_sagas_data_fields(self) -> None:
        # Les champs cles de la reponse get_incomplete_sagas doivent etre utilises
        self.assertIn("missing_films", self.js)
        self.assertIn("owned_films", self.js)
        self.assertIn("total_films_in_collection", self.js)


class DecadesSectionTests(unittest.TestCase):
    """Spec 10 §5 : Decennies - lit stats.by_decade ou endpoint dedie."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_decades_reads_by_decade(self) -> None:
        self.assertIn("by_decade", self.js)

    def test_decade_row_clickable(self) -> None:
        # Phase 5 : passage de <a href> a <button> + navigateTo
        self.assertIn("data-qualite-decade", self.js)
        self.assertIn("/bibliotheque?filter=decade_", self.js)


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
