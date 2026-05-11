"""Tests pour les ameliorations scoring V4 (ere, encode warnings, commentary)."""

from __future__ import annotations

import unittest

from cinesort.domain.quality_score import compute_quality_score, default_quality_profile


def _base_probe(height=1080, codec="hevc", bitrate="15000", hdr="", audio_codec="ac3", channels=6):
    """Construit un normalized_probe minimal pour les tests."""
    return {
        "video": {
            "width": int(height * 16 / 9),
            "height": height,
            "codec": codec,
            "bitrate": str(bitrate),
            "bit_depth": 8,
            "hdr_format": hdr,
        },
        "audio_tracks": [
            {"codec": audio_codec, "channels": channels, "bitrate": "640", "language": "fra"},
        ],
        "sources": {},
        "probe_quality": "FULL",
    }


class EraContextTests(unittest.TestCase):
    """Tests pour le bonus/malus contexte ere."""

    def test_heritage_bonus(self):
        """Film 1950 en 1080p → score plus eleve."""
        profile = default_quality_profile()
        probe = _base_probe(height=1080)
        r_no_year = compute_quality_score(normalized_probe=probe, profile=profile)
        r_heritage = compute_quality_score(normalized_probe=probe, profile=profile, film_year=1950)
        self.assertGreater(r_heritage["score"], r_no_year["score"])

    def test_classic_bonus(self):
        """Film 1990 en 720p → bonus +4."""
        profile = default_quality_profile()
        probe = _base_probe(height=720, bitrate="5000")
        r_no_year = compute_quality_score(normalized_probe=probe, profile=profile)
        r_classic = compute_quality_score(normalized_probe=probe, profile=profile, film_year=1990)
        self.assertGreater(r_classic["score"], r_no_year["score"])

    def test_modern_penalty(self):
        """Film 2024 en 1080p (non AV1) → score plus bas."""
        profile = default_quality_profile()
        probe = _base_probe(height=1080)
        r_no_year = compute_quality_score(normalized_probe=probe, profile=profile)
        r_modern = compute_quality_score(normalized_probe=probe, profile=profile, film_year=2024)
        self.assertLess(r_modern["score"], r_no_year["score"])

    def test_modern_no_penalty_av1(self):
        """Film 2024 en 1080p AV1 → pas de malus."""
        profile = default_quality_profile()
        probe = _base_probe(height=1080, codec="av1")
        r_no_year = compute_quality_score(normalized_probe=probe, profile=profile)
        r_modern = compute_quality_score(normalized_probe=probe, profile=profile, film_year=2024)
        self.assertEqual(r_modern["score"], r_no_year["score"])

    def test_no_year_unchanged(self):
        """film_year=None → pas de bonus/malus."""
        profile = default_quality_profile()
        probe = _base_probe()
        r1 = compute_quality_score(normalized_probe=probe, profile=profile)
        r2 = compute_quality_score(normalized_probe=probe, profile=profile, film_year=None)
        self.assertEqual(r1["score"], r2["score"])


class EncodeWarningsTests(unittest.TestCase):
    """Tests pour la penalite encode warnings."""

    def test_upscale_penalty(self):
        profile = default_quality_profile()
        probe = _base_probe()
        r_clean = compute_quality_score(normalized_probe=probe, profile=profile)
        r_upscale = compute_quality_score(normalized_probe=probe, profile=profile, encode_warnings=["upscale_suspect"])
        self.assertLess(r_upscale["score"], r_clean["score"])

    def test_reencode_penalty(self):
        profile = default_quality_profile()
        probe = _base_probe()
        r_clean = compute_quality_score(normalized_probe=probe, profile=profile)
        r_reencode = compute_quality_score(
            normalized_probe=probe, profile=profile, encode_warnings=["reencode_degraded"]
        )
        self.assertLess(r_reencode["score"], r_clean["score"])

    def test_no_warnings_unchanged(self):
        profile = default_quality_profile()
        probe = _base_probe()
        r1 = compute_quality_score(normalized_probe=probe, profile=profile)
        r2 = compute_quality_score(normalized_probe=probe, profile=profile, encode_warnings=[])
        self.assertEqual(r1["score"], r2["score"])


class CommentaryOnlyTests(unittest.TestCase):
    """Tests pour la penalite commentary-only."""

    def test_commentary_only_penalty(self):
        profile = default_quality_profile()
        probe = _base_probe()
        r_clean = compute_quality_score(normalized_probe=probe, profile=profile)
        r_commentary = compute_quality_score(
            normalized_probe=probe,
            profile=profile,
            audio_analysis={"tracks_count": 1, "has_commentary": True},
        )
        self.assertLess(r_commentary["score"], r_clean["score"])

    def test_commentary_plus_normal_no_penalty(self):
        profile = default_quality_profile()
        probe = _base_probe()
        r_clean = compute_quality_score(normalized_probe=probe, profile=profile)
        r_mixed = compute_quality_score(
            normalized_probe=probe,
            profile=profile,
            audio_analysis={"tracks_count": 2, "has_commentary": True},
        )
        self.assertEqual(r_mixed["score"], r_clean["score"])


if __name__ == "__main__":
    unittest.main()
