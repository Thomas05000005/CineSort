"""Ultra-audit 2026-08-03 — lot NUANCES frontend (N01/N07/N08/N09/N13/N14/N15/N33/N35).

Tous les tests EXECUTENT la vraie source `web/dashboard/**/*.js` sous Node via
`tests/_jsexec` (imports neutralises, corps de fonction jamais reecrit). Aucune
assertion ne compare une chaine de CODE SOURCE : on observe des evenements
emis, des appels captures et du HTML RENDU — c'est-a-dire ce que l'utilisateur
recoit reellement.

Findings couverts :
  N01/N08  core/keyboard.js  Ctrl+Z dispatchait `cinesort:undo-shortcut`, un
                             evenement sans aucun auditeur depuis la migration
                             ESM : la frappe etait consommee pour rien et
                             l'aide promettait un undo inexistant.
  N01      app.js:519        le listener `cinesort:undo` (refresh des badges
                             sidebar) etait orphelin : plus personne n'emettait
                             l'evenement. traitement.js et historique.js
                             l'emettent desormais apres un undo REUSSI.
  N09      core/keyboard.js  `cinesort:refresh` (F5 + palette Ctrl+K) etait
                             dispatche a deux endroits et ecoute a zero.
  N07      traitement.js     la modale d'apply annoncait « N fichiers
                             renommes/deplaces » avec N = nombre de FILMS
                             approuves, contredisant le resume juste au-dessus.
  N13      modal.js          la modale danger ne se fermait qu'apres resolution
                             de onConfirm : son overlay masquait la barre de
                             progression pendant tout l'apply.
  N14      bibliotheque.js   le CTA « Lancer un scan » de la bibliotheque vide
                             pointait sur /processing (vue interne) au lieu de
                             /traitement (vue du menu).
  N15      accueil.js        tooltip mensonger sur l'entree Traitement grisee,
                             et titre d'origine detruit au lieu d'etre restaure.
  N33      core/api.js       sur 5xx, un instantane localStorage vieux de 24 h
                             etait servi SANS aucun signalement utilisateur.
  N35      traitement.js     un apply retournant `errors > 0` (fichier
                             verrouille) affichait un toast VERT « Apply
                             termine ».

Relecture adversaire de la PR #873 — deux REGRESSIONS que le lot creait
lui-meme, corrigees et verrouillees ici :

  point 1  traitement.js     F5 pendant un apply reel -> le nouvel auditeur
                             `cinesort:refresh` re-monte la route ->
                             `unmountTraitement()` -> `_abortController.abort()`
                             -> le POST `run/apply` (emis avec `_signal()`)
                             rejette un AbortError -> toast ROUGE « Erreur lors
                             de l'apply. » PENDANT que le backend deplace les
                             fichiers. Avant la PR, F5 etait 100 % inerte.
                             Couvert par `ApplyAbortPendantLeVolTests` sur les
                             TROIS chemins qui postent avec `_signal()` (apply
                             reel, dry-run, undo), + non-reg : une vraie panne
                             reseau reste un toast rouge.
  point 2  traitement.js     la modale de danger SOUS-annoncait : `opsLine` ne
                             lisait que `totals.renames`/`totals.moves`, or
                             `build_apply_preview` force
                             `quarantine_unapproved=False` — « 0 renommage · 0
                             deplacement » pour un apply qui deplace 50 dossiers
                             vers `_review/`. Couvert par un test d'INVARIANT
                             (`test_invariant_aucune_operation_disque_prevue_ne_manque_a_la_modale`)
                             qui verrouille la chaine cle du payload run/apply
                             -> registre `_APPLY_DISK_OPS` -> texte rendu.

Fusion de `origin/main` dans cette branche (2026-08-04) — deux ajustements que
la fusion TEXTUELLE ne pouvait pas voir :

  N09      les deux branches avaient cable un auditeur de `cinesort:refresh`,
           ce lot dans `app.js`, main dans `core/keyboard.js`. Les additionner
           aurait fait DEUX remontages de vue par F5. Un seul est conserve
           (celui de main) et l'unicite est desormais un test
           (`RefreshAuditeurUniqueTests`).
  stubs    `historique.js` importe depuis main `cachedGetSettings` et
           `deriveRunStatus` : les stubs de ce fichier ont ete completes, sans
           quoi l'appel levait un ReferenceError avale par un `try/catch` — un
           vert obtenu sur un module amoindri.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, inline_module, node_check, require_node, run_module_test

KEYBOARD_JS = ROOT / "web" / "dashboard" / "core" / "keyboard.js"
API_JS = ROOT / "web" / "dashboard" / "core" / "api.js"
APP_JS = ROOT / "web" / "dashboard" / "app.js"
MODAL_JS = ROOT / "web" / "dashboard" / "components" / "modal.js"
TRAITEMENT_JS = ROOT / "web" / "dashboard" / "views" / "traitement.js"
HISTORIQUE_JS = ROOT / "web" / "dashboard" / "views" / "historique.js"
BIBLIOTHEQUE_JS = ROOT / "web" / "dashboard" / "views" / "bibliotheque.js"
ACCUEIL_JS = ROOT / "web" / "dashboard" / "views" / "accueil.js"


# ===================================================================== N01/N08/N09
# core/keyboard.js — un seul listener 'keydown' est pose par initKeyboard ; on
# le recupere et on lui envoie de vrais objets KeyboardEvent-like en notant
# preventDefault() et les CustomEvent emis.

_KEYBOARD_STUBS = r"""
globalThis.__dispatched = [];
globalThis.__modals = [];
globalThis.__navs = [];
globalThis.__keydown = null;

const navigateTo = (h) => { globalThis.__navs.push(h); };
const showModal = (o) => { globalThis.__modals.push(o); };
const toggleSidebar = () => {};
const isRightPanelExpanded = () => false;
const setRightPanelExpanded = () => {};

globalThis.__activeTag = "BODY";
globalThis.document = {
  addEventListener(type, fn) { if (type === "keydown") globalThis.__keydown = fn; },
  removeEventListener() {},
  querySelector: () => null,
  getElementById: () => null,
  get activeElement() { return { tagName: globalThis.__activeTag }; },
};
// `__winOn` note les inscriptions faites sur window (sans les cabler : ces
// tests-la observent ce qui est EMIS). L'inventaire sert au test d'unicite de
// l'auditeur `cinesort:refresh`, cf. RefreshAuditeurUniqueTests.
globalThis.__winOn = [];
globalThis.window = {
  dispatchEvent(ev) { globalThis.__dispatched.push(ev.type); return true; },
  addEventListener(type) { globalThis.__winOn.push(type); },
  removeEventListener() {},
};
globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
globalThis.setTimeout = setTimeout;
"""

_KEYBOARD_EXTRA = r"""
export const __h = {
  press: (init) => {
    let prevented = false;
    const ev = Object.assign(
      { key: "", ctrlKey: false, altKey: false, shiftKey: false,
        preventDefault() { prevented = true; } },
      init,
    );
    globalThis.__keydown(ev);
    return prevented;
  },
  reset: () => { globalThis.__dispatched.length = 0; globalThis.__modals.length = 0; },
};
"""


class KeyboardShortcutsTests(unittest.TestCase):
    """N01/N08 (Ctrl+Z inerte) et N09 (F5 -> cinesort:refresh)."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(KEYBOARD_JS, stubs=_KEYBOARD_STUBS, extra=_KEYBOARD_EXTRA, driver=driver)

    def test_ctrl_z_ne_consomme_plus_la_frappe_et_nemet_plus_rien(self):
        """N01/N08 ROUGE avant fix : preventDefault + dispatch d'un evenement
        que plus aucun module n'ecoute -> frappe volee pour rien."""
        res = self._run(
            r"""
M.initKeyboard();
const prevented = M.__h.press({ key: "z", ctrlKey: true });
__emit({ prevented, dispatched: globalThis.__dispatched });
"""
        )
        self.assertFalse(
            res["prevented"],
            "Ctrl+Z ne doit plus appeler preventDefault : le raccourci n'existe plus",
        )
        self.assertEqual(res["dispatched"], [], "Ctrl+Z ne doit plus emettre d'evenement orphelin")

    def test_ctrl_z_dans_un_champ_texte_reste_inoffensif(self):
        """Non-regression : l'undo natif du navigateur dans un input n'a jamais
        ete casse (la garde _isInputFocused precedait le preventDefault) et ne
        doit pas le devenir."""
        res = self._run(
            r"""
M.initKeyboard();
globalThis.__activeTag = "INPUT";
const prevented = M.__h.press({ key: "z", ctrlKey: true });
__emit({ prevented, dispatched: globalThis.__dispatched });
"""
        )
        self.assertFalse(res["prevented"])
        self.assertEqual(res["dispatched"], [])

    def test_laide_clavier_ne_promet_plus_dundo(self):
        """L'aide F1 annoncait « Ctrl+Z : Annuler la derniere application ».
        On verifie le HTML REELLEMENT rendu par _showHelp, pas la source."""
        res = self._run(
            r"""
M.initKeyboard();
M.__h.press({ key: "F1" });
const body = globalThis.__modals.length ? String(globalThis.__modals[0].body) : "";
__emit({
  count: globalThis.__modals.length,
  promettUndo: /Annuler la derniere application/i.test(body),
  mentionneF5: /Rafraichir la vue/i.test(body),
});
"""
        )
        self.assertEqual(res["count"], 1, "F1 doit toujours ouvrir l'aide")
        self.assertFalse(res["promettUndo"], "l'aide ne doit plus promettre un undo inexistant")
        self.assertTrue(res["mentionneF5"], "les autres raccourcis restent documentes")

    def test_f5_emet_toujours_cinesort_refresh(self):
        """N09 : le producteur de l'evenement reste en place (c'est le
        consommateur qui manquait, cf AppRefreshListenerTests)."""
        res = self._run(
            r"""
M.initKeyboard();
const prevented = M.__h.press({ key: "F5" });
__emit({ prevented, dispatched: globalThis.__dispatched });
"""
        )
        self.assertTrue(res["prevented"])
        self.assertEqual(res["dispatched"], ["cinesort:refresh"])

    def test_nonreg_autres_raccourcis_intacts(self):
        res = self._run(
            r"""
M.initKeyboard();
M.__h.press({ key: "s", ctrlKey: true });
M.__h.press({ key: "k", ctrlKey: true });
const d1 = globalThis.__dispatched.slice();
M.__h.press({ key: "3" });
M.__h.press({ key: "2", altKey: true });
__emit({ dispatched: d1, navs: globalThis.__navs });
"""
        )
        self.assertEqual(res["dispatched"], ["cinesort:save-request", "cinesort:command-palette"])
        self.assertEqual(res["navs"], ["/bibliotheque", "/traitement"])

    def test_nonreg_syntaxe(self):
        node_check(self, KEYBOARD_JS)


