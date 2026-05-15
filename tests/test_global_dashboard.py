"""Tests for global dashboard stats — DB methods + API endpoint + UI contracts."""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend


class GlobalDashboardDbTests(unittest.TestCase):
    """Test the 3 new DB mixin methods."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_global_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.store, _ = self.api._get_or_create_infra(self.state_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _insert_run(self, run_id: str, ts: float, total: int = 5) -> None:
        self.store.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={},
            created_ts=ts - 1,
        )
        self.store.mark_run_running(run_id, started_ts=ts)
        self.store.mark_run_done(run_id, stats={"planned_rows": total}, ended_ts=ts + 10)

    def _insert_quality(self, run_id: str, row_id: str, score: int, tier: str) -> None:
        self.store.upsert_quality_report(
            run_id=run_id,
            row_id=row_id,
            score=score,
            tier=tier,
            reasons=[],
            metrics={},
            profile_id="default",
            profile_version=1,
        )

    def _insert_anomaly(self, run_id: str, code: str) -> None:
        self.store._ensure_anomalies_table()
        with self.store._managed_conn() as conn:
            conn.execute(
                "INSERT INTO anomalies(run_id, row_id, severity, code, message, path, recommended_action, context_json, ts) "
                "VALUES(?, ?, 'WARN', ?, 'test', '', '', '{}', ?)",
                (run_id, "row_1", code, time.time()),
            )

    def test_get_global_tier_distribution_empty(self) -> None:
        result = self.store.get_global_tier_distribution(limit_runs=10)
        self.assertEqual(result["tiers"], {})
        self.assertEqual(result["total_scored"], 0)

    def test_get_global_tier_distribution_with_data(self) -> None:
        self._insert_run("run_a", 1000.0)
        self._insert_run("run_b", 2000.0)
        self._insert_quality("run_a", "r1", 90, "Premium")
        self._insert_quality("run_a", "r2", 75, "Bon")
        self._insert_quality("run_b", "r3", 50, "Mauvais")
        self._insert_quality("run_b", "r4", 60, "Moyen")
        result = self.store.get_global_tier_distribution(limit_runs=10)
        self.assertEqual(result["total_scored"], 4)
        self.assertEqual(result["tiers"]["Premium"], 1)
        self.assertEqual(result["tiers"]["Bon"], 1)
        self.assertEqual(result["tiers"]["Moyen"], 1)
        self.assertEqual(result["tiers"]["Mauvais"], 1)

    def test_get_top_anomaly_codes_empty(self) -> None:
        result = self.store.get_top_anomaly_codes(limit_runs=10, limit_codes=5)
        self.assertEqual(result, [])

    def test_get_top_anomaly_codes_with_data(self) -> None:
        self._insert_run("run_a", 1000.0)
        self._insert_run("run_b", 2000.0)
        self._insert_anomaly("run_a", "low_bitrate")
        self._insert_anomaly("run_a", "low_bitrate")
        self._insert_anomaly("run_b", "low_bitrate")
        self._insert_anomaly("run_b", "missing_audio")
        result = self.store.get_top_anomaly_codes(limit_runs=10, limit_codes=5)
        self.assertGreaterEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "low_bitrate")
        self.assertEqual(result[0]["count"], 3)

    def test_get_runs_summary(self) -> None:
        self._insert_run("run_a", 1000.0, total=10)
        self._insert_run("run_b", 2000.0, total=20)
        result = self.store.get_runs_summary(limit=10)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["run_id"], "run_b")  # most recent first
        self.assertEqual(result[0]["total_rows"], 20)
        self.assertEqual(result[1]["run_id"], "run_a")


class GlobalDashboardApiTests(unittest.TestCase):
    """Test the get_global_stats API endpoint."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_global_api_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.store, _ = self.api._get_or_create_infra(self.state_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _insert_run(self, run_id: str, ts: float, total: int = 5) -> None:
        self.store.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={},
            created_ts=ts - 1,
        )
        self.store.mark_run_running(run_id, started_ts=ts)
        self.store.mark_run_done(run_id, stats={"planned_rows": total}, ended_ts=ts + 10)

    def _insert_quality(self, run_id: str, row_id: str, score: int, tier: str) -> None:
        self.store.upsert_quality_report(
            run_id=run_id,
            row_id=row_id,
            score=score,
            tier=tier,
            reasons=[],
            metrics={},
            profile_id="default",
            profile_version=1,
        )

    def test_get_global_stats_empty(self) -> None:
        result = self.api.get_global_stats(20)
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["total_runs"], 0)
        self.assertEqual(result["timeline"], [])

    def test_get_global_stats_with_runs(self) -> None:
        for i in range(6):
            rid = f"run_{i:03d}"
            self._insert_run(rid, 1000.0 + i * 100, total=10)
            self._insert_quality(rid, f"row_{i}", 70 + i * 5, "Bon")

        result = self.api.get_global_stats(20)
        self.assertTrue(result["ok"])
        s = result["summary"]
        self.assertEqual(s["total_runs"], 6)
        self.assertEqual(s["total_films"], 60)
        self.assertGreater(s["avg_score"], 0)
        self.assertIn(s["trend"], ["↑", "↓", "→"])
        self.assertGreaterEqual(s["unscored_films"], 0)

        # Timeline should have 6 entries (chronological order)
        self.assertEqual(len(result["timeline"]), 6)

        # Activity should have 6 entries (reverse chronological)
        self.assertEqual(len(result["activity"]), 6)

    def test_trend_indicator_up(self) -> None:
        """Recent runs better than older → trend ↑."""
        for i in range(10):
            rid = f"run_{i:03d}"
            self._insert_run(rid, 1000.0 + i * 100, total=5)
            score = 60 + i * 4  # rising scores
            self._insert_quality(rid, f"row_{i}", score, "Bon")

        result = self.api.get_global_stats(20)
        self.assertEqual(result["summary"]["trend"], "↑")

    def test_trend_indicator_down(self) -> None:
        """Recent runs worse than older → trend ↓."""
        for i in range(10):
            rid = f"run_{i:03d}"
            self._insert_run(rid, 1000.0 + i * 100, total=5)
            score = 95 - i * 4  # declining scores
            self._insert_quality(rid, f"row_{i}", score, "Bon")

        result = self.api.get_global_stats(20)
        self.assertEqual(result["summary"]["trend"], "↓")

    def test_unscored_films_count(self) -> None:
        """Films in latest run without quality report."""
        self._insert_run("run_latest", 5000.0, total=10)
        self._insert_quality("run_latest", "row_1", 80, "Bon")
        self._insert_quality("run_latest", "row_2", 90, "Premium")

        result = self.api.get_global_stats(20)
        # 10 total - 2 scored = 8 unscored
        self.assertEqual(result["summary"]["unscored_films"], 8)


