"""Revue post-merge 2026-08-03 — trois ecarts « ce que l'ecran dit » vs « ce que
le code fait », un par fichier.

1. views/parametres.js — modale « Nouveau profil qualite ». `components/modal.js`
   fait `actions[idx].onClick(); closeModal();` SANS condition, et closeModal
   fait `overlay.remove()` de facon synchrone : le message d'erreur etait ecrit
   dans un noeud DEJA DETACHE et n'atteignait jamais l'ecran. La modale rouverte
   repartait de « MonProfil_v1 », effacant la saisie. En prime la regex ASCII
   `[A-Za-z0-9 _-]` refusait tout accent alors que l'UI est integralement en
   francais : « Qualite max » passait, « Qualité max » etait refuse — sans que
   rien ne s'affiche pour l'expliquer.

2. views/accueil.js — le ping Plex de la barre d'environnement envoyait
   `api_key`, alors que `IntegrationsFacade.test_plex_connection(url, token,
   timeout_s)` attend `token` (Plex est la seule integration a ne pas utiliser
   `api_key`). Le serveur REST fait `method(**params)` sans aliasing : TypeError
   -> HTTP 400 -> pastille Plex bloquee sur « hors ligne » alors que
   Parametres > Tester repondait OK sur le meme serveur.

3. components/perceptual-modal.js — le pied de modale lisait `d.analyzed_at`,
   cle que le backend n'emet PAS (il renvoie `ts`, epoch secondes). Une analyse
   complete s'affichait donc avec « Non analysé » juste sous son propre score.

Les trois sont prouves en executant la vraie source sous Node.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, inline_module, node_check, require_node, run_module_test

PARAMETRES_JS = ROOT / "web" / "dashboard" / "views" / "parametres.js"
ACCUEIL_JS = ROOT / "web" / "dashboard" / "views" / "accueil.js"
PERCEPTUAL_JS = ROOT / "web" / "dashboard" / "components" / "perceptual-modal.js"

# --------------------------------------------------------------------------
# views/parametres.js
# --------------------------------------------------------------------------
PARAMETRES_STUBS = r"""
const escapeHtml = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const apiPost = async () => ({ status: 200, data: { ok: true } });
const invalidateSettingsCache = () => {};
const dangerConfirmModal = () => {};
const trapFocus = () => () => {};

globalThis.__modals = [];
globalThis.__overlay = null;
globalThis.__input = null;
// Reproduit modal.js : le corps HTML est rendu, l'input existe reellement et sa
// valeur initiale vient de l'attribut `value=` produit par la vue.
const showModal = (opts) => {
  globalThis.__modals.push(opts);
  const m = /data-parametres-profile-name-input[\s\S]*?>/.exec(String(opts.body || ""));
  const valueAttr = /value="([^"]*)"/.exec(String(opts.body || ""));
  const input = { value: valueAttr ? valueAttr[1] : "", _tag: m ? "input" : "?" };
  globalThis.__input = input;
  globalThis.__overlay = {
    querySelector: (sel) => (String(sel).includes("profile-name-input") ? input : null),
  };
};
// Reproduit `actions[idx].onClick(); closeModal();` de modal.js : la fermeture
// est INCONDITIONNELLE et synchrone.
globalThis.__clickAction = (label) => {
  const modal = globalThis.__modals[globalThis.__modals.length - 1];
  const action = modal.actions.find((a) => a.label === label);
  action.onClick();
  globalThis.__overlay = null;   // closeModal() -> overlay.remove()
};

