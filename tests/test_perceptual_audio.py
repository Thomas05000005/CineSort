"""Tests analyse audio perceptuelle — Phase IV (item 9.24).

Couvre :
- select_best_audio_track : hierarchie codec
- analyze_loudnorm : parsing JSON, verdicts LRA/TP
- analyze_astats : parsing regex, verdicts noise/dynamics/crest
- analyze_clipping_segments : comptage segments, verdict
- analyze_audio_perceptual : orchestration, deep=False, score, piste absente
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from cinesort.domain.perceptual.audio_perceptual import (
    analyze_audio_perceptual,
    analyze_astats,
    analyze_clipping_segments,
    analyze_loudnorm,
    select_best_audio_track,
    _compute_audio_score,
)


# ---------------------------------------------------------------------------
# select_best_audio_track (2 tests)
# ---------------------------------------------------------------------------


class SelectBestTrackTests(unittest.TestCase):
    """Tests de la selection de la meilleure piste audio."""

    def test_truehd_before_ac3(self) -> None:
        """TrueHD (rang 5) choisi avant AC3 (rang 2)."""
        tracks = [
            {"index": 0, "codec": "ac3", "channels": 6, "language": "eng", "title": ""},
            {"index": 1, "codec": "truehd", "channels": 8, "language": "eng", "title": ""},
        ]
        best = select_best_audio_track(tracks)
        self.assertIsNotNone(best)
        self.assertEqual(best["index"], 1)
        self.assertEqual(best["codec"], "truehd")

    def test_empty_tracks_returns_none(self) -> None:
        """Aucune piste → None."""
        self.assertIsNone(select_best_audio_track([]))

    def test_hierarchy_respected(self) -> None:
        """L'ordre complet de la hierarchie est respecte."""
        tracks = [
            {"index": 0, "codec": "aac", "channels": 2, "language": "eng", "title": ""},
            {"index": 1, "codec": "dts", "channels": 6, "language": "eng", "title": ""},
            {"index": 2, "codec": "eac3", "channels": 6, "language": "eng", "title": ""},
            {"index": 3, "codec": "dts-hd", "channels": 8, "language": "eng", "title": ""},
        ]
        best = select_best_audio_track(tracks)
        self.assertEqual(best["index"], 3)  # dts-hd rang 4, le plus haut


# ---------------------------------------------------------------------------
# analyze_loudnorm (3 tests)
# ---------------------------------------------------------------------------


class LoudnormTests(unittest.TestCase):
    """Tests du parsing loudnorm EBU R128."""

    @mock.patch("cinesort.domain.perceptual.audio_perceptual.run_ffmpeg_text")
    def test_json_parsing_correct(self, mock_run) -> None:
        """Bloc JSON correctement parse → IL, LRA, TP extraits."""
        loudnorm_json = json.dumps(
            {
                "input_i": "-24.2",
                "input_tp": "-1.5",
                "input_lra": "14.5",
                "input_thresh": "-34.5",
                "target_offset": "0.3",
            }
        )
        mock_run.return_value = (0, "", f"some info\n{loudnorm_json}\n")
        result = analyze_loudnorm("/usr/bin/ffmpeg", "film.mkv", 0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["integrated_loudness"], -24.2)
        self.assertAlmostEqual(result["loudness_range"], 14.5)
        self.assertAlmostEqual(result["true_peak"], -1.5)
        self.assertEqual(result["lra_verdict"], "good")  # 10-15
        self.assertEqual(result["tp_verdict"], "safe")  # < -1

    @mock.patch("cinesort.domain.perceptual.audio_perceptual.run_ffmpeg_text")
    def test_malformed_json_returns_none(self, mock_run) -> None:
        """JSON malforme → None."""
        mock_run.return_value = (0, "", "not json at all")
        result = analyze_loudnorm("/usr/bin/ffmpeg", "film.mkv", 0)
        self.assertIsNone(result)

    @mock.patch("cinesort.domain.perceptual.audio_perceptual.run_ffmpeg_text")
    def test_lra_verdicts(self, mock_run) -> None:
        """LRA > 15 → excellent, < 7 → flat."""
        # Excellent
        mock_run.return_value = (0, "", json.dumps({"input_i": "-20", "input_lra": "18", "input_tp": "-3"}))
        r = analyze_loudnorm("/usr/bin/ffmpeg", "film.mkv", 0)
        self.assertEqual(r["lra_verdict"], "excellent")

        # Flat
        mock_run.return_value = (0, "", json.dumps({"input_i": "-20", "input_lra": "5", "input_tp": "-3"}))
        r = analyze_loudnorm("/usr/bin/ffmpeg", "film.mkv", 0)
        self.assertEqual(r["lra_verdict"], "flat")


