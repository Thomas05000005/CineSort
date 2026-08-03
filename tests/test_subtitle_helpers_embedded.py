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
            report_new = build_subtitle_report(folder, video, ["fr"], embedded_subtitles=None)
            self.assertEqual(report_old.languages, report_new.languages)
            self.assertEqual(report_old.missing_languages, report_new.missing_languages)
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

    # Fix audit 2026-05-26 (v1.5.6) Vague L (subs-2 mutation testing) : les tests
    # ci-dessus ne distinguaient pas les langues -> une mutation de
    # _normalize_iso639 renvoyant 'fr' constant les laissait TOUS verts. Les cas
    # suivants verifient des langues DISTINCTES : ils CASSENT si la normalisation
    # collapse tout vers 'fr'.

    def test_embedded_german_is_not_french(self):
        """Un sous-titre 'ger' embarque ne doit PAS satisfaire expected=['fr'].

        CASSE si _normalize_iso639 retourne 'fr' constant : 'de' apparaitrait
        comme 'fr' et missing_languages serait vide a tort.
        """
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            video = folder / "Movie.mkv"
            video.touch()

            embedded = [{"index": 0, "language": "ger", "forced": False}]
            report = build_subtitle_report(folder, video, ["fr"], embedded_subtitles=embedded)
            self.assertEqual(report.languages, ["de"], "'ger' doit normaliser vers 'de', pas 'fr'")
            self.assertEqual(
                report.missing_languages,
                ["fr"],
                "FR doit etre flag manquant : seul un sous-titre allemand est present",
            )
            self.assertNotIn("fr", report.languages)

    def test_distinct_languages_preserved(self):
        """eng + ger + spa restent distincts (aucun collapse vers 'fr')."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            video = folder / "Movie.mkv"
            video.touch()

            embedded = [
                {"index": 0, "language": "eng", "forced": False},
                {"index": 1, "language": "ger", "forced": False},
                {"index": 2, "language": "spa", "forced": False},
            ]
            report = build_subtitle_report(folder, video, ["fr"], embedded_subtitles=embedded)
            self.assertEqual(report.languages, ["de", "en", "es"])
            self.assertEqual(report.missing_languages, ["fr"])

    # Fix audit 2026-05-26 (v1.5.6) Vague L (subs-3) : normalisation SYMETRIQUE
    # des langues ATTENDUES. Avant le fix, expected_languages n'etait pas passe
    # par _LANG_MAP : 'french'/'fra'/'fre'/'francais' ne matchaient jamais 'fr'.

    def test_expected_language_iso639_2_normalized(self):
        """expected=['fra'] (ISO 639-2) doit matcher un FR present (externe)."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            video = folder / "Movie.mkv"
            video.touch()
            (folder / "Movie.fr.srt").touch()

            report = build_subtitle_report(folder, video, ["fra"])
            self.assertIn("fr", report.languages)
            self.assertEqual(
                report.missing_languages,
                [],
                "expected 'fra' doit normaliser vers 'fr' et matcher le sous-titre FR",
            )

    def test_expected_language_common_name_normalized(self):
        """expected=['french'] / ['French'] doit matcher un FR embarque."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            video = folder / "Movie.mkv"
            video.touch()

            embedded = [{"index": 0, "language": "fre", "forced": False}]
            for exp in ("french", "French", "FRENCH", "fre"):
                report = build_subtitle_report(folder, video, [exp], embedded_subtitles=embedded)
                self.assertEqual(
                    report.missing_languages,
                    [],
                    f"expected '{exp}' doit normaliser vers 'fr' et ne pas etre manquant",
                )

    def test_expected_language_normalized_still_flags_real_miss(self):
        """expected=['fra'] reste flag manquant si SEUL l'anglais est present.

        Garde-fou : la normalisation symetrique ne doit pas tout faire matcher.
        """
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            video = folder / "Movie.mkv"
            video.touch()

            embedded = [{"index": 0, "language": "eng", "forced": False}]
            report = build_subtitle_report(folder, video, ["fra"], embedded_subtitles=embedded)
            self.assertEqual(report.languages, ["en"])
            self.assertEqual(report.missing_languages, ["fr"])


if __name__ == "__main__":
    unittest.main()
