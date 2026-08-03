"""F04 — parametres.js : le debounce de sauvegarde etait annule (jamais envoye)
au demontage de la vue.

Bug d'origine (BACKLOG35 F04) : `unmountParametres()` faisait
`clearTimeout(_state.saveTimer)` sans flush. Le SEUL chemin d'ecriture des
reglages etant le debounce 500 ms de `_scheduleSave`, quitter /parametres moins
de 500 ms apres une frappe perdait l'edition en silence — et au retour sur la
vue `_loadSettings()` ecrasait la valeur locale par l'etat serveur.

Les tests executent la VRAIE source du module sous Node (imports stubbes, corps
des fonctions intact) : c'est la sequence reelle scheduleSave -> unmount ->
POST qui est verifiee, pas la presence d'une chaine dans le fichier.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, node_check, require_node, run_module_test

JS = ROOT / "web" / "dashboard" / "views" / "parametres.js"

STUBS = r"""
globalThis.__calls = [];
globalThis.__saveOk = true;
const apiPost = async (endpoint, body, opts) => {
  const entry = { endpoint, body: JSON.parse(JSON.stringify(body || {})), t: Date.now(), opts: !!opts };
  globalThis.__calls.push(entry);
  if (globalThis.__postDelayMs && endpoint === "settings/save_settings") {
    await new Promise((r) => setTimeout(r, globalThis.__postDelayMs));
  }
  globalThis.__calls.push({ endpoint: endpoint + ":resolved", t: Date.now() });
  if (endpoint === "settings/get_settings") {
    return { status: 200, data: { ok: true, data: globalThis.__serverSettings || {} } };
  }
  if (endpoint === "settings/save_settings" && !globalThis.__saveOk) {
    return { status: 200, data: { ok: false, message: "quota disque" } };
  }
  return { status: 200, data: { ok: true } };
};
const invalidateSettingsCache = () => { globalThis.__invalidated = (globalThis.__invalidated || 0) + 1; };
const escapeHtml = (s) => String(s == null ? "" : s);
const dangerConfirmModal = () => {};
const showModal = () => {};
const trapFocus = () => () => {};

