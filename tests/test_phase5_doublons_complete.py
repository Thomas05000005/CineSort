"""Tests Phase 5 : Vue Doublons complete (spec 01-doublons.md).

Couvre :
- Vue doublons.js : poster TMDb, decision badges, navigation clavier,
  bulk perceptual, mark_duplicate_winner sur cartes.
- Modal Comparateur (duplicate-comparator-modal.js) : 3 onglets, decisions.
- Inspecteur droit cable via right-panel.setSections.
- Balance accolades CSS.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DOUBLONS_JS = _ROOT / "web" / "dashboard" / "views" / "doublons.js"
_MODAL_JS = _ROOT / "web" / "dashboard" / "components" / "duplicate-comparator-modal.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


# =============================================================================
# Section 1 : Modal Comparateur (3 onglets)
# =============================================================================


class ComparatorModalFileTests(unittest.TestCase):
    def test_modal_file_exists(self) -> None:
        self.assertTrue(_MODAL_JS.is_file(), "duplicate-comparator-modal.js doit exister")


class ComparatorModalApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _MODAL_JS.read_text(encoding="utf-8")

    def test_exports_open_function(self) -> None:
        self.assertIn("export function openDuplicateComparatorModal", self.js)

    def test_exports_close_function(self) -> None:
        self.assertIn("export function closeDuplicateComparatorModal", self.js)


class ComparatorModalTabsTests(unittest.TestCase):
    """Spec 01 §3 : 3 onglets Apercu / Frames / Audio."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _MODAL_JS.read_text(encoding="utf-8")

    def test_apercu_tab_present(self) -> None:
        self.assertIn('id: "apercu"', self.js)
        self.assertIn("_renderApercu", self.js)

    def test_frames_tab_present(self) -> None:
        self.assertIn('id: "frames"', self.js)
        self.assertIn("_renderFramesPayload", self.js)

    def test_audio_tab_present(self) -> None:
        self.assertIn('id: "audio"', self.js)
        self.assertIn("_renderAudioPayload", self.js)


class ComparatorModalBackendCallsTests(unittest.TestCase):
    """Spec 01 §3 : utilise les endpoints quality/* et run/mark_duplicate_winner."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _MODAL_JS.read_text(encoding="utf-8")

    def test_calls_get_perceptual_compare_frames(self) -> None:
        self.assertIn("quality/get_perceptual_compare_frames", self.js)

    def test_calls_get_perceptual_compare_audio(self) -> None:
        self.assertIn("quality/get_perceptual_compare_audio", self.js)

    def test_calls_mark_duplicate_winner(self) -> None:
        self.assertIn("run/mark_duplicate_winner", self.js)

    def test_lazy_loading_frames_and_audio(self) -> None:
        # Les onglets frames/audio doivent etre charges via _loadFramesTab /
        # _loadAudioTab (lazy), pas en bloc dans le render initial.
        self.assertIn("_loadFramesTab", self.js)
        self.assertIn("_loadAudioTab", self.js)


class ComparatorModalDecisionTests(unittest.TestCase):
    """Spec 01 §3 : boutons Garder A / Garder B / Skip dans le footer."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _MODAL_JS.read_text(encoding="utf-8")

    def test_keep_a_button(self) -> None:
        self.assertIn('data-duplicate-decide="a"', self.js)
        self.assertIn("Garder A", self.js)

    def test_keep_b_button(self) -> None:
        self.assertIn('data-duplicate-decide="b"', self.js)
        self.assertIn("Garder B", self.js)

    def test_skip_button(self) -> None:
        self.assertIn('data-duplicate-decide="skip"', self.js)

    def test_decision_invokes_mark_winner(self) -> None:
        self.assertIn("_decideWinner", self.js)
        # Verifie que le decideWinner appelle bien mark_duplicate_winner avec
        # winner_row_id, group_key, run_id.
        idx = self.js.find("_decideWinner")
        sub = self.js[idx : idx + 3000]
        self.assertIn("winner_row_id", sub)
        self.assertIn("group_key", sub)
        self.assertIn("mark_duplicate_winner", sub)


class ComparatorModalEscapeKeyTests(unittest.TestCase):
    """Spec 01 §3 : Esc ferme le modal."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _MODAL_JS.read_text(encoding="utf-8")

    def test_escape_handler(self) -> None:
        self.assertIn("Escape", self.js)
        self.assertIn("closeDuplicateComparatorModal", self.js)


# =============================================================================
# Section 2 : Vue Doublons enrichie
# =============================================================================


class DoublonsViewBackendCallsTests(unittest.TestCase):
    """Spec 01 §1 + §4 : les nouveaux endpoints sont bien cables."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DOUBLONS_JS.read_text(encoding="utf-8")

    def test_uses_get_film_full_for_posters(self) -> None:
        self.assertIn("library/get_film_full", self.js)

    def test_uses_size_savings_total(self) -> None:
        # Spec §2 "Contexte" : 3.2 Go récupérables vient de size_savings_total
        self.assertIn("size_savings_total", self.js)

    def test_uses_mark_duplicate_winner_from_card(self) -> None:
        self.assertIn("run/mark_duplicate_winner", self.js)

    def test_uses_queue_perceptual_analyses(self) -> None:
        self.assertIn("quality/queue_perceptual_analyses", self.js)

    def test_polls_job_status(self) -> None:
        self.assertIn("quality/get_perceptual_job_status", self.js)


