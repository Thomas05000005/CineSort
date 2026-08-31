"""Audit 2026-08-31 — lot « front » : annonce-vs-fait, perte-de-donnees, gardes inertes.

Les constats couverts portent tous sur `web/dashboard/views/parametres.js` et
`web/dashboard/core/api.js`. Chaque test EXECUTE la vraie source sous Node via
`tests/_jsexec` (imports neutralises, corps de fonction jamais reecrit) ou lit
les fichiers reellement livres : aucune assertion ne compare une chaine de code
a une autre chaine de code.

  #72 CRITIQUE  perte-de-donnees
      Sur HTTP 5xx, `apiPost` sert l'instantane localStorage (TTL 24 h,
      core/cache.js:8) en y posant `_offline`/`_stale_age` — mais PAS `ok:false`,
      puisque le corps servi est celui d'une reponse a SUCCES mise en cache
      (`{ok:true, data:{...}}`). Le garde de `_loadSettings`
      (parametres.js:2567) ne teste que `res.data.ok === false` et ne regarde
      jamais `res.status` : l'ecran Parametres se peuplait de reglages vieux de
      24 h en se croyant a jour. Au premier toggle, `_scheduleSave` renvoyait
      cet instantane au backend => les reglages REELS etaient ecrases par ceux
      d'hier. C'est une PERTE, pas un affichage errone.

  #58 CRITIQUE  annonce-vs-fait
      « ↻ Re-calculer scores avec ce profil » (parametres.js:1389) postait
      `apiPost("quality/recompute_all_scores", {})` — corps VIDE. Le backend
      `recompute_all_scores(api)` (cinesort/ui/api/quality_audit_support.py:503)
      n'accepte aucun parametre : il re-score depuis le profil ACTIF PERSISTE.
      Or les curseurs de poids et les seuils de tier n'ecrivent que dans
      `_state.profileDraft` (memoire, parametres.js:3854 et :3864). Bouger un
      curseur puis cliquer lancait donc un re-scoring irreversible de TOUTE la
      bibliotheque (~5-10 min) avec un profil que l'ecran ne montrait plus.

  #59 MAJEUR    annonce-vs-fait
      « Au-dessus de ce score, l'UI n'affichera plus de recommandation
      d'upgrade pour ces films » (parametres.js:1428-1431). Aucun executant :
      `upgrade_until_score` n'est lu par aucune autre vue de `web/` et par
      aucun consommateur Python hors CRUD/import-export de profil.

  #63 MAJEUR    annonce-vs-fait (PARTIEL — la divergence de fond est backend)
      `_renderScanMaxWorkersSection` invente un plafond `64` quand le payload
      ne declare pas ses bornes (`Number(state.max || 64)`), c'est-a-dire une
      TROISIEME copie d'une borne que le front ne possede pas.

  #69 MINEUR    garde inerte
      `_RETRY_DELAYS_MS = [100, 200, 400, 800]` avec `_MAX_RETRIES = 3` : les
      deux boucles de retry lisent `_RETRY_DELAYS_MS[attempt]` sous la garde
      `attempt < _MAX_RETRIES`, donc les indices 0/1/2 seulement. Le 800 ms
      annonce en commentaire n'a jamais ete attendu.

  #68 MINEUR    garde inerte
      `_setConnStatus` (api.js:12) cible `#dashConnStatus`, un element qui
      n'existe ni dans `web/dashboard/index.html` ni cree par aucun JS : la
      fonction sortait a sa premiere ligne a chaque appel, et le compteur
      `_connFailureStreak` / `_CONN_FAIL_THRESHOLD` etait tenu pour personne.

ROUGE constate : les deux fichiers remis a leur version d'avant correctif font
echouer 13 de ces tests (les autres sont des non-regressions, vertes des deux
cotes). Chacun a ete relu pour verifier qu'il echoue bien pour le mecanisme
vise, pas pour un ReferenceError de harnais.

Mutation ciblee, 5 mutants, 5 tues — dont deux qui ont revele une faiblesse
d'assertion avant d'etre commis :

  - `_motifDeRefusDesReglages`, branche `_offline` retiree -> le message
    redevient le generique « Serveur indisponible (HTTP 503). ». L'assertion
    d'origine acceptait « 503 » et laissait donc ce mutant VIVANT ; elle exige
    desormais le mot « hors ligne » ET l'age de l'instantane, que SEULE cette
    branche produit.
  - branche `status >= 400` retiree -> seul
    `test_un_4xx_sans_cle_ok_est_refuse_par_le_status` rougit. Ce test a ete
    AJOUTE pour ce mutant : les 4xx que `core/api.js` n'intercepte pas (410
    Gone des chemins historiques, 404, 403) traversent avec le corps du
    serveur, qui peut n'avoir aucune cle `ok`.
  - branche `ok === false` retiree -> le garde historique (BUG USER #1) rougit.
  - `_brouillonDivergeDuProfilApplique` comparant le brouillon a LUI-MEME
    (garde qui ne mord jamais) -> 2 tests.
  - le meme garde force a `true` (garde trop zele, qui bloquerait un profil
    conforme) -> 3 non-regressions. Les deux directions sont donc tenues.
"""

