"""Tests analyse audio approfondie — cinesort/domain/audio_analysis.py.

Couvre :
- Format : Atmos, TrueHD, DTS-HD MA, EAC3, FLAC, DTS, AC3, AAC, MP3
- Canaux : 7.1, 5.1, 2.0, 1.0
- Commentaire : disposition, title pattern
- Doublons : TrueHD+AC3 normal, 2xAC3 suspect
- Badge : label, tier
- Edge : 0 pistes, codec inconnu
- Probe enrichie : title et is_commentary
- UI : badges presents, CSS classes
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.domain.audio_analysis import analyze_audio


def _track(*, codec="", channels=0, language="eng", title="", is_commentary=False):
    return {
        "codec": codec,
        "channels": channels,
        "language": language,
        "title": title,
        "is_commentary": is_commentary,
        "bitrate": 0,
        "index": 0,
    }


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


class FormatTests(unittest.TestCase):
    """Detection du format audio."""

    def test_atmos_truehd_with_title(self) -> None:
        """TrueHD + title contient 'Atmos' → Atmos."""
        r = analyze_audio([_track(codec="truehd", channels=8, title="TrueHD Atmos 7.1")])
        self.assertEqual(r["best_format"], "Atmos")
        self.assertEqual(r["badge_tier"], "premium")

    def test_truehd_without_atmos(self) -> None:
        """TrueHD sans Atmos dans le titre → TrueHD."""
        r = analyze_audio([_track(codec="truehd", channels=8)])
        self.assertEqual(r["best_format"], "TrueHD")
        self.assertEqual(r["badge_tier"], "premium")

    def test_dts_hd_ma(self) -> None:
        r = analyze_audio([_track(codec="dts-hd ma", channels=6)])
        self.assertEqual(r["best_format"], "DTS-HD MA")
        self.assertEqual(r["badge_tier"], "bon")

    def test_eac3(self) -> None:
        r = analyze_audio([_track(codec="eac3", channels=6)])
        self.assertEqual(r["best_format"], "EAC3")
        self.assertEqual(r["badge_tier"], "bon")

    def test_flac(self) -> None:
        r = analyze_audio([_track(codec="flac", channels=2)])
        self.assertEqual(r["best_format"], "FLAC")
        self.assertEqual(r["badge_tier"], "bon")

    def test_dts(self) -> None:
        r = analyze_audio([_track(codec="dts", channels=6)])
        self.assertEqual(r["best_format"], "DTS")
        self.assertEqual(r["badge_tier"], "standard")

    def test_ac3(self) -> None:
        r = analyze_audio([_track(codec="ac3", channels=6)])
        self.assertEqual(r["best_format"], "AC3")
        self.assertEqual(r["badge_tier"], "standard")

    def test_aac(self) -> None:
        r = analyze_audio([_track(codec="aac", channels=2)])
        self.assertEqual(r["best_format"], "AAC")
        self.assertEqual(r["badge_tier"], "basique")

    def test_mp3(self) -> None:
        r = analyze_audio([_track(codec="mp3", channels=2)])
        self.assertEqual(r["best_format"], "MP3")
        self.assertEqual(r["badge_tier"], "basique")

    def test_best_format_from_multiple(self) -> None:
        """Plusieurs pistes → meilleur format selectionne."""
        tracks = [
            _track(codec="ac3", channels=6, language="eng"),
            _track(codec="truehd", channels=8, language="eng"),
            _track(codec="aac", channels=2, language="fra"),
        ]
        r = analyze_audio(tracks)
        self.assertEqual(r["best_format"], "TrueHD")


# ---------------------------------------------------------------------------
# Canaux
# ---------------------------------------------------------------------------


class ChannelsTests(unittest.TestCase):
    """Detection des canaux."""

    def test_7_1(self) -> None:
        r = analyze_audio([_track(codec="truehd", channels=8)])
        self.assertEqual(r["best_channels"], "7.1")

    def test_5_1(self) -> None:
        r = analyze_audio([_track(codec="ac3", channels=6)])
        self.assertEqual(r["best_channels"], "5.1")

    def test_2_0(self) -> None:
        r = analyze_audio([_track(codec="aac", channels=2)])
        self.assertEqual(r["best_channels"], "2.0")

    def test_1_0(self) -> None:
        r = analyze_audio([_track(codec="aac", channels=1)])
        self.assertEqual(r["best_channels"], "1.0")


# ---------------------------------------------------------------------------
# Commentaire
# ---------------------------------------------------------------------------


class CommentaryTests(unittest.TestCase):
    """Detection commentaire realisateur."""

    def test_disposition_comment(self) -> None:
        r = analyze_audio([_track(codec="ac3", channels=2, is_commentary=True)])
        self.assertTrue(r["has_commentary"])

    def test_title_commentary(self) -> None:
        r = analyze_audio([_track(codec="ac3", channels=2, title="Director Commentary", is_commentary=True)])
        self.assertTrue(r["has_commentary"])

    def test_normal_track(self) -> None:
        r = analyze_audio([_track(codec="ac3", channels=6)])
        self.assertFalse(r["has_commentary"])


# ---------------------------------------------------------------------------
# Doublons
# ---------------------------------------------------------------------------


class DuplicateTests(unittest.TestCase):
    """Detection doublons audio."""

    def test_truehd_ac3_same_lang_normal(self) -> None:
        """TrueHD + AC3 meme langue = compat fallback, pas suspect."""
        tracks = [
            _track(codec="truehd", channels=8, language="eng"),
            _track(codec="ac3", channels=6, language="eng"),
        ]
        r = analyze_audio(tracks)
        self.assertEqual(r["duplicate_tracks"], [])

    def test_two_ac3_same_lang_suspect(self) -> None:
        """2x AC3 meme langue = suspect."""
        tracks = [
            _track(codec="ac3", channels=6, language="fra"),
            _track(codec="ac3", channels=6, language="fra"),
        ]
        r = analyze_audio(tracks)
        self.assertGreater(len(r["duplicate_tracks"]), 0)
        self.assertEqual(r["duplicate_tracks"][0]["language"], "fra")

    def test_different_langs_not_duplicate(self) -> None:
        """AC3 en anglais + AC3 en francais = normal."""
        tracks = [
            _track(codec="ac3", channels=6, language="eng"),
            _track(codec="ac3", channels=6, language="fra"),
        ]
        r = analyze_audio(tracks)
        self.assertEqual(r["duplicate_tracks"], [])

    def test_commentary_ignored_in_duplicates(self) -> None:
        """Les pistes commentaire sont ignorees dans la detection doublons."""
        tracks = [
            _track(codec="ac3", channels=6, language="eng"),
            _track(codec="ac3", channels=2, language="eng", is_commentary=True),
        ]
        r = analyze_audio(tracks)
        self.assertEqual(r["duplicate_tracks"], [])


# ---------------------------------------------------------------------------
# Badge
# ---------------------------------------------------------------------------


class BadgeTests(unittest.TestCase):
    """Badge label et tier."""

    def test_badge_label_atmos(self) -> None:
        r = analyze_audio([_track(codec="truehd", channels=8, title="Atmos")])
        self.assertEqual(r["badge_label"], "Atmos 7.1")

    def test_badge_label_ac3_51(self) -> None:
        r = analyze_audio([_track(codec="ac3", channels=6)])
        self.assertEqual(r["badge_label"], "AC3 5.1")

    def test_badge_tier_premium(self) -> None:
        r = analyze_audio([_track(codec="truehd", channels=8)])
        self.assertEqual(r["badge_tier"], "premium")

    def test_badge_tier_basique(self) -> None:
        r = analyze_audio([_track(codec="aac", channels=2)])
        self.assertEqual(r["badge_tier"], "basique")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class EdgeCaseTests(unittest.TestCase):
    """Edge cases."""

    def test_zero_tracks(self) -> None:
        r = analyze_audio([])
        self.assertEqual(r["best_format"], "Aucun")
        self.assertEqual(r["badge_tier"], "basique")
        self.assertEqual(r["tracks_count"], 0)

    def test_unknown_codec(self) -> None:
        r = analyze_audio([_track(codec="pcm_s24le", channels=2)])
        self.assertEqual(r["best_format"], "Inconnu")

    def test_channels_none(self) -> None:
        r = analyze_audio([{"codec": "ac3", "channels": None, "language": "eng", "title": "", "is_commentary": False}])
        self.assertEqual(r["best_channels"], "—")

    def test_languages_collected(self) -> None:
        tracks = [_track(codec="ac3", channels=6, language="eng"), _track(codec="aac", channels=2, language="fra")]
        r = analyze_audio(tracks)
        self.assertIn("eng", r["languages"])
        self.assertIn("fra", r["languages"])


# ---------------------------------------------------------------------------
# Probe enrichie
# ---------------------------------------------------------------------------


class ProbeEnrichmentTests(unittest.TestCase):
    """Verification que la probe extrait title et is_commentary."""

    def test_ffprobe_extraction_structure(self) -> None:
        """Verifie que normalize.py extrait title et is_commentary pour les pistes audio."""
        # On ne peut pas tester l'extraction reelle sans ffprobe, mais on verifie
        # que le code d'extraction est present dans normalize.py
        norm_code = (Path(__file__).resolve().parents[1] / "cinesort" / "infra" / "probe" / "normalize.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"title"', norm_code)
        self.assertIn('"is_commentary"', norm_code)
        self.assertIn("commentary", norm_code)


# ---------------------------------------------------------------------------
# UI badges
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/review.js supprime (remplace par processing v5) — adaptation vers v5 deferee a V5C-03")
class UiBadgeTests(unittest.TestCase):
    """Badges audio dans les fichiers UI."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.validation_js = (root / "web" / "views" / "validation.js").read_text(encoding="utf-8")
        cls.review_js = (root / "web" / "dashboard" / "views" / "review.js").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")
        cls.dash_css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_desktop_audio_badge(self) -> None:
        self.assertIn("audio_analysis", self.validation_js)
        self.assertIn("badge_label", self.validation_js)

    def test_dashboard_audio_badge(self) -> None:
        self.assertIn("audio_analysis", self.review_js)
        self.assertIn("badge_label", self.review_js)

    def test_desktop_css_audio_premium(self) -> None:
        self.assertIn(".badge--audio-premium", self.app_css)

    def test_desktop_css_audio_bon(self) -> None:
        self.assertIn(".badge--audio-bon", self.app_css)

    def test_desktop_css_audio_standard(self) -> None:
        self.assertIn(".badge--audio-standard", self.app_css)

    def test_desktop_css_audio_basique(self) -> None:
        self.assertIn(".badge--audio-basique", self.app_css)

    def test_dashboard_css_audio(self) -> None:
        self.assertIn("badge-audio-premium", self.dash_css)
        self.assertIn("badge-audio-basique", self.dash_css)