class DoublonsViewUiElementsTests(unittest.TestCase):
    """Spec 01 §1 : poster + decision badge + bulk button."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DOUBLONS_JS.read_text(encoding="utf-8")

    def test_poster_card(self) -> None:
        self.assertIn("doublons-card-poster", self.js)

    def test_decision_badge(self) -> None:
        self.assertIn("duplicate-decision-badge--decided", self.js)
        self.assertIn("Décidé", self.js)

    def test_bulk_perceptual_button(self) -> None:
        self.assertIn("Analyser perceptuel sur", self.js)
        self.assertIn("bulk-perceptual", self.js)

    def test_keep_a_button_on_card(self) -> None:
        self.assertIn('data-side="a"', self.js)
        self.assertIn("Garder A", self.js)

    def test_keep_b_button_on_card(self) -> None:
        self.assertIn('data-side="b"', self.js)
        self.assertIn("Garder B", self.js)


class DoublonsViewRightPanelTests(unittest.TestCase):
    """Spec 01 §2 : inspecteur droit cable via right-panel.setSections."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DOUBLONS_JS.read_text(encoding="utf-8")

    def test_imports_right_panel(self) -> None:
        self.assertIn("right-panel.js", self.js)
        self.assertIn("setSections", self.js)

    def test_right_panel_has_context_section(self) -> None:
        self.assertIn("Contexte", self.js)

    def test_right_panel_has_selected_group_section(self) -> None:
        self.assertIn("Groupe sélectionné", self.js)

    def test_right_panel_has_actions_section(self) -> None:
        # §2 layout : "Suite logique" -> dans notre impl on appelle "Actions"
        self.assertIn("doublons-inspector-actions", self.js)

    def test_right_panel_unmount_clears_sections(self) -> None:
        # Au unmount on doit passer setSections([]) pour eviter de garder
        # les sections d'une vue sur une autre.
        idx = self.js.find("unmountDoublons")
        self.assertGreater(idx, -1)
        sub = self.js[idx : idx + 800]
        self.assertIn("setRightPanelSections", sub)


class DoublonsViewKeyboardNavTests(unittest.TestCase):
    """Spec 01 §2 : navigation clavier ArrowUp/ArrowDown."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DOUBLONS_JS.read_text(encoding="utf-8")

    def test_arrow_down_handler(self) -> None:
        self.assertIn("ArrowDown", self.js)

    def test_arrow_up_handler(self) -> None:
        self.assertIn("ArrowUp", self.js)

    def test_persists_selection(self) -> None:
        # Persistance via localStorage cf §2 "Persistance"
        self.assertIn("cinesort.doublons.selectedGroupKey", self.js)


class DoublonsViewNoLegacyFallbackTests(unittest.TestCase):
    """Le fallback "compare" ne doit plus rediriger vers #/library."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DOUBLONS_JS.read_text(encoding="utf-8")

    def test_compare_opens_new_modal(self) -> None:
        # Verifie que l'action compare passe par le nouveau modal
        self.assertIn("openDuplicateComparatorModal", self.js)

    def test_no_legacy_hash_redirect_on_compare(self) -> None:
        # On a supprime le `window.location.hash = "#/library"` du compare action.
        # On tolere la presence du string dans des commentaires, mais le pattern
        # ".hash = "#/library"" ne doit plus apparaitre pour l'action compare.
        # On extrait le bloc autour de "compare"
        for m in re.finditer(r'_doublons-card-action="compare"', self.js):
            pass  # decoratif : on verifie juste qu'il n'y a plus de redirect.
        # Pattern global : aucun `#/library` n'est utilise comme fallback.
        # Plus precis : ce string ne doit pas etre dans la fonction _bindEvents
        # apres "case \"compare\"". On test simplement qu'on n'a plus le pattern
        # "window.location.hash = \"#/library\"" associe au compare.
        self.assertNotIn('window.location.hash = "#/library"', self.js)


# =============================================================================
# Section 3 : CSS - balance accolades
# =============================================================================


class CssBalanceTests(unittest.TestCase):
    """Verifie qu'on a pas casse la balance d'accolades en appendant."""

    def test_braces_balanced(self) -> None:
        text = _COMPONENTS_CSS.read_text(encoding="utf-8")
        # Strip CSS comments to avoid counting `{` inside them.
        stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        opens = stripped.count("{")
        closes = stripped.count("}")
        self.assertEqual(
            opens,
            closes,
            f"CSS unbalanced: {opens} opens vs {closes} closes (delta {opens - closes})",
        )


class CssClassesPresentTests(unittest.TestCase):
    """Spec 01 §5 : les classes specifiees sont bien definies dans le CSS."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_modal_overlay(self) -> None:
        self.assertIn(".duplicate-modal-overlay", self.css)

    def test_modal_root(self) -> None:
        self.assertIn(".duplicate-modal ", self.css)

    def test_modal_tabs(self) -> None:
        self.assertIn(".duplicate-modal-tabs", self.css)
        self.assertIn(".duplicate-modal-tab", self.css)

    def test_modal_tab_content(self) -> None:
        self.assertIn(".duplicate-modal-tab-content", self.css)

    def test_frames_grid(self) -> None:
        self.assertIn(".duplicate-frames-grid", self.css)
        self.assertIn(".duplicate-frames-col", self.css)

    def test_audio_player(self) -> None:
        self.assertIn(".duplicate-audio-player", self.css)
        self.assertIn(".duplicate-audio-waveform", self.css)

    def test_decision_badges(self) -> None:
        self.assertIn(".duplicate-decision-badge", self.css)
        self.assertIn(".duplicate-decision-badge--decided", self.css)


if __name__ == "__main__":
    unittest.main()
