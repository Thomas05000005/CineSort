"""Les cinq actions d'integration doivent poser la BONNE route, et rendre la reponse.

CE QUE CES BOUTONS RENDENT ATTEIGNABLE. Cinq methodes de facade existaient,
testees cote backend, et n'etaient appelees par AUCUN code du dashboard.
`docs/TROUBLESHOOTING.md` donne pourtant le rapport de coherence Jellyfin comme
*la* solution utilisateur a un probleme documente — une reponse que personne ne
pouvait suivre.

CE QUE CE FICHIER EPROUVE, ET POURQUOI PAS AUTRE CHOSE. Une action d'integration
n'a que deux facons de se tromper qui comptent : appeler la mauvaise route, ou
perdre l'information de la reponse. Les deux sont verifiees sur la VRAIE source
`web/dashboard/views/parametres.js` (cf. `tests/_jsexec.py`) — un test qui
chercherait la chaine `get_jellyfin_sync_report` dans le fichier passerait au
vert sur du code mort.

POURQUOI `request_radarr_upgrade` N'EST PAS LA. Elle exige un `radarr_movie_id`,
donc elle appartient a la fiche d'un film, pas a un reglage global. La cabler ici
aurait demande d'inventer un champ de saisie d'identifiant Radarr — une interface
que personne n'a demandee, pour une methode qui a deja son domicile naturel
ailleurs. Elle reste donc dans `KNOWN_ORPHAN_METHODS`, et ce fichier ne pretend
pas le contraire.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

PARAMETRES_JS = ROOT / "web" / "dashboard" / "views" / "parametres.js"

#: Les routes que la page doit rendre atteignables.
#:
#: B2 : les cinq actions d'integration. B3 : quatre methodes runtime/settings.
#:
#: CETTE LISTE EST COURTE POUR UNE RAISON, ET LA RAISON EST MESUREE. La vague B3
#: portait sur ONZE methodes orphelines ; sept ne sont PAS cablees, chacune pour
#: un motif verifie dans le code et consigne dans `KNOWN_ORPHAN_METHODS` :
#:
#:   runtime.get_tools_status        alias STRICT de get_probe_tools_status, deja
#:                                   cable (app.js) et seul present dans la liste
#:                                   blanche du cache hors-ligne
#:   runtime.check_for_updates       doublon d'une capacite deja presente
#:   settings.preview_naming_template `sample_row_id` est INERTE (#460 : la branche
#:                                   qui chargeait un vrai film « etait morte
#:                                   depuis sa premiere ligne »)
#:   runtime.set_probe_tool_paths    perte de donnees sur payload partiel
#:   runtime.reset_incremental_cache impossible de dresser la liste d'elements
#:                                   qu'exige la regle des actions destructives
#:   runtime.run_nas_benchmark       aucun parametre de chemin : « tester mon NAS »
#:                                   est irrealisable en l'etat
ROUTES_ATTENDUES = (
    "integrations/get_jellyfin_sync_report",
    "integrations/refresh_jellyfin_library_now",
    "integrations/get_plex_sync_report",
    "integrations/refresh_plex_library_now",
    "integrations/test_email_report",
    "runtime/get_log_paths",
    "runtime/purge_probe_cache",
    "settings/get_naming_presets",
    "settings/get_user_data_size",
    "settings/reset_all_user_data",
)

_STUBS = r"""
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };

/** Un noeud DOM assez complet pour survivre a un rendu, et rien de plus. */
function noeudFactice() {
  return {
    dataset: {},
    style: { setProperty() {}, removeProperty() {} },
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    setAttribute() {}, removeAttribute() {}, getAttribute: () => null,
    appendChild() {}, removeChild() {},
    addEventListener() {}, removeEventListener() {},
    querySelector: () => null, querySelectorAll: () => [],
    focus() {}, remove() {},
    textContent: "", className: "", innerHTML: "",
  };
}
globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById() { return null; }, querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() { return { style: {}, classList: { add() {}, remove() {} }, appendChild() {} }; },
  body: noeudFactice(),
  // `_applyLivePreview` ecrit sur la racine du document ET sur le body (theme,
  // animations, vitesse d'effet). Sans eux, tout test qui declenche un
  // RECHARGEMENT echouait sur un `setAttribute` d'undefined — un echec de
  // HARNAIS, qu'il aurait ete facile de prendre pour un defaut du code.
  documentElement: noeudFactice(),
};

globalThis.__appels = [];
globalThis.__reponses = {};