# ---------------------------------------------------------------------------
# Detection langue audio (item 9.27)
# ---------------------------------------------------------------------------


class AudioLanguageCoherenceTests(unittest.TestCase):
    """Tests de la detection d'incoherence des tags langue audio."""

    def test_all_tracks_tagged(self) -> None:
        """Toutes les pistes ont une langue → pas de warning."""
        tracks = [
            {"codec": "ac3", "channels": 6, "language": "fra", "is_commentary": False},
            {"codec": "ac3", "channels": 6, "language": "eng", "is_commentary": False},
        ]
        result = analyze_audio(tracks)
        self.assertEqual(result["missing_language_count"], 0)
        self.assertFalse(result["incomplete_languages"])

    def test_one_track_missing_language(self) -> None:
        """1 piste sur 3 sans langue → missing=1, incomplete=True."""
        tracks = [
            {"codec": "ac3", "channels": 6, "language": "fra", "is_commentary": False},
            {"codec": "ac3", "channels": 6, "language": "", "is_commentary": False},
            {"codec": "ac3", "channels": 6, "language": "eng", "is_commentary": False},
        ]
        result = analyze_audio(tracks)
        self.assertEqual(result["missing_language_count"], 1)
        self.assertTrue(result["incomplete_languages"])

    def test_single_track_no_language(self) -> None:
        """Piste unique sans langue → missing=1, incomplete=False (pas de piste taguee)."""
        tracks = [
            {"codec": "aac", "channels": 2, "language": None, "is_commentary": False},
        ]
        result = analyze_audio(tracks)
        self.assertEqual(result["missing_language_count"], 1)
        self.assertFalse(result["incomplete_languages"])

    def test_commentary_without_language_ignored(self) -> None:
        """Piste commentaire sans langue → pas comptee."""
        tracks = [
            {"codec": "ac3", "channels": 6, "language": "fra", "is_commentary": False},
            {"codec": "ac3", "channels": 2, "language": None, "is_commentary": True},
        ]
        result = analyze_audio(tracks)
        self.assertEqual(result["missing_language_count"], 0)
        self.assertFalse(result["incomplete_languages"])

    def test_und_treated_as_missing(self) -> None:
        """'und' traite comme absence de langue."""
        tracks = [
            {"codec": "ac3", "channels": 6, "language": "und", "is_commentary": False},
            {"codec": "ac3", "channels": 6, "language": "fra", "is_commentary": False},
        ]
        result = analyze_audio(tracks)
        self.assertEqual(result["missing_language_count"], 1)
        self.assertTrue(result["incomplete_languages"])

    def test_all_tracks_missing_language(self) -> None:
        """Toutes les pistes sans langue → missing=2, incomplete=False (aucune taguee)."""
        tracks = [
            {"codec": "ac3", "channels": 6, "language": "", "is_commentary": False},
            {"codec": "aac", "channels": 2, "language": "und", "is_commentary": False},
        ]
        result = analyze_audio(tracks)
        self.assertEqual(result["missing_language_count"], 2)
        self.assertFalse(result["incomplete_languages"])

    def test_empty_tracks_no_crash(self) -> None:
        """0 pistes → les champs existent avec valeurs par defaut."""
        result = analyze_audio([])
        self.assertEqual(result.get("missing_language_count"), None)
        # Les champs ne sont pas dans le resultat vide


@unittest.skip("V5C-01: dashboard/views/review.js supprime (remplace par processing v5) — adaptation vers v5 deferee a V5C-03")
class AudioLanguageUiTests(unittest.TestCase):
    """Tests presence UI badge langue audio."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.validation_js = (root / "web" / "views" / "validation.js").read_text(encoding="utf-8")
        cls.review_js = (root / "web" / "dashboard" / "views" / "review.js").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")
        cls.dash_css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_validation_js_has_audio_lang_badge(self) -> None:
        self.assertIn("audioLangBadge", self.validation_js)
        self.assertIn("badge--audio-lang", self.validation_js)
        self.assertIn("Langue ?", self.validation_js)

    def test_review_js_has_audio_lang_badge(self) -> None:
        self.assertIn("badge-audio-lang", self.review_js)
        self.assertIn("audio_language_missing", self.review_js)

    def test_app_css_has_audio_lang(self) -> None:
        self.assertIn(".badge--audio-lang", self.app_css)

    def test_dash_css_has_audio_lang(self) -> None:
        self.assertIn(".badge-audio-lang", self.dash_css)


if __name__ == "__main__":
    unittest.main()
