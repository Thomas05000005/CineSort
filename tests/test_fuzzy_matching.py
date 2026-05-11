"""Tests pour le fuzzy matching (rapidfuzz integration)."""

from __future__ import annotations

import time
import unittest

from cinesort.domain.title_helpers import seq_ratio


class SeqRatioRapidfuzzTests(unittest.TestCase):
    """Tests pour seq_ratio() apres migration vers rapidfuzz."""

    def test_identical_strings(self):
        self.assertAlmostEqual(seq_ratio("test", "test"), 1.0, places=2)

    def test_similar_strings(self):
        ratio = seq_ratio("the matrix", "the matrx")
        self.assertGreater(ratio, 0.8)

    def test_different_strings(self):
        ratio = seq_ratio("inception", "avatar")
        self.assertLess(ratio, 0.4)

    def test_empty_both(self):
        """Deux chaines vides = 0.0 (compatibilite difflib)."""
        self.assertAlmostEqual(seq_ratio("", ""), 0.0, places=2)

    def test_one_empty(self):
        self.assertAlmostEqual(seq_ratio("test", ""), 0.0, places=2)

    def test_returns_float_0_1(self):
        """Le resultat doit etre entre 0.0 et 1.0 (pas 0-100)."""
        ratio = seq_ratio("hello world", "hello")
        self.assertGreaterEqual(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)

    def test_accents(self):
        """Les accents reduisent le ratio mais ne le cassent pas."""
        ratio = seq_ratio("amelie", "amélie")
        self.assertGreater(ratio, 0.8)

    def test_word_order_basic(self):
        """fuzz.ratio est sensible a l'ordre (c'est normal pour seq_ratio)."""
        ratio = seq_ratio("the matrix", "matrix the")
        # fuzz.ratio est basique (pas token_sort), donc l'ordre compte
        self.assertGreater(ratio, 0.5)

    def test_performance_1000_calls(self):
        """1000 appels seq_ratio en moins de 200ms (rapidfuzz est rapide)."""
        pairs = [("the matrix reloaded", "matrix reloaded the")] * 1000
        t0 = time.monotonic()
        for a, b in pairs:
            seq_ratio(a, b)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.2, f"1000 appels en {elapsed:.3f}s (> 200ms)")


class FuzzyUtilsTests(unittest.TestCase):
    """Tests pour _fuzzy_utils (normalize + fuzzy_title_match)."""

    def test_normalize_accents(self):
        from cinesort.app._fuzzy_utils import normalize_for_fuzzy

        self.assertEqual(normalize_for_fuzzy("Amelie"), "amelie")
        self.assertEqual(normalize_for_fuzzy("Amelie"), normalize_for_fuzzy("Amélie"))

    def test_normalize_punctuation(self):
        from cinesort.app._fuzzy_utils import normalize_for_fuzzy

        result = normalize_for_fuzzy("Spider-Man: No Way Home")
        self.assertEqual(result, "spider man no way home")

    def test_normalize_empty(self):
        from cinesort.app._fuzzy_utils import normalize_for_fuzzy

        self.assertEqual(normalize_for_fuzzy(""), "")
        self.assertEqual(normalize_for_fuzzy(None), "")

    def test_fuzzy_match_exact(self):
        from cinesort.app._fuzzy_utils import fuzzy_title_match

        self.assertTrue(fuzzy_title_match("Inception", "Inception"))

    def test_fuzzy_match_accents(self):
        from cinesort.app._fuzzy_utils import fuzzy_title_match

        self.assertTrue(fuzzy_title_match("Café Society", "Cafe Society"))

    def test_fuzzy_match_below_threshold(self):
        from cinesort.app._fuzzy_utils import fuzzy_title_match

        self.assertFalse(fuzzy_title_match("Up", "Us"))

    def test_fuzzy_match_different_films(self):
        from cinesort.app._fuzzy_utils import fuzzy_title_match

        self.assertFalse(fuzzy_title_match("The Dark Knight", "Dark Waters"))

    def test_fuzzy_match_empty(self):
        from cinesort.app._fuzzy_utils import fuzzy_title_match

        self.assertFalse(fuzzy_title_match("", "test"))
        self.assertFalse(fuzzy_title_match("test", ""))


