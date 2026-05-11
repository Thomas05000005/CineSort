"""Tests Vague 5 v7.6.0 — Traitement fusion F1 (scan / review / apply)."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class ProcessingViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "views" / "processing.js").read_text(encoding="utf-8")

    def test_es_module_exports(self) -> None:
        # V5bis-04 : IIFE -> ES module, plus de window.ProcessingV5 global
        self.assertNotIn("window.ProcessingV5", self.js)
        self.assertIn("export async function initProcessing", self.js)

    def test_init_unmount_gotostep_exposed(self) -> None:
        self.assertIn("export async function initProcessing", self.js)
        self.assertIn("export function unmountProcessing", self.js)
        self.assertIn("export function goToStep", self.js)

    def test_3_steps_defined(self) -> None:
        for step in ("scan", "review", "apply"):
            self.assertIn(f'id: "{step}"', self.js)

    def test_step_status_states(self) -> None:
        for status in ("done", "current", "pending", "blocked"):
            self.assertIn(f'"{status}"', self.js)

    def test_uses_core_endpoints(self) -> None:
        for ep in ("start_plan", "get_status", "cancel_run", "load_validation", "save_validation", "apply"):
            self.assertIn(ep, self.js)

    def test_stepper_keyboard_accessible(self) -> None:
        self.assertIn('role="tab"', self.js)
        self.assertIn("aria-selected", self.js)

    def test_bulk_actions_supported(self) -> None:
        for bulk in ("approve-all", "reject-all", "clear"):
            self.assertIn(bulk, self.js)

    def test_apply_dry_run_default(self) -> None:
        self.assertIn("data-v5-dry-run", self.js)
        # Checkbox checked par defaut pour dry-run
        self.assertIn("checked data-v5-dry-run", self.js)

    def test_polling_status_on_running(self) -> None:
        self.assertIn("_pollStatus", self.js)
        self.assertIn("pollTimer", self.js)


class RouterProcessingRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (_ROOT / "web" / "core" / "router.js").read_text(encoding="utf-8")

    def test_processing_alias_removed(self) -> None:
        # L'alias processing -> validation doit etre retire (vraie vue)
        self.assertNotIn('processing: "validation"', self.js)

    def test_navigate_to_processing_helper(self) -> None:
        self.assertIn("_navigateToProcessing", self.js)
        self.assertIn("_hideProcessingOverlay", self.js)

    def test_processing_overlay_ensure(self) -> None:
        self.assertIn("_ensureProcessingOverlay", self.js)
        self.assertIn("processing-overlay", self.js)

    def test_processing_hidden_on_other_views(self) -> None:
        self.assertIn("_hideProcessingOverlay()", self.js)

    def test_film_and_processing_mutually_exclusive(self) -> None:
        # Naviguer a film masque processing, et vice-versa
        self.assertRegex(self.js, r"_navigateToFilm[\s\S]*?_hideProcessingOverlay")
        self.assertRegex(self.js, r"_navigateToProcessing[\s\S]*?_hideFilmDetailOverlay")


class CssVague5Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")

    def test_processing_shell_classes(self) -> None:
        for cls in (
            ".v5-processing-shell",
            ".v5-processing-stepper-wrap",
            ".v5-processing-panel",
            ".v5-processing-overlay",
        ):
            self.assertIn(cls, self.css)

    def test_stepper_classes(self) -> None:
        for cls in (
            ".v5-processing-stepper",
            ".v5-stepper-step",
            ".v5-stepper-circle",
            ".v5-stepper-content",
            ".v5-stepper-label",
            ".v5-stepper-connector",
        ):
            self.assertIn(cls, self.css)

    def test_stepper_state_variants(self) -> None:
        for state in ("is-current", "is-done", "is-blocked"):
            self.assertIn(state, self.css)

    def test_processing_apply_summary_classes(self) -> None:
        for cls in (".v5-processing-apply-summary", ".v5-processing-apply-card", ".v5-processing-apply-value"):
            self.assertIn(cls, self.css)

    def test_review_row_decision_variants(self) -> None:
        self.assertIn(".v5-processing-table tr.row-approved", self.css)
        self.assertIn(".v5-processing-table tr.row-rejected", self.css)

    def test_progress_bar(self) -> None:
        self.assertIn(".v5-processing-progress", self.css)
        self.assertIn(".v5-processing-progress-bar", self.css)

    def test_overlay_active_state(self) -> None:
        self.assertIn(".v5-processing-overlay.is-active", self.css)


class IntegrationVague5Tests(unittest.TestCase):
    def test_index_html_loads_processing_script(self) -> None:
        html = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("processing.js", html)


if __name__ == "__main__":
    unittest.main()
