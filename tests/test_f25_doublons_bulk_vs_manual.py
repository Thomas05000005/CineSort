"""F25 — doublons.js : « Auto-decider tous » ecrasait silencieusement une
decision manuelle prise pendant la boucle.

Bug d'origine (BACKLOG35 F25) : `_autoDecideAll` boucle sur un snapshot
`candidates` fige AVANT la confirmation et ne revalide jamais `g.winner_decided`
ni `decisionInFlightByGroup` dans le corps. Pendant ce temps les boutons
« Garder A/B » des cartes n'etaient desactives que par `decisionInFlightByGroup`.
Cote backend, `upsert_duplicate_decision` est un INSERT..ON CONFLICT DO UPDATE
(dernier ecrit gagne) : la boucle repassait derriere le choix de l'utilisateur,
puis `_loadGroups(true)` resynchronisait l'UI dessus. A l'apply, le fichier
choisi partait en `_review/_duplicates_user_decided/`.

Les tests executent la VRAIE source du module sous Node (imports + DOM stubbes)
et observent les POST `run/mark_duplicate_winner` reellement emis.

Ecart assume vs la spec de correctif : la spec proposait de reutiliser
`_state.bulkInFlight`. Ce drapeau est PARTAGE avec le bulk perceptuel
(`_bulkPerceptual`, jusqu'a ~1 min de polling) qui ne pose aucune decision :
le reutiliser aurait desactive les boutons de decision sans raison et affiche
un message faux. On introduit donc `_state.autoDecideInFlight`, pose uniquement
par `_autoDecideAll`.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, node_check, require_node, run_module_test

JS = ROOT / "web" / "dashboard" / "views" / "doublons.js"

STUBS = r"""
globalThis.__marks = [];
globalThis.__toasts = [];
globalThis.__markDelayMs = 60;
globalThis.__groups = null;

const apiPost = async (endpoint, body) => {
  if (endpoint === "run/get_dashboard") return { status: 200, data: { ok: true, run_id: "run-1" } };
  if (endpoint === "run/check_duplicates") {
    return { status: 200, data: { ok: true, groups: globalThis.__groups, size_savings_total: 0 } };
  }
  if (endpoint === "run/mark_duplicate_winner") {
    globalThis.__marks.push({ group_key: body.group_key, winner_row_id: body.winner_row_id, notes: body.notes || null });
    await new Promise((r) => setTimeout(r, globalThis.__markDelayMs));
    return { status: 200, data: { ok: true, losers: [] } };
  }
  if (endpoint === "library/get_film_full") return { status: 200, data: { ok: true, row: {} } };
  return { status: 200, data: { ok: true } };
};
globalThis.__apiPost = apiPost;   // sert a emuler le POST du MODAL comparateur
const escapeHtml = (s) => String(s == null ? "" : s);
const formatBytes = (n) => String(n);
const getNavSignal = () => undefined;
const labelsForFlags = () => [];
const countBySeverity = () => ({});
const openPerceptualModal = () => {};
const renderFilmDetail = async () => {};
const openDuplicateComparatorModal = (o) => { globalThis.__comparatorOpened = (globalThis.__comparatorOpened || 0) + 1; void o; };
const showToast = (o) => { globalThis.__toasts.push(o); };
globalThis.__panels = [];
const setRightPanelSections = (sections) => { globalThis.__panels.push(sections); };
const navigateTo = () => {};
// dangerConfirmModal : confirme immediatement (la modale est deja couverte
// ailleurs ; ici on teste ce qui se passe APRES la confirmation).
const dangerConfirmModal = (o) => { globalThis.__confirmPromise = o.onConfirm(); };

