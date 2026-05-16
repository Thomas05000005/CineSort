"""Tests Library Timeline — films ajoutes par mois."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from cinesort.ui.api.library_timeline_support import (
    _generate_month_range,
    _parse_iso_to_month,
    get_library_timeline,
)


class ParseIsoToMonthTests(unittest.TestCase):
    def test_jellyfin_format_with_nanoseconds(self):
        # Jellyfin retourne "2024-03-15T18:30:00.0000000Z" (7-digit fractional)
        self.assertEqual(_parse_iso_to_month("2024-03-15T18:30:00.0000000Z"), "2024-03")

    def test_standard_iso_with_z(self):
        self.assertEqual(_parse_iso_to_month("2025-12-31T23:59:59Z"), "2025-12")

    def test_iso_with_tz_offset(self):
        self.assertEqual(_parse_iso_to_month("2024-06-15T12:00:00+02:00"), "2024-06")

    def test_date_only(self):
        self.assertEqual(_parse_iso_to_month("2024-03-15"), "2024-03")

    def test_empty_string(self):
        self.assertIsNone(_parse_iso_to_month(""))

    def test_none(self):
        self.assertIsNone(_parse_iso_to_month(None))

    def test_invalid_format(self):
        self.assertIsNone(_parse_iso_to_month("not-a-date"))

    def test_year_before_1990_rejected(self):
        # Garde-fou : annee implausible
        self.assertIsNone(_parse_iso_to_month("1985-01-01T00:00:00Z"))

    def test_year_after_2100_rejected(self):
        self.assertIsNone(_parse_iso_to_month("2150-01-01T00:00:00Z"))


class GenerateMonthRangeTests(unittest.TestCase):
    def test_12_months_from_dec_2025(self):
        result = _generate_month_range("2025-12", 12)
        # 12 mois reculs de Dec 2025 = Jan 2025 -> Dec 2025 (12 entries)
        self.assertEqual(len(result), 12)
        self.assertEqual(result[0], "2025-01")
        self.assertEqual(result[-1], "2025-12")

    def test_across_year_boundary(self):
        result = _generate_month_range("2026-03", 6)
        # 6 mois reculs de Mar 2026 = Oct 2025 -> Mar 2026
        self.assertEqual(result, ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"])

    def test_1_month(self):
        result = _generate_month_range("2025-07", 1)
        self.assertEqual(result, ["2025-07"])

    def test_invalid_format_returns_empty(self):
        self.assertEqual(_generate_month_range("invalid", 12), [])


class GetLibraryTimelineTests(unittest.TestCase):
    def setUp(self):
        self.mock_api = MagicMock()
        self.mock_api.settings.get_settings.return_value = {
            "state_dir": "/tmp/test",
            "jellyfin_enabled": False,
        }
        self.mock_store = MagicMock()
        self.mock_api._get_or_create_infra.return_value = (self.mock_store, None)
        self.mock_store.get_runs_summary.return_value = [{"run_id": "run-test"}]

    @patch("cinesort.ui.api.library_timeline_support._file_mtime_to_month")
    @patch("cinesort.ui.api.library_timeline_support._build_library_rows")
    @patch("cinesort.ui.api.library_timeline_support.normalize_user_path")
    def test_filesystem_only_aggregation(self, mock_norm, mock_build, mock_mtime):
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [
            {"path": "/m/Film1.mkv", "tmdb_id": "1"},
            {"path": "/m/Film2.mkv", "tmdb_id": "2"},
            {"path": "/m/Film3.mkv", "tmdb_id": "3"},
        ]
        # mtime simule : 2 films en 2025-06, 1 en 2025-07
        mock_mtime.side_effect = ["2025-06", "2025-06", "2025-07"]

        result = get_library_timeline(self.mock_api, months=3, run_id="run-test")
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "filesystem")
        self.assertEqual(result["total_films"], 3)
        # 100% des films ont une date
        self.assertEqual(result["films_with_date_pct"], 100.0)
        # 3 mois generates : on doit avoir 2025-05 (0), 2025-06 (2), 2025-07 (1)
        months_dict = {m["month"]: m["count"] for m in result["months"]}
        self.assertEqual(months_dict.get("2025-06"), 2)
        self.assertEqual(months_dict.get("2025-07"), 1)

    @patch("cinesort.ui.api.library_timeline_support._get_jellyfin_date_map")
    @patch("cinesort.ui.api.library_timeline_support._file_mtime_to_month")
    @patch("cinesort.ui.api.library_timeline_support._build_library_rows")
    @patch("cinesort.ui.api.library_timeline_support.normalize_user_path")
    def test_jellyfin_source_preferred(self, mock_norm, mock_build, mock_mtime, mock_jelly):
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [
            {"path": "/m/Film1.mkv", "tmdb_id": "1"},
            {"path": "/m/Film2.mkv", "tmdb_id": "2"},
        ]
        # Jellyfin connait les 2 films
        mock_jelly.return_value = {
            "1": "2024-12-15T10:00:00Z",
            "2": "2025-01-20T10:00:00Z",
        }
        # mtime n'est pas appele car Jellyfin couvre tout
        mock_mtime.return_value = "2030-01"

        result = get_library_timeline(self.mock_api, months=6, run_id="run-test")
        self.assertEqual(result["source"], "jellyfin")
        months_dict = {m["month"]: m["count"] for m in result["months"]}
        self.assertEqual(months_dict.get("2024-12"), 1)
        self.assertEqual(months_dict.get("2025-01"), 1)
        # mtime ne doit pas avoir ete consulte
        mock_mtime.assert_not_called()

    @patch("cinesort.ui.api.library_timeline_support._get_jellyfin_date_map")
    @patch("cinesort.ui.api.library_timeline_support._file_mtime_to_month")
    @patch("cinesort.ui.api.library_timeline_support._build_library_rows")
    @patch("cinesort.ui.api.library_timeline_support.normalize_user_path")
    def test_mixed_source(self, mock_norm, mock_build, mock_mtime, mock_jelly):
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [
            {"path": "/m/Film1.mkv", "tmdb_id": "1"},
            {"path": "/m/Film2.mkv", "tmdb_id": "2"},  # pas dans Jellyfin
        ]
        mock_jelly.return_value = {"1": "2024-12-15T10:00:00Z"}
        mock_mtime.return_value = "2024-12"  # fallback pour film 2

        result = get_library_timeline(self.mock_api, months=6, run_id="run-test")
        self.assertEqual(result["source"], "mixed")
        months_dict = {m["month"]: m["count"] for m in result["months"]}
        self.assertEqual(months_dict.get("2024-12"), 2)

    @patch("cinesort.ui.api.library_timeline_support._file_mtime_to_month")
    @patch("cinesort.ui.api.library_timeline_support._build_library_rows")
    @patch("cinesort.ui.api.library_timeline_support.normalize_user_path")
    def test_partial_coverage(self, mock_norm, mock_build, mock_mtime):
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [
            {"path": "/m/Film1.mkv", "tmdb_id": "1"},
            {"path": "/m/MissingFile.mkv", "tmdb_id": "2"},
        ]
        # Le 1er a un mtime, le 2eme echoue (None)
        mock_mtime.side_effect = ["2025-06", None]

        result = get_library_timeline(self.mock_api, months=3, run_id="run-test")
        # Pourcentage de coverage : 1/2 = 50%
        self.assertEqual(result["films_with_date_pct"], 50.0)
        self.assertEqual(result["total_films"], 2)

    def test_no_run_returns_empty(self):
        self.mock_store.get_runs_summary.return_value = []
        result = get_library_timeline(self.mock_api, months=12, run_id=None)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["run_id"])
        self.assertEqual(result["total_films"], 0)
        self.assertEqual(result["months"], [])

    @patch("cinesort.ui.api.library_timeline_support._file_mtime_to_month")
    @patch("cinesort.ui.api.library_timeline_support._build_library_rows")
    @patch("cinesort.ui.api.library_timeline_support.normalize_user_path")
    def test_months_capped_at_60(self, mock_norm, mock_build, mock_mtime):
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [{"path": "/m/F.mkv", "tmdb_id": "1"}]
        mock_mtime.return_value = "2025-06"
        result = get_library_timeline(self.mock_api, months=999, run_id="run-test")
        self.assertLessEqual(len(result["months"]), 60)

    @patch("cinesort.ui.api.library_timeline_support._file_mtime_to_month")
    @patch("cinesort.ui.api.library_timeline_support._build_library_rows")
    @patch("cinesort.ui.api.library_timeline_support.normalize_user_path")
    def test_months_min_1(self, mock_norm, mock_build, mock_mtime):
        mock_norm.return_value = "/tmp/test"
        mock_build.return_value = [{"path": "/m/F.mkv", "tmdb_id": "1"}]
        mock_mtime.return_value = "2025-06"
        result = get_library_timeline(self.mock_api, months=0, run_id="run-test")
        # months=0 (falsy) -> default 12, pas a 0
        self.assertEqual(len(result["months"]), 12)


if __name__ == "__main__":
    unittest.main()