# ============================================================================ N09
# app.js — le module enregistre ses listeners globaux au chargement. On les
# capture et on les invoque.

_APP_WINDOW = r"""
globalThis.__winListeners = {};
globalThis.__docListeners = {};
globalThis.__navs = [];
globalThis.__routes = [];
globalThis.__currentRoute = "/bibliotheque";

globalThis.window = {
  addEventListener(t, f) { (globalThis.__winListeners[t] = globalThis.__winListeners[t] || []).push(f); },
  removeEventListener() {},
  dispatchEvent() {},
  location: { hash: "#/bibliotheque", origin: "http://x", search: "", href: "http://x/" },
  setTimeout, clearTimeout, setInterval, clearInterval,
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  history: { replaceState() {} },
  navigator: { userAgent: "node" },
};
globalThis.document = {
  addEventListener(t, f) { (globalThis.__docListeners[t] = globalThis.__docListeners[t] || []).push(f); },
  removeEventListener() {},
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => null,
  createElement: () => ({ style: {}, classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
                          setAttribute() {}, appendChild() {}, addEventListener() {}, remove() {} }),
  body: { classList: { add() {}, remove() {}, toggle() {} }, appendChild() {} },
  documentElement: { classList: { add() {}, remove() {}, toggle() {} }, setAttribute() {}, style: {} },
  readyState: "loading",
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {}, key: () => null, length: 0 };
globalThis.location = globalThis.window.location;
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
globalThis.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = o && o.detail; } };
"""

_APP_STUBS = r"""
const registerRoute = (h) => { globalThis.__routes.push(h); };
const requireAuth = () => true;
const startRouter = () => {};
const navigateTo = (h) => { globalThis.__navs.push(h); };
const currentRoute = () => globalThis.__currentRoute;
const apiPost = async () => ({ status: 200, data: { ok: true } });
const cachedGetSettings = async () => ({ status: 200, data: { ok: true } });
const initI18n = async () => {};
const setLocale = () => {};
const hasToken = () => true;
const onClearToken = () => {};
const setToken = () => {};
const markTokenAbsent = () => {};
const markTokenReady = () => {};
const $$ = () => [];
const renderFilmDetail = async () => {};
const cleanupExpiredDrafts = () => {};
const decorateMainButtons = () => {};
const initAutoTooltip = () => {};
const initCommandPalette = () => {};
const initCopyToClipboard = () => {};
const initDropHandlers = () => {};
const initGlossaryTooltips = () => {};
const initKeyboard = () => {};
const initScanBanner = () => {};
const initLogin = () => {};
const initAccueil = () => {}; const unmountAccueil = () => {};
const initAide = () => {}; const unmountAide = () => {};
const initBibliotheque = () => {}; const unmountBibliotheque = () => {};
const initDoublons = () => {}; const unmountDoublons = () => {};
const initHistorique = () => {}; const unmountHistorique = () => {};
const initParametres = () => {}; const unmountParametres = () => {};
const initProcessing = async () => {}; const unmountProcessing = () => {};
const initQualite = () => {}; const unmountQualite = () => {};
const initRunDetailPage = () => {}; const unmountRunDetailPage = () => {};
const initTraitement = () => {}; const unmountTraitement = () => {};
const _ns = () => new Proxy({}, { get: () => (() => {}) });
const sidebarV5 = _ns();
const topBarV5 = _ns();
const breadcrumb = _ns();
const notifCenter = _ns();
const rightPanel = _ns();
"""

_APP_EXTRA = r"""
export const __h = {
  fire: (type) => {
    const fns = globalThis.__winListeners[type] || [];
    for (const f of fns) f({ type });
    return fns.length;
  },
};
"""


class RefreshAuditeurUniqueTests(unittest.TestCase):
    """N09 : `cinesort:refresh` avait 2 emetteurs et 0 auditeur.

    Fusion main <- PR #873 — les DEUX branches ont corrige ce defaut, chacune de
    son cote : ce lot posait l'auditeur dans `app.js` (`currentRoute()` +
    navigateTo), la revue post-merge le posait dans `core/keyboard.js`
    (`_refreshCurrentView`). Textuellement les deux apports fusionnaient sans
    conflit ; semantiquement ils s'additionnaient : DEUX `navigateTo` par F5,
    donc deux `hashchange` synchrones, donc un double cleanup + double `init()`
    de la vue (double refetch reseau, le 2e remontage annulant les requetes du
    1er via `abortCurrentNav`). Un seul auditeur a ete conserve, celui de
    `core/keyboard.js`, et c'est cette UNICITE que ces tests verrouillent.
    """

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(
            APP_JS, stubs=_APP_WINDOW + _APP_STUBS, extra=_APP_EXTRA, driver=driver + "\nprocess.exit(0);\n"
        )

    def test_un_seul_auditeur_de_cinesort_refresh(self):
        """ROUGE si l'un des deux auditeurs revient : on compte les inscriptions
        REELLES sur `window` faites par les deux modules concernes, et la somme
        doit valoir exactement 1.

        Le comptage se fait module par module (le harnais charge une source a la
        fois) mais porte sur le meme contrat : `window.addEventListener(
        "cinesort:refresh", ...)`. Somme = 2 -> double remontage de la vue par
        F5 ; somme = 0 -> la touche redevient morte.
        """
        app = self._run(
            r"""
__emit({ n: (globalThis.__winListeners["cinesort:refresh"] || []).length });
"""
        )
        kb = run_module_test(
            KEYBOARD_JS,
            stubs=_KEYBOARD_STUBS,
            extra=_KEYBOARD_EXTRA,
            driver=r"""
M.initKeyboard();
__emit({ n: globalThis.__winOn.filter((t) => t === "cinesort:refresh").length });
""",
        )
        self.assertEqual(
            app["n"] + kb["n"],
            1,
            f"auditeurs de cinesort:refresh — app.js: {app['n']}, keyboard.js: {kb['n']} (attendu : 1 au total)",
        )
        self.assertEqual(kb["n"], 1, "l'auditeur unique vit dans core/keyboard.js (au plus pres du dispatch)")
        self.assertEqual(app["n"], 0, "app.js ne doit plus en poser un second")

    def test_lauditeur_unique_remonte_la_route_courante_une_seule_fois(self):
        """L'unicite ne vaut que si l'auditeur restant fait REELLEMENT le travail
        (sinon on aurait juste supprime la fonctionnalite). On le verifie sur un
        `window` qui est un vrai EventTarget : un dispatch = une navigation, et
        la query du hash courant est preservee (`?filter=hd` : rafraichir une
        bibliotheque filtree ne doit pas perdre le filtre)."""
        res = run_module_test(
            KEYBOARD_JS,
            stubs=r"""
globalThis.__navs = [];
const navigateTo = (h) => { globalThis.__navs.push(h); };
const showModal = () => {};
const toggleSidebar = () => {};
const isRightPanelExpanded = () => false;
const setRightPanelExpanded = () => {};
const _win = new EventTarget();
_win.location = { hash: "#/bibliotheque?filter=hd" };
globalThis.window = _win;
globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  querySelector: () => null, getElementById: () => null,
  activeElement: { tagName: "BODY" },
};
""",
            extra="",
            driver=r"""
M.initKeyboard();
globalThis.window.dispatchEvent(new CustomEvent("cinesort:refresh"));
__emit({ navs: globalThis.__navs });
""",
        )
        self.assertEqual(
            res["navs"],
            ["/bibliotheque?filter=hd"],
            f"un dispatch de cinesort:refresh = exactement une remontee de la route courante : {res['navs']!r}",
        )

    def test_cinesort_undo_a_toujours_son_auditeur(self):
        """N01 : le consommateur du refresh des badges reste en place — ce sont
        les EMETTEURS qui manquaient (cf UndoEventEmittedTests)."""
        res = self._run(
            r"""
__emit({ types: Object.keys(globalThis.__winListeners) });
"""
        )
        self.assertIn("cinesort:undo", res["types"])

    def test_nonreg_syntaxe(self):
        node_check(self, APP_JS)


