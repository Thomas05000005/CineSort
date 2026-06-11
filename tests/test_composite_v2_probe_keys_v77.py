"""GATE AUDIT 2026-06-10 (REAL 2/2) — composite_score_v2 lit les BONNES cles du
probe normalise.

- _score_hdr lisait has_hdr10/has_dv/has_hdr10_plus alors que le probe expose
  hdr10/hdr_dolby_vision/hdr10_plus -> tout HDR10/DV score comme SDR (60/0.3).
- La regle fake-lossless lisait `audio` alors que la cle est `audio_tracks` ->
  has_lossless_codec toujours False, malus jamais applique.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from cinesort.domain.perceptual.composite_score_v2 import (
    _score_hdr,
    apply_contextual_adjustments,
)
from cinesort.domain.perceptual.models import SubScore


class ScoreHdrKeysTests(unittest.TestCase):
    def _video(self):
        return SimpleNamespace(has_hdr10_plus_detected=False)

    def test_hdr10_scored_as_hdr_not_sdr(self) -> None:
        probe = {"video": {"hdr10": True, "max_cll": 1000, "max_fall": 400}}
        value, conf, _flags = _score_hdr(self._video(), probe)
        self.assertGreaterEqual(value, 75.0, "HDR10 doit etre score HDR, pas SDR (60)")
        self.assertEqual(conf, 1.0)

    def test_dolby_vision_detected(self) -> None:
        probe = {"video": {"hdr_dolby_vision": True, "dv_profile": "5"}}
        value, conf, _flags = _score_hdr(self._video(), probe)
        self.assertEqual(value, 80.0)  # DV5
        self.assertEqual(conf, 1.0)

    def test_sdr_still_neutral(self) -> None:
        probe = {"video": {"hdr10": False}}
        value, conf, _flags = _score_hdr(self._video(), probe)
        self.assertEqual(value, 60.0)
        self.assertEqual(conf, 0.3)

    def test_old_keys_no_longer_trigger_hdr(self) -> None:
        # Les anciennes (mauvaises) cles ne doivent PLUS declencher HDR.
        probe = {"video": {"has_hdr10": True, "has_dv": True}}
        value, conf, _flags = _score_hdr(self._video(), probe)
        self.assertEqual(value, 60.0)  # SDR car has_* ne sont pas les vraies cles


class FakeLosslessAudioTracksTests(unittest.TestCase):
    def _audio_subs(self):
        return [SubScore(name="spectral_cutoff", value=40.0, weight=1.0, confidence=1.0, label_fr="Coupe")]

    def test_fake_lossless_fires_with_audio_tracks_key(self) -> None:
        probe = {"audio_tracks": [{"codec": "flac"}]}
        _v, audio_out, _trace = apply_contextual_adjustments(
            [], self._audio_subs(), None, probe, None, None, [], False, "modern",
        )
        sub = next(s for s in audio_out if s.name == "spectral_cutoff")
        # Le malus fake-lossless a ete applique -> value < 40 (valeur initiale).
        self.assertLess(sub.value, 40.0, "malus fake-lossless non applique")

    def test_old_audio_key_no_longer_fires(self) -> None:
        # Avec l'ancienne cle `audio`, audio_tracks serait vide -> pas de malus.
        probe = {"audio": [{"codec": "flac"}]}
        _v, audio_out, _trace = apply_contextual_adjustments(
            [], self._audio_subs(), None, probe, None, None, [], False, "modern",
        )
        sub = next(s for s in audio_out if s.name == "spectral_cutoff")
        self.assertEqual(sub.value, 40.0, "pas de malus si la cle audio_tracks est absente")


if __name__ == "__main__":
    unittest.main()
