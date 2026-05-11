"""Tests espace disque intelligent — item 9.8.

Couvre :
- _compute_space_analysis : total, moyenne, by_tier, by_resolution, by_codec, top_wasteful, archivable
- _estimate_file_size : calcul depuis duration + bitrate
- Formule waste_score : size_gb × (100 - score) / 100
- Edge cases : 0 films, taille 0
- UI : section espace dans dashboard + desktop, CSS classes
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.domain.quality_score import _estimate_file_size


# ---------------------------------------------------------------------------
# _estimate_file_size
# ---------------------------------------------------------------------------


class EstimateFileSizeTests(unittest.TestCase):
    """Estimation de la taille fichier depuis duration et bitrate."""

    def test_normal_case(self) -> None:
        """1h30 a 15000 kbps → ~10 Go."""
        probe = {"duration_s": 5400}  # 1h30
        size = _estimate_file_size(probe, 15000)
        # 5400 × 15000 × 1000 / 8 = 10,125,000,000 bytes ≈ 10 Go
        self.assertGreater(size, 9_000_000_000)
        self.assertLess(size, 11_000_000_000)

    def test_zero_duration(self) -> None:
        size = _estimate_file_size({"duration_s": 0}, 15000)
        self.assertEqual(size, 0)

    def test_zero_bitrate(self) -> None:
        size = _estimate_file_size({"duration_s": 5400}, 0)
        self.assertEqual(size, 0)

    def test_none_probe(self) -> None:
        size = _estimate_file_size(None, 15000)
        self.assertEqual(size, 0)


# ---------------------------------------------------------------------------
# _compute_space_analysis
# ---------------------------------------------------------------------------


class SpaceAnalysisTests(unittest.TestCase):
    """Tests de _compute_space_analysis."""

    def _make_store_with_reports(self, reports):
        """Cree un mock store avec des quality reports."""

        class MockStore:
            def __init__(self, reports):
                self._reports = reports

            def list_quality_reports(self, *, run_id):
                return self._reports

        return MockStore(reports)

    def _make_report(
        self,
        *,
        row_id="r1",
        score=80,
        tier="Bon",
        bitrate_kbps=8000,
        duration_s=5400,
        resolution="1080p",
        video_codec="hevc",
    ):
        size = int(duration_s * bitrate_kbps * 1000 / 8) if duration_s and bitrate_kbps else 0
        return {
            "row_id": row_id,
            "score": score,
            "tier": tier,
            "metrics": {
                "detected": {
                    "bitrate_kbps": bitrate_kbps,
                    "duration_s": duration_s,
                    "file_size_bytes": size,
                    "resolution": resolution,
                    "video_codec": video_codec,
                }
            },
        }

    def test_total_bytes(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_space_analysis

        reports = [
            self._make_report(row_id="a", score=90, tier="Premium", bitrate_kbps=20000, duration_s=7200),
            self._make_report(row_id="b", score=30, tier="Mauvais", bitrate_kbps=2000, duration_s=5400),
        ]
        store = self._make_store_with_reports(reports)
        result = _compute_space_analysis(store, "run1")
        self.assertGreater(result["total_bytes"], 0)
        self.assertEqual(result["film_count"], 2)

    def test_by_tier(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_space_analysis

        reports = [
            self._make_report(row_id="a", score=90, tier="Premium", bitrate_kbps=20000),
            self._make_report(row_id="b", score=30, tier="Mauvais", bitrate_kbps=2000),
        ]
        store = self._make_store_with_reports(reports)
        result = _compute_space_analysis(store, "run1")
        self.assertIn("Premium", result["by_tier"])
        self.assertIn("Mauvais", result["by_tier"])
        self.assertGreater(result["by_tier"]["Premium"], result["by_tier"]["Mauvais"])

    def test_by_resolution(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_space_analysis

        reports = [
            self._make_report(row_id="a", resolution="2160p", bitrate_kbps=30000),
            self._make_report(row_id="b", resolution="1080p", bitrate_kbps=8000),
        ]
        store = self._make_store_with_reports(reports)
        result = _compute_space_analysis(store, "run1")
        self.assertIn("2160p", result["by_resolution"])
        self.assertIn("1080p", result["by_resolution"])

    def test_archivable(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_space_analysis

        reports = [
            self._make_report(row_id="a", score=90, tier="Premium"),
            self._make_report(row_id="b", score=20, tier="Mauvais", bitrate_kbps=3000),
            self._make_report(row_id="c", score=25, tier="Mauvais", bitrate_kbps=2000),
        ]
        store = self._make_store_with_reports(reports)
        result = _compute_space_analysis(store, "run1")
        self.assertEqual(result["archivable_count"], 2)
        self.assertGreater(result["archivable_bytes"], 0)

    def test_top_wasteful_sorted(self) -> None:
        """Top gaspilleurs tries par waste_score desc."""
        from cinesort.ui.api.dashboard_support import _compute_space_analysis

        reports = [
            self._make_report(row_id="good", score=95, tier="Premium", bitrate_kbps=20000),
            self._make_report(row_id="bad", score=20, tier="Mauvais", bitrate_kbps=8000),
        ]
        store = self._make_store_with_reports(reports)
        result = _compute_space_analysis(store, "run1")
        top = result["top_wasteful"]
        self.assertGreaterEqual(len(top), 2)
        # Le "bad" (score 20, gros) doit etre en premier
        self.assertEqual(top[0]["row_id"], "bad")
        self.assertGreater(top[0]["waste_score"], top[1]["waste_score"])

    def test_waste_score_formula(self) -> None:
        """waste_score = size_gb × (100 - score) / 100."""
        from cinesort.ui.api.dashboard_support import _compute_space_analysis

        # 1h30 @ 8000 kbps → ~5.4 Go, score 50 → waste = 5.4 * 0.5 = 2.7
        reports = [self._make_report(row_id="mid", score=50, tier="Moyen", bitrate_kbps=8000)]
        store = self._make_store_with_reports(reports)
        result = _compute_space_analysis(store, "run1")
        top = result["top_wasteful"]
        self.assertEqual(len(top), 1)
        # 5400 * 8000 * 1000 / 8 = 5,400,000,000 bytes = 5.03 Go
        # waste = 5.03 * (100-50)/100 = 2.51
        self.assertGreater(top[0]["waste_score"], 2.0)
        self.assertLess(top[0]["waste_score"], 3.0)

    def test_empty_run(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_space_analysis

        store = self._make_store_with_reports([])
        result = _compute_space_analysis(store, "run1")
        self.assertEqual(result["total_bytes"], 0)
        self.assertEqual(result["film_count"], 0)

    def test_no_run_id(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_space_analysis

        store = self._make_store_with_reports([])
        result = _compute_space_analysis(store, "")
        self.assertEqual(result["total_bytes"], 0)

    def test_max_10_wasteful(self) -> None:
        from cinesort.ui.api.dashboard_support import _compute_space_analysis

        reports = [self._make_report(row_id=f"r{i}", score=20 + i, tier="Mauvais") for i in range(15)]
        store = self._make_store_with_reports(reports)
        result = _compute_space_analysis(store, "run1")
        self.assertLessEqual(len(result["top_wasteful"]), 10)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/status.js supprime — adaptation v5 deferee a V5C-03")
class UiSpaceTests(unittest.TestCase):
    """Tests de la presence des sections espace dans l'UI."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.status_js = (root / "web" / "dashboard" / "views" / "status.js").read_text(encoding="utf-8")
        cls.quality_js = (root / "web" / "views" / "quality.js").read_text(encoding="utf-8")
        cls.dash_css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")
        cls.app_css = (root / "web" / "styles.css").read_text(encoding="utf-8")
        cls.html = (root / "web" / "index.html").read_text(encoding="utf-8")

    def test_dashboard_space_section(self) -> None:
        self.assertIn("space_analysis", self.status_js)
        self.assertIn("total_bytes", self.status_js)
        self.assertIn("archivable", self.status_js)

    def test_dashboard_space_bars(self) -> None:
        self.assertIn("space-bar", self.status_js)

    def test_dashboard_format_bytes(self) -> None:
        self.assertIn("_fmtBytes", self.status_js)

    def test_dashboard_top_wasteful(self) -> None:
        self.assertIn("top_wasteful", self.status_js)

    def test_desktop_space_section(self) -> None:
        self.assertIn("space_analysis", self.quality_js)
        self.assertIn("globalSpaceSection", self.quality_js)

    def test_desktop_html_container(self) -> None:
        self.assertIn('id="globalSpaceSection"', self.html)

    def test_css_space_bars_dashboard(self) -> None:
        self.assertIn(".space-bar-track", self.dash_css)
        self.assertIn(".space-bar-fill", self.dash_css)

    def test_css_space_bars_desktop(self) -> None:
        self.assertIn(".space-bar-track", self.app_css)
        self.assertIn(".space-bar-fill", self.app_css)


if __name__ == "__main__":
    unittest.main()
