"""UI logic contract tests — v2 architecture.

These tests verify structural invariants of the new modular JS/HTML/CSS
architecture (core/ + components/ + views/ + app.js bootstrap).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


class UiLogicContractsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        web = root / "web"
        cls.index_html = (web / "index.html").read_text(encoding="utf-8")
        cls.styles_css = (web / "styles.css").read_text(encoding="utf-8")
        cls.app_js = (web / "app.js").read_text(encoding="utf-8")

        # Load all JS modules into a combined string
        js_files = []
        for d in ["core", "components", "views"]:
            p = web / d
            if p.is_dir():
                for f in sorted(p.glob("*.js")):
                    js_files.append(f.read_text(encoding="utf-8"))
        js_files.append(cls.app_js)
        cls.front_js = "\n".join(js_files)

    # --- Layout & views ----------------------------------------------------

    def test_views_are_declared(self) -> None:
        """Les 9 vues de la sidebar restauree + home par defaut sont declarees dans le HTML."""
        found = set(re.findall(r'id="view-([a-z]+)"', self.index_html))
        # Sidebar restauree : home/validation/execution/quality + jellyfin/plex/radarr + history/settings
        expected = {"home", "validation", "execution", "quality", "jellyfin", "plex", "radarr", "history", "settings"}
        self.assertTrue(expected.issubset(found), f"Missing views: {expected - found}")

    def test_views_use_section_and_tabpanel(self) -> None:
        for view in ["home", "validation", "execution", "quality", "jellyfin", "plex", "radarr", "history", "settings"]:
            self.assertIn(f'id="view-{view}"', self.index_html)

    def test_home_is_default_active_view(self) -> None:
        self.assertIn('class="view active" id="view-home"', self.index_html)
        self.assertIn('showView("home")', self.app_js)

    def test_sidebar_has_ten_nav_buttons(self) -> None:
        """Sidebar : 10 onglets coeur + 1 onglet Aide (V1-14, FAQ + glossaire)."""
        nav_views = re.findall(r'class="nav-btn[^"]*" data-view="([^"]+)"', self.index_html)
        self.assertEqual(
            len(nav_views), 11, f"Expected 11 nav buttons (10 coeur + Aide), got {len(nav_views)}: {nav_views}"
        )
        expected = {
            "library",
            "home",
            "validation",
            "execution",
            "quality",
            "jellyfin",
            "plex",
            "radarr",
            "history",
            "settings",
            "help",
        }
        self.assertEqual(set(nav_views), expected)

    def test_sidebar_has_brand_and_footer(self) -> None:
        self.assertIn("sidebar-brand", self.index_html)
        self.assertIn("sidebar-footer", self.index_html)
        self.assertIn('id="pillRun"', self.index_html)
        self.assertIn('id="pillStatus"', self.index_html)

    # --- Theme & help buttons ----------------------------------------------

    def test_theme_and_help_buttons_exist(self) -> None:
        self.assertIn('id="btnTheme"', self.index_html)
        self.assertIn('id="btnHelp"', self.index_html)

    # --- Modals ------------------------------------------------------------

    def test_modals_are_declared(self) -> None:
        for modal_id in ["modalHelp", "modalCandidates", "modalActionDialog", "wizardModal"]:
            self.assertIn(f'id="{modal_id}"', self.index_html)

    def test_modal_system_is_present(self) -> None:
        self.assertIn("function openModal(id)", self.front_js)
        self.assertIn("function closeModal(id)", self.front_js)
        self.assertIn("function trapModalFocus(e, modal)", self.front_js)

    # --- Design system tokens ----------------------------------------------

    def test_css_uses_design_tokens(self) -> None:
        for token in [
            "--bg-base",
            "--bg-surface",
            "--bg-raised",
            "--text-primary",
            "--accent",
            "--success",
            "--warning",
            "--danger",
            "--fs-xs",
            "--fs-sm",
            "--fs-body",
            "--fs-lg",
            "--fs-xl",
            "--sp-1",
            "--sp-2",
            "--sp-4",
            "--radius-sm",
            "--radius-md",
        ]:
            self.assertIn(token, self.styles_css)

    def test_css_has_light_mode(self) -> None:
        self.assertIn("body.light", self.styles_css)

    def test_css_uses_manrope_font(self) -> None:
        # V3-02 (v7.7.0) : police partagee dans web/shared/fonts/
        self.assertIn("Manrope", self.styles_css)
        self.assertIn("shared/fonts/Manrope-Variable.ttf", self.styles_css)

    def test_css_has_three_button_variants(self) -> None:
        self.assertIn(".btn--primary", self.styles_css)
        self.assertIn(".btn--danger", self.styles_css)
        self.assertIn(".btn--ghost", self.styles_css)

    # --- Navigation & routing ----------------------------------------------

    def test_show_view_toggles_active_class(self) -> None:
        self.assertIn("function showView(view)", self.front_js)
        self.assertIn('v.classList.toggle("active"', self.front_js)

    def test_navigate_to_loads_view_data(self) -> None:
        self.assertIn("async function navigateTo(view", self.front_js)

    # --- State management --------------------------------------------------

    def test_state_object_has_core_properties(self) -> None:
        for prop in [
            "view:",
            "runId:",
            "lastRunId:",
            "rows:",
            "decisions:",
            "polling:",
            "advancedMode:",
            "activeModalId:",
        ]:
            self.assertIn(prop, self.front_js)

    def test_persistence_helpers_exist(self) -> None:
        self.assertIn("function restoreContextFromStorage()", self.front_js)
        self.assertIn("function persistContextToStorage()", self.front_js)

    def test_context_helpers_exist(self) -> None:
        self.assertIn("function currentContextRunId()", self.front_js)
        self.assertIn("function currentContextRowId()", self.front_js)
        self.assertIn("function setLastRunContext(", self.front_js)

    def test_run_reset_helper_exists(self) -> None:
        self.assertIn("function resetRunScopedState()", self.front_js)

    # --- API layer ---------------------------------------------------------

    def test_api_call_wrapper_exists(self) -> None:
        self.assertIn("async function apiCall(name, fn", self.front_js)

    def test_persist_validation_exists(self) -> None:
        self.assertIn("async function persistValidation()", self.front_js)

    # --- Home view ---------------------------------------------------------

    def test_home_has_env_bar(self) -> None:
        self.assertIn('id="homeEnvBar"', self.index_html)
        self.assertIn('id="homeEnvTmdb"', self.index_html)
        self.assertIn('id="homeEnvProbe"', self.index_html)

    def test_home_has_scan_launcher(self) -> None:
        self.assertIn('id="btnStartPlan"', self.index_html)
        self.assertIn('id="progressFill"', self.index_html)
        self.assertIn('id="logboxPlan"', self.index_html)

    def test_home_has_run_card(self) -> None:
        self.assertIn('id="homeRunCard"', self.index_html)
        self.assertIn('id="homeKpiFilms"', self.index_html)
        self.assertIn('id="homeKpiScore"', self.index_html)

    def test_home_has_signals(self) -> None:
        self.assertIn('id="homeSignalsList"', self.index_html)

    # --- Validation view ---------------------------------------------------

    def test_validation_has_table(self) -> None:
        self.assertIn('id="planTbody"', self.index_html)
        self.assertIn('id="searchBox"', self.index_html)
        self.assertIn('id="filterConf"', self.index_html)

    def test_validation_has_presets(self) -> None:
        self.assertIn('data-preset="review_risk"', self.index_html)
        self.assertIn('data-preset="none"', self.index_html)

    def test_validation_has_inspector(self) -> None:
        self.assertIn('id="valInspector"', self.index_html)
        self.assertIn('id="inspectorTitle"', self.index_html)

    def test_validation_has_save_button(self) -> None:
        self.assertIn('id="btnSaveValidation"', self.index_html)

    def test_validation_keyboard_shortcuts(self) -> None:
        self.assertIn("function _handleValidationKey(e)", self.front_js)
        self.assertIn("function hookKeyboard()", self.front_js)

    # --- Execution view ----------------------------------------------------

    def test_execution_has_apply_controls(self) -> None:
        self.assertIn('id="btnApply"', self.index_html)
        self.assertIn('id="ckDryRun"', self.index_html)
        self.assertIn('id="ckQuarantine"', self.index_html)
        self.assertIn('id="applyResult"', self.index_html)

    def test_execution_has_conflicts_section(self) -> None:
        self.assertIn('id="execConflictsCard"', self.index_html)
        self.assertIn('id="dupTbody"', self.index_html)

    def test_execution_has_undo(self) -> None:
        self.assertIn('id="btnUndoPreview"', self.index_html)
        self.assertIn('id="btnUndoRun"', self.index_html)
        self.assertIn('id="undoResult"', self.index_html)

    def test_execution_has_undo_v5(self) -> None:
        self.assertIn('id="undoV5Tbody"', self.index_html)
        self.assertIn('id="btnUndoV5Load"', self.index_html)
        self.assertIn('id="btnUndoV5Execute"', self.index_html)

    # --- Quality view ------------------------------------------------------

    def test_quality_has_kpis(self) -> None:
        self.assertIn('id="qKpiScore"', self.index_html)
        self.assertIn('id="qKpiPremium"', self.index_html)

    def test_quality_has_distribution(self) -> None:
        self.assertIn('id="distPremium"', self.index_html)
        self.assertIn('id="distGood"', self.index_html)

    def test_quality_has_anomalies(self) -> None:
        self.assertIn('id="qualityAnomaliesTbody"', self.index_html)

    def test_quality_has_stat_grids(self) -> None:
        self.assertIn('id="qualityResolutions"', self.index_html)
        self.assertIn('id="qualityHdr"', self.index_html)
        self.assertIn('id="qualityAudio"', self.index_html)

    # --- History view ------------------------------------------------------

    def test_history_has_export_buttons(self) -> None:
        self.assertIn('id="btnExportJson"', self.index_html)
        self.assertIn('id="btnExportCsv"', self.index_html)
        self.assertIn('id="btnExportHtml"', self.index_html)
        self.assertIn('id="btnExportNfo"', self.index_html)

    def test_history_has_runs_table(self) -> None:
        self.assertIn('id="historyTbody"', self.index_html)

    # --- Settings view -----------------------------------------------------

    def test_settings_has_essential_fields(self) -> None:
        self.assertIn('id="rootsList"', self.index_html)
        self.assertIn('id="inNewRoot"', self.index_html)
        self.assertIn('id="inState"', self.index_html)
        self.assertIn('id="inApiKey"', self.index_html)

    def test_settings_has_jellyfin(self) -> None:
        self.assertIn('id="ckJellyfinEnabled"', self.index_html)
        self.assertIn('id="inJellyfinUrl"', self.index_html)

    def test_settings_has_probe_config(self) -> None:
        self.assertIn('id="selProbeBackend"', self.index_html)
        self.assertIn('id="ckEnableTvDetection"', self.index_html)

    def test_settings_has_save_button(self) -> None:
        self.assertIn('id="btnSaveSettings"', self.index_html)

    def test_settings_has_cleanup_options(self) -> None:
        self.assertIn('id="ckResidualCleanupEnabled"', self.index_html)
        self.assertIn('id="selResidualCleanupScope"', self.index_html)

    def test_shortcuts_modal_exists(self) -> None:
        self.assertIn('id="modalShortcuts"', self.index_html)
        self.assertIn("shortcuts-table", self.index_html)

    def test_keyboard_and_drop_modules_loaded(self) -> None:
        self.assertIn("core/keyboard.js", self.index_html)
        self.assertIn("core/drop.js", self.index_html)

    # --- Onboarding / Wizard -----------------------------------------------

    def test_wizard_steps_exist(self) -> None:
        for i in range(1, 6):
            self.assertIn(f'id="wizStep{i}"', self.index_html)
        self.assertIn('id="wizRoot"', self.index_html)
        self.assertIn('id="wizTmdbKey"', self.index_html)

    def test_wizard_logic_exists(self) -> None:
        self.assertIn("function wizShowStep(n)", self.front_js)
        self.assertIn("async function wizFinish(launchScan)", self.front_js)
        self.assertIn("async function maybeShowWizard()", self.front_js)

    # --- Bridge ------------------------------------------------------------

    def test_bridge_exposes_state_snapshot(self) -> None:
        self.assertIn("window.CineSortBridge", self.front_js)
        self.assertIn("getStateSnapshot()", self.front_js)

    # --- Bootstrap ---------------------------------------------------------

    def test_bootstrap_guard_prevents_double_init(self) -> None:
        self.assertIn("if (appBootstrapped) return;", self.app_js)
        self.assertIn("appBootstrapped = true;", self.app_js)

    def test_startup_loads_settings_and_presets(self) -> None:
        self.assertIn("await loadSettings()", self.app_js)
        self.assertIn("await loadQualityPresets()", self.app_js)
        self.assertIn("await maybeShowWizard()", self.app_js)

    # --- JS module structure -----------------------------------------------

    def test_core_modules_exist(self) -> None:
        root = Path(__file__).resolve().parents[1] / "web" / "core"
        for name in ["dom.js", "state.js", "api.js", "router.js"]:
            self.assertTrue((root / name).exists(), f"Missing core/{name}")

    def test_component_modules_exist(self) -> None:
        root = Path(__file__).resolve().parents[1] / "web" / "components"
        for name in ["modal.js", "status.js", "table.js", "badge.js", "empty-state.js"]:
            self.assertTrue((root / name).exists(), f"Missing components/{name}")

    def test_view_modules_exist(self) -> None:
        root = Path(__file__).resolve().parents[1] / "web" / "views"
        for name in ["home.js", "validation.js", "execution.js", "quality.js", "history.js", "settings.js"]:
            self.assertTrue((root / name).exists(), f"Missing views/{name}")

    def test_scripts_loaded_in_correct_order(self) -> None:
        """Core before components before views before app.js"""
        self.assertIn('src="./core/dom.js"', self.index_html)
        self.assertIn('src="./app.js"', self.index_html)
        dom_idx = self.index_html.index('src="./core/dom.js"')
        app_idx = self.index_html.index('src="./app.js"')
        self.assertLess(dom_idx, app_idx)

    # --- Formatting helpers ------------------------------------------------

    def test_formatting_helpers_exist(self) -> None:
        for fn in ["fmtEta", "fmtSpeed", "fmtDateTime", "fmtDurationSec", "formatMovieLabel"]:
            self.assertIn(f"function {fn}(", self.front_js)

    # --- Apply logic -------------------------------------------------------

    def test_apply_checks_duplicates_before_execution(self) -> None:
        self.assertIn("check_duplicates", self.front_js)
        self.assertIn("async function applySelected()", self.front_js)

    def test_apply_result_formatting(self) -> None:
        self.assertIn("function formatApplyResult(result, dryRun)", self.front_js)

    # --- Undo logic --------------------------------------------------------

    def test_undo_preview_and_execution(self) -> None:
        self.assertIn("async function refreshUndoPreview(", self.front_js)
        self.assertIn("function formatUndoPreview(preview)", self.front_js)

    def test_undo_v5_per_film(self) -> None:
        self.assertIn("async function loadUndoV5Detail()", self.front_js)
        self.assertIn("async function executeUndoV5(dryRun)", self.front_js)


if __name__ == "__main__":
    unittest.main()