from __future__ import annotations

import re
import unittest

from tests._jsexec import ROOT, inline_module, node_check, require_node, run_module_test

PARAMETRES_JS = ROOT / "web" / "dashboard" / "views" / "parametres.js"
API_JS = ROOT / "web" / "dashboard" / "core" / "api.js"
INDEX_HTML = ROOT / "web" / "dashboard" / "index.html"
DASHBOARD_DIR = ROOT / "web" / "dashboard"


# =============================================================================
# Stubs parametres.js
#
# `apiPost` est pilotable par endpoint (`globalThis.__responses`) et enregistre
# tout ce qui part (`globalThis.__calls`) : c'est le seul moyen d'observer ce
# que le bouton transmet REELLEMENT au backend.
# =============================================================================
_PARAM_STUBS = r"""
globalThis.__calls = [];
globalThis.__responses = {};
globalThis.__profilMessages = [];
globalThis.__dangerModals = [];

const apiPost = async (endpoint, body) => {
  globalThis.__calls.push({ endpoint, body: JSON.parse(JSON.stringify(body || {})) });
  if (Object.prototype.hasOwnProperty.call(globalThis.__responses, endpoint)) {
    return globalThis.__responses[endpoint];
  }
  return { status: 200, data: { ok: true } };
};
const invalidateSettingsCache = () => {};
const escapeHtml = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const formatBytes = (n) => String(n);
// La modale de danger confirme immediatement : ces tests mesurent ce qui part
// APRES confirmation utilisateur, pas l'ergonomie de la modale elle-meme.
const dangerConfirmModal = (opts) => {
  globalThis.__dangerModals.push({ title: opts && opts.title, consequence: opts && opts.consequence });
  if (opts && typeof opts.onConfirm === "function") return opts.onConfirm();
  return undefined;
};
const showModal = () => {};
const trapFocus = () => () => {};
const ouvrirSimulateurQualite = () => {};
const ouvrirReglesQualite = () => {};
const ouvrirCalibrationQualite = () => {};

function __el(name) {
  const el = {
    _name: name, _html: "", _text: "",
    addEventListener() {}, removeEventListener() {},
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    classList: { add() {}, remove() {}, toggle() {} },
    dataset: {}, style: { setProperty() {} },
    querySelector: () => null, querySelectorAll: () => [],
    focus() {}, select() {}, appendChild() {}, remove() {},
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; }, set(v) { el._html = String(v); },
  });
  Object.defineProperty(el, "textContent", {
    get() { return el._text; },
    set(v) { el._text = String(v); if (el._name === "profils-message") globalThis.__profilMessages.push(String(v)); },
  });
  return el;
}
globalThis.__el = __el;
globalThis.__messageEl = __el("profils-message");
// containerRef minimal : seul le paragraphe de message des profils est resolu,
// c'est par lui que l'utilisateur est (ou n'est pas) averti.
globalThis.__container = {
  querySelector: (sel) => (String(sel).includes("profils-message") ? globalThis.__messageEl : null),
  querySelectorAll: () => [],
};

globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = {
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  createElement: () => __el("created"), addEventListener() {}, removeEventListener() {},
  body: Object.assign(__el("body"), { appendChild() {}, dataset: {} }),
  documentElement: __el("html"),
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
"""

_PARAM_EXTRA = r"""
export const __h = {
  state: _state,
  loadSettings: _loadSettings,
  loadProfiles: _loadProfiles,
  recomputeScores: _recomputeScores,
  renderProfilsQualite: _renderProfilsQualite,
  renderScanMaxWorkers: _renderScanMaxWorkersSection,
  scheduleSave: _scheduleSave,
  DEFAULT_TIERS: _DEFAULT_TIERS,
  DEFAULT_WEIGHTS: _DEFAULT_WEIGHTS,
};
"""


def _run_parametres(driver: str) -> dict:
    return run_module_test(PARAMETRES_JS, stubs=_PARAM_STUBS, extra=_PARAM_EXTRA, driver=driver, timeout=90)


# =============================================================================
# #72 — l'instantane hors ligne franchit le garde de _loadSettings
# =============================================================================

