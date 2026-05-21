"""Tests Phase 6 (Spec 07 Fix 100%) — Inspecteur droit mono-film utilise
renderFilmDetail mode A au lieu d'un rendu local.

Spec 07 §6 + Spec 06 §3.5 : quand un seul film est selectionne (ou focused via
hover/clic) dans la Bibliotheque, l'inspecteur droit doit afficher le composant
FilmDetail mode A (poster + meta + score V2 + alertes + candidats TMDb +
onglets + actions) — pas un rendu local degrade.

Verifications statiques sur web/dashboard/views/bibliotheque.js :
  - L'inspecteur mono-film delegue a renderFilmDetail({mode:"A", rowId, runId}).
  - L'ancien rendu local (poster + <dl> meta + bouton "Ouvrir le détail
    complet" + appel navigateTo) a bien ete supprime.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BIBLIOTHEQUE_JS = _ROOT / "web" / "dashboard" / "views" / "bibliotheque.js"
_FILM_DETAIL_JS = _ROOT / "web" / "dashboard" / "components" / "film-detail.js"


class InspectorDelegatesToFilmDetailTests(unittest.TestCase):
    """L'inspecteur mono-film doit appeler renderFilmDetail mode A."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_renderfilmdetail_imported(self) -> None:
        """L'import du composant FilmDetail existe deja (necessaire pour mode A)."""
        self.assertRegex(
            self.js,
            r"import\s*\{[^}]*renderFilmDetail[^}]*\}\s*from\s*[\"']\.\./components/film-detail\.js[\"']",
        )

    def test_update_inspector_calls_renderfilmdetail_mode_a(self) -> None:
        """_updateInspector pour mono-selection doit invoquer renderFilmDetail
        avec mode:"A" et le rowId (le composant gere son propre mount dans
        right-panel via setSections, donc container n'est pas requis pour A)."""
        m = re.search(
            r"function\s+_updateInspector\s*\([^)]*\)\s*\{(.+?)\n\}\n",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "fonction _updateInspector introuvable")
        body = m.group(1)
        # L'appel renderFilmDetail mode A doit apparaitre dans cette fonction.
        self.assertIn("renderFilmDetail", body)
        self.assertRegex(body, r'mode\s*:\s*[\"\']A[\"\']')
        # Le rowId doit etre passe.
        self.assertIn("rowId", body)
        # Le runId doit etre passe pour permettre au composant de re-charger
        # les bonnes donnees (library/get_film_full attend run_id).
        self.assertIn("runId", body)

    def test_no_more_local_inspector_html(self) -> None:
        """Le rendu local stub (classes "bibliotheque-inspector-meta",
        "bibliotheque-inspector-poster", bouton "Ouvrir le détail complet")
        ne doit plus exister : le composant FilmDetail prend le relais."""
        for forbidden in (
            "bibliotheque-inspector-meta",
            "bibliotheque-inspector-poster",
            "bibliotheque-inspector-warnings",
            "data-bibliotheque-inspect-open",
            "Ouvrir le détail complet",
        ):
            self.assertNotIn(
                forbidden,
                self.js,
                f"Le marqueur du rendu local '{forbidden}' devrait etre supprime",
            )

    def test_no_more_undefined_navigateto_call(self) -> None:
        """L'ancien appel a navigateTo (non importe -> ReferenceError au runtime)
        doit etre supprime puisque le composant FilmDetail gere lui-meme la
        navigation via ses propres handlers."""
        self.assertNotIn("navigateTo(", self.js)

    def test_film_detail_component_supports_mode_a(self) -> None:
        """Sanity-check : le composant cible existe bien et expose renderFilmDetail
        + sait gerer mode A via _ensureModeAContainer (mount dans right-panel)."""
        comp = _FILM_DETAIL_JS.read_text(encoding="utf-8")
        self.assertIn("export async function renderFilmDetail", comp)
        self.assertIn("_ensureModeAContainer", comp)
        # Le mount A delegue a right-panel.setSections (pas besoin de container
        # passe par l'appelant).
        self.assertIn("rightPanel.setSections", comp)


class MultiSelectAggregatesPreservedTests(unittest.TestCase):
    """Le mode multi-selection (agregats : duree, taille, distribution tier)
    n'est PAS impacte par le fix : il reste un rendu local."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _BIBLIOTHEQUE_JS.read_text(encoding="utf-8")

    def test_aggregates_classes_still_present(self) -> None:
        for css_class in (
            "bibliotheque-inspector-aggregates",
            "bibliotheque-inspector-tierdist",
            "bibliotheque-inspector-actions",
        ):
            self.assertIn(css_class, self.js)


if __name__ == "__main__":
    unittest.main()