// Element DOM minimal : `innerHTML` est un vrai accesseur, ce qui permet de
// LIRE ce que _updateSavedIndicator a reellement ecrit dans l'indicateur.
function __el(name) {
  const el = {
    _name: name, _html: "", _writes: [],
    addEventListener() {}, removeEventListener() {},
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    classList: { add() {}, remove() {}, toggle() {} },
    dataset: {}, style: { setProperty() {} },
    querySelector: () => null, querySelectorAll: () => [],
    focus() {}, select() {},
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; },
    set(v) { el._html = String(v); el._writes.push(String(v)); },
  });
  return el;
}
globalThis.__el = __el;
globalThis.__indicator = __el("indicator");
globalThis.__container = __el("container");
globalThis.__container.querySelector = (sel) => (
  String(sel).includes("saved-indicator") ? globalThis.__indicator : null
);
globalThis.window = globalThis.window || { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = globalThis.document || {
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => null,
  createElement: () => __el("created"),
  addEventListener() {},
  removeEventListener() {},
  body: Object.assign(__el("body"), { appendChild() {} }),
  documentElement: __el("html"),
};
globalThis.localStorage = globalThis.localStorage || {
  getItem: () => null, setItem() {}, removeItem() {},
};
"""

EXTRA = r"""
export const __h = {
  state: _state,
  scheduleSave: _scheduleSave,
  loadSettings: _loadSettings,
};
"""


class F04FlushPendingSaveTests(unittest.TestCase):
    """Le save en attente doit partir au demontage de la vue."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(JS, stubs=STUBS, extra=EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_unmount_flushe_le_save_en_attente(self):
        """ROUGE avant fix : aucun POST save_settings n'etait emis."""
        res = self._run(r"""
const st = M.__h.state;
st.containerRef = { querySelector: () => null };
st.settings = { omdb_api_key: "CLE-EDITEE-JUSTE-AVANT-DE-PARTIR" };
M.__h.scheduleSave();
M.unmountParametres();                 // < 500 ms apres la frappe
await globalThis.__sleep(80);
const saves = globalThis.__calls.filter((c) => c.endpoint === "settings/save_settings");
__emit({
  saveCount: saves.length,
  sentKey: saves.length ? saves[0].body.settings.omdb_api_key : null,
  savedAt: st.savedAt,
  timerAfter: st.saveTimer,
});
""")
        self.assertEqual(
            res["saveCount"],
            1,
            "unmountParametres doit envoyer le save en attente (F04) — 0 POST = edition perdue",
        )
        self.assertEqual(res["sentKey"], "CLE-EDITEE-JUSTE-AVANT-DE-PARTIR")
        self.assertIsNone(res["timerAfter"], "le timer doit etre desarme apres le flush")

    def test_pas_de_badge_sauvegarde_fantome_apres_unmount(self):
        """La reponse tardive du flush ne doit pas re-poser savedAt (badge
        '✓ Sauvegarde a HH:MM' fantome au remontage de la vue)."""
        res = self._run(r"""
const st = M.__h.state;
st.containerRef = { querySelector: () => null };
st.settings = { a: 1 };
globalThis.__postDelayMs = 40;
M.__h.scheduleSave();
M.unmountParametres();                 // met containerRef a null
await globalThis.__sleep(120);
__emit({ savedAt: st.savedAt, saveError: st.saveError, invalidated: globalThis.__invalidated || 0 });
""")
        self.assertIsNone(res["savedAt"])
        self.assertIsNone(res["saveError"])
        self.assertEqual(res["invalidated"], 1, "invalidateSettingsCache doit rester inconditionnel")

    def test_load_settings_attend_le_flush_en_vol(self):
        """Retour immediat sur la vue : le GET ne doit pas partir avant que le
        POST de flush soit resolu, sinon on relit un etat pre-save."""
        res = self._run(r"""
const st = M.__h.state;
st.containerRef = { querySelector: () => null };
st.settings = { omdb_api_key: "NEW" };
globalThis.__postDelayMs = 60;
globalThis.__serverSettings = { omdb_api_key: "OLD" };
M.__h.scheduleSave();
M.unmountParametres();
await M.__h.loadSettings();            // remontage immediat de la vue
const seq = globalThis.__calls.map((c) => c.endpoint);
__emit({ seq });
""")
        seq = res["seq"]
        self.assertIn("settings/save_settings:resolved", seq)
        self.assertIn("settings/get_settings", seq)
        self.assertLess(
            seq.index("settings/save_settings:resolved"),
            seq.index("settings/get_settings"),
            "_loadSettings doit attendre le flush en vol avant de relire le serveur",
        )

    # ------------------------------------------- ROUGE (revue adversaire R1)
    def test_echec_du_flush_est_signale_au_remontage_de_la_vue(self):
        """Revue adversaire R1 (MEDIUM) : le flush part PAR CONSTRUCTION depuis
        unmountParametres, donc sa reponse arrive quand `containerRef` est deja
        null. Gardee par `containerRef`, l'ecriture de `saveError` n'avait donc
        JAMAIS lieu : un refus backend (ok:false / 401 / 5xx apres retries)
        perdait l'edition exactement comme avant le correctif, mais desormais
        SANS aucun signal. On execute le VRAI initParametres au remontage et on
        lit l'indicateur DOM reellement ecrit."""
        res = self._run(r"""
const st = M.__h.state;
globalThis.__serverSettings = { omdb_api_key: "ANCIENNE" };
globalThis.__saveOk = false;               // le backend refuse le flush
globalThis.__postDelayMs = 40;
st.containerRef = globalThis.__container;
st.settings = { omdb_api_key: "NOUVELLE-CLE" };
M.__h.scheduleSave();
M.unmountParametres();                     // < 500 ms : c'est le flush F04
await globalThis.__sleep(150);             // la reponse arrive vue demontee
const afterFlush = { saveError: st.saveError, lastFlushError: st.lastFlushError };
globalThis.__indicator._html = "";         // on repart d'un indicateur vierge
await M.initParametres(globalThis.__container);   // remontage reel de la vue
__emit({
  afterFlush,
  indicatorHtml: globalThis.__indicator.innerHTML,
  valueAtRemount: st.settings.omdb_api_key,
  savesSent: globalThis.__calls.filter((c) => c.endpoint === "settings/save_settings").length,
});
""")
        self.assertEqual(res["savesSent"], 1, "le flush doit bien avoir ete tente")
        self.assertEqual(
            res["afterFlush"]["lastFlushError"],
            "quota disque",
            "l'echec doit etre memorise dans un champ qui SURVIT au demontage",
        )
        self.assertIn(
            "NON enregistr",
            res["indicatorHtml"],
            "au remontage, l'utilisateur doit VOIR que sa derniere modification "
            f"n'a pas ete enregistree ; indicateur = {res['indicatorHtml']!r}",
        )
        self.assertIn("quota disque", res["indicatorHtml"], "le motif backend doit etre repris")
        # Verite factuelle du scenario : la valeur serveur reprend le dessus.
        # C'est justement pourquoi l'echec DOIT etre affiche.
        self.assertEqual(res["valueAtRemount"], "ANCIENNE")

    def test_lattente_du_flush_au_montage_est_bornee(self):
        """Revue adversaire R1 (LOW) : `await _state.saveInFlight` est sur le
        chemin de MONTAGE (initParametres, bloc aria-busy) et l'apiPost du flush
        part sans timeoutMs, avec jusqu'a 3 retries + backoff. Sans borne, le
        GET get_settings n'etait meme pas emis et l'ecran restait sur son
        skeleton. Ici : POST a 3000 ms, l'attente doit rendre la main bien
        avant."""
        res = self._run(r"""
const st = M.__h.state;
st.containerRef = globalThis.__container;
st.settings = { omdb_api_key: "NEW" };
globalThis.__postDelayMs = 3000;           // backend occupe / chaine de retries
globalThis.__serverSettings = { omdb_api_key: "OLD" };
M.__h.scheduleSave();
M.unmountParametres();
const t0 = Date.now();
await M.__h.loadSettings();                // remontage immediat
const elapsed = Date.now() - t0;
__emit({ elapsed, seq: globalThis.__calls.map((c) => c.endpoint) });
""")
        self.assertIn("settings/get_settings", res["seq"], "le GET doit finir par partir")
        self.assertLess(
            res["elapsed"],
            2500,
            "le montage de la vue ne doit pas rester bloque sur un POST de flush lent "
            f"(mesure : {res['elapsed']} ms pour un POST de 3000 ms)",
        )
        self.assertGreater(
            res["elapsed"],
            300,
            "l'attente doit rester reelle (borne, pas supprimee)",
        )

    # -------------------------------------------------- NON-REGRESSION
    # (doivent rester VERTES des deux cotes de la mutation)
    def test_nonreg_debounce_normal_envoie_une_seule_fois(self):
        """Sans demontage, le debounce 500 ms fonctionne toujours et coalesce
        les frappes rapprochees en UN seul POST."""
        res = self._run(r"""
const st = M.__h.state;
st.containerRef = { querySelector: () => null };
st.settings = { naming_movie_template: "{title} ({year})" };
M.__h.scheduleSave();
await globalThis.__sleep(50);
st.settings.naming_movie_template = "{title} ({year}) FINAL";
M.__h.scheduleSave();
await globalThis.__sleep(900);
const saves = globalThis.__calls.filter((c) => c.endpoint === "settings/save_settings");
__emit({
  saveCount: saves.length,
  sentTemplate: saves.length ? saves[0].body.settings.naming_movie_template : null,
  savedAtIsSet: st.savedAt != null,
});
""")
        self.assertEqual(res["saveCount"], 1, "debounce : une seule requete pour deux frappes")
        self.assertEqual(res["sentTemplate"], "{title} ({year}) FINAL")
        self.assertTrue(res["savedAtIsSet"], "vue toujours montee -> l'indicateur doit etre pose")

    def test_nonreg_unmount_sans_edition_n_envoie_rien(self):
        """Quitter la vue sans edition en attente ne doit declencher AUCUN POST."""
        res = self._run(r"""
const st = M.__h.state;
st.containerRef = { querySelector: () => null };
M.unmountParametres();
await globalThis.__sleep(60);
__emit({ calls: globalThis.__calls.map((c) => c.endpoint) });
""")
        self.assertEqual(res["calls"], [], "aucun POST parasite au demontage sans edition")

    def test_nonreg_unmount_nettoie_toujours_letat_de_vue(self):
        res = self._run(r"""
const st = M.__h.state;
st.containerRef = { querySelector: () => null };
st.searchQuery = "omdb";
st.savedAt = new Date();
st.saveError = "boom";
M.unmountParametres();
__emit({
  containerRef: st.containerRef, searchQuery: st.searchQuery,
  savedAt: st.savedAt, saveError: st.saveError,
});
""")
        self.assertIsNone(res["containerRef"])
        self.assertEqual(res["searchQuery"], "")
        self.assertIsNone(res["savedAt"])
        self.assertIsNone(res["saveError"])

    def test_nonreg_flush_reussi_ne_laisse_aucun_bandeau_derreur(self):
        """Symetrique du test d'echec : un flush ACCEPTE ne doit laisser aucune
        trace d'erreur au remontage (sinon le bandeau devient du bruit)."""
        res = self._run(r"""
const st = M.__h.state;
globalThis.__serverSettings = { omdb_api_key: "NOUVELLE-CLE" };
globalThis.__saveOk = true;
globalThis.__postDelayMs = 40;
st.containerRef = globalThis.__container;
st.settings = { omdb_api_key: "NOUVELLE-CLE" };
M.__h.scheduleSave();
M.unmountParametres();
await globalThis.__sleep(150);
globalThis.__indicator._html = "";
await M.initParametres(globalThis.__container);
__emit({
  lastFlushError: st.lastFlushError,
  saveError: st.saveError,
  indicatorHtml: globalThis.__indicator.innerHTML,
  valueAtRemount: st.settings.omdb_api_key,
});
""")
        self.assertIsNone(res["lastFlushError"])
        self.assertIsNone(res["saveError"])
        self.assertNotIn("NON enregistr", res["indicatorHtml"])
        self.assertEqual(res["valueAtRemount"], "NOUVELLE-CLE", "l'edition a bien ete persistee")

    def test_nonreg_syntaxe_du_module(self):
        node_check(self, JS)


if __name__ == "__main__":
    unittest.main()
