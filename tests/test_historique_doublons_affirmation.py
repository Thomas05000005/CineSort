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

SECOND VOLET (audit 2026-09-24). La premiere suite exerce `_renderDoublonsList`
en lui passant son `stats` A LA MAIN : elle prouve que la DECISION distingue les
trois etats, jamais que son SITE D'APPEL lui transmet l'inconnu. Il ne le
faisait pas — le repli de `_ensureHistoryStats` ecrasait la valeur avec `|| 0`,
donc la garde ci-dessus etait correcte et INATTEIGNABLE des que
`run/get_history_stats` echouait. `LeSiteDAppelTransmetLInconnuTests` execute
les deux fonctions de production a la suite.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

HISTORIQUE_JS = ROOT / "web" / "dashboard" / "views" / "historique.js"

_STUBS_COMMUNS = r"""
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
  createElement: () => ({ style: {}, classList: { add() {}, remove() {} }, appendChild() {} }),
  body: { classList: { add() {}, remove() {} } },
};
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

#: `apiPost` par defaut : le rendu seul n'en depend pas.
_API_INERTE = "function apiPost() { return Promise.resolve({ ok: true }); }\n"

#: `run/get_history_stats` en ECHEC — le chemin de repli de `_ensureHistoryStats`.
#: `get_history_stats` y tombe pour deux causes reelles : « Run introuvable »
#: (run purge par la retention, base restauree) et son wrap global
#: `except Exception` (history_support.py:470), qui couvre un verrou SQLite ou
#: un `plan.jsonl` illisible. `run/get_status` reste servi : le repli le sollicite
#: pour recuperer au moins les logs.
_API_HISTORY_STATS_KO = r"""
function apiPost(route) {
  if (String(route) === "run/get_history_stats") {
    return Promise.resolve({ ok: false, error: "history_stats_failed" });
  }
  return Promise.resolve({ data: { logs: [] } });
}
"""

_STUBS = _STUBS_COMMUNS + _API_INERTE

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


class LeSiteDAppelTransmetLInconnuTests(unittest.TestCase):
    """TESTER LA DECISION NE DIT RIEN DU SITE D'APPEL.

    La suite ci-dessus prouve que `_renderDoublonsList` distingue les trois
    etats — mais elle lui passe son `stats` A LA MAIN. Elle ne peut donc pas
    voir ce que son APPELANT lui transmet reellement, et c'est exactement la ou
    l'invariant se perdait : le repli de `_ensureHistoryStats` construisait
    `duplicates_groups: base.duplicates_groups || 0`.

    Le zero n'etait pas conditionnel mais CERTAIN : `get_runs_summary`
    (`repositories/run.py`) n'expose pas `duplicates_groups`, donc la valeur lue
    vaut toujours `undefined`. Des que `run/get_history_stats` echouait,
    l'onglet reaffirmait « Aucun doublon detecte dans ce run » — la phrase meme
    que #1077 avait retiree, restauree par une garde posee en aval d'un `|| 0`.

    Ces tests executent donc les DEUX fonctions de production a la suite :
    le repli fabrique l'objet, le rendu le lit. Aucun `stats` ecrit a la main.
    """

    def setUp(self) -> None:
        require_node(self)

    def _rendre_apres_echec_backend(self) -> dict:
        return run_module_test(
            HISTORIQUE_JS,
            stubs=_STUBS_COMMUNS + _API_HISTORY_STATS_KO,
            extra=_EXTRA + "export const __ensure = _ensureHistoryStats;\n",
            driver=(
                'const entree = await M.__ensure("run-cible");\n'
                "__emit({ html: M.__rendreDoublons(entree.run), groupes: entree.run.duplicates_groups });"
                + _EXIT
            ),
            timeout=90,
        )

    def test_un_backend_en_echec_n_affirme_pas_AUCUN_DOUBLON(self) -> None:
        """LE defaut. Le repli forcait un zero, le rendu l'affirmait."""
        res = self._rendre_apres_echec_backend()

        self.assertNotIn(
            "Aucun doublon détecté",
            str(res["html"]),
            "le repli transmet un 0 que personne n'a mesure : l'ecran AFFIRME "
            "l'absence de doublons alors que le backend vient d'echouer",
        )

    def test_il_dit_ce_qu_il_SAIT_et_laisse_une_porte_de_sortie(self) -> None:
        """Ne rien affirmer ne suffit pas, ici non plus."""
        res = self._rendre_apres_echec_backend()
        html = str(res["html"])

        self.assertIn("non comptés", html, "l'ecran ne dit plus rien du tout")
        self.assertIn("#/doublons", html, "aucun chemin vers l'ecran qui peut repondre")

    def test_la_valeur_transmise_est_bien_INCONNUE(self) -> None:
        """Asserter ce que SEUL le correctif produit.

        Le HTML seul ne suffirait pas : « non comptés » pourrait venir d'une
        autre branche. On epingle donc la valeur que le repli met dans l'objet,
        la ou vivait le `|| 0`.
        """
        res = self._rendre_apres_echec_backend()

        self.assertIsNone(
            res["groupes"],
            "`duplicates_groups` doit rester INCONNU (null) apres un repli ; "
            "un 0 ici est le defaut lui-meme",
        )

    def test_un_run_qui_porte_un_ZERO_MESURE_le_garde(self) -> None:
        """CONTRE-TEST : `??` ne doit pas transformer un vrai 0 en inconnu.

        Sans lui, remplacer `|| 0` par `?? null` passerait aussi bien en
        rendant TOUJOURS null — ce qui detruirait l'autre moitie des trois
        etats. On pose donc un run qui PORTE la cle a 0 dans `_runs`.
        """
        res = run_module_test(
            HISTORIQUE_JS,
            stubs=_STUBS_COMMUNS + _API_HISTORY_STATS_KO,
            extra=(
                _EXTRA
                + "export const __ensure = _ensureHistoryStats;\n"
                + "export function __poserRuns(rs) { _runs = rs; }\n"
            ),
            driver=(
                'M.__poserRuns([{ run_id: "run-cible", duplicates_groups: 0 }]);\n'
                'const entree = await M.__ensure("run-cible");\n'
                "__emit({ html: M.__rendreDoublons(entree.run), groupes: entree.run.duplicates_groups });"
                + _EXIT
            ),
            timeout=90,
        )

        self.assertEqual(res["groupes"], 0, "un 0 REELLEMENT porte par la liste doit survivre")
        self.assertIn(
            "Aucun doublon détecté",
            str(res["html"]),
            "un zero MESURE doit pouvoir s'affirmer — c'est l'autre moitie des trois etats",
        )


if __name__ == "__main__":
    unittest.main()