function apiPost(route, params) {
  globalThis.__appels.push({ route, params });
  const r = globalThis.__reponses[route];
  return Promise.resolve(r === undefined ? { ok: true } : r);
}
function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function showToast(o) { globalThis.__toasts.push(o); }
globalThis.__toasts = [];
globalThis.__confirmations = [];
globalThis.__enCours = null;
// FIDELE A LA PRODUCTION, ET C'EST TOUT L'ENJEU. `dangerConfirmModal` n'est pas
// `async` et ne porte AUCUN `return` avec valeur : elle rappelle `onConfirm` ou
// `onCancel`. Le stub precedent rendait `Promise.resolve(true)` — un contrat que
// le code reel n'offre pas — et rendait donc VERT un appelant qui faisait
// `const accepte = await dangerConfirmModal(...)`, ou `accepte` valait toujours
// `undefined` et ou l'action ne partait jamais.
function dangerConfirmModal(o) {
  globalThis.__confirmations.push(o);
  if (globalThis.__accepte === false) {
    if (o.onCancel) o.onCancel();
    return;
  }
  // La vraie modale transmet a `onConfirm` CE QUE L'UTILISATEUR A TAPE quand
  // `requireTyped` est demande (modal.js). Un stub qui n'appellerait `onConfirm()`
  // sans argument laisserait passer un appelant qui ignore la saisie et envoie
  // la constante — precisement le defaut qui rendrait le garde du backend
  // decoratif. `__saisie` est ce que le test fait taper.
  const saisie = o.requireTyped ? String(globalThis.__saisie ?? o.requireTyped) : undefined;
  globalThis.__enCours = o.onConfirm ? o.onConfirm(saisie) : null;
}
function t(k) { return String(k); }
function formatBytes() { return ""; }
function registerRoute() {}
function navigate() {}
const rightPanel = { setWidth() {}, setExpanded() {}, setContent() {} };
// Le rechargement post-reset passe par le cache partage : on COMPTE ses appels.
globalThis.__invalidations = 0;
function invalidateSettingsCache() { globalThis.__invalidations += 1; }
"""

_EXTRA = (
    "export const __ACTIONS = ACTIONS_DE_SECTION;\n"
    "export const __rendreSectionActions = _renderSectionActions;\n"
    "export const __lancer = _lancerActionDeSection;\n"
    "export const __rendreReponse = _rendreReponseAction;\n"
    "export const __recharger = _rechargerApresReset;\n"
    "export const __etat = _state;\n"
    "export const __bindChamps = _bindFields;\n"
)

_EXIT = "\nprocess.exit(0);\n"

#: Les reponses que le RECHARGEMENT post-reset ira chercher. `_loadSettings` lit
#: `res.data` et LEVE si la forme n'y est pas (garde du BUG USER #1) : sans ces
#: reponses, le test mesurerait l'echec du harnais, pas celui du code.
_APRES_RESET = r"""
globalThis.__reponses["settings/get_settings"] = { data: { root: "R", state_dir: "S" } };
globalThis.__reponses["settings/get_profiles"] = { data: { profiles: [], active: "" } };
"""

#: Un bouton et sa section, tels que le DOM les porterait. Le `closest` remonte
#: a la section, qui expose la zone de sortie : c'est ce chemin-la qui casse si
#: le rendu et le gestionnaire divergent.
_FAUX_DOM = r"""
function fauxBouton(route, idSection) {
  // LA RACINE REMPLACE SON CONTENU, COMME LA VRAIE. `_refreshAll()` fait
  // `root.innerHTML = _renderParametres()` : il DETRUIT le noeud de sortie. Un
  // faux DOM qui rendrait eternellement le MEME objet ne pourrait jamais perdre
  // le message — et un test « le resultat survit au rechargement » serait vert
  // quoi qu'il arrive. La mutation l'a montre : deux correctifs de cette famille
  // ont SURVECU a leur propre batterie tant que ce faux DOM ne remplacait rien.
  const id = idSection || "stockage-sqlite";
  let vivant = { textContent: "", className: "" };
  const sortie = vivant;
  const section = { querySelector: () => vivant, dataset: { sectionId: id } };
  const btn = {
    dataset: { sectionAction: route },
    disabled: false,
    closest: () => section,
  };
  const racine = {
    set innerHTML(_v) { vivant = { textContent: "", className: "" }; },
    get innerHTML() { return ""; },
    classList: { toggle() {}, add() {}, remove() {} },
    querySelector(sel) { return sel === `[data-section-actions-out="${id}"]` ? vivant : null; },
    querySelectorAll: () => [],
  };
  // `sortie` est le noeud INITIAL — celui qu'un rechargement detacherait.
  // `courante()` rend celui qui est vivant apres un rendu.
  return { btn, sortie, racine, courante: () => vivant };
}
"""


class LesActionsSontDECLAREESTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(PARAMETRES_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)

    def test_les_routes_declarees_sont_exactement_celles_attendues(self) -> None:
        res = self._run(
            r"""
const routes = [];
for (const actions of Object.values(M.__ACTIONS)) for (const a of actions) routes.push(a.route);
__emit({ routes });
"""
        )
        self.assertEqual(sorted(res["routes"]), sorted(ROUTES_ATTENDUES))

    def test_chaque_action_porte_un_libelle_et_une_explication(self) -> None:
        """Un bouton sans titre laisse l'utilisateur deviner ce qu'il declenche."""
        res = self._run(
            r"""
const manques = [];
for (const actions of Object.values(M.__ACTIONS)) for (const a of actions) {
  if (!a.label || !a.titre || !a.rendu) manques.push(a.route);
}
__emit({ manques });
"""
        )
        self.assertEqual(res["manques"], [])

    def test_une_section_SANS_action_ne_rend_rien(self) -> None:
        """Le rendu ne doit pas semer des barres d'action vides partout."""
        res = self._run('__emit({ html: M.__rendreSectionActions({ id: "tmdb" }) });')
        self.assertEqual(res["html"], "")

    def test_la_section_jellyfin_rend_ses_DEUX_boutons(self) -> None:
        res = self._run('__emit({ html: M.__rendreSectionActions({ id: "jellyfin" }) });')
        self.assertIn("integrations/get_jellyfin_sync_report", res["html"])
        self.assertIn("integrations/refresh_jellyfin_library_now", res["html"])
        self.assertIn('data-section-actions-out="jellyfin"', res["html"])


