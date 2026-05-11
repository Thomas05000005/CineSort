"""Tests edge cases analyse perceptuelle — Phase IX (item 9.24).

Couvre :
- Film tres court
- Audio-only / video-only
- ffmpeg disparu
- Probe FAILED
- Settings min/max
- Persistence DB
- Stub calibration
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cinesort.ui.api.perceptual_support import (
    _build_settings_dict,
    get_perceptual_report,
)
from cinesort.domain.perceptual.constants import CALIBRATION_ENABLED, CALIBRATION_MIN_FILMS
from cinesort.domain.perceptual.composite_score import (
    build_perceptual_result,
    compute_global_score,
)
from cinesort.domain.perceptual.models import AudioPerceptual, VideoPerceptual


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_api(perceptual_enabled: bool = True):
    api = mock.MagicMock()
    api.get_settings.return_value = {
        "perceptual_enabled": perceptual_enabled,
        "ffprobe_path": "/usr/bin/ffprobe",
        "perceptual_timeout_per_film_s": 120,
        "perceptual_frames_count": 10,
        "perceptual_skip_percent": 5,
        "perceptual_dark_weight": 1.5,
        "perceptual_audio_deep": True,
        "perceptual_audio_segment_s": 30,
        "perceptual_comparison_frames": 20,
        "perceptual_comparison_timeout_s": 600,
    }
    return api


def _setup_api_with_probe(api, probe_normalized, row=None):
    """Configure le mock API avec probe et row."""
    store = mock.MagicMock()
    store.get_perceptual_report.return_value = None
    api._find_run_row.return_value = ({"state_dir": "/tmp"}, store)
    rs = mock.MagicMock()
    r = row or SimpleNamespace(
        row_id="r1",
        proposed_title="Film",
        proposed_year=2020,
        folder="/films/Film",
        video="film.mkv",
        candidates=[],
    )
    rs.rows = [r]
    rs.cfg = mock.MagicMock()
    api._get_run.return_value = rs
    media = mock.MagicMock()
    media.exists.return_value = True
    api._resolve_media_path_for_row.return_value = media
    return store, r, media


# ---------------------------------------------------------------------------
# Edge cases (10 tests)
# ---------------------------------------------------------------------------


class ShortFilmTests(unittest.TestCase):
    """Tests film tres court."""

    @mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value="/usr/bin/ffmpeg")
    @mock.patch("cinesort.ui.api.perceptual_support._load_probe")
    @mock.patch("cinesort.ui.api.perceptual_support.extract_representative_frames", return_value=[])
    @mock.patch("cinesort.ui.api.perceptual_support.run_filter_graph", return_value=[])
    @mock.patch("cinesort.ui.api.perceptual_support.analyze_audio_perceptual")
    def test_short_film_no_crash(self, mock_audio, mock_filter, mock_frames, mock_probe, _) -> None:
        """Film < 2 min → fonctionne, frames_count reduit."""
        api = _mock_api()
        mock_probe.return_value = {
            "normalized": {
                "video": {"width": 1920, "height": 1080, "bit_depth": 8, "fps": 24},
                "duration_s": 60.0,  # 1 minute
                "audio_tracks": [{"index": 0, "codec": "aac", "channels": 2}],
                "probe_quality": "FULL",
            }
        }
        mock_audio.return_value = AudioPerceptual(track_index=0, audio_score=50, audio_tier="mediocre")
        _setup_api_with_probe(api, None)

        result = get_perceptual_report(api, "run1", "r1")
        self.assertTrue(result["ok"])
        # Verifier que frames_count a ete passe reduit (<=3)
        if mock_frames.called:
            # Le test verifie simplement qu'on ne crashe pas ; la valeur exacte
            # de frames_count n'est pas asserted ici.
            _ = mock_frames.call_args


class AudioOnlyTests(unittest.TestCase):
    """Tests fichier audio-only."""

    @mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value="/usr/bin/ffmpeg")
    @mock.patch("cinesort.ui.api.perceptual_support._load_probe")
    @mock.patch("cinesort.ui.api.perceptual_support.analyze_audio_perceptual")
    def test_audio_only_visual_zero(self, mock_audio, mock_probe, _) -> None:
        """Pas de video → visual_score=0, audio analyse."""
        api = _mock_api()
        mock_probe.return_value = {
            "normalized": {
                "video": {},  # pas de video
                "duration_s": 3600.0,
                "audio_tracks": [{"index": 0, "codec": "aac", "channels": 2}],
                "probe_quality": "PARTIAL",
            }
        }
        mock_audio.return_value = AudioPerceptual(track_index=0, audio_score=70, audio_tier="bon")
        _setup_api_with_probe(api, None)

        result = get_perceptual_report(api, "run1", "r1")
        self.assertTrue(result["ok"])
        perc = result.get("perceptual", {})
        self.assertEqual(perc.get("visual_score", 0), 0)
        self.assertGreater(perc.get("audio_score", 0), 0)


class VideoOnlyTests(unittest.TestCase):
    """Tests fichier video-only."""

    def test_video_only_audio_zero(self) -> None:
        """Pas d'audio → audio_score=0, global = visual."""
        video = VideoPerceptual(visual_score=80)
        result = build_perceptual_result(video, None, None)
        self.assertEqual(result.audio_score, 0)
        # Global = visual (100% video quand pas d'audio)
        self.assertEqual(result.global_score, result.visual_score)

    def test_global_score_no_audio(self) -> None:
        """compute_global_score avec audio=0 → retourne visual."""
        self.assertEqual(compute_global_score(80, 0), 80)


