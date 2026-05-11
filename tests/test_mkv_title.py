"""Tests conflit titre conteneur MKV/MP4 — item 9.23.

Couvre :
- check_container_title : null, vide, identique, scene, different
- _is_scene_title : detection patterns scene
- Extraction ffprobe/mediainfo container_title
- NormalizedProbe.container_title
- UI : badges presents, CSS classes
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.domain.mkv_title_check import check_container_title, _is_scene_title
from cinesort.domain.probe_models import NormalizedProbe
from cinesort.infra.probe.normalize import _extract_ffprobe, _extract_mediainfo


# ---------------------------------------------------------------------------
# check_container_title
# ---------------------------------------------------------------------------


class CheckContainerTitleTests(unittest.TestCase):
    """Tests de la detection de conflit titre conteneur."""

    def test_null_container_title(self) -> None:
        """container_title None → pas de warning."""
        self.assertEqual(check_container_title(None, "Inception"), [])

    def test_empty_container_title(self) -> None:
        """container_title vide → pas de warning."""
        self.assertEqual(check_container_title("", "Inception"), [])
        self.assertEqual(check_container_title("  ", "Inception"), [])

    def test_identical_title(self) -> None:
        """container_title == proposed_title → pas de warning."""
        self.assertEqual(check_container_title("Inception", "Inception"), [])

    def test_identical_case_insensitive(self) -> None:
        """container_title identique case-insensitive → pas de warning."""
        self.assertEqual(check_container_title("inception", "Inception"), [])
        self.assertEqual(check_container_title("INCEPTION", "Inception"), [])

    def test_scene_title_mismatch(self) -> None:
        """Titre scene → warning mkv_title_mismatch."""
        flags = check_container_title("Inception.2010.1080p.BluRay.x264-SPARKS", "Inception")
        self.assertEqual(flags, ["mkv_title_mismatch"])

    def test_different_clean_title(self) -> None:
        """Titre different mais propre → warning mkv_title_mismatch."""
        flags = check_container_title("Mon Film", "Inception")
        self.assertEqual(flags, ["mkv_title_mismatch"])

    def test_empty_proposed_title(self) -> None:
        """proposed_title vide → pas de warning (pas de reference de comparaison)."""
        self.assertEqual(check_container_title("Something", ""), [])

    def test_mp4_with_different_title(self) -> None:
        """Conteneur non-MKV avec titre different → warning aussi."""
        flags = check_container_title("rip.by.XxX", "The Matrix")
        self.assertEqual(flags, ["mkv_title_mismatch"])


# ---------------------------------------------------------------------------
# _is_scene_title
# ---------------------------------------------------------------------------


class SceneTitleDetectionTests(unittest.TestCase):
    """Tests de la detection de titres scene."""

    def test_typical_scene(self) -> None:
        self.assertTrue(_is_scene_title("Inception.2010.1080p.BluRay.x264-SPARKS"))

    def test_clean_title(self) -> None:
        self.assertFalse(_is_scene_title("Inception"))

    def test_year_and_codec(self) -> None:
        self.assertTrue(_is_scene_title("Movie 2020 x264"))

    def test_single_pattern(self) -> None:
        """Un seul pattern ne suffit pas (threshold = 2)."""
        self.assertFalse(_is_scene_title("Movie 2020"))


# ---------------------------------------------------------------------------
# Extraction probe
# ---------------------------------------------------------------------------


class ProbeExtractionTests(unittest.TestCase):
    """Tests extraction du container_title depuis ffprobe/mediainfo."""

    def test_ffprobe_extracts_container_title(self) -> None:
        """ffprobe format.tags.title → container_title."""
        raw = {
            "format": {
                "format_name": "matroska,webm",
                "duration": "7200.0",
                "tags": {"title": "Inception.2010.1080p.BluRay.x264-SPARKS"},
            },
            "streams": [],
        }
        result = _extract_ffprobe(raw)
        self.assertEqual(result["container_title"], "Inception.2010.1080p.BluRay.x264-SPARKS")

    def test_ffprobe_no_title(self) -> None:
        """ffprobe sans tags.title → container_title None."""
        raw = {"format": {"format_name": "matroska", "duration": "100"}, "streams": []}
        result = _extract_ffprobe(raw)
        self.assertIsNone(result["container_title"])

    def test_mediainfo_extracts_container_title(self) -> None:
        """MediaInfo general.Title → container_title."""
        raw = {
            "media": {
                "track": [
                    {"@type": "General", "Format": "Matroska", "Title": "Mon Film Rip"},
                ]
            }
        }
        result = _extract_mediainfo(raw)
        self.assertEqual(result["container_title"], "Mon Film Rip")

    def test_mediainfo_movie_field(self) -> None:
        """MediaInfo general.Movie → container_title (fallback)."""
        raw = {
            "media": {
                "track": [
                    {"@type": "General", "Format": "Matroska", "Movie": "Film Name"},
                ]
            }
        }
        result = _extract_mediainfo(raw)
        self.assertEqual(result["container_title"], "Film Name")

    def test_normalized_probe_has_container_title(self) -> None:
        """NormalizedProbe possede le champ container_title."""
        probe = NormalizedProbe(path="/test.mkv")
        self.assertIsNone(probe.container_title)
        probe.container_title = "Test Title"
        self.assertEqual(probe.container_title, "Test Title")


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/review.js supprime — adaptation v5 deferee a V5C-03")
class MkvTitleUiTests(unittest.TestCase):
    """Tests presence UI badge titre MKV."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.validation_js = (root / "web" / "views" / "validation.js").read_text(encoding="utf-8")
        cls.review_js = (root / "web" / "dashboard" / "views" / "review.js").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")
        cls.dash_css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_validation_js_has_mkv_title_badge(self) -> None:
        self.assertIn("mkvTitleBadge", self.validation_js)
        self.assertIn("badge--mkv-title", self.validation_js)
        self.assertIn("mkv_title_mismatch", self.validation_js)

    def test_review_js_has_mkv_title_badge(self) -> None:
        self.assertIn("badge-mkv-title", self.review_js)
        self.assertIn("mkv_title_mismatch", self.review_js)

    def test_app_css_has_mkv_title(self) -> None:
        self.assertIn(".badge--mkv-title", self.app_css)

    def test_dash_css_has_mkv_title(self) -> None:
        self.assertIn(".badge-mkv-title", self.dash_css)


if __name__ == "__main__":
    unittest.main()
