"""Tests unitaires pour export_support (HTML, NFO, CSV enrichi)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cinesort.app.export_support import (
    _build_nfo_xml,
    export_html_report,
    export_nfo_for_run,
)


def _make_report(rows=None, counts=None):
    """Helper : construit un report payload minimal pour les tests."""
    default_counts = {
        "rows_total": 3,
        "validated_ok": 2,
        "quality_reports": 3,
        "quality_probe_partial": 0,
        "quality_tiers": {"premium": 1, "bon": 1, "moyen": 1},
    }
    default_rows = [
        {
            "run_id": "test-run-001",
            "row_id": "r1",
            "kind": "single",
            "folder": "D:\\Films\\Avatar (2009)",
            "video": "Avatar.mkv",
            "proposed_title": "Avatar",
            "proposed_year": 2009,
            "proposed_source": "nfo",
            "confidence": 95,
            "confidence_label": "high",
            "decision_ok": True,
            "decision_title": "Avatar",
            "decision_year": 2009,
            "quality_status": "analyzed",
            "quality_score": 92,
            "quality_tier": "premium",
            "probe_quality": "COMPLETE",
            "quality_resolution": "2160p",
            "quality_video_codec": "hevc",
            "quality_bitrate_kbps": 45000,
            "quality_audio_codec": "truehd",
            "quality_audio_channels": 8,
            "quality_hdr": "HDR10 + DV",
            "quality_subscore_video": 88,
            "quality_subscore_audio": 95,
            "quality_subscore_extras": 90,
            "quality_explanation": "Excellent encodage 4K HDR",
            "warning_flags": "",
            "nfo_present": True,
            "notes": "",
        },
    ]
    return {
        "run_id": "test-run-001",
        "generated_at": "2026-04-03 15:00:00",
        "run": {"root": "D:\\Films", "status": "DONE"},
        "counts": counts if counts is not None else default_counts,
        "rows": rows if rows is not None else default_rows,
    }


class TestHtmlReport(unittest.TestCase):
    """Tests pour export_html_report."""

    def test_contains_html_structure(self):
        html = export_html_report(_make_report())
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("</html>", html)
        self.assertIn("CineSort", html)

    def test_contains_run_id(self):
        html = export_html_report(_make_report())
        self.assertIn("test-run-001", html)

    def test_contains_stats_cards(self):
        html = export_html_report(_make_report())
        self.assertIn("Films analysés", html)
        self.assertIn("Validés OK", html)

    def test_contains_svg_chart(self):
        html = export_html_report(_make_report())
        self.assertIn("<svg", html)
        # U1 audit : tiers renommes Platinum/Gold/Silver/Bronze/Reject.
        self.assertIn("Platinum", html)
        self.assertIn("Gold", html)

    def test_contains_table(self):
        html = export_html_report(_make_report())
        self.assertIn("Avatar", html)
        self.assertIn("2009", html)
        self.assertIn("<table", html)

    def test_empty_rows(self):
        report = _make_report(
            rows=[], counts={"rows_total": 0, "validated_ok": 0, "quality_reports": 0, "quality_tiers": {}}
        )
        html = export_html_report(report)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Détail des films (0)", html)

    def test_html_escapes_title(self):
        rows = _make_report()["rows"]
        rows[0]["proposed_title"] = '<script>alert("xss")</script>'
        html = export_html_report(_make_report(rows=rows))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class TestBuildNfoXml(unittest.TestCase):
    """Tests pour _build_nfo_xml."""

    def test_basic_nfo(self):
        xml = _build_nfo_xml("Avatar", 2009)
        self.assertIn("<title>Avatar</title>", xml)
        self.assertIn("<year>2009</year>", xml)
        self.assertIn('<?xml version="1.0"', xml)

    def test_with_tmdb_id(self):
        xml = _build_nfo_xml("Avatar", 2009, tmdb_id="19995")
        self.assertIn('type="tmdb"', xml)
        self.assertIn("19995", xml)

    def test_with_imdb_id(self):
        xml = _build_nfo_xml("Avatar", 2009, imdb_id="tt0499549")
        self.assertIn('type="imdb"', xml)
        self.assertIn("tt0499549", xml)

    def test_original_title(self):
        xml = _build_nfo_xml("Mon Voisin Totoro", 1988, original_title="Tonari no Totoro")
        self.assertIn("<originaltitle>Tonari no Totoro</originaltitle>", xml)

    def test_no_original_title_when_same(self):
        xml = _build_nfo_xml("Avatar", 2009, original_title="Avatar")
        self.assertNotIn("<originaltitle>", xml)

    def test_no_year_zero(self):
        xml = _build_nfo_xml("Test", 0)
        self.assertNotIn("<year>", xml)


class TestExportNfoForRun(unittest.TestCase):
    """Tests pour export_nfo_for_run."""

    def test_dry_run_no_file_written(self):
        rows = [{"folder": "D:\\Films\\Test", "video": "test.mkv", "proposed_title": "Test", "proposed_year": 2020}]
        result = export_nfo_for_run(rows, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["written"], 1)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["details"][0]["status"], "would_write")

    def test_skip_no_data(self):
        rows = [{"folder": "", "video": "", "proposed_title": "", "proposed_year": 0}]
        result = export_nfo_for_run(rows, dry_run=True)
        self.assertEqual(result["skipped_no_data"], 1)
        self.assertEqual(result["written"], 0)

    def test_skip_existing_nfo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            video = Path(tmpdir) / "film.mkv"
            nfo = Path(tmpdir) / "film.nfo"
            video.touch()
            nfo.write_text("<movie></movie>", encoding="utf-8")
            rows = [{"folder": tmpdir, "video": "film.mkv", "proposed_title": "Film", "proposed_year": 2020}]
            result = export_nfo_for_run(rows, overwrite=False, dry_run=False)
            self.assertEqual(result["skipped_existing"], 1)
            self.assertEqual(result["written"], 0)

    def test_write_nfo_real(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"folder": tmpdir, "video": "film.mkv", "proposed_title": "Mon Film", "proposed_year": 2024}]
            result = export_nfo_for_run(rows, overwrite=False, dry_run=False)
            self.assertEqual(result["written"], 1)
            nfo_path = Path(tmpdir) / "film.nfo"
            self.assertTrue(nfo_path.exists())
            content = nfo_path.read_text(encoding="utf-8")
            self.assertIn("<title>Mon Film</title>", content)
            self.assertIn("<year>2024</year>", content)

    def test_overwrite_existing_nfo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nfo = Path(tmpdir) / "film.nfo"
            nfo.write_text("<movie><title>Old</title></movie>", encoding="utf-8")
            rows = [{"folder": tmpdir, "video": "film.mkv", "proposed_title": "New", "proposed_year": 2024}]
            result = export_nfo_for_run(rows, overwrite=True, dry_run=False)
            self.assertEqual(result["written"], 1)
            content = nfo.read_text(encoding="utf-8")
            self.assertIn("<title>New</title>", content)


class TestCsvEnrichedPayload(unittest.TestCase):
    """Tests pour le CSV enrichi via dashboard_support."""

    def test_csv_has_enriched_columns(self):
        from cinesort.ui.api.dashboard_support import report_to_csv_text

        report = _make_report()
        csv_text = report_to_csv_text(report)
        # Vérifier les en-têtes enrichis
        header = csv_text.split("\n")[0]
        self.assertIn("confidence;", header)
        self.assertIn("quality_resolution", header)
        self.assertIn("quality_video_codec", header)
        self.assertIn("quality_bitrate_kbps", header)
        self.assertIn("quality_audio_codec", header)
        self.assertIn("quality_hdr", header)
        self.assertIn("warning_flags", header)
        self.assertIn("nfo_present", header)

    def test_csv_row_data(self):
        from cinesort.ui.api.dashboard_support import report_to_csv_text

        report = _make_report()
        csv_text = report_to_csv_text(report)
        lines = csv_text.strip().split("\n")
        self.assertEqual(len(lines), 2)  # header + 1 data row
        self.assertIn("Avatar", lines[1])
        self.assertIn("2160p", lines[1])
        self.assertIn("hevc", lines[1])


class TestHdrLabel(unittest.TestCase):
    """Tests pour _hdr_label dans dashboard_support."""

    def test_sdr(self):
        from cinesort.ui.api.dashboard_support import _hdr_label

        self.assertEqual(_hdr_label({}), "SDR")

    def test_hdr10(self):
        from cinesort.ui.api.dashboard_support import _hdr_label

        self.assertEqual(_hdr_label({"hdr10": True}), "HDR10")

    def test_dolby_vision(self):
        from cinesort.ui.api.dashboard_support import _hdr_label

        self.assertEqual(_hdr_label({"hdr_dolby_vision": True}), "DV")

    def test_dv_plus_hdr10(self):
        from cinesort.ui.api.dashboard_support import _hdr_label

        self.assertEqual(_hdr_label({"hdr_dolby_vision": True, "hdr10": True}), "DV + HDR10")


if __name__ == "__main__":
    unittest.main()
