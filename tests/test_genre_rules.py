"""P4.2 : tests pour le scoring genre-aware."""

from __future__ import annotations

import unittest

from cinesort.domain.genre_rules import (
    adjust_bitrate_threshold,
    canonical_genre,
    compute_genre_adjustments,
    detect_primary_genre,
    get_genre_rules,
)


class CanonicalGenreTests(unittest.TestCase):
    def test_english_canonical(self):
        self.assertEqual(canonical_genre("Animation"), "animation")
        self.assertEqual(canonical_genre("Action"), "action")
        self.assertEqual(canonical_genre("Horror"), "horror")
        self.assertEqual(canonical_genre("Documentary"), "documentary")

    def test_french_aliases(self):
        self.assertEqual(canonical_genre("Comédie"), "comedy")
        self.assertEqual(canonical_genre("Horreur"), "horror")
        self.assertEqual(canonical_genre("Documentaire"), "documentary")

    def test_unknown_returns_none(self):
        self.assertIsNone(canonical_genre("Sci-Fi"))  # pas dans la table (intentionnel)
        self.assertIsNone(canonical_genre(""))
        self.assertIsNone(canonical_genre(None))  # type: ignore

    def test_case_insensitive(self):
        self.assertEqual(canonical_genre("ACTION"), "action")
        self.assertEqual(canonical_genre("horror"), "horror")


class DetectPrimaryGenreTests(unittest.TestCase):
    def test_single_genre(self):
        self.assertEqual(detect_primary_genre(["Action"]), "action")

    def test_priority_animation_over_action(self):
        # Animation a la priorité sur Action dans un film d'animation d'action
        self.assertEqual(detect_primary_genre(["Action", "Animation"]), "animation")

    def test_priority_horror_over_thriller(self):
        self.assertEqual(detect_primary_genre(["Thriller", "Horror"]), "horror")

    def test_priority_action_over_drama(self):
        self.assertEqual(detect_primary_genre(["Drama", "Action"]), "action")

    def test_empty_returns_none(self):
        self.assertIsNone(detect_primary_genre([]))
        self.assertIsNone(detect_primary_genre(None))

    def test_unknown_genres_return_none(self):
        self.assertIsNone(detect_primary_genre(["Sci-Fi"]))

    def test_mixed_known_unknown(self):
        self.assertEqual(detect_primary_genre(["Sci-Fi", "Thriller"]), "thriller")


class GetGenreRulesTests(unittest.TestCase):
    def test_animation_has_leniency_below_1(self):
        r = get_genre_rules("animation")
        self.assertIsNotNone(r)
        assert r is not None
        self.assertLess(r["bitrate_leniency"], 1.0)

    def test_action_has_leniency_above_1(self):
        r = get_genre_rules("action")
        self.assertIsNotNone(r)
        assert r is not None
        self.assertGreater(r["bitrate_leniency"], 1.0)

    def test_horror_has_hdr_bonus(self):
        r = get_genre_rules("horror")
        assert r is not None
        self.assertGreater(r["hdr_bonus"], 0)

    def test_unknown_returns_none(self):
        self.assertIsNone(get_genre_rules(None))
        self.assertIsNone(get_genre_rules("sci-fi"))


class ComputeGenreAdjustmentsTests(unittest.TestCase):
    def test_no_genre_returns_zero(self):
        total, factors = compute_genre_adjustments(None, video_codec="hevc", height=2160, has_hdr=True, has_atmos=True)
        self.assertEqual(total, 0.0)
        self.assertEqual(factors, [])

    def test_animation_hevc_gets_modern_bonus(self):
        total, factors = compute_genre_adjustments(
            "animation", video_codec="hevc", height=1080, has_hdr=False, has_atmos=False
        )
        self.assertGreater(total, 0)
        # Au moins un factor doit mentionner le codec
        labels = " ".join(f["label"].lower() for f in factors)
        self.assertIn("codec", labels)

    def test_action_hdr_atmos_gets_bonuses(self):
        total, factors = compute_genre_adjustments(
            "action", video_codec="hevc", height=2160, has_hdr=True, has_atmos=True
        )
        self.assertGreaterEqual(total, 6)  # hdr_bonus 3 + atmos_bonus 3
        labels = " ".join(f["label"].lower() for f in factors)
        self.assertIn("hdr", labels)
        self.assertIn("immersif", labels)

    def test_horror_hdr_gives_big_bonus(self):
        total, factors = compute_genre_adjustments(
            "horror", video_codec="h264", height=2160, has_hdr=True, has_atmos=False
        )
        self.assertGreaterEqual(total, 4)  # horror hdr_bonus 4

    def test_animation_grain_penalty(self):
        total, factors = compute_genre_adjustments(
            "animation", video_codec="h264", height=1080, has_hdr=False, has_atmos=False, has_heavy_grain=True
        )
        # Grain en animation → malus
        self.assertLessEqual(total, -5)

    def test_documentary_720p_barely_penalized(self):
        total, factors = compute_genre_adjustments(
            "documentary", video_codec="h264", height=720, has_hdr=False, has_atmos=False
        )
        # Documentary tolère le 720p (malus -1 seulement)
        self.assertEqual(total, -1)

    def test_action_720p_heavily_penalized(self):
        total, factors = compute_genre_adjustments(
            "action", video_codec="h264", height=720, has_hdr=False, has_atmos=False
        )
        # Action en 720p → malus -5
        self.assertEqual(total, -5)

    def test_factors_have_standard_format(self):
        _, factors = compute_genre_adjustments("action", video_codec="hevc", height=2160, has_hdr=True, has_atmos=True)
        for f in factors:
            self.assertIn("category", f)
            self.assertIn("delta", f)
            self.assertIn("label", f)


class AdjustBitrateThresholdTests(unittest.TestCase):
    def test_animation_reduces_threshold(self):
        # Animation multiplier 0.75 → seuil 10000 → 7500
        self.assertEqual(adjust_bitrate_threshold(10000, "animation"), 7500)

    def test_action_increases_threshold(self):
        # Action multiplier 1.15 → seuil 10000 → 11500
        self.assertEqual(adjust_bitrate_threshold(10000, "action"), 11500)

    def test_unknown_genre_unchanged(self):
        self.assertEqual(adjust_bitrate_threshold(10000, None), 10000)
        self.assertEqual(adjust_bitrate_threshold(10000, "unknown_genre"), 10000)


if __name__ == "__main__":
    unittest.main()