# ============================================================================ N13
# components/modal.js — DOM minimal : on n'analyse pas de HTML, on observe
# l'ORDRE des operations (l'overlay est-il encore monte pendant onConfirm ?).

_MODAL_STUBS = r"""
globalThis.__body = [];

function _mkEl(tag) {
  const el = {
    tagName: tag,
    id: "",
    className: "",
    innerHTML: "",
    textContent: "",
    disabled: false,
    isConnected: false,
    dataset: {},
    _byrole: {},
    _listeners: {},
    setAttribute() {}, removeAttribute() {}, getAttribute: () => null,
    focus() {},
    addEventListener(t, f) { (this._listeners[t] = this._listeners[t] || []).push(f); },
    removeEventListener() {},
    querySelector(sel) {
      if (!this._byrole[sel]) this._byrole[sel] = _mkEl("stub:" + sel);
      return this._byrole[sel];
    },
    remove() {
      this.isConnected = false;
      const i = globalThis.__body.indexOf(this);
      if (i >= 0) globalThis.__body.splice(i, 1);
    },
    click() { for (const f of (this._listeners.click || [])) f({ target: this }); },
  };
  return el;
}

globalThis.document = {
  createElement: (t) => _mkEl(t),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {}, removeEventListener() {},
  activeElement: null,
  body: { appendChild(el) { el.isConnected = true; globalThis.__body.push(el); } },
};
globalThis.window = { addEventListener() {}, removeEventListener() {} };
const escapeHtml = (s) => String(s == null ? "" : s);
const t = (k) => k;
"""

_MODAL_EXTRA = r"""
export const __h = {
  overlay: () => globalThis.__body[globalThis.__body.length - 1] || null,
  bodyCount: () => globalThis.__body.length,
};
"""


class DangerModalCloseOrderTests(unittest.TestCase):
    """N13 : la modale danger restait affichee pendant toute la duree de
    l'action confirmee, masquant la progression qu'elle venait de lancer."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(MODAL_JS, stubs=_MODAL_STUBS, extra=_MODAL_EXTRA, driver=driver)

    def test_close_before_confirm_demonte_loverlay_avant_laction(self):
        """ROUGE avant fix : l'overlay restait monte pendant tout l'apply."""
        res = self._run(
            r"""
let pendantAction = null;
let resolveAction;
const attente = new Promise((r) => { resolveAction = r; });
M.dangerConfirmModal({
  title: "T",
  closeBeforeConfirm: true,
  onConfirm: async () => { pendantAction = M.__h.bodyCount(); await attente; },
});
const avant = M.__h.bodyCount();
const overlay = M.__h.overlay();
const btn = overlay.querySelector("[data-danger-confirm]");
const p = btn._listeners.click[0]({});
await globalThis.__sleep(10);
const pendant = pendantAction;
resolveAction();
await p;
__emit({ avant, pendant, apres: M.__h.bodyCount() });
"""
        )
        self.assertEqual(res["avant"], 1, "la modale doit bien s'afficher au depart")
        self.assertEqual(res["pendant"], 0, "l'overlay doit etre demonte AVANT que l'action ne demarre")
        self.assertEqual(res["apres"], 0)

    def test_defaut_inchange_loverlay_reste_pendant_laction(self):
        """Non-regression des ~20 autres sites d'appel : sans l'option, la
        semantique historique (fermeture dans le finally) est preservee — elle
        protege d'un double-clic sur le declencheur sous-jacent."""
        res = self._run(
            r"""
let pendantAction = null;
let resolveAction;
const attente = new Promise((r) => { resolveAction = r; });
M.dangerConfirmModal({
  title: "T",
  onConfirm: async () => { pendantAction = M.__h.bodyCount(); await attente; },
});
const overlay = M.__h.overlay();
const p = overlay.querySelector("[data-danger-confirm]")._listeners.click[0]({});
await globalThis.__sleep(10);
const pendant = pendantAction;
resolveAction();
await p;
__emit({ pendant, apres: M.__h.bodyCount() });
"""
        )
        self.assertEqual(res["pendant"], 1, "sans l'option, l'overlay reste monte pendant l'action")
        self.assertEqual(res["apres"], 0, "et se ferme apres")

    def test_close_before_confirm_nappelle_pas_oncancel(self):
        """Piege : close() declenche onCancel si `_confirmed` n'est pas pose.
        Fermer AVANT l'action ne doit pas faire croire a une annulation."""
        res = self._run(
            r"""
let cancels = 0;
M.dangerConfirmModal({
  title: "T",
  closeBeforeConfirm: true,
  onCancel: () => { cancels += 1; },
  onConfirm: async () => {},
});
const overlay = M.__h.overlay();
await overlay.querySelector("[data-danger-confirm]")._listeners.click[0]({});
__emit({ cancels });
"""
        )
        self.assertEqual(res["cancels"], 0)

    def test_nonreg_oncancel_toujours_appele_sur_annulation(self):
        res = self._run(
            r"""
let cancels = 0;
M.dangerConfirmModal({ title: "T", closeBeforeConfirm: true, onCancel: () => { cancels += 1; }, onConfirm: () => {} });
const overlay = M.__h.overlay();
overlay.querySelector("[data-danger-cancel]")._listeners.click[0]({});
__emit({ cancels, apres: M.__h.bodyCount() });
"""
        )
        self.assertEqual(res["cancels"], 1)
        self.assertEqual(res["apres"], 0)

    def test_nonreg_syntaxe(self):
        node_check(self, MODAL_JS)


# ================================================================ N07/N13/N35/N01
# views/traitement.js