class LActionAPPELLELaRouteDeSonBoutonTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(PARAMETRES_JS, stubs=_STUBS, extra=_EXTRA, driver=_FAUX_DOM + driver + _EXIT, timeout=90)

    def test_le_rapport_jellyfin_appelle_sa_route(self) -> None:
        res = self._run(
            r"""
const { btn } = fauxBouton("integrations/get_jellyfin_sync_report");
globalThis.__reponses["integrations/get_jellyfin_sync_report"] = { ok: true, missing: 3, matched: 41 };
await M.__lancer({ querySelectorAll: () => [] }, btn);
__emit({ appels: globalThis.__appels.map((a) => a.route) });
"""
        )
        self.assertEqual(res["appels"], ["integrations/get_jellyfin_sync_report"])

    def test_une_route_INCONNUE_n_appelle_rien(self) -> None:
        """Un bouton dont la route n'est pas declaree ne doit pas partir au hasard."""
        res = self._run(
            r"""
const { btn } = fauxBouton("integrations/format_c_drive");
await M.__lancer({ querySelectorAll: () => [] }, btn);
__emit({ appels: globalThis.__appels.map((a) => a.route) });
"""
        )
        self.assertEqual(res["appels"], [])

    def test_un_REFUS_affiche_le_message_du_backend(self) -> None:
        res = self._run(
            r"""
const { btn, sortie } = fauxBouton("integrations/refresh_plex_library_now");
globalThis.__reponses["integrations/refresh_plex_library_now"] =
  { ok: false, user_message: "URL Plex absente." };
await M.__lancer({ querySelectorAll: () => [] }, btn);
__emit({ texte: sortie.textContent, classe: sortie.className });
"""
        )
        self.assertEqual(res["texte"], "URL Plex absente.")
        self.assertIn("--error", res["classe"])

    def test_le_bouton_est_reactive_meme_apres_un_echec(self) -> None:
        """Un bouton laisse desactive rendrait l'action injouable jusqu'au rechargement."""
        res = self._run(
            r"""
const { btn } = fauxBouton("integrations/test_email_report");
globalThis.__reponses["integrations/test_email_report"] = { ok: false, message: "SMTP KO" };
await M.__lancer({ querySelectorAll: () => [] }, btn);
__emit({ disabled: btn.disabled });
"""
        )
        self.assertFalse(res["disabled"])


class LeRapportRENDSesChiffresTests(unittest.TestCase):
    """Un rapport de coherence existe POUR ses chiffres : les reduire a « OK »
    perdrait exactement l'information qu'on est venu chercher."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(PARAMETRES_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)

    def test_les_compteurs_apparaissent(self) -> None:
        res = self._run(
            r"""
__emit({ texte: M.__rendreReponse({ rendu: "rapport" }, { ok: true, missing: 3, matched: 41 }) });
"""
        )
        self.assertIn("3", res["texte"])
        self.assertIn("41", res["texte"])

    def test_une_cle_ABSENTE_n_est_pas_rendue_comme_zero(self) -> None:
        """Une absence de mesure ne doit pas passer pour une mesure nulle."""
        res = self._run(
            r"""
__emit({ texte: M.__rendreReponse({ rendu: "rapport" }, { ok: true, matched: 41 }) });
"""
        )
        self.assertNotIn("0 absents", res["texte"])
        self.assertIn("41", res["texte"])

    def test_un_rapport_SANS_aucun_compteur_retombe_sur_le_message(self) -> None:
        res = self._run(
            r"""
__emit({ texte: M.__rendreReponse({ rendu: "rapport" }, { ok: true, message: "Rien à comparer." }) });
"""
        )
        self.assertEqual(res["texte"], "Rien à comparer.")

    def test_une_action_de_type_message_ne_cherche_pas_de_compteurs(self) -> None:
        res = self._run(
            r"""
__emit({ texte: M.__rendreReponse({ rendu: "message" }, { ok: true, missing: 3, message: "Rafraîchissement demandé." }) });
"""
        )
        self.assertEqual(res["texte"], "Rafraîchissement demandé.")


class UneActionDESTRUCTIVEDemandeConfirmationTests(unittest.TestCase):
    """La regle du depot : nommer la consequence AVANT d'agir.

    `purge_probe_cache` ne detruit pas de donnee utilisateur, mais elle fait
    repayer chaque mesure technique au prochain scan. Sur une grande
    bibliotheque c'est long, et c'est le genre de cout qu'on ne decouvre pas
    apres coup.
    """

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(PARAMETRES_JS, stubs=_STUBS, extra=_EXTRA, driver=_FAUX_DOM + driver + _EXIT, timeout=90)

    def test_un_REFUS_de_confirmation_n_appelle_RIEN(self) -> None:
        """Le test qui compte : dire non doit vraiment tout arreter."""
        res = self._run(
            r"""
globalThis.__accepte = false;
const { btn } = fauxBouton("runtime/purge_probe_cache");
await M.__lancer({ querySelectorAll: () => [] }, btn);
__emit({ appels: globalThis.__appels.map((a) => a.route), confirmations: globalThis.__confirmations.length });
"""
        )
        self.assertEqual(res["appels"], [], "la purge est partie malgre un refus de confirmation")
        self.assertEqual(res["confirmations"], 1, "aucune confirmation n'a ete demandee")

    def test_une_confirmation_ACCEPTEE_lance_bien_l_action(self) -> None:
        """LE test qui manquait.

        Sans lui, `await dangerConfirmModal(...)` — une fonction qui ne rend
        RIEN — donnait `undefined`, le garde `if (!accepte) return;` sortait, et
        la purge n'etait JAMAIS lancee : un bouton mort, silencieux, derriere une
        modale qui s'affichait normalement. Trois tests de confirmation restaient
        verts parce qu'ils n'eprouvaient que le chemin du REFUS.
        """
        res = self._run(
            r"""
