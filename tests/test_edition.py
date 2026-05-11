"""Tests editions multiples / multi-version — item 9.22.

Couvre :
- extract_edition, strip_edition : detection et nettoyage
- PlanRow.edition : serialisation/deserialisation
- Naming : {edition}, {edition-tag}
- Doublons : movie_key edition-aware
- UI : badges present, CSS classes
- Integration : scan, conformance, TMDb
"""

from __future__ import annotations

import unittest
from dataclasses import asdict
from pathlib import Path

from cinesort.domain.edition_helpers import extract_edition, strip_edition
from cinesort.domain.naming import (
    build_naming_context,
    format_movie_folder,
    validate_template,
    _KNOWN_VARS,
)
from cinesort.domain.duplicate_support import movie_key


# ---------------------------------------------------------------------------
# Detection (8 tests)
# ---------------------------------------------------------------------------


class ExtractEditionTests(unittest.TestCase):
    """Tests de la detection d'editions dans les noms de fichiers/dossiers."""

    def test_directors_cut_apostrophe(self) -> None:
        self.assertEqual(extract_edition("Inception Director's Cut 2010 1080p"), "Director's Cut")

    def test_directors_cut_dots(self) -> None:
        self.assertEqual(extract_edition("Inception.Directors.Cut.2010"), "Director's Cut")

    def test_extended_edition(self) -> None:
        self.assertEqual(extract_edition("Inception Extended Edition 1080p"), "Extended Edition")

    def test_imax(self) -> None:
        self.assertEqual(extract_edition("Inception IMAX 2010"), "IMAX")

    def test_no_edition(self) -> None:
        self.assertIsNone(extract_edition("Inception 2010 1080p"))

    def test_strip_edition(self) -> None:
        result = strip_edition("Inception Director's Cut 2010")
        self.assertNotIn("Director", result)
        self.assertIn("Inception", result)
        self.assertIn("2010", result)

    def test_final_cut(self) -> None:
        self.assertEqual(extract_edition("Blade.Runner.1982.Final.Cut.BluRay"), "Final Cut")

    def test_anniversary_edition(self) -> None:
        result = extract_edition("Alien 40th Anniversary Edition")
        self.assertIsNotNone(result)
        self.assertIn("Anniversary", result)


# ---------------------------------------------------------------------------
# Stockage (2 tests)
# ---------------------------------------------------------------------------


class PlanRowEditionTests(unittest.TestCase):
    """Tests serialisation/deserialisation du champ edition."""

    def test_planrow_with_edition(self) -> None:
        import cinesort.domain.core as core

        row = core.PlanRow(
            row_id="test1",
            kind="single",
            folder="/tmp/test",
            video="test.mkv",
            proposed_title="Inception",
            proposed_year=2010,
            proposed_source="tmdb",
            confidence=85,
            confidence_label="high",
            candidates=[],
            edition="Director's Cut",
        )
        self.assertEqual(row.edition, "Director's Cut")
        d = asdict(row)
        self.assertEqual(d["edition"], "Director's Cut")

    def test_planrow_without_edition(self) -> None:
        import cinesort.domain.core as core

        row = core.PlanRow(
            row_id="test2",
            kind="single",
            folder="/tmp/test",
            video="test.mkv",
            proposed_title="Inception",
            proposed_year=2010,
            proposed_source="tmdb",
            confidence=85,
            confidence_label="high",
            candidates=[],
        )
        self.assertIsNone(row.edition)

    def test_deserialize_with_edition(self) -> None:
        from cinesort.app.plan_support import plan_row_from_jsonable

        data = {
            "row_id": "S|abc",
            "kind": "single",
            "folder": "/tmp",
            "video": "x.mkv",
            "proposed_title": "Inception",
            "proposed_year": 2010,
            "proposed_source": "tmdb",
            "confidence": 80,
            "confidence_label": "high",
            "candidates": [],
            "edition": "IMAX",
        }
        row = plan_row_from_jsonable(data)
        self.assertIsNotNone(row)
        self.assertEqual(row.edition, "IMAX")

    def test_deserialize_without_edition(self) -> None:
        from cinesort.app.plan_support import plan_row_from_jsonable

        data = {
            "row_id": "S|abc",
            "kind": "single",
            "folder": "/tmp",
            "video": "x.mkv",
            "proposed_title": "Inception",
            "proposed_year": 2010,
            "proposed_source": "tmdb",
            "confidence": 80,
            "confidence_label": "high",
            "candidates": [],
        }
        row = plan_row_from_jsonable(data)
        self.assertIsNotNone(row)
        self.assertIsNone(row.edition)


# ---------------------------------------------------------------------------
# Renommage (4 tests)
# ---------------------------------------------------------------------------


