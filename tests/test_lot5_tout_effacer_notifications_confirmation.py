"""LOT 5 D — « Tout effacer » du centre de notifications sans confirmation.

`components/notification-center.js` rend le bouton avec la classe
`v5-btn--danger-ghost` — le code le classe donc LUI-MEME comme destructif — puis
appelle `runtime/clear_notifications` sur le clic, sans rien demander.

Les deux conditions du critere ecrit dans `dangerConfirmModal` sont remplies :

  1. la perte est IRRECUPERABLE PAR L'APPLICATION : les notifications vivent en
     MEMOIRE (`notifications_support` -> `store.clear()`), il n'y a ni undo, ni
     corbeille, ni route de restauration ;
  2. la portee n'est PAS une selection de l'utilisateur : le bouton efface TOUT
     — y compris ce que le filtre courant (« Non lues », « Insights »…) ne
     montre pas.

Et l'enjeu n'est pas cosmetique : d'apres `CLAUDE.md`, le centre de
notifications est « le canal qui atteint reellement l'utilisateur, seul a
survivre a la fermeture de l'ecran d'apply ». Un clic reflexe y detruit le seul
temoin d'un apply incoherent.

Un garde a ete cherche ailleurs avant d'ecrire celui-ci : `grep -n
"confirm|dangerConfirm"` sur `notification-center.js` ne rend RIEN, et aucun
appelant n'en pose un (le drawer se pilote par delegation de clic interne).

Les tests executent la VRAIE source du module sous Node (imports + DOM stubbes),
cf `tests/_jsexec.py`.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, node_check, require_node, run_module_test

JS = ROOT / "web" / "dashboard" / "components" / "notification-center.js"

STUBS = r"""
globalThis.__posts = [];
globalThis.__confirms = [];

/* 3 notifications, dont UNE SEULE non lue : le filtre « Non lues » n'en
   montrerait qu'une alors que « Tout effacer » les detruit toutes les trois. */
globalThis.__notifs = [
  { id: "n1", title: "Apply termine avec 3 erreurs", body: "", category: "event", read: false, ts: 1 },
  { id: "n2", title: "Doublons detectes", body: "", category: "insight", read: true, ts: 2 },
  { id: "n3", title: "Scan termine", body: "", category: "event", read: true, ts: 3 },
];

const apiPost = async (endpoint, body) => {
  globalThis.__posts.push({ endpoint, body: body || null });
  if (endpoint === "runtime/get_notifications") {
    return { status: 200, data: { ok: true, notifications: globalThis.__notifs, unread_count: 1 } };
  }
  return { status: 200, data: { ok: true } };
};
const escapeHtml = (s) => String(s == null ? "" : s);

/* La modale danger est STUBBEE : elle enregistre ses options et n'auto-confirme
   PAS. Un test qui confirmerait tout seul ne prouverait rien. */
const dangerConfirmModal = (opts) => { globalThis.__confirms.push(opts); };

/* --- DOM minimal --- */
function __makeEl(tag) {
  const el = {
    tagName: tag, id: "", className: "", _html: "", disabled: false,
    style: {}, _attrs: {}, dataset: {}, children: [], parent: null,
    setAttribute(k, v) { el._attrs[k] = String(v); },
    getAttribute: (k) => (k in el._attrs ? el._attrs[k] : null),
    removeAttribute(k) { delete el._attrs[k]; },
    _listeners: [],
    addEventListener(t, fn) { el._listeners.push({ t, fn }); },
    removeEventListener(t, fn) {
      const i = el._listeners.findIndex((l) => l.t === t && l.fn === fn);
      if (i >= 0) el._listeners.splice(i, 1);
    },
    appendChild(c) { c.parent = el; el.children.push(c); return c; },
    remove() {
      if (!el.parent) return;
      const i = el.parent.children.indexOf(el);
      if (i >= 0) el.parent.children.splice(i, 1);
      el.parent = null;
    },
    focus() {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; },
    set(v) { el._html = String(v); },
  });
  return el;
}

const __body = __makeEl("body");
function __findById(node, id) {
  for (const c of node.children) {
    if (c.id === id) return c;
    const f = __findById(c, id);
    if (f) return f;
  }
  return null;
}

globalThis.document = {
  body: __body,
  createElement: (t) => __makeEl(t),
  getElementById: (id) => __findById(__body, id),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {}, removeEventListener() {},
  dispatchEvent() { return true; },
};
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };

/** Fabrique un evenement de clic dont `target.closest(sel)` ne repond QUE pour
 *  le selecteur vise — fidele a la delegation reelle sur le drawer. */
globalThis.__clic = (selecteur, extra) => ({
  target: {
    closest: (sel) => (sel === selecteur ? Object.assign(__makeEl("button"), extra || {}) : null),
  },
  stopPropagation() {},
  preventDefault() {},
});
"""

EXTRA = r"""
export const __h = {
  handler: () => _drawerClickHandler,
  cache: () => _cache,
};
"""

_OUVRIR = r"""
M.openNotifications();
await globalThis.__sleep(30);
globalThis.__posts.length = 0;   // on ignore le get_notifications d'ouverture
const h = M.__h.handler();
"""


class DToutEffacerConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(JS, stubs=STUBS, extra=EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_tout_effacer_demande_confirmation_avant_dappeler_lapi(self):
        res = self._run(
            _OUVRIR
            + r"""