_TRAITEMENT_STUBS = r"""
globalThis.__applyCalls = [];
globalThis.__toasts = [];
globalThis.__dangerOpts = [];
globalThis.__dispatched = [];
globalThis.__applyResult = { ok: true, result: { errors: 0, error_messages: [], renames: 3, moves: 1 } };
globalThis.__applyDelayMs = 0;
globalThis.__undoDelayMs = 0;

// Le stub honore `AbortSignal` EXACTEMENT comme le vrai `core/api.js`
// (`_mkAbortError` + `_perCallerView`, api.js:137-171) : signal deja abort ->
// rejet immediat ; sinon course entre la reponse et l'evenement 'abort'.
// Point capital : la requete est DEJA PARTIE cote backend quand l'abort
// survient (__applyCalls est incremente AVANT la course) — c'est tout le sujet
// du finding : le backend continue de deplacer les fichiers.
const _mkAbortError = () => { const e = new Error("Aborted"); e.name = "AbortError"; return e; };
const _perCallerView = (promise, signal) => {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(_mkAbortError());
  return new Promise((resolve, reject) => {
    let done = false;
    const onAbort = () => { if (done) return; done = true; reject(_mkAbortError()); };
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(
      (v) => { if (done) return; done = true; resolve(v); },
      (e) => { if (done) return; done = true; reject(e); },
    );
  });
};
const _delayed = (ms, value) => (async () => {
  if (ms) await new Promise((r) => setTimeout(r, ms));
  return value();
})();

const apiPost = async (endpoint, body, opts) => {
  const signal = opts && opts.signal;
  if (endpoint === "run/apply") {
    globalThis.__applyCalls.push(JSON.parse(JSON.stringify(body || {})));
    return _perCallerView(
      _delayed(globalThis.__applyDelayMs, () => {
        // Panne reseau reelle : fetch() rejette un TypeError, PAS un AbortError.
        if (globalThis.__forceApplyThrow) throw new TypeError("Failed to fetch");
        return { status: 200, data: globalThis.__applyResult };
      }),
      signal,
    );
  }
  if (endpoint === "run/undo_last_apply") {
    globalThis.__undoCalls = (globalThis.__undoCalls || 0) + 1;
    return _perCallerView(
      _delayed(globalThis.__undoDelayMs, () => ({ status: 200, data: globalThis.__undoResult || { ok: true } })),
      signal,
    );
  }
  if (endpoint === "run/build_apply_preview") {
    return { status: 200, data: { ok: true, films: [], totals: { renames: 12, moves: 3, quarantined: 0 } } };
  }
  return { status: 200, data: { ok: true } };
};
const fetchConfidenceThresholds = async () => ({});
const getConfidenceThresholdsSync = () => ({ CONF_HIGH: 85, CONF_MED: 60 });
const escapeHtml = (s) => String(s == null ? "" : s);
const navigateTo = () => {};
const dangerConfirmModal = (o) => { globalThis.__dangerOpts.push(o); };
const showModal = () => {};
const closeModal = () => {};
const showToast = (o) => { globalThis.__toasts.push(o); };
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

globalThis.window = {
  addEventListener() {}, removeEventListener() {},
  dispatchEvent(ev) { globalThis.__dispatched.push(ev.type); return true; },
  location: { hash: "" }, setTimeout, clearTimeout,
};
globalThis.CustomEvent = class { constructor(t) { this.type = t; } };
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

_TRAITEMENT_EXTRA = r"""
export const __h = {
  seed: (rows, opts) => {
    _runInfo = { runId: "run-1" };
    _validationPlan = { rows };
    _initDecisionsState();
    _applyOptions.dry_run = false;
    _applyStatus = null;
    _applyPreview = (opts && opts.totals) ? { totals: opts.totals } : null;
  },
  applyNow: _handleApplyNow,
  dangerOpts: () => globalThis.__dangerOpts,
  runConfirm: async () => {
    const o = globalThis.__dangerOpts[globalThis.__dangerOpts.length - 1];
    return await o.onConfirm();
  },
  undoExecute: () => { _runInfo = { runId: "run-1", pendingUndo: { reversibleCount: 3, batchId: "b1" } }; _onUndoExecute(); },
  applyStatus: () => _applyStatus,
  setDryRun: (v) => { _applyOptions.dry_run = Boolean(v); },
  setQuarantine: (v) => { _applyOptions.quarantine = Boolean(v); },
  // `initTraitement()` (traitement.js:2960) arme l'AbortController de la vue ;
  // `unmountTraitement()` l'abort. On reproduit le montage sans DOM.
  arm: () => { _abortController = new AbortController(); },
  // Registre des operations disque annoncables : sert au test d'INVARIANT.
  diskOpKeys: () => _APPLY_DISK_OPS.map((o) => o.key),
};
"""

# `_startPolling()` (appele par le VRAI `_handleApplyNow`) pose un setInterval :
# sans sortie explicite le process node reste vivant et le harnais expire a 60 s.
# On sort donc apres l'emission (stdout est synchrone sur les pipes Windows).
_EXIT = "\nprocess.exit(0);\n"

_ROWS = r"""
const rows = [];
for (let i = 0; i < 250; i++) rows.push({ row_id: "r" + i, proposed_year: 2000, decision: "OK" });
"""


class ApplyModalCountTests(unittest.TestCase):
    """N07 : la modale d'apply comptait des FILMS en disant « fichiers »."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(TRAITEMENT_JS, stubs=_TRAITEMENT_STUBS, extra=_TRAITEMENT_EXTRA, driver=driver + _EXIT)

    def test_la_modale_annonce_les_operations_reelles_pas_les_films(self):
        """ROUGE avant fix : « 250 fichiers renommes/deplaces » alors que le
        plan backend ne prevoit que 12 renommages et 3 deplacements."""
        res = self._run(
            _ROWS
            + r"""
M.__h.seed(rows, { totals: { renames: 12, moves: 3, quarantined: 0 } });
await M.__h.applyNow();
const items = M.__h.dangerOpts()[0].items;
__emit({ items });
"""
        )
        ligne = res["items"][0]
        self.assertIn("12", ligne, f"le nombre reel de renommages doit apparaitre : {ligne}")
        self.assertIn("3", ligne, f"le nombre reel de deplacements doit apparaitre : {ligne}")
        self.assertNotIn("250", ligne, f"le nombre de films approuves n'est pas un compte d'operations : {ligne}")
        self.assertNotIn("fichiers renommés", ligne, "apply ne renomme jamais le fichier video, seulement le dossier")

    def test_sans_plan_backend_la_modale_parle_de_films_pas_de_fichiers(self):
        """Repli honnete : tant que build_apply_preview n'a pas repondu, on
        annonce des FILMS APPROUVES en le disant, pas des fichiers."""
        res = self._run(
            _ROWS
            + r"""
M.__h.seed(rows, null);
await M.__h.applyNow();
__emit({ items: M.__h.dangerOpts()[0].items });
"""
        )
        ligne = res["items"][0]
        self.assertIn("250", ligne)
        self.assertIn("film", ligne.lower())
        self.assertNotIn("fichiers renommés", ligne)

    def test_quarantine_active_la_modale_annonce_le_nombre_de_films_deplaces(self):
        """Relecture adversaire de la PR #873, point 2 — la modale SOUS-annoncait.

        `build_apply_preview` force `quarantine_unapproved=False`
        (apply_support.py:3133) : ses `totals` ne portent JAMAIS de mise en
        quarantaine. L'apply reel envoie `_applyOptions.quarantine` et
        `apply_core.py:2009` deplace CHAQUE film non approuve vers `_review/`
        (increment de `res.quarantined`, jamais de `renames`/`moves`).
        Bibliotheque deja rangee + quarantaine + 50 refuses : la modale
        annoncait « 0 renommage · 0 deplacement » pour 50 dossiers deplaces.
        """
        res = self._run(
            r"""
const rows = [];
for (let i = 0; i < 250; i++) rows.push({ row_id: "r" + i, proposed_year: 2000, decision: i < 50 ? "REJECT" : "OK" });
M.__h.seed(rows, { totals: { renames: 0, moves: 0, quarantined: 0 } });
M.__h.setQuarantine(true);
await M.__h.applyNow();
const sansPlan = [];
M.__h.seed(rows, null);             // build_apply_preview pas encore repondu
M.__h.setQuarantine(true);
await M.__h.applyNow();
__emit({ items: M.__h.dangerOpts()[0].items, itemsSansPlan: M.__h.dangerOpts()[1].items });
"""
        )
        # 1. La ligne d'operations elle-meme doit porter le compte.
        self.assertIn(
            "50",
            res["items"][0],
            f"les 50 mises en quarantaine doivent etre annoncees dans la ligne d'operations : {res['items'][0]}",
        )
        # 2. L'item « Quarantaine » doit dire COMBIEN et OU, pas juste « activee ».
        quarantaine = [i for i in res["items"] if i.startswith("Quarantaine")]
        self.assertEqual(len(quarantaine), 1)
        self.assertIn("50", quarantaine[0], f"item quarantaine muet sur le nombre : {quarantaine[0]}")
        self.assertIn("_review", quarantaine[0], f"item quarantaine muet sur la destination : {quarantaine[0]}")
        # 3. Meme sans plan backend, la quarantaine est connue COTE CLIENT : le
        #    repli ne doit pas la perdre.
        self.assertIn(
            "50",
            res["itemsSansPlan"][0],
            f"repli sans plan : la quarantaine reste annoncable cote client : {res['itemsSansPlan'][0]}",
        )

    def test_invariant_aucune_operation_disque_prevue_ne_manque_a_la_modale(self):
        """INVARIANT — le test qui empeche le trou de se recreer.

        Trois verrous, tous observes en RUNTIME sur la vraie source :

        1. STRUCTUREL : toute cle du payload `run/apply` reellement poste est
           classee, soit comme n'entrainant aucune operation disque, soit comme
           liee a une operation que la modale doit annoncer. Ajouter demain un
           `delete_leftovers: true` au payload rend ce test ROUGE tant que
           l'operation n'a pas ete cablee dans la modale.
        2. REGISTRE : chaque operation ainsi declaree existe dans le registre
           `_APPLY_DISK_OPS` de traitement.js (source unique de la modale).
        3. RENDU : chaque entree du registre apparait effectivement dans le
           texte de la modale, avec son compte.
        """
        res = self._run(
            r"""
const rows = [];
for (let i = 0; i < 250; i++) rows.push({ row_id: "r" + i, proposed_year: 2000, decision: i < 50 ? "REJECT" : "OK" });
M.__h.seed(rows, { totals: { renames: 7, moves: 4, quarantined: 0 } });
M.__h.setQuarantine(true);
await M.__h.applyNow();
const items = M.__h.dangerOpts()[0].items;
await M.__h.runConfirm();           // pour observer le VRAI payload run/apply
__emit({ items, payload: globalThis.__applyCalls[0], keys: M.__h.diskOpKeys() });
"""
        )
        # 1. STRUCTUREL — toute cle du payload doit etre classee.
        sans_operation = {"run_id", "dry_run", "apply_atomic"}
        avec_operation = {"decisions": ("renames", "moves"), "quarantine_unapproved": ("quarantined",)}
        payload_keys = set(res["payload"].keys())
        self.assertEqual(
            payload_keys,
            sans_operation | set(avec_operation),
            "une cle du payload run/apply n'est pas classee : soit elle ne declenche aucune "
            "operation disque (ajouter a `sans_operation`), soit la modale doit l'annoncer",
        )
        # 2. REGISTRE — chaque operation declaree est connue du registre front.
        registre = set(res["keys"])
        attendues = {op for ops in avec_operation.values() for op in ops}
        self.assertTrue(
            attendues <= registre,
            f"operations non annoncables par la modale : {sorted(attendues - registre)}",
        )
        # 3. RENDU — chaque entree du registre apparait dans la LIGNE
        #    d'operations de la modale (items[0]), pas seulement quelque part
        #    dans la modale : c'est cette ligne qui recapitule ce qui va bouger.
        ligne_ops = res["items"][0]
        for compte in ("7", "4", "50"):
            self.assertIn(compte, ligne_ops, f"compte {compte} absent de la ligne d'operations : {ligne_ops}")

    def test_invariant_activer_la_quarantaine_change_ce_qui_est_annonce(self):
        """Verrou differentiel : une option du payload qui fait bouger N dossiers
        de plus DOIT changer ce que la modale annonce. Sans ca, les deux rendus
        seraient identiques — exactement le defaut mesure par le relecteur."""
        res = self._run(
            r"""
const rows = [];
for (let i = 0; i < 250; i++) rows.push({ row_id: "r" + i, proposed_year: 2000, decision: i < 50 ? "REJECT" : "OK" });
M.__h.seed(rows, { totals: { renames: 0, moves: 0, quarantined: 0 } });
M.__h.setQuarantine(false);
await M.__h.applyNow();
const sans = M.__h.dangerOpts()[0].items.join(" | ");
M.__h.seed(rows, { totals: { renames: 0, moves: 0, quarantined: 0 } });
M.__h.setQuarantine(true);
await M.__h.applyNow();
const avec = M.__h.dangerOpts()[1].items.join(" | ");
__emit({ sans, avec });
"""
        )
        self.assertNotEqual(
            res["sans"],
            res["avec"],
            "quarantaine ON deplace 50 dossiers de plus : la modale doit le dire",
        )
        self.assertIn("50", res["avec"])
        self.assertNotIn("50", res["sans"], "sans quarantaine, aucun des 50 refuses ne bouge")

    def test_la_modale_dapply_se_ferme_avant_de_lancer_lapply(self):
        """N13 : contrat passe a dangerConfirmModal par CE site d'appel."""
        res = self._run(
            _ROWS
            + r"""
M.__h.seed(rows, { totals: { renames: 12, moves: 3 } });
await M.__h.applyNow();
__emit({ close: Boolean(M.__h.dangerOpts()[0].closeBeforeConfirm) });
"""
        )
        self.assertTrue(res["close"])

    def test_un_second_clic_pendant_lapply_est_ignore(self):
        """N13 (effet de bord) : fermer la modale avant l'action re-expose le
        bouton « Appliquer maintenant ». Sans garde, un 2e apply partait."""
        res = self._run(
            _ROWS
            + r"""
M.__h.seed(rows, { totals: { renames: 12, moves: 3 } });
globalThis.__applyDelayMs = 200;
await M.__h.applyNow();
const p = M.__h.runConfirm();      // apply en vol
await globalThis.__sleep(20);
await M.__h.applyNow();            // 2e clic sur le bouton re-expose
const modales = M.__h.dangerOpts().length;
await p;
__emit({ modales, applyCalls: globalThis.__applyCalls.length });
"""
        )
        self.assertEqual(res["applyCalls"], 1, "un seul POST run/apply")
        self.assertEqual(res["modales"], 1, "le 2e clic ne doit pas rouvrir la modale")


