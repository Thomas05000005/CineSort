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
        """La forme d'un preset n'est pas supposee : chaine OU objet."""
        res = self._run(
            r"""
__emit({
  chaines: M.__rendreReponse({ rendu: "presets" }, { ok: true, presets: ["Simple", "Avec edition"] }),
  objets: M.__rendreReponse({ rendu: "presets" }, { ok: true, presets: [{ name: "Simple" }, { template: "{title}" }] }),
});
"""
        )
        self.assertIn("2 modèle(s)", res["chaines"])
        self.assertIn("Simple", res["objets"])

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
    pas exactement « RESET » (`reset_support.py:196`), et `dangerConfirmModal`
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
const { btn } = fauxBouton("settings/reset_all_user_data");
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
            r"""
globalThis.__saisie = "RESET";
const { btn } = fauxBouton("settings/reset_all_user_data");
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
const { btn } = fauxBouton("settings/reset_all_user_data");
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
const { btn } = fauxBouton("settings/reset_all_user_data");
M.__lancer(null, btn);
await new Promise((r) => setTimeout(r, 0));
__emit({ appels: globalThis.__appels.map((a) => a.route) });
"""
        )
        self.assertEqual(res["appels"], [], "l'action est partie malgre l'annulation")

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


if __name__ == "__main__":
    unittest.main()
