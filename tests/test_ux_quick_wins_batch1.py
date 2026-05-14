"""Tests d'inspection statique pour les UX quick wins batch 1 (issue #92)."""

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class NotificationsDefaultsTests(unittest.TestCase):
    """Issue #92 quick win #6 : defauts notifs = apply + errors uniquement."""

    def test_save_section_notifications_conservative_defaults(self) -> None:
        from cinesort.ui.api.settings_support import _save_section_notifications

        result = _save_section_notifications({})
        # Apply + Errors = True (utile)
        self.assertEqual(result["notifications_apply_done"], True)
        self.assertEqual(result["notifications_errors"], True)
        # Scan triggered/done + Undo = False (spam pour power user)
        self.assertEqual(result["notifications_scan_triggered"], False)
        self.assertEqual(result["notifications_scan_done"], False)
        self.assertEqual(result["notifications_undo_done"], False)


class DemoBannerDismissButtonTests(unittest.TestCase):
    """Issue #92 quick win #8 : bouton X pour masquer le banner demo."""

    def test_demo_wizard_renders_dismiss_button(self) -> None:
        src = (PROJECT_ROOT / "web" / "dashboard" / "views" / "demo-wizard.js").read_text(encoding="utf-8")
        self.assertIn("btnDismissDemoBanner", src)
        self.assertIn("demo-banner__close", src)
        # Listener click qui retire le banner sans navigateTo
        self.assertIn("btnDismiss?.addEventListener", src)

    def test_demo_banner_close_css_defined(self) -> None:
        css = (PROJECT_ROOT / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".demo-banner__close", css)


class QualityEmptyStateCTATests(unittest.TestCase):
    """Issue #92 quick win #9 : CTA direct install probe dans empty state Quality."""

    def test_quality_empty_state_calls_install_directly(self) -> None:
        src = (PROJECT_ROOT / "web" / "views" / "quality.js").read_text(encoding="utf-8")
        # Le CTA quand probe absent declenche auto_install_probe_tools
        self.assertIn("Installer FFprobe + MediaInfo", src)
        self.assertIn("auto_install_probe_tools", src)


class DemoWizardEscapeKeyTests(unittest.TestCase):
    """Issue #92 quick win #10 : Esc ferme le wizard + toast info."""

    def test_demo_wizard_listens_to_escape_key(self) -> None:
        src = (PROJECT_ROOT / "web" / "dashboard" / "views" / "demo-wizard.js").read_text(encoding="utf-8")
        # On verifie la presence d'un handler keydown qui check Escape
        self.assertIn('e.key !== "Escape"', src)
        self.assertIn("overlay.remove()", src)
        # Et le toast info quand on ferme via Esc
        self.assertIn("Wizard fermé", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
