"""Tests Phase 6 : drag-select rectangulaire sur la grille Bibliotheque.

Couvre spec 07 §5 : "Drag-select : maintenir clic gauche sur la grille pour
selectionner une zone rectangulaire."

Verifications statiques sur :
- web/dashboard/views/bibliotheque.js : handlers mousedown / mousemove /
  mouseup / Escape, seuil de mouvement, calcul d'intersection, additif
  Ctrl/Cmd/Shift, branchement sur la grille, nettoyage dans unmount.
- web/shared/components.css : classe .bibliotheque-drag-overlay avec border
  dashed accent et background rgba accent semi-transparent.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BIBLIOTHEQUE_JS = _ROOT / "web" / "dashboard" / "views" / "bibliotheque.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


# ---------------------------------------------------------------------------
# 1. Handlers JS : mousedown demarre, mousemove update, mouseup commit, Esc annule
# ---------------------------------------------------------------------------


class DragSelectHandlersTests(unittest.TestCase):
    """Spec 07 §5 : 4 handlers obligatoires."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_mousedown_handler_defined(self) -> None:
        self.assertIn("_onDragSelectMouseDown", self.js)

    def test_mousemove_handler_defined(self) -> None:
        self.assertIn("_onDragSelectMouseMove", self.js)

    def test_mouseup_handler_defined(self) -> None:
        self.assertIn("_onDragSelectMouseUp", self.js)

    def test_escape_handler_defined(self) -> None:
        # La touche Echap est geree dans _onDragSelectKey.
        self.assertIn("_onDragSelectKey", self.js)
        self.assertIn('ev.key === "Escape"', self.js)

    def test_mousedown_started_on_grid(self) -> None:
        # Le listener mousedown est attache sur ".bibliotheque-grid".
        self.assertIn(".bibliotheque-grid", self.js)
        self.assertIn('grid.addEventListener("mousedown"', self.js)

    def test_mousemove_listener_registered_on_window(self) -> None:
        self.assertIn('window.addEventListener("mousemove"', self.js)

    def test_mouseup_listener_registered_on_window(self) -> None:
        self.assertIn('window.addEventListener("mouseup"', self.js)

    def test_keydown_listener_registered_on_window(self) -> None:
        self.assertIn('window.addEventListener("keydown"', self.js)


# ---------------------------------------------------------------------------
# 2. Overlay rectangulaire affiche dans le DOM pendant le drag
# ---------------------------------------------------------------------------


class DragSelectOverlayTests(unittest.TestCase):
    """Overlay DOM cree au franchissement du seuil."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_overlay_class_in_js(self) -> None:
        self.assertIn('"bibliotheque-drag-overlay"', self.js)

    def test_overlay_appended_to_body(self) -> None:
        self.assertIn("document.body.appendChild(overlay)", self.js)

    def test_overlay_css_class_present(self) -> None:
        self.assertIn(".bibliotheque-drag-overlay", self.css)

    def test_overlay_css_uses_accent_dashed_border(self) -> None:
        # Style minimal demande : border 1px dashed accent.
        self.assertRegex(
            self.css,
            r"\.bibliotheque-drag-overlay\s*\{[^}]*border\s*:\s*1px\s+dashed\s+var\(--accent\)",
        )

    def test_overlay_css_uses_translucent_background(self) -> None:
        # Style minimal demande : background rgba accent ~0.1.
        self.assertRegex(
            self.css,
            r"\.bibliotheque-drag-overlay\s*\{[^}]*background\s*:\s*rgba\([^)]*0\.1",
        )

    def test_overlay_uses_fixed_position(self) -> None:
        # Position fixed -> coords viewport, simple a updater.
        self.assertIn('overlay.style.position = "fixed"', self.js)

    def test_overlay_is_pointer_events_none(self) -> None:
        # Doit pas intercepter clics sur les cartes.
        self.assertIn('overlay.style.pointerEvents = "none"', self.js)


# ---------------------------------------------------------------------------
# 3. Intersection rectangle <-> cartes et mise a jour _state.selected
# ---------------------------------------------------------------------------


class DragSelectIntersectionTests(unittest.TestCase):
    """mouseup ajoute les cartes intersectees a _state.selected."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_intersection_helper_defined(self) -> None:
        self.assertIn("_dragSelectIntersect", self.js)

    def test_intersection_iterates_cards(self) -> None:
        self.assertIn(".bibliotheque-card[data-row-id]", self.js)

    def test_intersection_uses_getBoundingClientRect(self) -> None:
        self.assertIn("getBoundingClientRect()", self.js)

    def test_intersection_writes_state_selected(self) -> None:
        self.assertIn("_state.selected = next", self.js)

    def test_intersection_test_excludes_via_4_sides(self) -> None:
        # AABB classique : exclusion sur les 4 cotes (cardRight < rect.left, etc.).
        for token in ("cardRight < rect.left", "cardLeft > rect.right",
                      "cardBottom < rect.top", "cardTop > rect.bottom"):
            self.assertIn(token, self.js, f"intersection AABB : '{token}' manquant")