class GlobalDashboardUiContractTests(unittest.TestCase):
    """UI contract tests for global dashboard elements."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.index_html = (root / "web" / "index.html").read_text(encoding="utf-8")
        js_files = []
        for d in ["core", "components", "views"]:
            p = root / "web" / d
            if p.is_dir():
                for f in sorted(p.glob("*.js")):
                    js_files.append(f.read_text(encoding="utf-8"))
        js_files.append((root / "web" / "app.js").read_text(encoding="utf-8"))
        cls.front_js = "\n".join(js_files)

    def test_quality_mode_toggle_exists(self) -> None:
        self.assertIn('id="qualityModeToggle"', self.index_html)
        self.assertIn('data-qmode="run"', self.index_html)
        self.assertIn('data-qmode="global"', self.index_html)

    def test_global_panel_exists(self) -> None:
        self.assertIn('id="qualityPanelGlobal"', self.index_html)
        self.assertIn('id="qualityPanelRun"', self.index_html)

    def test_global_kpi_elements_exist(self) -> None:
        for kid in ["gKpiRuns", "gKpiFilms", "gKpiScore", "gKpiPremium", "gKpiTrend", "gKpiUnscored"]:
            self.assertIn(f'id="{kid}"', self.index_html)

    def test_global_timeline_chart_container(self) -> None:
        self.assertIn('id="globalTimelineChart"', self.index_html)

    def test_global_distribution_container(self) -> None:
        self.assertIn('id="globalDistBars"', self.index_html)

    def test_global_anomalies_table(self) -> None:
        self.assertIn('id="globalAnomaliesTbody"', self.index_html)

    def test_global_activity_table(self) -> None:
        self.assertIn('id="globalActivityTbody"', self.index_html)

    def test_js_has_global_stats_functions(self) -> None:
        self.assertIn("async function refreshGlobalStats(", self.front_js)
        self.assertIn("function renderGlobalStats(data)", self.front_js)
        self.assertIn("function buildTimelineSvg(timeline)", self.front_js)
        self.assertIn("function setQualityMode(mode)", self.front_js)

    def test_js_calls_get_global_stats_api(self) -> None:
        self.assertIn("get_global_stats", self.front_js)

    def test_trend_rendering(self) -> None:
        self.assertIn("function trendClass(trend)", self.front_js)

    def test_svg_chart_uses_tier_colors(self) -> None:
        self.assertIn("var(--success)", self.front_js)
        self.assertIn("var(--danger)", self.front_js)


if __name__ == "__main__":
    unittest.main()
