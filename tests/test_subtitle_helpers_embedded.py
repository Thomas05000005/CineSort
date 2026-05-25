"""Tests pour la detection des sous-titres EMBARQUES (Vague F Fix 5).

Couvre l'extension de `build_subtitle_report` avec le parametre optionnel
`embedded_subtitles` : les pistes du probe ffprobe/mediainfo doivent etre
prises en compte pour calculer `missing_languages`.

Fix audit 2026-05-25 (v1.5.3) : 853 films flagges a tort en
"subtitle_missing_fr" parce que la detection ignorait les pistes embarquees.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cinesort.domain.subtitle_helpers import build_subtitle_report


class TestBuildSubtitleReportEmbedded(unittest.TestCase):
    """Tests pour build_subtitle_report avec embedded_subtitles."""

    def test_external_only_still_works(self):
        """Backward compat : sans embedded_subtitles, comportement inchange."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            video = folder / "Inception.mkv"
            video.touch()
            (folder / "Inception.fr.srt").touch()

            # Aucune mention d'embedded → default None
            report = build_subtitle_report(folder, video, ["fr", "en"])
            self.assertEqual(report.languages, ["fr"])
            self.assertEqual(report.missing_languages, ["en"])
            self.assertEqual(report.count, 1)

    def test_embedded_only_fr_detected(self):
        """Une piste FR embarquee suffit a satisfaire expected=['fr']."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            video = folder / "Movie.mkv"
            video.touch()

            embedded = [{"index": 2, "language": "fra", "forced": False}]
            report = build_subtitle_report(
                folder,
                video,
                ["fr"],
                embedded_subtitles=embedded,
            )
            # Pas de sous-titre externe matche, mais FR embarque
            self.assertEqual(report.count, 0)  # count = externes uniquement
            self.assertIn("fr", report.languages)
            self.assertEqual(report.missing_languages, [])  # FIX Vague F

    def test_embedded_iso_variants(self):
        """Les variantes `fra` / `fre` / `fr` se normalisent toutes vers `fr`."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            video = folder / "Movie.mkv"
            video.touch()

            for tag in ("fra", "fre", "fr", "French", "FRENCH"):
                embedded = [{"index": 0, "language": tag, "forced": False}]
                report = build_subtitle_report(
                    folder,
                    video,
                    ["fr"],
                    embedded_subtitles=embedded,
                )
                self.assertIn(
                    "fr",
                    report.languages,
                    f"Tag '{tag}' devrait se normaliser en 'fr'",
                )
                self.assertEqual(report.missing_languages, [])

    def test_both_sources_merge(self):
        """Externes (.srt FR) + embarques (EN) -> union [en, fr]."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            video = folder / "Movie.mkv"
            video.touch()
            (folder / "Movie.fr.srt").touch()

            embedded = [
                {"index": 2, "language": "eng", "forced": False},
                {"index": 3, "language": "und", "forced": False},  # ignore
            ]
            report = build_subtitle_report(
                folder,
                video,
                ["fr", "en"],
                embedded_subtitles=embedded,
            )
            self.assertEqual(report.languages, ["en", "fr"])
            self.assertEqual(report.missing_languages, [])
            # count reste sur les externes uniquement
            self.assertEqual(report.count, 1)

    def test_embedded_empty_language_ignored(self):
        """Une piste embarquee sans tag de langue ne doit RIEN ajouter."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            video = folder / "Movie.mkv"
            video.touch()

            embedded = [
                {"index": 0, "language": None, "forced": False},
                {"index": 1, "language": "", "forced": False},
                {"index": 2, "language": "   ", "forced": False},
                # Pas de cle "language" du tout :
                {"index": 3, "forced": False},
            ]
            report = build_subtitle_report(
                folder,
                video,
                ["fr"],
                embedded_subtitles=embedded,
            )
            self.assertEqual(report.languages, [])
            self.assertEqual(report.missing_languages, ["fr"])

    def test_embedded_none_default_backward_compat(self):
        """Appel sans kwarg : strictement equivalent a l'ancien comportement."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            video = folder / "Movie.mkv"
            video.touch()

            report_old = build_subtitle_report(folder, video, ["fr"])
            report_new = build_subtitle_report(
                folder, video, ["fr"], embedded_subtitles=None
            )
            self.assertEqual(report_old.languages, report_new.languages)
            self.assertEqual(
                report_old.missing_languages, report_new.missing_languages
            )
            self.assertEqual(report_old.count, report_new.count)

    def test_embedded_non_dict_items_skipped(self):
        """Items malformes (non-dict) dans la liste ne crashent pas."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            video = folder / "Movie.mkv"
            video.touch()

            embedded = [
                "garbage",  # type: ignore[list-item]
                None,
                {"index": 0, "language": "fra", "forced": False},
            ]
            report = build_subtitle_report(
                folder,
                video,
                ["fr"],
                embedded_subtitles=embedded,  # type: ignore[arg-type]
            )
            self.assertIn("fr", report.languages)


if __name__ == "__main__":
    unittest.main()
