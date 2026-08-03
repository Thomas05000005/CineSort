"""AUDIT ULTRA 2026-07-13 — H14 (HIGH, lens=E-raw-consumers).

Defaut : le defaut d'approbation de l'ecran Validation etait calcule sur la
CONFIDENCE BRUTE (`Number(r.confidence || 0) >= thrHigh`, seuil 85), ignorant le
verdict backend `auto_approvable` (qui EXCLUT deja les flags bloquants
_AUTO_BLOCKING, cf. history_support._enrich_plan_payload). Consequence : un film
confiance 92 + nfo_year_mismatch (auto_approvable=false) etait PRE-COCHE a tort,
tout en etant liste dans "Cas a verifier" sur le meme ecran.

Fix : un helper unique `_defaultDecisionOk(r)` retourne `r.auto_approvable`
(fallback confiance >= high seulement si le bool n'est pas fourni), partage par
les 4 sites qui doivent bouger ENSEMBLE, sinon _hasUnsavedValidationDecisions
produit un faux "decisions non enregistrees" permanent :

  1. _initDecisionsState          (seed du _decisionsState)
  2. _renderValidationStep        (etat coche de la checkbox)
  3. _renderApplyStep             (compteur "approuves")
  4. _hasUnsavedValidationDecisions (dirty-check vs defaut)

Test = assertion sur la SOURCE JS (le fix est purement front). node --check est
lance a part. Pytest ici verrouille que les 4 sites lisent le verdict backend et
qu'aucun seuil de confiance brute ne subsiste pour le pre-cochage.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_JS = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "traitement.js"


def _read_source() -> str:
    # utf-8-sig : tolere un eventuel BOM (fichiers edites sous Windows).
    return _JS.read_text(encoding="utf-8-sig")


def _slice_function(src: str, name: str) -> str:
    """Corps approximatif d'une fonction top-level : de `function NAME(` jusqu'a
    la prochaine declaration `\\nfunction ` en colonne 0 (ou la fin du fichier).
    Suffisant pour ces 4 fonctions declarees au niveau module."""
    start = src.index(f"function {name}(")
    nxt = src.find("\nfunction ", start + 1)
    return src[start:] if nxt == -1 else src[start:nxt]


class H14ValidationDefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _read_source()

    # --- Le helper unique existe et lit le verdict backend -----------------
    def test_helper_exists_and_reads_auto_approvable(self) -> None:
        self.assertIn(
            "function _defaultDecisionOk(r) {",
            self.src,
            "Le helper partage _defaultDecisionOk doit exister.",
        )
        helper = _slice_function(self.src, "_defaultDecisionOk")
        self.assertIn(
            'typeof r.auto_approvable === "boolean"',
            helper,
            "Le defaut doit s'appuyer sur le verdict backend auto_approvable.",
        )
        self.assertIn(
            "return r.auto_approvable;",
            helper,
            "Quand fourni, auto_approvable doit etre renvoye tel quel (verdict backend).",
        )

    # --- Les 4 sites appellent le helper (source unique partagee) ----------
    def test_four_sites_use_shared_helper(self) -> None:
        for fn, call in (
            ("_initDecisionsState", "_defaultDecisionOk(r)"),
            ("_renderValidationStep", "_defaultDecisionOk(r)"),
            ("_renderApplyStep", "_defaultDecisionOk(r)"),
            ("_hasUnsavedValidationDecisions", "_defaultDecisionOk(row)"),
        ):
            body = _slice_function(self.src, fn)
            self.assertIn(
                call,
                body,
                f"{fn} doit deriver son defaut via {call} (verdict backend).",
            )

        # 4 appels + 1 definition = au moins 5 occurrences du symbole.
        self.assertGreaterEqual(
            self.src.count("_defaultDecisionOk"),
            5,
            "Attendu : 1 definition + 4 sites appelants.",
        )

    # --- Plus aucun pre-cochage sur la confidence BRUTE --------------------
    def test_no_raw_confidence_default_remains(self) -> None:
        forbidden = [
            "else ok = Number(r.confidence || 0) >= thrHigh;",
            "else defaultChecked = conf >= _thr.high;",
            "Number(r.confidence || 0) >= _autoThr",
            "else defaultOk = Number(row.confidence || 0) >= thrHigh;",
        ]
        for line in forbidden:
            self.assertNotIn(
                line,
                self.src,
                f"Pre-cochage sur confidence brute encore present : {line!r}",
            )

        # Les consts de seuil devenues inutiles ont disparu (les 4 sites ne
        # doivent plus declarer de seuil high pour le pre-cochage).
        self.assertNotIn("const _autoThr", self.src)
        self.assertNotRegex(
            self.src,
            r"const\s+thrHigh\s*=",
            "Aucune const thrHigh ne doit subsister apres l'unification H14.",
        )


if __name__ == "__main__":
    unittest.main()
