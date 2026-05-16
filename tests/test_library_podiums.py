"""Tests Dashboard Podiums — extract_release_group, extract_source, get_library_podiums."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from cinesort.domain.scene_parser import extract_release_group, extract_source
from cinesort.ui.api.library_podiums_support import (
    _aggregate_top,
    get_library_podiums,
)


class ExtractReleaseGroupTests(unittest.TestCase):
    """Heuristique : release group = segment apres dernier `-`, validee par
    presence d'un marker scene (annee/codec/resolution) dans le prefixe."""

    def test_standard_scene_release(self):
        self.assertEqual(
            extract_release_group("Inception.2010.1080p.BluRay.x264-RARBG.mkv"),
            "RARBG",
        )

    def test_mixed_case_group_preserved(self):
        self.assertEqual(
            extract_release_group("Mad.Max.2015.2160p.Atmos-VeXHD.mkv"),
            "VeXHD",
        )

    def test_lowercase_group(self):
        self.assertEqual(
            extract_release_group("Movie.1961.1080p.BluRay.x264-fist.mkv"),
            "fist",
        )

    def test_alphanum_group(self):
        self.assertEqual(
            extract_release_group("Film.2013.1080p.x265-T4KT.mkv"),
            "T4KT",
        )

    def test_spider_man_hyphen_not_detected_as_group(self):
        # Tiret interne au titre + pas de scene marker = pas un groupe
        self.assertIsNone(extract_release_group("Spider-Man.mkv"))

    def test_spider_man_with_year_no_dash_after(self):
        # "Spider-Man.2002.1080p.mkv" - pas de tiret apres l'annee
        self.assertIsNone(extract_release_group("Spider-Man.2002.1080p.mkv"))

    def test_no_dash_at_all(self):
        self.assertIsNone(extract_release_group("Inception.mkv"))

    def test_empty_filename(self):
        self.assertIsNone(extract_release_group(""))

    def test_no_scene_marker_rejects_candidate(self):
        # "Some Title-Extra.mkv" - pas de marker scene = pas un groupe
        self.assertIsNone(extract_release_group("Some.Title-Extra.mkv"))

    def test_candidate_with_only_digits_rejected(self):
        # "Movie.2010.1080p-2020.mkv" - candidate "2020" = pas de lettre
        self.assertIsNone(extract_release_group("Movie.2010.1080p-2020.mkv"))

    def test_only_dash_at_end(self):
        # Pas de candidate apres le dernier tiret
        self.assertIsNone(extract_release_group("Movie.2010.1080p-.mkv"))


class ExtractSourceTests(unittest.TestCase):
    def test_bluray(self):
        self.assertEqual(extract_source("Movie.2010.BluRay.x264.mkv"), "BluRay")

    def test_bluray_remux(self):
        self.assertEqual(extract_source("Movie.2020.BD-Remux.x264.mkv"), "BluRay Remux")

    def test_remux_alone(self):
        self.assertEqual(extract_source("Movie.2020.Remux.x264.mkv"), "Remux")

    def test_web_dl(self):
        self.assertEqual(extract_source("Movie.2024.WEB-DL.x265.mkv"), "WEB-DL")

    def test_web_rip(self):
        self.assertEqual(extract_source("Movie.2024.WEBRip.x264.mkv"), "WEBRip")

    def test_hdtv(self):
        self.assertEqual(extract_source("Movie.2020.HDTV.x264.mkv"), "HDTV")

    def test_dvdrip(self):
        self.assertEqual(extract_source("Movie.1999.DVDRip.XviD.avi"), "DVDRip")

    def test_bdrip(self):
        self.assertEqual(extract_source("Movie.2010.BDRip.x264.mkv"), "BDRip")

    def test_no_source(self):
        self.assertIsNone(extract_source("Inception.mkv"))

    def test_empty(self):
        self.assertIsNone(extract_source(""))

    def test_priority_bluray_remux_over_remux(self):
        # "BD-Remux" doit matcher "BluRay Remux", pas "Remux" seul
        self.assertEqual(extract_source("Movie.2020.BD.Remux.mkv"), "BluRay Remux")

    def test_priority_bluray_remux_over_bluray(self):
        self.assertEqual(extract_source("Movie.2020.BluRay.Remux.mkv"), "Remux")


class AggregateTopTests(unittest.TestCase):
    def test_simple_count(self):
        result = _aggregate_top(["a", "a", "b", "c", "a"], limit=10)
        self.assertEqual(result, [{"name": "a", "count": 3}, {"name": "b", "count": 1}, {"name": "c", "count": 1}])

    def test_limit_respected(self):
        result = _aggregate_top(["a", "b", "c", "d", "e"], limit=2)
        self.assertEqual(len(result), 2)

    def test_none_and_empty_ignored(self):
        result = _aggregate_top(["a", None, "", "  ", "a"], limit=10)
        self.assertEqual(result, [{"name": "a", "count": 2}])

    def test_tie_sorted_alphabetically(self):
        # Egalite de count : tri alphabetique
        result = _aggregate_top(["zoo", "apple", "zoo", "apple"], limit=10)
        self.assertEqual(result[0]["name"], "apple")  # tie sur 2, "apple" avant "zoo"
        self.assertEqual(result[1]["name"], "zoo")

    def test_empty_list(self):
        self.assertEqual(_aggregate_top([], limit=10), [])