# ---------------------------------------------------------------------------
# 4. Seuil de mouvement : protege le clic simple / double-clic
# ---------------------------------------------------------------------------


class DragSelectThresholdTests(unittest.TestCase):
    """Seuil de N px avant que le drag soit considere actif."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_threshold_constant_defined(self) -> None:
        self.assertIn("DRAG_THRESHOLD_PX", self.js)

    def test_threshold_value_at_least_3(self) -> None:
        # Capture la valeur numerique declaree.
        import re
        m = re.search(r"DRAG_THRESHOLD_PX\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "DRAG_THRESHOLD_PX doit avoir une valeur entiere")
        val = int(m.group(1))
        self.assertGreaterEqual(val, 3, "seuil doit etre >= 3 px pour proteger les clics")

    def test_threshold_compared_against_dx_dy(self) -> None:
        # Verifie qu'on compare bien le delta absolu vs le seuil.
        self.assertIn("Math.abs(dx) < DRAG_THRESHOLD_PX", self.js)
        self.assertIn("Math.abs(dy) < DRAG_THRESHOLD_PX", self.js)

    def test_mousedown_skips_card_clicks(self) -> None:
        # Pour ne pas casser clic carte : on bail si target.closest(".bibliotheque-card").
        self.assertIn('target.closest(".bibliotheque-card")', self.js)


# ---------------------------------------------------------------------------
# 5. Annulation Esc + nettoyage listeners au unmount
# ---------------------------------------------------------------------------


class DragSelectCancellationTests(unittest.TestCase):
    """Esc annule, et unmountBibliotheque nettoie les listeners window."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_esc_restores_base_selection(self) -> None:
        # Snapshot baseSelection restaure quand Esc.
        self.assertIn("baseSelection", self.js)
        self.assertIn("_state.selected = new Set(_dragSelect.baseSelection)", self.js)

    def test_reset_removes_window_listeners(self) -> None:
        self.assertIn('window.removeEventListener("mousemove"', self.js)
        self.assertIn('window.removeEventListener("mouseup"', self.js)
        self.assertIn('window.removeEventListener("keydown"', self.js)

    def test_reset_removes_overlay(self) -> None:
        self.assertIn("removeChild(_dragSelect.overlay)", self.js)

    def test_unmount_calls_reset(self) -> None:
        # _resetDragSelect doit etre appele dans unmountBibliotheque.
        # On verifie en localisant la fonction puis en cherchant l'appel a l'interieur.
        idx = self.js.find("export function unmountBibliotheque")
        self.assertNotEqual(idx, -1, "unmountBibliotheque doit etre exporte")
        end = self.js.find("\n}", idx)
        self.assertNotEqual(end, -1)
        body = self.js[idx:end]
        self.assertIn("_resetDragSelect()", body,
                      "unmountBibliotheque doit appeler _resetDragSelect()")


# ---------------------------------------------------------------------------
# 6. Drag additif (Ctrl/Cmd/Shift) preserve la selection existante
# ---------------------------------------------------------------------------


class DragSelectAdditiveTests(unittest.TestCase):
    """Ctrl/Cmd ou Shift au mousedown : drag additif."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_additive_modifiers_detected(self) -> None:
        # Reconnait au moins ctrlKey + shiftKey + metaKey au mousedown.
        for modifier in ("ev.ctrlKey", "ev.metaKey", "ev.shiftKey"):
            self.assertIn(modifier, self.js, f"modificateur '{modifier}' manquant")

    def test_additive_seeds_base_selection_from_state(self) -> None:
        # additive => baseSelection = snapshot de _state.selected.
        self.assertIn("new Set(_state.selected)", self.js)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
