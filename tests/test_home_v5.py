"""Tests Vague 2 v7.6.0 — Home overview-first.

Couvre :
- Backend : 3 nouvelles fonctions _compute_* + get_global_stats enrichi
- _PerceptualMixin : 4 nouvelles methodes DB (tier V2, trend, count_since, warnings)
- Composants desktop IIFE : home-widgets.js (kpi-grid + insights + posters),
                             home-charts.js (donut + line)
- Versions ES module dashboard equivalentes
- CSS Vague 2 (kpi, insights, carousel, donut, line)
- Integration index.html (scripts charges)
- renderHomeV5Overview function dans home.js
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _make_store_with_data():
    """Helper : cree un store temp avec 5 films (2 platinum + 1 gold + 1 silver + 1 reject)."""
    from cinesort.infra.db.migration_manager import MigrationManager
    from cinesort.infra.db.sqlite_store import SQLiteStore

    td = tempfile.mkdtemp()
    db = Path(td) / "test.db"
    MigrationManager(db, _ROOT / "cinesort" / "infra" / "db" / "migrations").apply()
    store = SQLiteStore(db)

    run_id = "r1"
    store.insert_run_pending(run_id=run_id, state_dir=str(td), root="X:/", config={})

    fixtures = [
        ("film1", "platinum", 92.0, []),
        ("film2", "platinum", 95.0, []),
        ("film3", "gold", 82.0, []),
        ("film4", "silver", 70.0, []),
        ("film5", "reject", 40.0, ["dnr_partial detected"]),
    ]
    for rid, tier, score, warns in fixtures:
        payload = {"warnings": warns}
        store.upsert_perceptual_report(
            run_id=run_id,
            row_id=rid,
            visual_score=50,
            audio_score=50,
            global_score=50,
            global_tier="bon",
            metrics={},
            settings_used={},
            global_score_v2=score,
            global_tier_v2=tier,
            global_score_v2_payload=payload,
        )
    return store, run_id, td


# ---------------------------------------------------------------------------
# Backend : _PerceptualMixin new methods
# ---------------------------------------------------------------------------


class PerceptualMixinV2AggregatesTests(unittest.TestCase):
    def test_tier_v2_distribution_counts(self) -> None:
        store, run_id, _ = _make_store_with_data()
        dist = store.get_global_tier_v2_distribution(run_ids=[run_id])
        self.assertEqual(dist.get("platinum"), 2)
        self.assertEqual(dist.get("gold"), 1)
        self.assertEqual(dist.get("silver"), 1)
        self.assertEqual(dist.get("reject"), 1)
        self.assertEqual(dist.get("bronze"), 0)

    def test_tier_v2_distribution_empty(self) -> None:
        store, _, _ = _make_store_with_data()
        dist = store.get_global_tier_v2_distribution(run_ids=[])
        self.assertEqual(dist, {})

    def test_count_v2_tier_since(self) -> None:
        store, _, _ = _make_store_with_data()
        self.assertEqual(store.count_v2_tier_since(tier="platinum", since_ts=0), 2)
        self.assertEqual(store.count_v2_tier_since(tier="reject", since_ts=0), 1)
        # Tier inexistant -> 0
        self.assertEqual(store.count_v2_tier_since(tier="nonexistent", since_ts=0), 0)

    def test_count_v2_warnings_flag(self) -> None:
        store, run_id, _ = _make_store_with_data()
        self.assertEqual(store.count_v2_warnings_flag(flag="dnr_partial", run_ids=[run_id]), 1)
        self.assertEqual(store.count_v2_warnings_flag(flag="nonexistent", run_ids=[run_id]), 0)

    def test_get_global_score_v2_trend_groups_by_day(self) -> None:
        store, _, _ = _make_store_with_data()
        # Les 5 films ont ts=now, donc 1 point pour aujourd'hui
        trend = store.get_global_score_v2_trend(since_ts=time.time() - 86400)
        self.assertGreaterEqual(len(trend), 1)
        point = trend[-1]
        self.assertIn("date", point)
        self.assertIn("avg_score", point)
        self.assertIn("count", point)
        # Moyenne des 5 scores V2 = (92 + 95 + 82 + 70 + 40) / 5 = 75.8
        self.assertAlmostEqual(point["avg_score"], 75.8, places=0)
        self.assertEqual(point["count"], 5)


# ---------------------------------------------------------------------------
# Backend : dashboard_support compute functions
# ---------------------------------------------------------------------------


class DashboardSupportV5Tests(unittest.TestCase):
    def test_compute_v2_tier_distribution_adds_percentages(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_v2_tier_distribution

        store, run_id, _ = _make_store_with_data()
        result = _compute_v2_tier_distribution(store, [run_id])
        self.assertIn("counts", result)
        self.assertIn("percentages", result)
        self.assertIn("total", result)
        self.assertIn("scored_total", result)
        self.assertEqual(result["scored_total"], 5)
        self.assertAlmostEqual(result["percentages"]["platinum"], 40.0)
        self.assertAlmostEqual(result["percentages"]["gold"], 20.0)

    def test_compute_v2_tier_distribution_no_runs(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_v2_tier_distribution

        store, _, _ = _make_store_with_data()
        result = _compute_v2_tier_distribution(store, [])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["scored_total"], 0)
        # Tous les tiers presents avec count 0
        for tier in ("platinum", "gold", "silver", "bronze", "reject", "unknown"):
            self.assertEqual(result["counts"][tier], 0)

    def test_compute_trend_30days_returns_31_points(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_trend_30days

        store, _, _ = _make_store_with_data()
        points = _compute_trend_30days(store)
        self.assertEqual(len(points), 31)
        for p in points:
            self.assertIn("date", p)
            self.assertIn("avg_score", p)
            self.assertIn("count", p)

    def test_compute_trend_30days_has_data_for_today(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_trend_30days

        store, _, _ = _make_store_with_data()
        points = _compute_trend_30days(store)
        today = points[-1]
        # Aujourd'hui devrait avoir les 5 films
        self.assertIsNotNone(today["avg_score"])
        self.assertEqual(today["count"], 5)

    def test_compute_active_insights_returns_list(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_active_insights

        store, run_id, _ = _make_store_with_data()
        insights = _compute_active_insights(None, store, [run_id], {})
        self.assertIsInstance(insights, list)
        # Doit contenir au moins new_rejects (1 reject), dnr_partial (1), new_platinum_month (2)
        types = [i["type"] for i in insights]
        self.assertIn("new_rejects", types)
        self.assertIn("dnr_partial", types)
        self.assertIn("new_platinum_month", types)

    def test_compute_active_insights_sorts_by_severity(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_active_insights

        store, run_id, _ = _make_store_with_data()
        insights = _compute_active_insights(None, store, [run_id], {})
        # warning avant info avant success
        sev_order = {"warning": 0, "info": 1, "success": 2}
        for i in range(len(insights) - 1):
            self.assertLessEqual(
                sev_order.get(insights[i]["severity"], 9),
                sev_order.get(insights[i + 1]["severity"], 9),
            )

    def test_compute_active_insights_limits_to_5(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_active_insights

        store, run_id, _ = _make_store_with_data()
        insights = _compute_active_insights(None, store, [run_id], {})
        self.assertLessEqual(len(insights), 5)

    def test_compute_active_insights_filter_hints_structure(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_active_insights

        store, run_id, _ = _make_store_with_data()
        insights = _compute_active_insights(None, store, [run_id], {})
        for it in insights:
            self.assertIn("type", it)
            self.assertIn("severity", it)
            self.assertIn("count", it)
            self.assertIn("label", it)
            self.assertIn("icon", it)


# ---------------------------------------------------------------------------
# Desktop components (home-widgets.js + home-charts.js)
# ---------------------------------------------------------------------------


class HomeWidgetsDesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "components" / "home-widgets.js").read_text(encoding="utf-8")

    def test_exposes_home_widgets_global(self) -> None:
        self.assertIn("window.HomeWidgets", self.js)

    def test_api_methods(self) -> None:
        for fn in ("renderKpiGrid", "renderInsights", "renderPosterCarousel"):
            self.assertIn(fn, self.js)

    def test_icons_defined(self) -> None:
        for icon in (
            "activity",
            "alert-triangle",
            "alert-circle",
            "film",
            "award",
            "bar-chart",
            "trend-up",
            "trend-down",
            "library",
        ):
            self.assertIn(f'"{icon}"', self.js)

    def test_accessibility(self) -> None:
        self.assertIn('role="list"', self.js)
        self.assertIn('role="listitem"', self.js)
        self.assertIn("aria-label", self.js)

    def test_stagger_animation_used(self) -> None:
        self.assertIn("stagger-item", self.js)
        self.assertIn("--order", self.js)


class HomeChartsDesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "components" / "home-charts.js").read_text(encoding="utf-8")

    def test_exposes_home_charts_global(self) -> None:
        self.assertIn("window.HomeCharts", self.js)

    def test_api_methods(self) -> None:
        for fn in ("renderDonut", "renderLine"):
            self.assertIn(fn, self.js)

    def test_tier_colors_from_design_system(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f"--tier-{tier}-solid", self.js)

    def test_svg_accessibility(self) -> None:
        self.assertIn('role="img"', self.js)
        self.assertIn("aria-label", self.js)


# ---------------------------------------------------------------------------
# Dashboard ES modules parity
# ---------------------------------------------------------------------------


class HomeDashboardModulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.widgets = (_ROOT / "web" / "dashboard" / "components" / "home-widgets.js").read_text(encoding="utf-8")
        self.charts = (_ROOT / "web" / "dashboard" / "components" / "home-charts.js").read_text(encoding="utf-8")

    def test_widgets_es_exports(self) -> None:
        for exp in (
            "export function renderKpiGrid",
            "export function renderInsights",
            "export function renderPosterCarousel",
        ):
            self.assertIn(exp, self.widgets)

    def test_charts_es_exports(self) -> None:
        for exp in ("export function renderDonut", "export function renderLine"):
            self.assertIn(exp, self.charts)

    def test_widgets_imports_escapeHtml(self) -> None:
        self.assertIn('import { escapeHtml } from "../core/dom.js"', self.widgets)

    def test_charts_imports_escapeHtml(self) -> None:
        self.assertIn('import { escapeHtml } from "../core/dom.js"', self.charts)


# ---------------------------------------------------------------------------
# CSS Vague 2
# ---------------------------------------------------------------------------


class Vague2CssTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")

    def test_kpi_classes(self) -> None:
        for cls in (
            ".v5-kpi-grid",
            ".v5-kpi-card",
            ".v5-kpi-label",
            ".v5-kpi-value",
            ".v5-kpi-trend",
            ".v5-kpi-trend--up",
            ".v5-kpi-trend--down",
        ):
            self.assertIn(cls, self.css)

    def test_kpi_tier_variants(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f".v5-kpi-card--tier-{tier}", self.css)

    def test_insight_classes(self) -> None:
        for cls in (
            ".v5-insight-list",
            ".v5-insight-card",
            ".v5-insight-label",
            ".v5-insight-card.is-dismissed",
            ".v5-insight-card--warning",
            ".v5-insight-card--success",
        ):
            self.assertIn(cls, self.css)

    def test_poster_classes(self) -> None:
        for cls in (
            ".v5-poster-carousel",
            ".v5-poster-card",
            ".v5-poster-image",
            ".v5-poster-meta",
            ".v5-poster-title",
        ):
            self.assertIn(cls, self.css)

    def test_donut_classes(self) -> None:
        for cls in (".v5-donut-wrap", ".v5-donut-svg", ".v5-donut-arc", ".v5-donut-legend", ".v5-donut-total"):
            self.assertIn(cls, self.css)

    def test_line_classes(self) -> None:
        for cls in (
            ".v5-line-wrap",
            ".v5-line-svg",
            ".v5-line-path",
            ".v5-line-delta",
            ".v5-line-delta--up",
            ".v5-line-delta--down",
        ):
            self.assertIn(cls, self.css)

    def test_home_v5_section(self) -> None:
        self.assertIn(".home-v5-section", self.css)
        self.assertIn(".home-v5-header", self.css)
        self.assertIn(".home-v5-title", self.css)
        self.assertIn(".home-v5-charts", self.css)


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class IntegrationVague2Tests(unittest.TestCase):
    def test_index_html_loads_vague2_scripts(self) -> None:
        html = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("home-widgets.js", html)
        self.assertIn("home-charts.js", html)

    def test_home_js_has_renderHomeV5Overview(self) -> None:
        js = (_ROOT / "web" / "views" / "home.js").read_text(encoding="utf-8")
        self.assertIn("renderHomeV5Overview", js)
        self.assertIn("v2_tier_distribution", js)
        self.assertIn("trend_30days", js)
        self.assertIn("insights", js)
        self.assertIn("home-v5-overview", js)

    def test_home_js_uses_home_widgets_and_charts(self) -> None:
        """V1-05 : home.js a migre des globals window.HomeWidgets/HomeCharts
        vers des imports ESM (renderKpiGrid, renderInsights, etc.). On verifie
        que les fonctions cles sont effectivement importees / utilisees.
        """
        js = (_ROOT / "web" / "views" / "home.js").read_text(encoding="utf-8")
        # Imports ESM des helpers home v5 (V6 : remplacent les globals window.X).
        self.assertIn("renderKpiGrid", js)
        self.assertIn("renderInsights", js)
        # Charts (donut + line) toujours utilises pour la section Vague 2.
        self.assertIn("renderDonut", js)
        self.assertIn("renderLine", js)


# ---------------------------------------------------------------------------
# Node smoke test dashboard ES modules
# ---------------------------------------------------------------------------


class DashboardSmokeTests(unittest.TestCase):
    def test_modules_import_cleanly(self) -> None:
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node indisponible")
        result = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                "Promise.all(["
                "import('./web/dashboard/components/home-widgets.js'),"
                "import('./web/dashboard/components/home-charts.js'),"
                "]).then(([w,c]) => {"
                "console.log('W:' + Object.keys(w).sort().join(','));"
                "console.log('C:' + Object.keys(c).sort().join(','));"
                "})",
            ],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            # v1.0.0-beta : 60s pour absorber le startup node.js + I/O sur CI
            # Windows partage (etait 15s, timeout sur GitHub Actions).
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("W:renderInsights,renderKpiGrid,renderPosterCarousel", result.stdout)
        self.assertIn("C:renderDonut,renderLine", result.stdout)


if __name__ == "__main__":
    unittest.main()
