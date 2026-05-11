"""Tests mode bibliothecaire — cinesort/domain/librarian.py.

Couvre :
- Codec obsolete, doublons, sous-titres, non identifies, basse resolution, collections
- Priorite tri, health score, edge cases
- UI : section suggestions dans dashboard + desktop
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from cinesort.domain.librarian import generate_suggestions


def _row(
    *,
    row_id="r1",
    proposed_title="Film",
    proposed_source="tmdb",
    confidence=80,
    warning_flags=None,
    subtitle_missing_langs=None,
    tmdb_collection_id=None,
    tmdb_collection_name=None,
):
    return SimpleNamespace(
        row_id=row_id,
        proposed_title=proposed_title,
        proposed_source=proposed_source,
        confidence=confidence,
        warning_flags=warning_flags or [],
        subtitle_missing_langs=subtitle_missing_langs or [],
        tmdb_collection_id=tmdb_collection_id,
        tmdb_collection_name=tmdb_collection_name,
    )


def _qr(*, row_id="r1", score=80, tier="Bon", video_codec="hevc", resolution="1080p", height=1080):
    return {
        "row_id": row_id,
        "score": score,
        "tier": tier,
        "metrics": {
            "detected": {"video_codec": video_codec, "resolution": resolution, "height": height, "title": row_id}
        },
    }


class CodecObsoleteTests(unittest.TestCase):
    def test_xvid_detected(self) -> None:
        rows = [_row(row_id="r1")]
        qrs = [_qr(row_id="r1", video_codec="xvid")]
        r = generate_suggestions(rows, qrs)
        ids = [s["id"] for s in r["suggestions"]]
        self.assertIn("codec_obsolete", ids)

    def test_hevc_no_suggestion(self) -> None:
        rows = [_row(row_id="r1")]
        qrs = [_qr(row_id="r1", video_codec="hevc")]
        r = generate_suggestions(rows, qrs)
        ids = [s["id"] for s in r["suggestions"]]
        self.assertNotIn("codec_obsolete", ids)


class DuplicateTests(unittest.TestCase):
    def test_duplicate_flag(self) -> None:
        rows = [_row(row_id="r1", warning_flags=["duplicate_cross_root"])]
        r = generate_suggestions(rows, [])
        ids = [s["id"] for s in r["suggestions"]]
        self.assertIn("duplicates", ids)
        dup_s = next(s for s in r["suggestions"] if s["id"] == "duplicates")
        self.assertEqual(dup_s["priority"], "high")

    def test_no_duplicate(self) -> None:
        rows = [_row(row_id="r1")]
        r = generate_suggestions(rows, [])
        ids = [s["id"] for s in r["suggestions"]]
        self.assertNotIn("duplicates", ids)


class MissingSubtitlesTests(unittest.TestCase):
    def test_missing_fr(self) -> None:
        rows = [
            _row(row_id="r1", subtitle_missing_langs=["fr"]),
            _row(row_id="r2", subtitle_missing_langs=["fr"]),
            _row(row_id="r3"),
        ]
        r = generate_suggestions(rows, [], {"subtitle_expected_languages": ["fr"]})
        s = next((x for x in r["suggestions"] if x["id"] == "missing_subtitles"), None)
        self.assertIsNotNone(s)
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["priority"], "medium")

    def test_no_missing(self) -> None:
        rows = [_row(row_id="r1")]
        r = generate_suggestions(rows, [], {"subtitle_expected_languages": ["fr"]})
        ids = [s["id"] for s in r["suggestions"]]
        self.assertNotIn("missing_subtitles", ids)


class UnidentifiedTests(unittest.TestCase):
    def test_unknown_source(self) -> None:
        rows = [_row(row_id="r1", proposed_source="unknown", confidence=0)]
        r = generate_suggestions(rows, [])
        ids = [s["id"] for s in r["suggestions"]]
        self.assertIn("unidentified", ids)

    def test_tmdb_identified(self) -> None:
        rows = [_row(row_id="r1", proposed_source="tmdb", confidence=80)]
        r = generate_suggestions(rows, [])
        ids = [s["id"] for s in r["suggestions"]]
        self.assertNotIn("unidentified", ids)


class LowResolutionTests(unittest.TestCase):
    def test_sd_detected(self) -> None:
        rows = [_row(row_id="r1")]
        qrs = [_qr(row_id="r1", resolution="SD", height=480)]
        r = generate_suggestions(rows, qrs)
        ids = [s["id"] for s in r["suggestions"]]
        self.assertIn("low_resolution", ids)

    def test_1080p_no_suggestion(self) -> None:
        rows = [_row(row_id="r1")]
        qrs = [_qr(row_id="r1", resolution="1080p", height=1080)]
        r = generate_suggestions(rows, qrs)
        ids = [s["id"] for s in r["suggestions"]]
        self.assertNotIn("low_resolution", ids)


class CollectionsTests(unittest.TestCase):
    def test_collections_info(self) -> None:
        rows = [
            _row(row_id="r1", tmdb_collection_id=87096, tmdb_collection_name="Avatar"),
            _row(row_id="r2", tmdb_collection_id=87096, tmdb_collection_name="Avatar"),
            _row(row_id="r3", tmdb_collection_id=119, tmdb_collection_name="LOTR"),
        ]
        r = generate_suggestions(rows, [])
        s = next((x for x in r["suggestions"] if x["id"] == "collections_info"), None)
        self.assertIsNotNone(s)
        self.assertEqual(s["count"], 3)
        self.assertEqual(s["priority"], "low")


class PriorityTests(unittest.TestCase):
    def test_high_before_medium(self) -> None:
        rows = [
            _row(row_id="r1", warning_flags=["duplicate_cross_root"]),
            _row(row_id="r2", proposed_source="unknown", confidence=0),
        ]
        r = generate_suggestions(rows, [])
        self.assertEqual(r["suggestions"][0]["priority"], "high")
        self.assertEqual(r["suggestions"][1]["priority"], "medium")


class HealthScoreTests(unittest.TestCase):
    def test_all_healthy(self) -> None:
        rows = [_row(row_id=f"r{i}") for i in range(10)]
        r = generate_suggestions(rows, [])
        self.assertEqual(r["health_score"], 100)

    def test_some_problems(self) -> None:
        rows = [_row(row_id=f"r{i}") for i in range(10)]
        # 2 films avec problemes
        rows[0].proposed_source = "unknown"
        rows[0].confidence = 0
        rows[1].warning_flags = ["duplicate_cross_root"]
        r = generate_suggestions(rows, [])
        self.assertEqual(r["health_score"], 80)

    def test_zero_films(self) -> None:
        r = generate_suggestions([], [])
        self.assertEqual(r["health_score"], 100)
        self.assertEqual(r["suggestions"], [])


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/status.js supprime — adaptation v5 deferee a V5C-03")
class UiSuggestionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.status_js = (root / "web" / "dashboard" / "views" / "status.js").read_text(encoding="utf-8")
        cls.quality_js = (root / "web" / "views" / "quality.js").read_text(encoding="utf-8")
        cls.html = (root / "web" / "index.html").read_text(encoding="utf-8")
        cls.dash_css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")

    def test_dashboard_librarian_section(self) -> None:
        self.assertIn("librarian", self.status_js)
        self.assertIn("health_score", self.status_js)
        self.assertIn("suggestions", self.status_js)

    def test_dashboard_suggestion_card(self) -> None:
        self.assertIn("suggestion-card", self.status_js)

    def test_desktop_librarian_section(self) -> None:
        self.assertIn("librarian", self.quality_js)
        self.assertIn("health_score", self.quality_js)

    def test_desktop_html_container(self) -> None:
        self.assertIn('id="globalLibrarianSection"', self.html)

    def test_css_suggestion_card_dashboard(self) -> None:
        self.assertIn(".suggestion-card", self.dash_css)

    def test_css_suggestion_card_desktop(self) -> None:
        self.assertIn(".suggestion-card", self.app_css)


if __name__ == "__main__":
    unittest.main()
