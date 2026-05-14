from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cinesort.ui.api.cinesort_api as backend


class DashboardApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_dashboard_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.api = backend.CineSortApi()
        saved = self.api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(saved.get("ok"), saved)
        self.store, _runner = self.api._get_or_create_infra(self.state_dir)  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_plan_rows(self, run_id: str, rows: list[dict]) -> None:
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        plan = run_dir / "plan.jsonl"
        payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
        plan.write_text(payload, encoding="utf-8")

    def _insert_run_done(self, run_id: str, *, started_ts: float, stats: dict) -> None:
        self.store.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={"tmdb_enabled": False},
            created_ts=started_ts - 2.0,
        )
        self.store.mark_run_running(run_id, started_ts=started_ts)
        self.store.mark_run_done(run_id, stats=stats, ended_ts=started_ts + 10.0)

    def _sample_rows(self) -> list[dict]:
        return [
            {
                "row_id": "row_1",
                "kind": "single",
                "folder": str(self.root / "Film A"),
                "video": str(self.root / "Film A" / "Film.A.mkv"),
                "proposed_title": "Film A",
                "proposed_year": 2013,
                "proposed_source": "tmdb",
                "confidence": 86,
                "confidence_label": "high",
                "candidates": [],
                "notes": "",
                "collection_name": None,
            },
            {
                "row_id": "row_2",
                "kind": "single",
                "folder": str(self.root / "Film B"),
                "video": str(self.root / "Film B" / "Film.B.mkv"),
                "proposed_title": "Film B",
                "proposed_year": 2010,
                "proposed_source": "name",
                "confidence": 72,
                "confidence_label": "med",
                "candidates": [],
                "notes": "",
                "collection_name": None,
            },
        ]

    def _insert_reports_for_run(self, run_id: str) -> None:
        self.store.upsert_quality_report(
            run_id=run_id,
            row_id="row_1",
            score=52,
            tier="Faible",
            reasons=["Debit faible pour 2160p."],
            metrics={
                "probe_quality": "PARTIAL",
                "detected": {
                    "resolution": "2160p",
                    "bitrate_kbps": 7000,
                    "audio_best_codec": "aac",
                    "hdr_dolby_vision": False,
                    "hdr10_plus": False,
                    "hdr10": False,
                    "languages": ["fr"],
                },
                "thresholds_used": {
                    "bitrate_min_kbps_2160p": 18000,
                },
            },
            profile_id="CinemaLux_v1",
            profile_version=1,
            ts=time.time(),
        )
        self.store.upsert_quality_report(
            run_id=run_id,
            row_id="row_2",
            score=91,
            tier="Premium",
            reasons=["Bon profil video/audio."],
            metrics={
                "probe_quality": "FULL",
                "detected": {
                    "resolution": "1080p",
                    "bitrate_kbps": 12000,
                    "audio_best_codec": "dts-hd ma",
                    "hdr_dolby_vision": False,
                    "hdr10_plus": False,
                    "hdr10": True,
                    "languages": ["fr", "en"],
                },
                "thresholds_used": {
                    "bitrate_min_kbps_2160p": 18000,
                },
            },
            profile_id="CinemaLux_v1",
            profile_version=1,
            ts=time.time(),
        )

    def test_get_dashboard_contains_expected_sections_and_bins(self) -> None:
        run_id = "20260222_120000_111"
        started = time.time() - 100.0
        rows = self._sample_rows()
        self._insert_run_done(
            run_id,
            started_ts=started,
            stats={"planned_rows": 2, "applied_count": 1},
        )
        self._write_plan_rows(run_id, rows)
        self._insert_reports_for_run(run_id)

        data = self.api.get_dashboard(run_id)
        self.assertTrue(data.get("ok"), data)
        self.assertEqual(data.get("run_id"), run_id)
        self.assertEqual(data.get("run_dir"), str(self.state_dir / "runs" / f"tri_films_{run_id}"))

        self.assertIn("kpis", data)
        self.assertIn("distributions", data)
        self.assertIn("anomalies_top", data)
        self.assertIn("outliers", data)
        self.assertIn("runs_history", data)

        kpis = data["kpis"]
        self.assertEqual(int(kpis.get("scored_movies") or 0), 2)
        self.assertEqual(int(kpis.get("total_movies") or 0), 2)
        self.assertGreaterEqual(float(kpis.get("score_avg") or 0), 0.0)

        bins = data["distributions"]["score_bins"]
        self.assertEqual(len(bins), 10)
        self.assertEqual(sum(int(x.get("count") or 0) for x in bins), 2)

        self.assertGreaterEqual(len(data["outliers"]["low_bitrate"]), 1)
        self.assertGreaterEqual(len(data["outliers"]["sdr_4k"]), 1)
        self.assertGreaterEqual(len(data["outliers"]["vo_missing"]), 1)
        self.assertGreaterEqual(len(data["anomalies_top"]), 1)

        run_ids = [str(x.get("run_id") or "") for x in data["runs_history"]]
        self.assertIn(run_id, run_ids)
        history_entry = next((x for x in data["runs_history"] if str(x.get("run_id") or "") == run_id), None)
        self.assertIsNotNone(history_entry)
        assert history_entry is not None
        self.assertEqual(history_entry.get("run_dir"), str(self.state_dir / "runs" / f"tri_films_{run_id}"))

    def test_get_dashboard_latest_and_no_scores_fallback(self) -> None:
        old_run = "20260222_120000_111"
        new_run = "20260222_130000_222"
        base = time.time() - 80.0

        self._insert_run_done(old_run, started_ts=base, stats={"planned_rows": 2, "applied_count": 0})
        self._write_plan_rows(old_run, self._sample_rows())
        self._insert_reports_for_run(old_run)

        self._insert_run_done(new_run, started_ts=base + 40.0, stats={"planned_rows": 1, "applied_count": 0})
        self._write_plan_rows(
            new_run,
            [
                {
                    "row_id": "row_new",
                    "kind": "single",
                    "folder": str(self.root / "Film C"),
                    "video": str(self.root / "Film C" / "Film.C.mkv"),
                    "proposed_title": "Film C",
                    "proposed_year": 2001,
                    "proposed_source": "name",
                    "confidence": 60,
                    "confidence_label": "med",
                    "candidates": [],
                    "notes": "",
                    "collection_name": None,
                }
            ],
        )

        latest = self.api.get_dashboard("latest")
        self.assertTrue(latest.get("ok"), latest)
        self.assertEqual(latest.get("run_id"), new_run)
        self.assertEqual(latest.get("run_dir"), str(self.state_dir / "runs" / f"tri_films_{new_run}"))
        self.assertEqual(int(latest.get("kpis", {}).get("scored_movies") or 0), 0)
        self.assertIn("non score", str(latest.get("message") or "").lower())

    def test_get_dashboard_logs_structured_error_and_returns_clean_message(self) -> None:
        run_id = "20260222_140000_333"
        started = time.time() - 50.0
        self._insert_run_done(run_id, started_ts=started, stats={"planned_rows": 1, "applied_count": 0})
        self._write_plan_rows(run_id, self._sample_rows())

        with mock.patch.object(self.store, "list_quality_reports", side_effect=OSError("dashboard boom")):
            out = self.api.get_dashboard(run_id)

        self.assertFalse(out.get("ok"), out)
        self.assertEqual(str(out.get("message") or ""), "Impossible de charger la synthese du run.")
        self.assertNotIn("dashboard boom", str(out.get("message") or ""))

        errs = self.store.list_errors(run_id)
        self.assertTrue(errs, errs)
        last = errs[-1]
        self.assertEqual(str(last.get("step") or ""), "get_dashboard")
        self.assertEqual(str(last.get("code") or ""), "OSError")
        self.assertIn("dashboard boom", str(last.get("message") or ""))
        ctx = json.loads(str(last.get("context_json") or "{}"))
        self.assertEqual(str(ctx.get("endpoint") or ""), "get_dashboard")
        self.assertEqual(str(ctx.get("run_id") or ""), run_id)

    def test_get_dashboard_reuses_cache_on_second_open(self) -> None:
        run_id = "20260222_150000_444"
        started = time.time() - 40.0
        self._insert_run_done(run_id, started_ts=started, stats={"planned_rows": 2, "applied_count": 1})
        self._write_plan_rows(run_id, self._sample_rows())
        self._insert_reports_for_run(run_id)

        first = self.api.get_dashboard(run_id)
        self.assertTrue(first.get("ok"), first)

        cache_path = self.state_dir / "runs" / f"tri_films_{run_id}" / "dashboard_cache.json"
        self.assertTrue(cache_path.exists(), str(cache_path))

        with mock.patch.object(self.store, "list_quality_reports", side_effect=OSError("should not hit reports")):
            second = self.api.get_dashboard(run_id)

        self.assertTrue(second.get("ok"), second)
        self.assertEqual(second.get("kpis"), first.get("kpis"))
        self.assertEqual(second.get("distributions"), first.get("distributions"))
        self.assertEqual(second.get("anomalies_top"), first.get("anomalies_top"))
        self.assertEqual(second.get("outliers"), first.get("outliers"))

    def test_get_dashboard_invalidates_cache_when_plan_changes(self) -> None:
        run_id = "20260222_160000_555"
        started = time.time() - 30.0
        self._insert_run_done(run_id, started_ts=started, stats={"planned_rows": 2, "applied_count": 1})
        self._write_plan_rows(run_id, self._sample_rows())
        self._insert_reports_for_run(run_id)

        first = self.api.get_dashboard(run_id)
        self.assertTrue(first.get("ok"), first)

        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        plan_path = run_dir / "plan.jsonl"
        original = plan_path.read_text(encoding="utf-8")
        plan_path.write_text(original + "\n", encoding="utf-8")

        with mock.patch.object(self.store, "list_quality_reports", side_effect=OSError("cache invalidated")):
            second = self.api.get_dashboard(run_id)

        self.assertFalse(second.get("ok"), second)
        self.assertEqual(str(second.get("message") or ""), "Impossible de charger la synthese du run.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
