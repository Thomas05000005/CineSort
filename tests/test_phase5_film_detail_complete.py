"""Tests Phase 5 — Modal Detail Film tri-mode (spec 06, frontend complet).

Couvre :
- Existence du composant film-detail.js
- Export renderFilmDetail (modes A/B/C)
- Consommation des endpoints PR #303 (get_film_full, set_film_tmdb_candidate,
  mark_for_deletion, mark_alert_ignored, run/rescan_row, open_path)
- Onglet "Renommage proposé" present (remplace Comparaison legacy)
- Candidats TMDb avec posters + bouton "Choisir"
- Action "Marquer pour suppression" via dangerConfirmModal
- CSS classes attendues dans components.css
- Cablage bibliotheque + doublons -> renderFilmDetail
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_FILM_DETAIL = _ROOT / "web" / "dashboard" / "components" / "film-detail.js"
_BIBLIOTHEQUE = _ROOT / "web" / "dashboard" / "views" / "bibliotheque.js"
_DOUBLONS = _ROOT / "web" / "dashboard" / "views" / "doublons.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"
_RIGHT_PANEL = _ROOT / "web" / "dashboard" / "components" / "right-panel.js"


class FileExistsTests(unittest.TestCase):
    def test_film_detail_component_exists(self) -> None:
        self.assertTrue(_FILM_DETAIL.is_file(), "Composant film-detail.js absent")

    def test_components_css_exists(self) -> None:
        self.assertTrue(_COMPONENTS_CSS.is_file())


class FilmDetailApiTests(unittest.TestCase):
    """Section 1 + 2 : composant ESM avec modes A/B/C."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _FILM_DETAIL.read_text(encoding="utf-8")

    def test_exports_render_film_detail(self) -> None:
        self.assertIn("export async function renderFilmDetail(", self.js)

    def test_exports_close_film_detail(self) -> None:
        self.assertIn("export function closeFilmDetail(", self.js)

    def test_supports_three_modes(self) -> None:
        # Le code branche selon mode A/B/C
        for mode_lit in ('mode === "A"', 'mode === "B"', 'mode === "C"'):
            self.assertIn(mode_lit, self.js, f"branche {mode_lit} manquante")

    def test_uses_right_panel_for_mode_a(self) -> None:
        self.assertIn("rightPanel.setSections", self.js)
        self.assertIn("rightPanel.setWidth(600)", self.js)

    def test_uses_overlay_for_mode_c(self) -> None:
        self.assertIn("film-detail-modal-overlay", self.js)
        # Esc + clic backdrop ferment
        self.assertIn('ev.key === "Escape"', self.js)
        self.assertIn("closeFilmDetail", self.js)


class EndpointsConsumedTests(unittest.TestCase):
    """Section 2.4 : endpoints backend PR #303 consommes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _FILM_DETAIL.read_text(encoding="utf-8")

    def test_uses_get_film_full(self) -> None:
        self.assertIn("library/get_film_full", self.js)

    def test_uses_set_film_tmdb_candidate(self) -> None:
        self.assertIn("library/set_film_tmdb_candidate", self.js)

    def test_uses_mark_for_deletion(self) -> None:
        self.assertIn("library/mark_for_deletion", self.js)

    def test_uses_mark_alert_ignored(self) -> None:
        self.assertIn("library/mark_alert_ignored", self.js)

    def test_uses_rescan_row(self) -> None:
        self.assertIn("run/rescan_row", self.js)

    def test_uses_save_validation(self) -> None:
        self.assertIn("save_validation", self.js)

    def test_uses_open_path(self) -> None:
        self.assertIn("open_path", self.js)


class SectionsRenderTests(unittest.TestCase):
    """Section 2 : 6 sections layout interne identique modes A/B/C."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _FILM_DETAIL.read_text(encoding="utf-8")

    def test_renders_hero(self) -> None:
        self.assertIn("_renderHero", self.js)
        self.assertIn("film-detail-hero", self.js)

    def test_renders_synopsis(self) -> None:
        self.assertIn("_renderSynopsis", self.js)
        # Spec 3.2 : repliable via <details>
        self.assertIn("<details", self.js)

    def test_renders_alerts(self) -> None:
        self.assertIn("_renderAlerts", self.js)
        # Reutilise alert-labels.js
        self.assertIn("labelsForFlags", self.js)

    def test_renders_candidates_with_posters(self) -> None:
        self.assertIn("_renderCandidate", self.js)
        self.assertIn("film-detail-candidate-poster", self.js)
        # Bouton Choisir
        self.assertIn("choose-candidate", self.js)
        # Badge choisi
        self.assertIn("film-detail-candidate--chosen", self.js)
        self.assertIn("✓ Choisi", self.js)

    def test_renders_4_tabs(self) -> None:
        # Spec 3.5 : Apercu / Analyse V2 / Historique / Renommage propose
        for tab in ('"overview"', '"analysis"', '"history"', '"rename"'):
            self.assertIn(tab, self.js, f"onglet {tab} manquant")

    def test_rename_tab_present(self) -> None:
        """Onglet 'Renommage proposé' remplace Comparison legacy."""
        self.assertIn("_renderRenameTab", self.js)
        self.assertIn("Renommage proposé", self.js)
        # Diff coloré
        self.assertIn("film-detail-rename-diff", self.js)