function __makeEl() {
  const el = {
    _html: "", _writes: [],
    addEventListener() {}, removeEventListener() {},
    querySelector: () => null, querySelectorAll: () => [],
    setAttribute() {}, getAttribute: () => null,
    dataset: {}, classList: { add() {}, remove() {}, toggle() {} },
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; },
    set(v) { el._html = String(v); el._writes.push(String(v)); },
  });
  return el;
}
globalThis.__makeEl = __makeEl;
globalThis.document = {
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: () => null, createElement: () => __makeEl(),
  addEventListener() {}, removeEventListener() {},
  body: { classList: { add() {}, remove() {} }, appendChild() {} },
};
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
"""

EXTRA = r"""
export const __h = {
  autoDecideAll: _autoDecideAll,
  decideFromCard: _decideFromCard,
  openComparator: _openComparator,
  renderRightPanel: _renderRightPanel,
  state: () => _state,
};
"""

# POST du MODAL comparateur, copie VERBATIM de duplicate-comparator-modal.js
# `_decideWinner` (memes endpoint et payload). Le modal a son PROPRE verrou
# `_state.decisionInFlight` (module distinct) et, si l'utilisateur ferme sur
# Echap pendant le POST, `closeDuplicateComparatorModal` met son `_state` a
# null : le callback `onDecided` n'est alors JAMAIS appele, donc la vue Doublons
# n'apprend jamais que cette decision manuelle est partie.
_MODAL_POST = r"""
const __modalPost = (groupKey, winnerRowId) => globalThis.__apiPost(
  "run/mark_duplicate_winner",
  { run_id: M.__h.state().runId, group_key: groupKey, winner_row_id: winnerRowId, notes: null },
);
"""

_BOOT = r"""
globalThis.__groups = [1, 2, 3].map((i) => ({
  group_key: "film" + i + "|200" + i,
  title: "Film " + i,
  year: 2000 + i,
  winner_decided: false,
  comparison: { winner: "a", size_savings: 0 },
  rows: [{ row_id: "r" + i + "a" }, { row_id: "r" + i + "b" }],
}));
const el = globalThis.__makeEl();
globalThis.__lastContainer = el;
globalThis.__containerHtml = () => el.innerHTML;
await M.initDoublons(el);
"""


class F25BulkVsManualDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(JS, stubs=STUBS, extra=EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_bulk_saute_un_groupe_decide_manuellement_en_vol(self):
        """ROUGE avant fix : la boucle postait quand meme sur film3, ecrasant la
        decision manuelle (winner b) par le winner automatique (a)."""
        res = self._run(
            _BOOT
            + r"""