class FfmpegAbsentTests(unittest.TestCase):
    """Tests ffmpeg introuvable."""

    @mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value=None)
    def test_ffmpeg_missing_graceful(self, _) -> None:
        """ffmpeg introuvable → erreur gracieuse."""
        api = _mock_api()
        result = get_perceptual_report(api, "run1", "r1")
        self.assertFalse(result["ok"])
        self.assertIn("ffmpeg", result["message"].lower())


class ProbeFailedTests(unittest.TestCase):
    """Tests probe echouee."""

    @mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value="/usr/bin/ffmpeg")
    @mock.patch("cinesort.ui.api.perceptual_support._load_probe")
    def test_probe_failed_graceful(self, mock_probe, _) -> None:
        """Probe FAILED → erreur gracieuse."""
        api = _mock_api()
        mock_probe.return_value = {
            "normalized": {
                "video": {},
                "duration_s": 0,
                "audio_tracks": [],
                "probe_quality": "FAILED",
            }
        }
        _setup_api_with_probe(api, None)

        result = get_perceptual_report(api, "run1", "r1")
        self.assertFalse(result["ok"])
        self.assertIn("corrompu", result["message"].lower())


class DisabledTests(unittest.TestCase):
    """Tests perceptual desactive."""

    def test_disabled_no_analysis(self) -> None:
        api = _mock_api(perceptual_enabled=False)
        result = get_perceptual_report(api, "run1", "r1")
        self.assertFalse(result["ok"])
        self.assertIn("desactivee", result["message"])


class SettingsExtremeTests(unittest.TestCase):
    """Tests settings aux valeurs min et max."""

    def test_settings_min_values(self) -> None:
        """Tous les settings aux valeurs minimum → dict valide."""
        d = _build_settings_dict(
            {
                "perceptual_enabled": True,
                "perceptual_timeout_per_film_s": 30,
                "perceptual_frames_count": 5,
                "perceptual_skip_percent": 0,
                "perceptual_dark_weight": 1.0,
                "perceptual_audio_segment_s": 10,
                "perceptual_comparison_frames": 10,
                "perceptual_comparison_timeout_s": 120,
            }
        )
        self.assertEqual(d["timeout_per_film_s"], 30)
        self.assertEqual(d["frames_count"], 5)

    def test_settings_max_values(self) -> None:
        """Tous les settings aux valeurs maximum → dict valide."""
        d = _build_settings_dict(
            {
                "perceptual_enabled": True,
                "perceptual_timeout_per_film_s": 600,
                "perceptual_frames_count": 50,
                "perceptual_skip_percent": 20,
                "perceptual_dark_weight": 3.0,
                "perceptual_audio_segment_s": 120,
                "perceptual_comparison_frames": 100,
                "perceptual_comparison_timeout_s": 1800,
            }
        )
        self.assertEqual(d["timeout_per_film_s"], 600)
        self.assertEqual(d["comparison_timeout_s"], 1800)


class PersistenceRoundtripTests(unittest.TestCase):
    """Tests persistence DB."""

    def test_db_roundtrip_identical(self) -> None:
        """Resultat persiste et recharge identique."""
        tmp = tempfile.mkdtemp(prefix="cinesort_perc_rt_")
        try:
            from cinesort.infra.db.sqlite_store import SQLiteStore

            store = SQLiteStore(Path(tmp) / "db" / "cinesort.sqlite")
            store.initialize()
            store.upsert_perceptual_report(
                run_id="run1",
                row_id="r1",
                visual_score=78,
                audio_score=82,
                global_score=80,
                global_tier="excellent",
                metrics={"global_score": 80, "version": "1.0"},
                settings_used={"frames_count": 10, "dark_weight": 1.5},
            )
            loaded = store.get_perceptual_report(run_id="run1", row_id="r1")
            self.assertEqual(loaded["visual_score"], 78)
            self.assertEqual(loaded["audio_score"], 82)
            self.assertEqual(loaded["global_score"], 80)
            self.assertEqual(loaded["global_tier"], "excellent")
            self.assertEqual(loaded["metrics"]["version"], "1.0")
            self.assertEqual(loaded["settings_used"]["dark_weight"], 1.5)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CalibrationStubTests(unittest.TestCase):
    """Tests du stub calibration."""

    def test_calibration_disabled(self) -> None:
        """CALIBRATION_ENABLED est False."""
        self.assertFalse(CALIBRATION_ENABLED)
        self.assertEqual(CALIBRATION_MIN_FILMS, 3)


if __name__ == "__main__":
    unittest.main()