globalThis.__accepte = true;
globalThis.__reponses["runtime/purge_probe_cache"] = { ok: true, items: 42 };
const { btn } = fauxBouton("runtime/purge_probe_cache");
M.__lancer({ querySelectorAll: () => [] }, btn);
await globalThis.__enCours;
__emit({ appels: globalThis.__appels.map((a) => a.route), confirmations: globalThis.__confirmations.length });
"""
        )
        self.assertEqual(
            res["appels"],
            ["runtime/purge_probe_cache"],
            "la confirmation a ete acceptee mais l'action n'est jamais partie",
        )
        self.assertEqual(res["confirmations"], 1)

    def test_la_confirmation_NOMME_la_consequence(self) -> None:
        """La cle est `consequence`, la seule que la modale destructure.

        Elle recevait `body`, que `dangerConfirmModal` ignore : la modale
        s'affichait SANS sa consequence, en violation de la regle n3 du depot.
        Asserter sur la cle transmise ne suffisait pas — il faut asserter sur
        celle que la modale LIT.
        """
        res = self._run(
            r"""
globalThis.__accepte = false;
const { btn } = fauxBouton("runtime/purge_probe_cache");
await M.__lancer({ querySelectorAll: () => [] }, btn);
const c = globalThis.__confirmations[0];
__emit({ corps: c.consequence, titre: c.title, cles: Object.keys(c) });
"""
        )
        self.assertIn("refaites au prochain scan", res["corps"])
        self.assertIn("Aucun film", res["corps"])
        self.assertTrue(res["titre"])
        self.assertNotIn(
            "body",
            res["cles"],
            "`body` n'est pas une option de dangerConfirmModal : ce qu'on y met est jete",
        )

    def test_le_DELAI_est_DECLARE_par_la_table_jamais_implicite(self) -> None:
        """LA REGLE N3 GRADUE LE DELAI SUR LE NOMBRE D'ELEMENTS.

        Sans `countdownSeconds` explicite, `dangerConfirmModal` le calcule sur
        `items.length` — c'est-a-dire sur ZERO, faute de liste — et l'absence de
        delai passe pour un choix alors que c'est un silence.

        Ici le delai est ECARTE, et c'est une decision mesuree :
        `purge_probe_cache()` ne prend aucun parametre et ne rend son compte
        (`entries_deleted`) qu'APRES coup, donc le nombre est inconnaissable
        avant l'appel ; et le cache se REGENERE au prochain scan, donc ce qui
        est perdu est du temps, pas de la donnee.

        Ce test verrouille le fait que la valeur soit TRANSMISE, pas sa valeur :
        une action future qui detruirait vraiment devra passer la sienne.
        """
        res = self._run(
            r"""
globalThis.__accepte = false;
const { btn } = fauxBouton("runtime/purge_probe_cache");
await M.__lancer({ querySelectorAll: () => [] }, btn);
const c = globalThis.__confirmations[0];
__emit({ cles: Object.keys(c), delai: c.countdownSeconds });
"""
        )
        self.assertIn(
            "countdownSeconds",
            res["cles"],
            "le delai n'est pas transmis : son absence serait un silence, pas un choix",
        )
        self.assertEqual(res["delai"], 0)

    def test_CHAQUE_confirmation_de_la_table_declare_son_delai(self) -> None:
        """Le garde qui compte pour la SUITE.

        Une action destructive ajoutee demain heritera du delai implicite — donc
        de zero — si personne ne l'oblige a se prononcer. Chaque `confirmation`
        doit porter `delaiSecondes`, et un delai nul doit porter son `motifSansDelai`.
        """
        res = self._run(
            r"""
const manquants = [];
for (const [section, actions] of Object.entries(M.__ACTIONS || {})) {
  for (const a of actions) {
    if (!a.confirmation) continue;
    const c = a.confirmation;
    if (typeof c.delaiSecondes !== "number") manquants.push(`${a.route}: delaiSecondes absent`);
    else if (c.delaiSecondes === 0 && !c.motifSansDelai) manquants.push(`${a.route}: delai nul sans motif`);
  }
}
__emit({ manquants });
"""
        )
        self.assertEqual(
            res["manquants"],
            [],
            "une confirmation ne declare pas son delai : la regle n3 ne peut pas s'armer",
        )

    def test_une_action_NON_destructive_ne_demande_rien(self) -> None:
        """Une confirmation sur tout devient un reflexe, donc plus une garde."""
        res = self._run(
            r"""
const { btn } = fauxBouton("runtime/get_log_paths");
globalThis.__reponses["runtime/get_log_paths"] = { ok: true, app_log: "C:/logs/app.txt" };
await M.__lancer({ querySelectorAll: () => [] }, btn);
__emit({ confirmations: globalThis.__confirmations.length, appels: globalThis.__appels.map((a) => a.route) });
"""
        )
        self.assertEqual(res["confirmations"], 0)
        self.assertEqual(res["appels"], ["runtime/get_log_paths"])


class LesRendusB3RestituentLInformationTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(PARAMETRES_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)

    def test_les_chemins_de_logs_sont_lisibles(self) -> None:
        res = self._run(
            r"""
__emit({ texte: M.__rendreReponse({ rendu: "chemins" }, { ok: true, app_log: "C:/l/app.txt", ui_log: "C:/l/ui.txt" }) });
"""
        )
        self.assertIn("C:/l/app.txt", res["texte"])
        self.assertIn("C:/l/ui.txt", res["texte"])

    def test_les_presets_sont_comptes_et_nommes(self) -> None:
        """LA FORME REELLE D'ABORD, les formes tolerees ensuite.

        Ce test n'eprouvait que des chaines et `{name}` / `{template}` — deux
        formes que le backend n'emet JAMAIS. Mesure de `get_naming_presets` sur
        un state_dir neuf :

            {"id": "default", "label": "Standard",
             "movie_template": "{title} ({year})", "tv_template": "{series} ({year})"}

        La cle qui fait fonctionner l'ecran est donc **`label`**, et aucune
        assertion ne la couvrait. Le rendu la lit — verifie — mais c'est un
        hasard heureux tant qu'aucun test ne l'exige : une simplification du
        rendu l'aurait fait disparaitre en silence, comme la cle `group_name` de
        la vague C.
        """
        res = self._run(
            r"""
