"""Tests §9 v7.5.0 — spectral cutoff audio."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from cinesort.domain.perceptual.spectral_analysis import (
    SpectralResult,
    analyze_spectral,
    classify_cutoff,
    compute_rms_db,
    compute_spectrogram,
    extract_audio_segment,
    find_cutoff_hz,
)


def _fake_completed(stdout: bytes = b"", returncode: int = 0, stderr: bytes = b"") -> MagicMock:
    cp = MagicMock()
    cp.stdout = stdout
    cp.stderr = stderr
    cp.returncode = returncode
    return cp


def _sine_wave(freq: float, sr: int, duration_s: float, amp: float = 0.5) -> np.ndarray:
    t = np.linspace(0.0, duration_s, int(sr * duration_s), endpoint=False, dtype=np.float32)
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def _low_pass_cutoff(samples: np.ndarray, sr: int, cutoff_hz: float) -> np.ndarray:
    """Filtre passe-bas naif par FFT (mise a zero des bins > cutoff)."""
    N = len(samples)
    spec = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(N, 1.0 / sr)
    spec[freqs > cutoff_hz] = 0.0
    return np.fft.irfft(spec, n=N).astype(np.float32)


# ---------------------------------------------------------------------------
# extract_audio_segment
# ---------------------------------------------------------------------------


class TestExtractAudioSegment(unittest.TestCase):
    def test_parse_f32le_bytes_correctly(self):
        # 100 samples float32
        samples = np.array([0.1, -0.2, 0.3, -0.4] * 25, dtype="<f4")
        fake_stdout = samples.tobytes()
        with patch(
            "cinesort.domain.perceptual.spectral_analysis.tracked_run",
            return_value=_fake_completed(stdout=fake_stdout),
        ):
            out = extract_audio_segment("/tmp/ffmpeg", "/tmp/movie.mkv", 0)
        self.assertIsNotNone(out)
        self.assertEqual(len(out), 100)
        np.testing.assert_allclose(out, samples, atol=1e-6)

    def test_ffmpeg_error_returns_none(self):
        with patch(
            "cinesort.domain.perceptual.spectral_analysis.tracked_run",
            return_value=_fake_completed(returncode=1, stderr=b"error"),
        ):
            self.assertIsNone(extract_audio_segment("/tmp/ffmpeg", "/tmp/x", 0))

    def test_timeout_returns_none(self):
        with patch(
            "cinesort.domain.perceptual.spectral_analysis.tracked_run",
            side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=15),
        ):
            self.assertIsNone(extract_audio_segment("/tmp/ffmpeg", "/tmp/x", 0))

    def test_oserror_returns_none(self):
        with patch(
            "cinesort.domain.perceptual.spectral_analysis.tracked_run",
            side_effect=OSError("no ffmpeg"),
        ):
            self.assertIsNone(extract_audio_segment("/tmp/ffmpeg", "/tmp/x", 0))

    def test_empty_stdout_returns_none(self):
        with patch(
            "cinesort.domain.perceptual.spectral_analysis.tracked_run",
            return_value=_fake_completed(stdout=b""),
        ):
            self.assertIsNone(extract_audio_segment("/tmp/ffmpeg", "/tmp/x", 0))


# ---------------------------------------------------------------------------
# compute_spectrogram
# ---------------------------------------------------------------------------


class TestComputeSpectrogram(unittest.TestCase):
    def test_sine_wave_1000hz_peak_at_1000(self):
        sr = 48000
        samples = _sine_wave(1000.0, sr, duration_s=1.0)
        spec = compute_spectrogram(samples, window_size=4096)
        self.assertEqual(spec.shape, (4096 // 2 + 1,))
        # Bin correspondant a 1000 Hz : 1000 / (sr/2 / (N-1)) = 1000 / 11.72 ~ 85
        peak_bin = int(np.argmax(spec))
        freq_res = (sr / 2) / (len(spec) - 1)
        peak_freq = peak_bin * freq_res
        self.assertAlmostEqual(peak_freq, 1000.0, delta=100.0)

    def test_silence_low_magnitude(self):
        sr = 48000
        samples = np.zeros(sr, dtype=np.float32)
        spec = compute_spectrogram(samples, window_size=4096)
        self.assertLess(float(spec.max()), 1e-6)

    def test_short_input_returns_empty(self):
        samples = np.zeros(100, dtype=np.float32)
        spec = compute_spectrogram(samples, window_size=4096)
        self.assertEqual(spec.size, 0)

    def test_shape_is_window_half_plus_one(self):
        sr = 48000
        samples = _sine_wave(500.0, sr, 0.5)
        spec = compute_spectrogram(samples, window_size=2048)
        self.assertEqual(spec.size, 2048 // 2 + 1)


# ---------------------------------------------------------------------------
# find_cutoff_hz
# ---------------------------------------------------------------------------


class TestFindCutoffHz(unittest.TestCase):
    def test_pure_tone_10k_cutoff_near_10k(self):
        sr = 48000
        samples = _sine_wave(10000.0, sr, 1.0)
        spec = compute_spectrogram(samples)
        cutoff = find_cutoff_hz(spec, sr)
        self.assertAlmostEqual(cutoff, 10000.0, delta=300.0)

    def test_low_pass_filtered_at_16k(self):
        sr = 48000
        # Bruit blanc borne par un low-pass a 16 kHz
        rng = np.random.default_rng(42)
        noise = rng.standard_normal(sr).astype(np.float32) * 0.3
        filtered = _low_pass_cutoff(noise, sr, 16000.0)
        spec = compute_spectrogram(filtered)
        cutoff = find_cutoff_hz(spec, sr, rolloff_pct=0.85)
        # Avec un low-pass dur a 16k, le rolloff 85% doit etre bien en dessous
        self.assertLess(cutoff, 17000.0)
        self.assertGreater(cutoff, 5000.0)

    def test_broadband_noise_cutoff_near_rolloff(self):
        sr = 48000
        rng = np.random.default_rng(123)
        noise = rng.standard_normal(sr).astype(np.float32) * 0.2
        spec = compute_spectrogram(noise)
        cutoff = find_cutoff_hz(spec, sr, rolloff_pct=0.85)
        # Bruit blanc -> spectre plat -> rolloff 85% ~ 0.85 * 24000 = 20400
        self.assertAlmostEqual(cutoff, 20400.0, delta=2000.0)

    def test_empty_spec_returns_zero(self):
        self.assertEqual(find_cutoff_hz(np.zeros(0), 48000), 0.0)

    def test_zero_spec_returns_zero(self):
        self.assertEqual(find_cutoff_hz(np.zeros(100), 48000), 0.0)


# ---------------------------------------------------------------------------
# compute_rms_db
# ---------------------------------------------------------------------------


class TestComputeRmsDb(unittest.TestCase):
    def test_sine_amp_one_is_about_minus_3db(self):
        # RMS d'une sine pure d'amplitude 1.0 = 1/sqrt(2) -> -3 dB
        samples = _sine_wave(1000.0, 48000, 1.0, amp=1.0)
        self.assertAlmostEqual(compute_rms_db(samples), -3.0, delta=0.5)

    def test_silence_returns_minus_inf(self):
        samples = np.zeros(1000, dtype=np.float32)
        self.assertEqual(compute_rms_db(samples), float("-inf"))

    def test_half_amplitude_minus_9db(self):
        samples = _sine_wave(1000.0, 48000, 1.0, amp=0.5)
        # 0.5 amp sine: RMS = 0.5/sqrt(2) -> ~-9 dB
        self.assertAlmostEqual(compute_rms_db(samples), -9.0, delta=0.5)

    def test_empty_returns_minus_inf(self):
        self.assertEqual(compute_rms_db(np.zeros(0)), float("-inf"))


# ---------------------------------------------------------------------------
# classify_cutoff
# ---------------------------------------------------------------------------


class TestClassifyCutoff(unittest.TestCase):
    def test_silent_overrides(self):
        v, c = classify_cutoff(20000.0, rms_db=-60.0, codec="flac", sample_rate=48000)
        self.assertEqual(v, "silent_segment")

    def test_he_aac_ambiguous(self):
        v, c = classify_cutoff(22000.0, rms_db=-20.0, codec="HE-AAC", sample_rate=48000)
        self.assertEqual(v, "lossy_ambiguous_sbr")

    def test_he_aac_variants(self):
        for codec in ("he-aac", "HE_AAC", "heaac", "aac_he_v2"):
            v, _ = classify_cutoff(22000.0, rms_db=-20.0, codec=codec, sample_rate=48000)
            self.assertEqual(v, "lossy_ambiguous_sbr", codec)

    def test_22050_sr_native_nyquist(self):
        v, c = classify_cutoff(11000.0, rms_db=-20.0, codec="aac", sample_rate=22050)
        self.assertEqual(v, "lossless_native_nyquist")

    def test_22k_flac_lossless(self):
        v, c = classify_cutoff(22000.0, rms_db=-20.0, codec="flac", sample_rate=48000)
        self.assertEqual(v, "lossless")

    def test_20k_lossy_high(self):
        v, c = classify_cutoff(20000.0, rms_db=-20.0, codec="ac3", sample_rate=48000)
        self.assertEqual(v, "lossy_high")

    def test_classic_film_vintage_master(self):
        v, c = classify_cutoff(19700.0, rms_db=-20.0, codec="flac", sample_rate=48000, film_era="classic_film")
        self.assertEqual(v, "lossless_vintage_master")

    def test_digital_era_no_vintage_tolerance(self):
        v, c = classify_cutoff(19700.0, rms_db=-20.0, codec="flac", sample_rate=48000, film_era="digital")
        self.assertEqual(v, "lossy_high")

    def test_17k_lossy_mid(self):
        v, c = classify_cutoff(17000.0, rms_db=-20.0, codec="aac", sample_rate=48000)
        self.assertEqual(v, "lossy_mid")

    def test_15k_lossy_low(self):
        v, c = classify_cutoff(15000.0, rms_db=-20.0, codec="mp3", sample_rate=48000)
        self.assertEqual(v, "lossy_low")

    def test_confidence_in_range(self):
        for cutoff in (22000, 20000, 17000, 15000):
            _, c = classify_cutoff(cutoff, -20.0, "aac", 48000)
            self.assertGreaterEqual(c, 0.0)
            self.assertLessEqual(c, 1.0)


# ---------------------------------------------------------------------------
# analyze_spectral integration (mocks)
# ---------------------------------------------------------------------------


class TestAnalyzeSpectralMocked(unittest.TestCase):
    def test_end_to_end_lossless_like_signal(self):
        sr = 48000
        # Bruit blanc fait "lossless" : cutoff proche de Nyquist
        rng = np.random.default_rng(1)
        samples = rng.standard_normal(sr * 5).astype(np.float32) * 0.3
        with patch(
            "cinesort.domain.perceptual.spectral_analysis.extract_audio_segment",
            return_value=samples,
        ):
            result = analyze_spectral(
                "/tmp/ffmpeg",
                "/tmp/x.mkv",
                0,
                duration_total_s=7200.0,
                codec="flac",
                sample_rate=48000,
            )
        self.assertIsInstance(result, SpectralResult)
        # Bruit blanc 85% rolloff ~ 20400 Hz -> lossy_high ou lossless
        self.assertIn(result.lossy_verdict, ("lossless", "lossy_high", "lossless_native_nyquist"))

    def test_end_to_end_silent_returns_silent(self):
        samples = np.zeros(48000 * 5, dtype=np.float32)
        with patch(
            "cinesort.domain.perceptual.spectral_analysis.extract_audio_segment",
            return_value=samples,
        ):
            result = analyze_spectral("/tmp/ffmpeg", "/tmp/x.mkv", 0, duration_total_s=7200)
        self.assertEqual(result.lossy_verdict, "silent_segment")

    def test_extract_fails_returns_error(self):
        with patch(
            "cinesort.domain.perceptual.spectral_analysis.extract_audio_segment",
            return_value=None,
        ):
            result = analyze_spectral("/tmp/ffmpeg", "/tmp/x.mkv", 0, duration_total_s=7200)
        self.assertEqual(result.lossy_verdict, "error")

    def test_low_pass_16k_detected_as_lossy_mid(self):
        sr = 48000
        rng = np.random.default_rng(2)
        noise = rng.standard_normal(sr * 5).astype(np.float32) * 0.3
        filtered = _low_pass_cutoff(noise, sr, 16000.0)
        with patch(
            "cinesort.domain.perceptual.spectral_analysis.extract_audio_segment",
            return_value=filtered,
        ):
            result = analyze_spectral(
                "/tmp/ffmpeg", "/tmp/x.mkv", 0, duration_total_s=7200, codec="mp3", sample_rate=48000
            )
        # Le rolloff 85% sur un signal dur-coupe a 16k tombera nettement en dessous
        self.assertIn(result.lossy_verdict, ("lossy_mid", "lossy_low"))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestSettingDefaults(unittest.TestCase):
    def setUp(self):
        import cinesort.ui.api.cinesort_api as backend

        self._tmp = tempfile.mkdtemp(prefix="cinesort_spec_")
        self._root = Path(self._tmp) / "root"
        self._sd = Path(self._tmp) / "state"
        self._root.mkdir()
        self._sd.mkdir()
        self.api = backend.CineSortApi()
        self.api._state_dir = self._sd

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _save(self, extra):
        base = {"root": str(self._root), "state_dir": str(self._sd)}
        base.update(extra)
        return self.api.save_settings(base)

    def test_default_enabled(self):
        s = self.api.get_settings()
        self.assertTrue(s.get("perceptual_audio_spectral_enabled"))

    def test_roundtrip_false(self):
        self._save({"perceptual_audio_spectral_enabled": False})
        s = self.api.get_settings()
        self.assertFalse(s.get("perceptual_audio_spectral_enabled"))


# ---------------------------------------------------------------------------
# Store roundtrip (migration 016)
# ---------------------------------------------------------------------------


class TestStoreRoundtrip(unittest.TestCase):
    def test_upsert_and_get_preserves_spectral_fields(self):
        from cinesort.infra.db.sqlite_store import SQLiteStore

        tmp = tempfile.mkdtemp(prefix="cinesort_specdb_")
        try:
            db_path = Path(tmp) / "db" / "test.sqlite"
            store = SQLiteStore(db_path)
            store.initialize()
            store.upsert_perceptual_report(
                run_id="run1",
                row_id="row1",
                visual_score=80,
                audio_score=75,
                global_score=78,
                global_tier="excellent",
                metrics={"foo": "bar"},
                settings_used={},
                spectral_cutoff_hz=20500.5,
                lossy_verdict="lossy_high",
            )
            got = store.get_perceptual_report(run_id="run1", row_id="row1")
            self.assertIsNotNone(got)
            self.assertAlmostEqual(got.get("spectral_cutoff_hz"), 20500.5, places=1)
            self.assertEqual(got.get("lossy_verdict"), "lossy_high")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Model serialization
# ---------------------------------------------------------------------------


class TestAudioPerceptualSerialization(unittest.TestCase):
    def test_to_dict_contains_spectral_block(self):
        from cinesort.domain.perceptual.models import AudioPerceptual

        ap = AudioPerceptual()
        ap.spectral_cutoff_hz = 21500.0
        ap.lossy_verdict = "lossless"
        ap.lossy_confidence = 0.92
        d = ap.to_dict()
        self.assertIn("spectral", d)
        self.assertAlmostEqual(d["spectral"]["cutoff_hz"], 21500.0, places=1)
        self.assertEqual(d["spectral"]["lossy_verdict"], "lossless")


# ---------------------------------------------------------------------------
# CineSort.spec
# ---------------------------------------------------------------------------


class TestSpecContainsSpectralAnalysis(unittest.TestCase):
    def test_hiddenimport_module(self):
        spec = (Path(__file__).resolve().parents[1] / "CineSort.spec").read_text(encoding="utf-8")
        self.assertIn("cinesort.domain.perceptual.spectral_analysis", spec)

    def test_hiddenimport_numpy(self):
        spec = (Path(__file__).resolve().parents[1] / "CineSort.spec").read_text(encoding="utf-8")
        self.assertIn("numpy", spec)


if __name__ == "__main__":
    unittest.main()