globalThis.__markDelayMs = 80;
// Decision manuelle sur film3 (POST lent, donc encore en vol).
const manual = M.__h.decideFromCard("film3|2003", "b", "r3b");
await globalThis.__sleep(5);
M.__h.autoDecideAll();
await globalThis.__confirmPromise;
await manual;
const byGroup = {};
for (const m of globalThis.__marks) (byGroup[m.group_key] = byGroup[m.group_key] || []).push(m.winner_row_id);
__emit({ marks: globalThis.__marks, byGroup, toasts: globalThis.__toasts.map((t) => t.text) });
"""
        )
        posts_film3 = res["byGroup"].get("film3|2003", [])
        self.assertEqual(
            posts_film3,
            ["r3b"],
            "la boucle bulk ne doit PAS reposter sur un groupe deja decide manuellement",
        )
        self.assertIn("film1|2001", res["byGroup"], "les autres groupes sont bien auto-decides")
        self.assertIn("film2|2002", res["byGroup"])

    def test_bulk_saute_un_groupe_marque_decide_pendant_la_boucle(self):
        """Une decision manuelle TERMINEE pendant la boucle (winner_decided pose
        sur l'objet groupe) doit etre respectee par les tours suivants."""
        res = self._run(
            _BOOT
            + r"""
globalThis.__markDelayMs = 60;
const st = M.__h.state();
M.__h.autoDecideAll();
await globalThis.__sleep(20);          // la boucle traite film1
// Simule la fin d'une decision manuelle sur film3 (ce que fait _handleDecision).
const g3 = st.groups.find((g) => g.group_key === "film3|2003");
g3.winner_decided = true;
g3.winner_row_id = "r3b";
await globalThis.__confirmPromise;
__emit({ groups: globalThis.__marks.map((m) => m.group_key), toasts: globalThis.__toasts.map((t) => t.text) });
"""
        )
        self.assertNotIn("film3|2003", res["groups"], "film3 deja decide -> la boucle doit le sauter")
        self.assertIn("film1|2001", res["groups"])
        self.assertTrue(
            any("ignor" in t for t in res["toasts"]),
            f"le toast final doit annoncer le(s) groupe(s) ignore(s) : {res['toasts']}",
        )

    def test_decision_manuelle_refusee_pendant_le_bulk(self):
        """Un clic « Garder B » dispatche pendant le bulk doit etre refuse avec
        un message, pas partir en concurrence de la boucle."""
        res = self._run(
            _BOOT
            + r"""
globalThis.__markDelayMs = 80;
M.__h.autoDecideAll();
await globalThis.__sleep(20);
const before = globalThis.__marks.length;
await M.__h.decideFromCard("film3|2003", "b", "r3b");
const after = globalThis.__marks.length;
const toastsMid = globalThis.__toasts.map((t) => t.text);
await globalThis.__confirmPromise;
__emit({ before, after, toastsMid,
  manualPosts: globalThis.__marks.filter((m) => m.winner_row_id === "r3b").length });
"""
        )
        self.assertEqual(res["before"], res["after"], "aucun POST manuel ne doit partir pendant le bulk")
        self.assertEqual(res["manualPosts"], 0)
        self.assertTrue(
            any("Auto-d" in t for t in res["toastsMid"]),
            f"l'utilisateur doit etre averti : {res['toastsMid']}",
        )

    def test_comparateur_bloque_pendant_le_bulk(self):
        """Le modal comparateur poste mark_duplicate_winner avec son PROPRE
        verrou : il doit rester inaccessible pendant le bulk."""
        res = self._run(
            _BOOT
            + r"""
globalThis.__markDelayMs = 80;
const st = M.__h.state();
M.__h.autoDecideAll();
await globalThis.__sleep(20);
M.__h.openComparator(st.groups[2]);
const opened = globalThis.__comparatorOpened || 0;
await globalThis.__confirmPromise;
__emit({ opened });
"""
        )
        self.assertEqual(res["opened"], 0, "le comparateur ne doit pas s'ouvrir pendant le bulk")

    # ------------------------------------------- ROUGE (revue adversaire R1)
    def test_bulk_nepose_rien_sur_un_groupe_ouvert_dans_le_comparateur(self):
        """Revue adversaire R1 (MEDIUM) : le comparateur poste
        mark_duplicate_winner depuis son PROPRE module, avec son propre verrou —
        il n'alimente jamais `decisionInFlightByGroup`, et son `onDecided` est
        perdu si l'utilisateur ferme sur Echap pendant le POST. Le garde 5 etait
        donc AVEUGLE a une decision manuelle deja partie et la boucle upsertait
        par-dessus (ON CONFLICT DO UPDATE = dernier ecrit gagne)."""
        res = self._run(
            _BOOT
            + _MODAL_POST
            + r"""
globalThis.__markDelayMs = 400;             // POST du modal encore en vol
const st = M.__h.state();
M.__h.openComparator(st.groups[2]);         // film3 : comparateur ouvert
const modal = __modalPost("film3|2003", "r3b");   // l'utilisateur choisit B
// ... puis ferme sur Echap (aucun onDecided ne remontera jamais) et lance le bulk
M.__h.autoDecideAll();
await globalThis.__confirmPromise;
await modal;
const byGroup = {};
for (const m of globalThis.__marks) (byGroup[m.group_key] = byGroup[m.group_key] || []).push(m.winner_row_id);
__emit({
  byGroup,
  chrono: globalThis.__marks.map((m) => m.group_key + "=" + m.winner_row_id),
  toasts: globalThis.__toasts.map((t) => t.text),
  pendingAfter: st.comparatorPendingByGroup ? st.comparatorPendingByGroup.size : null,
});
"""
        )
        self.assertEqual(
            res["byGroup"].get("film3|2003"),
            ["r3b"],
            "la boucle bulk ne doit PAS reposter sur un groupe ouvert dans le comparateur "
            f"(chronologie observee : {res['chrono']})",
        )
        # Non-regression (verte des deux cotes) : les autres groupes sont traites.
        self.assertEqual(res["byGroup"].get("film1|2001"), ["r1a"])
        self.assertEqual(res["byGroup"].get("film2|2002"), ["r2a"])
        self.assertTrue(
            any("ignor" in t for t in res["toasts"]),
            f"le groupe saute doit etre annonce a l'utilisateur : {res['toasts']}",
        )
        self.assertEqual(
            res["pendingAfter"],
            0,
            "le marquage doit etre BORNE a une passe (pas d'exclusion permanente) : "
            "apres le rechargement force de fin de bulk il est vide",
        )

    def test_le_marquage_comparateur_survit_a_un_aller_retour_de_vue(self):
        """Le cache de groupes (`_groupsCache`) survit aux navigations et sert
        des `winner_decided` potentiellement perimes : le marquage doit avoir la
        MEME duree de vie, sinon il suffit de quitter puis revenir sur Doublons
        pour que le bulk ecrase de nouveau la decision du comparateur."""
        res = self._run(
            _BOOT
            + _MODAL_POST
            + r"""
globalThis.__markDelayMs = 300;
const st = M.__h.state();
M.__h.openComparator(st.groups[2]);
const modal = __modalPost("film3|2003", "r3b");
M.unmountDoublons();                          // l'utilisateur quitte la vue
await M.initDoublons(globalThis.__lastContainer);   // ... et revient
M.__h.autoDecideAll();
await globalThis.__confirmPromise;
await modal;
const byGroup = {};
for (const m of globalThis.__marks) (byGroup[m.group_key] = byGroup[m.group_key] || []).push(m.winner_row_id);
__emit({ byGroup });
"""
        )
        self.assertEqual(
            res["byGroup"].get("film3|2003"),
            ["r3b"],
            "le marquage doit survivre au demontage de la vue (portee module, comme _groupsCache)",
        )
        self.assertEqual(res["byGroup"].get("film1|2001"), ["r1a"])

    def test_skip_du_panneau_droit_reste_utilisable_pendant_le_bulk(self):
        """Revue adversaire R1 (LOW) : le panneau droit n'a AUCUN bouton
        « Garder A/B » — le garde y desactivait « → Skip ce groupe », qui est une
        navigation purement locale (aucun reseau, aucune decision), pendant
        plusieurs minutes de bulk, tandis que « Comparer en detail » (le seul
        bouton du panneau qui mene a une decision) restait actif."""
        res = self._run(
            _BOOT
            + r"""
globalThis.__markDelayMs = 80;
M.__h.autoDecideAll();
await globalThis.__sleep(20);
globalThis.__panels.length = 0;
M.__h.renderRightPanel();                   // rendu du panneau PENDANT le bulk
const during = globalThis.__panels[globalThis.__panels.length - 1].map((s) => s.html).join("");
await globalThis.__confirmPromise;
globalThis.__panels.length = 0;
M.__h.renderRightPanel();                   // rendu HORS bulk
const after = globalThis.__panels[globalThis.__panels.length - 1].map((s) => s.html).join("");
const grab = (html, action) => {
  const m = html.match(new RegExp('data-doublons-inspector-action="' + action + '"[^>]*>'));
  return m ? m[0] : "";
};
__emit({
  duringSkip: grab(during, "skip"),
  duringCompare: grab(during, "compare"),
  afterSkip: grab(after, "skip"),
  afterCompare: grab(after, "compare"),
});
"""
        )
        self.assertTrue(res["duringSkip"], "le bouton Skip doit exister dans le panneau")
        self.assertNotIn(
            "disabled",
            res["duringSkip"],
            "« Skip ce groupe » est une navigation locale : il ne doit pas etre "
            f"desactive par le bulk ({res['duringSkip']!r})",
        )
        self.assertIn(
            "disabled",
            res["duringCompare"],
            "« Comparer en detail » mene a une decision : c'est LUI que le bulk doit "
            f"verrouiller ({res['duringCompare']!r})",
        )
        # Non-regression (verte des deux cotes) : hors bulk, tout est actif.
        self.assertNotIn("disabled", res["afterSkip"])
        self.assertNotIn("disabled", res["afterCompare"])

    def test_boutons_garder_disabled_pendant_le_bulk(self):
        res = self._run(
            _BOOT
            + r"""
globalThis.__markDelayMs = 80;
M.__h.autoDecideAll();
await globalThis.__sleep(20);
const during = globalThis.__containerHtml();
await globalThis.__confirmPromise;
const after = globalThis.__containerHtml();
__emit({
  duringHasDisabledKeep: /data-doublons-card-action="keep"[\s\S]{0,240}?disabled/.test(during),
  afterHasDisabledKeep: /data-doublons-card-action="keep"[\s\S]{0,240}?disabled/.test(after),
  duringHasTitle: during.includes("Auto-décision en cours"),
});
"""
        )
        self.assertTrue(res["duringHasDisabledKeep"], "les boutons Garder A/B doivent etre disabled pendant le bulk")
        self.assertTrue(res["duringHasTitle"], "un title explicatif doit accompagner le disabled")

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_bulk_nominal_decide_tous_les_groupes(self):
        """Sans interference, l'auto-decision traite les 3 groupes avec le
        winner du backend."""
        res = self._run(
            _BOOT
            + r"""
globalThis.__markDelayMs = 0;
M.__h.autoDecideAll();
await globalThis.__confirmPromise;
__emit({
  marks: globalThis.__marks,
  toasts: globalThis.__toasts.map((t) => t.text),
  autoFlag: M.__h.state().autoDecideInFlight,
  bulkFlag: M.__h.state().bulkInFlight,
});
"""
        )
        keys = [m["group_key"] for m in res["marks"]]
        self.assertEqual(sorted(keys), ["film1|2001", "film2|2002", "film3|2003"])
        self.assertEqual([m["winner_row_id"] for m in res["marks"]], ["r1a", "r2a", "r3a"])
        self.assertFalse(res["autoFlag"], "le verrou doit etre relache en fin de bulk")
        self.assertFalse(res["bulkFlag"])
        self.assertTrue(any("auto-d" in t.lower() for t in res["toasts"]))

    def test_nonreg_decision_manuelle_hors_bulk_fonctionne(self):
        res = self._run(
            _BOOT
            + r"""
globalThis.__markDelayMs = 0;
await M.__h.decideFromCard("film2|2002", "b", "r2b");
__emit({ marks: globalThis.__marks, inflight: M.__h.state().decisionInFlightByGroup.size });
"""
        )
        self.assertEqual(len(res["marks"]), 1)
        self.assertEqual(res["marks"][0]["group_key"], "film2|2002")
        self.assertEqual(res["marks"][0]["winner_row_id"], "r2b")
        self.assertEqual(res["inflight"], 0, "le verrou per-groupe doit etre relache")

    def test_nonreg_comparateur_ouvrable_hors_bulk(self):
        res = self._run(
            _BOOT
            + r"""
const st = M.__h.state();
M.__h.openComparator(st.groups[0]);
__emit({ opened: globalThis.__comparatorOpened || 0 });
"""
        )
        self.assertEqual(res["opened"], 1)

    def test_nonreg_syntaxe_du_module(self):
        node_check(self, JS)


if __name__ == "__main__":
    unittest.main()
