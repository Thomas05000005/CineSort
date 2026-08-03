"""F23 — traitement.js : l'apercu d'apply n'etait pas refetche apres une edition
d'annee ou un swap approuve/rejete 1-pour-1.

Bug d'origine (BACKLOG35 F23) : `_applyDecisionsSignature()` valait
`runId|size|approved`. Or `size` est CONSTANT (toutes les rows sont pre-seedees
par `_initDecisionsState`) et `_setDecisionYear` ne touche ni `size` ni
`approved`. Retour sur l'etape Apply -> signature identique -> `_ensureApplyPreview`
early-return -> le « Resume des operations » montrait l'ANCIEN plan backend, non
etiquete « estimation », alors que l'apply reel poste `_buildDecisions()` frais
ou `year` prime pour le dossier cible (apply_core.py:1691).

Les tests executent la VRAIE source du module sous Node (imports stubbes) et
comptent les POST `run/build_apply_preview` reellement emis.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, node_check, require_node, run_module_test

JS = ROOT / "web" / "dashboard" / "views" / "traitement.js"

STUBS = r"""
globalThis.__previews = [];
globalThis.__previewDelayMs = 0;
// Chaque reponse porte un `renames` UNIQUE (111, 222, ...) : le HTML rendu dit
// donc sans ambiguite QUEL plan backend est affiche.
const apiPost = async (endpoint, body) => {
  if (endpoint === "run/build_apply_preview") {
    globalThis.__previews.push(JSON.parse(JSON.stringify(body || {})));
    const n = globalThis.__previews.length;
    if (globalThis.__previewDelayMs) await new Promise((r) => setTimeout(r, globalThis.__previewDelayMs));
    return {
      status: 200,
      data: { ok: true, films: [], totals: { renames: n * 111, moves: 0, quarantined: 0 } },
    };
  }
  return { status: 200, data: { ok: true } };
};
const fetchConfidenceThresholds = async () => ({});
const getConfidenceThresholdsSync = () => ({ CONF_HIGH: 85, CONF_MED: 60 });
const escapeHtml = (s) => String(s == null ? "" : s);
const navigateTo = () => {};
const dangerConfirmModal = () => {};
const showModal = () => {};
const closeModal = () => {};
const showToast = () => {};
const formatRelative = () => "";
const formatDuration = () => "";
const initDoublons = async () => {};
const unmountDoublons = () => {};
const renderFilmDetail = async () => {};
const labelsForFlags = () => [];
const countBySeverity = () => ({});
const getNavSignal = () => undefined;
const formatBytes = (n) => String(n);
const setSections = () => {};
const openPerceptualModal = () => {};
const openDuplicateComparatorModal = () => {};
const posterProxyUrl = (u) => u;
const trapFocus = () => () => {};
const invalidateSettingsCache = () => {};
const apiGet = async () => ({ status: 200, data: { ok: true } });

globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" }, setTimeout, clearTimeout };
globalThis.document = {
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => null,
  createElement: () => ({ innerHTML: "", appendChild() {}, setAttribute() {}, addEventListener() {}, classList: { add() {}, remove() {} } }),
  addEventListener() {}, removeEventListener() {},
  body: { classList: { add() {}, remove() {} }, appendChild() {} },
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
"""

EXTRA = r"""
export const __h = {
  sig: _applyDecisionsSignature,
  decisions: () => _decisionsState,
  buildDecisions: _buildDecisions,
  setYear: _setDecisionYear,
  setOk: _setDecisionOk,
  ensurePreview: _ensureApplyPreview,
  renderApplyStep: _renderApplyStep,
  previewTotals: () => (_applyPreview && _applyPreview.totals) || null,
  setRunInfo: (v) => { _runInfo = v; },
  resetPreviewSig: () => { _applyPreviewSig = ""; },
  seed: (rows) => {
    _validationPlan = { rows };
    _initDecisionsState();
  },
};
"""

_SEED = r"""
M.__h.setRunInfo({ runId: "run-1" });
M.__h.seed([
  { row_id: "r1", proposed_year: 2019, decision: "OK" },
  { row_id: "r2", proposed_year: 1999, decision: "OK" },
  { row_id: "r3", proposed_year: 2005, decision: "REJECT" },
]);
"""


class F23ApplyPreviewSignatureTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(JS, stubs=STUBS, extra=EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_edition_dannee_refetche_lapercu(self):
        """ROUGE avant fix : 1 seule requete, portant l'ancienne annee."""
        res = self._run(
            _SEED
            + r"""
await M.__h.ensurePreview();           // 1er passage sur l'etape Apply
M.__h.setYear("r1", 1999);             // retour Validation : edition d'annee
await M.__h.ensurePreview();           // retour sur l'etape Apply
__emit({
  count: globalThis.__previews.length,
  lastYear: globalThis.__previews.length ? globalThis.__previews[globalThis.__previews.length - 1].decisions.r1.year : null,
});
"""
        )
        self.assertEqual(res["count"], 2, "une edition d'annee doit invalider l'apercu backend")
        self.assertEqual(res["lastYear"], 1999)

    def test_swap_approuve_rejete_refetche_lapercu(self):
        """ROUGE avant fix : `approved` constant -> signature identique."""
        res = self._run(
            _SEED
            + r"""
await M.__h.ensurePreview();
M.__h.setOk("r1", false);              // swap 1-pour-1 : approved inchange
M.__h.setOk("r3", true);
await M.__h.ensurePreview();
const last = globalThis.__previews[globalThis.__previews.length - 1].decisions;
__emit({ count: globalThis.__previews.length, r1: last.r1.ok, r3: last.r3.ok });
"""
        )
        self.assertEqual(res["count"], 2, "un swap approuve/rejete doit invalider l'apercu")
        self.assertFalse(res["r1"])
        self.assertTrue(res["r3"])

    def test_apercu_perime_nest_pas_presente_comme_plan_backend(self):
        """Revue adversaire R1 (MEDIUM) : `_renderApplyStep` appelle
        `_ensureApplyPreview()` SANS l'attendre puis lit `_applyPreview` dans la
        foulee. Le refetch partait bien (correctif F23) mais l'ANCIEN plan
        restait affiche avec `totals` non nul -> `previewIsEstimate=false` : le
        « Résumé des opérations » presentait un plan PERIME comme le vrai plan
        backend, non etiquete « (estimation) », pendant tout l'aller-retour —
        et rien ne gate le bouton « Appliquer maintenant »."""
        res = self._run(
            _SEED
            + r"""
await M.__h.ensurePreview();                 // plan backend #1 -> renames=111
const html1 = M.__h.renderApplyStep();       // etape Apply, plan a jour
M.__h.setYear("r1", 1888);                   // retour Validation : edition
globalThis.__previewDelayMs = 300;           // backend lent
const html2 = M.__h.renderApplyStep();       // retour Apply : refetch en vol
await globalThis.__sleep(500);
const html3 = M.__h.renderApplyStep();       // plan backend #2 -> renames=222
__emit({
  html1: { has111: html1.includes(">111<"), estimation: html1.includes("(estimation)") },
  html2: { has111: html2.includes(">111<"), estimation: html2.includes("(estimation)") },
  html3: { has222: html3.includes(">222<"), estimation: html3.includes("(estimation)") },
  previews: globalThis.__previews.length,
  lastYear: globalThis.__previews[globalThis.__previews.length - 1].decisions.r1.year,
});
"""
        )
        # Non-regression (verte des deux cotes) : un plan A JOUR est bien
        # presente comme le vrai plan backend.
        self.assertTrue(res["html1"]["has111"], "le plan backend frais doit etre affiche")
        self.assertFalse(res["html1"]["estimation"], "un plan frais n'est pas une estimation")
        # ROUGE sans le fix : le plan perime restait affiche, non etiquete.
        self.assertFalse(
            res["html2"]["has111"],
            "le plan PERIME ne doit plus etre affiche des que les decisions ont change",
        )
        self.assertTrue(
            res["html2"]["estimation"],
            "pendant le refetch, le resume doit etre explicitement etiquete « (estimation) »",
        )
        # Non-regression (verte des deux cotes) : le refetch aboutit bien.
        self.assertTrue(res["html3"]["has222"], "le nouveau plan backend doit finir par s'afficher")
        self.assertFalse(res["html3"]["estimation"])
        self.assertEqual(res["previews"], 2)
        self.assertEqual(res["lastYear"], 1888, "le refetch porte bien l'annee editee")

    def test_signature_varie_avec_lannee(self):
        res = self._run(
            _SEED
            + r"""
const before = M.__h.sig();
M.__h.setYear("r2", 2001);
const after = M.__h.sig();
__emit({ before, after });
"""
        )
        self.assertNotEqual(res["before"], res["after"])

    def test_signature_varie_avec_un_swap(self):
        res = self._run(
            _SEED
            + r"""
const before = M.__h.sig();
M.__h.setOk("r1", false);
M.__h.setOk("r3", true);
const after = M.__h.sig();
__emit({ before, after });
"""
        )
        self.assertNotEqual(res["before"], res["after"])

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_signature_stable_si_rien_ne_change(self):
        """Idempotence : sans changement, la signature ne bouge pas — sinon
        _ensureApplyPreview refetcherait en boucle a chaque re-render."""
        res = self._run(
            _SEED
            + r"""
const a = M.__h.sig();
const b = M.__h.sig();
// re-poser la MEME valeur ne doit pas changer la signature (decided_at bouge
// pourtant a chaque set : il ne doit surtout pas entrer dans la signature).
M.__h.setYear("r1", 2019);
M.__h.setOk("r1", true);
const c = M.__h.sig();
__emit({ a, b, c });
"""
        )
        self.assertEqual(res["a"], res["b"])
        self.assertEqual(res["a"], res["c"], "decided_at ne doit pas entrer dans la signature")

    def test_nonreg_pas_de_refetch_sans_changement(self):
        res = self._run(
            _SEED
            + r"""
await M.__h.ensurePreview();
await M.__h.ensurePreview();
await M.__h.ensurePreview();
__emit({ count: globalThis.__previews.length });
"""
        )
        self.assertEqual(res["count"], 1, "aucun refetch tant que les decisions sont inchangees")

    def test_nonreg_signature_insensible_a_lordre_dinsertion(self):
        """Les bulk-actions font delete+set : l'ordre de la Map change sans que
        les decisions changent. La signature doit rester identique."""
        res = self._run(
            _SEED
            + r"""
const before = M.__h.sig();
const m = M.__h.decisions();
const v = m.get("r1");
m.delete("r1");
m.set("r1", v);                        // reinsere en fin de Map
const after = M.__h.sig();
__emit({ before, after, size: m.size });
"""
        )
        self.assertEqual(res["size"], 3)
        self.assertEqual(res["before"], res["after"])

    def test_signature_garde_run_size_approved_en_clair(self):
        """Mitigation collision : la partie lisible `runId|size|approved` reste
        en clair devant le hash (une collision 32 bits ne peut donc pas a elle
        seule ramener le bug). Ce test n'est PAS une non-regression : il decrit
        la forme voulue de la nouvelle signature."""
        res = self._run(
            _SEED
            + r"""
__emit({ sig: M.__h.sig() });
"""
        )
        self.assertTrue(res["sig"].startswith("run-1|3|2|"), res["sig"])

    def test_nonreg_syntaxe_du_module(self):
        node_check(self, JS)


if __name__ == "__main__":
    unittest.main()
