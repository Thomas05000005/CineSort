"""Tests Phase 6.1 — score_runtime_delta edition-aware.

Couvre :
- Match parfait / acceptable / zone grise / mismatch franc
- Tolerance elargie pour Director's Cut / Extended Edition / Ultimate Cut
- Cas no-op (donnees manquantes, valeurs invalides, runtime nul)
"""

from __future__ import annotations

import unittest

from cinesort.domain.runtime_matching import (
    WARN_RUNTIME_MISMATCH,
    score_runtime_delta,
)


class ScoreRuntimeDeltaTests(unittest.TestCase):
    # --- Match parfait (delta < 3 min) ---

    def test_exact_match_returns_plus_20(self):
        bonus, warn = score_runtime_delta(148.0, 148, None)
        self.assertEqual(bonus, 20)
        self.assertIsNone(warn)

    def test_match_within_2_min_returns_plus_20(self):
        # Inception : fichier 146, TMDb 148 → +20
        bonus, warn = score_runtime_delta(146.0, 148, None)
        self.assertEqual(bonus, 20)
        self.assertIsNone(warn)

    # --- Match acceptable (delta < tolerance theatricale) ---

    def test_soft_match_theatrical_delta_4_returns_plus_10(self):
        bonus, warn = score_runtime_delta(144.0, 148, None)
        self.assertEqual(bonus, 10)
        self.assertIsNone(warn)

    def test_soft_match_at_tolerance_limit_returns_plus_10(self):
        # Delta = 4.5 min (sous le seuil 5 min)
        bonus, warn = score_runtime_delta(143.5, 148, None)
        self.assertEqual(bonus, 10)
        self.assertIsNone(warn)

    # --- Tolerance edition-aware ---

    def test_directors_cut_with_15min_delta_returns_plus_10(self):
        # Director's Cut tolerance = 15 min, delta = 14 → +10
        bonus, warn = score_runtime_delta(162.0, 148, "Director's Cut")
        self.assertEqual(bonus, 10)
        self.assertIsNone(warn)

    def test_extended_edition_with_12min_delta_returns_plus_10(self):
        bonus, warn = score_runtime_delta(160.0, 148, "Extended Edition")
        self.assertEqual(bonus, 10)
        self.assertIsNone(warn)

    def test_ultimate_cut_with_25min_delta_returns_zero_gray(self):
        # Hors tolerance edition (15 min) mais sous mismatch (30 min)
        bonus, warn = score_runtime_delta(173.0, 148, "Ultimate Cut")
        self.assertEqual(bonus, 0)
        self.assertIsNone(warn)

    def test_theatrical_with_4min_delta_returns_plus_10(self):
        # Theatrical n'est PAS dans _EXTENDED_EDITIONS → tolerance 5 min
        bonus, warn = score_runtime_delta(144.0, 148, "Theatrical")
        self.assertEqual(bonus, 10)
        self.assertIsNone(warn)

    # --- Zone grise (5 < delta < 30 min) ---

    def test_gray_zone_delta_10_returns_zero(self):
        bonus, warn = score_runtime_delta(138.0, 148, None)
        self.assertEqual(bonus, 0)
        self.assertIsNone(warn)

    def test_gray_zone_just_below_mismatch_returns_zero(self):
        # Delta = 29.5 min → zone grise (sous 30 min)
        bonus, warn = score_runtime_delta(118.5, 148, None)
        self.assertEqual(bonus, 0)
        self.assertIsNone(warn)

    # --- Franc mismatch (delta >= 30 min) ---

    def test_mismatch_at_threshold_returns_penalty_and_warning(self):
        bonus, warn = score_runtime_delta(118.0, 148, None)
        self.assertEqual(bonus, -25)
        self.assertEqual(warn, WARN_RUNTIME_MISMATCH)

    def test_mismatch_50min_returns_penalty_and_warning(self):
        # Faux match type "Le Ruffian (90 min) matche Magnificent Ruffians (140 min)"
        bonus, warn = score_runtime_delta(90.0, 140, None)
        self.assertEqual(bonus, -25)
        self.assertEqual(warn, WARN_RUNTIME_MISMATCH)

    def test_mismatch_even_with_directors_cut_returns_penalty(self):
        # Meme avec edition longue, 50 min de delta = trop
        bonus, warn = score_runtime_delta(98.0, 148, "Director's Cut")
        self.assertEqual(bonus, -25)
        self.assertEqual(warn, WARN_RUNTIME_MISMATCH)

    # --- Cas no-op ---

    def test_none_file_runtime_returns_noop(self):
        bonus, warn = score_runtime_delta(None, 148, None)
        self.assertEqual(bonus, 0)
        self.assertIsNone(warn)

    def test_none_tmdb_runtime_returns_noop(self):
        bonus, warn = score_runtime_delta(148.0, None, None)
        self.assertEqual(bonus, 0)
        self.assertIsNone(warn)

    def test_zero_file_runtime_returns_noop(self):
        bonus, warn = score_runtime_delta(0.0, 148, None)
        self.assertEqual(bonus, 0)
        self.assertIsNone(warn)

    def test_zero_tmdb_runtime_returns_noop(self):
        bonus, warn = score_runtime_delta(148.0, 0, None)
        self.assertEqual(bonus, 0)
        self.assertIsNone(warn)

    def test_negative_runtime_returns_noop(self):
        # Defensive : runtime negatif (probe corrompu) ne doit pas crasher
        bonus, warn = score_runtime_delta(-5.0, 148, None)
        self.assertEqual(bonus, 0)
        self.assertIsNone(warn)

    def test_invalid_string_runtime_returns_noop(self):
        # Defensive : type incorrect ne doit pas crasher
        bonus, warn = score_runtime_delta("not-a-number", 148, None)
        self.assertEqual(bonus, 0)
        self.assertIsNone(warn)

    # --- Edition label edge cases ---

    def test_unknown_edition_falls_back_to_theatrical_tolerance(self):
        # Label inconnu (ex: "IMAX") → traite comme theatrical (5 min)
        bonus, warn = score_runtime_delta(160.0, 148, "IMAX")
        self.assertEqual(bonus, 0)  # delta 12 > 5 → zone grise
        self.assertIsNone(warn)

    def test_empty_edition_string_falls_back_to_theatrical(self):
        bonus, warn = score_runtime_delta(160.0, 148, "")
        self.assertEqual(bonus, 0)
        self.assertIsNone(warn)

    def test_edition_case_insensitive(self):
        # "extended" / "EXTENDED" / "Extended Edition" → tous reconnus
        bonus, _ = score_runtime_delta(160.0, 148, "EXTENDED")
        self.assertEqual(bonus, 10)
        bonus, _ = score_runtime_delta(160.0, 148, "extended cut")
        self.assertEqual(bonus, 10)


if __name__ == "__main__":
    unittest.main()
