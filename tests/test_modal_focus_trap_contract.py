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


if __name__ == "__main__":
    unittest.main()
