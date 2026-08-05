from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cinesort.ui.api.cinesort_api as backend


class DashboardCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_dashboard_cache_")
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
        self.store.run.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={"tmdb_enabled": False},
            created_ts=started_ts - 2.0,
        )
        self.store.run.mark_run_running(run_id, started_ts=started_ts)
        self.store.run.mark_run_done(run_id, stats=stats, ended_ts=started_ts + 10.0)

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
        self.store.quality.upsert_quality_report(
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
                "thresholds_used": {"bitrate_min_kbps_2160p": 18000},
            },
            profile_id="CinemaLux_v1",
            profile_version=1,
            ts=time.time(),
        )
        self.store.quality.upsert_quality_report(
            run_id=run_id,
            row_id="row_2",
            score=91,
            tier="Premium",
            reasons=["Bon profil video/audio."],
            metrics={
                "probe_quality": "FULL",
                "detected": {
                    "resolution": "1080p",
                    "bitrate_kbps": 24000,
                    "audio_best_codec": "dts-hd ma",
                    "hdr_dolby_vision": False,
                    "hdr10_plus": False,
                    "hdr10": False,
                    "languages": ["fr", "en"],
                },
                "thresholds_used": {"bitrate_min_kbps_1080p": 8000},
            },
            profile_id="CinemaLux_v1",
            profile_version=1,
            ts=time.time(),
        )

    def _prepare_run(self, run_id: str) -> None:
        started = time.time() - 20.0
        self._insert_run_done(run_id, started_ts=started, stats={"planned_rows": 2})
        self._write_plan_rows(run_id, self._sample_rows())
        self._insert_reports_for_run(run_id)

    def _signature_for(self, run_id: str) -> dict:
        run_row = self.store.run.get_run(run_id)
        run_paths = self.api._run_paths_for(self.state_dir, run_id, ensure_exists=False)  # type: ignore[attr-defined]
        return self.api._dashboard_cache_signature(  # type: ignore[attr-defined]
            run_row=run_row, run_paths=run_paths, store=self.store
        )

    def test_signature_changes_when_auto_approve_threshold_changes(self) -> None:
        # M7 : le seuil auto_approve alimente review_queue_count/conflicts_count
        # (mis en cache) ; sans lui dans la signature, changer le seuil laisse le
        # KPI fige. AVANT le fix les deux signatures sont identiques.
        run_id = "20260315_101010_777"
        self._prepare_run(run_id)

        with mock.patch.object(self.api, "_get_settings_impl", return_value={"auto_approve_threshold": 85}):
            sig_85 = self._signature_for(run_id)
        with mock.patch.object(self.api, "_get_settings_impl", return_value={"auto_approve_threshold": 95}):
            sig_95 = self._signature_for(run_id)

        self.assertEqual(sig_85.get("auto_approve_threshold"), 85)
        self.assertEqual(sig_95.get("auto_approve_threshold"), 95)
        self.assertNotEqual(sig_85, sig_95)

    def test_signature_changes_when_alert_ignored(self) -> None:
        # M17 : "Ignorer une alerte" = INSERT dans ignored_alerts (table disjointe
        # des stats quality/perceptual/anomaly). AVANT le fix la signature ne bouge
        # pas et le KPI "Cas a verifier"/"Conflits" reste fige.
        run_id = "20260315_111111_888"
        self._prepare_run(run_id)

        sig_before = self._signature_for(run_id)
        res = self.store.film_modal.insert_ignored_alert("row_2", "low_confidence")
        self.assertTrue(res.get("inserted"), res)
        sig_after = self._signature_for(run_id)

        self.assertNotEqual(sig_before.get("ignored_alerts"), sig_after.get("ignored_alerts"))
        self.assertNotEqual(sig_before, sig_after)

    def test_signature_changes_when_duplicate_decision_recorded(self) -> None:
        # M18 : duplicates_groups derive de duplicate_decisions (mis en cache) ;
        # sans cette table dans la signature, "Garder A"/"Auto-decider" laissent le
        # compteur fige. Couvre aussi le changement d'avis (meme groupe, autre
        # gagnant) qui doit encore differencier la signature.
        run_id = "20260315_121212_999"
        self._prepare_run(run_id)

        sig_before = self._signature_for(run_id)
        self.store.apply.upsert_duplicate_decision(
            run_id=run_id,
            group_key="Film A (2013)",
            winner_row_id="row_1",
            loser_row_ids=["row_2"],
        )
        sig_after = self._signature_for(run_id)
        self.assertNotEqual(sig_before.get("duplicate_decisions"), sig_after.get("duplicate_decisions"))
        self.assertNotEqual(sig_before, sig_after)

        self.store.apply.upsert_duplicate_decision(
            run_id=run_id,
            group_key="Film A (2013)",
            winner_row_id="row_2",
            loser_row_ids=["row_1"],
        )
        sig_changed = self._signature_for(run_id)
        self.assertNotEqual(sig_after.get("duplicate_decisions"), sig_changed.get("duplicate_decisions"))
        self.assertNotEqual(sig_after, sig_changed)

    def test_get_dashboard_reuses_cache_on_second_open(self) -> None:
        run_id = "20260222_150000_444"
        started = time.time() - 40.0
        self._insert_run_done(run_id, started_ts=started, stats={"planned_rows": 2, "applied_count": 1})
        self._write_plan_rows(run_id, self._sample_rows())
        self._insert_reports_for_run(run_id)

        first = self.api._get_dashboard_impl(run_id)
        self.assertTrue(first.get("ok"), first)

        cache_path = self.state_dir / "runs" / f"tri_films_{run_id}" / "dashboard_cache.json"
        self.assertTrue(cache_path.exists(), str(cache_path))

        with mock.patch.object(
            self.store.quality, "list_quality_reports", side_effect=OSError("should not hit reports")
        ):
            second = self.api._get_dashboard_impl(run_id)

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

        first = self.api._get_dashboard_impl(run_id)
        self.assertTrue(first.get("ok"), first)

        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        plan_path = run_dir / "plan.jsonl"
        original = plan_path.read_text(encoding="utf-8")
        plan_path.write_text(original + "\n", encoding="utf-8")

        with mock.patch.object(self.store.quality, "list_quality_reports", side_effect=OSError("cache invalidated")):
            second = self.api._get_dashboard_impl(run_id)

        self.assertFalse(second.get("ok"), second)
        self.assertEqual(str(second.get("message") or ""), "Impossible de charger la synthese du run.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