class ApplyAbortPendantLeVolTests(unittest.TestCase):
    """Relecture adversaire de la PR #873, point 1 — REGRESSION creee par le lot.

    L'auditeur de `cinesort:refresh` (`_refreshCurrentView`, core/keyboard.js
    apres la fusion de main) re-monte la route courante :
    `navigateTo(<hash courant>)` -> `hashchange` -> cleanup de la vue ->
    `unmountTraitement()` -> `_abortController.abort()` (traitement.js:3106).
    Le POST `run/apply` etant emis AVEC `_signal()`, il est annule cote CLIENT
    alors que le backend, lui, CONTINUE de deplacer les fichiers. Le `catch`
    affichait alors « Erreur lors de l'apply. » en rouge — le pire message
    possible sur un chemin destructif, l'utilisateur relance.

    Ce que ces tests verrouillent : un abort en vol ne doit produire AUCUN toast
    d'erreur, sur les trois chemins qui postent avec `_signal()` (apply reel,
    dry-run, undo). Le POST doit avoir ete emis (le backend travaille), et
    l'ordre des evenements doit rester : requete partie PUIS abort.
    """

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(TRAITEMENT_JS, stubs=_TRAITEMENT_STUBS, extra=_TRAITEMENT_EXTRA, driver=driver + _EXIT)

    def test_f5_pendant_un_apply_reel_naffiche_aucune_erreur(self):
        """ROUGE avant fix : toast {type: error, text: "Erreur lors de l'apply."}
        alors que le backend deplace les fichiers."""
        res = self._run(
            _ROWS
            + r"""
M.__h.seed(rows, { totals: { renames: 12, moves: 3 } });
M.__h.arm();                        // la vue est montee : AbortController arme
globalThis.__applyDelayMs = 400;
await M.__h.applyNow();
const p = M.__h.runConfirm();       // POST run/apply en vol, avec _signal()
await globalThis.__sleep(30);
M.unmountTraitement();              // F5 -> navigateTo -> cleanup de la vue
await p;
__emit({ toasts: globalThis.__toasts, applyCalls: globalThis.__applyCalls.length });
"""
        )
        self.assertEqual(res["applyCalls"], 1, "le POST est bien parti : le backend deplace les fichiers")
        erreurs = [t for t in res["toasts"] if t.get("type") == "error"]
        self.assertEqual(
            erreurs,
            [],
            f"un apply annule cote CLIENT ne doit PAS etre annonce comme un echec : {res['toasts']}",
        )

    def test_f5_pendant_un_dry_run_naffiche_aucune_erreur(self):
        """Meme chemin, branche dry-run (traitement.js:2342)."""
        res = self._run(
            _ROWS
            + r"""
M.__h.seed(rows, null);
M.__h.arm();
M.__h.setDryRun(true);
globalThis.__applyDelayMs = 400;
const p = M.__h.applyNow();         // le dry-run poste sans passer par la modale
await globalThis.__sleep(30);
M.unmountTraitement();
await p;
__emit({ toasts: globalThis.__toasts, applyCalls: globalThis.__applyCalls.length });
"""
        )
        self.assertEqual(res["applyCalls"], 1)
        erreurs = [t for t in res["toasts"] if t.get("type") == "error"]
        self.assertEqual(erreurs, [], f"dry-run annule cote client : aucun toast d'erreur : {res['toasts']}")

    def test_f5_pendant_un_undo_naffiche_aucune_erreur(self):
        """Meme cause, meme gravite : `_onUndoExecute` poste `run/undo_last_apply`
        avec `_signal()` (traitement.js:1387) et son catch affichait « Erreur lors
        de l'annulation. » pendant que le backend RESTAURE les fichiers."""
        res = self._run(
            r"""
M.__h.seed([{ row_id: "r1", decision: "OK" }], null);
M.__h.arm();
globalThis.__undoDelayMs = 400;
M.__h.undoExecute();
const p = M.__h.runConfirm();
await globalThis.__sleep(30);
M.unmountTraitement();
await p;
__emit({ toasts: globalThis.__toasts, undoCalls: globalThis.__undoCalls || 0 });
"""
        )
        self.assertEqual(res["undoCalls"], 1, "le POST undo est parti : le backend restaure")
        erreurs = [t for t in res["toasts"] if t.get("type") == "error"]
        self.assertEqual(erreurs, [], f"undo annule cote client : aucun toast d'erreur : {res['toasts']}")

    def test_nonreg_une_vraie_panne_reseau_reste_signalee(self):
        """Le filtre ne doit avaler QUE `AbortError` : une exception reseau
        (TypeError « Failed to fetch ») reste un toast rouge."""
        res = self._run(
            _ROWS
            + r"""
M.__h.seed(rows, { totals: { renames: 12, moves: 3 } });
M.__h.arm();
globalThis.__applyResult = null;
globalThis.__forceApplyThrow = true;
await M.__h.applyNow();
await M.__h.runConfirm();
__emit({ toasts: globalThis.__toasts });
"""
        )
        self.assertEqual(len(res["toasts"]), 1)
        self.assertEqual(res["toasts"][0]["type"], "error", "une vraie panne doit rester visible")


