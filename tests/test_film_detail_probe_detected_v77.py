"""GATE AUDIT 2026-06-14 (R7-2) — apercu Modal Detail Film lit probe.detected.*

get_film_full renvoie le metrics brut (probe = quality_reports.metrics) dont les
caracteristiques sont sous probe.detected.* (resolution/video_codec/bitrate_kbps/
audio_tracks_count/duration_s). Le front lisait probe.video/audio/subtitles ->
specs vides, "Pistes audio: 0". Le nb de sous-titres vient de la PlanRow.
"""
from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_COMP = _ROOT / "web" / "dashboard" / "components" / "film-detail.js"
_QS = _ROOT / "cinesort" / "domain" / "quality_score.py"


class FilmDetailProbeDetectedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _COMP.read_text(encoding="utf-8")
        cls.qs = _QS.read_text(encoding="utf-8")

    def test_backend_metrics_has_detected(self) -> None:
        self.assertIn('"detected": {', self.qs)
        self.assertIn('"audio_tracks_count"', self.qs)

    def test_overview_reads_detected(self) -> None:
        self.assertIn("const det = probe.detected || {}", self.js)
        self.assertIn("det.audio_tracks_count", self.js)
        self.assertIn("det.video_codec", self.js)
        self.assertIn("det.bitrate_kbps", self.js)
        self.assertIn("row.subtitle_count", self.js)

    def test_overview_no_longer_reads_legacy_shape(self) -> None:
        self.assertNotIn("const video = probe.video || {}", self.js)
        self.assertNotIn("Array.isArray(probe.audio)", self.js)
        self.assertNotIn("Array.isArray(probe.subtitles)", self.js)


if __name__ == "__main__":
    unittest.main()