# ---------------------------------------------------------------------------
# analyze_astats (2 tests)
# ---------------------------------------------------------------------------


class AstatsTests(unittest.TestCase):
    """Tests du parsing astats."""

    @mock.patch("cinesort.domain.perceptual.audio_perceptual.run_ffmpeg_text")
    def test_all_fields_parsed(self, mock_run) -> None:
        """Tous les champs extraits depuis stderr."""
        stderr = (
            "[Parsed_astats_0 @ 0x1234]\n"
            "Overall RMS level: -28.4 dB\n"
            "Overall Peak level: -1.2 dB\n"
            "Overall Noise floor: -68.5 dB\n"
            "Overall Crest factor: 18.2\n"
            "Overall Dynamic range: 55.3\n"
        )
        mock_run.return_value = (0, "", stderr)
        result = analyze_astats("/usr/bin/ffmpeg", "film.mkv", 0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["rms_level"], -28.4)
        self.assertAlmostEqual(result["peak_level"], -1.2)
        self.assertAlmostEqual(result["noise_floor"], -68.5)
        self.assertAlmostEqual(result["crest_factor"], 18.2)
        self.assertAlmostEqual(result["dynamic_range"], 55.3)
        self.assertEqual(result["noise_verdict"], "good")  # -70 a -60
        self.assertEqual(result["dynamics_verdict"], "good")  # 45-60
        self.assertEqual(result["crest_verdict"], "good")  # 14-20

    @mock.patch("cinesort.domain.perceptual.audio_perceptual.run_ffmpeg_text")
    def test_partial_parsing(self, mock_run) -> None:
        """Champs manquants → None pour les champs absents."""
        mock_run.return_value = (0, "", "Overall RMS level: -30.0 dB\n")
        result = analyze_astats("/usr/bin/ffmpeg", "film.mkv", 0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["rms_level"], -30.0)
        self.assertIsNone(result["noise_floor"])
        self.assertIsNone(result["dynamic_range"])


# ---------------------------------------------------------------------------
# analyze_clipping_segments (2 tests)
# ---------------------------------------------------------------------------


class ClippingTests(unittest.TestCase):
    """Tests de la detection clipping."""

    @mock.patch("cinesort.domain.perceptual.audio_perceptual.run_ffmpeg_text")
    def test_no_clipping(self, mock_run) -> None:
        """Aucun segment >= -0.1 dBFS → 0%."""
        stderr = "\n".join(f"Peak level: {-5.0 + i * 0.1} dB" for i in range(20))
        mock_run.return_value = (0, "", stderr)
        result = analyze_clipping_segments("/usr/bin/ffmpeg", "film.mkv", 0)
        self.assertEqual(result["clipping_segments"], 0)
        self.assertEqual(result["clipping_pct"], 0.0)
        self.assertEqual(result["verdict"], "acceptable")

    @mock.patch("cinesort.domain.perceptual.audio_perceptual.run_ffmpeg_text")
    def test_severe_clipping(self, mock_run) -> None:
        """Beaucoup de segments en clipping → % eleve."""
        # 10 segments normaux + 3 en clipping
        lines = ["Peak level: -5.0 dB" for _ in range(10)]
        lines += ["Peak level: 0.5 dB" for _ in range(3)]
        mock_run.return_value = (0, "", "\n".join(lines))
        result = analyze_clipping_segments("/usr/bin/ffmpeg", "film.mkv", 0)
        self.assertEqual(result["clipping_segments"], 3)
        self.assertEqual(result["total_segments"], 13)
        self.assertGreater(result["clipping_pct"], 20.0)
        self.assertEqual(result["verdict"], "critical")


# ---------------------------------------------------------------------------
# Score audio (1 test)
# ---------------------------------------------------------------------------