h(globalThis.__clic("[data-notif-clear-all]"));
await globalThis.__sleep(20);
__emit({
  confirms: globalThis.__confirms.length,
  endpoints: globalThis.__posts.map((p) => p.endpoint),
});
"""
        )
        self.assertEqual(
            res["confirms"],
            1,
            "« Tout effacer » doit passer par dangerConfirmModal (regle projet n3)",
        )
        self.assertNotIn(
            "runtime/clear_notifications",
            res["endpoints"],
            "l'API ne doit pas etre appelee tant que l'utilisateur n'a pas confirme",
        )

    def test_la_confirmation_porte_la_liste_et_la_consequence(self):
        """Regle n3 : confirmation + LISTE des elements + CONSEQUENCE."""
        res = self._run(
            _OUVRIR
            + r"""
h(globalThis.__clic("[data-notif-clear-all]"));
await globalThis.__sleep(20);
const o = globalThis.__confirms[0] || {};
__emit({
  title: o.title || null,
  items: o.items || null,
  consequence: o.consequence || null,
});
"""
        )
        self.assertIsNotNone(res["title"])
        self.assertIsNotNone(res["items"], "la modale doit lister les elements concernes")
        self.assertEqual(
            len(res["items"]),
            3,
            "la liste doit couvrir TOUTES les notifications, pas seulement celles que le filtre courant affiche",
        )
        self.assertIn("Apply termine avec 3 erreurs", res["items"])
        self.assertIn("Doublons detectes", res["items"])
        self.assertTrue(
            res["consequence"],
            "la consequence doit etre enoncee (perte definitive, aucun undo)",
        )

    def test_confirmer_declenche_bien_leffacement(self):
        """Le garde ne doit pas rendre l'action INATTEIGNABLE (cf. #1053)."""
        res = self._run(
            _OUVRIR
            + r"""
h(globalThis.__clic("[data-notif-clear-all]"));
await globalThis.__sleep(20);
await globalThis.__confirms[0].onConfirm();
await globalThis.__sleep(30);
__emit({ endpoints: globalThis.__posts.map((p) => p.endpoint) });
"""
        )
        self.assertIn("runtime/clear_notifications", res["endpoints"])
        self.assertIn(
            "runtime/get_notifications",
            res["endpoints"],
            "la liste doit etre rafraichie apres l'effacement",
        )

    def test_annuler_neffce_rien(self):
        """Ne pas confirmer = ne rien detruire."""
        res = self._run(
            _OUVRIR
            + r"""
h(globalThis.__clic("[data-notif-clear-all]"));
await globalThis.__sleep(50);
__emit({ endpoints: globalThis.__posts.map((p) => p.endpoint) });
"""
        )
        self.assertEqual(res["endpoints"], [])

    def test_bouton_desactive_ne_confirme_rien(self):
        """Zero notification : le bouton est `disabled`, aucune modale."""
        res = self._run(
            _OUVRIR
            + r"""
h(globalThis.__clic("[data-notif-clear-all]", { disabled: true }));
await globalThis.__sleep(20);
__emit({
  confirms: globalThis.__confirms.length,
  endpoints: globalThis.__posts.map((p) => p.endpoint),
});
"""
        )
        self.assertEqual(res["confirms"], 0)
        self.assertEqual(res["endpoints"], [])

    # ----------------------------------------------------- NON-REGRESSION
    def test_nonreg_tout_marquer_lu_reste_immediat(self):
        """Non destructif (rien n'est perdu) : pas de confirmation, sinon le
        garde devient un reflexe et ne protege plus rien."""
        res = self._run(
            _OUVRIR
            + r"""
h(globalThis.__clic("[data-notif-mark-all]"));
await globalThis.__sleep(30);
__emit({
  confirms: globalThis.__confirms.length,
  endpoints: globalThis.__posts.map((p) => p.endpoint),
});
"""
        )
        self.assertEqual(res["confirms"], 0)
        self.assertIn("runtime/mark_all_notifications_read", res["endpoints"])

    def test_nonreg_suppression_unitaire_reste_immediate(self):
        """Portee CHOISIE par l'utilisateur : pas de confirmation (critere du
        depot, cf. docstring de dangerConfirmModal)."""
        res = self._run(
            _OUVRIR
            + r"""
const ev = {
  target: {
    closest: (sel) => {
      if (sel === "[data-notif-dismiss]") {
        return { closest: (s2) => (s2 === "[data-notif-id]" ? { dataset: { notifId: "n1" } } : null) };
      }
      return null;
    },
  },
  stopPropagation() {},
};
h(ev);
await globalThis.__sleep(30);
__emit({
  confirms: globalThis.__confirms.length,
  endpoints: globalThis.__posts.map((p) => p.endpoint),
  body: globalThis.__posts.length ? globalThis.__posts[0].body : null,
});
"""
        )
        self.assertEqual(res["confirms"], 0)
        self.assertIn("runtime/dismiss_notification", res["endpoints"])
        self.assertEqual(res["body"], {"notification_id": "n1"})

    def test_nonreg_syntaxe_du_module(self):
        node_check(self, JS)


if __name__ == "__main__":
    unittest.main()
