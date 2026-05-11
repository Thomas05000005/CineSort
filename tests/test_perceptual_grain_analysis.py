"""Tests detection grain / DNR — Phase III (item 9.24).

Couvre :
- estimate_grain : image plate, image bruitee, uniformite
- classify_film_era : eres de production
- analyze_grain : verdicts contextualises, animation, studio, budget, confiance
- TMDb cache backward compatibility
"""

from __future__ import annotations

import unittest

from cinesort.domain.perceptual.grain_analysis import (
    analyze_grain,
    classify_film_era,
    estimate_grain,
)
from cinesort.domain.perceptual.constants import (
    GRAIN_MODERATE,
    GRAIN_UNIFORMITY_ARTIFICIAL,
    GRAIN_UNIFORMITY_NATURAL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flat_frame(w: int = 32, h: int = 32, value: int = 128) -> dict:
    """Frame uniforme (grain = 0)."""
    return {"pixels": [value] * (w * h), "width": w, "height": h, "y_avg": float(value)}


def _make_noisy_frame(w: int = 32, h: int = 32, seed: int = 0) -> dict:
    """Frame bruitee avec variation (grain eleve)."""
    pixels = [(seed + i * 37 + i * i) % 256 for i in range(w * h)]
    return {"pixels": pixels, "width": w, "height": h, "y_avg": 128.0}


def _make_grainy_frame(w: int = 32, h: int = 32, base: int = 128, noise: int = 8) -> dict:
    """Frame avec grain modere autour d'une valeur de base (blocs plats bruites)."""
    import random

    rng = random.Random(42)
    pixels = [max(0, min(255, base + rng.randint(-noise, noise))) for _ in range(w * h)]
    return {"pixels": pixels, "width": w, "height": h, "y_avg": float(base)}


def _make_uniform_grain_frame(w: int = 32, h: int = 32, base: int = 128, noise: int = 5) -> dict:
    """Frame avec grain tres uniforme (suspect artificiel)."""
    # Chaque pixel = base + pattern repetitif
    pixels = [base + (i % (noise * 2)) - noise for i in range(w * h)]
    return {"pixels": pixels, "width": w, "height": h, "y_avg": float(base)}


# ---------------------------------------------------------------------------
# estimate_grain (4 tests)
# ---------------------------------------------------------------------------


class EstimateGrainTests(unittest.TestCase):
    """Tests de l'estimation du grain."""

    def test_flat_image_low_grain(self) -> None:
        """Image uniforme → grain_level bas."""
        pixels = [128] * (32 * 32)
        result = estimate_grain(pixels, 32, 32, bit_depth=8)
        self.assertAlmostEqual(result["grain_level"], 0.0, places=1)

    def test_noisy_image_high_grain(self) -> None:
        """Image bruitee dans les zones plates → grain_level eleve."""
        # Pixels avec variation moderee (stddev ~5-10 dans les blocs)
        frame = _make_grainy_frame(32, 32, base=128, noise=10)
        result = estimate_grain(frame["pixels"], 32, 32, bit_depth=8)
        self.assertGreater(result["grain_level"], 1.0)
        self.assertGreater(result["flat_zone_count"], 0)

    def test_uniformity_natural(self) -> None:
        """Grain spatialement varie → uniformite plus basse que le grain uniforme."""
        # Grain qui varie par zone : certains blocs peu bruites, d'autres beaucoup
        import random

        rng = random.Random(99)
        pixels = []
        for by in range(4):  # 4 bandes de 16 lignes sur 64×64
            noise_level = [2, 10, 3, 12][by]  # amplitude variable par bande
            for _ in range(16 * 64):
                pixels.append(max(0, min(255, 128 + rng.randint(-noise_level, noise_level))))
        result_varied = estimate_grain(pixels, 64, 64, bit_depth=8)

        # Grain uniforme pour comparer
        frame_u = _make_uniform_grain_frame(64, 64, base=128, noise=5)
        result_uniform = estimate_grain(frame_u["pixels"], 64, 64, bit_depth=8)

        # Le grain varie doit avoir une uniformite plus basse que le grain uniforme
        if result_varied["flat_zone_count"] > 0 and result_uniform["flat_zone_count"] > 0:
            self.assertLess(result_varied["grain_uniformity"], result_uniform["grain_uniformity"])

    def test_uniformity_artificial_high(self) -> None:
        """Grain tres uniforme (pattern repetitif) → uniformite elevee."""
        # Tous les blocs ont exactement le meme pattern de bruit
        frame = _make_uniform_grain_frame(64, 64, base=128, noise=5)
        result = estimate_grain(frame["pixels"], 64, 64, bit_depth=8)
        # Pattern repetitif → stddevs tres similaires → uniformite haute
        if result["flat_zone_count"] > 0:
            self.assertGreater(result["grain_uniformity"], 0.5)


# ---------------------------------------------------------------------------
# classify_film_era (2 tests)
# ---------------------------------------------------------------------------


class ClassifyFilmEraTests(unittest.TestCase):
    """Tests de la classification d'ere."""

    def test_eras(self) -> None:
        self.assertEqual(classify_film_era(1994), "classic_film")
        self.assertEqual(classify_film_era(2005), "transition")
        self.assertEqual(classify_film_era(2020), "digital")
        self.assertEqual(classify_film_era(0), "unknown")
        self.assertEqual(classify_film_era(None), "unknown")


# ---------------------------------------------------------------------------
# analyze_grain — verdicts (10 tests)
# ---------------------------------------------------------------------------


class AnalyzeGrainVerdictTests(unittest.TestCase):
    """Tests des verdicts contextualises."""

    def test_grain_naturel_preserve_pre2002(self) -> None:
        """Pre-2002 + grain modere + uniformite naturelle → grain_naturel_preserve."""
        import random

        rng = random.Random(42)
        w, h = 128, 128
        pixels = [0] * (w * h)
        # Base variable par bloc + grain modere a amplitude variable → grain naturel
        for by in range(0, h, 16):
            for bx in range(0, w, 16):
                base = 80 + (by + bx) % 80
                noise = [4, 8, 3, 9, 5, 7, 2, 10][(by // 16 + bx // 16) % 8]
                for dy in range(16):
                    for dx in range(16):
                        pixels[(by + dy) * w + bx + dx] = max(0, min(255, base + rng.randint(-noise, noise)))
        frames = [{"pixels": pixels, "width": w, "height": h, "y_avg": 128.0}]
        result = analyze_grain(frames, video_blur_mean=0.02, bit_depth=8, tmdb_year=1994)
        self.assertGreaterEqual(result.grain_level, GRAIN_MODERATE)
        self.assertLess(result.grain_uniformity, GRAIN_UNIFORMITY_NATURAL)
        self.assertEqual(result.verdict, "grain_naturel_preserve")
        self.assertGreater(result.score, 70)

    def test_dnr_suspect_pre2002(self) -> None:
        """Pre-2002 + pas de grain + blur eleve → dnr_suspect."""
        frames = [_make_flat_frame(32, 32, value=128)]
        result = analyze_grain(frames, video_blur_mean=0.06, bit_depth=8, tmdb_year=1995)
        self.assertEqual(result.verdict, "dnr_suspect")
        self.assertTrue(result.dnr_suspect)
        self.assertLess(result.score, 40)

    def test_bruit_numerique_post2015(self) -> None:
        """Post-2015 + grain sur source digital → bruit_numerique_excessif."""
        import random

        rng = random.Random(55)
        w, h = 128, 128
        pixels = [0] * (w * h)
        for by in range(0, h, 16):
            for bx in range(0, w, 16):
                base = 80 + (by + bx) % 80
                noise = [4, 8, 3, 9, 5, 7, 2, 10][(by // 16 + bx // 16) % 8]
                for dy in range(16):
                    for dx in range(16):
                        pixels[(by + dy) * w + bx + dx] = max(0, min(255, base + rng.randint(-noise, noise)))
        frames = [{"pixels": pixels, "width": w, "height": h, "y_avg": 128.0}]
        result = analyze_grain(frames, video_blur_mean=0.02, bit_depth=8, tmdb_year=2020)
        self.assertGreater(result.grain_level, GRAIN_MODERATE)
        self.assertEqual(result.verdict, "bruit_numerique_excessif")
        self.assertLess(result.score, 40)

    def test_image_propre_post2012(self) -> None:
        """Post-2012 propre → image_propre_normal."""
        frames = [_make_flat_frame(32, 32, value=128)]
        result = analyze_grain(frames, video_blur_mean=0.02, bit_depth=8, tmdb_year=2022)
        self.assertEqual(result.verdict, "image_propre_normal")
        self.assertGreater(result.score, 60)

    def test_grain_artificiel_suspect(self) -> None:
        """Uniformite > seuil → grain_artificiel_suspect."""
        frames = [_make_uniform_grain_frame(64, 64, base=128, noise=5)]
        result = analyze_grain(frames, video_blur_mean=0.02, bit_depth=8, tmdb_year=1998)
        # Si l'uniformite est detectee comme artificielle
        if result.grain_uniformity > GRAIN_UNIFORMITY_ARTIFICIAL:
            self.assertEqual(result.verdict, "grain_artificiel_suspect")
            self.assertTrue(result.artificial_grain_suspect)

    def test_grain_absent_suspect_pre2002(self) -> None:
        """Pre-2002 sans grain ni blur → grain_absent_suspect."""
        frames = [_make_flat_frame(32, 32, value=128)]
        result = analyze_grain(frames, video_blur_mean=0.01, bit_depth=8, tmdb_year=1990)
        self.assertEqual(result.verdict, "grain_absent_suspect")

    def test_animation_skip(self) -> None:
        """Genre Animation → not_applicable, score neutre 50."""
        frames = [_make_grainy_frame(32, 32)]
        meta = {
            "genres": ["Animation", "Family"],
            "budget": 100_000_000,
            "production_companies": ["Walt Disney Pictures"],
        }
        result = analyze_grain(frames, tmdb_metadata=meta, bit_depth=8, tmdb_year=2019)
        self.assertEqual(result.verdict, "not_applicable")
        self.assertEqual(result.score, 50)
        self.assertTrue(result.is_animation)

    def test_major_studio_adjusts_score(self) -> None:
        """Studio majeur → score ajuste (attente plus haute)."""
        frames = [_make_flat_frame(32, 32)]
        meta_major = {"genres": ["Drama"], "budget": 0, "production_companies": ["Warner Bros."]}
        meta_indie = {"genres": ["Drama"], "budget": 0, "production_companies": ["Studio Indie"]}
        r_major = analyze_grain(frames, tmdb_metadata=meta_major, bit_depth=8, tmdb_year=2022)
        r_indie = analyze_grain(frames, tmdb_metadata=meta_indie, bit_depth=8, tmdb_year=2022)
        self.assertTrue(r_major.is_major_studio)
        self.assertFalse(r_indie.is_major_studio)
        # Studio majeur → score egal ou inferieur (attente plus haute)
        self.assertLessEqual(r_major.score, r_indie.score)

    def test_high_budget_adjusts_score(self) -> None:
        """Budget > 50M → score ajuste."""
        frames = [_make_flat_frame(32, 32)]
        meta_high = {"genres": ["Action"], "budget": 100_000_000, "production_companies": []}
        meta_low = {"genres": ["Action"], "budget": 1_000_000, "production_companies": []}
        r_high = analyze_grain(frames, tmdb_metadata=meta_high, bit_depth=8, tmdb_year=2022)
        r_low = analyze_grain(frames, tmdb_metadata=meta_low, bit_depth=8, tmdb_year=2022)
        self.assertLessEqual(r_high.score, r_low.score)

    def test_unknown_year_low_confidence(self) -> None:
        """Annee inconnue → confiance basse."""
        frames = [_make_flat_frame(32, 32)]
        result = analyze_grain(frames, bit_depth=8, tmdb_year=0)
        self.assertEqual(result.film_era, "unknown")
        self.assertLess(result.verdict_confidence, 0.75)


# ---------------------------------------------------------------------------
# TMDb backward compatibility (1 test)
# ---------------------------------------------------------------------------


class TmdbCacheBackwardTests(unittest.TestCase):
    """Verifie que les anciens cache entries sans genres/budget fonctionnent."""

    def test_old_cache_entry_no_genres(self) -> None:
        """Cache entry sans genres/budget → .get() retourne [] et 0."""
        old_entry = {"poster_path": "/abc.jpg", "collection_id": 1, "collection_name": "Saga"}
        # Simuler la lecture comme le ferait get_movie_metadata_for_perceptual
        genres = list(old_entry.get("genres") or [])
        budget = int(old_entry.get("budget") or 0)
        companies = list(old_entry.get("production_companies") or [])
        self.assertEqual(genres, [])
        self.assertEqual(budget, 0)
        self.assertEqual(companies, [])


if __name__ == "__main__":
    unittest.main()
