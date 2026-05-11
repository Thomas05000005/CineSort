"""Tests pour les ameliorations detection non-film V4."""

from __future__ import annotations

import unittest

from cinesort.domain.scan_helpers import not_a_movie_score


class DurationHeuristicTests(unittest.TestCase):
    """Tests pour l'heuristique duree."""

    def test_very_short_duration(self):
        """Fichier de 3 min → score eleve."""
        score = not_a_movie_score("trailer.mkv", 50_000_000, "unknown", 0, "Trailer", duration_s=180)
        self.assertGreaterEqual(score, 60)

    def test_short_duration(self):
        """Fichier de 15 min → +25 pts."""
        score_with = not_a_movie_score("film.mkv", 500_000_000, "tmdb", 80, "Good Film", duration_s=900)
        score_without = not_a_movie_score("film.mkv", 500_000_000, "tmdb", 80, "Good Film")
        self.assertGreater(score_with, score_without)

    def test_normal_duration_no_points(self):
        """Fichier de 120 min → pas de points duree."""
        score_with = not_a_movie_score("film.mkv", 5_000_000_000, "tmdb", 80, "Good Film", duration_s=7200)
        score_without = not_a_movie_score("film.mkv", 5_000_000_000, "tmdb", 80, "Good Film")
        self.assertEqual(score_with, score_without)

    def test_no_duration_unchanged(self):
        """duration_s=None → comportement inchange (meme score avec et sans)."""
        score_with = not_a_movie_score("film.mkv", 5_000_000_000, "tmdb", 80, "A Good Long Film Title", duration_s=None)
        score_without = not_a_movie_score("film.mkv", 5_000_000_000, "tmdb", 80, "A Good Long Film Title")
        self.assertEqual(score_with, score_without)


class NewKeywordsTests(unittest.TestCase):
    """Tests pour les nouveaux mots-cles."""

    def test_gag_reel(self):
        score = not_a_movie_score("gag reel.mkv", 200_000_000, "unknown", 0, "Gag Reel")
        self.assertGreaterEqual(score, 40)

    def test_blooper(self):
        score = not_a_movie_score("bloopers.mkv", 200_000_000, "unknown", 0, "Bloopers")
        self.assertGreaterEqual(score, 40)


if __name__ == "__main__":
    unittest.main()