class GetLibraryPodiumsTests(unittest.TestCase):
    def setUp(self):
        self.mock_api = MagicMock()
        self.mock_api.settings.get_settings.return_value = {"state_dir": "/tmp/test"}
        # Mock store
        self.mock_store = MagicMock()
        self.mock_api._get_or_create_infra.return_value = (self.mock_store, None)
        self.mock_store.get_runs_summary.return_value = [{"run_id": "run-test-1"}]

    @patch("cinesort.ui.api.library_podiums_support._build_library_rows")
    @patch("cinesort.ui.api.library_podiums_support.normalize_user_path")
    def test_basic_podiums(self, mock_norm, mock_build):
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [
            {"path": "/m/Inception.2010.1080p.BluRay.x264-RARBG.mkv", "codec": "x264"},
            {"path": "/m/Mad.Max.2015.2160p.BluRay.x265-VeXHD.mkv", "codec": "x265"},
            {"path": "/m/Dune.2024.WEB-DL.x265-CTRLHD.mkv", "codec": "x265"},
        ]
        result = get_library_podiums(self.mock_api, run_id="run-test-1", limit=5)
        self.assertTrue(result["ok"])
        self.assertEqual(result["total_films"], 3)
        # Release groups
        rg_names = [r["name"] for r in result["release_groups"]]
        self.assertIn("RARBG", rg_names)
        self.assertIn("VeXHD", rg_names)
        self.assertIn("CTRLHD", rg_names)
        # Codecs : x265 doit etre en haut (2 vs 1)
        self.assertEqual(result["codecs"][0]["name"], "x265")
        self.assertEqual(result["codecs"][0]["count"], 2)
        # Sources : 2 BluRay vs 1 WEB-DL
        sources_dict = {s["name"]: s["count"] for s in result["sources"]}
        self.assertEqual(sources_dict.get("BluRay"), 2)
        self.assertEqual(sources_dict.get("WEB-DL"), 1)
        # Coverage
        self.assertEqual(result["coverage"]["release_groups_pct"], 100.0)
        self.assertEqual(result["coverage"]["codecs_pct"], 100.0)
        self.assertEqual(result["coverage"]["sources_pct"], 100.0)

    @patch("cinesort.ui.api.library_podiums_support._build_library_rows")
    @patch("cinesort.ui.api.library_podiums_support.normalize_user_path")
    def test_partial_coverage(self, mock_norm, mock_build):
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [
            {"path": "/m/Inception.2010.1080p.BluRay.x264-RARBG.mkv", "codec": "x264"},
            {"path": "/m/Random.mkv", "codec": None},  # ni group ni source ni codec
            {"path": "/m/Spider-Man.mkv", "codec": "x264"},  # codec OK, pas de group/source
        ]
        result = get_library_podiums(self.mock_api, run_id="run-test-1", limit=5)
        # 1 film avec release group sur 3 = 33.3%
        self.assertAlmostEqual(result["coverage"]["release_groups_pct"], 33.3, places=1)
        # 2 films avec codec sur 3 = 66.7%
        self.assertAlmostEqual(result["coverage"]["codecs_pct"], 66.7, places=1)
        # 1 film avec source sur 3 = 33.3%
        self.assertAlmostEqual(result["coverage"]["sources_pct"], 33.3, places=1)

    def test_no_run_returns_empty_payload(self):
        # Aucun run dans store
        self.mock_store.get_runs_summary.return_value = []
        result = get_library_podiums(self.mock_api, run_id=None, limit=10)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["run_id"])
        self.assertEqual(result["total_films"], 0)
        self.assertEqual(result["release_groups"], [])

    @patch("cinesort.ui.api.library_podiums_support._build_library_rows")
    @patch("cinesort.ui.api.library_podiums_support.normalize_user_path")
    def test_limit_capped_at_50(self, mock_norm, mock_build):
        mock_norm.return_value = "/tmp/test"
        # 60 films chacun avec un group different
        mock_build.return_value = [
            {"path": f"/m/Movie{i}.2020.1080p.x264-GROUP{i}.mkv", "codec": "x264"} for i in range(60)
        ]
        # Demande limit=100 -> cape a 50
        result = get_library_podiums(self.mock_api, run_id="run-test-1", limit=100)
        self.assertLessEqual(len(result["release_groups"]), 50)

    @patch("cinesort.ui.api.library_podiums_support._build_library_rows")
    @patch("cinesort.ui.api.library_podiums_support.normalize_user_path")
    def test_limit_min_1(self, mock_norm, mock_build):
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [
            {"path": "/m/Movie.2020.x264-RARBG.mkv", "codec": "x264"},
            {"path": "/m/Movie2.2020.x265-CTRLHD.mkv", "codec": "x265"},
        ]
        # Demande limit=1 -> retourne 1 seul element
        result = get_library_podiums(self.mock_api, run_id="run-test-1", limit=1)
        self.assertEqual(len(result["release_groups"]), 1)


if __name__ == "__main__":
    unittest.main()
