"""P4.1 : tests pour cinesort/domain/calibration.py + endpoint submit_score_feedback.

Couvre : tier_ordinal, compute_tier_delta, analyze_feedback_bias,
suggest_weight_adjustment, et l'endpoint complet via CineSortApi.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.domain.calibration import (
    analyze_feedback_bias,
    compute_tier_delta,
    suggest_weight_adjustment,
    tier_ordinal,
)


class TierOrdinalTests(unittest.TestCase):
    def test_canonical_tiers(self):
        self.assertEqual(tier_ordinal("Reject"), 0)
        self.assertEqual(tier_ordinal("Bronze"), 1)
        self.assertEqual(tier_ordinal("Silver"), 2)
        self.assertEqual(tier_ordinal("Gold"), 3)
        self.assertEqual(tier_ordinal("Platinum"), 4)

    def test_case_insensitive(self):
        self.assertEqual(tier_ordinal("gold"), 3)
        self.assertEqual(tier_ordinal("PLATINUM"), 4)

    def test_legacy_aliases(self):
        self.assertEqual(tier_ordinal("Premium"), tier_ordinal("Platinum"))
        self.assertEqual(tier_ordinal("Bon"), tier_ordinal("Gold"))
        self.assertEqual(tier_ordinal("Moyen"), tier_ordinal("Silver"))
        self.assertEqual(tier_ordinal("Mauvais"), tier_ordinal("Reject"))

    def test_unknown_returns_minus_one(self):
        self.assertEqual(tier_ordinal("Unknown"), -1)
        self.assertEqual(tier_ordinal(""), -1)


class ComputeTierDeltaTests(unittest.TestCase):
    def test_accord(self):
        self.assertEqual(compute_tier_delta("Gold", "Gold"), 0)

    def test_user_higher(self):
        self.assertEqual(compute_tier_delta("Silver", "Gold"), 1)
        self.assertEqual(compute_tier_delta("Bronze", "Platinum"), 3)

    def test_user_lower(self):
        self.assertEqual(compute_tier_delta("Platinum", "Silver"), -2)
        self.assertEqual(compute_tier_delta("Gold", "Bronze"), -2)

    def test_unknown_returns_zero(self):
        self.assertEqual(compute_tier_delta("Gold", "Unknown"), 0)


class AnalyzeFeedbackBiasTests(unittest.TestCase):
    def test_empty_returns_neutral(self):
        r = analyze_feedback_bias([])
        self.assertEqual(r["total_feedbacks"], 0)
        self.assertEqual(r["bias_direction"], "neutral")
        self.assertEqual(r["bias_strength"], "none")

    def test_all_accord(self):
        fbs = [{"tier_delta": 0} for _ in range(10)]
        r = analyze_feedback_bias(fbs)
        self.assertEqual(r["accord_pct"], 100.0)
        self.assertEqual(r["bias_direction"], "neutral")

    def test_underscore_bias(self):
        fbs = [{"tier_delta": 1} for _ in range(10)] + [{"tier_delta": 2} for _ in range(5)]
        r = analyze_feedback_bias(fbs)
        self.assertGreater(r["mean_delta"], 0)
        self.assertEqual(r["bias_direction"], "underscore")
        self.assertIn(r["bias_strength"], ("moderate", "strong"))

    def test_overscore_bias(self):
        fbs = [{"tier_delta": -1} for _ in range(8)] + [{"tier_delta": -2} for _ in range(5)]
        r = analyze_feedback_bias(fbs)
        self.assertLess(r["mean_delta"], 0)
        self.assertEqual(r["bias_direction"], "overscore")

    def test_weak_bias_not_strong(self):
        fbs = [{"tier_delta": 1}, {"tier_delta": 0}, {"tier_delta": 0}, {"tier_delta": 0}]
        r = analyze_feedback_bias(fbs)
        self.assertEqual(r["bias_strength"], "weak")

    def test_category_bias_counts(self):
        fbs = [
            {"tier_delta": 1, "category_focus": "audio"},
            {"tier_delta": 1, "category_focus": "audio"},
            {"tier_delta": 1, "category_focus": "video"},
            {"tier_delta": 1, "category_focus": None},
        ]
        r = analyze_feedback_bias(fbs)
        self.assertEqual(r["category_bias"]["audio"], 2)
        self.assertEqual(r["category_bias"]["video"], 1)
        self.assertEqual(r["category_bias"]["extras"], 0)


class SuggestWeightAdjustmentTests(unittest.TestCase):
    def test_no_suggestion_if_weak_bias(self):
        bias = {
            "bias_direction": "neutral",
            "bias_strength": "none",
            "category_bias": {"video": 0, "audio": 0, "extras": 0},
            "total_feedbacks": 0,
        }
        r = suggest_weight_adjustment(bias, {"video": 60, "audio": 30, "extras": 10})
        self.assertIsNone(r)

    def test_underscore_audio_increases_audio_weight(self):
        # Bias underscore + catégorie audio pointée → audio weight augmente
        bias = {
            "bias_direction": "underscore",
            "bias_strength": "moderate",
            "category_bias": {"video": 1, "audio": 5, "extras": 0},
            "total_feedbacks": 6,
        }
        r = suggest_weight_adjustment(bias, {"video": 60, "audio": 30, "extras": 10})
        self.assertIsNotNone(r)
        assert r is not None
        self.assertEqual(r["focus_category"], "audio")
        self.assertGreater(r["to"]["audio"], r["from"]["audio"])
        # Somme conservée
        self.assertEqual(sum(r["to"].values()), sum(r["from"].values()))

    def test_overscore_video_decreases_video_weight(self):
        bias = {
            "bias_direction": "overscore",
            "bias_strength": "strong",
            "category_bias": {"video": 8, "audio": 1, "extras": 0},
            "total_feedbacks": 9,
        }
        r = suggest_weight_adjustment(bias, {"video": 60, "audio": 30, "extras": 10})
        assert r is not None
        self.assertEqual(r["focus_category"], "video")
        self.assertLess(r["to"]["video"], r["from"]["video"])

    def test_no_category_pointed_returns_none(self):
        bias = {
            "bias_direction": "underscore",
            "bias_strength": "moderate",
            "category_bias": {"video": 0, "audio": 0, "extras": 0},
            "total_feedbacks": 5,
        }
        r = suggest_weight_adjustment(bias, {"video": 60, "audio": 30, "extras": 10})
        self.assertIsNone(r)

    def test_rationale_contains_explanation(self):
        bias = {
            "bias_direction": "underscore",
            "bias_strength": "moderate",
            "category_bias": {"video": 0, "audio": 5, "extras": 0},
            "total_feedbacks": 5,
        }
        r = suggest_weight_adjustment(bias, {"video": 60, "audio": 30, "extras": 10})
        assert r is not None
        self.assertIn("audio", r["rationale"].lower())
        self.assertIn("5", r["rationale"])


class SubmitFeedbackIntegrationTests(unittest.TestCase):
    """End-to-end : créer un run, soumettre feedback, lire calibration report."""

    def setUp(self):
        import cinesort.domain.core as core

        self._tmp = tempfile.mkdtemp(prefix="cinesort_calib_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True)
        self.state_dir.mkdir(parents=True)
        self._min_bytes = core.MIN_VIDEO_BYTES
        core.MIN_VIDEO_BYTES = 1

    def tearDown(self):
        import cinesort.domain.core as core

        core.MIN_VIDEO_BYTES = self._min_bytes
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_submit_feedback_without_quality_report_fails(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        folder = self.root / "Film.2020"
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)
        api = CineSortApi()
        start = api.run.start_plan({"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False})
        import time as _time

        while not api.run.get_status(start["run_id"], 0).get("done"):
            _time.sleep(0.05)
        plan = api.run.get_plan(start["run_id"])
        rows = plan.get("rows", [])
        self.assertTrue(rows)
        # Pas de quality_report généré → le endpoint doit refuser
        r = api.quality.submit_score_feedback(
            run_id=start["run_id"],
            row_id=rows[0]["row_id"],
            user_tier="Gold",
        )
        self.assertFalse(r.get("ok"))

    def test_invalid_run_id(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi()
        r = api.quality.submit_score_feedback(run_id="not_a_valid_id", row_id="x", user_tier="Gold")
        self.assertFalse(r.get("ok"))

    def test_missing_row_id(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi()
        r = api.quality.submit_score_feedback(run_id="20260101_120000_000", row_id="", user_tier="Gold")
        self.assertFalse(r.get("ok"))


if __name__ == "__main__":
    unittest.main()
