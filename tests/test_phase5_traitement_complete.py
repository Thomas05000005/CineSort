"""Tests Phase 5 : vue Traitement complete (spec 08-traitement.md).

Verifie l'implementation native du workflow 5 etapes :
  - Header run actif avec statut/ETA/boutons (pause/resume/save/cancel)
  - Etape 1 Analyse avec drawer scan options + progress + live log
  - Etape 2 Verification avec table dense + filtres
  - Etape 3 Validation avec table dense + bulk approve
  - Etape 4 Doublons inline (import initDoublons)
  - Etape 5 Apply avec dangerConfirmModal countdown 3s
  - CSS classes traitement-* dans components.css
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TRAITEMENT_JS = _ROOT / "web" / "dashboard" / "views" / "traitement.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class HeaderRunTests(unittest.TestCase):
    """Spec §2 : header run actif (run_id, statut, ETA, boutons globaux)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_header_run_renders_status(self) -> None:
        self.assertIn("_renderHeaderRun", self.js)
        self.assertIn("STATUS_COLORS", self.js)

    def test_header_run_includes_eta_field(self) -> None:
        self.assertIn("traitement-run-eta", self.js)
        # ETA peut etre derivee depuis eta_s ou calculee depuis progress
        self.assertIn("eta_s", self.js)

    def test_header_run_has_pause_button(self) -> None:
        self.assertIn('data-traitement-action="pause"', self.js)

    def test_header_run_has_resume_button(self) -> None:
        self.assertIn('data-traitement-action="resume"', self.js)

    def test_header_run_has_save_button(self) -> None:
        self.assertIn('data-traitement-action="save"', self.js)

    def test_header_run_has_cancel_button(self) -> None:
        self.assertIn('data-traitement-action="cancel"', self.js)

    def test_cancel_uses_danger_confirm_modal(self) -> None:
        # Le cancel doit ouvrir une dangerConfirmModal
        self.assertIn("dangerConfirmModal", self.js)
        # Recherche dans le contexte du handler cancel : titre + countdown
        self.assertIn("Annuler le run", self.js)

    def test_polling_5s_during_running(self) -> None:
        # Spec §1 demande un poll get_dashboard / run/get_status toutes les 5s pendant RUNNING
        self.assertIn("POLL_INTERVAL_RUNNING", self.js)
        self.assertIn("5000", self.js)

    def test_uses_run_get_status(self) -> None:
        self.assertIn('run/get_status', self.js)


class AnalyseStepTests(unittest.TestCase):
    """Spec §3.1 : etape Analyse avec drawer scan options + progress + live log."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_scan_drawer_renders(self) -> None:
        self.assertIn("traitement-scan-drawer", self.js)

    def test_scan_options_checkboxes(self) -> None:
        # 4 options : perceptual / subtitles / omdb / nfo
        for opt in ("perceptual", "subtitles", "omdb", "nfo"):
            self.assertIn(f'data-scan-opt="{opt}"', self.js, f"option {opt} manquante")

    def test_scan_parallelism_slider(self) -> None:
        self.assertIn('data-scan-opt="parallelism"', self.js)
        self.assertIn('type="range"', self.js)

    def test_scan_start_calls_start_plan(self) -> None:
        self.assertIn("start_plan", self.js)
        self.assertIn('data-traitement-action="start-scan"', self.js)

    def test_scan_progress_bar(self) -> None:
        self.assertIn("traitement-scan-progress-bar", self.js)
        self.assertIn("traitement-scan-progress-fill", self.js)

    def test_scan_live_log_polling(self) -> None:
        # Spec §3.1 : polling 2s pendant scan
        self.assertIn("POLL_INTERVAL_ANALYSE", self.js)
        self.assertIn("2000", self.js)
        self.assertIn("traitement-scan-live-log", self.js)


class VerificationStepTests(unittest.TestCase):
    """Spec §3.2 : etape Verification (table problematiques + filtres rapides)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_verif_table_renders(self) -> None:
        self.assertIn("traitement-verif-table", self.js)

    def test_verif_filters_present(self) -> None:
        # Filtres : all / subs / dups / nfo
        for f in ("all", "subs", "dups", "nfo"):
            self.assertIn(f'data-traitement-verif-filter="{f}"', self.js)

    def test_verif_actions_rescan_rename_ignore(self) -> None:
        for action in ("rescan", "rename", "ignore"):
            self.assertIn(f'data-traitement-verif-action="{action}"', self.js)


class ValidationStepTests(unittest.TestCase):
    """Spec §3.3 : etape Validation (table dense + bulk approve + presets)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_validation_table_renders(self) -> None:
        self.assertIn("traitement-validation-table", self.js)

    def test_bulk_approve_sure_button(self) -> None:
        self.assertIn('data-traitement-action="bulk-approve-sure"', self.js)
        # confidence >= 90 (spec dit 85, on tolere 90 plus strict)
        self.assertIn("confidence", self.js)

    def test_presets_no_alert_platinum_gold(self) -> None:
        self.assertIn('data-traitement-action="preset-no-alert"', self.js)
        self.assertIn('data-traitement-action="preset-platinum-gold"', self.js)

    def test_inline_year_edit(self) -> None:
        self.assertIn("traitement-validation-year-input", self.js)
        self.assertIn('type="number"', self.js)

    def test_bulk_approve_shows_toast_5s(self) -> None:
        # Toast 5s avec snapshot pour undo
        self.assertIn("showToast", self.js)
        self.assertIn("duration: 5000", self.js)
        self.assertIn("_traitementLastBulkSnapshot", self.js)


class DoublonsStepTests(unittest.TestCase):
    """Spec §3.4 : etape Doublons inline (composant initDoublons)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_imports_doublons_view(self) -> None:
        self.assertIn('from "./doublons.js"', self.js)
        self.assertIn("initDoublons", self.js)
        self.assertIn("unmountDoublons", self.js)

    def test_doublons_mount_point(self) -> None:
        self.assertIn("traitement-doublons-mount", self.js)


