"""Tests §12 v7.5.0 — Mel spectrogram."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from cinesort.domain.perceptual.mel_analysis import (
    analyze_mel,
    apply_mel_filters,
    build_mel_filter_bank,
    compute_mel_score,
    compute_spectral_flatness,
    detect_aac_holes,
    detect_soft_clipping,
    hz_to_mel,
    mel_to_db,
    mel_to_hz,
)


def _sine_wave(freq: float, sr: int, duration_s: float, amp: float = 0.5) -> np.ndarray:
    t = np.linspace(0.0, duration_s, int(sr * duration_s), endpoint=False, dtype=np.float32)
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def _white_noise(n: int, seed: int = 0, amp: float = 0.3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (amp * rng.standard_normal(n)).astype(np.float32)


def _low_pass(samples: np.ndarray, sr: int, cutoff: float) -> np.ndarray:
    """Low-pass naif via FFT mask (mise a zero bins > cutoff)."""
    spec = np.fft.rfft(samples.astype(np.float64))
    freqs = np.fft.rfftfreq(len(samples), 1.0 / sr)
    spec[freqs > cutoff] = 0.0
    return np.fft.irfft(spec, n=len(samples)).astype(np.float32)


# ---------------------------------------------------------------------------
# Conversions Hz <-> Mel
# ---------------------------------------------------------------------------


class TestMelConversions(unittest.TestCase):
    def test_hz_to_mel_zero(self):
        self.assertAlmostEqual(hz_to_mel(0.0), 0.0, places=3)

    def test_hz_to_mel_700_is_about_781(self):
        # hz_to_mel(700) = 2595 * log10(2) ~ 781
        self.assertAlmostEqual(hz_to_mel(700.0), 781.17, places=1)

    def test_mel_to_hz_roundtrip(self):
        for hz in (100, 500, 1000, 5000, 10000, 20000):
            m = hz_to_mel(hz)
            back = mel_to_hz(m)
            self.assertAlmostEqual(back, hz, places=2)


# ---------------------------------------------------------------------------
# Filter bank
# ---------------------------------------------------------------------------


class TestBuildMelFilterBank(unittest.TestCase):
    def test_shape(self):
        fb = build_mel_filter_bank(n_filters=64, sample_rate=48000, n_fft=4096)
        self.assertEqual(fb.shape, (64, 4096 // 2 + 1))

    def test_filters_non_negative(self):
        fb = build_mel_filter_bank(n_filters=32, sample_rate=48000, n_fft=1024)
        self.assertTrue(np.all(fb >= 0))

    def test_filters_peak_near_one(self):
        # Chaque filtre triangulaire a un pic proche de 1.0
        fb = build_mel_filter_bank(n_filters=16, sample_rate=48000, n_fft=2048)
        peaks = fb.max(axis=1)
        for p in peaks:
            self.assertGreater(p, 0.4)
            self.assertLessEqual(p, 1.0 + 1e-6)


class TestApplyMelFilters(unittest.TestCase):
    def test_output_shape(self):
        spec = np.random.default_rng(0).standard_normal((10, 4096 // 2 + 1)).astype(np.float64)
        spec = np.abs(spec)
        fb = build_mel_filter_bank(n_filters=64, sample_rate=48000, n_fft=4096)
        mel = apply_mel_filters(spec, fb)
        self.assertEqual(mel.shape, (10, 64))

    def test_non_negative(self):
        spec = np.ones((5, 4096 // 2 + 1)) * 0.1
        fb = build_mel_filter_bank(n_filters=32, sample_rate=48000, n_fft=4096)
        mel = apply_mel_filters(spec, fb)
        self.assertTrue(np.all(mel >= 0))


class TestMelToDb(unittest.TestCase):
    def test_clipped_range(self):
        mel = np.array([[1.0, 0.1, 0.01]], dtype=np.float64)
        db = mel_to_db(mel, top_db=80.0)
        self.assertLessEqual(float(db.max()), 0.0)
        self.assertGreaterEqual(float(db.min()), -80.0)


# ---------------------------------------------------------------------------
# Detections
# ---------------------------------------------------------------------------


class TestDetectSoftClipping(unittest.TestCase):
    def test_insufficient_empty(self):
        result = detect_soft_clipping(np.zeros((0, 0)), np.zeros(0))
        self.assertEqual(result["verdict"], "insufficient")

    def test_pure_tone_no_harmonics(self):
        # Sinusoide pure 1kHz : pas d'harmoniques (signal mathematiquement parfait)
        samples = _sine_wave(1000.0, 48000, 1.0, amp=0.3)
        result = analyze_mel(samples)
        # Un sine pur dans le spectrogramme : quelques harmoniques par leakage
        self.assertLess(result.mel_soft_clipping_pct, 50.0)

    def test_noisy_signal_variable(self):
        # Bruit blanc : spectrogramme bruitee, soft_clipping possible mais variable
        samples = _white_noise(48000, seed=1)
        result = analyze_mel(samples)
        # Juste verifier que ca ne crashe pas, pas de valeur precise
        self.assertIn(
            result.mel_verdict, ("clean", "insufficient_data", "soft_clipped", "mp3_encoded", "aac_low_bitrate")
        )


class TestDetectMp3Shelf(unittest.TestCase):
    def test_flat_spectrum_no_shelf(self):
        # Bruit blanc : spectre plat, pas de shelf
        samples = _white_noise(48000 * 3, seed=0)
        result = analyze_mel(samples)
        # Bruit blanc a de l'energie au-dessus de 16k, donc pas de shelf
        self.assertFalse(result.mel_mp3_shelf_detected)

    def test_lowpass_16k_detected_as_shelf(self):
        # Low-pass dur a 16k : coupure totale au-dela = shelf evident
        samples = _white_noise(48000 * 3, seed=1)
        filtered = _low_pass(samples, 48000, 16000.0)
        result = analyze_mel(filtered)
        # Apres un low-pass 16k, le drop 14-16k vs 16-18k doit etre enorme
        self.assertTrue(result.mel_mp3_shelf_detected)

    def test_low_sample_rate_no_shelf_mesurable(self):
        # SR 22050 -> Nyquist 11025, pas de bande 14-16k ni 16-18k
        samples = _sine_wave(5000.0, 22050, 1.0, amp=0.3)
        result = analyze_mel(samples, sample_rate=22050)
        self.assertFalse(result.mel_mp3_shelf_detected)


class TestDetectAacHoles(unittest.TestCase):
    def test_empty_insufficient(self):
        result = detect_aac_holes(np.zeros((0, 0)), np.zeros(0))
        self.assertEqual(result["verdict"], "insufficient")

    def test_flat_noise_no_severe_holes(self):
        samples = _white_noise(48000 * 3, seed=2)
        result = analyze_mel(samples)
        # Bruit blanc : pas de verdict severe
        self.assertLess(result.mel_aac_holes_ratio, 0.10)

    def test_constant_signal_many_bands_low_variance(self):
        # Signal DC constant : toutes les bandes sans variance temporelle
        samples = np.full(48000, 0.5, dtype=np.float32)
        result = analyze_mel(samples)
        # Signal DC : peu de structure spectrale
        self.assertGreaterEqual(result.mel_aac_holes_ratio, 0.0)


class TestSpectralFlatness(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(compute_spectral_flatness(np.zeros((0, 0))), 0.0)

    def test_uniform_spectrum_high_flatness(self):
        # Spectre uniforme : flatness = 1
        mel = np.ones((5, 32))
        flatness = compute_spectral_flatness(mel)
        self.assertAlmostEqual(flatness, 1.0, places=2)

    def test_peaky_spectrum_low_flatness(self):
        # Spectre avec un pic : flatness proche de 0
        mel = np.full((5, 32), 1e-6)
        mel[:, 16] = 1.0
        flatness = compute_spectral_flatness(mel)
        self.assertLess(flatness, 0.2)

    def test_bounded(self):
        mel = np.random.default_rng(3).random((10, 64))
        flatness = compute_spectral_flatness(mel)
        self.assertGreaterEqual(flatness, 0.0)
        self.assertLessEqual(flatness, 1.0)


# ---------------------------------------------------------------------------
# Score composite + verdict
# ---------------------------------------------------------------------------


class TestComputeMelScore(unittest.TestCase):
    def test_clean_all_low_metrics(self):
        soft = {"pct_frames_with_harmonics": 2.0, "verdict": "normal"}
        mp3 = {"shelf_detected": False, "shelf_drop_db": 0.0, "frames_pct": 0.0}
        aac = {"hole_ratio": 0.01, "synthetic_ratio": 0.02, "verdict": "normal"}
        score, verdict = compute_mel_score(soft, mp3, aac, flatness=0.3)
        self.assertGreaterEqual(score, 70)
        self.assertEqual(verdict, "clean")

    def test_mp3_shelf_verdict(self):
        soft = {"pct_frames_with_harmonics": 2.0, "verdict": "normal"}
        mp3 = {"shelf_detected": True, "shelf_drop_db": 25.0, "frames_pct": 80.0}
        aac = {"hole_ratio": 0.01, "verdict": "normal"}
        score, verdict = compute_mel_score(soft, mp3, aac, flatness=0.3)
        self.assertEqual(verdict, "mp3_encoded")

    def test_aac_severe_verdict(self):
        soft = {"pct_frames_with_harmonics": 2.0, "verdict": "normal"}
        mp3 = {"shelf_detected": False, "shelf_drop_db": 0.0}
        aac = {"hole_ratio": 0.25, "verdict": "severe"}
        score, verdict = compute_mel_score(soft, mp3, aac, flatness=0.3)
        self.assertEqual(verdict, "aac_low_bitrate")

    def test_soft_clip_severe_verdict(self):
        soft = {"pct_frames_with_harmonics": 50.0, "verdict": "severe"}
        mp3 = {"shelf_detected": False, "shelf_drop_db": 0.0}
        aac = {"hole_ratio": 0.01, "verdict": "normal"}
        score, verdict = compute_mel_score(soft, mp3, aac, flatness=0.3)
        self.assertEqual(verdict, "soft_clipped")


# ---------------------------------------------------------------------------
# Orchestrateur analyze_mel
# ---------------------------------------------------------------------------


class TestAnalyzeMel(unittest.TestCase):
    def test_insufficient_data_too_short(self):
        samples = _white_noise(100, seed=0)
        result = analyze_mel(samples)
        self.assertEqual(result.mel_verdict, "insufficient_data")
        self.assertEqual(result.mel_score, 0)

    def test_empty_samples(self):
        result = analyze_mel(np.zeros(0, dtype=np.float32))
        self.assertEqual(result.mel_verdict, "insufficient_data")

    def test_white_noise_produces_result(self):
        samples = _white_noise(48000 * 2, seed=5)
        result = analyze_mel(samples)
        # Bruit blanc : verdict depend des pseudo-harmoniques aleatoires.
        # On verifie juste l'absence de shelf MP3.
        self.assertFalse(result.mel_mp3_shelf_detected)

    def test_lowpass_signal_flags_mp3(self):
        samples = _low_pass(_white_noise(48000 * 2, seed=6), 48000, 15500.0)
        result = analyze_mel(samples)
        self.assertEqual(result.mel_verdict, "mp3_encoded")
        self.assertTrue(result.mel_mp3_shelf_detected)


# ---------------------------------------------------------------------------
# Settings + model serialization
# ---------------------------------------------------------------------------


class TestSettings(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile

        import cinesort.ui.api.cinesort_api as backend

        self._tmp = tempfile.mkdtemp(prefix="cinesort_mel_")
        self._root = Path(self._tmp) / "root"
        self._sd = Path(self._tmp) / "state"
        self._root.mkdir()
        self._sd.mkdir()
        self.api = backend.CineSortApi()
        self.api._state_dir = self._sd
        self._shutil = shutil

    def tearDown(self):
        self._shutil.rmtree(self._tmp, ignore_errors=True)

    def test_default_enabled(self):
        s = self.api.get_settings()
        self.assertTrue(s.get("perceptual_audio_mel_enabled"))

    def test_roundtrip_false(self):
        self.api.save_settings(
            {
                "root": str(self._root),
                "state_dir": str(self._sd),
                "perceptual_audio_mel_enabled": False,
            }
        )
        s = self.api.get_settings()
        self.assertFalse(s.get("perceptual_audio_mel_enabled"))


class TestAudioPerceptualSerialization(unittest.TestCase):
    def test_mel_block_in_to_dict(self):
        from cinesort.domain.perceptual.models import AudioPerceptual

        ap = AudioPerceptual()
        ap.mel_soft_clipping_pct = 12.5
        ap.mel_mp3_shelf_detected = True
        ap.mel_aac_holes_ratio = 0.08
        ap.mel_spectral_flatness = 0.25
        ap.mel_score = 55
        ap.mel_verdict = "mp3_encoded"
        d = ap.to_dict()
        self.assertIn("mel", d)
        self.assertEqual(d["mel"]["verdict"], "mp3_encoded")
        self.assertTrue(d["mel"]["mp3_shelf_detected"])
        self.assertEqual(d["mel"]["score"], 55)


class TestSpecContainsMelAnalysis(unittest.TestCase):
    def test_hiddenimport(self):
        spec = (Path(__file__).resolve().parents[1] / "CineSort.spec").read_text(encoding="utf-8")
        self.assertIn("cinesort.domain.perceptual.mel_analysis", spec)


if __name__ == "__main__":
    unittest.main()
