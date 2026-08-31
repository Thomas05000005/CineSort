"""LOT 5 A/B — les modales dereferencaient `_state` APRES un `await`.

Meme forme dans deux composants :

  A. `duplicate-comparator-modal.js` `_decideWinner` : la garde `if (!_state)`
     est en tete de fonction, AVANT `await apiPost("run/mark_duplicate_winner")`.
     Or `closeDuplicateComparatorModal()` pose `_state = null`, et Echap
     (`_onKeydown`) comme le clic sur le backdrop l'appellent sans regarder
     `decisionInFlight`. Fermer la modale pendant la requete faisait donc
     lever un TypeError sur `_state.comparison`, TypeError rattrape par le
     `catch` qui lui-meme ecrivait `_state.decisionInFlight = false` -> second
     TypeError, celui-la NON rattrape (rejet de promesse). Consequence metier :
     le serveur A enregistre le gagnant, mais `onDecided` n'est jamais appele
     donc la vue parente n'est pas rafraichie, et l'utilisateur voit un toast
     d'erreur JS brut.

  B. `perceptual-modal.js` `_loadCompareList` : `if (!_state) return;` est
     AVANT l'`await apiPost("library/get_library_filtered")`, et les ecritures
     `_state.compareRows` / `compareLoaded` / `compareInFlight` sont APRES.
     Cette liste est PRE-CHARGEE a l'ouverture (`void _loadCompareList()`),
     donc la course est le cas nominal : ouvrir puis fermer aussitot.
     `closePerceptualModal()` pose `_state = null` -> meme cascade de deux
     TypeError, le second non rattrape.

Correctif de forme commun : memoriser la reference de session AVANT l'await et
re-verifier `_state === stateRef` APRES chaque await avant toute ecriture.

Les tests executent la VRAIE source des modules sous Node (imports + DOM
stubbes), cf `tests/_jsexec.py`.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, node_check, require_node, run_module_test

JS_DUP = ROOT / "web" / "dashboard" / "components" / "duplicate-comparator-modal.js"
JS_PERC = ROOT / "web" / "dashboard" / "components" / "perceptual-modal.js"


# --------------------------------------------------------------------------
# A — duplicate-comparator-modal.js
# --------------------------------------------------------------------------

_DOM_STUB = r"""
function __makeEl(tag) {
  const el = {
    tagName: tag, className: "", _html: "", style: {},
    children: [], dataset: {},
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    addEventListener() {}, removeEventListener() {},
    appendChild(c) { el.children.push(c); return c; },
    remove() {}, focus() {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; },
    set(v) { el._html = String(v); },
  });
  Object.defineProperty(el, "outerHTML", {
    get() { return el._html; },
    set(v) { el._html = String(v); },
  });
  return el;
}
globalThis.document = {
  createElement: (t) => __makeEl(t),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {}, removeEventListener() {},
  body: { classList: { add() {}, remove() {} }, appendChild() {} },
};
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
"""

_STUBS_DUP = (
    r"""
globalThis.__toasts = [];
globalThis.__decided = [];
globalThis.__decideLatency = 80;

