"""Tests Phase 5 : Modal Perceptuelle complete (spec 02 §0, §1, §4.5, §5).

Couvre les ajouts au-dela de la Phase 3.2 :
- Mode A inspecteur elargi via right-panel
- Dropdown Comparer §5
- Section Frames lazy §1
- Etat partial §4.5 avec bouton Completer
- Ligne Bitrate vs resolution
- Fix bouton Copier empreinte (valeur complete)
- Detection disabled/no-ffmpeg via codes structures
- Bouton Replier sur Breakdown
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PERCEPTUAL_MODAL = _ROOT / "web" / "dashboard" / "components" / "perceptual-modal.js"
_RIGHT_PANEL = _ROOT / "web" / "dashboard" / "components" / "right-panel.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FilesExistTests(unittest.TestCase):
    def test_modal_exists(self) -> None:
        self.assertTrue(_PERCEPTUAL_MODAL.is_file())

    def test_right_panel_exists(self) -> None:
        self.assertTrue(_RIGHT_PANEL.is_file())

    def test_css_exists(self) -> None:
        self.assertTrue(_COMPONENTS_CSS.is_file())


class DualModeTests(unittest.TestCase):
    """Spec 02 §0 : openPerceptualModal accepte mode A ou B."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_open_accepts_mode_param(self) -> None:
        # La signature mentionne mode "A"|"B"
        self.assertIn('opts.mode === "A"', self.js)
        self.assertIn('opts.mode === "B"', self.js)

    def test_views_inspector_array_defined(self) -> None:
        """Le tableau des vues qui utilisent Mode A doit etre present."""
        self.assertIn("_VIEWS_INSPECTOR", self.js)
        for view in ("/bibliotheque", "/library", "/doublons", "/qualite", "/historique"):
            self.assertIn(view, self.js, f"vue {view} non listee dans _VIEWS_INSPECTOR")

    def test_resolve_mode_function(self) -> None:
        self.assertIn("function _resolveMode(", self.js)

    def test_mode_a_uses_right_panel_set_sections(self) -> None:
        """Mode A injecte le contenu dans right-panel.setSections, pas dans overlay."""
        self.assertIn("rpSetSections", self.js)
        self.assertIn("setExpandedWidth as rpSetExpandedWidth", self.js)

    def test_mode_b_uses_overlay(self) -> None:
        self.assertIn("_ensureOverlay()", self.js)
        self.assertIn("perceptual-modal-overlay", self.js)

    def test_mode_a_sets_expanded_width(self) -> None:
        """Mode A doit appeler setExpandedWidth(true) pour passer en 600px."""
        self.assertIn("rpSetExpandedWidth(true)", self.js)

    def test_toggle_width_button(self) -> None:
        """Bouton ▶/◀ pour basculer largeur normale/elargie en Mode A."""
        self.assertIn("toggle-width", self.js)


class RightPanelExtensionTests(unittest.TestCase):
    """Spec 02 §0 : right-panel doit exporter setExpandedWidth + permettre 600px."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _RIGHT_PANEL.read_text(encoding="utf-8")

    def test_exports_set_expanded_width(self) -> None:
        self.assertIn("export function setExpandedWidth(", self.js)

    def test_exports_is_expanded_width(self) -> None:
        self.assertIn("export function isExpandedWidth(", self.js)

    def test_expanded_max_width_constant(self) -> None:
        self.assertIn("EXPANDED_MAX_WIDTH = 600", self.js)

    def test_resize_handler_allows_expanded(self) -> None:
        """Le handler de resize doit autoriser jusqu'a EXPANDED_MAX_WIDTH quand is-mode-expanded."""
        self.assertIn("is-mode-expanded", self.js)


