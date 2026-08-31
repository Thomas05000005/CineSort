"""LOT 5 C — le drawer inspecteur de `views/processing.js` fuit au demontage.

`_renderInspectorMobileDrawer()` pose un handler `keydown` ANONYME sur
`document` :

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") _closeInspectorDrawer();
    });

Sans reference nommee, ce handler ne peut plus jamais etre retire.
`unmountProcessing()` — que le routeur appelle avant chaque navigation — ne
nettoie que le timer de poll et `containerRef.innerHTML`. Or le drawer et son
voile sont ajoutes a `document.body`, pas au conteneur de la vue : ils
survivent donc eux aussi.

Deux consequences observables :

  1. **DOM orphelin visible.** Quitter Traitement avec le drawer OUVERT laisse
     l'`aside` (`transform: translateX(0)`) et son voile (`hidden = false`)
     par-dessus l'ecran suivant.
  2. **Handler global perpetuel.** Le listener `keydown` reste sur `document`
     pour toute la duree de la session, sur toutes les autres vues.

Les tests executent la VRAIE source du module sous Node (imports + DOM
stubbes), cf `tests/_jsexec.py`.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, node_check, require_node, run_module_test

JS = ROOT / "web" / "dashboard" / "views" / "processing.js"

STUBS = r"""
/* --- stubs des imports --- */
const apiPost = async () => ({ ok: true });
const escapeHtml = (s) => String(s == null ? "" : s);
const getConfidenceThresholdsSync = () => ({ high: 85, low: 60 });
const fetchConfidenceThresholds = async () => ({ high: 85, low: 60 });
const showToast = () => {};
const trapFocus = () => () => {};
const dangerConfirmModal = () => {};
const buildEmptyState = () => "";
const bindEmptyStateCta = () => {};

/* --- DOM minimal, avec registre de listeners sur `document` --- */
globalThis.__docListeners = [];

function __makeEl(tag) {
  const el = {
    tagName: tag, id: "", className: "", hidden: false, _html: "",
    style: { cssText: "", transform: "" },
    _attrs: {}, dataset: {}, children: [], parent: null,
    setAttribute(k, v) { el._attrs[k] = String(v); },
    getAttribute: (k) => (k in el._attrs ? el._attrs[k] : null),
    removeAttribute(k) { delete el._attrs[k]; },
    addEventListener() {}, removeEventListener() {},
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
    closest: () => null,
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; },
    set(v) {
      el._html = String(v);
      // Le vrai DOM materialise les noeuds decrits par le HTML : sans ca,
      // `document.getElementById("v5InspectorBody")` rendrait null et
      // `_openInspectorDrawer` sortirait par sa garde `if (!drawer || !body)`.
      // On ne materialise que ce dont le module se sert : les elements A ID.
      for (const c of el.children.slice()) c.remove();
      for (const m of el._html.matchAll(/\sid="([A-Za-z0-9_-]+)"/g)) {
        const enfant = __makeEl("div");
        enfant.id = m[1];
        el.appendChild(enfant);
      }
    },
  });
  return el;
}

const __body = __makeEl("body");

function __findById(node, id) {
  for (const c of node.children) {
    if (c.id === id) return c;
    const found = __findById(c, id);
    if (found) return found;
  }
  return null;
}

globalThis.document = {
  body: __body,
  createElement: (t) => __makeEl(t),
  getElementById: (id) => __findById(__body, id),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener(type, fn) { globalThis.__docListeners.push({ type, fn }); },
  removeEventListener(type, fn) {
    const i = globalThis.__docListeners.findIndex((l) => l.type === type && l.fn === fn);
    if (i >= 0) globalThis.__docListeners.splice(i, 1);
  },
};

globalThis.__mobile = true;
globalThis.window = {
  matchMedia: (q) => ({ matches: String(q).includes("min-width: 768px") ? !globalThis.__mobile : globalThis.__mobile }),
  addEventListener() {}, removeEventListener() {},
  location: { hash: "" },
};
globalThis.localStorage = {
  _m: {},
  getItem(k) { return k in this._m ? this._m[k] : null; },
  setItem(k, v) { this._m[k] = String(v); },
  removeItem(k) { delete this._m[k]; },
};