__emit({
  reel: M.__rendreReponse({ rendu: "presets" }, { ok: true, presets: [
    { id: "default", label: "Standard", movie_template: "{title} ({year})", tv_template: "{series} ({year})" },
    { id: "avec_edition", label: "Avec edition", movie_template: "{title} ({year}) [{edition}]", tv_template: "" },
  ] }),
  chaines: M.__rendreReponse({ rendu: "presets" }, { ok: true, presets: ["Simple", "Avec edition"] }),
  objets: M.__rendreReponse({ rendu: "presets" }, { ok: true, presets: [{ name: "Simple" }, { template: "{title}" }] }),
  vide: M.__rendreReponse({ rendu: "presets" }, { ok: true, presets: [] }),
});
"""
        )
        # La forme REELLE : c'est `label` qui doit s'afficher, pas l'id.
        self.assertIn("2 modèle(s)", res["reel"])
        self.assertIn("Standard", res["reel"], "le libelle du preset n'est pas rendu")
        self.assertIn("Avec edition", res["reel"])
        self.assertNotIn("avec_edition", res["reel"], "l'identifiant technique s'affiche a la place du libelle")
        # Les formes TOLEREES restent supportees.
        self.assertIn("2 modèle(s)", res["chaines"])
        self.assertIn("Simple", res["objets"])
        # Une liste vide ne compte pas « 0 modele(s) » : elle retombe sur le
        # message generique du backend, qui sait quoi dire.
        self.assertNotIn("0 modèle(s)", res["vide"])

    def test_une_taille_est_rendue_en_octets_lisibles(self) -> None:
        res = self._run(
            r"""
__emit({ texte: M.__rendreReponse({ rendu: "taille" }, { ok: true, size_mb: 12.5, items: 3 }) });
"""
        )
        self.assertIn("Mo", res["texte"])
        self.assertIn("3 élément(s)", res["texte"])

    def test_un_rendu_SANS_donnee_retombe_sur_le_message(self) -> None:
        for rendu in ("chemins", "presets", "taille"):
            with self.subTest(rendu=rendu):
                res = self._run(
                    f'__emit({{ texte: M.__rendreReponse({{ rendu: "{rendu}" }}, {{ ok: true, message: "Rien." }}) }});'
                )
                self.assertEqual(res["texte"], "Rien.")


class LaREINITIALISATIONTOTALEEstAtteignableTests(unittest.TestCase):
    """LA SEULE DES DIX METHODES DE LA VAGUE B3 RESTEE NON CABLABLE.

    `settings.reset_all_user_data` refuse tout appel dont `confirmation` ne vaut
    pas exactement « RESET » (`reset_support.py:266`), et `dangerConfirmModal`
    n'avait aucune affordance de saisie : la capacite etait inatteignable depuis
    toute l'application. Le tri des routes orphelines la classait « NON cablable »
    pour cette raison.
    """

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(PARAMETRES_JS, stubs=_STUBS, extra=_EXTRA, driver=_FAUX_DOM + driver + _EXIT, timeout=90)

    def test_elle_exige_un_mot_TAPE_une_liste_et_un_delai(self) -> None:
        """La regle n3 du depot : liste des elements, consequence, delai. Le mot
        tape s'y ajoute — c'est l'action la plus destructive de l'application."""
        res = self._run(
            r"""
const { btn, racine, courante } = fauxBouton("settings/reset_all_user_data");
M.__etat.containerRef = racine;
M.__lancer(null, btn);
const c = globalThis.__confirmations[0] || {};
__emit({ mot: c.requireTyped, elements: (c.items || []).length,
         delai: c.countdownSeconds, consequence: String(c.consequence || "") });
"""
        )
        self.assertEqual(res["mot"], "RESET", "aucun mot n'est exige : le backend refusera toujours")
        self.assertGreaterEqual(res["elements"], 3, "la liste de ce qui sera detruit n'est pas montree")
        self.assertEqual(res["delai"], 3, "l'action irreversible part sans delai de reflexion")
        self.assertIn("sauvegarde", res["consequence"].lower(), "la sauvegarde ZIP n'est pas annoncee")

    def test_la_SAISIE_de_l_utilisateur_part_au_backend(self) -> None:
        """Envoyer la constante a la place rendrait le garde du backend
        decoratif : il relirait ce que ce fichier lui a souffle."""
        res = self._run(
            _APRES_RESET
            + r"""
globalThis.__saisie = "RESET";
const { btn, racine, courante } = fauxBouton("settings/reset_all_user_data");
M.__etat.containerRef = racine;
M.__lancer(null, btn);
await globalThis.__enCours;
const appel = globalThis.__appels.find((a) => a.route === "settings/reset_all_user_data");
__emit({ params: appel ? appel.params : null });
"""
        )
        self.assertEqual(
            res["params"],
            {"confirmation": "RESET"},
            "le mot tape n'est pas transmis : l'action partirait avec un corps vide",
        )

    def test_un_mot_DIFFERENT_part_tel_quel_et_le_backend_tranche(self) -> None:
        """Le front ne corrige pas la saisie : c'est le backend qui refuse. Sinon
        deux verites coexisteraient sur ce qui vaut confirmation."""
        res = self._run(
            r"""