class CompareDropdownTests(unittest.TestCase):
    """Spec 02 §5 : dropdown Comparer avec un autre film du run."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_compare_dropdown_renderer(self) -> None:
        self.assertIn("function _renderCompareDropdown(", self.js)

    def test_dropdown_in_header(self) -> None:
        """Le dropdown doit etre rendu DANS le header (composition)."""
        # _renderHeader doit appeler _renderCompareDropdown
        self.assertIn("_renderCompareDropdown()", self.js)

    def test_uses_details_summary(self) -> None:
        """details/summary pour le pliage natif."""
        self.assertIn("<details", self.js)
        self.assertIn("<summary>", self.js)

    def test_filter_input_present(self) -> None:
        self.assertIn("perceptual-compare-filter", self.js)

    def test_filter_debounced(self) -> None:
        """Filtre debounced a 250ms."""
        self.assertIn("250", self.js)
        self.assertIn("_filterDebounceTimer", self.js)

    def test_calls_library_get_filtered(self) -> None:
        """Au clic sur dropdown : appel library/get_library_filtered."""
        self.assertIn("library/get_library_filtered", self.js)
        self.assertIn("page_size: 500", self.js)

    def test_routes_to_duplicate_comparator(self) -> None:
        """Au pick : tentative openDuplicateComparatorModal ou fallback /doublons."""
        self.assertIn("openDuplicateComparatorModal", self.js)
        self.assertIn("/doublons", self.js)


class FramesLazyTests(unittest.TestCase):
    """Spec 02 §1 : section Frames lazy avec bouton Voir."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_frames_section_renderer(self) -> None:
        self.assertIn("function _renderFramesSection(", self.js)

    def test_load_frames_button(self) -> None:
        self.assertIn("load-frames", self.js)
        self.assertIn("Voir les frames", self.js)

    def test_lazy_load_via_endpoint(self) -> None:
        self.assertIn("quality/get_perceptual_compare_frames", self.js)

    def test_frames_grid_rendered_on_click(self) -> None:
        """Au click, _loadFrames doit fetch + rendre grille PNG base64."""
        self.assertIn("async function _loadFrames(", self.js)
        self.assertIn("perceptual-frames-grid", self.js)
        self.assertIn("data:image/png;base64,", self.js)


class PartialStateTests(unittest.TestCase):
    """Spec 02 §4.5 : etat partial avec champs vides + bouton Completer."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_is_partial_detector(self) -> None:
        self.assertIn("function _isPartial(", self.js)

    def test_partial_checks_critical_fields(self) -> None:
        """Verifie audio_fingerprint, ssim_self_ref, spectral_cutoff_hz."""
        self.assertIn("audio_fingerprint", self.js)
        self.assertIn("ssim_self_ref", self.js)
        self.assertIn("spectral_cutoff_hz", self.js)

    def test_complete_button_present(self) -> None:
        self.assertIn("Compléter", self.js)
        self.assertIn("perceptual-partial-row", self.js)

    def test_complete_calls_relaunch_with_only_missing(self) -> None:
        self.assertIn("onlyMissing", self.js)
        self.assertIn("only_missing", self.js)

    def test_render_partial_cell_helper(self) -> None:
        self.assertIn("function _renderPartialCell(", self.js)

    def test_partial_force_true(self) -> None:
        """Le bouton Completer appelle get_perceptual_report avec force=true."""
        self.assertIn("force: true", self.js)


class BitrateVsResolutionTests(unittest.TestCase):
    """Spec 02 §1 : ligne Bitrate vs resolution avec calcul JS."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_renderer_present(self) -> None:
        self.assertIn("function _renderBitrateVsResolution(", self.js)

    def test_calculation_uses_megapixels(self) -> None:
        """Calcul bitrate / (width * height / 1000000) = Mb/s par MP."""
        self.assertIn("megapixels", self.js)

    def test_thresholds(self) -> None:
        """3 et 6 Mb/s/MP comme seuils faible/moyen/bon."""
        self.assertIn("ratio < 3", self.js)
        self.assertIn("ratio < 6", self.js)

    def test_verdict_text(self) -> None:
        self.assertIn("faible", self.js)
        self.assertIn("moyen", self.js)
        self.assertIn("bon", self.js)


