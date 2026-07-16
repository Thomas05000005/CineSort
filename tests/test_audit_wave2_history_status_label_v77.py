"""GATE AUDIT 2026-07-15 (H8) — la décision utilisateur prime sur le tier qualité.

Défaut H8 (frontend) : `_filmStatusLabel` (web/dashboard/views/historique.js)
testait `tier === "reject"` AVANT de lire `film.decision`. Un film dont le TIER
qualité est `reject` mais que l'utilisateur a explicitement ACCEPTÉ
(film.decision = "accepted", tri-état exposé par history_support.py depuis
validation.json) affichait encore « Rejeté ».

La décision UTILISATEUR doit primer sur le tier ; on ne retombe sur le tier QUE
si `decision` est vide. Test d'assertion sur la SOURCE (style
test_bibliotheque_compare_action_v77.py) prouvant que la décision est lue AVANT
le tier. Complété par `node --check` hors pytest.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_HIST = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "historique.js"


class HistoriqueDecisionPrimeTierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _HIST.read_text(encoding="utf-8")
        m = re.search(r"function _filmStatusLabel\(film\) \{(.+?)\n\}", cls.js, re.DOTALL)
        assert m is not None, "fonction _filmStatusLabel introuvable"
        cls.body = m.group(1)

    def test_accepted_decision_read_before_tier(self) -> None:
        # Cœur du défaut H8 : la décision explicite « accepted » doit être testée
        # AVANT la garde `if (tier === "reject")`. On ancre sur `if (tier ...`
        # (forme du code) pour ne pas confondre avec une mention en commentaire.
        idx_accepted = self.body.find('"accepted"')
        idx_tier = self.body.find('if (tier === "reject")')
        self.assertNotEqual(idx_accepted, -1, "la décision 'accepted' n'est jamais testée")
        self.assertNotEqual(idx_tier, -1, "garde tier reject introuvable")
        self.assertLess(
            idx_accepted,
            idx_tier,
            "la décision utilisateur ('accepted') doit être lue AVANT le tier qualité",
        )

    def test_rejected_decision_read_before_tier(self) -> None:
        idx_rejected = self.body.find('dec === "rejected"')
        idx_tier = self.body.find('if (tier === "reject")')
        self.assertNotEqual(idx_rejected, -1, "la décision 'rejected' explicite n'est pas testée")
        self.assertLess(idx_rejected, idx_tier)

    def test_tier_declared_after_decision(self) -> None:
        # La lecture du tier (`const tier`) doit venir APRÈS la résolution des
        # décisions explicites.
        idx_tier_decl = self.body.find("const tier")
        idx_accepted = self.body.find('"accepted"')
        self.assertNotEqual(idx_tier_decl, -1, "déclaration `const tier` introuvable")
        self.assertLess(
            idx_accepted,
            idx_tier_decl,
            "le tier doit être lu APRÈS la résolution de la décision utilisateur",
        )

    def test_accepted_maps_to_approuve_label(self) -> None:
        # accepted/approved -> « Approuvé » (la décision, pas le tier).
        self.assertRegex(self.body, r'dec === "accepted".*?"Approuvé"')

    def test_deferred_tri_state_handled(self) -> None:
        # Le tri-état « deferred » exposé par le backend doit avoir un libellé.
        self.assertIn('dec === "deferred"', self.body,
                      "le tri-état 'deferred' doit être géré")

    def test_empty_decision_falls_back_to_tier(self) -> None:
        # Fallback conservé : décision vide -> le tier `reject` produit « Rejeté ».
        self.assertIn('if (tier === "reject") return { label: "Rejeté"', self.body)


if __name__ == "__main__":
    unittest.main()