# La forme servie sur 5xx n'est pas inventee ici : elle est MESUREE plus bas par
# `InstantaneHorsLigneFormeReelleTests`, qui fait tourner la vraie `core/api.js`
# avec la vraie `core/cache.js` et un vrai aller-retour localStorage.
_REPONSE_5XX_AVEC_INSTANTANE = r"""
globalThis.__responses["settings/get_settings"] = {
  status: 503,
  data: {
    ok: true,
    data: { roots: ["D:/FilmsDHier"], theme: "cinema", expert_mode: false },
    _offline: true,
    _stale_age: "il y a 7 h",
  },
};
"""


class InstantaneHorsLigneRefuseTests(unittest.TestCase):
    """#72 : un instantane de 24 h ne doit JAMAIS devenir `_state.settings`."""

    def setUp(self) -> None:
        require_node(self)

    def test_load_settings_refuse_un_instantane_hors_ligne(self):
        """ROUGE avant fix : `_loadSettings` rendait la main sans erreur et
        `_state.settings` valait les reglages d'hier — l'ecran affichait un etat
        perime en se croyant a jour (aucun banner, aucun bouton Reessayer)."""
        res = _run_parametres(
            _REPONSE_5XX_AVEC_INSTANTANE
            + r"""
const st = M.__h.state;
let leve = null;
try { await M.__h.loadSettings(); } catch (e) { leve = String((e && e.message) || e); }
__emit({ leve, roots: (st.settings && st.settings.roots) || null });
"""
        )
        self.assertIsNotNone(
            res["leve"],
            "_loadSettings doit ECHOUER sur un repli hors ligne (status 5xx + _offline), "
            "sinon initParametres croit avoir charge l'etat serveur",
        )
        self.assertIsNone(
            res["roots"],
            "les reglages perimes ne doivent pas etre installes dans _state.settings",
        )

    def test_le_message_derreur_nomme_le_repli_hors_ligne(self):
        """L'utilisateur doit pouvoir distinguer « serveur injoignable, rien
        n'a ete charge » d'une erreur HTTP quelconque.

        Cette assertion vise ce que SEULE la branche `_offline` produit. Un
        garde qui se contenterait de `status >= 400` rendrait ici le message
        generique « Serveur indisponible (HTTP 503). » — verifie par mutation :
        retirer la branche `_offline` fait bien echouer ce test."""
        res = _run_parametres(
            _REPONSE_5XX_AVEC_INSTANTANE
            + r"""
let leve = null;
try { await M.__h.loadSettings(); } catch (e) { leve = String((e && e.message) || e); }
__emit({ leve });
"""
        )
        self.assertIsNotNone(res["leve"])
        bas = res["leve"].lower()
        self.assertIn("hors ligne", bas, f"le repli hors ligne doit etre nomme : {res['leve']!r}")
        self.assertIn(
            "il y a 7 h",
            bas,
            f"l'age de l'instantane ecarte (`_stale_age`) doit atteindre l'utilisateur : {res['leve']!r}",
        )

    def test_un_echec_de_chargement_ne_fait_pas_ecraser_les_reglages_reels(self):
        """LA perte de donnees. Sequence reelle : la vue a deja les reglages
        courants, un rechargement tombe sur un 5xx servi depuis l'instantane,
        puis l'utilisateur coche une case -> `_scheduleSave` POSTe.

        ROUGE avant fix : le POST partait avec `roots = ["D:/FilmsDHier"]`,
        c'est-a-dire que la sauvegarde d'un simple toggle RESTAURAIT les
        reglages de la veille par-dessus les vrais."""
        res = _run_parametres(
            _REPONSE_5XX_AVEC_INSTANTANE
            + r"""
const st = M.__h.state;
st.containerRef = globalThis.__container;
st.settings = { roots: ["D:/FilmsActuels"], theme: "luxe", expert_mode: false };
try { await M.__h.loadSettings(); } catch (_e) { /* attendu apres fix */ }
st.settings.expert_mode = true;          // l'utilisateur coche « Mode expert »
M.__h.scheduleSave();
await globalThis.__sleep(700);           // debounce 500 ms
const saves = globalThis.__calls.filter((c) => c.endpoint === "settings/save_settings");
__emit({
  saveCount: saves.length,
  rootsEnvoyes: saves.length ? saves[0].body.settings.roots : null,
});
"""
        )
        self.assertEqual(res["saveCount"], 1, "le toggle doit bien declencher une sauvegarde")
        self.assertEqual(
            res["rootsEnvoyes"],
            ["D:/FilmsActuels"],
            "le save renvoie les reglages de l'instantane perime : les dossiers racines "
            "reels sont ecrases par ceux d'hier",
        )

    def test_nonreg_une_reponse_200_charge_normalement(self):
        res = _run_parametres(
            r"""
globalThis.__responses["settings/get_settings"] = {
  status: 200, data: { ok: true, data: { roots: ["D:/FilmsActuels"], theme: "luxe" } },
};
const st = M.__h.state;
let leve = null;
try { await M.__h.loadSettings(); } catch (e) { leve = String((e && e.message) || e); }
__emit({ leve, roots: st.settings.roots, theme: st.settings.theme });
"""
        )
        self.assertIsNone(res["leve"])
        self.assertEqual(res["roots"], ["D:/FilmsActuels"])
        self.assertEqual(res["theme"], "luxe")

    def test_nonreg_une_erreur_backend_explicite_reste_une_erreur(self):
        """Le garde historique (`ok === false`, BUG USER #1) ne doit pas sauter."""
        res = _run_parametres(
            r"""
globalThis.__responses["settings/get_settings"] = {
  status: 200, data: { ok: false, message: "Cle d'acces invalide." },
};
let leve = null;
try { await M.__h.loadSettings(); } catch (e) { leve = String((e && e.message) || e); }
__emit({ leve });
"""
        )
        self.assertIsNotNone(res["leve"])
        self.assertIn("invalide", res["leve"])

    def test_un_4xx_sans_cle_ok_est_refuse_par_le_status(self):
        """La branche `status >= 400` est la SEULE a couvrir ce cas.

        `core/api.js` intercepte 401/429/409/5xx et fabrique lui-meme un
        `{ok: false, ...}`. Mais un 4xx qu'il n'intercepte pas (le 410 Gone des
        chemins `/api/<methode>` historiques, un 404, un 403) traverse tel quel :
        `res.data` est le corps du serveur, qui peut n'avoir aucune cle `ok`.
        Ni `ok === false` ni `_offline` ne le voient — sans ce garde, l'ecran
        installerait ce corps d'erreur comme s'il s'agissait des reglages."""
        res = _run_parametres(
            r"""
globalThis.__responses["settings/get_settings"] = {
  status: 410, data: { error: "gone", detail: "utilisez /api/settings/get_settings" },
};
const st = M.__h.state;
st.settings = null;
let leve = null;
try { await M.__h.loadSettings(); } catch (e) { leve = String((e && e.message) || e); }
__emit({ leve, settings: st.settings });
"""
        )
        self.assertIsNotNone(res["leve"], "un 4xx sans cle `ok` doit etre refuse")
        self.assertIsNone(res["settings"], "aucun corps d'erreur ne doit devenir les reglages")
        self.assertIn("410", res["leve"])

    def test_nonreg_syntaxe(self):
        node_check(self, PARAMETRES_JS)