class ApplyErrorsToastTests(unittest.TestCase):
    """N35 : un apply avec `errors > 0` affichait un toast VERT."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(TRAITEMENT_JS, stubs=_TRAITEMENT_STUBS, extra=_TRAITEMENT_EXTRA, driver=driver + _EXIT)

    def test_un_fichier_verrouille_ne_donne_plus_un_toast_vert(self):
        """ROUGE avant fix : `{ok: true, result: {errors: 1}}` -> toast
        `success` « Apply termine · Undo possible 24h », le film verrouille
        n'ayant pas bouge. Cas reel : .mkv en seeding / ouvert dans VLC."""
        res = self._run(
            _ROWS
            + r"""
M.__h.seed(rows, { totals: { renames: 12, moves: 3 } });
globalThis.__applyResult = {
  ok: true,
  result: { errors: 1, renames: 1, moves: 0,
            error_messages: ["FICHIER VERROUILLE : Locked.Movie.2020"] },
};
await M.__h.applyNow();
await M.__h.runConfirm();
__emit({ toasts: globalThis.__toasts });
"""
        )
        toasts = res["toasts"]
        self.assertEqual(len(toasts), 1)
        self.assertEqual(toasts[0]["type"], "warning", "un apply avec echecs n'est pas un succes")
        self.assertIn("1", toasts[0]["text"])
        self.assertIn("FICHIER VERROUILLE", toasts[0]["text"], "le message backend doit remonter")

    def test_apply_sans_echec_reste_un_succes(self):
        res = self._run(
            _ROWS
            + r"""
M.__h.seed(rows, { totals: { renames: 12, moves: 3 } });
globalThis.__applyResult = { ok: true, result: { errors: 0, error_messages: [], renames: 12 } };
await M.__h.applyNow();
await M.__h.runConfirm();
__emit({ toasts: globalThis.__toasts });
"""
        )
        self.assertEqual(res["toasts"][0]["type"], "success")
        self.assertIn("Undo", res["toasts"][0]["text"])

    def test_dry_run_avec_echecs_est_aussi_signale(self):
        res = self._run(
            _ROWS
            + r"""
M.__h.seed(rows, { totals: { renames: 12, moves: 3 } });
M.__h.setDryRun(true);
globalThis.__applyResult = { ok: true, result: { errors: 2, error_messages: ["boom"] } };
await M.__h.applyNow();
__emit({ toasts: globalThis.__toasts, dangers: M.__h.dangerOpts().length });
"""
        )
        self.assertEqual(res["dangers"], 0, "le dry-run ne passe pas par la modale danger")
        self.assertEqual(res["toasts"][0]["type"], "warning")

    def test_nonreg_syntaxe(self):
        node_check(self, TRAITEMENT_JS)


class UndoEventEmittedTests(unittest.TestCase):
    """N01 : app.js ecoute `cinesort:undo` mais personne ne l'emettait plus."""

    def setUp(self) -> None:
        require_node(self)

    def test_traitement_emet_cinesort_undo_apres_un_undo_reussi(self):
        res = run_module_test(
            TRAITEMENT_JS,
            stubs=_TRAITEMENT_STUBS,
            extra=_TRAITEMENT_EXTRA,
            driver=r"""
M.__h.seed([{ row_id: "r1", decision: "OK" }], null);
M.__h.undoExecute();
await M.__h.runConfirm();
__emit({ dispatched: globalThis.__dispatched, toasts: globalThis.__toasts });
""",
        )
        self.assertIn("cinesort:undo", res["dispatched"])
        self.assertEqual(res["toasts"][0]["type"], "success")

    def test_traitement_nemet_rien_si_lundo_echoue(self):
        res = run_module_test(
            TRAITEMENT_JS,
            stubs=_TRAITEMENT_STUBS,
            extra=_TRAITEMENT_EXTRA,
            driver=r"""
globalThis.__undoResult = { ok: false, message: "delai 24h depasse" };
M.__h.seed([{ row_id: "r1", decision: "OK" }], null);
M.__h.undoExecute();
await M.__h.runConfirm();
__emit({ dispatched: globalThis.__dispatched, toasts: globalThis.__toasts });
""",
        )
        self.assertNotIn("cinesort:undo", res["dispatched"])
        self.assertEqual(res["toasts"][0]["type"], "error")


# ============================================================================ N14
_BIBLIO_STUBS = r"""
globalThis.__emptyStates = [];
const buildEmptyState = (o) => { globalThis.__emptyStates.push(o); return "<div class='es'></div>"; };
const apiPost = async () => ({ status: 200, data: { ok: true } });
const apiGet = async () => ({ status: 200, data: { ok: true } });
const escapeHtml = (s) => String(s == null ? "" : s);
const navigateTo = () => {};
const dangerConfirmModal = () => {};
const showModal = () => {};
const closeModal = () => {};
const showToast = () => {};
const formatRelative = () => "";
const formatDuration = () => "";
const formatBytes = (n) => String(n);
const renderFilmDetail = async () => {};
const openPerceptualModal = () => {};
const openDuplicateComparatorModal = () => {};
const posterProxyUrl = (u) => u;
const trapFocus = () => () => {};
const getNavSignal = () => undefined;
const labelsForFlags = () => [];
const countBySeverity = () => ({});
const setSections = () => {};
const initDoublons = async () => {};
const unmountDoublons = () => {};
const t = (k) => k;
const fetchConfidenceThresholds = async () => ({});
const getConfidenceThresholdsSync = () => ({ CONF_HIGH: 85, CONF_MED: 60 });
const cachedGetSettings = async () => ({ status: 200, data: { ok: true } });
const invalidateSettingsCache = () => {};
const buildSkeleton = () => "";
const buildErrorState = () => "";
const ADVANCED_DRAWER_DEFAULTS = {};
globalThis.window = { addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, location: { hash: "" }, setTimeout, clearTimeout };
globalThis.document = {
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  createElement: () => ({ innerHTML: "", appendChild() {}, setAttribute() {}, addEventListener() {}, classList: { add() {}, remove() {} } }),
  addEventListener() {}, removeEventListener() {},
  body: { classList: { add() {}, remove() {} }, appendChild() {} },
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.CustomEvent = class { constructor(t) { this.type = t; } };
"""


