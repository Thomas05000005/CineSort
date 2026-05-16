"""Tests Phase 6.3 — parse_scene_title.

Couvre :
- Strip release group (-XXXXX)
- Strip audio residue (HD MA, 5.1, 7.1, Atmos)
- Position-aware : tags ambigus (FRENCH, CUT, EDITION) stripes seulement
  apres le token annee, jamais avant (preserve "The French Connection",
  "The Final Cut", "Le Capitaine Fracasse 1961 FRENCH")
- Films-annee preserves (1917, 2001 Space Odyssey, Blade Runner 2049)
- Edge cases : Spider-Man hyphen, fichiers renommes main, parentheses
"""

from __future__ import annotations

import unittest

from cinesort.domain.scene_parser import parse_scene_title


class StripReleaseGroupTests(unittest.TestCase):
    def test_basic_release_group_stripped(self):
        self.assertEqual(
            parse_scene_title("Inception.2010.1080p.BluRay.x264-RARBG.mkv"),
            "Inception 2010",
        )

    def test_release_group_camelcase(self):
        self.assertEqual(
            parse_scene_title("Movie.2020.1080p.BluRay.x264-NoTag.mkv"),
            "Movie 2020",
        )

    def test_spider_man_hyphen_preserved(self):
        # Le hyphen interne du titre ne doit pas etre traite comme separateur groupe
        self.assertEqual(
            parse_scene_title("Spider-Man.2002.1080p.BluRay-WiKi.mkv"),
            "Spider-Man 2002",
        )

    def test_x_men_hyphen_preserved(self):
        self.assertEqual(
            parse_scene_title("X-Men.Days.of.Future.Past.2014.1080p.BluRay-CMRG.mkv"),
            "X-Men Days of Future Past 2014",
        )


class StripAudioResidueTests(unittest.TestCase):
    def test_dts_hd_ma_residue_stripped(self):
        self.assertEqual(
            parse_scene_title("Movie.2015.1080p.BluRay.DTS-HD.MA.5.1.x264-Tigole.mkv"),
            "Movie 2015",
        )

    def test_truehd_71_atmos_stripped(self):
        self.assertEqual(
            parse_scene_title(
                "Mad.Max.Fury.Road.2015.MULTi.UHD.BluRay.2160p.HDR.HEVC.TrueHD.7.1.Atmos-VeXHD.mkv"
            ),
            "Mad Max Fury Road 2015",
        )

    def test_audio_channels_50_71(self):
        self.assertEqual(
            parse_scene_title("Movie.2010.1080p.BluRay.AC3.5.1.x264-NoTag.mkv"),
            "Movie 2010",
        )


class PositionAwareLanguageTests(unittest.TestCase):
    """Langues stripees apres annee, preservees si elles font partie du titre."""

    def test_french_after_year_stripped(self):
        self.assertEqual(
            parse_scene_title("Le.Capitaine.Fracasse.1961.FRENCH.1080p.BluRay.DTS.x264-fist.mkv"),
            "Le Capitaine Fracasse 1961",
        )

    def test_french_in_title_preserved(self):
        # "The French Connection" - "French" est AVANT 1975
        self.assertEqual(
            parse_scene_title("The.French.Connection.2.1975.avi"),
            "The French Connection 2 1975",
        )

    def test_french_in_title_with_scene_tags_preserved(self):
        self.assertEqual(
            parse_scene_title("The.French.Connection.2.1975.1080p.BluRay.x264.mkv"),
            "The French Connection 2 1975",
        )

    def test_multi_vff_combo_after_year_stripped(self):
        self.assertEqual(
            parse_scene_title("12.Years.a.Slave.2013.MULTi.VFF.1080p.10bit.BluRay.DTS-HD.MA.5.1.x265-T4KT.mkv"),
            "12 Years a Slave 2013",
        )

    def test_le_ruffian_french_web_stripped(self):
        # Cas reel : "Le Ruffian 1982 FRENCH WEB" doit donner "Le Ruffian 1982"
        self.assertEqual(
            parse_scene_title("Le.Ruffian.1982.FRENCH.SDR.2160p.WEB.H265-BULiTT.mkv"),
            "Le Ruffian 1982",
        )

    def test_amelie_poulain_french_stripped(self):
        self.assertEqual(
            parse_scene_title("Le.Fabuleux.Destin.dAmelie.Poulain.2001.FRENCH.1080p.BluRay.x264-AVCHD.mkv"),
            "Le Fabuleux Destin dAmelie Poulain 2001",
        )


