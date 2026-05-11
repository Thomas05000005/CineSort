"""Tests pour les patterns TV V4 (dot separator, texte Season/Saison)."""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.domain.tv_helpers import parse_tv_info


class DotSeparatorTests(unittest.TestCase):
    """Tests pour le pattern S01.E01 (point entre S et E)."""

    def test_s01_dot_e05(self):
        info = parse_tv_info(Path("/Shows/MyShow"), Path("MyShow.S01.E05.mkv"))
        self.assertIsNotNone(info)
        self.assertEqual(info.season, 1)
        self.assertEqual(info.episode, 5)

    def test_s02_dot_e10(self):
        info = parse_tv_info(Path("/Shows/MyShow"), Path("Show.S02.E10.1080p.mkv"))
        self.assertIsNotNone(info)
        self.assertEqual(info.season, 2)
        self.assertEqual(info.episode, 10)

    def test_existing_s01e01_still_works(self):
        info = parse_tv_info(Path("/Shows/MyShow"), Path("Show.S01E01.mkv"))
        self.assertIsNotNone(info)
        self.assertEqual(info.season, 1)
        self.assertEqual(info.episode, 1)

    def test_existing_1x01_still_works(self):
        info = parse_tv_info(Path("/Shows/MyShow"), Path("Show.1x01.mkv"))
        self.assertIsNotNone(info)
        self.assertEqual(info.season, 1)
        self.assertEqual(info.episode, 1)


class SeasonEpisodeTextTests(unittest.TestCase):
    """Tests pour le pattern 'Season N Episode N' (texte)."""

    def test_season_episode_english(self):
        info = parse_tv_info(Path("/Shows/MyShow"), Path("MyShow Season 2 Episode 10.mkv"))
        self.assertIsNotNone(info)
        self.assertEqual(info.season, 2)
        self.assertEqual(info.episode, 10)

    def test_saison_episode_french(self):
        info = parse_tv_info(Path("/Shows/MaSerie"), Path("MaSerie Saison 1 Episode 3.mkv"))
        self.assertIsNotNone(info)
        self.assertEqual(info.season, 1)
        self.assertEqual(info.episode, 3)

    def test_no_false_positive_film(self):
        """Un film normal ne doit pas etre detecte comme serie."""
        info = parse_tv_info(Path("/Movies/Inception (2010)"), Path("Inception.2010.1080p.mkv"))
        self.assertIsNone(info)

    def test_no_false_positive_brackets(self):
        """Un film avec crochets ne doit pas etre detecte comme serie."""
        info = parse_tv_info(Path("/Movies/Film"), Path("[Remastered] Film 2020.mkv"))
        self.assertIsNone(info)


if __name__ == "__main__":
    unittest.main()