globalThis.__saisie = "reset";
const { btn, racine, courante } = fauxBouton("settings/reset_all_user_data");
M.__etat.containerRef = racine;
M.__lancer(null, btn);
await globalThis.__enCours;
const appel = globalThis.__appels.find((a) => a.route === "settings/reset_all_user_data");
__emit({ params: appel ? appel.params : null });
"""
        )
        self.assertEqual(res["params"], {"confirmation": "reset"})

    def test_un_REFUS_n_appelle_RIEN(self) -> None:
        res = self._run(
            r"""
globalThis.__accepte = false;
const { btn, racine, courante } = fauxBouton("settings/reset_all_user_data");
M.__etat.containerRef = racine;
M.__lancer(null, btn);
await new Promise((r) => setTimeout(r, 0));
__emit({ appels: globalThis.__appels.map((a) => a.route) });
"""
        )
        self.assertEqual(res["appels"], [], "l'action est partie malgre l'annulation")

    def test_un_reset_PARTIEL_n_est_pas_annonce_comme_un_SUCCES(self) -> None:
        """LE CAS NORMAL, PAS L'EXCEPTION. Le wipe s'execute pendant que
        l'application TOURNE : ses threads de fond tiennent des fichiers ouverts,
        et sous Windows un seul suffit a faire echouer la suppression de son
        dossier parent (docstring de `_vider_state_dir_sauf_logs`). Le backend
        rend alors `ok: True` AVEC `failed` et un message « Reinitialisation
        PARTIELLE … fermez puis relancez ».

        Une premiere version ne lisait que `removed` et `backup_path` : la base
        et settings.json pouvaient SURVIVRE pendant que l'ecran annoncait
        « 1 element(s) supprime(s) » en VERT.
        """
        res = self._run(
            _APRES_RESET
            + r"""
globalThis.__saisie = "RESET";
globalThis.__reponses["settings/reset_all_user_data"] = {
  ok: true,
  backup_path: "C:/data/backup.zip",
  removed: ["runs"],
  failed: ["cinesort.db", "settings.json"],
  message: "Réinitialisation PARTIELLE : 1 élément(s) supprimé(s), 2 n'ont pas pu l'être (cinesort.db, settings.json). Fermez puis relancez l'application.",
};
const { btn, racine, courante } = fauxBouton("settings/reset_all_user_data");
M.__etat.containerRef = racine;   // le rechargement REMPLACERA le noeud
M.__lancer(null, btn);
await globalThis.__enCours;
await new Promise((r) => setTimeout(r, 0));
__emit({ texte: courante().textContent, classe: courante().className });
"""
        )
        # LES DEUX SOURCES SONT ASSERTEES SEPAREMENT. « 2 » et « cinesort.db »
        # figurent AUSSI dans la phrase du backend : les chercher nus laissait le
        # rendu de `failed` non prouve — la mutation l'a montre en survivant.
        # On exige donc la formule que SEUL ce rendu produit, puis la consigne
        # que seul le backend produit.
        self.assertIn(
            "N'ONT PAS PU L'ÊTRE",
            res["texte"],
            "le rendu ne dit pas, de lui-meme, que des elements ont resiste",
        )
        self.assertIn("cinesort.db", res["texte"], "on ne sait pas CE QUI a survecu")
        self.assertIn("relancez", res["texte"], "la consigne du backend est perdue")
        self.assertNotIn("--ok", res["classe"], "un reset PARTIEL est affiche en vert")
        self.assertIn("--avertissement", res["classe"])

    def test_un_reset_COMPLET_reste_vert(self) -> None:
        """La regle ne doit pas devenir alarmiste : sans `failed`, c'est un
        succes, et le dire autrement userait l'attention de l'utilisateur."""
        res = self._run(
            _APRES_RESET
            + r"""
globalThis.__saisie = "RESET";
globalThis.__reponses["settings/reset_all_user_data"] = {
  ok: true, backup_path: "C:/data/backup.zip", removed: ["db", "runs"], failed: [],
};
const { btn, racine, courante } = fauxBouton("settings/reset_all_user_data");
M.__etat.containerRef = racine;   // le rechargement REMPLACERA le noeud
M.__lancer(null, btn);
await globalThis.__enCours;
await new Promise((r) => setTimeout(r, 0));
__emit({ classe: courante().className, texte: courante().textContent });
"""
        )
        self.assertIn("--ok", res["classe"])
        self.assertNotIn("--avertissement", res["classe"])

    def test_la_RAISON_de_l_echec_est_montree_meme_sous_la_cle_error(self) -> None:
        """`reset_support` renvoie ses echecs sous `key="error"` (lignes 272, 278
        et 326), contrat historique documente dans `_responses.py`. Sans cette
        lecture, un disque plein pendant le ZIP affichait « L'action a echoue. »
        et rien d'autre : l'utilisateur ignorait que la SAUVEGARDE n'avait pas
        ete faite."""
        res = self._run(
            _APRES_RESET
            + r"""
