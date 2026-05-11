"""Tests pour les criteres doublons enrichis V4 (perceptuel + sous-titres FR)."""

from __future__ import annotations

import unittest

from cinesort.domain.duplicate_compare import compare_duplicates


def _make_probe(height=1080, codec="hevc", bitrate=15000, audio_codec="ac3", channels=6, hdr=""):
    return {
        "video": {
            "width": int(height * 16 / 9),
            "height": height,
            "codec": codec,
            "bitrate": bitrate,
            "bit_depth": 8,
            "hdr_format": hdr,
        },
        "audio_tracks": [{"codec": audio_codec, "channels": channels, "bitrate": 640, "language": "fra"}],
        "duration_s": 7200,
        "file_size_bytes": 5_000_000_000,
    }


class PerceptualCriterionTests(unittest.TestCase):
    def test_perceptual_better_wins(self):
        """Fichier A perceptual=80, B=50 → A gagne le critere."""
        r = compare_duplicates(_make_probe(), _make_probe(), perceptual_score_a=80, perceptual_score_b=50)
        perc = [c for c in r.criteria if c.name == "perceptual"]
        self.assertEqual(len(perc), 1)
        self.assertGreater(perc[0].points_delta, 0)

    def test_perceptual_missing_no_crash(self):
        """Pas de scores perceptuels → critere absent."""
        r = compare_duplicates(_make_probe(), _make_probe())
        perc = [c for c in r.criteria if c.name == "perceptual"]
        self.assertEqual(len(perc), 0)

    def test_perceptual_one_missing(self):
        """Un seul score perceptuel → critere absent."""
        r = compare_duplicates(_make_probe(), _make_probe(), perceptual_score_a=80)
        perc = [c for c in r.criteria if c.name == "perceptual"]
        self.assertEqual(len(perc), 0)


class SubtitlesCriterionTests(unittest.TestCase):
    def test_subtitles_fr_a_wins(self):
        """A avec FR, B sans → A gagne +5."""
        r = compare_duplicates(_make_probe(), _make_probe(), subtitles_fr_a=True, subtitles_fr_b=False)
        subs = [c for c in r.criteria if c.name == "subtitles_fr"]
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0].points_delta, 5)

    def test_subtitles_both_no_criterion(self):
        """Les deux avec FR → pas de critere."""
        r = compare_duplicates(_make_probe(), _make_probe(), subtitles_fr_a=True, subtitles_fr_b=True)
        subs = [c for c in r.criteria if c.name == "subtitles_fr"]
        self.assertEqual(len(subs), 0)

    def test_subtitles_none_no_criterion(self):
        """Aucun avec FR → pas de critere."""
        r = compare_duplicates(_make_probe(), _make_probe(), subtitles_fr_a=False, subtitles_fr_b=False)
        subs = [c for c in r.criteria if c.name == "subtitles_fr"]
        self.assertEqual(len(subs), 0)


class ExistingCriteriaUnchangedTests(unittest.TestCase):
    def test_seven_base_criteria_present(self):
        """Les 7 criteres de base sont toujours presents."""
        r = compare_duplicates(_make_probe(), _make_probe())
        keys = [c.name for c in r.criteria]
        for expected in ["resolution", "hdr", "video_codec", "audio_codec", "audio_channels", "bitrate", "file_size"]:
            self.assertIn(expected, keys, f"Critere manquant: {expected}")


if __name__ == "__main__":
    unittest.main()