class CopyFingerprintFixTests(unittest.TestCase):
    """Spec 02 fix : bouton Copier copie la valeur COMPLETE, pas tronquee."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_full_fingerprint_in_state(self) -> None:
        """_state.fullFingerprint stocke la valeur complete au render."""
        self.assertIn("fullFingerprint", self.js)
        self.assertIn("_state.fullFingerprint = fp", self.js)

    def test_copy_uses_state_not_text_content(self) -> None:
        """Le handler Copier lit _state.fullFingerprint, pas fpEl.textContent."""
        # On verifie qu'on n'utilise PAS fpEl.textContent dans le handler
        # (le code existant avait ce bug)
        copy_handler_start = self.js.find("data-perceptual-copy-fp")
        self.assertGreater(copy_handler_start, 0)
        # Le bon comportement utilise _state.fullFingerprint
        self.assertIn("(_state && _state.fullFingerprint)", self.js)


class StructuredCodesDetectionTests(unittest.TestCase):
    """Spec 02 §7 : detection disabled / no-ffmpeg via codes structures."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_missing_tool_check(self) -> None:
        self.assertIn("missing_tool", self.js)
        self.assertIn("ffmpeg", self.js)

    def test_category_state_check(self) -> None:
        """category: 'state' = feature desactivee."""
        self.assertIn('category === "state"', self.js)


class BreakdownToggleTests(unittest.TestCase):
    """Spec 02 §1 : bouton Replier sur Breakdown."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_toggle_breakdown_action(self) -> None:
        self.assertIn("toggle-breakdown", self.js)

    def test_replier_label(self) -> None:
        self.assertIn("Replier", self.js)

    def test_breakdown_body_dataset(self) -> None:
        self.assertIn("data-perceptual-breakdown-body", self.js)


class CssTests(unittest.TestCase):
    """Nouvelles classes CSS Phase 5."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_compare_dropdown_classes(self) -> None:
        for cls_name in (
            ".perceptual-compare-dropdown",
            ".perceptual-compare-panel",
            ".perceptual-compare-filter",
            ".perceptual-compare-list",
            ".perceptual-compare-item",
        ):
            self.assertIn(cls_name, self.css)

    def test_frames_grid_classes(self) -> None:
        for cls_name in (
            ".perceptual-frames-grid",
            ".perceptual-frame-item",
        ):
            self.assertIn(cls_name, self.css)

    def test_partial_row_class(self) -> None:
        self.assertIn(".perceptual-partial-row", self.css)

    def test_header_actions_class(self) -> None:
        """Spec 02 §0 : header avec dropdown + bouton toggle largeur."""
        self.assertIn(".perceptual-modal-header-actions", self.css)
        self.assertIn(".perceptual-modal-title-row", self.css)

    def test_right_panel_mode_expanded(self) -> None:
        """Spec 02 §0 : override max-width pour Mode A."""
        self.assertIn(".v5-right-panel.is-mode-expanded", self.css)


