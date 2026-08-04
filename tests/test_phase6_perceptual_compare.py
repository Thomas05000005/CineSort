"""Tests Phase 6 : integration Modal Perceptuelle <-> Modal Comparateur Doublons.

Cf docs/internal/design/refonte_2026_05_17/screens/02-modal-perceptuelle.md §5.

Couvre :
- Import direct de openDuplicateComparatorModal dans perceptual-modal.js (pas
  un window.openDuplicateComparatorModal global, pas un fallback navigateTo
  dans le flow nominal).
- Appel avec les bons parametres (runId, rowA, rowB, readOnly=true).
- Mode readOnly de la Modal Comparateur : pas de footer de decision, juste
  un message + bouton Fermer.
- Pre-chargement de la liste "Comparer avec autre film" a l'ouverture de la
  Modal Perceptuelle (polish UX : pas de "Chargement..." au clic).
- Sanity-check syntaxe (node --check) sur les 2 fichiers modifies.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests._jsexec import node_check

_ROOT = Path(__file__).resolve().parents[1]
_PERCEPTUAL_MODAL = _ROOT / "web" / "dashboard" / "components" / "perceptual-modal.js"
_DUPLICATE_MODAL = _ROOT / "web" / "dashboard" / "components" / "duplicate-comparator-modal.js"


class ImportIntegrationTests(unittest.TestCase):
    """L'import doit etre statique en haut de perceptual-modal.js, pas un
    acces dynamique a window.openDuplicateComparatorModal."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_import_statement_present(self) -> None:
        # Import ES module depuis le fichier dedie
        self.assertIn(
            'import { openDuplicateComparatorModal } from "./duplicate-comparator-modal.js"',
            self.js,
        )

    def test_no_window_fallback_for_open(self) -> None:
        """Le code ne doit plus tester typeof window.openDuplicateComparatorModal."""
        self.assertNotIn("typeof window.openDuplicateComparatorModal", self.js)
        self.assertNotIn("window.openDuplicateComparatorModal?.", self.js)

    def test_pick_compare_calls_direct_function(self) -> None:
        """_onPickCompare doit appeler openDuplicateComparatorModal directement."""
        idx = self.js.find("function _onPickCompare(")
        self.assertGreater(idx, 0, "_onPickCompare doit exister")
        body = self.js[idx : idx + 2500]
        self.assertIn("openDuplicateComparatorModal({", body)
        # Pas de garde "typeof window.openDuplicateComparatorModal" dans le flow nominal
        self.assertNotIn("typeof window.openDuplicateComparatorModal", body)


class ReadOnlyParamTests(unittest.TestCase):
    """L'appel depuis perceptual-modal doit passer readOnly=true."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_readonly_passed(self) -> None:
        self.assertIn("readOnly: true", self.js)

    def test_rowa_rowb_passed(self) -> None:
        """rowA et rowB sont les 2 rows compares."""
        idx = self.js.find("function _onPickCompare(")
        body = self.js[idx : idx + 2500]
        self.assertIn("rowA: rowId", body)
        self.assertIn("rowB: otherRowId", body)

    def test_runid_passed(self) -> None:
        idx = self.js.find("function _onPickCompare(")
        body = self.js[idx : idx + 2500]
        self.assertIn("runId", body)


class DuplicateModalReadOnlyTests(unittest.TestCase):
    """duplicate-comparator-modal.js doit gerer le mode readOnly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _DUPLICATE_MODAL.read_text(encoding="utf-8")

    def test_readonly_in_state(self) -> None:
        self.assertIn("readOnly", self.js)

    def test_readonly_skips_decision_footer(self) -> None:
        """En readOnly, _renderFooter ne doit pas afficher les boutons Garder A/B."""
        idx = self.js.find("function _renderFooter(")
        self.assertGreater(idx, 0)
        body = self.js[idx : idx + 2500]
        self.assertIn("readOnly", body)
        # Le marqueur CSS du footer readonly
        self.assertIn("duplicate-modal-footer--readonly", body)

    def test_groupkey_optional_in_readonly(self) -> None:
        """En readOnly, groupKey peut etre absent (pas requis comme dans la vue Doublons)."""
        # La validation initiale doit tolerer l'absence de groupKey en readOnly
        self.assertIn("(!readOnly && !o.groupKey)", self.js)

    def test_readonly_param_propagated(self) -> None:
        """L'option readOnly doit etre lue depuis opts et stockee dans _state."""
        self.assertIn("o.readOnly === true", self.js)
        # _state stocke aussi readOnly
        idx = self.js.find("export function openDuplicateComparatorModal")
        body = self.js[idx : idx + 2000]
        self.assertIn("readOnly,", body)