# --- oracle de forme : la vraie api.js + la vraie cache.js -------------------
#
# `loadSnapshot` n'est PAS stubbe : la source de `core/cache.js` est injectee
# telle quelle et `localStorage` est une vraie Map. Sans cela le test
# verifierait la copie du testeur, pas le contrat livre.
_API_CACHE_STUBS = (
    inline_module("core/cache.js")
    + r"""
globalThis.__store = new Map();
globalThis.localStorage = {
  get length() { return globalThis.__store.size; },
  key: (i) => Array.from(globalThis.__store.keys())[i] ?? null,
  getItem: (k) => (globalThis.__store.has(k) ? globalThis.__store.get(k) : null),
  setItem: (k, v) => { globalThis.__store.set(k, String(v)); },
  removeItem: (k) => { globalThis.__store.delete(k); },
};
globalThis.__toasts = [];
globalThis.__status = 200;
globalThis.__payload = { ok: true, data: { roots: ["D:/FilmsDHier"], theme: "cinema" } };

const getToken = () => "tok";
const clearToken = () => {};
const awaitToken = async () => {};
const showToast = (o) => { globalThis.__toasts.push(o); };

globalThis.window = {
  location: { origin: "http://127.0.0.1:8642", hostname: "127.0.0.1" },
  addEventListener() {}, removeEventListener() {},
};
globalThis.document = {
  getElementById: () => null, querySelector: () => null,
  addEventListener() {}, removeEventListener() {},
};
globalThis.fetch = async () => ({ status: globalThis.__status, json: async () => globalThis.__payload });
"""
)