class BibliothequeEmptyCtaTests(unittest.TestCase):
    """N14 : le CTA de la bibliotheque vide envoyait sur une vue interne."""

    def setUp(self) -> None:
        require_node(self)

    def test_le_cta_lancer_un_scan_pointe_sur_la_vue_du_menu(self):
        """ROUGE avant fix : '/processing?step=scan' — un stepper 3 etapes,
        different de l'ecran qu'ouvre l'item de sidebar « Traitement »
        (/traitement, workflow 5 etapes), lequel restait surligne."""
        res = run_module_test(
            BIBLIOTHEQUE_JS,
            stubs=_BIBLIO_STUBS,
            extra=r"""
export const __h = {
  emptyHtml: () => {
    // Bibliotheque VIDE (0 film en base) et AUCUN filtre actif : c'est la
    // seule branche de _renderGrid qui rend le CTA « Lancer un scan ».
    _state = _initState();
    _state.rows = [];
    _state.loading = false;
    _state.total = 0;
    _state.tierFilter = "all";
    _state.activeChips = new Set();
    _state.search = "";
    _state.advancedActive = false;
    return _renderGrid();
  },
  states: () => globalThis.__emptyStates,
};
""",
            driver=r"""
const html = M.__h.emptyHtml();
const first = M.__h.states()[0] || null;
__emit({ html: String(html), cta: first && first.ctaRoute, label: first && first.ctaLabel, testId: first && first.testId });
""",
        )
        self.assertEqual(res["testId"], "bibliotheque-empty-cta")
        self.assertEqual(res["cta"], "/traitement")
        self.assertEqual(res["label"], "Lancer un scan")

    def test_nonreg_syntaxe(self):
        node_check(self, BIBLIOTHEQUE_JS)


# ============================================================================ N15
_ACCUEIL_ELEMENT = r"""
globalThis.__el = null;
function _mkSidebarItem(title) {
  return {
    _attrs: { title },
    dataset: {},
    classList: { _c: new Set(), toggle(c, on) { if (on) this._c.add(c); else this._c.delete(c); },
                 add(c) { this._c.add(c); }, remove(c) { this._c.delete(c); },
                 contains(c) { return this._c.has(c); } },
    setAttribute(k, v) { this._attrs[k] = v; },
    removeAttribute(k) { delete this._attrs[k]; },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; },
  };
}
globalThis.__mkSidebarItem = _mkSidebarItem;
"""


class AccueilSidebarTooltipTests(unittest.TestCase):
    """N15 : libelle mensonger + titre d'origine detruit."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        stubs = (
            _ACCUEIL_ELEMENT
            + r"""
