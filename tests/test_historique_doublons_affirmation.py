"""L'onglet Doublons de l'Historique ne doit pas AFFIRMER ce qu'il ignore.

Constat 1 de l'audit du 2026-08-12 (#1031), verifie puis corrige a minima.

`history_support` lit `duplicates_groups` dans `runs.stats_json` avec un `or 0`.
Ce n'est PAS un repli : le scan persiste `dict(stats.__dict__)` et le dataclass
`Stats` ne porte pas cette cle. La valeur est donc un **zero permanent deguise en
repli**, et la branche « aucun groupe » de la vue est la seule atteignable.

Elle affichait : « **Aucun doublon dans ce run.** » — une affirmation, fausse des
qu'un run a detecte des groupes que l'utilisateur n'a pas decides.

CE QUI EST CORRIGE ET CE QUI NE L'EST PAS. Afficher le nombre de groupes
DETECTES demanderait de les persister au scan : nouveau champ dans `Stats`, donc
un arbitrage produit, pas un correctif d'affichage. Ce qui se corrige sans
arbitrage, c'est de dire ce qu'on SAIT (`decided` et `skipped` sont vides) au
lieu de ce qu'on ignore.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

HISTORIQUE_JS = ROOT / "web" / "dashboard" / "views" / "historique.js"

_STUBS = r"""
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
  createElement: () => ({ style: {}, classList: { add() {}, remove() {} }, appendChild() {} }),
  body: { classList: { add() {}, remove() {} } },
};
function apiPost() { return Promise.resolve({ ok: true }); }
function escapeHtml(s) { return String(s == null ? "" : s); }
function showToast() {}
function t(k) { return String(k); }
function formatBytes() { return ""; }
function registerRoute() {}
function navigate() {}
function dangerConfirmModal() {}
function invalidateSettingsCache() {}
// FIDELE AU CONTRAT REEL : `_emptyInline` delegue a `buildEmptyState`, qui rend
// le MESSAGE dans son balisage. Un stub qui rendrait "" ferait passer le test
// « il ne dit plus AUCUN DOUBLON » pour de mauvaises raisons — il ne dirait
// rien du tout, quelle que soit la correction.
function buildEmptyState(o) { return `<div class="empty">${String((o && o.message) || o || "")}</div>`; }
const rightPanel = { setWidth() {}, setExpanded() {}, setContent() {} };
"""

_EXTRA = "export const __rendreDoublons = _renderDoublonsList;\n"
_EXIT = "\nprocess.exit(0);\n"


class LOngletNAffirmePasCeQuIlIgnoreTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _rendre(self, stats_js: str) -> str:
        res = run_module_test(
            HISTORIQUE_JS,
            stubs=_STUBS,
            extra=_EXTRA,
            driver=f"__emit({{ html: M.__rendreDoublons({stats_js}) }});" + _EXIT,
            timeout=90,
        )
        return str(res["html"])

    def test_sans_decision_il_ne_dit_pas_AUCUN_DOUBLON(self) -> None:
        """LE defaut. `duplicates_groups` valant toujours 0, cette branche est la
        SEULE atteignable : la phrase etait donc affichee a tout le monde."""
        html = self._rendre("{ duplicates_decided: [], duplicates_skipped: [] }")

        self.assertNotIn(
            "Aucun doublon dans ce run",
            html,
            "l'ecran AFFIRME qu'il n'y a aucun doublon alors que le backend "
            "n'ecrit jamais `duplicates_groups` : il ne peut pas le savoir",
        )

    def test_il_dit_ce_qu_il_SAIT_et_ouvre_la_vue_Doublons(self) -> None:
        """Ne rien affirmer ne suffit pas : sans porte de sortie, l'utilisateur
        reste sans reponse a la question qu'il se pose."""
        html = self._rendre("{ duplicates_decided: [], duplicates_skipped: [] }")

        self.assertIn("non comptés", html, "l'ecran ne dit plus rien du tout")
        self.assertIn("#/doublons", html, "aucun chemin vers l'ecran qui, lui, peut repondre")

    def test_ZERO_range_se_dit_AUTREMENT_qu_inconnu(self) -> None:
        """LE point des trois etats. Un run reellement sans doublon doit pouvoir
        l'AFFIRMER — c'est la seule chose qui distingue une mesure d'une absence
        de mesure, et c'est tout l'objet de cette suite."""
        inconnu = self._rendre("{ duplicates_decided: [], duplicates_skipped: [] }")
        zero = self._rendre("{ duplicates_decided: [], duplicates_skipped: [], duplicates_groups: 0 }")

        self.assertIn("Aucun doublon détecté", zero, "un 0 MESURE ne s'affirme pas")
        self.assertNotIn("Aucun doublon détecté", inconnu, "l'inconnu s'affirme comme un zero")
        self.assertNotEqual(inconnu, zero, "les deux etats rendent le meme ecran")

    def test_un_compte_NON_NUL_est_montre(self) -> None:
        html = self._rendre("{ duplicates_decided: [], duplicates_skipped: [], duplicates_groups: 12 }")
        self.assertIn("12", html)
        self.assertIn("#/doublons", html)

    def test_avec_des_decisions_le_rendu_les_montre_toujours(self) -> None:
        """CONTRE-EPREUVE : le chemin nominal ne doit pas etre touche."""
        html = self._rendre(
            '{ duplicates_decided: [{ title: "Dune", year: 2024, winner_label: "v1" }], duplicates_skipped: [] }'
        )

        self.assertIn("Dune", html)
        self.assertNotIn("Aucune décision de doublon", html)


if __name__ == "__main__":
    unittest.main()