class InstantaneHorsLigneFormeReelleTests(unittest.TestCase):
    """#72 (oracle) : ce que `apiPost` rend VRAIMENT sur 5xx apres mise en cache.

    Ce test ne verifie pas un correctif : il MESURE la forme dont depend le
    garde de `_loadSettings`. C'est lui qui interdit de « corriger » le garde
    sur une forme imaginee.
    """

    def setUp(self) -> None:
        require_node(self)

    def test_le_repli_5xx_ne_porte_pas_ok_false(self):
        res = run_module_test(
            API_JS,
            stubs=_API_CACHE_STUBS,
            extra="",
            driver=r"""
// 1) un succes : l'instantane part en localStorage (settings/get_settings est
//    dans la whitelist de core/cache.js).
const ok = await M.apiPost("settings/get_settings", {});
// 2) le serveur tombe.
globalThis.__status = 503;
const ko = await M.apiPost("settings/get_settings", {});
__emit({
  statusOk: ok.status,
  cle: Array.from(globalThis.__store.keys()),
  statusKo: ko.status,
  okFieldKo: ko.data.ok,
  offline: ko.data._offline === true,
  rootsKo: (ko.data.data && ko.data.data.roots) || null,
});
""",
            timeout=90,
        )
        self.assertEqual(res["statusOk"], 200)
        self.assertIn("cinesort.cache.settings/get_settings", res["cle"], "l'instantane a bien ete ecrit")
        self.assertEqual(res["statusKo"], 503)
        self.assertTrue(res["offline"], "le repli pose bien `_offline`")
        self.assertIsNot(
            res["okFieldKo"],
            False,
            "MESURE : sur 5xx le corps servi porte le `ok` du succes mis en cache — "
            "`data.ok === false` ne peut donc PAS detecter la panne, seul `status` le peut",
        )
        self.assertEqual(res["rootsKo"], ["D:/FilmsDHier"], "ce sont bien les donnees d'hier qui remontent")

    def test_nonreg_syntaxe(self):
        node_check(self, API_JS)


# =============================================================================
# #58 — le brouillon edite n'est jamais transmis au re-calcul
# =============================================================================
_PROFIL_SAUVEGARDE = r"""
globalThis.__responses["settings/get_profiles"] = {
  status: 200,
  data: {
    ok: true,
    active_profile_id: "p1",
    profiles: [{
      id: "p1", label: "Mon profil",
      tiers: { platinum: 70, gold: 66, silver: 55, bronze: 40 },
      weights: { video: 60, audio: 30, extras: 10 },
    }],
  },
};
globalThis.__responses["quality/recompute_all_scores"] = {
  status: 200, data: { ok: true, job_id: "job-1" },
};
"""


class RecomputeBrouillonNonTransmisTests(unittest.TestCase):
    """#58 : « Re-calculer scores avec ce profil » avec un profil que le backend
    ne verra jamais."""

    def setUp(self) -> None:
        require_node(self)

    def test_un_brouillon_divergent_ne_lance_pas_le_rescoring(self):
        """ROUGE avant fix : le POST partait avec un corps VIDE, donc le backend
        re-scorait toute la bibliotheque avec le profil SAUVEGARDE (video 60)
        alors que l'ecran montrait video 90. Ecrasement irreversible des scores
        avec un profil que l'utilisateur n'a pas choisi."""
        res = _run_parametres(
            _PROFIL_SAUVEGARDE
            + r"""
const st = M.__h.state;
st.containerRef = globalThis.__container;
await M.__h.loadProfiles();              // brouillon = profil sauvegarde
st.profileDraft.weights.video = 90;      // l'utilisateur bouge le curseur
st.profileDraft.weights.audio = 5;
st.profileDraft.weights.extras = 5;
await M.__h.recomputeScores();
await globalThis.__sleep(30);
const posts = globalThis.__calls.filter((c) => c.endpoint === "quality/recompute_all_scores");
__emit({ posts, messages: globalThis.__profilMessages });
"""
        )
        self.assertEqual(
            len(res["posts"]),
            0,
            "le re-calcul ne doit pas partir tant que le brouillon a l'ecran n'a pas ete "
            "enregistre : le backend ne lit QUE le profil actif persiste",
        )
        self.assertTrue(res["messages"], "l'utilisateur doit etre averti, pas laisse sans reponse")
        dernier = res["messages"][-1].lower()
        self.assertTrue(
            "enregistr" in dernier or "sauvegard" in dernier,
            f"le message doit dire quoi faire (enregistrer le profil) : {res['messages'][-1]!r}",
        )

    def test_un_seuil_de_tier_modifie_bloque_aussi(self):
        """Les seuils passent par le meme brouillon (parametres.js:3854)."""
        res = _run_parametres(
            _PROFIL_SAUVEGARDE
            + r"""
const st = M.__h.state;
st.containerRef = globalThis.__container;
await M.__h.loadProfiles();
st.profileDraft.tiers.gold = 62;
await M.__h.recomputeScores();
await globalThis.__sleep(30);
__emit({ posts: globalThis.__calls.filter((c) => c.endpoint === "quality/recompute_all_scores").length });
"""
        )
        self.assertEqual(res["posts"], 0)

    def test_nonreg_un_brouillon_conforme_lance_bien_le_rescoring(self):
        """Non-regression : sans divergence, le bouton garde son comportement.
        Le brouillon est construit par le VRAI `_loadProfiles`, pas a la main :
        c'est la seule facon de prouver qu'aucune divergence fantome n'est
        introduite par la normalisation."""
        res = _run_parametres(
            _PROFIL_SAUVEGARDE
            + r"""
const st = M.__h.state;
st.containerRef = globalThis.__container;
await M.__h.loadProfiles();
await M.__h.recomputeScores();
await globalThis.__sleep(30);
const posts = globalThis.__calls.filter((c) => c.endpoint === "quality/recompute_all_scores");
__emit({ posts, messages: globalThis.__profilMessages });
"""
        )
        self.assertEqual(len(res["posts"]), 1, "aucune divergence : le re-calcul doit partir")
        self.assertTrue(
            any("job-1" in m for m in res["messages"]),
            f"le job lance doit etre annonce : {res['messages']!r}",
        )

    def test_nonreg_aucun_profil_charge_et_brouillon_par_defaut_lance_le_rescoring(self):
        """Installation neuve : pas de profil en base, brouillon = defauts
        client (alignes sur le backend, cf test_audit_ultra_wave4b). Rien ne
        diverge, donc rien ne doit bloquer."""
        res = _run_parametres(
            r"""
globalThis.__responses["quality/recompute_all_scores"] = { status: 200, data: { ok: true, job_id: "job-2" } };
const st = M.__h.state;
st.containerRef = globalThis.__container;
st.profilesList = [];
st.activeProfileId = "";
st.profileDraft = null;
await M.__h.recomputeScores();
await globalThis.__sleep(30);
__emit({ posts: globalThis.__calls.filter((c) => c.endpoint === "quality/recompute_all_scores").length });
"""
        )
        self.assertEqual(res["posts"], 1)

    def test_la_modale_nomme_le_profil_reellement_applique(self):
        """La consequence annoncee doit dire AVEC QUOI le re-calcul tourne."""
        res = _run_parametres(
            _PROFIL_SAUVEGARDE
            + r"""
const st = M.__h.state;
st.containerRef = globalThis.__container;
await M.__h.loadProfiles();
await M.__h.recomputeScores();
await globalThis.__sleep(30);
__emit({ modals: globalThis.__dangerModals });
"""
        )
        self.assertEqual(len(res["modals"]), 1)
        texte = f"{res['modals'][0]['title']} {res['modals'][0]['consequence']}"
        self.assertIn(
            "Mon profil",
            texte,
            f"la modale doit nommer le profil ACTIF applique par le backend, pas un « ce profil » ambigu : {texte!r}",
        )


