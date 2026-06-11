"""GATE AUDIT 2026-06-10 (REAL 2/2, invariant titres) — parse_scene_title ne
mutile plus les titres reels.

Deux bugs corriges :
1. _AUDIO_RESIDUE_RE : separateur de canal optionnel + tokens nus "ma"/"hra"
   mutilaient "21 Jump Street", "50 First Dates", "Ma Vie de Courgette", etc.
2. _RELEASE_GROUP_RE applique sans garde scene -> "Thor - Ragnarok" -> "Thor".
"""

from __future__ import annotations

import unittest

from cinesort.domain.scene_parser import parse_scene_title


class TitlePreservationTests(unittest.TestCase):
    def test_number_titles_not_mutilated(self) -> None:
        self.assertEqual(parse_scene_title("21 Jump Street (2012)"), "21 Jump Street")
        self.assertEqual(parse_scene_title("50 First Dates"), "50 First Dates")
        self.assertEqual(parse_scene_title("20 000 Leagues Under the Sea (1954)"),
                         "20 000 Leagues Under the Sea")

    def test_ma_titlecase_word_preserved(self) -> None:
        self.assertEqual(parse_scene_title("Ma Vie de Courgette"), "Ma Vie de Courgette")

    def test_subtitle_after_dash_preserved_without_tech_marker(self) -> None:
        self.assertEqual(parse_scene_title("Thor - Ragnarok (2017)"), "Thor - Ragnarok")
        self.assertEqual(parse_scene_title("Blade - Trinity (2004)"), "Blade - Trinity")
        self.assertEqual(parse_scene_title("Cloverfield - Paradox"), "Cloverfield - Paradox")


class RealReleaseStillCleanedTests(unittest.TestCase):
    def test_release_group_stripped_when_tech_marker_present(self) -> None:
        self.assertEqual(
            parse_scene_title("Thor.Ragnarok.2017.1080p.BluRay.x264-SPARKS"),
            "Thor Ragnarok 2017",
        )

    def test_dts_hd_ma_audio_tag_still_stripped(self) -> None:
        # "MA" en majuscules (tag audio) toujours retire ; titre propre.
        self.assertEqual(
            parse_scene_title("Movie.2015.1080p.BluRay.DTS-HD.MA.5.1.x264-Tigole.mkv"),
            "Movie 2015",
        )

    def test_channel_layout_still_stripped(self) -> None:
        self.assertEqual(
            parse_scene_title("Dune.Part.Two.2024.2160p.BluRay.DTS-HD.MA.7.1-SWTYBLZ.mkv"),
            "Dune Part Two 2024",
        )


if __name__ == "__main__":
    unittest.main()
