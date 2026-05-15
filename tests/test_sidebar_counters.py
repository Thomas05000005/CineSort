"""V3-04 — Tests pour les compteurs sidebar (badges validation/application/quality).

Ces tests verifient :
- Le backend (`get_sidebar_counters`) accepte un api avec/sans run et retourne
  toujours les 3 cles attendues avec des entiers.
- Le frontend (HTML/CSS/JS) declare bien les badges, le loader et le polling.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SidebarCountersBackendTests(unittest.TestCase):
    """Tests structurels et de robustesse de get_sidebar_counters."""

    def test_function_exists(self) -> None:
        from cinesort.ui.api.dashboard_support import get_sidebar_counters

        self.assertTrue(callable(get_sidebar_counters))

    def test_returns_expected_keys_when_no_run(self) -> None:
        """Issue #84 PR 10 : dashboard_support appelle api.settings.get_settings()."""
        from cinesort.ui.api.dashboard_support import get_sidebar_counters

        class FakeStore:
            def get_latest_run(self):
                return None

        class FakeSettingsFacade:
            def get_settings(self):
                return {"state_dir": str(Path.cwd())}

        class FakeApi:
            def __init__(self) -> None:
                self.settings = FakeSettingsFacade()

            def _get_or_create_infra(self, _state_dir):
                return FakeStore(), None

        out = get_sidebar_counters(FakeApi())
        for key in ("validation", "application", "quality"):
            self.assertIn(key, out)
            self.assertIsInstance(out[key], int)
            self.assertEqual(out[key], 0)

    def test_returns_zero_dict_on_error(self) -> None:
        """Si get_settings explose, on retourne {0,0,0} (pas une exception)."""
        from cinesort.ui.api.dashboard_support import get_sidebar_counters

        class BrokenSettingsFacade:
            def get_settings(self):
                raise OSError("boom")

        class BrokenApi:
            def __init__(self) -> None:
                self.settings = BrokenSettingsFacade()

        out = get_sidebar_counters(BrokenApi())
        self.assertEqual(out, {"validation": 0, "application": 0, "quality": 0})

    def test_row_needs_review_heuristic(self) -> None:
        from cinesort.ui.api.dashboard_support import _row_needs_review

        class Row:
            def __init__(self, confidence, flags):
                self.confidence = confidence
                self.warning_flags = flags

        # Confiance basse → review
        self.assertTrue(_row_needs_review(Row(50, [])))
        # Confiance haute, pas de flag critique → pas review
        self.assertFalse(_row_needs_review(Row(85, ["minor_thing"])))
        # Confiance haute mais flag critique → review
        self.assertTrue(_row_needs_review(Row(90, ["integrity_header_invalid"])))
        # Aucun flag, confiance moyenne (sous seuil) → review
        self.assertTrue(_row_needs_review(Row(0, [])))


class SidebarCountersApiTests(unittest.TestCase):
    """L'endpoint doit etre expose sur la classe CineSortApi."""

    def test_endpoint_exposed_on_api(self) -> None:
        from cinesort.ui.api.cinesort_api import CineSortApi

        self.assertTrue(hasattr(CineSortApi, "get_sidebar_counters"))
        self.assertTrue(callable(getattr(CineSortApi, "get_sidebar_counters")))


class SidebarCountersFrontendTests(unittest.TestCase):
    """Verifie que la sidebar HTML, le CSS et le JS sont alignes avec l'endpoint."""

    @classmethod
    def setUpClass(cls) -> None:
        repo = Path(__file__).resolve().parents[1]
        cls.html = (repo / "web" / "dashboard" / "index.html").read_text(encoding="utf-8")
        cls.css = (repo / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")
        cls.app_js = (repo / "web" / "dashboard" / "app.js").read_text(encoding="utf-8")
        cls.sidebar_v5_js = (repo / "web" / "dashboard" / "components" / "sidebar-v5.js").read_text(encoding="utf-8")

    def test_badge_spans_present(self) -> None:
        # V5B-01 : sidebar v5 dynamique, le template data-badge-key vit dans sidebar-v5.js.
        self.assertIn("data-badge-key", self.sidebar_v5_js)
        self.assertIn("updateSidebarBadges", self.sidebar_v5_js)

    def test_loader_function_present(self) -> None:
        self.assertIn("_loadSidebarCounters", self.app_js)
        self.assertIn("get_sidebar_counters", self.app_js)

    def test_polling_interval(self) -> None:
        self.assertIn("setInterval(_loadSidebarCounters", self.app_js)
        self.assertIn("30000", self.app_js)

    def test_css_styles(self) -> None:
        self.assertIn(".nav-badge", self.css)
        self.assertIn(".nav-badge--active", self.css)


if __name__ == "__main__":
    unittest.main()