class ActionsTests(unittest.TestCase):
    """Section 3.6 : 5 actions principales presentes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _FILM_DETAIL.read_text(encoding="utf-8")

    def test_action_validate(self) -> None:
        self.assertIn('data-film-action="validate"', self.js)

    def test_action_analyze_perceptual(self) -> None:
        self.assertIn('data-film-action="analyze-perceptual"', self.js)
        # Ouvre Modal Perceptuelle existante
        self.assertIn("openPerceptualModal", self.js)

    def test_action_open_folder(self) -> None:
        self.assertIn('data-film-action="open-folder"', self.js)

    def test_action_rescan(self) -> None:
        self.assertIn('data-film-action="rescan"', self.js)

    def test_action_mark_delete(self) -> None:
        self.assertIn('data-film-action="mark-delete"', self.js)
        # Utilise dangerConfirmModal (feedback-cinesort-actions-dangereuses)
        self.assertIn("dangerConfirmModal", self.js)

    def test_choose_candidate_shows_toast(self) -> None:
        """Spec 3.4 : direct, sans confirmation + toast renommage maj."""
        self.assertIn("showToast", self.js)
        self.assertIn("Candidat changé", self.js)


class WiringTests(unittest.TestCase):
    """Section 3 : cablage bibliotheque + doublons sur le nouveau composant."""

    def test_bibliotheque_imports_film_detail(self) -> None:
        js = _BIBLIOTHEQUE.read_text(encoding="utf-8")
        self.assertIn("renderFilmDetail", js)
        self.assertIn('from "../components/film-detail.js"', js)

    def test_bibliotheque_uses_mode_a_on_click(self) -> None:
        js = _BIBLIOTHEQUE.read_text(encoding="utf-8")
        # clic carte -> mode A
        self.assertIn('renderFilmDetail({ mode: "A", rowId })', js)

    def test_bibliotheque_uses_mode_c_on_dblclick(self) -> None:
        js = _BIBLIOTHEQUE.read_text(encoding="utf-8")
        # double-clic -> mode C
        self.assertIn('renderFilmDetail({ mode: "C", rowId })', js)

    def test_doublons_imports_film_detail(self) -> None:
        js = _DOUBLONS.read_text(encoding="utf-8")
        self.assertIn("renderFilmDetail", js)
        self.assertIn('from "../components/film-detail.js"', js)

    def test_doublons_voir_fiche_detaillee_mode_c(self) -> None:
        js = _DOUBLONS.read_text(encoding="utf-8")
        self.assertIn("Voir fiche détaillée", js)
        # Mode C depuis doublons (au-dessus du Modal Comparateur)
        self.assertIn('mode: "C"', js)


class RightPanelWidthTests(unittest.TestCase):
    """Mode A : right-panel doit pouvoir aller jusqu'a 600px (au lieu de 480)."""

    def test_max_width_600(self) -> None:
        js = _RIGHT_PANEL.read_text(encoding="utf-8")
        self.assertIn("const MAX_WIDTH = 600", js)


class CssTests(unittest.TestCase):
    """Section 4 : CSS film-detail-* classes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_classes_present(self) -> None:
        for cls_name in (
            ".film-detail",
            ".film-detail-hero",
            ".film-detail-poster",
            ".film-detail-meta",
            ".film-detail-synopsis",
            ".film-detail-alerts-list",
            ".film-detail-candidates-list",
            ".film-detail-candidate",
            ".film-detail-candidate--chosen",
            ".film-detail-candidate-poster",
            ".film-detail-tabs",
            ".film-detail-tab",
            ".film-detail-rename-diff",
            ".film-detail-actions",
            ".film-detail-modal-overlay",
            ".film-detail-modal",
            ".film-detail-modal-close",
        ):
            self.assertIn(cls_name, self.css, f"class CSS {cls_name} manquante")

    def test_braces_balanced(self) -> None:
        """Section 4 : balance accolades a verifier (cf incident #296)."""
        balance = 0
        for ch in self.css:
            if ch == "{":
                balance += 1
            elif ch == "}":
                balance -= 1
        self.assertEqual(balance, 0, f"Accolades CSS desequilibrees : balance={balance}")


if __name__ == "__main__":
    unittest.main()
