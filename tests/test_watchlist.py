"""Tests watchlist import — item 9.12.

Couvre :
- Parsing Letterboxd CSV et IMDb CSV
- Normalisation titre (accents, articles, case)
- Matching watchlist vs bibliotheque locale
- Rapport structure (compteurs, owned, missing)
- Endpoint existe
- UI (boutons import)
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from cinesort.app.watchlist import (
    parse_letterboxd_csv,
    parse_imdb_csv,
    compare_watchlist,
    _normalize_title,
)


# ---------------------------------------------------------------------------
# Parsing CSV (4 tests)
# ---------------------------------------------------------------------------


class ParseLetterboxdTests(unittest.TestCase):
    """Tests parsing Letterboxd CSV."""

    def test_valid_csv(self) -> None:
        csv = "Date,Name,Year,Letterboxd URI\n2024-03-15,Inception,2010,https://letterboxd.com/film/inception/\n2024-03-10,The Matrix,1999,https://letterboxd.com/film/the-matrix/\n"
        films = parse_letterboxd_csv(csv)
        self.assertEqual(len(films), 2)
        self.assertEqual(films[0]["title"], "Inception")
        self.assertEqual(films[0]["year"], 2010)

    def test_empty_csv(self) -> None:
        films = parse_letterboxd_csv("")
        self.assertEqual(len(films), 0)

    def test_corrupted_csv(self) -> None:
        films = parse_letterboxd_csv("garbage\x00\x01data\nno,headers")
        # Ne doit pas crasher, peut retourner 0 ou des resultats partiels
        self.assertIsInstance(films, list)


class ParseImdbTests(unittest.TestCase):
    """Tests parsing IMDb CSV."""

    def test_valid_csv(self) -> None:
        csv = 'Position,Const,Created,Modified,Description,Title,URL,Title Type,IMDb Rating,Runtime (mins),Year,Genres,Num Votes,Release Date,Directors\n1,tt1375666,2024-03-15,,My Watchlist,Inception,https://www.imdb.com/title/tt1375666/,movie,8.8,148,2010,"Action, Sci-Fi",2500000,2010-07-16,Christopher Nolan\n'
        films = parse_imdb_csv(csv)
        self.assertEqual(len(films), 1)
        self.assertEqual(films[0]["title"], "Inception")
        self.assertEqual(films[0]["year"], 2010)
        self.assertEqual(films[0]["imdb_id"], "tt1375666")


# ---------------------------------------------------------------------------
# Normalisation titre (3 tests)
# ---------------------------------------------------------------------------


class NormalizeTitleTests(unittest.TestCase):
    """Tests de la normalisation de titres."""

    def test_case_insensitive(self) -> None:
        self.assertEqual(_normalize_title("INCEPTION"), _normalize_title("inception"))

    def test_article_removed(self) -> None:
        self.assertEqual(_normalize_title("The Matrix"), _normalize_title("Matrix"))
        self.assertEqual(_normalize_title("Le Fabuleux Destin"), _normalize_title("Fabuleux Destin"))

    def test_accents_stripped(self) -> None:
        self.assertEqual(_normalize_title("Amélie"), _normalize_title("Amelie"))


# ---------------------------------------------------------------------------
# Matching (5 tests)
# ---------------------------------------------------------------------------


def _row(title, year):
    return SimpleNamespace(proposed_title=title, proposed_year=year)


class CompareWatchlistTests(unittest.TestCase):
    """Tests comparaison watchlist vs bibliotheque locale."""

    def test_owned_exact_match(self) -> None:
        wl = [{"title": "Inception", "year": 2010}]
        local = [_row("Inception", 2010)]
        report = compare_watchlist(wl, local)
        self.assertEqual(report["owned_count"], 1)
        self.assertEqual(report["missing_count"], 0)

    def test_missing_film(self) -> None:
        wl = [{"title": "Blade Runner 2049", "year": 2017}]
        local = [_row("Inception", 2010)]
        report = compare_watchlist(wl, local)
        self.assertEqual(report["missing_count"], 1)
        self.assertEqual(report["missing"][0]["title"], "Blade Runner 2049")

    def test_case_insensitive_match(self) -> None:
        wl = [{"title": "inception", "year": 2010}]
        local = [_row("INCEPTION", 2010)]
        report = compare_watchlist(wl, local)
        self.assertEqual(report["owned_count"], 1)

    def test_article_match(self) -> None:
        """'The Matrix' dans watchlist matche 'Matrix' en local."""
        wl = [{"title": "The Matrix", "year": 1999}]
        local = [_row("Matrix", 1999)]
        report = compare_watchlist(wl, local)
        self.assertEqual(report["owned_count"], 1)

    def test_accent_match(self) -> None:
        wl = [{"title": "Amélie", "year": 2001}]
        local = [_row("Amelie", 2001)]
        report = compare_watchlist(wl, local)
        self.assertEqual(report["owned_count"], 1)

    def test_no_year_match_by_title(self) -> None:
        """Film sans annee dans la watchlist → match par titre seul."""
        wl = [{"title": "Inception", "year": 0}]
        local = [_row("Inception", 2010)]
        report = compare_watchlist(wl, local)
        self.assertEqual(report["owned_count"], 1)

    def test_counters_correct(self) -> None:
        wl = [
            {"title": "Inception", "year": 2010},
            {"title": "Missing Film", "year": 2020},
            {"title": "The Matrix", "year": 1999},
        ]
        local = [_row("Inception", 2010), _row("Matrix", 1999)]
        report = compare_watchlist(wl, local)
        self.assertEqual(report["total_watchlist"], 3)
        self.assertEqual(report["owned_count"], 2)
        self.assertEqual(report["missing_count"], 1)
        self.assertAlmostEqual(report["coverage_pct"], 66.7, places=1)

    def test_empty_watchlist(self) -> None:
        report = compare_watchlist([], [_row("Film", 2020)])
        self.assertEqual(report["total_watchlist"], 0)
        self.assertEqual(report["coverage_pct"], 100.0)

    def test_empty_library(self) -> None:
        wl = [{"title": "Film", "year": 2020}]
        report = compare_watchlist(wl, [])
        self.assertEqual(report["missing_count"], 1)
        self.assertEqual(report["owned_count"], 0)


# ---------------------------------------------------------------------------
# Endpoint + UI (2 tests)
# ---------------------------------------------------------------------------


class EndpointAndUiTests(unittest.TestCase):
    """Tests endpoint et presence UI."""

    def test_endpoint_exists(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        self.assertTrue(hasattr(api, "import_watchlist"))
        # Source invalide → erreur
        result = api.import_watchlist("csv", "unknown")
        self.assertFalse(result["ok"])

    def test_ui_buttons_present(self) -> None:
        # V5B-01 : le HTML dashboard ne contient plus les inputs file directement
        # (rendus dynamiquement par les vues v5 / library.js v4 si chargee).
        # On verifie l'endpoint cote backend + l'existence de l'UI dans les vues
        # qui declenchent l'import (web/views/settings.js et dashboard/views/library.js).
        root = Path(__file__).resolve().parents[1]
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        settings_js = (root / "web" / "views" / "settings.js").read_text(encoding="utf-8")
        lib_js = (root / "web" / "dashboard" / "views" / "library.js").read_text(encoding="utf-8")
        self.assertIn("fileLetterboxd", html)
        self.assertIn("fileImdb", html)
        self.assertIn("import_watchlist", settings_js)
        self.assertIn("import_watchlist", lib_js)
        # Les inputs dashFile* sont injectes dynamiquement par library.js (legacy v4).
        self.assertIn("dashFileLetterboxd", lib_js)


if __name__ == "__main__":
    unittest.main()
