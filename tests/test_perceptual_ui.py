"""Tests UI analyse perceptuelle — Phase VIII (item 9.24).

Couvre :
- Settings HTML : section perceptuelle, 11 parametres, sous-sections
- Validation.js : bouton analyse, structure rendu
- Dashboard library.js : bouton analyse + comparer
- Dashboard status.js : indicateur perceptuel
- CSS desktop : badges 5 tiers + cross verdicts + details
- CSS dashboard : badges 5 tiers + cross verdicts
- Settings.js : load + gather perceptual
"""

from __future__ import annotations

import unittest
from pathlib import Path


class PerceptualSettingsHtmlTests(unittest.TestCase):
    """Tests de la section settings perceptuelle dans index.html."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.html = (root / "web" / "index.html").read_text(encoding="utf-8")

    def test_section_present(self) -> None:
        """La section Analyse perceptuelle existe."""
        self.assertIn("Analyse perceptuelle", self.html)

    def test_toggle_enabled(self) -> None:
        self.assertIn("ckPerceptualEnabled", self.html)

    def test_toggle_auto_on_scan(self) -> None:
        self.assertIn("ckPerceptualAutoOnScan", self.html)

    def test_toggle_auto_on_quality(self) -> None:
        self.assertIn("ckPerceptualAutoOnQuality", self.html)

    def test_input_timeout(self) -> None:
        self.assertIn("inPerceptualTimeout", self.html)

    def test_input_frames(self) -> None:
        self.assertIn("inPerceptualFrames", self.html)

    def test_input_skip(self) -> None:
        self.assertIn("inPerceptualSkip", self.html)

    def test_input_dark_weight(self) -> None:
        self.assertIn("inPerceptualDarkWeight", self.html)

    def test_toggle_audio_deep(self) -> None:
        self.assertIn("ckPerceptualAudioDeep", self.html)

    def test_input_audio_segment(self) -> None:
        self.assertIn("inPerceptualAudioSegment", self.html)

    def test_input_comparison_frames(self) -> None:
        self.assertIn("inPerceptualCompFrames", self.html)

    def test_input_comparison_timeout(self) -> None:
        self.assertIn("inPerceptualCompTimeout", self.html)

    def test_subsections_present(self) -> None:
        """Sous-sections Video, Audio, Comparaison presentes."""
        self.assertIn(">Video<", self.html)
        self.assertIn(">Audio<", self.html)
        self.assertIn(">Comparaison<", self.html)


class PerceptualSettingsJsTests(unittest.TestCase):
    """Tests que settings.js gere les parametres perceptuels."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.js = (root / "web" / "views" / "settings.js").read_text(encoding="utf-8")

    def test_load_perceptual_enabled(self) -> None:
        self.assertIn("ckPerceptualEnabled", self.js)
        self.assertIn("perceptual_enabled", self.js)

    def test_gather_perceptual_settings(self) -> None:
        self.assertIn("perceptual_timeout_per_film_s", self.js)
        self.assertIn("perceptual_frames_count", self.js)
        self.assertIn("perceptual_comparison_timeout_s", self.js)


class PerceptualValidationJsTests(unittest.TestCase):
    """Tests du bouton analyse perceptuelle dans validation.js."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.js = (root / "web" / "views" / "validation.js").read_text(encoding="utf-8")

    def test_button_present(self) -> None:
        self.assertIn("btnPerceptual", self.js)
        self.assertIn("Analyse perceptuelle", self.js)

    def test_run_perceptual_function(self) -> None:
        self.assertIn("_runPerceptualAnalysis", self.js)
        self.assertIn("get_perceptual_report", self.js)

    def test_score_display(self) -> None:
        self.assertIn("perceptual-scores", self.js)
        self.assertIn("global_score", self.js)
        self.assertIn("global_tier", self.js)

    def test_cross_verdicts_display(self) -> None:
        self.assertIn("cross-verdict", self.js)
        self.assertIn("cross_verdicts", self.js)

    def test_details_depliable(self) -> None:
        self.assertIn("perceptual-details", self.js)
        self.assertIn("<details", self.js)


class PerceptualDashboardLibraryTests(unittest.TestCase):
    """Tests du bouton perceptuel dans le dashboard library."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.js = (root / "web" / "dashboard" / "views" / "library.js").read_text(encoding="utf-8")

    def test_button_present(self) -> None:
        self.assertIn("btnDashPerceptual", self.js)
        self.assertIn("Analyse perceptuelle", self.js)

    def test_perceptual_function(self) -> None:
        self.assertIn("_loadDashPerceptual", self.js)
        self.assertIn("get_perceptual_report", self.js)


@unittest.skip("V5C-01: dashboard/views/status.js supprime — adaptation v5 deferee a V5C-03")
class PerceptualDashboardStatusTests(unittest.TestCase):
    """Tests de l'indicateur perceptuel dans le dashboard status."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.js = (root / "web" / "dashboard" / "views" / "status.js").read_text(encoding="utf-8")

    def test_indicator_present(self) -> None:
        self.assertIn("perceptual_enabled", self.js)
        self.assertIn("perceptuelle", self.js)


class PerceptualCssDesktopTests(unittest.TestCase):
    """Tests des classes CSS perceptuelles desktop."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.css = (root / "web" / "styles.css").read_text(encoding="utf-8")

    def test_five_tier_badges(self) -> None:
        for tier in ("reference", "excellent", "bon", "mediocre", "degrade"):
            with self.subTest(tier=tier):
                self.assertIn(f".badge--perceptual-{tier}", self.css)

    def test_cross_verdict_classes(self) -> None:
        for sev in ("error", "warning", "info", "positive"):
            with self.subTest(severity=sev):
                self.assertIn(f".cross-verdict--{sev}", self.css)

    def test_perceptual_scores_layout(self) -> None:
        self.assertIn(".perceptual-scores", self.css)

    def test_perceptual_details(self) -> None:
        self.assertIn(".perceptual-details", self.css)


class PerceptualCssDashboardTests(unittest.TestCase):
    """Tests des classes CSS perceptuelles dashboard."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_five_tier_badges(self) -> None:
        for tier in ("reference", "excellent", "bon", "mediocre", "degrade"):
            with self.subTest(tier=tier):
                self.assertIn(f".badge-perceptual-{tier}", self.css)

    def test_cross_verdict_classes(self) -> None:
        for sev in ("error", "warning", "info", "positive"):
            with self.subTest(severity=sev):
                self.assertIn(f".cross-verdict--{sev}", self.css)


if __name__ == "__main__":
    unittest.main()
