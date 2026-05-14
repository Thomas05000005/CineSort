"""Tests backend pour G5 — simulateur de preset qualite."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from cinesort.ui.api.quality_simulator_support import (
    _apply_weights,
    _count_tiers,
    _group_avg_delta,
    _recompute_in_memory,
    _resolve_target_profile,
    _slugify,
    _tier_for,
    clear_cache,
    run_simulation,
)


class ApplyWeightsTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_apply_weights(80, 60, 40, {"video": 60, "audio": 30, "extras": 10}), 70)

    def test_all_zero_weights_fallback(self):
        """Poids 0/0/0 -> divise par 1 mais numerator=0 donc score=0 (comportement attendu)."""
        self.assertEqual(_apply_weights(80, 60, 40, {"video": 0, "audio": 0, "extras": 0}), 0)

    def test_clamp_upper(self):
        self.assertEqual(_apply_weights(120, 120, 120, {"video": 1, "audio": 0, "extras": 0}), 100)

    def test_clamp_lower(self):
        self.assertEqual(_apply_weights(-10, -10, -10, {"video": 1, "audio": 1, "extras": 1}), 0)


class TierForTests(unittest.TestCase):
    def test_tiers_modern(self):
        # U1 audit : 5 tiers Platinum/Gold/Silver/Bronze/Reject (migration 011)
        t = {"platinum": 85, "gold": 68, "silver": 54, "bronze": 30}
        self.assertEqual(_tier_for(95, t), "Platinum")
        self.assertEqual(_tier_for(85, t), "Platinum")
        self.assertEqual(_tier_for(70, t), "Gold")
        self.assertEqual(_tier_for(55, t), "Silver")
        self.assertEqual(_tier_for(40, t), "Bronze")
        self.assertEqual(_tier_for(10, t), "Reject")

    def test_tiers_legacy_keys_still_read(self):
        # Retro-compat : les profils sauvegardes avec les anciennes clefs doivent
        # continuer a produire les nouveaux noms.
        t = {"premium": 85, "bon": 68, "moyen": 54}
        self.assertEqual(_tier_for(95, t), "Platinum")
        self.assertEqual(_tier_for(70, t), "Gold")
        self.assertEqual(_tier_for(55, t), "Silver")
        self.assertEqual(_tier_for(40, t), "Bronze")
        self.assertEqual(_tier_for(10, t), "Reject")


class CountTiersTests(unittest.TestCase):
    def test_count(self):
        got = _count_tiers(["Platinum", "Gold", "Gold", "Silver", "Reject", "Platinum"])
        self.assertEqual(got["Platinum"], 2)
        self.assertEqual(got["Gold"], 2)
        self.assertEqual(got["Silver"], 1)
        self.assertEqual(got["Reject"], 1)
        self.assertEqual(got["Bronze"], 0)


class GroupAvgDeltaTests(unittest.TestCase):
    def test_group(self):
        rows = [
            {"codec": "hevc", "delta": 5},
            {"codec": "hevc", "delta": 15},
            {"codec": "h264", "delta": -2},
        ]
        out = _group_avg_delta(rows, "codec")
        self.assertEqual(out["hevc"]["avg_delta"], 10.0)
        self.assertEqual(out["hevc"]["count"], 2)
        self.assertEqual(out["h264"]["avg_delta"], -2.0)


class SlugifyTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_slugify("Mon Preset Tres Cool"), "mon_preset_tres_cool")
        self.assertEqual(_slugify("Test!@#$123"), "test_123")
        self.assertEqual(_slugify(""), "custom")


class ResolveTargetProfileTests(unittest.TestCase):
    def test_known_preset(self):
        prof = _resolve_target_profile("equilibre", None)
        self.assertIsNotNone(prof)
        self.assertIn("weights", prof)
        self.assertIn("tiers", prof)

    def test_unknown_preset(self):
        self.assertIsNone(_resolve_target_profile("no_such_preset_id", None))

    def test_overrides_merge(self):
        prof = _resolve_target_profile("equilibre", {"weights": {"video": 80, "audio": 15, "extras": 5}})
        self.assertEqual(prof["weights"]["video"], 80)
        self.assertEqual(prof["weights"]["audio"], 15)


class RecomputeInMemoryTests(unittest.TestCase):
    def test_simple(self):
        reports = [
            {
                "row_id": "1",
                "score": 70,
                "tier": "Bon",
                "metrics": {
                    "subscores": {"video": 80, "audio": 60, "extras": 40},
                    "detected": {"video_codec": "hevc", "resolution": "1080p", "title": "Dune"},
                },
            },
            {
                "row_id": "2",
                "score": 50,
                "tier": "Moyen",
                "metrics": {
                    "subscores": {"video": 40, "audio": 60, "extras": 60},
                    "detected": {"video_codec": "h264", "resolution": "720p", "title": "Old"},
                },
            },
        ]
        baseline = {
            "weights": {"video": 60, "audio": 30, "extras": 10},
            "tiers": {"premium": 85, "bon": 68, "moyen": 54},
        }
        target = {
            "weights": {"video": 80, "audio": 15, "extras": 5},
            "tiers": {"premium": 85, "bon": 68, "moyen": 54},
            "label": "Video-first",
        }

        out = _recompute_in_memory(reports, baseline, target)
        self.assertEqual(len(out), 2)
        self.assertIn("score_after", out[0])
        self.assertIn("delta", out[0])
        # video dominant => row 1 (video=80) score_after > score_before
        self.assertGreater(out[0]["score_after"], 70)


class RunSimulationIntegrationTests(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def _make_api(self, reports, active_profile=None):
        api = MagicMock()
        store = MagicMock()
        store.list_quality_reports.return_value = reports
        store.get_latest_run.return_value = {"run_id": "RUN123"}
        store.list_runs.return_value = [{"run_id": "RUN123"}]
        api._store = store
        api._active_quality_profile_payload.return_value = {
            "profile_json": active_profile
            or {
                "id": "active",
                "label": "Actuel",
                "weights": {"video": 60, "audio": 30, "extras": 10},
                "tiers": {"premium": 85, "bon": 68, "moyen": 54},
            }
        }
        return api

    def test_empty_scope(self):
        api = self._make_api([])
        res = run_simulation(api, run_id="RUN123", preset_id="equilibre", scope="run")
        self.assertFalse(res.get("ok"))

    def test_full_simulation(self):
        reports = [
            {
                "row_id": str(i),
                "score": 50 + i * 3,
                "tier": "Moyen",
                "metrics": {
                    "subscores": {"video": 50 + i * 3, "audio": 60, "extras": 40},
                    "detected": {"video_codec": "hevc", "resolution": "1080p", "title": f"Film {i}"},
                },
            }
            for i in range(10)
        ]
        api = self._make_api(reports)
        res = run_simulation(api, run_id="RUN123", preset_id="equilibre", scope="run")
        self.assertTrue(res.get("ok"))
        self.assertEqual(res["films_count"], 10)
        self.assertIn("before", res)
        self.assertIn("after", res)
        self.assertIn("delta", res)
        self.assertIn("top_winners", res)
        self.assertIn("top_losers", res)
        self.assertIn("distribution_shift", res)
        self.assertIn("by_codec", res)
        self.assertIn("by_resolution", res)

    def test_cache_hit(self):
        reports = [
            {
                "row_id": "1",
                "score": 70,
                "tier": "Bon",
                "metrics": {
                    "subscores": {"video": 70, "audio": 70, "extras": 50},
                    "detected": {"video_codec": "hevc", "resolution": "1080p"},
                },
            }
        ]
        api = self._make_api(reports)
        r1 = run_simulation(api, run_id="RUN123", preset_id="equilibre", scope="run")
        self.assertFalse(r1.get("cache_hit"))
        r2 = run_simulation(api, run_id="RUN123", preset_id="equilibre", scope="run")
        self.assertTrue(r2.get("cache_hit"))

    def test_is_dry_run(self):
        """Verifie qu'aucune methode de store d'ecriture n'est appelee."""
        reports = [
            {
                "row_id": "1",
                "score": 70,
                "tier": "Bon",
                "metrics": {
                    "subscores": {"video": 70, "audio": 70, "extras": 50},
                    "detected": {"video_codec": "hevc", "resolution": "1080p"},
                },
            }
        ]
        api = self._make_api(reports)
        run_simulation(api, run_id="RUN123", preset_id="equilibre", scope="run")
        api._store.save_quality_profile.assert_not_called()
        api._save_active_quality_profile.assert_not_called()

    def test_concurrent_simulations_thread_safe(self):
        """Audit 2026-05-13 : _SIM_CACHE est mute par plusieurs threads
        REST (ThreadingHTTPServer). Sans lock, l'eviction FIFO
        `_SIM_CACHE.pop(next(iter(...)))` peut crasher avec
        RuntimeError si un autre thread mute le dict pendant l'iteration.
        Ce test simule N threads qui appellent run_simulation +
        clear_cache en parallele et exige zero exception."""
        import threading

        reports = [
            {
                "row_id": str(i),
                "score": 60 + i,
                "tier": "Moyen",
                "metrics": {
                    "subscores": {"video": 60 + i, "audio": 60, "extras": 60},
                    "detected": {"video_codec": "hevc", "resolution": "1080p"},
                },
            }
            for i in range(5)
        ]
        api = self._make_api(reports)
        errors: list[BaseException] = []
        clear_cache()

        def worker(idx: int) -> None:
            try:
                # Vary run_id pour forcer beaucoup de cache misses + evictions.
                run_simulation(api, run_id=f"RUN{idx}", preset_id="equilibre", scope="run")
                if idx % 7 == 0:
                    clear_cache()
            except BaseException as exc:  # noqa: BLE001 - on capture tout
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        clear_cache()
        self.assertEqual(errors, [], f"thread errors: {errors}")

    def test_distribution_shift_sums_to_total(self):
        reports = [
            {
                "row_id": str(i),
                "score": 60,
                "tier": "Moyen",
                "metrics": {
                    "subscores": {"video": 60, "audio": 60, "extras": 60},
                    "detected": {"video_codec": "hevc", "resolution": "1080p"},
                },
            }
            for i in range(5)
        ]
        api = self._make_api(reports)
        res = run_simulation(api, run_id="RUN123", preset_id="equilibre", scope="run")
        total_in_shift = sum(res["distribution_shift"].values())
        self.assertEqual(total_in_shift, 5)


if __name__ == "__main__":
    unittest.main()