/** Nombre de listeners `keydown` encore poses sur `document`. */
globalThis.__keydownCount = () => globalThis.__docListeners.filter((l) => l.type === "keydown").length;
/** Simule un appui touche : rejoue tous les handlers `keydown` de `document`. */
globalThis.__pressKey = (key) => {
  for (const l of globalThis.__docListeners.filter((x) => x.type === "keydown")) {
    l.fn({ key });
  }
};
"""

EXTRA = r"""
export const __h = {
  openDrawer: _openInspectorDrawer,
  closeDrawer: _closeInspectorDrawer,
  state: _state,
};
"""


class CDrawerInspecteurDemontageTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(JS, stubs=STUBS, extra=EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_le_drawer_ouvert_ne_survit_pas_a_la_navigation(self):
        """Quitter Traitement avec le drawer ouvert ne doit rien laisser sur
        l'ecran suivant."""
        res = self._run(
            r"""
M.__h.state.decisions = { R1: { decision: "accepted", ok: true } };
M.__h.openDrawer("R1");
const ouvert = document.getElementById("v5ProcessingInspectorDrawer");
const voileOuvert = document.getElementById("v5ProcessingInspectorOverlay");
const avant = {
  drawerPresent: ouvert != null,
  transform: ouvert ? ouvert.style.transform : null,
  voileMasque: voileOuvert ? voileOuvert.hidden : null,
};
M.unmountProcessing();   // le routeur demonte la vue
__emit({
  avant,
  drawerApres: document.getElementById("v5ProcessingInspectorDrawer") != null,
  voileApres: document.getElementById("v5ProcessingInspectorOverlay") != null,
});
"""
        )
        # Le drawer etait bien ouvert et visible avant le demontage.
        self.assertTrue(res["avant"]["drawerPresent"])
        self.assertEqual(res["avant"]["transform"], "translateX(0)")
        self.assertFalse(res["avant"]["voileMasque"], "le voile est visible quand le drawer est ouvert")
        # ... et il ne doit plus rien rester apres.
        self.assertFalse(
            res["drawerApres"],
            "le drawer reste dans document.body et se superpose a l'ecran suivant",
        )
        self.assertFalse(res["voileApres"], "le voile reste dans document.body")

    def test_le_handler_keydown_est_retire_au_demontage(self):
        """Le handler etait ANONYME : aucune reference pour le retirer."""
        res = self._run(
            r"""
const avantMontage = globalThis.__keydownCount();
M.__h.state.decisions = { R1: { decision: "accepted", ok: true } };
M.__h.openDrawer("R1");
const pendant = globalThis.__keydownCount();
M.unmountProcessing();
__emit({ avantMontage, pendant, apres: globalThis.__keydownCount() });
"""
        )
        self.assertEqual(res["avantMontage"], 0)
        self.assertEqual(res["pendant"], 1, "le drawer pose bien un handler keydown sur document")
        self.assertEqual(
            res["apres"],
            0,
            "le handler keydown doit etre retire de document au demontage de la vue",
        )

    def test_echap_apres_demontage_ne_touche_plus_le_drawer_dune_autre_vue(self):
        """Le handler survivant agissait sur TOUTES les vues suivantes."""
        res = self._run(
            r"""
M.__h.state.decisions = { R1: { decision: "accepted", ok: true } };
M.__h.openDrawer("R1");
M.unmountProcessing();
// On vide le body de tout reliquat (le shell recree son DOM a chaque vue),
// puis une AUTRE vue pose un element homonyme. Un Echap ne doit reveiller
// aucun reliquat de Traitement : le handler ne doit plus exister.
for (const c of document.body.children.slice()) c.remove();
const autre = document.createElement("aside");
autre.id = "v5ProcessingInspectorDrawer";
autre.style.transform = "translateX(0)";
document.body.appendChild(autre);
globalThis.__pressKey("Escape");
__emit({ transform: autre.style.transform });
"""
        )
        self.assertEqual(
            res["transform"],
            "translateX(0)",
            "un Echap apres demontage ne doit plus atteindre _closeInspectorDrawer",
        )

    # ----------------------------------------------------- NON-REGRESSION
    def test_nonreg_echap_ferme_le_drawer_tant_que_la_vue_est_montee(self):
        res = self._run(
            r"""
M.__h.state.decisions = { R1: { decision: "accepted", ok: true } };
M.__h.openDrawer("R1");
const drawer = document.getElementById("v5ProcessingInspectorDrawer");
const avant = drawer.style.transform;
globalThis.__pressKey("Escape");
__emit({ avant, apres: drawer.style.transform, ariaHidden: drawer.getAttribute("aria-hidden") });
"""
        )
        self.assertEqual(res["avant"], "translateX(0)")
        self.assertEqual(res["apres"], "translateX(100%)", "Echap doit fermer le drawer")
        self.assertEqual(res["ariaHidden"], "true")

    def test_nonreg_remontage_redonne_un_drawer_fonctionnel(self):
        """Le drawer doit rester utilisable apres un aller-retour de navigation
        (et les listeners ne doivent pas s'accumuler)."""
        res = self._run(
            r"""
M.__h.state.decisions = { R1: { decision: "accepted", ok: true } };
M.__h.openDrawer("R1");
M.unmountProcessing();
M.__h.openDrawer("R1");            // retour sur Traitement
const drawer = document.getElementById("v5ProcessingInspectorDrawer");
const ouvert = drawer ? drawer.style.transform : null;
const listeners = globalThis.__keydownCount();
globalThis.__pressKey("Escape");
__emit({ ouvert, listeners, apresEchap: drawer ? drawer.style.transform : null });
"""
        )
        self.assertEqual(res["ouvert"], "translateX(0)", "le drawer doit se rouvrir apres remontage")
        self.assertEqual(res["listeners"], 1, "un seul handler keydown, pas d'accumulation")
        self.assertEqual(res["apresEchap"], "translateX(100%)", "Echap doit encore fermer le drawer")

    def test_nonreg_desktop_pas_de_drawer(self):
        res = self._run(
            r"""
globalThis.__mobile = false;
M.__h.state.decisions = { R1: { decision: "accepted", ok: true } };
M.__h.openDrawer("R1");
__emit({
  drawer: document.getElementById("v5ProcessingInspectorDrawer") != null,
  listeners: globalThis.__keydownCount(),
});
"""
        )
        self.assertFalse(res["drawer"], "en desktop le drawer n'est pas monte")
        self.assertEqual(res["listeners"], 0)

    def test_nonreg_syntaxe_du_module(self):
        node_check(self, JS)


if __name__ == "__main__":
    unittest.main()
