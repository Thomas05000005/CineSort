"""Tests phase 6 doublons : modal Comparateur supporte 3+ fichiers (tabs paire-a-paire).

Spec : docs/internal/design/refonte_2026_05_17/screens/01-doublons.md §3 « Cas 3+ fichiers ».

Tests statiques sur le source du composant JS (style du test_phase5_doublons_complete.py)
+ tests sur alert-labels.js pour les nouveaux codes.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MODAL_JS = _ROOT / "web" / "dashboard" / "components" / "duplicate-comparator-modal.js"
_ALERT_LABELS_JS = _ROOT / "web" / "dashboard" / "core" / "alert-labels.js"


# =============================================================================
# Section 1 : Modal Comparateur — accepte `rows` et affiche les tabs paires
# =============================================================================


class ComparatorModalRowsApiTests(unittest.TestCase):
    """openDuplicateComparatorModal accepte une option `rows` (array)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _MODAL_JS.read_text(encoding="utf-8")

    def test_modal_file_exists(self) -> None:
        self.assertTrue(_MODAL_JS.is_file())

    def test_open_function_accepts_rows_array(self) -> None:
        # On verifie que la doc ou la signature parlent de `rows` comme alternative
        # au couple rowA/rowB.
        self.assertIn("rows", self.js)
        # Le check d'entree doit accepter rows[0/1] comme fallback (pas seulement rowA/rowB).
        self.assertIn("o.rows", self.js)

    def test_builds_pairs_for_3_or_more_rows(self) -> None:
        self.assertIn("_buildPairs", self.js)

    def test_legacy_rowA_rowB_still_supported(self) -> None:
        # Garde-fou retrocompatibilite : si rowA/rowB sont fournis, ca doit
        # continuer a marcher (le test cherche les references dans le state).
        self.assertIn("o.rowA", self.js)
        self.assertIn("o.rowB", self.js)


class ComparatorModalPairsBarTests(unittest.TestCase):
    """Spec 01 §3 « Cas 3+ fichiers » : barre [A vs B] [A vs C] [B vs C]."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _MODAL_JS.read_text(encoding="utf-8")

    def test_renders_pairs_bar(self) -> None:
        self.assertIn("_renderPairsBar", self.js)
        # Les data-attr pour les paires sont presents (utilises par _bindPairsBarEvents).
        self.assertIn("data-duplicate-pair", self.js)

    def test_pairs_use_letter_labels(self) -> None:
        # Les paires sont labellisees "A vs B" / "A vs C" / etc.
        self.assertIn(" vs ", self.js)
        self.assertIn("_letter", self.js)

    def test_pairs_bar_only_when_3_or_more(self) -> None:
        # Le rendu retourne "" si rows.length < 3 -> "if (!_state.rows || _state.rows.length < 3)"
        # ou variante : on cherche le seuil.
        self.assertTrue(
            "_state.rows.length < 3" in self.js
            or "rows.length < 3" in self.js,
            msg="le rendu de la barre paires doit verifier rows.length >= 3",
        )

    def test_switch_pair_handler_present(self) -> None:
        self.assertIn("_switchPair", self.js)


class ComparatorModalMultiWinnerButtonsTests(unittest.TestCase):
    """Spec 01 §3 : footer expose 1 bouton "Garder X" par fichier en mode 3+."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _MODAL_JS.read_text(encoding="utf-8")

    def test_footer_renders_n_buttons_for_n_rows(self) -> None:
        # On cherche le map sur `rows` dans _renderFooter pour generer les boutons.
        idx = self.js.find("_renderFooter")
        self.assertGreater(idx, -1, "_renderFooter doit exister")
        sub = self.js[idx : idx + 2500]
        # Le mode multi-rows utilise .map((r, i)... pour generer les boutons
        self.assertIn(".map((r, i)", sub.replace(" ", "").replace("\n", "").replace("(r,i)", "(r, i)") + sub)
        self.assertIn("Garder", sub)

    def test_decide_winner_supports_numeric_index(self) -> None:
        # En mode 3+ : data-duplicate-decide=0..N (index), pas "a"/"b".
        idx = self.js.find("_decideWinner")
        self.assertGreater(idx, -1)
        sub = self.js[idx : idx + 3000]
        # Le code resout l'index numerique vers rows[idx].row_id
        self.assertIn("Number(side)", sub)
        self.assertIn("rows[idx]", sub)


class ComparatorModalCacheByPairTests(unittest.TestCase):
    """En mode 3+, le cache lazy frames/audio doit etre PAR PAIRE (pas un boolean global)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _MODAL_JS.read_text(encoding="utf-8")

    def test_frames_cache_by_pair(self) -> None:
        self.assertIn("framesLoadedByPair", self.js)

    def test_audio_cache_by_pair(self) -> None:
        self.assertIn("audioLoadedByPair", self.js)

    def test_uses_currentRowIds_helper(self) -> None:
        # Plutot que de lire directement _state.rowA/B, le code resout via la paire active.
        self.assertIn("_currentRowIds", self.js)


# =============================================================================
# Section 2 : alert-labels.js — codes manquants ajoutes (Phase 5/6 re-audit)
# =============================================================================


class AlertLabelsCompletenessTests(unittest.TestCase):
    """Spec 01 §2 : tous les codes warning_flags mentionnes doivent etre mappes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ALERT_LABELS_JS.read_text(encoding="utf-8")

    def test_subtitle_missing_en_mapped(self) -> None:
        self.assertIn("subtitle_missing_en", self.js)

    def test_duplicate_same_root_mapped(self) -> None:
        self.assertIn("duplicate_same_root", self.js)

    def test_low_confidence_tmdb_mapped(self) -> None:
        self.assertIn("low_confidence_tmdb", self.js)

    def test_runtime_mismatch_likely_wrong_film_mapped(self) -> None:
        self.assertIn("runtime_mismatch_likely_wrong_film", self.js)

    def test_each_new_code_has_required_fields(self) -> None:
        # Verifie que chaque nouveau code a au moins icon + label + severity.
        for code in (
            "subtitle_missing_en",
            "duplicate_same_root",
            "low_confidence_tmdb",
            "runtime_mismatch_likely_wrong_film",
        ):
            idx = self.js.find(code + ":")
            self.assertGreater(idx, -1, msg=f"{code} doit etre une cle d'objet")
            block = self.js[idx : idx + 600]
            self.assertIn("icon:", block, msg=f"{code} doit avoir icon:")
            self.assertIn("label:", block, msg=f"{code} doit avoir label:")
            self.assertIn("severity:", block, msg=f"{code} doit avoir severity:")


if __name__ == "__main__":
    unittest.main()