function __el(name) {
  const el = {
    _name: name, _html: "",
    addEventListener() {}, removeEventListener() {},
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    classList: { add() {}, remove() {}, toggle() {} },
    dataset: {}, style: { setProperty() {} },
    querySelector: () => null, querySelectorAll: () => [],
    focus() {}, select() {},
  };
  Object.defineProperty(el, "innerHTML", { get() { return el._html; }, set(v) { el._html = String(v); } });
  return el;
}
globalThis.window = globalThis.window || { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = globalThis.document || {
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: (id) => (id === "dashModal" ? globalThis.__overlay : null),
  createElement: () => __el("created"),
  addEventListener() {}, removeEventListener() {},
  body: Object.assign(__el("body"), { appendChild() {} }),
  documentElement: __el("html"),
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
"""

PARAMETRES_EXTRA = r"""
export const __h = { promptNewProfileName: _promptNewProfileName };
"""

# --------------------------------------------------------------------------
# views/accueil.js
# --------------------------------------------------------------------------
# `deriveRunStatus` : vraie source partagee injectee (cf. inline_module).
ACCUEIL_STUBS = (
    inline_module("core/run-status.js")
    + r"""
const escapeHtml = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
globalThis.__posts = [];
const apiPost = async (endpoint, params) => {
  globalThis.__posts.push({ endpoint, params: JSON.parse(JSON.stringify(params || {})) });
  // Simule le serveur REST : `result = method(**params)` puis `except TypeError`
  // -> HTTP 400. On declare la signature REELLE de la facade Python.
  const SIGNATURES = {
    "integrations/test_plex_connection": ["url", "token", "timeout_s"],
    "integrations/test_jellyfin_connection": ["url", "api_key", "timeout_s"],
    "integrations/test_radarr_connection": ["url", "api_key", "timeout_s"],
    "integrations/test_tmdb_key": ["api_key", "state_dir", "timeout_s"],
    "integrations/test_omdb_connection": ["api_key", "timeout_s"],
  };
  const allowed = SIGNATURES[endpoint];
  if (allowed) {
    const unexpected = Object.keys(params || {}).filter((k) => !allowed.includes(k));
    if (unexpected.length) {
      return { status: 400, data: { ok: false, message: `Parametres invalides: unexpected keyword argument '${unexpected[0]}'` } };
    }
  }
  return { status: 200, data: { ok: true } };
};
const getSettingsEpoch = () => 0;
const getNavSignal = () => undefined;
const navigateTo = () => {};
const rightPanel = { setSections() {}, clear() {} };
globalThis.window = globalThis.window || { addEventListener() {}, removeEventListener() {}, location: { hash: "#/accueil" } };
globalThis.document = globalThis.document || {
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  addEventListener() {}, removeEventListener() {},
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
"""
)

ACCUEIL_EXTRA = r"""
export const __h = { pingIntegration: _pingIntegration };
"""

# --------------------------------------------------------------------------
# components/perceptual-modal.js
# --------------------------------------------------------------------------
PERCEPTUAL_STUBS = r"""
const escapeHtml = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const apiPost = async () => ({ status: 200, data: { ok: true } });
const humanize = (v, fallback) => (v == null || v === "" ? (fallback || "") : String(v));
const severityForTier = () => "info";
const SCORE_V2_COMPONENTS = [
  { id: "resolution", label: "Résolution", weight: 0.25 },
  { id: "bitrate", label: "Bitrate vidéo", weight: 0.20 },
];
const rpSetSections = () => {};
const rpSetExpandedWidth = () => {};
const rpIsExpandedWidth = () => false;
const openDuplicateComparatorModal = () => {};
const trapFocus = () => () => {};
globalThis.window = globalThis.window || { addEventListener() {}, removeEventListener() {}, location: { hash: "#/bibliotheque" } };
globalThis.document = globalThis.document || {
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  addEventListener() {}, removeEventListener() {},
};
"""

PERCEPTUAL_EXTRA = r"""
export const __h = { renderNormal: _renderNormal, analyzedAtLabel: _analyzedAtLabel };
"""


class ModaleNouveauProfilTests(unittest.TestCase):
    """Un refus de validation doit DIRE pourquoi et garder la saisie."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(PARAMETRES_JS, stubs=PARAMETRES_STUBS, extra=PARAMETRES_EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_nom_accentue_est_accepte(self):
        """ROUGE avant fix : « Qualité max » (UI 100 % francaise) etait refuse
        par une regex ASCII, en boucle et sans explication."""
        res = self._run(r"""
const submitted = [];
// Pas de `await` sur la promesse : un refus la laisse EN ATTENTE (la modale se
// rouvre), ce qui ferait sortir Node sur un top-level await non resolu au lieu
// d'une assertion lisible.
M.__h.promptNewProfileName(async (name) => { submitted.push(name); });
globalThis.__input.value = "Qualité max";
globalThis.__clickAction("Créer");
await globalThis.__sleep(20);
__emit({ submitted, modals: globalThis.__modals.length });
""")
        self.assertEqual(res["submitted"], ["Qualité max"])
        self.assertEqual(res["modals"], 1, "aucune reouverture : le nom est valide")

    def test_refus_conserve_la_saisie_et_affiche_le_motif(self):
        """ROUGE avant fix : la modale rouverte repartait de « MonProfil_v1 » et
        affichait le texte d'aide generique — le message d'erreur etait ecrit
        dans un noeud deja detache du DOM."""
        res = self._run(r"""
const submitted = [];
M.__h.promptNewProfileName(async (name) => { submitted.push(name); });
globalThis.__input.value = "Remux/UHD";        // '/' interdit
globalThis.__clickAction("Créer");
await globalThis.__sleep(20);
const second = globalThis.__modals[1];
__emit({
  modals: globalThis.__modals.length,
  body2: second ? second.body : null,
  valueInSecondInput: globalThis.__input.value,
  submitted,
});
""")
        self.assertEqual(res["modals"], 2, "la modale doit se rouvrir apres un refus")
        self.assertEqual(res["submitted"], [], "onSubmit ne doit pas etre appele sur un nom invalide")
        self.assertIn(
            "Nom invalide",
            res["body2"],
            "le motif du refus doit etre PORTE par la modale rouverte (l'ancienne est detachee)",
        )
        self.assertEqual(
            res["valueInSecondInput"],
            "Remux/UHD",
            "la saisie de l'utilisateur doit etre conservee, pas remise a la valeur par defaut",
        )
        self.assertNotIn('value="MonProfil_v1"', res["body2"])

    def test_message_daide_pas_colore_en_rouge_hors_erreur(self):
        """Nuance du finding : le paragraphe d'aide etait deja rouge AVANT toute
        erreur — aucun contraste ne distinguait l'etat normal de l'etat erreur."""
        res = self._run(r"""
M.__h.promptNewProfileName(async () => {});
__emit({ body1: globalThis.__modals[0].body });
""")
        body = res["body1"]
        self.assertNotIn("#DC2626", body, "pas de rouge tant qu'il n'y a pas d'erreur")
        self.assertNotIn('role="alert"', body, "pas d'alerte a l'ouverture")

    def test_reouverture_apres_refus_porte_bien_le_role_alert(self):
        res = self._run(r"""
M.__h.promptNewProfileName(async () => {});
globalThis.__input.value = "ab";
globalThis.__clickAction("Créer");
await globalThis.__sleep(20);
__emit({ body2: globalThis.__modals[1].body });
""")
        self.assertIn('role="alert"', res["body2"])
        self.assertIn("#DC2626", res["body2"])

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_noms_dangereux_toujours_refuses(self):
        """La tolerance aux accents ne doit pas ouvrir la porte aux separateurs
        de chemin ni aux noms hors bornes."""
        res = self._run(r"""
const out = {};
for (const candidate of ["ab", "../etc", "a/b/c", "C:\\temp", "x".repeat(41), "", "   "]) {
  globalThis.__modals.length = 0;
  const submitted = [];
  M.__h.promptNewProfileName(async (n) => { submitted.push(n); });
  globalThis.__input.value = candidate;
  globalThis.__clickAction("Créer");
  await globalThis.__sleep(10);
  out[candidate] = { accepted: submitted.length > 0, reopened: globalThis.__modals.length };
}
__emit(out);
""")
        for candidate, info in res.items():
            self.assertFalse(info["accepted"], f"{candidate!r} ne doit PAS etre accepte")
            self.assertEqual(info["reopened"], 2, f"{candidate!r} doit rouvrir la modale avec le motif")

    def test_nom_accentue_en_forme_nfd_est_accepte(self):
        """Un « é » colle depuis un texte en forme NFD est la sequence « e » +
        U+0301 : la classe Unicode des lettres seule le refusait, alors que la
        forme NFC passait. Deux chaines visuellement identiques ne doivent pas
        avoir deux sorts opposes.
        """
        # La chaine est definie UNE fois cote Python puis injectee dans le driver
        # JS : les deux cotes ne peuvent pas diverger. L'assertion qui suit est le
        # garde-fou d'outillage — si un editeur renormalisait ce fichier en NFC, le
        # test deviendrait tautologique et doit ECHOUER bruyamment plutot que
        # passer au vert pour une mauvaise raison.
        nfd = "Qualité max"
        self.assertNotEqual(nfd, "Qualité max", "cas de test renormalise en NFC : il ne prouve plus rien")
        res = self._run(
            """
const submitted = [];
M.__h.promptNewProfileName(async (name) => { submitted.push(name); });
globalThis.__input.value = "%s";
globalThis.__clickAction("Créer");
await globalThis.__sleep(20);
__emit({ submitted, modals: globalThis.__modals.length });
"""
            % nfd
        )
        self.assertEqual(res["submitted"], [nfd])
        self.assertEqual(res["modals"], 1, "aucune reouverture : le nom est valide")

    def test_nonreg_noms_ascii_toujours_acceptes(self):
        res = self._run(r"""
const out = {};
for (const candidate of ["MonProfil_v1", "Qualite max", "profil-2026", "Mon_Profil 4K"]) {
  globalThis.__modals.length = 0;
  const submitted = [];
  M.__h.promptNewProfileName(async (n) => { submitted.push(n); });
  globalThis.__input.value = candidate;
  globalThis.__clickAction("Créer");
  await globalThis.__sleep(10);
  out[candidate] = submitted;
}
__emit(out);
""")
        for candidate, submitted in res.items():
            self.assertEqual(submitted, [candidate], f"{candidate!r} doit rester accepte")

    def test_nonreg_annuler_resout_sans_rien_creer(self):
        res = self._run(r"""
const submitted = [];
const p = M.__h.promptNewProfileName(async (n) => { submitted.push(n); });
globalThis.__clickAction("Annuler");
await p;
__emit({ submitted, modals: globalThis.__modals.length });
""")
        self.assertEqual(res["submitted"], [])
        self.assertEqual(res["modals"], 1)

    def test_nonreg_esm(self):
        node_check(self, PARAMETRES_JS)


class PingPlexAccueilTests(unittest.TestCase):
    """La pastille Plex de l'Accueil doit interroger la facade avec ses vrais
    noms de parametres."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(ACCUEIL_JS, stubs=ACCUEIL_STUBS, extra=ACCUEIL_EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_ping_plex_utilise_token_pas_api_key(self):
        """ROUGE avant fix : `api_key` -> TypeError cote facade -> HTTP 400 ->
        pastille « Plex configure mais hors ligne » en permanence."""
        res = self._run(r"""
const ok = await M.__h.pingIntegration("plex", {
  plex_url: "http://192.168.1.50:32400",
  plex_token: "••••••••",            // get_settings masque le token
});
const post = globalThis.__posts.find(p => p.endpoint === "integrations/test_plex_connection");
__emit({ ok, params: post ? post.params : null });
""")
        self.assertEqual(
            sorted(res["params"].keys()),
            ["timeout_s", "token", "url"],
            f"payload envoye = {res['params']!r} ; la facade attend (url, token, timeout_s)",
        )
        self.assertTrue(res["ok"], "avec le bon nom de parametre, la pastille passe en ligne")

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_autres_integrations_utilisent_bien_api_key(self):
        """Plex est l'exception : les 4 autres facades attendent `api_key`."""
        res = self._run(r"""
const settings = {
  jellyfin_url: "http://nas:8096", jellyfin_api_key: "J",
  radarr_url: "http://nas:7878", radarr_api_key: "R",
  tmdb_api_key: "T", omdb_api_key: "O",
};
const out = {};
for (const key of ["jellyfin", "radarr", "tmdb", "omdb"]) out[key] = await M.__h.pingIntegration(key, settings);
__emit({ out, posts: globalThis.__posts.map(p => ({ e: p.endpoint, k: Object.keys(p.params).sort() })) });
""")
        self.assertEqual(res["out"], {"jellyfin": True, "radarr": True, "tmdb": True, "omdb": True})
        for post in res["posts"]:
            self.assertIn("api_key", post["k"], f"{post['e']} doit continuer d'envoyer api_key")

    def test_nonreg_plex_non_configure_envoie_un_payload_vide(self):
        """Sans url ni token, on laisse le backend lire ses settings persistes."""
        res = self._run(r"""
await M.__h.pingIntegration("plex", { plex_url: "", plex_token: "" });
const post = globalThis.__posts.find(p => p.endpoint === "integrations/test_plex_connection");
__emit({ params: post ? post.params : null });
""")
        self.assertEqual(res["params"], {})

    def test_nonreg_esm(self):
        node_check(self, ACCUEIL_JS)


class PiedModalePerceptuelleTests(unittest.TestCase):
    """« Non analysé » ne doit pas s'afficher sous une analyse complete."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(PERCEPTUAL_JS, stubs=PERCEPTUAL_STUBS, extra=PERCEPTUAL_EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_horodatage_lu_depuis_ts(self):
        """ROUGE avant fix : le pied lisait `d.analyzed_at`, absent du payload ;
        `quality/get_perceptual_details` renvoie `ts` (epoch secondes, colonne
        perceptual_reports.ts) -> « Non analysé » sous un score de 84."""
        res = self._run(r"""
// Payload tel que renvoye par perceptual_support.get_perceptual_details
// (verifie par execution : cles ... display_tier, grain_analysis, hdr_analysis,
//  height, ts, width ... et AUCUN analyzed_at).
const details = {
  global_score_v2: 84.2, display_tier: "a", width: 3840, height: 2160,
  ts: 1749000000.0,
};
const html = M.__h.renderNormal("Blade Runner 2049", details);
__emit({ html, label: M.__h.analyzedAtLabel(details) });
""")
        self.assertIsNotNone(res["label"], "l'horodatage doit etre derive de `ts`")
        self.assertNotIn(
            "Non analysé",
            res["html"],
            "une analyse persistee ne doit pas etre annoncee comme absente",
        )
        self.assertIn("Dernière analyse", res["html"])
        self.assertIn("2025", res["html"], f"date attendue en 2025 (ts=1749000000) ; label={res['label']!r}")

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_sans_horodatage_le_pied_dit_non_analyse(self):
        res = self._run(r"""
__emit({
  html: M.__h.renderNormal("Film", { global_score_v2: 50 }),
  labelVide: M.__h.analyzedAtLabel({}),
  labelZero: M.__h.analyzedAtLabel({ ts: 0 }),
  labelTexte: M.__h.analyzedAtLabel({ ts: "pas-un-nombre" }),
});
""")
        self.assertIn("Non analysé", res["html"])
        self.assertIsNone(res["labelVide"])
        self.assertIsNone(res["labelZero"])
        self.assertIsNone(res["labelTexte"])

    def test_nonreg_analyzed_at_prioritaire_si_le_backend_l_ajoute(self):
        res = self._run(r"""
__emit({ label: M.__h.analyzedAtLabel({ analyzed_at: "2026-01-02 03:04", ts: 1749000000 }) });
""")
        self.assertEqual(res["label"], "2026-01-02 03:04")

    def test_nonreg_esm(self):
        node_check(self, PERCEPTUAL_JS)


if __name__ == "__main__":
    unittest.main()