class AudioScoreTests(unittest.TestCase):
    """Tests du scoring composite."""

    def test_composite_weighted(self) -> None:
        """Le score composite utilise les poids corrects."""
        # Scenario reference : tout excellent
        loud = {"loudness_range": 18.0, "true_peak": -3.0, "integrated_loudness": -24.0}
        astats = {
            "noise_floor": -75.0,
            "dynamic_range": 65.0,
            "crest_factor": 22.0,
            "rms_level": -28.0,
            "peak_level": -1.0,
        }
        clip = {"clipping_pct": 0.0, "total_segments": 100, "clipping_segments": 0}
        score = _compute_audio_score(loud, astats, clip)
        self.assertGreater(score, 85)  # Tout excellent → score tres haut

    def test_true_peak_clipping_penalty(self) -> None:
        """TP >= 0 → penalite sur le score clipping."""
        loud_safe = {"loudness_range": 12.0, "true_peak": -3.0, "integrated_loudness": -24.0}
        loud_clip = {"loudness_range": 12.0, "true_peak": 0.5, "integrated_loudness": -24.0}
        s_safe = _compute_audio_score(loud_safe, None, None)
        s_clip = _compute_audio_score(loud_clip, None, None)
        self.assertGreater(s_safe, s_clip)


# ---------------------------------------------------------------------------
# Orchestrateur (3 tests)
# ---------------------------------------------------------------------------


class OrchestratorTests(unittest.TestCase):
    """Tests de l'orchestrateur audio perceptuel."""

    @mock.patch("cinesort.domain.perceptual.audio_perceptual.analyze_clipping_segments")
    @mock.patch("cinesort.domain.perceptual.audio_perceptual.analyze_astats")
    @mock.patch("cinesort.domain.perceptual.audio_perceptual.analyze_loudnorm")
    def test_deep_false_skips_astats(self, mock_loud, mock_astats, mock_clip) -> None:
        """deep=False → seulement loudnorm, pas astats ni clipping."""
        mock_loud.return_value = {
            "integrated_loudness": -24.0,
            "loudness_range": 14.0,
            "true_peak": -2.0,
            "lra_verdict": "good",
            "tp_verdict": "safe",
        }
        tracks = [{"index": 0, "codec": "ac3", "channels": 6, "language": "eng", "title": ""}]
        result = analyze_audio_perceptual("/usr/bin/ffmpeg", "film.mkv", tracks, audio_deep=False)
        mock_loud.assert_called_once()
        mock_astats.assert_not_called()
        mock_clip.assert_not_called()
        self.assertAlmostEqual(result.loudness_range, 14.0)
        self.assertGreater(result.audio_score, 0)

    def test_no_tracks_returns_empty(self) -> None:
        """Aucune piste audio → score 0, tier degrade."""
        result = analyze_audio_perceptual("/usr/bin/ffmpeg", "film.mkv", [])
        self.assertEqual(result.audio_score, 0)
        self.assertEqual(result.audio_tier, "degrade")
        self.assertEqual(result.track_index, -1)

    @mock.patch("cinesort.domain.perceptual.audio_perceptual.analyze_clipping_segments")
    @mock.patch("cinesort.domain.perceptual.audio_perceptual.analyze_astats")
    @mock.patch("cinesort.domain.perceptual.audio_perceptual.analyze_loudnorm")
    def test_mono_track_no_crash(self, mock_loud, mock_astats, mock_clip) -> None:
        """Piste mono (1 channel) → pas de crash."""
        mock_loud.return_value = {
            "integrated_loudness": -24.0,
            "loudness_range": 10.0,
            "true_peak": -2.0,
            "lra_verdict": "good",
            "tp_verdict": "safe",
        }
        mock_astats.return_value = {
            "rms_level": -30.0,
            "peak_level": -2.0,
            "noise_floor": -65.0,
            "crest_factor": 16.0,
            "dynamic_range": 50.0,
            "noise_verdict": "good",
            "dynamics_verdict": "good",
            "crest_verdict": "good",
        }
        mock_clip.return_value = {
            "total_segments": 50,
            "clipping_segments": 0,
            "clipping_pct": 0.0,
            "verdict": "acceptable",
        }
        tracks = [{"index": 0, "codec": "aac", "channels": 1, "language": "eng", "title": ""}]
        result = analyze_audio_perceptual("/usr/bin/ffmpeg", "film.mkv", tracks, audio_deep=True)
        self.assertEqual(result.track_channels, 1)
        self.assertGreater(result.audio_score, 0)


if __name__ == "__main__":
    unittest.main()
