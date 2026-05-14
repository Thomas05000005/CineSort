"""Tests infrastructure analyse perceptuelle — Phase I (item 9.24).

Couvre :
- ffmpeg_runner : resolve_ffmpeg_path, run_ffmpeg_binary, run_ffmpeg_text
- DB mixin : _PerceptualMixin (upsert, get, list)
- Settings : defaults perceptuels
- Models : dataclasses et serialisation
- Constants : valeurs coherentes
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.domain.perceptual.constants import (
    GLOBAL_WEIGHT_AUDIO,
    GLOBAL_WEIGHT_VIDEO,
    MAJOR_STUDIOS,
    PERCEPTUAL_ENGINE_VERSION,
    TIER_REFERENCE,
    TIER_EXCELLENT,
    TIER_GOOD,
    TIER_MEDIOCRE,
    VISUAL_WEIGHT_BLOCKINESS,
    VISUAL_WEIGHT_BLUR,
    VISUAL_WEIGHT_BANDING,
    VISUAL_WEIGHT_BIT_DEPTH,
    VISUAL_WEIGHT_GRAIN_VERDICT,
    VISUAL_WEIGHT_TEMPORAL,
    AUDIO_WEIGHT_LRA,
    AUDIO_WEIGHT_NOISE_FLOOR,
    AUDIO_WEIGHT_CLIPPING,
    AUDIO_WEIGHT_DYNAMIC_RANGE,
    AUDIO_WEIGHT_CREST,
    AUDIO_WEIGHT_MEL,
)
from cinesort.domain.perceptual.models import (
    AudioPerceptual,
    GrainAnalysis,
    PerceptualResult,
    VideoPerceptual,
)
from cinesort.domain.perceptual.ffmpeg_runner import resolve_ffmpeg_path


# ---------------------------------------------------------------------------
# ffmpeg_runner (5 tests)
# ---------------------------------------------------------------------------


class FfmpegRunnerTests(unittest.TestCase):
    """Tests du runner ffmpeg."""

    def test_resolve_ffmpeg_from_ffprobe_sibling(self) -> None:
        """ffmpeg trouve comme sibling de ffprobe."""
        with tempfile.TemporaryDirectory() as tmp:
            ffprobe = Path(tmp) / "ffprobe.exe"
            ffmpeg = Path(tmp) / "ffmpeg.exe"
            ffprobe.write_text("fake")
            ffmpeg.write_text("fake")
            result = resolve_ffmpeg_path(str(ffprobe))
            self.assertEqual(result, str(ffmpeg))

    def test_resolve_ffmpeg_not_found_returns_which(self) -> None:
        """Fallback vers shutil.which si pas de sibling."""
        with mock.patch("cinesort.domain.perceptual.ffmpeg_runner.shutil.which", return_value=None):
            result = resolve_ffmpeg_path("/nonexistent/ffprobe")
            self.assertIsNone(result)

    def test_resolve_ffmpeg_empty_path_uses_which(self) -> None:
        """Chemin vide → shutil.which directement."""
        with mock.patch("cinesort.domain.perceptual.ffmpeg_runner.shutil.which", return_value="/usr/bin/ffmpeg"):
            result = resolve_ffmpeg_path("")
            self.assertEqual(result, "/usr/bin/ffmpeg")

    @mock.patch("cinesort.domain.perceptual.ffmpeg_runner.tracked_run")
    def test_run_ffmpeg_binary_returns_bytes(self, mock_run) -> None:
        """run_ffmpeg_binary retourne des bytes pour stdout.

        Note V1-03 : les runners utilisent maintenant `tracked_run` (cf
        `cinesort.infra.subprocess_safety`) au lieu de `subprocess.run` direct
        pour garantir le cleanup des subprocess en cas d'exception.
        """
        from cinesort.domain.perceptual.ffmpeg_runner import run_ffmpeg_binary

        mock_run.return_value = mock.MagicMock(returncode=0, stdout=b"\x00\x01\x02", stderr=b"info")
        rc, stdout, stderr = run_ffmpeg_binary(["ffmpeg", "-version"], 10.0)
        self.assertEqual(rc, 0)
        self.assertIsInstance(stdout, bytes)
        self.assertEqual(stdout, b"\x00\x01\x02")
        self.assertIsInstance(stderr, str)

    @mock.patch("cinesort.domain.perceptual.ffmpeg_runner.tracked_run")
    def test_run_ffmpeg_text_returns_strings(self, mock_run) -> None:
        """run_ffmpeg_text retourne des strings.

        Note V1-03 : voir test_run_ffmpeg_binary_returns_bytes pour la
        migration vers tracked_run.
        """
        from cinesort.domain.perceptual.ffmpeg_runner import run_ffmpeg_text

        mock_run.return_value = mock.MagicMock(returncode=0, stdout="output", stderr="info")
        rc, stdout, stderr = run_ffmpeg_text(["ffmpeg", "-version"], 10.0)
        self.assertEqual(rc, 0)
        self.assertIsInstance(stdout, str)
        self.assertIsInstance(stderr, str)


# ---------------------------------------------------------------------------
# DB mixin (4 tests)
# ---------------------------------------------------------------------------


class PerceptualDbTests(unittest.TestCase):
    """Tests du mixin DB perceptuel."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="cinesort_perc_db_")
        db_path = Path(self.tmp) / "db" / "cinesort.sqlite"
        from cinesort.infra.db.sqlite_store import SQLiteStore

        self.store = SQLiteStore(db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_upsert_and_get_roundtrip(self) -> None:
        """Upsert + get retourne les memes donnees."""
        metrics = {"visual_score": 78, "audio_score": 82}
        settings_used = {"frames_count": 10}
        self.store.upsert_perceptual_report(
            run_id="run1",
            row_id="row1",
            visual_score=78,
            audio_score=82,
            global_score=80,
            global_tier="Excellent",
            metrics=metrics,
            settings_used=settings_used,
        )
        result = self.store.get_perceptual_report(run_id="run1", row_id="row1")
        self.assertIsNotNone(result)
        self.assertEqual(result["visual_score"], 78)
        self.assertEqual(result["audio_score"], 82)
        self.assertEqual(result["global_score"], 80)
        self.assertEqual(result["global_tier"], "Excellent")
        self.assertEqual(result["metrics"]["visual_score"], 78)
        self.assertEqual(result["settings_used"]["frames_count"], 10)

    def test_get_nonexistent_returns_none(self) -> None:
        """Get d'un rapport inexistant retourne None."""
        result = self.store.get_perceptual_report(run_id="nope", row_id="nope")
        self.assertIsNone(result)

    def test_list_reports(self) -> None:
        """List retourne tous les rapports d'un run tries par score."""
        self.store.upsert_perceptual_report(
            run_id="run1",
            row_id="r1",
            visual_score=90,
            audio_score=85,
            global_score=88,
            global_tier="Excellent",
            metrics={},
            settings_used={},
        )
        self.store.upsert_perceptual_report(
            run_id="run1",
            row_id="r2",
            visual_score=50,
            audio_score=40,
            global_score=46,
            global_tier="Mediocre",
            metrics={},
            settings_used={},
        )
        reports = self.store.list_perceptual_reports(run_id="run1")
        self.assertEqual(len(reports), 2)
        # Tries par score ASC
        self.assertEqual(reports[0]["row_id"], "r2")
        self.assertEqual(reports[1]["row_id"], "r1")

    def test_upsert_update_existing(self) -> None:
        """Upsert met a jour un rapport existant."""
        self.store.upsert_perceptual_report(
            run_id="run1",
            row_id="r1",
            visual_score=50,
            audio_score=50,
            global_score=50,
            global_tier="Mediocre",
            metrics={},
            settings_used={},
        )
        self.store.upsert_perceptual_report(
            run_id="run1",
            row_id="r1",
            visual_score=90,
            audio_score=85,
            global_score=88,
            global_tier="Excellent",
            metrics={},
            settings_used={},
        )
        result = self.store.get_perceptual_report(run_id="run1", row_id="r1")
        self.assertEqual(result["global_score"], 88)


# ---------------------------------------------------------------------------
# Models (4 tests)
# ---------------------------------------------------------------------------


class ModelSerializationTests(unittest.TestCase):
    """Tests de serialisation des dataclasses."""

    def test_video_perceptual_to_dict(self) -> None:
        v = VideoPerceptual(
            frames_analyzed=10,
            blockiness_mean=22.4,
            blur_mean=0.025,
            visual_score=78,
            visual_tier="excellent",
            resolution_width=3840,
            resolution_height=2160,
        )
        d = v.to_dict()
        self.assertEqual(d["frames_analyzed"], 10)
        self.assertEqual(d["blockiness"]["mean"], 22.4)
        self.assertEqual(d["blur"]["mean"], 0.025)
        self.assertEqual(d["resolution"]["width"], 3840)
        self.assertEqual(d["visual_score"], 78)

    def test_audio_perceptual_to_dict(self) -> None:
        a = AudioPerceptual(
            track_index=0,
            track_codec="truehd",
            track_channels=8,
            integrated_loudness=-24.2,
            loudness_range=14.5,
            true_peak=-1.8,
            audio_score=82,
            audio_tier="excellent",
        )
        d = a.to_dict()
        self.assertEqual(d["track_analyzed"]["codec"], "truehd")
        self.assertEqual(d["ebu_r128"]["loudness_range"], 14.5)
        self.assertEqual(d["audio_score"], 82)

    def test_grain_analysis_to_dict(self) -> None:
        g = GrainAnalysis(
            grain_level=2.4,
            grain_uniformity=0.55,
            verdict="grain_naturel_preserve",
            verdict_confidence=0.88,
            tmdb_year=1994,
            score=85,
        )
        d = g.to_dict()
        self.assertEqual(d["grain_level"], 2.4)
        self.assertEqual(d["verdict"], "grain_naturel_preserve")
        self.assertEqual(d["tmdb_year"], 1994)

    def test_perceptual_result_to_dict(self) -> None:
        r = PerceptualResult(
            visual_score=78,
            audio_score=82,
            global_score=80,
            global_tier="excellent",
            ts=1712345678.9,
            video=VideoPerceptual(frames_analyzed=10),
            audio=AudioPerceptual(track_codec="truehd"),
            grain=GrainAnalysis(verdict="image_propre_normal"),
        )
        d = r.to_dict()
        self.assertEqual(d["global_score"], 80)
        self.assertIsNotNone(d["video_perceptual"])
        self.assertIsNotNone(d["audio_perceptual"])
        self.assertIsNotNone(d["grain_analysis"])
        self.assertEqual(d["video_perceptual"]["frames_analyzed"], 10)

    def test_perceptual_result_none_components(self) -> None:
        """Resultat sans composants = None dans le dict."""
        r = PerceptualResult(global_score=0, global_tier="degrade")
        d = r.to_dict()
        self.assertIsNone(d["video_perceptual"])
        self.assertIsNone(d["audio_perceptual"])
        self.assertIsNone(d["grain_analysis"])


# ---------------------------------------------------------------------------
# Constants (3 tests)
# ---------------------------------------------------------------------------


class ConstantsCoherenceTests(unittest.TestCase):
    """Tests de coherence des constantes."""

    def test_visual_weights_sum_100(self) -> None:
        total = (
            VISUAL_WEIGHT_BLOCKINESS
            + VISUAL_WEIGHT_BLUR
            + VISUAL_WEIGHT_BANDING
            + VISUAL_WEIGHT_BIT_DEPTH
            + VISUAL_WEIGHT_GRAIN_VERDICT
            + VISUAL_WEIGHT_TEMPORAL
        )
        self.assertEqual(total, 100)

    def test_audio_weights_sum_100(self) -> None:
        # §12 v7.5.0 : AUDIO_WEIGHT_MEL (15) inclus dans la somme 100
        total = (
            AUDIO_WEIGHT_LRA
            + AUDIO_WEIGHT_NOISE_FLOOR
            + AUDIO_WEIGHT_CLIPPING
            + AUDIO_WEIGHT_DYNAMIC_RANGE
            + AUDIO_WEIGHT_CREST
            + AUDIO_WEIGHT_MEL
        )
        self.assertEqual(total, 100)

    def test_global_weights_sum_100(self) -> None:
        self.assertEqual(GLOBAL_WEIGHT_VIDEO + GLOBAL_WEIGHT_AUDIO, 100)

    def test_tiers_ordered(self) -> None:
        self.assertGreater(TIER_REFERENCE, TIER_EXCELLENT)
        self.assertGreater(TIER_EXCELLENT, TIER_GOOD)
        self.assertGreater(TIER_GOOD, TIER_MEDIOCRE)

    def test_major_studios_non_empty(self) -> None:
        self.assertGreater(len(MAJOR_STUDIOS), 10)

    def test_engine_version_set(self) -> None:
        self.assertEqual(PERCEPTUAL_ENGINE_VERSION, "1.0")


# ---------------------------------------------------------------------------
# Settings (3 tests)
# ---------------------------------------------------------------------------


class SettingsDefaultsTests(unittest.TestCase):
    """Tests que les settings perceptuels ont des defaults."""

    def test_all_perceptual_settings_present(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        # Utiliser un state_dir temporaire vide pour tester les vrais defaults
        tmp = tempfile.mkdtemp(prefix="cinesort_perc_def_")
        try:
            api = backend.CineSortApi()
            api._state_dir = Path(tmp)
            s = api.settings.get_settings()
            self.assertFalse(s.get("perceptual_enabled"))
            self.assertFalse(s.get("perceptual_auto_on_scan"))
            self.assertTrue(s.get("perceptual_auto_on_quality"))
            self.assertEqual(s.get("perceptual_timeout_per_film_s"), 120)
            self.assertEqual(s.get("perceptual_frames_count"), 10)
            self.assertEqual(s.get("perceptual_skip_percent"), 5)
            self.assertEqual(s.get("perceptual_dark_weight"), 1.5)
            self.assertTrue(s.get("perceptual_audio_deep"))
            self.assertEqual(s.get("perceptual_audio_segment_s"), 30)
            self.assertEqual(s.get("perceptual_comparison_frames"), 20)
            self.assertEqual(s.get("perceptual_comparison_timeout_s"), 600)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_perceptual_settings_roundtrip(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        tmp = tempfile.mkdtemp(prefix="cinesort_perc_s_")
        try:
            root = Path(tmp) / "root"
            sd = Path(tmp) / "state"
            root.mkdir()
            sd.mkdir()
            api = backend.CineSortApi()
            api.settings.save_settings(
                {
                    "root": str(root),
                    "state_dir": str(sd),
                    "tmdb_enabled": False,
                    "perceptual_enabled": True,
                    "perceptual_frames_count": 25,
                    "perceptual_comparison_timeout_s": 900,
                }
            )
            s = api.settings.get_settings()
            self.assertTrue(s["perceptual_enabled"])
            self.assertEqual(s["perceptual_frames_count"], 25)
            self.assertEqual(s["perceptual_comparison_timeout_s"], 900)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_hiddenimports_perceptual_in_spec(self) -> None:
        """CineSort.spec contient le package perceptual dans hiddenimports."""
        spec = Path(__file__).resolve().parents[1] / "CineSort.spec"
        content = spec.read_text(encoding="utf-8")
        self.assertIn("cinesort.domain.perceptual", content)
        self.assertIn("cinesort.domain.perceptual.constants", content)
        self.assertIn("cinesort.domain.perceptual.models", content)
        self.assertIn("cinesort.domain.perceptual.ffmpeg_runner", content)


# ---------------------------------------------------------------------------
# Schema migration (1 test)
# ---------------------------------------------------------------------------


class SchemaMigrationTests(unittest.TestCase):
    """Tests que la migration 009 est chargee."""

    def test_migration_file_exists(self) -> None:
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "cinesort"
            / "infra"
            / "db"
            / "migrations"
            / "009_perceptual_reports.sql"
        )
        self.assertTrue(migration_path.exists())
        content = migration_path.read_text(encoding="utf-8")
        self.assertIn("perceptual_reports", content)
        self.assertIn("visual_score", content)
        self.assertIn("audio_score", content)
        self.assertIn("global_score", content)
        self.assertIn("metrics_json", content)
        self.assertIn("settings_json", content)


if __name__ == "__main__":
    unittest.main()
