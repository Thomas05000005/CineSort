from __future__ import annotations

import copy
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import cinesort.ui.api.cinesort_api as backend
import cinesort.domain.core as core
from cinesort.domain.quality_score import (
    compute_quality_score,
    default_quality_profile,
    list_quality_presets,
    quality_profile_from_preset,
)


class QualityScoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_quality_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "root"
        self.state_dir = Path(self._tmp.name) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _sample_probe(self, *, bitrate: int) -> dict:
        return {
            "probe_quality": "FULL",
            "probe_quality_reasons": ["Analyse technique complete."],
            "video": {
                "codec": "hevc",
                "width": 3840,
                "height": 2160,
                "bitrate": bitrate,
                "bit_depth": 10,
                "hdr_dolby_vision": True,
                "hdr10_plus": False,
                "hdr10": True,
            },
            "audio_tracks": [
                {
                    "codec": "dts-hd ma",
                    "channels": 8,
                    "language": "eng",
                    "bitrate": 3200000,
                },
                {
                    "codec": "aac",
                    "channels": 2,
                    "language": "fra",
                    "bitrate": 224000,
                },
            ],
            "sources": {
                "video": {
                    "codec": "ffprobe",
                    "bitrate": "ffprobe",
                    "width": "ffprobe",
                    "height": "ffprobe",
                }
            },
        }

    def _prepare_single_run(self) -> tuple[backend.CineSortApi, str, str]:
        api = backend.CineSortApi()
        movie_dir = self.root / "Gravity.2013.1080p"
        movie_dir.mkdir(parents=True, exist_ok=True)
        (movie_dir / "Gravity.2013.1080p.mkv").write_bytes(b"x" * 2048)

        old_min = core.MIN_VIDEO_BYTES
        core.MIN_VIDEO_BYTES = 1
        self.addCleanup(setattr, core, "MIN_VIDEO_BYTES", old_min)

        save = api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
                "probe_backend": "none",
            }
        )
        self.assertTrue(save.get("ok"), save)

        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
                "probe_backend": "none",
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])

        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            st = api.run.get_status(run_id, 0)
            if st.get("done"):
                break
            time.sleep(0.03)
        else:
            self.fail("Timeout plan run")

        plan = api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        self.assertTrue(rows, rows)
        row_id = str(rows[0]["row_id"])
        return api, run_id, row_id

    def test_score_stable_for_same_input(self) -> None:
        profile = default_quality_profile()
        probe = self._sample_probe(bitrate=22000000)

        a = compute_quality_score(normalized_probe=probe, profile=profile)
        b = compute_quality_score(normalized_probe=probe, profile=profile)

        self.assertEqual(a["score"], b["score"])
        self.assertEqual(a["tier"], b["tier"])
        self.assertEqual(a["reasons"], b["reasons"])

    def test_4k_light_toggle_changes_score(self) -> None:
        probe = self._sample_probe(bitrate=8000000)
        profile_on = default_quality_profile()
        profile_off = copy.deepcopy(profile_on)
        profile_on["toggles"]["enable_4k_light"] = True
        profile_off["toggles"]["enable_4k_light"] = False

        r_on = compute_quality_score(normalized_probe=probe, profile=profile_on)
        r_off = compute_quality_score(normalized_probe=probe, profile=profile_off)

        self.assertGreaterEqual(int(r_on["score"]), int(r_off["score"]))
        self.assertTrue(bool(r_on["metrics"]["flags"]["is_4k_light"]))
        self.assertFalse(bool(r_off["metrics"]["flags"]["is_4k_light"]))
        joined = "\n".join(str(x) for x in r_on.get("reasons", []))
        self.assertIn("kb/s", joined)

    def test_resolution_fallback_from_release_name_when_probe_is_incomplete(self) -> None:
        profile = default_quality_profile()
        probe = {
            "probe_quality": "PARTIAL",
            "video": {
                "codec": "hevc",
                "width": 0,
                "height": 0,
                "bitrate": 9500000,
                "bit_depth": 10,
                "hdr_dolby_vision": False,
                "hdr10_plus": False,
                "hdr10": True,
            },
            "audio_tracks": [{"codec": "dts", "channels": 6, "language": "eng", "bitrate": 768000}],
            "sources": {},
        }
        out = compute_quality_score(
            normalized_probe=probe,
            profile=profile,
            folder_name="Movie.Name",
            release_name="Movie.Name.2019.2160p.4KLight.x265.mkv",
        )
        detected = out.get("metrics", {}).get("detected", {})
        self.assertEqual(detected.get("resolution"), "2160p")
        self.assertEqual(detected.get("resolution_source"), "name_fallback")
        self.assertTrue(bool(out.get("metrics", {}).get("flags", {}).get("is_4k_light")))

    def test_score_is_more_discriminant_between_low_and_high_quality_inputs(self) -> None:
        profile = default_quality_profile()
        high_probe = self._sample_probe(bitrate=26000000)
        low_probe = {
            "probe_quality": "PARTIAL",
            "video": {
                "codec": "avc",
                "width": 1280,
                "height": 720,
                "bitrate": 1800000,
                "bit_depth": 8,
                "hdr_dolby_vision": False,
                "hdr10_plus": False,
                "hdr10": False,
            },
            "audio_tracks": [{"codec": "aac", "channels": 2, "language": "fra", "bitrate": 96000}],
            "sources": {},
        }
        high = compute_quality_score(normalized_probe=high_probe, profile=profile)
        low = compute_quality_score(normalized_probe=low_probe, profile=profile)
        self.assertGreaterEqual(int(high["score"]), int(low["score"]) + 20)

    def test_score_explanation_and_confidence_are_exposed(self) -> None:
        profile = default_quality_profile()
        probe = self._sample_probe(bitrate=21000000)
        out = compute_quality_score(
            normalized_probe=probe,
            profile=profile,
            folder_name="Some.Movie (2021)",
            expected_title="Some Movie",
            expected_year=2021,
            release_name="Some.Movie.2021.2160p.UHD.BluRay.x265",
        )
        conf = out.get("confidence")
        self.assertIsInstance(conf, dict)
        self.assertIn("value", conf)
        self.assertIn("label", conf)
        self.assertIn("reasons", conf)
        expl = out.get("explanation")
        self.assertIsInstance(expl, dict)
        self.assertTrue(str(expl.get("narrative") or "").strip())
        self.assertIsInstance(expl.get("top_positive"), list)
        self.assertIsInstance(expl.get("top_negative"), list)
        metrics = out.get("metrics", {})
        self.assertIsInstance(metrics.get("score_confidence"), dict)
        self.assertIsInstance(metrics.get("score_explanation"), dict)
        self.assertIsInstance(expl.get("factors"), list)

    def test_uhd_clean_profile_can_reach_above_70(self) -> None:
        profile = default_quality_profile()
        probe = self._sample_probe(bitrate=30000000)
        out = compute_quality_score(
            normalized_probe=probe,
            profile=profile,
            folder_name="Demo.Movie (2022)",
            expected_title="Demo Movie",
            expected_year=2022,
            release_name="Demo.Movie.2022.2160p.UHD.BluRay.Remux.TrueHD.Atmos",
        )
        self.assertGreaterEqual(int(out.get("score") or 0), 70, out)

    def test_profile_reset_restore_defaults(self) -> None:
        api = backend.CineSortApi()
        save = api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(save.get("ok"), save)

        custom = default_quality_profile()
        custom["toggles"]["enable_4k_light"] = False
        custom["weights"]["video"] = 50
        custom["weights"]["audio"] = 40
        custom["weights"]["extras"] = 10
        saved = api.quality.save_quality_profile(custom)
        self.assertTrue(saved.get("ok"), saved)

        reset = api.quality.reset_quality_profile()
        self.assertTrue(reset.get("ok"), reset)
        profile = reset.get("profile_json", {})
        self.assertEqual(profile.get("id"), "CinemaLux_v1")
        self.assertTrue(bool(profile.get("toggles", {}).get("enable_4k_light")))

    def test_quality_presets_catalog_contains_expected_presets(self) -> None:
        presets = list_quality_presets()
        ids = {str(x.get("preset_id")) for x in presets if isinstance(x, dict)}
        self.assertIn("remux_strict", ids)
        self.assertIn("equilibre", ids)
        self.assertIn("light", ids)

    def test_api_get_quality_presets_returns_expected_ids(self) -> None:
        api = backend.CineSortApi()
        out = api.quality.get_quality_presets()
        self.assertTrue(out.get("ok"), out)
        presets = out.get("presets") if isinstance(out.get("presets"), list) else []
        ids = {str(x.get("preset_id")) for x in presets if isinstance(x, dict)}
        self.assertIn("remux_strict", ids)
        self.assertIn("equilibre", ids)
        self.assertIn("light", ids)
        for row in presets:
            if not isinstance(row, dict):
                continue
            self.assertIsInstance(row.get("profile_json"), dict)

    def test_apply_quality_preset_persists_active_profile(self) -> None:
        api = backend.CineSortApi()
        save = api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(save.get("ok"), save)

        applied = api.quality.apply_quality_preset("remux_strict")
        self.assertTrue(applied.get("ok"), applied)
        profile = applied.get("profile_json", {})
        self.assertEqual(str(profile.get("id")), "CinemaLux_RemuxStrict_v1")

        loaded = api.quality.get_quality_profile()
        self.assertTrue(loaded.get("ok"), loaded)
        loaded_profile = loaded.get("profile_json", {})
        self.assertEqual(str(loaded_profile.get("id")), "CinemaLux_RemuxStrict_v1")

    def test_apply_quality_preset_invalid_returns_fr_error(self) -> None:
        api = backend.CineSortApi()
        out = api.quality.apply_quality_preset("unknown_preset")
        self.assertFalse(out.get("ok"), out)
        self.assertIn("Preset qualite inconnu", str(out.get("message", "")))

    def test_remux_strict_is_harsher_than_light_for_4k_light_case(self) -> None:
        probe = self._sample_probe(bitrate=9000000)
        strict = quality_profile_from_preset("remux_strict")
        light = quality_profile_from_preset("light")
        self.assertIsInstance(strict, dict)
        self.assertIsInstance(light, dict)
        out_strict = compute_quality_score(
            normalized_probe=probe,
            profile=dict(strict or {}),
            release_name="Movie.2021.2160p.4KLight.x265",
        )
        out_light = compute_quality_score(
            normalized_probe=probe,
            profile=dict(light or {}),
            release_name="Movie.2021.2160p.4KLight.x265",
        )
        self.assertLessEqual(int(out_strict.get("score") or 0), int(out_light.get("score") or 0))

    def test_profile_import_invalid_returns_fr_error(self) -> None:
        api = backend.CineSortApi()
        save = api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(save.get("ok"), save)

        bad = api.quality.import_quality_profile("{invalid_json")
        self.assertFalse(bad.get("ok"), bad)
        txt = f"{bad.get('message', '')} {' '.join(bad.get('errors', []) if isinstance(bad.get('errors'), list) else [])}".lower()
        self.assertTrue(("json invalide" in txt) or ("profil invalide" in txt), bad)

    def test_profile_unknown_toggle_values_fallback_to_defaults(self) -> None:
        api = backend.CineSortApi()
        save = api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(save.get("ok"), save)

        profile = default_quality_profile()
        profile["toggles"]["include_metadata"] = "maybe"
        profile["toggles"]["include_naming"] = "unknown"
        profile["toggles"]["enable_4k_light"] = "unexpected"
        out = api.quality.save_quality_profile(profile)
        self.assertTrue(out.get("ok"), out)

        loaded = api.quality.get_quality_profile()
        self.assertTrue(loaded.get("ok"), loaded)
        toggles = loaded.get("profile_json", {}).get("toggles", {})
        self.assertFalse(bool(toggles.get("include_metadata")))
        self.assertFalse(bool(toggles.get("include_naming")))
        self.assertTrue(bool(toggles.get("enable_4k_light")))

    def test_report_written_in_db_and_reloaded(self) -> None:
        api, run_id, row_id = self._prepare_single_run()

        rep = api.quality.get_quality_report(run_id, row_id)
        self.assertTrue(rep.get("ok"), rep)
        self.assertIn("score", rep)
        self.assertIn("tier", rep)

        store, _runner = api._get_or_create_infra(self.state_dir)  # type: ignore[attr-defined]
        db_row = store.get_quality_report(run_id=run_id, row_id=row_id)
        self.assertIsNotNone(db_row)
        assert db_row is not None
        self.assertEqual(int(db_row["score"]), int(rep["score"]))
        self.assertEqual(str(db_row["tier"]), str(rep["tier"]))
        self.assertIsInstance(rep.get("confidence"), dict)
        self.assertIsInstance(rep.get("explanation"), dict)

    def test_reuse_existing_is_invalidated_when_profile_engine_changes(self) -> None:
        api, run_id, row_id = self._prepare_single_run()
        first = api.quality.get_quality_report(run_id, row_id, {"reuse_existing": False})
        self.assertTrue(first.get("ok"), first)
        cached = api.quality.get_quality_report(run_id, row_id, {"reuse_existing": True})
        self.assertTrue(cached.get("ok"), cached)
        self.assertEqual(str(cached.get("status")), "ignored_existing")

        profile = default_quality_profile()
        profile["version"] = int(profile.get("version") or 1) + 1
        profile["engine_version"] = "CinemaLux_v1_test_bump"
        saved = api.quality.save_quality_profile(profile)
        self.assertTrue(saved.get("ok"), saved)

        refreshed = api.quality.get_quality_report(run_id, row_id, {"reuse_existing": True})
        self.assertTrue(refreshed.get("ok"), refreshed)
        self.assertEqual(str(refreshed.get("status")), "analyzed")
        self.assertFalse(bool(refreshed.get("cache_hit_quality")))

    def test_analyze_quality_batch_rejects_empty_selection(self) -> None:
        api = backend.CineSortApi()
        res = api.quality.analyze_quality_batch("abcd", [], {"reuse_existing": True})
        self.assertFalse(res.get("ok"), res)
        self.assertIn("Aucune ligne sélectionnée", str(res.get("message", "")))

    def test_analyze_quality_batch_summary_with_analyzed_ignored_and_errors(self) -> None:
        api, run_id, row_id = self._prepare_single_run()

        first = api.quality.analyze_quality_batch(run_id, [row_id, "row_introuvable"], {"reuse_existing": False})
        self.assertTrue(first.get("ok"), first)
        self.assertEqual(int(first.get("analyzed") or 0), 1, first)
        self.assertEqual(int(first.get("ignored") or 0), 0, first)
        self.assertEqual(int(first.get("errors") or 0), 1, first)

        second = api.quality.analyze_quality_batch(run_id, [row_id], {"reuse_existing": True})
        self.assertTrue(second.get("ok"), second)
        self.assertEqual(int(second.get("analyzed") or 0), 0, second)
        self.assertEqual(int(second.get("ignored") or 0), 1, second)
        self.assertEqual(int(second.get("errors") or 0), 0, second)
        results = second.get("results") if isinstance(second.get("results"), list) else []
        self.assertTrue(results, second)
        self.assertEqual(str(results[0].get("status")), "ignored_existing")

    def test_analyze_quality_batch_rejects_concurrent_launch(self) -> None:
        """Issue #84 PR 10 : get_quality_report est sur QualityFacade (private impl)."""
        api, run_id, row_id = self._prepare_single_run()
        entered = threading.Event()
        release = threading.Event()
        original = api._get_quality_report_impl

        def slow_get_quality_report(run_id_arg, row_id_arg, options=None):
            entered.set()
            release.wait(1.2)
            return {
                "ok": True,
                "status": "analyzed",
                "score": 70,
                "tier": "Bon",
                "cache_hit_probe": False,
                "cache_hit_quality": False,
            }

        api._get_quality_report_impl = slow_get_quality_report  # type: ignore[method-assign]
        first_result: dict = {}

        def run_first():
            first_result.update(api.quality.analyze_quality_batch(run_id, [row_id], {"reuse_existing": False}))

        t = threading.Thread(target=run_first, daemon=True)
        try:
            t.start()
            self.assertTrue(entered.wait(1.0), "Le premier batch n'a pas démarré")
            second = api.quality.analyze_quality_batch(run_id, [row_id], {"reuse_existing": False})
            self.assertFalse(second.get("ok"), second)
            self.assertIn("déjà en cours", str(second.get("message", "")).lower())
        finally:
            release.set()
            t.join(2.0)
            api._get_quality_report_impl = original  # type: ignore[method-assign]

        self.assertTrue(first_result.get("ok"), first_result)

    def test_analyze_quality_batch_logs_structured_error_and_returns_clean_message(self) -> None:
        api, run_id, row_id = self._prepare_single_run()
        store, _runner = api._get_or_create_infra(self.state_dir)  # type: ignore[attr-defined]

        with mock.patch.object(api, "_get_quality_report_impl", side_effect=OSError("quality batch boom")):
            out = api.quality.analyze_quality_batch(run_id, [row_id], {"reuse_existing": False})

        self.assertFalse(out.get("ok"), out)
        self.assertEqual(str(out.get("message") or ""), "Impossible de terminer l'analyse qualite.")
        self.assertNotIn("quality batch boom", str(out.get("message") or ""))

        errs = store.list_errors(run_id)
        self.assertTrue(errs, errs)
        last = errs[-1]
        self.assertEqual(str(last.get("step") or ""), "analyze_quality_batch")
        self.assertEqual(str(last.get("code") or ""), "OSError")


if __name__ == "__main__":
    unittest.main(verbosity=2)