# =============================================================================
# #59 — « l'UI n'affichera plus de recommandation d'upgrade » : aucun executant
# =============================================================================
class UpgradeUntilScoreSansExecutantTests(unittest.TestCase):
    """#59 : le reglage est bien persiste, mais rien ne s'en sert pour filtrer."""

    def setUp(self) -> None:
        require_node(self)

    def test_aucun_consommateur_dans_le_front(self):
        """MESURE : `upgrade_until_score` n'apparait que dans parametres.js."""
        autres = []
        for js in sorted(DASHBOARD_DIR.rglob("*.js")):
            if js == PARAMETRES_JS:
                continue
            if "upgrade_until" in js.read_text(encoding="utf-8"):
                autres.append(js.relative_to(ROOT).as_posix())
        self.assertEqual(
            autres,
            [],
            "un consommateur est apparu : l'annonce peut (doit) redevenir une promesse d'UI",
        )

    def test_lecran_ne_promet_plus_un_filtrage_dupgrade_inexistant(self):
        """ROUGE avant fix : le paragraphe annoncait « l'UI n'affichera plus de
        recommandation d'upgrade pour ces films » alors qu'aucune vue de `web/`
        ne lit ce seuil et qu'aucune recommandation d'upgrade n'existe."""
        res = _run_parametres(
            r"""
__emit({ html: M.__h.renderProfilsQualite() });
"""
        )
        # On mesure ce que l'utilisateur LIT : les commentaires HTML sont
        # certes servis au navigateur, mais ils ne s'affichent pas. Les retirer
        # evite qu'une note de developpeur citant l'ancienne promesse fasse
        # rougir le correctif qu'elle documente — et rappelle que le rationnel
        # a sa place dans un commentaire JS, pas dans le gabarit.
        html = re.sub(r"<!--.*?-->", "", res["html"], flags=re.S)
        self.assertNotIn(
            "n'affichera plus",
            html,
            "promesse de comportement d'UI sans aucun executant",
        )
        # « Recyclarr » figurait DEJA dans ce bloc (titre de la section
        # d'import/export) : l'asserter ne prouverait rien. On exige la seule
        # phrase que le correctif produit — l'aveu explicite d'absence de
        # lecteur, qui devra sauter le jour ou un ecran consommera le seuil.
        self.assertIn(
            "ne s'en sert pas encore",
            html,
            "le paragraphe doit dire ce que le reglage fait REELLEMENT (voyager dans "
            "l'export/import Recyclarr) et reconnaitre qu'aucun ecran ne le lit",
        )
        self.assertIn("upgrade.until_score", html, "le seuil doit etre nomme par son nom Recyclarr")