class NamingEditionTests(unittest.TestCase):
    """Tests des variables {edition} et {edition-tag} dans le naming."""

    def test_edition_tag_with_value(self) -> None:
        ctx = build_naming_context(title="Inception", year=2010, edition="Director's Cut")
        result = format_movie_folder("{title} ({year}) {edition-tag}", ctx)
        self.assertIn("{edition-Director's Cut}", result)

    def test_edition_tag_empty(self) -> None:
        ctx = build_naming_context(title="Inception", year=2010, edition="")
        result = format_movie_folder("{title} ({year}) {edition-tag}", ctx)
        self.assertEqual(result, "Inception (2010)")

    def test_edition_simple_with_value(self) -> None:
        ctx = build_naming_context(title="Inception", year=2010, edition="IMAX")
        result = format_movie_folder("{title} ({year}) - {edition}", ctx)
        self.assertEqual(result, "Inception (2010) - IMAX")

    def test_edition_vars_in_known(self) -> None:
        self.assertIn("edition", _KNOWN_VARS)
        self.assertIn("edition-tag", _KNOWN_VARS)

    def test_validate_template_accepts_edition(self) -> None:
        ok, _ = validate_template("{title} ({year}) {edition-tag}")
        self.assertTrue(ok)
        ok2, _ = validate_template("{title} ({year}) {edition}")
        self.assertTrue(ok2)


# ---------------------------------------------------------------------------
# Doublons (3 tests)
# ---------------------------------------------------------------------------


def _norm(s: str) -> str:
    return s.lower().strip()


class DuplicateEditionTests(unittest.TestCase):
    """Tests movie_key edition-aware."""

    def test_different_editions_different_keys(self) -> None:
        k1 = movie_key("Inception", 2010, norm_for_tokens=_norm, edition="Director's Cut")
        k2 = movie_key("Inception", 2010, norm_for_tokens=_norm, edition="Theatrical")
        self.assertNotEqual(k1, k2)

    def test_same_edition_same_key(self) -> None:
        k1 = movie_key("Inception", 2010, norm_for_tokens=_norm, edition="IMAX")
        k2 = movie_key("Inception", 2010, norm_for_tokens=_norm, edition="IMAX")
        self.assertEqual(k1, k2)

    def test_edition_vs_no_edition_different_keys(self) -> None:
        k1 = movie_key("Inception", 2010, norm_for_tokens=_norm, edition="Director's Cut")
        k2 = movie_key("Inception", 2010, norm_for_tokens=_norm)
        self.assertNotEqual(k1, k2)

    def test_no_edition_backward_compat(self) -> None:
        """Sans edition, le comportement est identique a l'ancien."""
        k1 = movie_key("Inception", 2010, norm_for_tokens=_norm)
        k2 = movie_key("Inception", 2010, norm_for_tokens=_norm, edition=None)
        self.assertEqual(k1, k2)


# ---------------------------------------------------------------------------
# UI (4 tests)
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/review.js supprime — adaptation v5 deferee a V5C-03")
class EditionUiTests(unittest.TestCase):
    """Tests presence UI badge edition."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.validation_js = (root / "web" / "views" / "validation.js").read_text(encoding="utf-8")
        cls.review_js = (root / "web" / "dashboard" / "views" / "review.js").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")
        cls.dash_css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_validation_js_edition_badge(self) -> None:
        self.assertIn("editionBadge", self.validation_js)
        self.assertIn("badge--edition", self.validation_js)

    def test_review_js_edition_badge(self) -> None:
        self.assertIn("badge-edition", self.review_js)

    def test_app_css_edition(self) -> None:
        self.assertIn(".badge--edition", self.app_css)

    def test_dash_css_edition(self) -> None:
        self.assertIn(".badge-edition", self.dash_css)


# ---------------------------------------------------------------------------
# Integration (4 tests)
# ---------------------------------------------------------------------------


class EditionIntegrationTests(unittest.TestCase):
    """Tests d'integration scan / clean / conformance."""

    def test_strip_then_clean_title(self) -> None:
        """strip_edition + clean_title_guess ne laisse pas de residus edition."""
        from cinesort.domain.edition_helpers import strip_edition
        import cinesort.domain.core as core

        stripped = strip_edition("Inception.Directors.Cut.2010.1080p.BluRay.x264")
        cleaned = core.clean_title_guess(stripped)
        self.assertNotIn("director", cleaned.lower())
        self.assertIn("inception", cleaned.lower())

    def test_no_edition_unchanged(self) -> None:
        """Film sans edition → comportement identique."""
        self.assertIsNone(extract_edition("Inception (2010)"))
        stripped = strip_edition("Inception (2010)")
        self.assertIn("Inception", stripped)

    def test_conformance_with_edition_template(self) -> None:
        """Template avec {edition-tag} + contexte edition → nom genere contient le tag."""
        ctx = build_naming_context(title="Blade Runner", year=1982, edition="Final Cut")
        result = format_movie_folder("{title} ({year}) {edition-tag}", ctx)
        self.assertIn("Blade Runner (1982)", result)
        self.assertIn("{edition-Final Cut}", result)

    def test_edition_none_clean_template(self) -> None:
        """Template avec {edition} mais edition=None → resultat propre sans tiret orphelin."""
        ctx = build_naming_context(title="Inception", year=2010, edition="")
        result = format_movie_folder("{title} ({year}) - {edition}", ctx)
        # Le tiret orphelin devrait etre nettoye
        self.assertNotIn(" - ", result.rstrip())


if __name__ == "__main__":
    unittest.main()
