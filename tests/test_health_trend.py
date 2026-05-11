"""Tests sante bibliotheque continue — item 9.10.

Couvre :
- _compute_health_trend : delta positif/negatif/stable, message, fleche
- _compute_subtitle_coverage : % couverture correct
- Timeline enrichi : health_score present si snapshot, absent sinon
- Edge : 0 runs, 1 run, snapshot null
- UI : graphe SVG dans dashboard + desktop, delta affiche
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.ui.api.dashboard_support import _compute_health_trend
from cinesort.ui.api.run_flow_support import _compute_subtitle_coverage


# ---------------------------------------------------------------------------
# _compute_health_trend
# ---------------------------------------------------------------------------


class HealthTrendTests(unittest.TestCase):
    """Tests du calcul de tendance sante."""

    def test_delta_positive(self) -> None:
        """Score monte → fleche up."""
        timeline = [
            {"health_score": 70, "start_ts": 1000},
            {"health_score": 80, "start_ts": 2000},
            {"health_score": 85, "start_ts": 3000},
        ]
        ht = _compute_health_trend(timeline)
        self.assertEqual(ht["arrow"], "↑")
        self.assertGreater(ht["delta"], 0)
        self.assertIn("↑", ht["message"])

    def test_delta_negative(self) -> None:
        """Score descend → fleche down."""
        timeline = [
            {"health_score": 90, "start_ts": 1000},
            {"health_score": 80, "start_ts": 2000},
        ]
        ht = _compute_health_trend(timeline)
        self.assertEqual(ht["arrow"], "↓")
        self.assertLess(ht["delta"], 0)

    def test_delta_zero(self) -> None:
        """Score stable → fleche stable."""
        timeline = [
            {"health_score": 80, "start_ts": 1000},
            {"health_score": 80, "start_ts": 2000},
        ]
        ht = _compute_health_trend(timeline)
        self.assertEqual(ht["arrow"], "→")
        self.assertEqual(ht["delta"], 0)

    def test_single_run(self) -> None:
        """1 seul run → pas de delta."""
        timeline = [{"health_score": 85, "start_ts": 1000}]
        ht = _compute_health_trend(timeline)
        self.assertEqual(ht["delta"], 0)
        self.assertEqual(ht["current"], 85)

    def test_no_runs(self) -> None:
        """0 runs → pas de donnees."""
        ht = _compute_health_trend([])
        self.assertEqual(ht["delta"], 0)
        self.assertIsNone(ht["current"])

    def test_points_without_snapshot_ignored(self) -> None:
        """Points sans health_score sont ignores."""
        timeline = [
            {"start_ts": 1000},  # pas de health_score
            {"health_score": 70, "start_ts": 2000},
            {"health_score": 85, "start_ts": 3000},
        ]
        ht = _compute_health_trend(timeline)
        self.assertEqual(ht["current"], 85)
        self.assertEqual(ht["delta"], 15)

    def test_all_points_without_snapshot(self) -> None:
        """Tous les points sans health_score → pas de donnees."""
        timeline = [{"start_ts": 1000}, {"start_ts": 2000}]
        ht = _compute_health_trend(timeline)
        self.assertIsNone(ht["current"])


# ---------------------------------------------------------------------------
# _compute_subtitle_coverage
# ---------------------------------------------------------------------------


class SubtitleCoverageTests(unittest.TestCase):
    """Tests du calcul couverture sous-titres."""

    def test_all_complete(self) -> None:
        from types import SimpleNamespace

        rows = [SimpleNamespace(subtitle_missing_langs=[]) for _ in range(5)]
        self.assertEqual(_compute_subtitle_coverage(rows), 100.0)

    def test_some_missing(self) -> None:
        from types import SimpleNamespace

        rows = [
            SimpleNamespace(subtitle_missing_langs=[]),
            SimpleNamespace(subtitle_missing_langs=["fr"]),
            SimpleNamespace(subtitle_missing_langs=[]),
            SimpleNamespace(subtitle_missing_langs=["fr"]),
        ]
        self.assertEqual(_compute_subtitle_coverage(rows), 50.0)

    def test_empty_rows(self) -> None:
        self.assertEqual(_compute_subtitle_coverage([]), 100.0)


# ---------------------------------------------------------------------------
# Metrics in snapshot
# ---------------------------------------------------------------------------


class SnapshotMetricsTests(unittest.TestCase):
    """Tests que le snapshot est genere avec les bonnes metriques."""

    def test_health_snapshot_keys(self) -> None:
        """Le snapshot a les 4 cles attendues."""
        # Simuler un snapshot tel qu'il serait genere
        from cinesort.domain.librarian import generate_suggestions
        from types import SimpleNamespace

        rows = [
            SimpleNamespace(
                row_id="r1",
                proposed_title="Film",
                proposed_source="tmdb",
                confidence=80,
                warning_flags=[],
                subtitle_missing_langs=[],
                tmdb_collection_id=None,
                tmdb_collection_name=None,
            )
        ]
        lib = generate_suggestions(rows, [])
        snapshot = {
            "health_score": lib["health_score"],
            "subtitle_coverage_pct": _compute_subtitle_coverage(rows),
            "resolution_4k_pct": None,
            "codec_modern_pct": None,
        }
        self.assertIn("health_score", snapshot)
        self.assertIn("subtitle_coverage_pct", snapshot)
        self.assertEqual(snapshot["health_score"], 100)
        self.assertEqual(snapshot["subtitle_coverage_pct"], 100.0)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/status.js supprime — adaptation v5 deferee a V5C-03")
class UiHealthTrendTests(unittest.TestCase):
    """Tests presence UI graphe sante."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.status_js = (root / "web" / "dashboard" / "views" / "status.js").read_text(encoding="utf-8")
        cls.quality_js = (root / "web" / "views" / "quality.js").read_text(encoding="utf-8")
        cls.html = (root / "web" / "index.html").read_text(encoding="utf-8")
        cls.dash_css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")

    def test_dashboard_health_chart(self) -> None:
        self.assertIn("health-chart", self.status_js)
        self.assertIn("health_score", self.status_js)

    def test_dashboard_polyline(self) -> None:
        self.assertIn("polyline", self.status_js)

    def test_dashboard_trend_message(self) -> None:
        self.assertIn("health_trend", self.status_js)

    def test_desktop_health_chart(self) -> None:
        self.assertIn("health-chart", self.quality_js)
        self.assertIn("health_trend", self.quality_js)

    def test_desktop_html_container(self) -> None:
        self.assertIn('id="globalHealthTrend"', self.html)

    def test_css_health_chart_dashboard(self) -> None:
        self.assertIn(".health-chart", self.dash_css)

    def test_css_health_chart_desktop(self) -> None:
        self.assertIn(".health-chart", self.app_css)


if __name__ == "__main__":
    unittest.main()
