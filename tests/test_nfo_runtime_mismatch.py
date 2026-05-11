"""P1.1.d : tests pour detect_nfo_runtime_mismatch.

Helper pur qui compare runtime NFO (minutes) vs probe.duration_s (secondes).
Déclenche un mismatch si :
- delta > 10% ET
- delta > 8 minutes (garde-fou remaster/director-cut)
"""

from __future__ import annotations

import unittest

from cinesort.ui.api.quality_report_support import detect_nfo_runtime_mismatch


class DetectNfoRuntimeMismatchTests(unittest.TestCase):
    def test_no_nfo_runtime_returns_none(self):
        self.assertIsNone(detect_nfo_runtime_mismatch(nfo_runtime_min=None, probe_duration_s=5400.0))

    def test_no_probe_duration_returns_none(self):
        self.assertIsNone(detect_nfo_runtime_mismatch(nfo_runtime_min=148, probe_duration_s=None))

    def test_probe_duration_zero_returns_none(self):
        self.assertIsNone(detect_nfo_runtime_mismatch(nfo_runtime_min=148, probe_duration_s=0))

    def test_probe_duration_negative_returns_none(self):
        self.assertIsNone(detect_nfo_runtime_mismatch(nfo_runtime_min=148, probe_duration_s=-10.0))

    def test_matching_runtime_returns_none(self):
        # 148 min NFO vs 148 min probe = 0 delta
        self.assertIsNone(detect_nfo_runtime_mismatch(nfo_runtime_min=148, probe_duration_s=148 * 60))

    def test_delta_under_8_minutes_ignored(self):
        # 148 min vs 153 min = 5 min delta (3.4%) → ignoré (< 8 min ET < 10%)
        self.assertIsNone(detect_nfo_runtime_mismatch(nfo_runtime_min=148, probe_duration_s=153 * 60))

    def test_delta_under_10pct_ignored_even_if_over_8min(self):
        # 200 min vs 215 min = 15 min delta (7.5%) → ignoré (< 10% même si > 8 min)
        self.assertIsNone(detect_nfo_runtime_mismatch(nfo_runtime_min=200, probe_duration_s=215 * 60))

    def test_large_mismatch_triggers(self):
        # 148 min vs 90 min = 58 min delta (39%) → mismatch évident (autre film)
        result = detect_nfo_runtime_mismatch(nfo_runtime_min=148, probe_duration_s=90 * 60)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["nfo_minutes"], 148)
        self.assertEqual(result["probe_minutes"], 90.0)
        self.assertEqual(result["delta_minutes"], 58.0)
        self.assertGreater(result["delta_pct"], 10.0)

    def test_short_film_small_absolute_delta_triggers_on_pct(self):
        # 30 min NFO vs 20 min probe = 10 min delta (33%) → mismatch (> 10% ET > 8min)
        result = detect_nfo_runtime_mismatch(nfo_runtime_min=30, probe_duration_s=20 * 60)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["delta_minutes"], 10.0)

    def test_directors_cut_mild_extension_not_flagged(self):
        # Film 120 min, director's cut 132 min = 12 min delta (10%) → pas flag (exactement 10%)
        result = detect_nfo_runtime_mismatch(nfo_runtime_min=120, probe_duration_s=132 * 60)
        self.assertIsNone(result)

    def test_extended_cut_over_threshold_flagged(self):
        # Film 120 min, extended 145 min = 25 min (20.8%) → flag (> 10% et > 8 min)
        result = detect_nfo_runtime_mismatch(nfo_runtime_min=120, probe_duration_s=145 * 60)
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