const apiPost = async (endpoint, body) => {
  if (endpoint === "run/mark_duplicate_winner") {
    await new Promise((r) => setTimeout(r, globalThis.__decideLatency));
    if (globalThis.__decideFails) throw new Error("reseau coupe");
    if (globalThis.__decideRefuses) {
      return { status: 200, data: { ok: false, message: "groupe deja decide" } };
    }
    return { status: 200, data: { ok: true, size_savings: 4096 } };
  }
  return { status: 200, data: { ok: true } };
};
const escapeHtml = (s) => String(s == null ? "" : s);
const showToast = (o) => { globalThis.__toasts.push(o); };
const trapFocus = () => () => {};
const formatBytes = (n) => String(n);
"""
    + _DOM_STUB
)

_EXTRA_DUP = r"""
export const __h = {
  decide: _decideWinner,
  state: () => _state,
};
"""

_OPEN_DUP = r"""
M.openDuplicateComparatorModal({
  runId: "run1", groupKey: "film|2001",
  rowA: "RA", rowB: "RB", title: "Film", year: 2001,
  comparison: { size_savings: 4096 },
  onDecided: (p) => { globalThis.__decided.push(p); },
});
"""


class ADecideWinnerFermetureEnVolTests(unittest.TestCase):
    """A — fermer la modale pendant `mark_duplicate_winner` en vol."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(JS_DUP, stubs=_STUBS_DUP, extra=_EXTRA_DUP, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_echap_pendant_la_decision_ne_leve_pas_et_notifie_le_parent(self):
        """Echap pendant la requete : la decision est enregistree cote serveur,
        donc la vue parente DOIT etre notifiee et aucune erreur ne doit fuiter."""
        res = self._run(
            _OPEN_DUP
            + r"""
const p = M.__h.decide("a");
await globalThis.__sleep(20);
M.closeDuplicateComparatorModal();   // Echap / clic backdrop pendant la requete
let rejected = null;
try { await p; } catch (e) { rejected = String((e && e.message) || e); }
await globalThis.__sleep(30);
__emit({
  rejected,
  decided: globalThis.__decided.length,
  winnerRowId: globalThis.__decided[0] ? globalThis.__decided[0].winnerRowId : null,
  toastTypes: globalThis.__toasts.map((t) => t.type),
  toastTexts: globalThis.__toasts.map((t) => String(t.text)),
  state: M.__h.state(),
});
"""
        )
        self.assertIsNone(
            res["rejected"],
            "fermer la modale pendant la decision ne doit pas rejeter la promesse",
        )
        self.assertEqual(
            res["decided"],
            1,
            "onDecided doit etre appele : le serveur a enregistre le gagnant, "
            "la vue parente doit se rafraichir meme si la modale a ete fermee",
        )
        self.assertEqual(res["winnerRowId"], "RA")
        self.assertNotIn(
            "error",
            res["toastTypes"],
            f"aucun toast d'erreur ne doit apparaitre : {res['toastTexts']}",
        )
        self.assertIsNone(res["state"], "la modale doit rester fermee")

    def test_echec_reseau_apres_fermeture_ne_leve_pas(self):
        """Branche `catch` : elle aussi ecrivait dans `_state` sans re-verifier."""
        res = self._run(
            _OPEN_DUP
            + r"""
globalThis.__decideFails = true;
const p = M.__h.decide("a");
await globalThis.__sleep(20);
M.closeDuplicateComparatorModal();
let rejected = null;
try { await p; } catch (e) { rejected = String((e && e.message) || e); }
__emit({ rejected, state: M.__h.state() });
"""
        )
        self.assertIsNone(res["rejected"], "l'echec reseau ne doit pas se doubler d'un TypeError")
        self.assertIsNone(res["state"])

    def test_refus_serveur_apres_fermeture_ne_leve_pas(self):
        """Branche `data.ok === false` : idem (premier deref de `_state`)."""
        res = self._run(
            _OPEN_DUP
            + r"""
globalThis.__decideRefuses = true;
const p = M.__h.decide("a");
await globalThis.__sleep(20);
M.closeDuplicateComparatorModal();
let rejected = null;
try { await p; } catch (e) { rejected = String((e && e.message) || e); }
__emit({ rejected, state: M.__h.state(), decided: globalThis.__decided.length });
"""
        )
        self.assertIsNone(res["rejected"])
        self.assertIsNone(res["state"])
        self.assertEqual(res["decided"], 0, "un refus serveur ne doit pas notifier un succes")

    def test_reouverture_pendant_la_decision_nepargne_pas_la_nouvelle_session(self):
        """La modale rouverte sur un AUTRE groupe ne doit pas etre fermee ni
        polluee par la reponse tardive de la session precedente."""
        res = self._run(
            _OPEN_DUP
            + r"""
const p = M.__h.decide("a");
await globalThis.__sleep(20);
M.closeDuplicateComparatorModal();
M.openDuplicateComparatorModal({
  runId: "run1", groupKey: "autre|1999",
  rowA: "RC", rowB: "RD", title: "Autre", year: 1999, comparison: {},
});
let rejected = null;
try { await p; } catch (e) { rejected = String((e && e.message) || e); }
await globalThis.__sleep(30);
const st = M.__h.state();
__emit({
  rejected,
  stillOpen: st != null,
  groupKey: st ? st.groupKey : null,
  decisionInFlight: st ? st.decisionInFlight : null,
});
"""
        )
        self.assertIsNone(res["rejected"])
        self.assertTrue(res["stillOpen"], "la modale rouverte ne doit pas etre fermee")
        self.assertEqual(res["groupKey"], "autre|1999")
        self.assertFalse(
            res["decisionInFlight"],
            "la nouvelle session ne doit pas heriter du drapeau de l'ancienne",
        )

    # ----------------------------------------------------- NON-REGRESSION
    def test_nonreg_decision_nominale_ferme_et_notifie(self):
        res = self._run(
            _OPEN_DUP
            + r"""
globalThis.__decideLatency = 0;
await M.__h.decide("b");
await globalThis.__sleep(20);
__emit({
  decided: globalThis.__decided.length,
  winnerRowId: globalThis.__decided[0] ? globalThis.__decided[0].winnerRowId : null,
  winnerSide: globalThis.__decided[0] ? globalThis.__decided[0].winnerSide : null,
  toastTypes: globalThis.__toasts.map((t) => t.type),
  state: M.__h.state(),
});
"""
        )
        self.assertEqual(res["decided"], 1)
        self.assertEqual(res["winnerRowId"], "RB")
        self.assertEqual(res["winnerSide"], "b")
        self.assertIn("success", res["toastTypes"])
        self.assertIsNone(res["state"], "une decision aboutie ferme la modale")

    def test_nonreg_refus_serveur_modale_ouverte_reste_utilisable(self):
        res = self._run(
            _OPEN_DUP
            + r"""
globalThis.__decideLatency = 0;
globalThis.__decideRefuses = true;
await M.__h.decide("a");
const st = M.__h.state();
__emit({
  stillOpen: st != null,
  decisionInFlight: st ? st.decisionInFlight : null,
  toastTypes: globalThis.__toasts.map((t) => t.type),
});
"""
        )
        self.assertTrue(res["stillOpen"], "un refus laisse la modale ouverte")
        self.assertFalse(res["decisionInFlight"], "le drapeau doit etre relache pour reessayer")
        self.assertIn("error", res["toastTypes"])

    def test_nonreg_syntaxe_du_module(self):
        node_check(self, JS_DUP)