globalThis.__saisie = "RESET";
globalThis.__reponses["settings/reset_all_user_data"] = {
  ok: false, error: "[Errno 28] No space left on device: 'C:/data/backup.zip'",
};
const { btn, racine, courante } = fauxBouton("settings/reset_all_user_data");
M.__etat.containerRef = racine;   // le rechargement REMPLACERA le noeud
M.__lancer(null, btn);
await globalThis.__enCours;
await new Promise((r) => setTimeout(r, 0));
__emit({ texte: courante().textContent, classe: courante().className });
"""
        )
        self.assertIn("No space left", res["texte"], "la raison de l'echec est jetee")
        self.assertIn("--error", res["classe"])

    def test_apres_le_reset_les_reglages_sont_RELUS_du_disque(self) -> None:
        """SANS CELA LE RESET S'ANNULE TOUT SEUL. `_state.settings` garde en
        memoire l'objet d'AVANT, et `_saveSettingsNow` POSTe `{settings}` en
        ENTIER : la premiere modification d'un champ recreerait settings.json
        avec exactement les reglages qu'on venait de supprimer."""
        res = self._run(
            _APRES_RESET
            + r"""
globalThis.__saisie = "RESET";
globalThis.__reponses["settings/reset_all_user_data"] = { ok: true, removed: ["db"], failed: [] };
globalThis.__invalidations = 0;
const { btn, racine, courante } = fauxBouton("settings/reset_all_user_data");
M.__etat.containerRef = racine;   // le rechargement REMPLACERA le noeud
M.__lancer(null, btn);
await globalThis.__enCours;
await new Promise((r) => setTimeout(r, 0));
__emit({ invalidations: globalThis.__invalidations,
         relu: globalThis.__appels.some((a) => a.route === "settings/get_settings"),
         texte: courante().textContent });
"""
        )
        self.assertGreaterEqual(res["invalidations"], 1, "le cache partage des reglages n'est pas invalide")
        # INVALIDER NE SUFFIT PAS : sans cette assertion, un rechargement qui
        # viderait le cache SANS relire le disque resterait vert, et l'ecran
        # continuerait de servir les reglages d'avant.
        self.assertTrue(res["relu"], "le cache est vide mais les reglages ne sont pas RELUS du disque")
        # LE RESULTAT DOIT SURVIVRE AU RECHARGEMENT. `_refreshAll` fait
        # `root.innerHTML = ...` : il DETRUIT le noeud de sortie. Sans reecriture,
        # l'utilisateur ne voyait RIEN — et sur cette action-la, cela emportait le
        # chemin de sauvegarde, seul moyen de revenir en arriere.
        self.assertTrue(
            res["texte"].strip(),
            "le message de resultat a disparu avec le rechargement du DOM",
        )

    def test_la_reponse_NOMME_la_sauvegarde(self) -> None:
        """C'est le seul moyen de revenir en arriere : ne pas la nommer rendrait
        la sauvegarde inutilisable."""
        res = self._run(
            r"""
const action = { rendu: "reset" };
__emit({ texte: M.__rendreReponse(action,
  { ok: true, backup_path: "C:/data/cinesort_backup_before_reset_1.zip", removed: ["db", "settings"] }) });
"""
        )
        self.assertIn("cinesort_backup_before_reset_1.zip", res["texte"])
        self.assertIn("2", res["texte"], "le nombre d'elements supprimes n'est pas dit")


