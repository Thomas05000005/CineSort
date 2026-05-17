from __future__ import annotations

import unittest
from pathlib import Path


class ModalFocusTrapContractTests(unittest.TestCase):
    """Contrat du focus trap de la modale (refonte UI v2 : web/components/modal.js)."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        # Depuis la refonte UI v2, les helpers modal/focus sont dans web/components/modal.js
        # (anciennement dans web/ui_shell.js, supprime lors de la migration).
        cls.modal_js = (root / "web" / "components" / "modal.js").read_text(encoding="utf-8")

    def test_modal_module_exposes_focusable_helper(self) -> None:
        self.assertIn("function getFocusableElements(container)", self.modal_js)
        self.assertIn('"button:not([disabled])"', self.modal_js)
        self.assertIn('"[href]"', self.modal_js)
        self.assertIn('"input:not([disabled])"', self.modal_js)
        self.assertIn('"select:not([disabled])"', self.modal_js)
        self.assertIn('"textarea:not([disabled])"', self.modal_js)
        self.assertIn("\"[tabindex]:not([tabindex='-1'])\"", self.modal_js)

    def test_focus_trap_loops_with_tab_and_shift_tab(self) -> None:
        self.assertIn("function trapModalFocus(e, modal)", self.modal_js)
        # Le test est Tab-only : early return si pas Tab
        self.assertIn('e.key !== "Tab"', self.modal_js)
        self.assertIn("getFocusableElements(modal)", self.modal_js)
        # Branches longueur 0 et 1
        self.assertIn("focusables.length === 0", self.modal_js)
        self.assertIn("focusables.length === 1", self.modal_js)
        # Boucle Tab / Shift+Tab
        self.assertIn("e.shiftKey", self.modal_js)
        self.assertIn("last.focus()", self.modal_js)
        self.assertIn("first.focus()", self.modal_js)
        self.assertIn("modal.contains(active)", self.modal_js)

    def test_modal_keydown_keeps_escape_and_restore_focus(self) -> None:
        # Escape ferme la modale active
        self.assertIn('e.key === "Escape"', self.modal_js)
        self.assertIn("state.activeModalId", self.modal_js)
        self.assertIn("closeModal(state.activeModalId)", self.modal_js)
        # Tab declenche le trap focus
        self.assertIn('e.key === "Tab"', self.modal_js)
        self.assertIn("trapModalFocus(e, activeModal)", self.modal_js)
        # Restauration du focus a la fermeture
        self.assertIn("state.modalReturnFocusEl", self.modal_js)
        self.assertIn("restore.focus()", self.modal_js)
        # Focus initial sur le premier element focusable a l'ouverture
        self.assertIn("getFocusableElements(modal)[0]", self.modal_js)


class DashboardModalFocusTrapContractTests(unittest.TestCase):
    """Contrat du focus trap pour la modale dashboard ESM (#217 — preparation
    suppression legacy `web/components/modal.js`).

    L'API ESM dashboard est differente du legacy IIFE :
    - Legacy : `trapModalFocus(e, modal)` + state global `activeModalId`.
    - Dashboard ESM : `trapFocus(modalEl)` attache un handler par modale et
      memorise `_previouslyFocused` directement sur l'overlay (pas de state
      module-level).

    Ce test garantit que la version dashboard respecte WCAG 2.1.2 (focus
    trap) et restore-focus a la fermeture, pour qu'on puisse migrer le test
    desktop vers cette implementation lors du chantier #217.
    """

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.modal_js = (
            root / "web" / "dashboard" / "components" / "modal.js"
        ).read_text(encoding="utf-8")

    def test_dashboard_modal_exports_trap_focus(self) -> None:
        # Export ESM nomme : trapFocus(modalEl).
        self.assertIn("export function trapFocus(modalEl)", self.modal_js)
        # Couvre tous les selecteurs focusables WCAG-compliant.
        self.assertIn("'a[href]'", self.modal_js)
        self.assertIn("'button:not([disabled])'", self.modal_js)
        self.assertIn('\'input:not([disabled]):not([type="hidden"])\'', self.modal_js)
        self.assertIn("'select:not([disabled])'", self.modal_js)
        self.assertIn("'textarea:not([disabled])'", self.modal_js)
        self.assertIn("'[tabindex]:not([tabindex=\"-1\"])'", self.modal_js)

    def test_dashboard_focus_trap_loops_with_tab_and_shift_tab(self) -> None:
        # Tab-only : early return si pas Tab.
        self.assertIn('e.key !== "Tab"', self.modal_js)
        # Branche longueur 0 = preventDefault et stay.
        self.assertIn("focusable.length === 0", self.modal_js)
        # Boucle Tab : sur last -> first.focus(), Shift+Tab : sur first -> last.focus().
        self.assertIn("e.shiftKey", self.modal_js)
        self.assertIn("last.focus()", self.modal_js)
        self.assertIn("first.focus()", self.modal_js)
        self.assertIn("modalEl.contains(active)", self.modal_js)

    def test_dashboard_modal_handles_escape_and_restores_focus(self) -> None:
        # showModal expose un escHandler Escape -> closeModal.
        self.assertIn('e.key === "Escape"', self.modal_js)
        self.assertIn("closeModal()", self.modal_js)
        # Memorise le focus precedent et le restaure a la fermeture.
        self.assertIn("_previouslyFocused", self.modal_js)
        self.assertIn("previous.focus()", self.modal_js)
        # trapFocus est appele au showModal pour activer la capture Tab.
        self.assertIn("trapFocus(overlay)", self.modal_js)


if __name__ == "__main__":
    unittest.main()
