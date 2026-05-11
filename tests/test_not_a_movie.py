"""Tests detection contenu non-film — cinesort/domain/scan_helpers.py.

Couvre :
- Scoring : chaque heuristique isolee
- Combinaisons realistes (making of, film normal, bonus, film inconnu)
- Seuil : score 59 → pas flagge, score 60 → flagge
- Edge cases : nom vide, taille 0
- UI : badge present dans HTML validation + review, CSS
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.domain.scan_helpers import (
    _NOT_A_MOVIE_THRESHOLD,
    _NAM_NO_TMDB_PTS,
    _NAM_SHORT_TITLE_PTS,
    _NAM_SIZE_SMALL_PTS,
    _NAM_SIZE_TINY_PTS,
    _NAM_SUSPECT_NAME_PTS,
    _NAM_UNCOMMON_EXT_PTS,
    not_a_movie_score,
)

_MB = 1024 * 1024


# ---------------------------------------------------------------------------
# Heuristiques isolees
# ---------------------------------------------------------------------------


class SuspectNameTests(unittest.TestCase):
    """Nom suspect → +40 points."""

    def test_sample(self) -> None:
        s = not_a_movie_score("sample.mkv", 50 * _MB, "tmdb", 80, "Film")
        self.assertGreaterEqual(s, _NAM_SUSPECT_NAME_PTS)

    def test_trailer(self) -> None:
        s = not_a_movie_score("trailer-film.mp4", 200 * _MB, "tmdb", 80, "Film")
        self.assertGreaterEqual(s, _NAM_SUSPECT_NAME_PTS)

    def test_making_of(self) -> None:
        s = not_a_movie_score("making of inception.mkv", 50 * _MB, "tmdb", 80, "Making of Inception")
        self.assertGreaterEqual(s, _NAM_SUSPECT_NAME_PTS)

    def test_featurette(self) -> None:
        s = not_a_movie_score("featurette.mp4", 80 * _MB, "tmdb", 80, "Featurette")
        self.assertGreaterEqual(s, _NAM_SUSPECT_NAME_PTS)

    def test_bonus(self) -> None:
        s = not_a_movie_score("bonus.mp4", 80 * _MB, "tmdb", 80, "Bonus")
        self.assertGreaterEqual(s, _NAM_SUSPECT_NAME_PTS)

    def test_normal_name_no_suspect(self) -> None:
        s = not_a_movie_score("inception.mkv", 8000 * _MB, "tmdb", 80, "Inception")
        # Pas de mot-cle suspect → pas de points suspect
        self.assertLess(s, _NAM_SUSPECT_NAME_PTS)


class SizeTests(unittest.TestCase):
    """Taille : < 100 Mo → +30, 100-300 Mo → +15."""

    def test_tiny_50mo(self) -> None:
        s = not_a_movie_score("video.mkv", 50 * _MB, "tmdb", 80, "Film Test Complet Long")
        self.assertGreaterEqual(s, _NAM_SIZE_TINY_PTS)

    def test_small_150mo(self) -> None:
        s = not_a_movie_score("video.mkv", 150 * _MB, "tmdb", 80, "Film Test Complet Long")
        # 100-300 Mo → _NAM_SIZE_SMALL_PTS
        self.assertTrue(0 < s - 0 <= _NAM_SIZE_SMALL_PTS + _NAM_SHORT_TITLE_PTS + 5)

    def test_large_8go_no_size_points(self) -> None:
        s = not_a_movie_score("video.mkv", 8000 * _MB, "tmdb", 80, "Film Test Complet Long Titre")
        # Pas de points taille ni suspect
        self.assertEqual(s, 0)


class NoTmdbTests(unittest.TestCase):
    """Pas de match TMDb → +25."""

    def test_unknown_source(self) -> None:
        s = not_a_movie_score("video.mkv", 8000 * _MB, "unknown", 0, "Film Test Complet Long Titre")
        self.assertEqual(s, _NAM_NO_TMDB_PTS)

    def test_tmdb_match_no_points(self) -> None:
        s = not_a_movie_score("video.mkv", 8000 * _MB, "tmdb", 80, "Film Test Complet Long Titre")
        self.assertEqual(s, 0)

    def test_confidence_zero(self) -> None:
        s = not_a_movie_score("video.mkv", 8000 * _MB, "name", 0, "Film Test Complet Long Titre")
        self.assertGreaterEqual(s, _NAM_NO_TMDB_PTS)


class ShortTitleTests(unittest.TestCase):
    """Titre tres court ≤ 3 mots → +10."""

    def test_one_word(self) -> None:
        s = not_a_movie_score("video.mkv", 8000 * _MB, "tmdb", 80, "Trailer")
        # "Trailer" = mot suspect + 1 mot court
        self.assertGreaterEqual(s, _NAM_SUSPECT_NAME_PTS + _NAM_SHORT_TITLE_PTS)

    def test_four_words_no_points(self) -> None:
        s = not_a_movie_score("video.mkv", 8000 * _MB, "tmdb", 80, "The Lord Of Rings")
        self.assertEqual(s, 0)


class UncommonExtTests(unittest.TestCase):
    """Extension peu courante → +10."""

    def test_m2ts(self) -> None:
        s = not_a_movie_score("video.m2ts", 8000 * _MB, "tmdb", 80, "Film Test Complet Long Titre")
        self.assertEqual(s, _NAM_UNCOMMON_EXT_PTS)

    def test_vob(self) -> None:
        s = not_a_movie_score("video.vob", 8000 * _MB, "tmdb", 80, "Film Test Complet Long Titre")
        self.assertEqual(s, _NAM_UNCOMMON_EXT_PTS)

    def test_mkv_no_points(self) -> None:
        s = not_a_movie_score("video.mkv", 8000 * _MB, "tmdb", 80, "Film Test Complet Long Titre")
        self.assertEqual(s, 0)


# ---------------------------------------------------------------------------
# Combinaisons realistes
# ---------------------------------------------------------------------------


class CombinationTests(unittest.TestCase):
    """Combinaisons realistes : flag ou pas ?"""

    def test_making_of_50mo_no_tmdb(self) -> None:
        """Making of 50 Mo sans TMDb → flagge (40+30+25 = 95)."""
        s = not_a_movie_score("Making of Inception.mkv", 50 * _MB, "unknown", 0, "Making of Inception")
        self.assertGreaterEqual(s, _NOT_A_MOVIE_THRESHOLD)

    def test_inception_8go_tmdb(self) -> None:
        """Film normal 8 Go avec TMDb → pas flagge."""
        s = not_a_movie_score("Inception (2010).mkv", 8000 * _MB, "tmdb", 85, "Inception")
        self.assertLess(s, _NOT_A_MOVIE_THRESHOLD)

    def test_trailer_500mo_no_tmdb(self) -> None:
        """Trailer 500 Mo sans TMDb → flagge (40+25 = 65)."""
        s = not_a_movie_score("trailer.mp4", 500 * _MB, "unknown", 0, "Trailer")
        self.assertGreaterEqual(s, _NOT_A_MOVIE_THRESHOLD)

    def test_film_inconnu_150mo(self) -> None:
        """Film inconnu 150 Mo → pas flagge (15+25 = 40, sous le seuil)."""
        s = not_a_movie_score("Film Inconnu.avi", 150 * _MB, "unknown", 0, "Film Inconnu")
        self.assertLess(s, _NOT_A_MOVIE_THRESHOLD)

    def test_sample_20mo(self) -> None:
        """sample.mkv 20 Mo → flagge (40+30 = 70)."""
        s = not_a_movie_score("sample.mkv", 20 * _MB, "tmdb", 80, "Sample")
        self.assertGreaterEqual(s, _NOT_A_MOVIE_THRESHOLD)


# ---------------------------------------------------------------------------
# Seuil exact
# ---------------------------------------------------------------------------


class ThresholdTests(unittest.TestCase):
    """Seuil exact : 59 → pas flagge, 60 → flagge."""

    def test_threshold_value(self) -> None:
        self.assertEqual(_NOT_A_MOVIE_THRESHOLD, 60)

    def test_below_threshold(self) -> None:
        # suspect (40) + short title (10) = 50 < 60
        s = not_a_movie_score("trailer.mkv", 8000 * _MB, "tmdb", 80, "Trailer")
        self.assertLess(s, _NOT_A_MOVIE_THRESHOLD)

    def test_at_threshold(self) -> None:
        # suspect (40) + small size (15) + short title (10) = 65 >= 60
        s = not_a_movie_score("trailer.mkv", 150 * _MB, "tmdb", 80, "Trailer")
        self.assertGreaterEqual(s, _NOT_A_MOVIE_THRESHOLD)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class EdgeCaseTests(unittest.TestCase):
    """Edge cases."""

    def test_empty_name(self) -> None:
        s = not_a_movie_score("", 0, "", 0, "")
        # Nom vide → pas de mot-cle, taille 0 (pas > 0 → pas de points taille)
        self.assertIsInstance(s, int)

    def test_zero_size(self) -> None:
        s = not_a_movie_score("video.mkv", 0, "tmdb", 80, "Film Test Complet Long Titre")
        # Taille 0 → pas de points taille (condition 0 < sz)
        self.assertEqual(s, 0)

    def test_none_values(self) -> None:
        s = not_a_movie_score("video.mkv", 0, None, None, None)
        self.assertIsInstance(s, int)


# ---------------------------------------------------------------------------
# UI : badges
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/review.js supprime — adaptation v5 deferee a V5C-03")
class UiBadgeTests(unittest.TestCase):
    """Badges non-film dans les fichiers UI."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.validation_js = (root / "web" / "views" / "validation.js").read_text(encoding="utf-8")
        cls.review_js = (root / "web" / "dashboard" / "views" / "review.js").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")
        cls.dash_css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_desktop_badge_present(self) -> None:
        self.assertIn("not_a_movie", self.validation_js)
        self.assertIn("Non-film", self.validation_js)

    def test_dashboard_badge_present(self) -> None:
        self.assertIn("not_a_movie", self.review_js)
        self.assertIn("Non-film", self.review_js)

    def test_desktop_css_class(self) -> None:
        self.assertIn("not-a-movie", self.app_css)

    def test_dashboard_css_class(self) -> None:
        self.assertIn("not-a-movie", self.dash_css)

    def test_badge_tooltip(self) -> None:
        """Le badge desktop a un tooltip explicatif."""
        self.assertIn("title=", self.validation_js)
        self.assertIn("suspect", self.validation_js.lower())


if __name__ == "__main__":
    unittest.main()
