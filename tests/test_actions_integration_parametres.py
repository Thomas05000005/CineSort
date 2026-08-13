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
#:   settings.reset_all_user_data    exige que l'utilisateur TAPE « RESET » ;
#:                                   `dangerConfirmModal` n'a pas d'affordance de
#:                                   saisie
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
)

_STUBS = r"""
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById() { return null; }, querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() { return { style: {}, classList: { add() {}, remove() {} }, appendChild() {} }; },
  body: { appendChild() {}, classList: { add() {}, remove() {} } },
};

globalThis.__appels = [];
globalThis.__reponses = {};

function apiPost(route, params) {
  globalThis.__appels.push({ route, params });
  const r = globalThis.__reponses[route];
  return Promise.resolve(r === undefined ? { ok: true } : r);
}
function invalidateSettingsCache() {}
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
  // La vraie modale attend la resolution de `onConfirm` avant de se fermer ; on
  // expose la promesse pour que le test puisse en faire autant.
  globalThis.__enCours = o.onConfirm ? o.onConfirm() : null;
}
function t(k) { return String(k); }
function formatBytes() { return ""; }
function registerRoute() {}
function navigate() {}
const rightPanel = { setWidth() {}, setExpanded() {}, setContent() {} };
"""

_EXTRA = (
    "export const __ACTIONS = ACTIONS_DE_SECTION;\n"
    "export const __rendreSectionActions = _renderSectionActions;\n"
    "export const __lancer = _lancerActionDeSection;\n"
    "export const __rendreReponse = _rendreReponseAction;\n"
)

_EXIT = "\nprocess.exit(0);\n"

#: Un bouton et sa section, tels que le DOM les porterait. Le `closest` remonte
#: a la section, qui expose la zone de sortie : c'est ce chemin-la qui casse si
#: le rendu et le gestionnaire divergent.
_FAUX_DOM = r"""
function fauxBouton(route) {
  const sortie = { textContent: "", className: "" };
  const section = { querySelector: () => sortie };
  const btn = {
    dataset: { sectionAction: route },
    disabled: false,
    closest: () => section,
  };
  return { btn, sortie };
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


if __name__ == "__main__":
    unittest.main()