class PreloadCompareListTests(unittest.TestCase):
    """Polish §5 : la liste Comparer est pre-chargee a l'ouverture de la modal."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_preload_after_loadAndRender(self) -> None:
        """Apres _loadAndRender() dans openPerceptualModal, on doit appeler _loadCompareList."""
        idx = self.js.find("export async function openPerceptualModal")
        self.assertGreater(idx, 0)
        body = self.js[idx : idx + 3500]
        await_idx = body.find("await _loadAndRender()")
        preload_idx = body.find("_loadCompareList()")
        self.assertGreater(await_idx, 0, "appel a _loadAndRender introuvable")
        self.assertGreater(
            preload_idx,
            await_idx,
            "_loadCompareList doit etre appele APRES _loadAndRender",
        )

    def test_compare_in_flight_guard(self) -> None:
        """_loadCompareList protege contre les double-appels via compareInFlight."""
        self.assertIn("compareInFlight", self.js)

    def test_cache_hit_rerenders_list(self) -> None:
        """Si la liste est deja chargee, _loadCompareList re-rend les items
        au lieu de re-fetch (sinon on verrait "Chargement..." apres rebind)."""
        idx = self.js.find("async function _loadCompareList(")
        self.assertGreater(idx, 0)
        body = self.js[idx : idx + 1500]
        # Si compareLoaded est true, on re-rend la liste depuis _state.compareRows
        self.assertIn("_renderCompareListItems(_state.compareRows || [])", body)

    def test_bind_events_rerenders_cached_list(self) -> None:
        """Apres _setModalContent, si la liste est en cache, on la re-rend."""
        self.assertIn(
            "_state.compareLoaded && Array.isArray(_state.compareRows)",
            self.js,
        )


class NoNavigateToInNominalFlowTests(unittest.TestCase):
    """L'ancien fallback navigateTo via location.hash ne doit etre que dans
    le catch (fallback ultime), pas dans le flow nominal."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_pick_compare_has_try_catch(self) -> None:
        """_onPickCompare doit envelopper l'appel comparateur dans try/catch
        avec le fallback hash dans le catch."""
        idx = self.js.find("function _onPickCompare(")
        body = self.js[idx : idx + 2500]
        self.assertIn("try {", body)
        self.assertIn("} catch", body)
        # Le commentaire mentionne explicitement "fallback"
        self.assertIn("fallback", body.lower())

    def test_pick_compare_no_inline_navigation_outside_catch(self) -> None:
        """Le navigateTo (#/doublons) ne doit pas etre dans le chemin nominal
        de _onPickCompare. On verifie qu'il vient apres le `catch`."""
        idx = self.js.find("function _onPickCompare(")
        body = self.js[idx : idx + 2500]
        catch_idx = body.find("} catch")
        nav_idx = body.find("/doublons?compareA=")
        self.assertGreater(catch_idx, 0, "catch attendu dans _onPickCompare")
        self.assertGreater(
            nav_idx,
            catch_idx,
            "la navigation hash doit etre dans le bloc catch, pas dans le flow nominal",
        )


class NodeSyntaxCheckTests(unittest.TestCase):
    """Syntaxe valide des 2 fichiers modifies.

    `node --check <chemin>` etait utilise ici : mesure du 2026-08-03, cette
    commande sort en 0 sur 47 des 48 `.js` de `web/dashboard/` meme avec une
    erreur de syntaxe averee (modules ESM, aucun `package.json` declarant
    `"type": "module"`). Le controle passe par le verificateur reel
    `scripts/check_js_syntax.mjs`.
    """

    def _node_check(self, path: Path) -> None:
        node_check(self, path)

    def test_perceptual_modal_syntax(self) -> None:
        self._node_check(_PERCEPTUAL_MODAL)

    def test_duplicate_modal_syntax(self) -> None:
        self._node_check(_DUPLICATE_MODAL)


if __name__ == "__main__":
    unittest.main()