class PositionAwareEditionTests(unittest.TestCase):
    """Editions (Cut, Edition) stripees apres annee, preservees si dans le titre."""

    def test_directors_cut_after_year_stripped(self):
        self.assertEqual(
            parse_scene_title("Blade.Runner.2049.2017.Directors.Cut.1080p.BluRay.x264.mkv"),
            "Blade Runner 2049 2017",
        )

    def test_the_final_cut_in_title_preserved(self):
        # "The Final Cut" (1992) est un vrai titre, Final+Cut sont AVANT 1992
        self.assertEqual(
            parse_scene_title("The.Final.Cut.1992.BluRay.mkv"),
            "The Final Cut 1992",
        )

    def test_the_final_cut_with_scene_tags_preserved(self):
        self.assertEqual(
            parse_scene_title("The.Final.Cut.1992.1080p.BluRay.x264-NoTag.mkv"),
            "The Final Cut 1992",
        )


class FilmsNamedAfterYearTests(unittest.TestCase):
    """Films-annee : 1917, 2001 Space Odyssey, Blade Runner 2049 — preserves."""

    def test_2001_space_odyssey_year_in_title_preserved(self):
        self.assertEqual(
            parse_scene_title("2001.A.Space.Odyssey.1968.1080p.BluRay.x264.mkv"),
            "2001 A Space Odyssey 1968",
        )

    def test_1917_year_in_title_preserved(self):
        self.assertEqual(
            parse_scene_title("1917.2019.1080p.BluRay.x264.mkv"),
            "1917 2019",
        )

    def test_blade_runner_2049_year_in_title_preserved(self):
        self.assertEqual(
            parse_scene_title("Blade.Runner.2049.2017.1080p.BluRay.x264-NoTag.mkv"),
            "Blade Runner 2049 2017",
        )

    def test_film_28_years_later_2025(self):
        # Annee 2025 doit etre detectee (NOISE_RE ne fait pas year detection)
        self.assertEqual(
            parse_scene_title("28.Years.Later.2025.MULTi.1080p.WEB-DL.x265.mkv"),
            "28 Years Later 2025",
        )

    def test_dune_2024_year_after_title(self):
        self.assertEqual(
            parse_scene_title(
                "Dune.Part.Two.2024.2160p.UHD.BluRay.x265.10bit.HDR.DTS-HD.MA.7.1-SWTYBLZ.mkv"
            ),
            "Dune Part Two 2024",
        )


class ParenthesizedYearTests(unittest.TestCase):
    def test_paren_year_stripped(self):
        self.assertEqual(
            parse_scene_title("Toy Story 4 (2019) 1080p.mkv"),
            "Toy Story 4",
        )

    def test_paren_year_with_french(self):
        self.assertEqual(
            parse_scene_title("Le Capitaine Fracasse (1961) FRENCH.mkv"),
            "Le Capitaine Fracasse",
        )

    def test_bracketed_year_stripped(self):
        self.assertEqual(
            parse_scene_title("Inception [2010] 1080p.mkv"),
            "Inception",
        )


class ManuallyRenamedFilesTests(unittest.TestCase):
    """Fichiers renommes a la main (sans tags scene)."""

    def test_single_word_title(self):
        self.assertEqual(parse_scene_title("Inception.mkv"), "Inception")

    def test_simple_title_with_year(self):
        self.assertEqual(
            parse_scene_title("Le Capitaine Fracasse 1961.mkv"),
            "Le Capitaine Fracasse 1961",
        )

    def test_title_without_extension(self):
        self.assertEqual(parse_scene_title("Inception"), "Inception")


class EdgeCasesTests(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(parse_scene_title(""), "")

    def test_only_extension(self):
        self.assertEqual(parse_scene_title(".mkv"), "")

    def test_no_year_no_tags(self):
        # Pas d'annee : NOISE_RE seulement, pas d'effet position-aware
        self.assertEqual(
            parse_scene_title("Some Random Film.mkv"),
            "Some Random Film",
        )

    def test_only_year(self):
        # Annee seule sans titre — possible avec un nom degnere
        self.assertEqual(parse_scene_title("2010.mkv"), "2010")

    def test_double_separators(self):
        self.assertEqual(
            parse_scene_title("Movie..Title...2010.mkv"),
            "Movie Title 2010",
        )

    def test_underscore_separators(self):
        self.assertEqual(
            parse_scene_title("Movie_Title_2010_1080p_BluRay.mkv"),
            "Movie Title 2010",
        )


class IntegrationWithCleanTitleGuessTests(unittest.TestCase):
    """Verifie que clean_title_guess() delegue bien a parse_scene_title()."""

    def test_clean_title_guess_uses_new_parser(self):
        from cinesort.domain.title_helpers import clean_title_guess

        # Cas ou parse_scene_title fait mieux que l'ancien regex
        result = clean_title_guess("Mad.Max.Fury.Road.2015.MULTi.BluRay.x264-VeXHD.mkv")
        self.assertEqual(result, "Mad Max Fury Road 2015")

    def test_clean_title_guess_preserves_french_in_title(self):
        from cinesort.domain.title_helpers import clean_title_guess

        # Regression : "The French Connection" doit conserver "French"
        result = clean_title_guess("The French Connection 2.avi")
        self.assertEqual(result, "The French Connection 2")


if __name__ == "__main__":
    unittest.main()