# --------------------------------------------------------------------------
# B — perceptual-modal.js
# --------------------------------------------------------------------------

_STUBS_PERC = (
    r"""
globalThis.__listLatency = 80;
globalThis.__listFails = false;
globalThis.__listCall = 0;

const apiPost = async (endpoint) => {
  if (endpoint === "quality/get_perceptual_details") {
    // Etat 4.2 « missing » : rendu court, sans dependre des formatteurs.
    return { status: 200, data: { ok: false, missing: true } };
  }
  if (endpoint === "library/get_library_filtered") {
    // Marqueur d'APPEL dans les row_id : permet d'identifier QUELLE requete a
    // rempli le cache (appel 1 = session abandonnee, appel 2 = session courante).
    const n = ++globalThis.__listCall;
    await new Promise((r) => setTimeout(r, globalThis.__listLatency));
    if (globalThis.__listFails) throw new Error("reseau coupe");
    return { status: 200, data: { ok: true, rows: [
      { row_id: "C" + n + "-1", title: "Alpha", year: 2001 },
      { row_id: "C" + n + "-2", title: "Beta", year: 2002 },
    ] } };
  }
  return { status: 200, data: { ok: true } };
};
const escapeHtml = (s) => String(s == null ? "" : s);
const humanize = (s) => String(s == null ? "" : s);
const humanizeMelVerdict = (s) => String(s == null ? "" : s);
const isMelMeasured = () => false;
const severityForTier = () => "info";
const SCORE_V2_COMPONENTS = [];
const rpSetSections = () => {};
const rpSetExpandedWidth = () => {};
const rpIsExpandedWidth = () => false;
const openDuplicateComparatorModal = () => {};
const trapFocus = () => () => {};
"""
    + _DOM_STUB
)

_EXTRA_PERC = r"""
export const __h = {
  loadCompareList: _loadCompareList,
  state: () => _state,
};
"""

_OPEN_PERC = r"""
await M.openPerceptualModal({ rowId: "R9", runId: "run1", rowTitle: "Film", mode: "B" });
"""


class BLoadCompareListFermetureEnVolTests(unittest.TestCase):
    """B — fermer la modale pendant le pre-chargement de la liste « Comparer »."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(JS_PERC, stubs=_STUBS_PERC, extra=_EXTRA_PERC, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_fermeture_pendant_le_prechargement_ne_leve_pas(self):
        """Cas nominal du bug : `openPerceptualModal` lance `void
        _loadCompareList()` en arriere-plan ; Echap juste apres."""
        res = self._run(
            _OPEN_PERC
            + r"""
