"""Tests unitaires pour cinesort/domain/subtitle_helpers.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cinesort.domain.subtitle_helpers import (
    SubtitleInfo,
    SubtitleReport,
    build_subtitle_report,
    detect_language_from_suffix,
    find_subtitles_in_folder,
    match_subtitles_to_video,
)


# ── detect_language_from_suffix ──────────────────────────────────────


class TestDetectLanguageFromSuffix(unittest.TestCase):
    """Tests pour detect_language_from_suffix."""

    def test_iso_639_1(self):
        self.assertEqual(detect_language_from_suffix("Movie.fr.srt"), "fr")
        self.assertEqual(detect_language_from_suffix("Movie.en.srt"), "en")
        self.assertEqual(detect_language_from_suffix("Movie.es.srt"), "es")
        self.assertEqual(detect_language_from_suffix("Movie.de.ass"), "de")

    def test_iso_639_2(self):
        self.assertEqual(detect_language_from_suffix("Movie.eng.srt"), "en")
        self.assertEqual(detect_language_from_suffix("Movie.fre.srt"), "fr")
        self.assertEqual(detect_language_from_suffix("Movie.fra.srt"), "fr")
        self.assertEqual(detect_language_from_suffix("Movie.spa.srt"), "es")
        self.assertEqual(detect_language_from_suffix("Movie.ger.srt"), "de")
        self.assertEqual(detect_language_from_suffix("Movie.deu.sub"), "de")

    def test_full_names(self):
        self.assertEqual(detect_language_from_suffix("Movie.french.srt"), "fr")
        self.assertEqual(detect_language_from_suffix("Movie.english.srt"), "en")
        self.assertEqual(detect_language_from_suffix("Movie.spanish.ass"), "es")
        self.assertEqual(detect_language_from_suffix("Movie.german.srt"), "de")

    def test_special_tags(self):
        self.assertEqual(detect_language_from_suffix("Movie.vostfr.srt"), "fr")
        self.assertEqual(detect_language_from_suffix("Movie.vf.srt"), "fr")
        self.assertEqual(detect_language_from_suffix("Movie.vo.srt"), "en")

    def test_non_language_tags(self):
        self.assertEqual(detect_language_from_suffix("Movie.forced.srt"), "")
        self.assertEqual(detect_language_from_suffix("Movie.sdh.srt"), "")
        self.assertEqual(detect_language_from_suffix("Movie.hi.srt"), "")
        self.assertEqual(detect_language_from_suffix("Movie.cc.srt"), "")

    def test_no_suffix(self):
        self.assertEqual(detect_language_from_suffix("Movie.srt"), "")

    def test_unknown_tag(self):
        self.assertEqual(detect_language_from_suffix("Movie.xyz123.srt"), "")

    def test_case_insensitive(self):
        self.assertEqual(detect_language_from_suffix("Movie.FR.srt"), "fr")
        self.assertEqual(detect_language_from_suffix("Movie.ENG.srt"), "en")
        self.assertEqual(detect_language_from_suffix("Movie.French.srt"), "fr")


# ── find_subtitles_in_folder ─────────────────────────────────────────


class TestFindSubtitlesInFolder(unittest.TestCase):
    """Tests pour find_subtitles_in_folder."""

    def test_finds_subtitle_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "Movie.fr.srt").write_text("sub content")
            (folder / "Movie.en.srt").write_text("sub content")
            (folder / "Movie.mkv").write_bytes(b"\x00" * 100)
            (folder / "readme.txt").write_text("notes")

            subs = find_subtitles_in_folder(folder)
            self.assertEqual(len(subs), 2)
            exts = {s.ext for s in subs}
            self.assertEqual(exts, {".srt"})

    def test_multiple_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "Movie.srt").write_text("sub")
            (folder / "Movie.ass").write_text("sub")
            (folder / "Movie.sub").write_text("sub")
            (folder / "Movie.idx").write_text("sub")
            (folder / "Movie.sup").write_bytes(b"\x00")

            subs = find_subtitles_in_folder(folder)
            self.assertEqual(len(subs), 5)
            formats = {s.ext for s in subs}
            self.assertEqual(formats, {".srt", ".ass", ".sub", ".idx", ".sup"})

    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            subs = find_subtitles_in_folder(Path(tmp))
            self.assertEqual(subs, [])

    def test_no_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "Movie.mkv").write_bytes(b"\x00")
            (folder / "Movie.nfo").write_text("nfo")

            subs = find_subtitles_in_folder(folder)
            self.assertEqual(subs, [])

    def test_nonexistent_folder(self):
        subs = find_subtitles_in_folder(Path("/nonexistent/folder"))
        self.assertEqual(subs, [])

    def test_sorted_by_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "z_movie.srt").write_text("")
            (folder / "a_movie.srt").write_text("")
            (folder / "m_movie.srt").write_text("")

            subs = find_subtitles_in_folder(folder)
            names = [s.filename for s in subs]
            self.assertEqual(names, ["a_movie.srt", "m_movie.srt", "z_movie.srt"])

    def test_language_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "Movie.fr.srt").write_text("")
            (folder / "Movie.srt").write_text("")

            subs = find_subtitles_in_folder(folder)
            by_name = {s.filename: s for s in subs}
            self.assertEqual(by_name["Movie.fr.srt"].language, "fr")
            self.assertEqual(by_name["Movie.fr.srt"].language_source, "suffix")
            self.assertEqual(by_name["Movie.srt"].language, "")
            self.assertEqual(by_name["Movie.srt"].language_source, "unknown")


# ── match_subtitles_to_video ─────────────────────────────────────────


class TestMatchSubtitlesToVideo(unittest.TestCase):
    """Tests pour match_subtitles_to_video."""

    def _make_sub(self, filename, lang="", orphan=True):
        return SubtitleInfo(
            filename=filename,
            ext=Path(filename).suffix.lower(),
            language=lang,
            language_source="suffix" if lang else "unknown",
            is_orphan=orphan,
        )

    def test_exact_stem_match(self):
        subs = [self._make_sub("Inception.srt")]
        matched = match_subtitles_to_video(subs, "Inception")
        self.assertEqual(len(matched), 1)
        self.assertFalse(matched[0].is_orphan)

    def test_prefix_match_with_lang(self):
        subs = [
            self._make_sub("Inception.fr.srt", "fr"),
            self._make_sub("Inception.en.srt", "en"),
        ]
        matched = match_subtitles_to_video(subs, "Inception")
        self.assertEqual(len(matched), 2)

    def test_no_match(self):
        subs = [self._make_sub("OtherMovie.fr.srt", "fr")]
        matched = match_subtitles_to_video(subs, "Inception")
        self.assertEqual(len(matched), 0)

    def test_case_insensitive(self):
        subs = [self._make_sub("inception.FR.srt", "fr")]
        matched = match_subtitles_to_video(subs, "Inception")
        self.assertEqual(len(matched), 1)

    def test_empty_video_stem(self):
        subs = [self._make_sub("Movie.srt")]
        matched = match_subtitles_to_video(subs, "")
        self.assertEqual(matched, [])

    def test_partial_stem_no_dot_no_match(self):
        """'Movie' ne doit pas matcher 'MovieExtra.srt'."""
        subs = [self._make_sub("MovieExtra.srt")]
        matched = match_subtitles_to_video(subs, "Movie")
        self.assertEqual(len(matched), 0)


# ── build_subtitle_report ────────────────────────────────────────────


class TestBuildSubtitleReport(unittest.TestCase):
    """Tests pour build_subtitle_report."""

    def test_full_report_with_matching_subs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / "Inception.mkv"
            video.write_bytes(b"\x00" * 100)
            (folder / "Inception.fr.srt").write_text("fr sub")
            (folder / "Inception.en.srt").write_text("en sub")

            report = build_subtitle_report(folder, video, ["fr", "en"])
            self.assertEqual(report.count, 2)
            self.assertEqual(sorted(report.languages), ["en", "fr"])
            self.assertEqual(report.formats, [".srt"])
            self.assertEqual(report.missing_languages, [])
            self.assertEqual(report.orphans, 0)

    def test_missing_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / "Movie.mkv"
            video.write_bytes(b"\x00")
            (folder / "Movie.fr.srt").write_text("")

            report = build_subtitle_report(folder, video, ["fr", "en"])
            self.assertEqual(report.count, 1)
            self.assertEqual(report.languages, ["fr"])
            self.assertEqual(report.missing_languages, ["en"])

    def test_no_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / "Movie.mkv"
            video.write_bytes(b"\x00")

            report = build_subtitle_report(folder, video, ["fr"])
            self.assertEqual(report.count, 0)
            self.assertEqual(report.missing_languages, ["fr"])

    def test_orphan_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / "Movie.mkv"
            video.write_bytes(b"\x00")
            (folder / "Movie.fr.srt").write_text("")
            (folder / "OtherFile.en.srt").write_text("")  # orphelin

            report = build_subtitle_report(folder, video, [])
            self.assertEqual(report.count, 1)
            self.assertEqual(report.orphans, 1)

    def test_duplicate_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / "Movie.mkv"
            video.write_bytes(b"\x00")
            (folder / "Movie.fr.srt").write_text("")
            (folder / "Movie.french.srt").write_text("")  # doublon FR

            report = build_subtitle_report(folder, video, [])
            self.assertEqual(report.count, 2)
            self.assertEqual(report.duplicate_languages, ["fr"])

    def test_no_expected_languages(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / "Movie.mkv"
            video.write_bytes(b"\x00")
            (folder / "Movie.fr.srt").write_text("")

            report = build_subtitle_report(folder, video, None)
            self.assertEqual(report.count, 1)
            self.assertEqual(report.missing_languages, [])

    def test_multiple_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / "Movie.mkv"
            video.write_bytes(b"\x00")
            (folder / "Movie.fr.srt").write_text("")
            (folder / "Movie.fr.ass").write_text("")

            report = build_subtitle_report(folder, video, [])
            self.assertEqual(report.count, 2)
            self.assertEqual(sorted(report.formats), [".ass", ".srt"])

    def test_subtitle_without_lang_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            video = folder / "Movie.mkv"
            video.write_bytes(b"\x00")
            (folder / "Movie.srt").write_text("")

            report = build_subtitle_report(folder, video, ["fr"])
            self.assertEqual(report.count, 1)
            self.assertEqual(report.languages, [])
            self.assertEqual(report.missing_languages, ["fr"])


# ── SubtitleInfo / SubtitleReport ────────────────────────────────────


class TestDataclasses(unittest.TestCase):
    """Tests pour les dataclasses."""

    def test_subtitle_info_frozen(self):
        si = SubtitleInfo("a.srt", ".srt", "fr", "suffix", False)
        with self.assertRaises(AttributeError):
            si.language = "en"  # type: ignore[misc]

    def test_subtitle_report_frozen(self):
        sr = SubtitleReport(0, [], [], 0, [], [], [])
        with self.assertRaises(AttributeError):
            sr.count = 5  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
