"""Revue post-merge 2026-08-03 — « promesses non tenues » des raccourcis clavier.

Trois ecarts entre ce que l'interface ANNONCE et ce que le code FAIT :

1. F5 / palette « Rafraichir la vue » : `core/keyboard.js` et
   `components/command-palette.js` dispatchaient `cinesort:refresh` alors
   qu'AUCUN module ne l'ecoutait. La touche etait morte (et son
   `preventDefault()` inconditionnel), la commande de palette fermait la palette
   sans rien faire, et la modale F1 promettait « F5 : Rafraichir la vue ».

2. `views/aide.js` annoncait Ctrl+S = « Lancer un nouveau scan » alors que le
   raccourci emet `cinesort:save-request`, ecoute uniquement par /parametres ou
   il flushe le debounce de sauvegarde. Le meme libelle errone avait deja ete
   retire d'accueil.js sans que /aide soit mis a jour.

3. `views/aide.js` annoncait ↑/↓ = « Navigation dans listes (films, doublons,
   runs) » alors que seule la vue Doublons implemente ces touches.

4. Ctrl+Z dispatchait `cinesort:undo-shortcut`, dont l'unique auditeur vivait
   dans `library/lib-apply.js`, supprime a la migration ESM : la frappe ne
   faisait plus rien, et le libelle (« depuis Bibliotheque ») designait une vue
   qui n'a aucun flux d'undo. Le raccourci a ete RETIRE plutot que rebranche :
   `run/undo_last_apply` redeplace des fichiers sur le disque et doit rester
   derriere une confirmation explicite.

Les tests EXECUTENT la vraie source sous Node (imports stubbes, corps des
fonctions intact) : c'est le handler keydown reel qui tourne et le HTML
reellement produit par `_renderShortcutsSection()` qui est inspecte.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, node_check, require_node, run_module_test

KEYBOARD_JS = ROOT / "web" / "dashboard" / "core" / "keyboard.js"
PALETTE_JS = ROOT / "web" / "dashboard" / "components" / "command-palette.js"
AIDE_JS = ROOT / "web" / "dashboard" / "views" / "aide.js"

# --------------------------------------------------------------------------
# core/keyboard.js
# --------------------------------------------------------------------------
KEYBOARD_STUBS = r"""
globalThis.__nav = [];
const navigateTo = (hash) => { globalThis.__nav.push(hash); };
globalThis.__modals = [];
const showModal = (opts) => { globalThis.__modals.push(opts); };
const toggleSidebar = () => {};
const isRightPanelExpanded = () => false;
const setRightPanelExpanded = () => {};

const _win = new EventTarget();
_win.location = { hash: "#/bibliotheque?filter=hd" };
globalThis.window = _win;

globalThis.__keydown = null;
globalThis.document = {
  addEventListener: (type, fn) => { if (type === "keydown") globalThis.__keydown = fn; },
  removeEventListener() {},
  querySelector: () => null,
  getElementById: () => null,
  activeElement: { tagName: "BODY" },
};
globalThis.__fire = (init) => {
  const ev = Object.assign({ ctrlKey: false, altKey: false, shiftKey: false }, init);
  ev.defaultPrevented = false;
  ev.preventDefault = () => { ev.defaultPrevented = true; };
  globalThis.__keydown(ev);
  return ev;
};
"""

KEYBOARD_EXTRA = r"""
export const __h = { showHelp: _showHelp };
"""

# --------------------------------------------------------------------------
# components/command-palette.js
# --------------------------------------------------------------------------
PALETTE_STUBS = r"""
globalThis.__nav = [];
const navigateTo = (hash) => { globalThis.__nav.push(hash); };
const trapFocus = () => () => {};

globalThis.__dispatched = [];
const _win = new EventTarget();
_win.location = { hash: "#/accueil" };
globalThis.window = _win;
_win.addEventListener("cinesort:refresh", () => { globalThis.__dispatched.push("cinesort:refresh"); });

globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: () => null,
  createElement: () => ({
    classList: { add() {}, remove() {} }, style: {}, dataset: {},
    addEventListener() {}, appendChild() {}, querySelector: () => null,
    querySelectorAll: () => [], remove() {},
  }),
  body: { appendChild() {}, contains: () => false },
  activeElement: null,
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
"""

PALETTE_EXTRA = r"""
export const __h = { buildCommands: _buildCommands };
"""

# --------------------------------------------------------------------------
# views/aide.js
# --------------------------------------------------------------------------
AIDE_STUBS = r"""
const escapeHtml = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");
const apiPost = async () => ({ status: 200, data: { ok: true } });
const trapFocus = () => () => {};
globalThis.window = globalThis.window || { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = globalThis.document || {
  addEventListener() {}, removeEventListener() {},
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
"""

AIDE_EXTRA = r"""
export const __h = { renderShortcuts: _renderShortcutsSection, shortcuts: _SHORTCUTS };
"""


def _label_for(rows, keys):
    """Retrouve le libelle d'une ligne de la table des raccourcis."""
    for row in rows:
        if row["keys"] == keys:
            return row["label"]
    raise AssertionError(f"raccourci {keys} absent de la table")


class F5RafraichitLaVueTests(unittest.TestCase):
    """F5 doit REELLEMENT rafraichir la vue courante, pas seulement l'annoncer."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(KEYBOARD_JS, stubs=KEYBOARD_STUBS, extra=KEYBOARD_EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_f5_remonte_la_vue_courante(self):
        """ROUGE avant fix : `cinesort:refresh` partait vers zero auditeur, donc
        aucun refetch — et le preventDefault supprimait le rechargement natif."""
        res = self._run(r"""
M.initKeyboard();
const ev = globalThis.__fire({ key: "F5" });
__emit({ prevented: ev.defaultPrevented, nav: globalThis.__nav });
""")
        self.assertTrue(res["prevented"], "F5 reste intercepte par l'application")
        self.assertEqual(
            res["nav"],
            ["/bibliotheque?filter=hd"],
            f"F5 doit re-resoudre la route COURANTE (query comprise) — navigations observees : {res['nav']!r}",
        )

    def test_evenement_refresh_est_ecoute(self):
        """La commande de palette « Rafraichir la vue » emet exactement
        `cinesort:refresh` sur window : cet evenement doit avoir un auditeur."""
        res = self._run(r"""
M.initKeyboard();
globalThis.window.dispatchEvent(new CustomEvent("cinesort:refresh"));
__emit({ nav: globalThis.__nav });
""")
        self.assertEqual(
            res["nav"],
            ["/bibliotheque?filter=hd"],
            "un dispatch de cinesort:refresh (palette Ctrl+K) doit rafraichir la vue",
        )

    def test_double_init_ne_rafraichit_pas_deux_fois(self):
        """L'auditeur est pose dans initKeyboard : un double appel ne doit pas
        produire deux remontages par frappe (double refetch reseau)."""
        res = self._run(r"""
M.initKeyboard();
M.initKeyboard();
globalThis.window.dispatchEvent(new CustomEvent("cinesort:refresh"));
__emit({ nav: globalThis.__nav });
""")
        self.assertEqual(len(res["nav"]), 1, f"un seul refresh attendu, obtenu {res['nav']!r}")

    def test_hash_vide_retombe_sur_accueil(self):
        """Bord : premiere ouverture sans hash — F5 ne doit pas naviguer vers ''."""
        res = self._run(r"""
globalThis.window.location.hash = "";
M.initKeyboard();
globalThis.__fire({ key: "F5" });
__emit({ nav: globalThis.__nav });
""")
        self.assertEqual(res["nav"], ["/accueil"])

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_ctrl_s_emet_toujours_save_request(self):
        """Ctrl+S ne doit PAS avoir ete transforme en scan ni en refresh."""
        res = self._run(r"""
globalThis.__events = [];
globalThis.window.addEventListener("cinesort:save-request", () => globalThis.__events.push("save"));
M.initKeyboard();
const ev = globalThis.__fire({ key: "s", ctrlKey: true });
__emit({ prevented: ev.defaultPrevented, events: globalThis.__events, nav: globalThis.__nav });
""")
        self.assertTrue(res["prevented"])
        self.assertEqual(res["events"], ["save"])
        self.assertEqual(res["nav"], [], "Ctrl+S ne navigue nulle part")

    def test_nonreg_alt_navigation_intacte(self):
        res = self._run(r"""
M.initKeyboard();
globalThis.__fire({ key: "3", altKey: true });
__emit({ nav: globalThis.__nav });
""")
        self.assertEqual(res["nav"], ["/bibliotheque"])

    def test_nonreg_modale_f1_annonce_toujours_f5(self):
        """La modale d'aide continue de documenter F5 — et c'est desormais vrai."""
        res = self._run(r"""
M.initKeyboard();
M.__h.showHelp();
__emit({ body: globalThis.__modals[0].body });
""")
        self.assertIn("<kbd>F5</kbd>", res["body"])
        self.assertIn("Rafraichir la vue", res["body"])

    def test_nonreg_syntaxe(self):
        node_check(self, KEYBOARD_JS)


class CtrlZPlusPromisTests(unittest.TestCase):
    """Ctrl+Z n'annulait rien : la promesse a ete retiree, pas laissee en place."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(KEYBOARD_JS, stubs=KEYBOARD_STUBS, extra=KEYBOARD_EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_ctrl_z_nintercepte_plus_la_frappe(self):
        """ROUGE avant fix : preventDefault() + dispatch de `cinesort:undo-shortcut`
        vers zero auditeur. La frappe doit desormais redescendre au navigateur."""
        res = self._run(r"""
globalThis.__events = [];
const _rawDispatch = globalThis.window.dispatchEvent.bind(globalThis.window);
globalThis.window.dispatchEvent = (e) => { globalThis.__events.push(e.type); return _rawDispatch(e); };
M.initKeyboard();
const ev = globalThis.__fire({ key: "z", ctrlKey: true });
__emit({ prevented: ev.defaultPrevented, events: globalThis.__events, nav: globalThis.__nav });
""")
        self.assertFalse(
            res["prevented"],
            "Ctrl+Z ne doit plus etre consomme par l'app (l'undo natif reste intact)",
        )
        self.assertEqual(
            res["events"],
            [],
            f"aucun evenement ne doit partir sur Ctrl+Z ; observes : {res['events']!r}",
        )
        self.assertEqual(res["nav"], [], "Ctrl+Z ne doit declencher aucune navigation")

    def test_aucun_dispatch_undo_shortcut_dans_le_module(self):
        """Filet complementaire : plus aucune emission de l'evenement orphelin,
        quelle que soit la touche."""
        res = self._run(r"""
globalThis.__events = [];
const _rawDispatch = globalThis.window.dispatchEvent.bind(globalThis.window);
globalThis.window.dispatchEvent = (e) => { globalThis.__events.push(e.type); return _rawDispatch(e); };
M.initKeyboard();
for (const key of ["z", "Z", "s", "k", "b", "i", ",", "F1", "F5", "Escape", "?"]) {
  globalThis.__fire({ key, ctrlKey: true });
  globalThis.__fire({ key });
}
__emit({ events: globalThis.__events });
""")
        self.assertNotIn("cinesort:undo-shortcut", res["events"])

    def test_modale_f1_ne_promet_plus_ctrl_z(self):
        res = self._run(r"""
M.initKeyboard();
M.__h.showHelp();
__emit({ body: globalThis.__modals[0].body });
""")
        self.assertNotIn("<kbd>Z</kbd>", res["body"])
        self.assertNotIn("depuis Bibliotheque", res["body"])

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_ctrl_z_dans_un_champ_texte_reste_natif(self):
        """Assertion vraie AVANT comme APRES le fix : dans un input, l'undo natif
        du navigateur n'est jamais bloque."""
        res = self._run(r"""
globalThis.document.activeElement = { tagName: "INPUT" };
M.initKeyboard();
const ev = globalThis.__fire({ key: "z", ctrlKey: true });
__emit({ prevented: ev.defaultPrevented });
""")
        self.assertFalse(res["prevented"])


class PaletteRafraichirTests(unittest.TestCase):
    """L'entree de palette « Rafraichir la vue » emet bien le contrat attendu."""

    def setUp(self) -> None:
        require_node(self)

    def test_commande_refresh_emet_cinesort_refresh(self):
        res = run_module_test(
            PALETTE_JS,
            stubs=PALETTE_STUBS,
            extra=PALETTE_EXTRA,
            driver=r"""
const cmds = M.__h.buildCommands();
const refresh = cmds.find((c) => c.id === "refresh");
if (refresh) refresh.run();
__emit({
  present: !!refresh,
  hint: refresh ? refresh.hint : null,
  dispatched: globalThis.__dispatched,
});
""",
        )
        self.assertTrue(res["present"], "la commande 'refresh' doit exister dans la palette")
        self.assertEqual(
            res["dispatched"],
            ["cinesort:refresh"],
            "la commande doit emettre exactement le nom d'evenement ecoute par keyboard.js",
        )

    def test_nonreg_syntaxe(self):
        node_check(self, PALETTE_JS)


class AideLibellesFidelesTests(unittest.TestCase):
    """La table des raccourcis de /aide ne doit annoncer que ce qui existe."""

    def setUp(self) -> None:
        require_node(self)

    def _render(self) -> dict:
        return run_module_test(
            AIDE_JS,
            stubs=AIDE_STUBS,
            extra=AIDE_EXTRA,
            driver=r"""
__emit({ html: M.__h.renderShortcuts(), rows: M.__h.shortcuts });
""",
        )

    # ---------------------------------------------------------------- ROUGE
    def test_ctrl_s_ne_promet_plus_un_scan(self):
        """ROUGE avant fix : la ligne Ctrl+S annoncait « Lancer un nouveau scan »
        alors que la touche flushe la sauvegarde des reglages."""
        res = self._render()
        label = _label_for(res["rows"], ["Ctrl", "S"])
        self.assertNotIn(
            "scan",
            label.lower(),
            f"Ctrl+S ne lance aucun scan ; libelle affiche = {label!r}",
        )
        self.assertIn("nregistr", label, f"le libelle doit decrire la sauvegarde ; obtenu {label!r}")
        self.assertNotIn("Lancer un nouveau scan", res["html"])

    def test_fleches_ne_promettent_que_les_doublons(self):
        """ROUGE avant fix : « films, doublons, runs » alors que seule la vue
        Doublons implemente ArrowUp/ArrowDown."""
        res = self._render()
        label = _label_for(res["rows"], ["↑", "↓"])
        self.assertIn("doublons", label.lower())
        self.assertNotIn("films", label.lower(), f"libelle trop large : {label!r}")
        self.assertNotIn("runs", label.lower(), f"libelle trop large : {label!r}")

    def test_ctrl_z_absent_de_la_table(self):
        """ROUGE avant fix : la table annoncait « Annuler le dernier apply
        (depuis Bibliotheque) » pour une touche qui ne faisait rien, dans une vue
        qui n'a aucun flux d'undo."""
        res = self._render()
        keys = ["+".join(r["keys"]) for r in res["rows"]]
        self.assertNotIn("Ctrl+Z", keys, "le raccourci Ctrl+Z a ete retire du code, pas seulement du libelle")
        self.assertNotIn("Bibliothèque", res["html"])

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_table_toujours_rendue_et_complete(self):
        res = self._render()
        self.assertIn("aide-shortcuts-table", res["html"])
        keys = ["+".join(r["keys"]) for r in res["rows"]]
        for expected in ("Ctrl+K", "Ctrl+S", "Ctrl+B", "Ctrl+I", "Ctrl+,", "↑+↓", "Alt+1..7"):
            self.assertIn(expected, keys, f"raccourci {expected} disparu de la table")

    def test_nonreg_syntaxe(self):
        node_check(self, AIDE_JS)


if __name__ == "__main__":
    unittest.main()
