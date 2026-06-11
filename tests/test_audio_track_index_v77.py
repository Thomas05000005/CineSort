"""GATE AUDIT 2026-06-10 (REAL 2/2) — l'index passe a `-map 0:a:N` est l'index
audio-RELATIF, pas l'index absolu du conteneur.

Avant : best["index"] (absolu : video=0, audio=1...) etait utilise tel quel ->
`-map 0:a:1` sur un film a 1 piste audio ne matche aucun flux ->
loudnorm/astats/clipping/fingerprint echouent tous silencieusement.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cinesort.domain.perceptual import audio_perceptual


class AudioTrackIndexTests(unittest.TestCase):
    def _run_and_capture_idx(self, audio_tracks):
        captured = {}

        def _fake_loudnorm(ffmpeg_path, media_path, idx, timeout_s=60.0):
            captured["idx"] = idx
            return None

        with patch.object(audio_perceptual, "analyze_loudnorm", side_effect=_fake_loudnorm), \
             patch.object(audio_perceptual, "analyze_astats", return_value=None), \
             patch.object(audio_perceptual, "analyze_clipping_segments", return_value=None):
            audio_perceptual.analyze_audio_perceptual(
                "ffmpeg", "movie.mkv", audio_tracks,
                audio_deep=False, enable_fingerprint=False, enable_spectral=False, enable_mel=False,
            )
        return captured.get("idx")

    def test_single_audio_track_uses_relative_index_zero(self) -> None:
        # 1 piste audio a l'index ABSOLU 1 (video=0) -> -map 0:a:0
        idx = self._run_and_capture_idx([{"index": 1, "codec": "aac", "channels": 2}])
        self.assertEqual(idx, 0, "doit etre l'index audio-relatif 0, pas l'absolu 1")

    def test_second_audio_track_relative_index_one(self) -> None:
        # 2 pistes audio (absolus 1 et 2) ; la meilleure (truehd, absolu 2) -> 0:a:1
        tracks = [
            {"index": 1, "codec": "aac", "channels": 2},
            {"index": 2, "codec": "truehd", "channels": 8},
        ]
        idx = self._run_and_capture_idx(tracks)
        self.assertEqual(idx, 1)

    def test_track_index_attribute_keeps_absolute(self) -> None:
        with patch.object(audio_perceptual, "analyze_loudnorm", return_value=None), \
             patch.object(audio_perceptual, "analyze_astats", return_value=None), \
             patch.object(audio_perceptual, "analyze_clipping_segments", return_value=None):
            res = audio_perceptual.analyze_audio_perceptual(
                "ffmpeg", "movie.mkv", [{"index": 1, "codec": "aac", "channels": 2}],
                audio_deep=False, enable_fingerprint=False, enable_spectral=False, enable_mel=False,
            )
        self.assertEqual(res.track_index, 1, "track_index garde l'index absolu (identite)")


if __name__ == "__main__":
    unittest.main()