class JellyfinFuzzyTests(unittest.TestCase):
    """Tests pour le fuzzy matching dans jellyfin_validation.build_sync_report()."""

    def _make_row(self, title, year, tmdb_id=None):
        """Cree un mock PlanRow minimal."""
        import types

        row = types.SimpleNamespace(
            folder="/movies/test",
            video="test.mkv",
            proposed_title=title,
            proposed_year=year,
            candidates=[],
        )
        if tmdb_id:
            row.candidates = [types.SimpleNamespace(tmdb_id=tmdb_id)]
        return row

    def test_sync_exact_match(self):
        from cinesort.app.jellyfin_validation import build_sync_report

        rows = [self._make_row("Inception", 2010)]
        jf = [{"id": "1", "name": "Inception", "year": 2010, "path": "/other/path", "tmdb_id": None}]
        report = build_sync_report(rows, jf)
        self.assertEqual(report["matched"], 1)
        self.assertEqual(len(report["missing_in_jellyfin"]), 0)

    def test_sync_fuzzy_accent_match(self):
        """Titre avec accent local vs sans accent Jellyfin → matched via fuzzy."""
        from cinesort.app.jellyfin_validation import build_sync_report

        rows = [self._make_row("Amélie Poulain", 2001)]
        jf = [{"id": "1", "name": "Amelie Poulain", "year": 2001, "path": "/other/path", "tmdb_id": None}]
        report = build_sync_report(rows, jf)
        self.assertEqual(report["matched"], 1)

    def test_sync_different_films_not_matched(self):
        """Films differents avec la meme annee ne doivent pas matcher en fuzzy."""
        from cinesort.app.jellyfin_validation import build_sync_report

        rows = [self._make_row("The Dark Knight", 2008)]
        jf = [{"id": "1", "name": "Dark Waters", "year": 2008, "path": "/other/path", "tmdb_id": None}]
        report = build_sync_report(rows, jf)
        self.assertEqual(report["matched"], 0)
        self.assertEqual(len(report["missing_in_jellyfin"]), 1)


class RadarrFuzzyTests(unittest.TestCase):
    """Tests pour le fuzzy matching dans radarr_sync.build_radarr_report()."""

    def _make_row(self, title, year, tmdb_id=None):
        import types

        row = types.SimpleNamespace(
            folder="/movies/test",
            video="test.mkv",
            proposed_title=title,
            proposed_year=year,
            row_id="r1",
            candidates=[],
        )
        if tmdb_id:
            row.candidates = [types.SimpleNamespace(tmdb_id=tmdb_id)]
        return row

    def test_radarr_fuzzy_accent(self):
        from cinesort.app.radarr_sync import build_radarr_report

        rows = [self._make_row("Café Society", 2016)]
        radarr = [
            {
                "id": 1,
                "title": "Cafe Society",
                "year": 2016,
                "tmdb_id": 0,
                "monitored": True,
                "has_file": True,
                "quality_profile_id": 1,
                "path": "/other/path",
                "quality_name": "HD",
            }
        ]
        report = build_radarr_report(rows, radarr, {}, [])
        self.assertEqual(report["matched_count"], 1)


class WatchlistFuzzyTests(unittest.TestCase):
    """Tests pour le fuzzy matching dans watchlist.compare_watchlist()."""

    def _make_row(self, title, year):
        import types

        return types.SimpleNamespace(proposed_title=title, proposed_year=year)

    def test_watchlist_exact_still_works(self):
        from cinesort.app.watchlist import compare_watchlist

        local = [self._make_row("Inception", 2010)]
        watchlist = [{"title": "Inception", "year": 2010}]
        result = compare_watchlist(watchlist, local)
        self.assertEqual(result["owned_count"], 1)
        self.assertEqual(result["missing_count"], 0)

    def test_watchlist_fuzzy_accent(self):
        """Titre avec accent dans la watchlist vs sans accent local → owned."""
        from cinesort.app.watchlist import compare_watchlist

        local = [self._make_row("Amelie Poulain", 2001)]
        watchlist = [{"title": "Amélie Poulain", "year": 2001}]
        result = compare_watchlist(watchlist, local)
        # L'accent est strip par _normalize_title → match exact en pass 1
        self.assertEqual(result["owned_count"], 1)

    def test_watchlist_fuzzy_article_order(self):
        """'Lord of the Rings' vs 'The Lord of the Rings' → owned via fuzzy."""
        from cinesort.app.watchlist import compare_watchlist

        # _normalize_title strip les articles, donc "lord of rings" devrait matcher
        local = [self._make_row("The Lord of the Rings", 2001)]
        watchlist = [{"title": "Lord of the Rings, The", "year": 2001}]
        result = compare_watchlist(watchlist, local)
        self.assertEqual(result["owned_count"], 1)

    def test_watchlist_fuzzy_below_threshold(self):
        """Titre trop different → missing."""
        from cinesort.app.watchlist import compare_watchlist

        local = [self._make_row("The Dark Knight", 2008)]
        watchlist = [{"title": "Dark Waters", "year": 2008}]
        result = compare_watchlist(watchlist, local)
        self.assertEqual(result["missing_count"], 1)

    def test_watchlist_fuzzy_year_protection(self):
        """Pass 2 fuzzy : meme titre fuzzy mais annee differente → missing.

        Note : le pass 1 exact matche "godzilla" via local_title_only (sans annee).
        Pour tester le filtre annee du fuzzy, on utilise un titre legerement different.
        """
        from cinesort.app.watchlist import compare_watchlist

        local = [self._make_row("Godzilla King of Monsters", 2019)]
        watchlist = [{"title": "Godzilla: King of the Monsters", "year": 2014}]
        # Annee 2014 ≠ 2019 et titre normalise different (articles) → pass 1 echoue
        # Pass 2 fuzzy : titre similaire mais annee differente → filtre annee → missing
        result = compare_watchlist(watchlist, local)
        self.assertEqual(result["missing_count"], 1)


if __name__ == "__main__":
    unittest.main()