# =============================================================================
# #63 — un plafond de workers invente par le front
# =============================================================================
class ScanWorkersPlafondInventeTests(unittest.TestCase):
    """#63 (partiel) : le front ne possede pas cette borne, il ne doit pas
    en fabriquer une."""

    def setUp(self) -> None:
        require_node(self)

    def test_sans_bornes_declarees_le_front_ninvente_pas_de_plafond(self):
        """ROUGE avant fix : `Number(state.max || 64)` faisait annoncer
        « entre 1 et 64 » et poser `max="64"` alors que le payload ne declarait
        aucune borne — une TROISIEME copie d'un plafond deja encode deux fois
        cote Python, et deja divergent (64 en reglages, 32 a l'execution)."""
        res = _run_parametres(
            r"""
const html = M.__h.renderScanMaxWorkers({
  mode: "manual", value: 4, effective: 4,
  storage_detected: "local_ssd", auto_suggestion: 4,
});
__emit({ html });
"""
        )
        html = res["html"]
        self.assertNotIn('max="64"', html, "plafond invente par le front")
        self.assertNotIn("et 64", html, "plafond invente annonce a l'utilisateur")

    def test_nonreg_les_bornes_declarees_par_le_backend_sont_rendues(self):
        res = _run_parametres(
            r"""
const html = M.__h.renderScanMaxWorkers({
  mode: "manual", value: 4, effective: 4,
  storage_detected: "local_ssd", auto_suggestion: 4, min: 1, max: 64,
});
__emit({ html });
"""
        )
        html = res["html"]
        self.assertIn('max="64"', html)
        self.assertIn('min="1"', html)
        self.assertIn("et 64", html)


# =============================================================================
# #69 — la 4e temporisation de retry n'est jamais attendue
# =============================================================================
_API_RETRY_STUBS = r"""
globalThis.__delays = [];
globalThis.__fetches = 0;
globalThis.__status = 503;

const _setTimeoutReel = globalThis.setTimeout;
// On note le delai DEMANDE puis on le rend immediat : ce test mesure la table
// reellement parcourue, pas la duree d'attente.
globalThis.setTimeout = (fn, ms) => { globalThis.__delays.push(ms); return _setTimeoutReel(fn, 0); };

const getToken = () => "tok";
const clearToken = () => {};
const awaitToken = async () => {};
const isCacheable = () => false;
const saveSnapshot = () => {};
const loadSnapshot = () => null;
const formatStaleness = () => "";
const showToast = () => {};

globalThis.window = {
  location: { origin: "http://127.0.0.1:8642", hostname: "127.0.0.1" },
  addEventListener() {}, removeEventListener() {},
};
globalThis.document = {
  getElementById: () => null, querySelector: () => null,
  addEventListener() {}, removeEventListener() {},
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.fetch = async () => {
  globalThis.__fetches += 1;
  return { status: globalThis.__status, json: async () => ({ ok: false }) };
};
"""

_API_RETRY_EXTRA = r"""
export const __h = { RETRY_DELAYS_MS: _RETRY_DELAYS_MS, MAX_RETRIES: _MAX_RETRIES };
"""