class LaPurgeDuBucketEXIGELeMotEnCLIQUANTTests(unittest.TestCase):
    """LE TEST QUE LES DEUX GARDES D'INVENTAIRE NE REMPLACENT PAS.

    Les deux tests de critere lisent le SOURCE JS et comparent des fragments :
    ce sont des CLIQUETS D'INVENTAIRE — « aucun mot n'apparait ailleurs sans
    qu'on repasse par le critere » est bien une question de source, et le depot
    en a d'autres du meme genre (KNOWN_ORPHAN_METHODS, PLAFONDS). Mais ils ne
    declenchent rien : ils ne peuvent donc PAS voir une confirmation posee sur la
    MAUVAISE action.

    Celui-ci CLIQUE le vrai bouton et observe ce qui part. Constat de revue,
    verifie et retenu.
    """

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(PARAMETRES_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)

    def test_le_clic_demande_le_mot_VIDER(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["run/list_quarantine_bucket"] = {
  data: { ok: true, purge_scope_files_count: 12, purge_scope_sample: ["a.mkv"], purge_scope_bytes: 1048576 },
};
const boutons = [{ dataset: {}, rappel: null, addEventListener(_t, fn) { this.rappel = fn; } }];
const conteneur = {
  querySelectorAll(sel) { return sel.indexOf("quarantine_purge_all") >= 0 ? boutons : []; },
  querySelector() { return null; },
};
M.__bindChamps(conteneur);
if (boutons[0].rappel) await boutons[0].rappel();
await new Promise((r) => setTimeout(r, 0));
const c = globalThis.__confirmations[globalThis.__confirmations.length - 1] || {};
__emit({ mot: c.requireTyped || "", titre: String(c.title || "") });
"""
        )
        self.assertEqual(
            res["mot"],
            "VIDER",
            "le bouton « Vider maintenant » ne demande aucun mot : la suppression definitive part au premier clic",
        )
        self.assertIn("_review", res["titre"], "la confirmation ne nomme pas ce qu'elle vide")

    def test_un_REFUS_ne_supprime_RIEN(self) -> None:
        res = self._run(
            r"""
globalThis.__accepte = false;
globalThis.__reponses["run/list_quarantine_bucket"] = {
  data: { ok: true, purge_scope_files_count: 12, purge_scope_sample: [], purge_scope_bytes: 0 },
};
const boutons = [{ dataset: {}, rappel: null, addEventListener(_t, fn) { this.rappel = fn; } }];
const conteneur = {
  querySelectorAll(sel) { return sel.indexOf("quarantine_purge_all") >= 0 ? boutons : []; },
  querySelector() { return null; },
};
M.__bindChamps(conteneur);
if (boutons[0].rappel) await boutons[0].rappel();
await new Promise((r) => setTimeout(r, 0));
__emit({ purges: globalThis.__appels.filter((a) => a.route === "run/purge_quarantine_bucket_all").length });
"""
        )
        self.assertEqual(res["purges"], 0, "la purge est partie malgre l'annulation")


_PURGE_CLIQUEE = r"""
globalThis.__accepte = true;
globalThis.__reponses["run/list_quarantine_bucket"] = {
  data: { ok: true, purge_scope_files_count: 300, purge_scope_sample: [], purge_scope_bytes: 0 },
};
const sortie = { className: "", textContent: "", innerHTML: "" };
const boutons = [{ dataset: {}, rappel: null, addEventListener(_t, fn) { this.rappel = fn; } }];
const conteneur = {
  querySelectorAll(sel) { return sel.indexOf("quarantine_purge_all") >= 0 ? boutons : []; },
  querySelector(sel) { return sel.indexOf("quarantine_purge_all") >= 0 ? sortie : null; },
};
"""

_PURGE_LANCEE = r"""
M.__bindChamps(conteneur);
if (boutons[0].rappel) await boutons[0].rappel();
await new Promise((r) => setTimeout(r, 0));
await new Promise((r) => setTimeout(r, 0));
__emit({ classe: sortie.className, texte: sortie.textContent });
"""


class LaPurgeNAnnoncePasUnSUCCESQuandRienNEstSupprimeTests(unittest.TestCase):
    """UN ECHEC NE DOIT PAS S'AFFICHER EN VERT.

    `purge_review_bucket_all` pose `ok: true` a la CONSTRUCTION de son payload et
    ne le rediscute JAMAIS (`quarantine_ttl.py`) : ses echecs vivent dans
    `errors`. L'ecran ne lisait que `deleted`, donc une purge dont TOUS les
    fichiers ont resiste — verrouilles par un traitement en cours, droits
    refuses — affichait « ✓ 0 fichier(s) supprimé(s) » avec la coche et la classe
    `--ok`. L'utilisateur venait de TAPER « VIDER » pour une suppression
    definitive : il repart en croyant le bucket vide alors que rien n'a bouge.

    On ne corrige PAS `ok` cote backend : le mettre a faux des qu'`errors > 0`
    ferait passer pour un echec une purge ou 299 fichiers sur 300 sont bien
    partis, et changerait la semantique d'une valeur que d'autres appelants
    lisent. C'est l'ECRAN qui doit dire la verite.
    """

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(PARAMETRES_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)

    def test_zero_supprime_et_des_echecs_n_est_PAS_un_succes(self) -> None:
        res = self._run(
            _PURGE_CLIQUEE
            + r"""
globalThis.__reponses["run/purge_quarantine_bucket_all"] = {
  data: { ok: true, deleted: 0, errors: 300, bytes_freed: 0, considered: 300 },
};
"""
            + _PURGE_LANCEE
        )
        self.assertIn(
            "--error",
            res["classe"],
            f"une purge qui n'a RIEN supprime s'affiche en {res['classe']!r} : {res['texte']!r}",
        )
        self.assertNotIn("--ok", res["classe"])
        # ASSERTER CE QUE SEUL LE CORRECTIF PRODUIT. « 300 » figure aussi dans le
        # decompte de la modale ; c'est le mot « echec » qui distingue.
        self.assertIn("échec", res["texte"].lower(), "le nombre d'echecs n'est pas dit")

    def test_une_purge_PARTIELLE_est_annoncee_comme_partielle(self) -> None:
        """Le cas ou le vert est le plus trompeur : 299 lignes supprimees, une
        resiste, et l'ecran annoncait un succes franc — donc « le bucket est
        vide », ce qui est faux."""
        res = self._run(
            _PURGE_CLIQUEE
            + r"""
globalThis.__reponses["run/purge_quarantine_bucket_all"] = {
  data: { ok: true, deleted: 299, errors: 1, bytes_freed: 1048576, considered: 300 },
};
"""
            + _PURGE_LANCEE
        )
        self.assertIn("--warn", res["classe"], f"purge partielle affichee en {res['classe']!r}")
        self.assertNotIn("--ok", res["classe"])
        self.assertIn("299", res["texte"], "le travail reellement fait n'est plus dit")
        self.assertIn("1 échec", res["texte"], "l'echec residuel est passe sous silence")

    def test_une_purge_REUSSIE_reste_verte(self) -> None:
        """LE CONTRE-TEST. Sans lui, afficher une erreur en toute circonstance
        satisferait les deux tests ci-dessus."""
        res = self._run(
            _PURGE_CLIQUEE
            + r"""
globalThis.__reponses["run/purge_quarantine_bucket_all"] = {
  data: { ok: true, deleted: 300, errors: 0, bytes_freed: 1048576, considered: 300 },
};
"""
            + _PURGE_LANCEE
        )
        self.assertIn("--ok", res["classe"])
        self.assertNotIn("--error", res["classe"])
        self.assertNotIn("--warn", res["classe"])


# LE CLIQUET QUE J'AVAIS ECRIT ICI A ETE SUPPRIME, ET C'EST LA CI QUI L'A TRANCHE.
# Ce correctif a d'abord ete ecrit avec `parametres-test-result--avertissement`,
# qui n'existe pas : le message serait parti sans couleur, et les trois tests
# ci-dessus seraient restes VERTS, puisqu'ils lisent le NOM de la classe et non
# sa definition. J'en avais conclu qu'aucun test du depot ne voyait cette
# famille, et j'avais ajoute un cliquet.
#
# C'etait faux. `tests/test_contract_css.py` garde cet invariant depuis la verif
# totale de 2026-07, avec une extraction plus large (class=, cls:, querySelector,
# closest, matches) et une baseline qui ne peut que RETRECIR. Verifie par
# mutation sur ce fichier meme : remettre `--avertissement` le fait rougir en
# nommant la classe. Un second cliquet, plus faible, n'aurait ajoute que du bruit.


if __name__ == "__main__":
    unittest.main()