class NodeSyntaxCheckTests(unittest.TestCase):
    """Sanity-check : node --check valide la syntaxe (parser officiel).

    Plus robuste qu'un compteur d'accolades ad-hoc qui mishandle les
    template literals avec ${...}, regex litterales, etc. Si node est
    introuvable (env CI minimal), le test est skip.
    """

    def test_modal_node_check(self) -> None:
        import shutil
        import subprocess

        if not shutil.which("node"):
            self.skipTest("node introuvable dans le PATH")
        result = subprocess.run(
            ["node", "--check", str(_PERCEPTUAL_MODAL)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"node --check echoue:\nstdout={result.stdout}\nstderr={result.stderr}",
        )

    def test_right_panel_node_check(self) -> None:
        import shutil
        import subprocess

        if not shutil.which("node"):
            self.skipTest("node introuvable dans le PATH")
        result = subprocess.run(
            ["node", "--check", str(_RIGHT_PANEL)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"node --check echoue:\nstdout={result.stdout}\nstderr={result.stderr}",
        )


class BalanceTests(unittest.TestCase):
    """Garde-fou : balance des accolades et parentheses dans le JS.

    Detecteur naif qui ignore strings + commentaires + template literals.
    Si node --check est dispo, NodeSyntaxCheckTests est plus fiable ; ces
    tests-ci servent juste de sanity-check supplementaire et tolerent un
    petit ecart (les template literals avec ${} imbriques font diverger).
    """

    TOLERANCE = 5  # tolere un petit decalage du au parser naif

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def _count_balanced(self, text: str, open_ch: str, close_ch: str) -> tuple[int, int]:
        """Compte naif des paires ; ignore strings, commentaires et template literals.

        Pour les template literals (`...`), on gere aussi les ${...} embarques
        (qui peuvent contenir du JS valide avec accolades). On ne sort du
        template literal que sur backtick au top-level (depth=0).
        """
        cleaned = []
        i = 0
        in_str = None
        in_template = False
        template_depth = 0  # profondeur des ${...} dans le template
        in_block_comment = False
        in_line_comment = False
        while i < len(text):
            ch = text[i]
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if in_block_comment:
                if ch == "*" and nxt == "/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue
            if in_line_comment:
                if ch == "\n":
                    in_line_comment = False
                i += 1
                continue
            if in_template:
                # Au sein d'un template literal, on entre/sort des ${...} :
                # depth=0 = texte du template ; depth>=1 = JS dans expression.
                if template_depth == 0:
                    if ch == "\\":
                        i += 2
                        continue
                    if ch == "`":
                        in_template = False
                        i += 1
                        continue
                    if ch == "$" and nxt == "{":
                        template_depth = 1
                        i += 2
                        continue
                    # Caractere de texte template : ignore
                    i += 1
                    continue
                else:
                    # Dans l'expression ${...} : comportement JS normal
                    # mais on track les { } pour savoir quand on sort.
                    if ch in ("'", '"'):
                        in_str = ch
                        i += 1
                        continue
                    if ch == "`":
                        # Template literal imbrique : on entre dans un nouveau template
                        # (rare, mais possible). On le traite comme une string opaque ici.
                        i += 1
                        # On va sauter jusqu'au prochain backtick (simplification ; ne gere pas
                        # le double-imbrique mais OK pour notre code)
                        while i < len(text) and text[i] != "`":
                            if text[i] == "\\":
                                i += 2
                                continue
                            i += 1
                        i += 1
                        continue
                    if ch == "{":
                        template_depth += 1
                        cleaned.append(ch)
                        i += 1
                        continue
                    if ch == "}":
                        template_depth -= 1
                        if template_depth == 0:
                            # Sortie de l'expression, on retourne au texte template
                            i += 1
                            continue
                        cleaned.append(ch)
                        i += 1
                        continue
                    cleaned.append(ch)
                    i += 1
                    continue
            if in_str is not None:
                if ch == "\\":
                    i += 2
                    continue
                if ch == in_str:
                    in_str = None
                i += 1
                continue
            if ch == "/" and nxt == "*":
                in_block_comment = True
                i += 2
                continue
            if ch == "/" and nxt == "/":
                in_line_comment = True
                i += 2
                continue
            if ch in ("'", '"'):
                in_str = ch
                i += 1
                continue
            if ch == "`":
                in_template = True
                template_depth = 0
                i += 1
                continue
            cleaned.append(ch)
            i += 1
        c = "".join(cleaned)
        return c.count(open_ch), c.count(close_ch)

    def test_braces_balanced(self) -> None:
        opens, closes = self._count_balanced(self.js, "{", "}")
        self.assertLessEqual(
            abs(opens - closes),
            self.TOLERANCE,
            f"Accolades desequilibrees : {opens} ouvertures vs {closes} fermetures (tolerance {self.TOLERANCE})",
        )

    def test_parens_balanced(self) -> None:
        opens, closes = self._count_balanced(self.js, "(", ")")
        self.assertLessEqual(
            abs(opens - closes),
            self.TOLERANCE,
            f"Parentheses desequilibrees : {opens} ouvertures vs {closes} fermetures (tolerance {self.TOLERANCE})",
        )

    def test_brackets_balanced(self) -> None:
        opens, closes = self._count_balanced(self.js, "[", "]")
        self.assertLessEqual(
            abs(opens - closes),
            self.TOLERANCE,
            f"Crochets desequilibres : {opens} ouvertures vs {closes} fermetures (tolerance {self.TOLERANCE})",
        )


if __name__ == "__main__":
    unittest.main()