class RetryDelaisTousAtteignablesTests(unittest.TestCase):
    """#69 : toute valeur de la table de backoff doit pouvoir etre attendue."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(API_JS, stubs=_API_RETRY_STUBS, extra=_API_RETRY_EXTRA, driver=driver, timeout=90)

    def test_post_5xx_parcourt_toute_la_table(self):
        """ROUGE avant fix : table = [100, 200, 400, 800], delais reellement
        demandes = [100, 200, 400]. Le 800 ms annonce n'a jamais ete attendu."""
        res = self._run(
            r"""
await M.apiPost("run/get_dashboard", {});
__emit({ delais: globalThis.__delays, table: M.__h.RETRY_DELAYS_MS, fetches: globalThis.__fetches });
"""
        )
        self.assertEqual(res["fetches"], 4, "1 essai + 3 retries")
        self.assertEqual(
            res["delais"],
            res["table"],
            f"table declaree {res['table']} mais delais reellement demandes {res['delais']} : "
            "la derniere valeur n'est atteignable par aucun `attempt`",
        )

    def test_get_5xx_parcourt_toute_la_table(self):
        res = self._run(
            r"""
await M.apiGet("/api/health");
__emit({ delais: globalThis.__delays, table: M.__h.RETRY_DELAYS_MS, fetches: globalThis.__fetches });
"""
        )
        self.assertEqual(res["fetches"], 4)
        self.assertEqual(res["delais"], res["table"])

    def test_la_table_et_le_compteur_ne_peuvent_plus_diverger(self):
        """Invariant structurel : `_MAX_RETRIES` doit valoir la longueur de la
        table, sinon la divergence peut revenir silencieusement."""
        res = self._run(
            r"""
__emit({ table: M.__h.RETRY_DELAYS_MS, max: M.__h.MAX_RETRIES });
"""
        )
        self.assertEqual(res["max"], len(res["table"]))

    def test_nonreg_pas_de_retry_sur_429(self):
        res = self._run(
            r"""
globalThis.__status = 429;
const r = await M.apiPost("run/get_dashboard", {});
__emit({ fetches: globalThis.__fetches, delais: globalThis.__delays, status: r.status });
"""
        )
        self.assertEqual(res["fetches"], 1, "429 ne doit pas etre retente")
        self.assertEqual(res["delais"], [])
        self.assertEqual(res["status"], 429)


# =============================================================================
# #68 — un indicateur de connexion cable sur un element inexistant
# =============================================================================
_ID_GET = re.compile(r"""getElementById\(\s*['"]([^'"]+)['"]\s*\)""")
_BLOC_COMMENTAIRE = re.compile(r"/\*.*?\*/", re.S)
_LIGNE_COMMENTAIRE = re.compile(r"(?m)^\s*(?://|\*).*$")


def _code_seul(src: str) -> str:
    """Retire les commentaires : ce test mesure ce que le module EXECUTE.

    Sans cette normalisation, le commentaire qui documente le retrait d'un
    appel contient l'appel lui-meme et rejoue eternellement le rouge — la prose
    ferait echouer le correctif qu'elle explique. On ne retire que les blocs
    `/* */` et les lignes qui COMMENCENT par `//` ou `*`, pour ne pas amputer
    un `http://` a l'interieur d'une chaine.
    """
    return _LIGNE_COMMENTAIRE.sub("", _BLOC_COMMENTAIRE.sub("", src))


class AucunElementFantomeDansApiTests(unittest.TestCase):
    """#68 : `core/api.js` ne doit cibler que des elements qui existent."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.api_src = _code_seul(API_JS.read_text(encoding="utf-8"))
        cls.html = INDEX_HTML.read_text(encoding="utf-8")
        cls.js_all = "\n".join(_code_seul(p.read_text(encoding="utf-8")) for p in sorted(DASHBOARD_DIR.rglob("*.js")))

    def _est_creable(self, ident: str) -> bool:
        if f'id="{ident}"' in self.html or f"id='{ident}'" in self.html:
            return True
        motifs = [
            rf"""\.id\s*=\s*['"]{re.escape(ident)}['"]""",
            rf"""setAttribute\(\s*['"]id['"]\s*,\s*['"]{re.escape(ident)}['"]""",
            rf"""id=["']{re.escape(ident)}["']""",
        ]
        return any(re.search(m, self.js_all) for m in motifs)

    def test_aucun_getelementbyid_ne_vise_un_element_inexistant(self):
        """ROUGE avant fix : `getElementById("dashConnStatus")` — cet element
        n'est ni dans `index.html` ni cree par aucun JS de `web/dashboard/`.
        `_setConnStatus` sortait donc a sa premiere ligne a CHAQUE appel, et le
        compteur `_connFailureStreak` / `_CONN_FAIL_THRESHOLD` etait tenu a jour
        pour personne."""
        fantomes = [i for i in sorted(set(_ID_GET.findall(self.api_src))) if not self._est_creable(i)]
        self.assertEqual(
            fantomes,
            [],
            f"identifiants cibles par core/api.js et introuvables dans le DOM livre : {fantomes}",
        )

    def test_aucun_compteur_dechec_sans_cible_affichable(self):
        """Le compteur d'echecs consecutifs n'a de sens que s'il pilote un
        affichage. S'il subsiste dans le CODE, il doit exister au moins un
        element DOM reellement present que `core/api.js` puisse peindre."""
        compteurs = [n for n in ("_CONN_FAIL_THRESHOLD", "_connFailureStreak") if n in self.api_src]
        if not compteurs:
            return
        cibles = [i for i in sorted(set(_ID_GET.findall(self.api_src))) if self._est_creable(i)]
        self.assertTrue(
            cibles,
            f"{compteurs} survivent alors que core/api.js ne peut peindre aucun element existant",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