const apiPost = async () => ({ status: 200, data: { ok: true } });
const apiGet = async () => ({ status: 200, data: { ok: true } });
const cachedGetSettings = async () => ({ status: 200, data: { ok: true } });
const escapeHtml = (s) => String(s == null ? "" : s);
const navigateTo = () => {};
const showToast = () => {};
const showModal = () => {};
const closeModal = () => {};
const dangerConfirmModal = () => {};
const formatRelative = () => "";
const formatDuration = () => "";
const formatBytes = (n) => String(n);
const posterProxyUrl = (u) => u;
const trapFocus = () => () => {};
const getNavSignal = () => undefined;
const labelsForFlags = () => [];
const countBySeverity = () => ({});
const setSections = () => {};
const renderFilmDetail = async () => {};
const openPerceptualModal = () => {};
const buildEmptyState = () => "";
const buildSkeleton = () => "";
const buildErrorState = () => "";
const t = (k) => k;
const fetchConfidenceThresholds = async () => ({});
const getConfidenceThresholdsSync = () => ({});
const invalidateSettingsCache = () => {};
globalThis.window = { addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, location: { hash: "" }, setTimeout, clearTimeout, setInterval, clearInterval };
globalThis.document = {
  querySelector: (sel) => (sel.includes('data-route="processing"') ? globalThis.__el : null),
  querySelectorAll: () => [],
  getElementById: () => null,
  createElement: () => ({ innerHTML: "", appendChild() {}, setAttribute() {}, addEventListener() {}, classList: { add() {}, remove() {} } }),
  addEventListener() {}, removeEventListener() {},
  body: { classList: { add() {}, remove() {} }, appendChild() {} },
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.CustomEvent = class { constructor(t) { this.type = t; } };
"""
        )
        extra = r"""
export const __h = { update: _updateSidebarForActiveRun };
"""
        return run_module_test(ACCUEIL_JS, stubs=stubs, extra=extra, driver=driver)

    def test_le_titre_dorigine_est_restaure_quand_un_run_demarre(self):
        """ROUGE avant fix : removeAttribute('title') -> l'entree perdait son
        tooltip « Traitement (Alt+2) », seule source du raccourci en sidebar
        repliee, jusqu'au prochain re-rendu complet de la sidebar."""
        res = self._run(
            r"""
globalThis.__el = globalThis.__mkSidebarItem("Traitement (Alt+2)");
M.__h.update(false);
const sansRun = { title: globalThis.__el.getAttribute("title"), dim: globalThis.__el.classList.contains("v5-sidebar-item--dimmed") };
M.__h.update(true);
const avecRun = { title: globalThis.__el.getAttribute("title"), dim: globalThis.__el.classList.contains("v5-sidebar-item--dimmed") };
__emit({ sansRun, avecRun });
"""
        )
        self.assertTrue(res["sansRun"]["dim"], "l'entree reste grisee sans run (intention produit)")
        self.assertFalse(res["avecRun"]["dim"])
        self.assertEqual(
            res["avecRun"]["title"],
            "Traitement (Alt+2)",
            "le titre d'origine doit etre RESTAURE, pas supprime",
        )

    def test_le_tooltip_nannonce_plus_une_vue_indisponible(self):
        """L'item reste 100 % cliquable (seule l'opacite baisse) et c'est de la
        que l'utilisateur lance son premier scan : dire « disponible quand un
        scan est lance » etait faux et circulaire."""
        res = self._run(
            r"""
globalThis.__el = globalThis.__mkSidebarItem("Traitement (Alt+2)");
M.__h.update(false);
__emit({ title: globalThis.__el.getAttribute("title") });
"""
        )
        self.assertNotIn("disponible quand", res["title"])
        self.assertIn("scan", res["title"].lower())

    def test_nonreg_syntaxe(self):
        node_check(self, ACCUEIL_JS)


# ============================================================================ N33
_API_STUBS = r"""
globalThis.__toasts = [];
globalThis.__status = 503;
globalThis.__snapshot = { data: { theme: "dark", library_path: "D:/Films" }, ageSeconds: 42, stale: true };
globalThis.__fetches = 0;

const getToken = () => "tok";
const clearToken = () => {};
const awaitToken = async () => {};
const isCacheable = () => true;
const saveSnapshot = () => {};
const loadSnapshot = () => globalThis.__snapshot;
const formatStaleness = () => "il y a quelques secondes";
const showToast = (o) => { globalThis.__toasts.push(o); };

globalThis.window = { location: { origin: "http://127.0.0.1:8642", hostname: "127.0.0.1" }, addEventListener() {}, removeEventListener() {} };
globalThis.document = { getElementById: () => null, querySelector: () => null, addEventListener() {}, removeEventListener() {} };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.fetch = async () => {
  globalThis.__fetches += 1;
  return { status: globalThis.__status, json: async () => ({ ok: false }) };
};
"""


class OfflineSnapshotNoticeTests(unittest.TestCase):
    """N33 : sur 5xx, un instantane vieux de 24 h max etait servi en silence,
    avec `_offline`/`_stale_age` que personne ne lit."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(API_JS, stubs=_API_STUBS, extra="", driver=driver, timeout=90)

    def test_un_instantane_perime_est_signale_a_lutilisateur(self):
        """ROUGE avant fix : ZERO toast, ZERO banniere — l'ecran se peuplait de
        valeurs perimees et l'utilisateur croyait lire son etat courant
        (l'indicateur #dashConnStatus vise par _setConnStatus n'existe dans
        aucun HTML de l'application)."""
        res = self._run(
            r"""
const r = await M.apiPost("settings/get_settings", {});
__emit({
  status: r.status,
  offline: r.data._offline === true,
  stale: r.data._stale_age,
  theme: r.data.theme,
  toasts: globalThis.__toasts,
});
"""
        )
        self.assertEqual(res["status"], 503)
        self.assertTrue(res["offline"], "le contrat _offline reste pose pour les appelants")
        self.assertEqual(res["theme"], "dark", "le repli hors ligne continue de servir le snapshot")
        self.assertEqual(len(res["toasts"]), 1, "l'utilisateur doit etre averti")
        self.assertEqual(res["toasts"][0]["type"], "warning")
        self.assertIn("hors ligne", res["toasts"][0]["text"].lower())

    def test_un_serveur_a_terre_ne_noie_pas_lecran_de_toasts(self):
        """Throttle : au boot, plusieurs endpoints caches tombent d'affilee."""
        res = self._run(
            r"""
await M.apiPost("settings/get_settings", {});
await M.apiPost("run/get_dashboard", {});
await M.apiPost("run/get_global_stats", {});
__emit({ toasts: globalThis.__toasts.length, fetches: globalThis.__fetches });
"""
        )
        self.assertGreaterEqual(res["fetches"], 3, "les 3 appels sont bien partis")
        self.assertEqual(res["toasts"], 1, "un seul avertissement dans la fenetre de throttle")

    def test_pas_de_snapshot_pas_de_toast_hors_ligne(self):
        """Sans instantane, le message d'erreur explicite suffit deja."""
        res = self._run(
            r"""
globalThis.__snapshot = null;
const r = await M.apiPost("settings/get_settings", {});
__emit({ toasts: globalThis.__toasts.length, ok: r.data.ok, msg: r.data.message });
"""
        )
        self.assertEqual(res["toasts"], 0)
        self.assertFalse(res["ok"])
        self.assertIn("indisponible", res["msg"].lower())

    def test_nonreg_reponse_200_inchangee(self):
        res = self._run(
            r"""
globalThis.__status = 200;
globalThis.fetch = async () => ({ status: 200, json: async () => ({ ok: true, theme: "light" }) });
const r = await M.apiPost("settings/get_settings", {});
__emit({ status: r.status, theme: r.data.theme, offline: r.data._offline === true, toasts: globalThis.__toasts.length });
"""
        )
        self.assertEqual(res["status"], 200)
        self.assertEqual(res["theme"], "light")
        self.assertFalse(res["offline"])
        self.assertEqual(res["toasts"], 0)

    def test_nonreg_syntaxe(self):
        node_check(self, API_JS)


# ============================================================================ N01
class HistoriqueUndoEventTests(unittest.TestCase):
    """N01 : historique.js est le second proprietaire de l'undo."""

    def setUp(self) -> None:
        require_node(self)

    # Fusion main <- PR #873 : main a ajoute deux imports a historique.js —
    # `cachedGetSettings` (retention lue dans les reglages, plus dans le payload
    # de get_dashboard) et `deriveRunStatus` (regle de statut sortie en module
    # partage). Sans eux dans le jeu de stubs, l'appel leve un ReferenceError
    # avale par le `try/catch` de `_fetchRetentionDays` : le test resterait vert
    # sur un module amoindri. `cachedGetSettings` est un appel reseau, donc
    # stubbe ; `deriveRunStatus` est de la LOGIQUE, donc la vraie source est
    # injectee (un stub maison ferait passer la copie du testeur pour le code
    # livre).
    _STUBS = (
        inline_module("core/run-status.js")
        + r"""
globalThis.__dispatched = [];
globalThis.__toasts = [];
globalThis.__undoResult = { ok: true };
globalThis.__settings = { ok: true, history_retention_days: 90 };
const apiPost = async (endpoint) => {
  if (endpoint === "run/undo_last_apply") return { status: 200, data: globalThis.__undoResult };
  return { status: 200, data: { ok: true, runs_history: [] } };
};
const apiGet = async () => ({ status: 200, data: { ok: true } });
const cachedGetSettings = async () => ({ status: 200, data: globalThis.__settings });
const escapeHtml = (s) => String(s == null ? "" : s);
const navigateTo = () => {};
const dangerConfirmModal = () => {};
const showModal = () => {};
const closeModal = () => {};
const showToast = (o) => { globalThis.__toasts.push(o); };
const formatRelative = () => "";
const formatDuration = () => "";
const formatBytes = (n) => String(n);
const posterProxyUrl = (u) => u;
const trapFocus = () => () => {};
const getNavSignal = () => undefined;
const setSections = () => {};
const renderFilmDetail = async () => {};
// Le VRAI buildEmptyState rend `message` (escape) dans .empty-state__message :
// on le restitue pour pouvoir observer le texte que la vue lui transmet.
const buildEmptyState = (o) => `<div class="empty-state__message">${String((o && o.message) || "")}</div>`;
const buildSkeleton = () => "";
const buildErrorState = () => "";
const t = (k) => k;
const openPerceptualModal = () => {};
const labelsForFlags = () => [];
const countBySeverity = () => ({});
globalThis.window = { addEventListener() {}, removeEventListener() {},
  dispatchEvent(ev) { globalThis.__dispatched.push(ev.type); return true; },
  location: { hash: "" }, setTimeout, clearTimeout };
globalThis.CustomEvent = class { constructor(t) { this.type = t; } };
globalThis.document = {
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  createElement: () => ({ innerHTML: "", appendChild() {}, setAttribute() {}, addEventListener() {}, classList: { add() {}, remove() {} } }),
  addEventListener() {}, removeEventListener() {},
  body: { classList: { add() {}, remove() {} }, appendChild() {} },
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
"""
    )

    _EXTRA = r"""
export const __h = {
  undo: _doUndoApply,
  logTab: (run, stats) => {
    _inspectorTab = "log";
    _historyStatsCache.set(run.run_id, { ok: true, run: stats });
    return _renderInspectorTabContent(run);
  },
};
"""

    def test_undo_reussi_emet_cinesort_undo(self):
        res = run_module_test(
            HISTORIQUE_JS,
            stubs=self._STUBS,
            extra=self._EXTRA,
            driver=r"""
await M.__h.undo("run-1");
__emit({ dispatched: globalThis.__dispatched, toasts: globalThis.__toasts });
""",
        )
        self.assertIn("cinesort:undo", res["dispatched"])
        self.assertEqual(res["toasts"][0]["type"], "success")

    def test_undo_refuse_par_le_backend_nemet_rien(self):
        """Le refus 410 « delai 24h depasse » ne doit pas passer pour un undo."""
        res = run_module_test(
            HISTORIQUE_JS,
            stubs=self._STUBS,
            extra=self._EXTRA,
            driver=r"""
globalThis.__undoResult = { ok: false, message: "L'annulation n'est plus possible (delai 24h depasse)." };
await M.__h.undo("run-1");
__emit({ dispatched: globalThis.__dispatched, toasts: globalThis.__toasts });
""",
        )
        self.assertNotIn("cinesort:undo", res["dispatched"])
        self.assertEqual(res["toasts"][0]["type"], "error")
        self.assertIn("24h", res["toasts"][0]["text"])

    def test_nonreg_syntaxe(self):
        node_check(self, HISTORIQUE_JS)


# ============================================================================ N29
class HistoriqueLogTabTests(unittest.TestCase):
    """N29 : l'onglet Log d'un run d'une session anterieure est toujours vide
    (le journal live n'existe qu'en memoire du process). Le fichier existe
    pourtant sur disque : l'ecran doit le dire et donner son chemin."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(
            HISTORIQUE_JS,
            stubs=HistoriqueUndoEventTests._STUBS,
            extra=HistoriqueUndoEventTests._EXTRA,
            driver=driver,
        )

    def test_log_vide_explique_pourquoi_et_donne_le_chemin_disque(self):
        """ROUGE avant fix : « Aucun log disponible pour ce run. » — exact mais
        trompeur (le journal EXISTE, sur disque) et sans issue."""
        res = self._run(
            r"""
const html = M.__h.logTab(
  { run_id: "run-42", run_dir: "C:\\Users\\x\\AppData\\Local\\CineSort\\runs\\run-42" },
  { log_lines: [] },
);
__emit({ html: String(html) });
"""
        )
        html = res["html"]
        self.assertIn("ui_log.txt", html, "le nom du fichier de journal doit etre donne")
        self.assertIn("runs\\run-42", html, "le dossier du run doit apparaitre dans le chemin")
        self.assertIn("session", html.lower(), "la CAUSE (journal en memoire de session) doit etre dite")

    def test_sans_run_dir_le_message_reste_actionnable(self):
        res = self._run(
            r"""
const html = M.__h.logTab({ run_id: "run-42" }, { log_lines: [] });
__emit({ html: String(html) });
"""
        )
        self.assertIn("ui_log.txt", res["html"])

    def test_nonreg_un_run_avec_logs_les_affiche_toujours(self):
        res = self._run(
            r"""
const html = M.__h.logTab(
  { run_id: "run-42", run_dir: "C:\\runs\\run-42" },
  { log_lines: ["ligne A", "ligne B"] },
);
__emit({ html: String(html) });
"""
        )
        self.assertIn("ligne A", res["html"])
        self.assertIn("ligne B", res["html"])
        self.assertNotIn("ui_log.txt", res["html"], "pas de message d'absence quand le log est la")


if __name__ == "__main__":
    unittest.main()
