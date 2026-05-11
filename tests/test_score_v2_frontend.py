"""Tests §16b v7.5.0 — Score composite V2 frontend.

Couvre :
- components/score-v2.js (desktop IIFE) : fonctions exposees, classes CSS, tooltips FR
- dashboard/components/score-v2.js (ES module) : exports, parite desktop
- styles.css / dashboard/styles.css : variables tier, classes, animations
- Integration validation.js / execution.js / library.js / lib-duplicates.js
- index.html : script charge
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class ScoreV2DesktopComponentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "components" / "score-v2.js").read_text(encoding="utf-8")

    def test_file_exists(self) -> None:
        self.assertTrue((_ROOT / "web" / "components" / "score-v2.js").exists())

    def test_exposes_global_scorev2_namespace(self) -> None:
        self.assertIn("window.ScoreV2", self.js)
        self.assertIn("window.renderScoreV2Container", self.js)
        self.assertIn("window.renderScoreV2CompareHtml", self.js)
        self.assertIn("window.bindScoreV2Events", self.js)

    def test_contains_all_helper_functions(self) -> None:
        for fn in (
            "scoreCircleHtml",
            "scoreGaugeHtml",
            "scoreAccordionHtml",
            "scoreWarningsHtml",
            "renderScoreV2Container",
            "renderScoreV2CompareHtml",
            "bindAccordionEvents",
        ):
            self.assertIn(fn, self.js, f"missing fn: {fn}")

    def test_contains_5_tier_labels(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(tier, self.js.lower())

    def test_contains_fr_tooltips_for_subscore_keys(self) -> None:
        for key in (
            "perceptual_visual",
            "resolution",
            "hdr_validation",
            "lpips_distance",
            "perceptual_audio",
            "spectral_cutoff",
            "drc_category",
            "chromaprint",
            "runtime_match",
            "nfo_consistency",
        ):
            self.assertIn(f"{key}:", self.js, f"missing tooltip key: {key}")

    def test_svg_circle_geometry(self) -> None:
        self.assertIn("stroke-dasharray", self.js)
        self.assertIn("stroke-dashoffset", self.js)

    def test_accordion_keyboard_accessible(self) -> None:
        self.assertIn('tabindex="0"', self.js)
        self.assertIn("aria-expanded", self.js)
        self.assertIn("Enter", self.js)

    def test_escapes_html(self) -> None:
        self.assertIn("&amp;", self.js)
        self.assertIn("&lt;", self.js)

    def test_script_loaded_in_index_html(self) -> None:
        idx = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("score-v2.js", idx)


class ScoreV2DashboardModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "dashboard" / "components" / "score-v2.js").read_text(encoding="utf-8")

    def test_file_exists(self) -> None:
        self.assertTrue((_ROOT / "web" / "dashboard" / "components" / "score-v2.js").exists())

    def test_es_module_exports(self) -> None:
        for exp in (
            "export function scoreCircleHtml",
            "export function scoreGaugeHtml",
            "export function scoreAccordionHtml",
            "export function scoreWarningsHtml",
            "export function renderScoreV2Container",
            "export function renderScoreV2CompareHtml",
            "export function bindScoreV2Events",
        ):
            self.assertIn(exp, self.js, f"missing export: {exp}")

    def test_imports_from_dom(self) -> None:
        self.assertIn('import { escapeHtml } from "../core/dom.js"', self.js)

    def test_parity_with_desktop_tooltips(self) -> None:
        for key in (
            "perceptual_visual",
            "resolution",
            "hdr_validation",
            "lpips_distance",
            "spectral_cutoff",
            "drc_category",
        ):
            self.assertIn(f"{key}:", self.js, f"missing tooltip key: {key}")


class ScoreV2CssTests(unittest.TestCase):
    def setUp(self) -> None:
        self.desktop = (_ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.dashboard = (_ROOT / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_desktop_tier_colors(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f"--tier-{tier}", self.desktop)

    def test_dashboard_tier_colors(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f"--tier-{tier}", self.dashboard)

    def test_core_component_classes_desktop(self) -> None:
        for cls in (
            ".score-circle",
            ".score-gauge-row",
            ".score-gauge-fill",
            ".score-accordion",
            ".score-accordion-section",
            ".score-sub-row",
            ".score-warning",
            ".score-v2-compare",
        ):
            self.assertIn(cls, self.desktop)

    def test_core_component_classes_dashboard(self) -> None:
        for cls in (
            ".score-circle",
            ".score-gauge-row",
            ".score-gauge-fill",
            ".score-accordion",
            ".score-warning",
        ):
            self.assertIn(cls, self.dashboard)

    def test_animations_present(self) -> None:
        self.assertIn("@keyframes scoreGaugeFill", self.desktop)
        self.assertIn("@keyframes scoreGaugeFill", self.dashboard)

    def test_transition_on_circle_fg(self) -> None:
        self.assertIn("stroke-dashoffset", self.desktop)
        self.assertIn("transition", self.desktop)


class ScoreV2IntegrationTests(unittest.TestCase):
    def test_desktop_validation_uses_renderer(self) -> None:
        js = (_ROOT / "web" / "views" / "validation.js").read_text(encoding="utf-8")
        self.assertIn("global_score_v2", js)
        self.assertIn("renderScoreV2Container", js)
        self.assertIn("bindScoreV2Events", js)

    def test_desktop_execution_compare_uses_renderer(self) -> None:
        js = (_ROOT / "web" / "views" / "execution.js").read_text(encoding="utf-8")
        self.assertIn("renderScoreV2CompareHtml", js)
        self.assertIn("global_score_v2_a", js)
        self.assertIn("global_score_v2_b", js)

    def test_dashboard_library_uses_renderer(self) -> None:
        js = (_ROOT / "web" / "dashboard" / "views" / "library.js").read_text(encoding="utf-8")
        self.assertIn("renderScoreV2Container", js)
        self.assertIn("bindScoreV2Events", js)
        self.assertIn("global_score_v2", js)

    @unittest.skip("V5C-01: dashboard/views/library/ supprime — score V2 desormais dans library-v5/film-detail (V5bis)")
    def test_dashboard_duplicates_uses_renderer(self) -> None:
        js = (_ROOT / "web" / "dashboard" / "views" / "library" / "lib-duplicates.js").read_text(encoding="utf-8")
        self.assertIn("renderScoreV2CompareHtml", js)
        self.assertIn("global_score_v2_a", js)
        self.assertIn("global_score_v2_b", js)

    def test_backend_compare_perceptual_exposes_v2(self) -> None:
        py = (_ROOT / "cinesort" / "ui" / "api" / "perceptual_support.py").read_text(encoding="utf-8")
        self.assertIn("global_score_v2_a", py)
        self.assertIn("global_score_v2_b", py)


class ScoreV2NodeSmokeTest(unittest.TestCase):
    """Smoke test : import dynamique du module ES pour verifier les exports."""

    def test_dashboard_module_imports_cleanly(self) -> None:
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node non disponible")
        result = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                "import('./web/dashboard/components/score-v2.js').then(m => {"
                "  const exp = Object.keys(m).sort().join(',');"
                "  console.log('EXPORTS:' + exp);"
                "})",
            ],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scoreCircleHtml", result.stdout)
        self.assertIn("scoreGaugeHtml", result.stdout)
        self.assertIn("renderScoreV2Container", result.stdout)
        self.assertIn("renderScoreV2CompareHtml", result.stdout)


if __name__ == "__main__":
    unittest.main()