const unhandled = [];
process.on("unhandledRejection", (e) => { unhandled.push(String((e && e.message) || e)); });
M.closePerceptualModal();   // Echap pendant le pre-chargement
await globalThis.__sleep(200);
__emit({ unhandled, state: M.__h.state() });
"""
        )
        self.assertEqual(
            res["unhandled"],
            [],
            "le pre-chargement abandonne ne doit produire aucun rejet non rattrape",
        )
        self.assertIsNone(res["state"])

    def test_appel_direct_ferme_en_vol_ne_leve_pas(self):
        res = self._run(
            _OPEN_PERC
            + r"""
const st = M.__h.state();
st.compareLoaded = false;
st.compareInFlight = false;
const p = M.__h.loadCompareList();
await globalThis.__sleep(20);
M.closePerceptualModal();
let rejected = null;
try { await p; } catch (e) { rejected = String((e && e.message) || e); }
__emit({ rejected, state: M.__h.state() });
"""
        )
        self.assertIsNone(res["rejected"])
        self.assertIsNone(res["state"])

    def test_echec_reseau_apres_fermeture_ne_leve_pas(self):
        """Branche `catch` : elle ecrivait `_state.compareInFlight` sans garde."""
        res = self._run(
            _OPEN_PERC
            + r"""
const st = M.__h.state();
st.compareLoaded = false;
st.compareInFlight = false;
globalThis.__listFails = true;
const p = M.__h.loadCompareList();
await globalThis.__sleep(20);
M.closePerceptualModal();
let rejected = null;
try { await p; } catch (e) { rejected = String((e && e.message) || e); }
__emit({ rejected, state: M.__h.state() });
"""
        )
        self.assertIsNone(res["rejected"])
        self.assertIsNone(res["state"])

    def test_reouverture_pendant_le_chargement_ne_pollue_pas_la_nouvelle_session(self):
        """La reponse tardive ne doit pas remplir le cache d'une AUTRE fiche."""
        res = self._run(
            r"""
const unhandled = [];
process.on("unhandledRejection", (e) => { unhandled.push(String((e && e.message) || e)); });
// Ouverture 1 : son pre-chargement (appel #1, lent) part en arriere-plan.
await M.openPerceptualModal({ rowId: "R9", runId: "run1", rowTitle: "Film", mode: "B" });
await globalThis.__sleep(20);
M.closePerceptualModal();
// Ouverture 2 sur une AUTRE fiche : son pre-chargement (appel #2) est instantane.
globalThis.__listLatency = 0;
await M.openPerceptualModal({ rowId: "RX", runId: "run1", rowTitle: "Autre", mode: "B" });
await globalThis.__sleep(300);   // l'appel #1 retombe ici
const st = M.__h.state();
__emit({
  unhandled,
  rowId: st ? st.rowId : null,
  rows: st ? st.compareRows.map((r) => r.row_id) : null,
});
"""
        )
        self.assertEqual(res["unhandled"], [])
        self.assertEqual(res["rowId"], "RX")
        self.assertEqual(
            res["rows"],
            ["C2-1", "C2-2"],
            "le cache de la fiche courante doit venir de SA requete (appel #2), "
            "pas de la reponse tardive de la fiche abandonnee (appel #1)",
        )

    # ----------------------------------------------------- NON-REGRESSION
    def test_nonreg_prechargement_nominal_remplit_le_cache(self):
        res = self._run(
            r"""
globalThis.__listLatency = 0;
"""
            + _OPEN_PERC
            + r"""
await globalThis.__sleep(50);
const st = M.__h.state();
__emit({
  compareLoaded: st.compareLoaded,
  compareInFlight: st.compareInFlight,
  rows: st.compareRows.map((r) => r.row_id),
});
"""
        )
        self.assertTrue(res["compareLoaded"])
        self.assertFalse(res["compareInFlight"])
        self.assertEqual(res["rows"], ["C1-1", "C1-2"])

    def test_nonreg_erreur_modale_ouverte_relache_le_verrou(self):
        res = self._run(
            _OPEN_PERC
            + r"""
const st = M.__h.state();
st.compareLoaded = false;
st.compareInFlight = false;
globalThis.__listFails = true;
globalThis.__listLatency = 0;
await M.__h.loadCompareList();
__emit({
  compareInFlight: M.__h.state().compareInFlight,
  compareLoaded: M.__h.state().compareLoaded,
});
"""
        )
        self.assertFalse(
            res["compareInFlight"],
            "modale toujours ouverte : le verrou doit etre relache pour reessayer",
        )
        self.assertFalse(res["compareLoaded"])

    def test_nonreg_syntaxe_du_module(self):
        node_check(self, JS_PERC)


if __name__ == "__main__":
    unittest.main()