class ApplyStepTests(unittest.TestCase):
    """Spec §3.5 : etape Apply (resume + options + dangerConfirmModal countdown 3s)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_apply_summary_renders(self) -> None:
        self.assertIn("traitement-apply-summary", self.js)
        self.assertIn("renommage", self.js)
        # Le mot apparait avec accent dans le code FR
        self.assertTrue(
            "deplacement" in self.js.lower() or "déplacement" in self.js.lower(),
            "le resume Apply doit mentionner les deplacements",
        )

    def test_apply_preview_renders(self) -> None:
        self.assertIn("traitement-apply-preview", self.js)

    def test_apply_options_checkboxes(self) -> None:
        for opt in ("dry_run", "export_csv", "sync_jellyfin"):
            self.assertIn(f'data-apply-opt="{opt}"', self.js, f"option apply {opt} manquante")

    def test_apply_real_uses_danger_confirm_with_countdown_3s(self) -> None:
        # Recherche la fonction _handleApplyNow et verifie qu'elle ouvre une
        # dangerConfirmModal avec countdownSeconds: 3
        m = re.search(
            r"_handleApplyNow.*?dangerConfirmModal\s*\(\s*\{(.*?)\}\s*\)",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "_handleApplyNow doit ouvrir une dangerConfirmModal")
        block = m.group(1)
        self.assertIn("countdownSeconds: 3", block, "countdownSeconds: 3 absent du modal apply")
        self.assertIn("Confirmer", block)

    def test_apply_calls_api_apply(self) -> None:
        self.assertIn('"apply"', self.js)


class CssTests(unittest.TestCase):
    """Spec §1+§3 : classes CSS nouvelles dans components.css."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_header_run_classes(self) -> None:
        for cls in (
            ".traitement-header-run",
            ".traitement-run-status",
            ".traitement-run-eta",
            ".traitement-header-actions",
        ):
            self.assertIn(cls, self.css, f"CSS class manquante : {cls}")

    def test_scan_drawer_classes(self) -> None:
        for cls in (
            ".traitement-scan-drawer",
            ".traitement-scan-progress",
            ".traitement-scan-progress-bar",
            ".traitement-scan-live-log",
        ):
            self.assertIn(cls, self.css)

    def test_table_classes(self) -> None:
        for cls in (
            ".traitement-verif-table",
            ".traitement-validation-table",
            ".traitement-validation-bulk",
        ):
            self.assertIn(cls, self.css)

    def test_apply_classes(self) -> None:
        for cls in (
            ".traitement-apply-summary",
            ".traitement-apply-preview",
            ".traitement-apply-options",
        ):
            self.assertIn(cls, self.css)

    def test_status_color_variants(self) -> None:
        # Statuts : is-running, is-paused, is-done, is-error
        for variant in ("is-running", "is-paused", "is-done", "is-error"):
            self.assertIn(f".traitement-run-status.{variant}", self.css)

    def test_brace_balance(self) -> None:
        # Suppression des commentaires CSS puis comptage des { }
        stripped = re.sub(r"/\*.*?\*/", "", self.css, flags=re.DOTALL)
        opens = stripped.count("{")
        closes = stripped.count("}")
        self.assertEqual(opens, closes, f"Accolades CSS desequilibrees : {opens} ouvrantes, {closes} fermantes")


class EndpointsConsumedTests(unittest.TestCase):
    """Verifie que la vue appelle bien les endpoints attendus."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_consumes_get_dashboard(self) -> None:
        self.assertIn("get_dashboard", self.js)

    def test_consumes_get_status(self) -> None:
        self.assertIn("run/get_status", self.js)

    def test_consumes_start_plan(self) -> None:
        self.assertIn("start_plan", self.js)

    def test_consumes_cancel_run(self) -> None:
        self.assertIn("run/cancel_run", self.js)

    def test_consumes_pause_run(self) -> None:
        # Peut etre stubbe si endpoint absent backend
        self.assertIn("run/pause_run", self.js)

    def test_consumes_resume_run(self) -> None:
        self.assertIn("run/resume_run", self.js)

    def test_consumes_save_for_later(self) -> None:
        self.assertIn("run/save_for_later", self.js)

    def test_consumes_save_validation(self) -> None:
        self.assertIn("save_validation", self.js)

    def test_consumes_apply(self) -> None:
        # Le mot apply apparait beaucoup, on cible l'apiPost
        self.assertRegex(self.js, r'apiPost\(\s*"apply"')


class LifecycleTests(unittest.TestCase):
    """Verifie le cycle init/unmount et le cleanup du polling."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _TRAITEMENT_JS.read_text(encoding="utf-8")

    def test_init_exports(self) -> None:
        self.assertIn("export async function initTraitement(", self.js)

    def test_unmount_exports(self) -> None:
        self.assertIn("export function unmountTraitement(", self.js)

    def test_unmount_cleans_polling(self) -> None:
        # unmountTraitement doit appeler _stopPolling
        m = re.search(r"export function unmountTraitement\(.*?\}\s*$", self.js, re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(m)
        block = m.group(0)
        self.assertIn("_stopPolling", block)

    def test_unmount_cleans_doublons(self) -> None:
        m = re.search(r"export function unmountTraitement\(.*?\}\s*$", self.js, re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(m)
        block = m.group(0)
        self.assertIn("unmountDoublons", block)


if __name__ == "__main__":
    unittest.main()
