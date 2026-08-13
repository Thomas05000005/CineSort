"""Le builder de regles doit parler la langue du backend, et ne rien inventer.

LES REGLES MODIFIENT REELLEMENT SCORE ET TIER, et elles etaient INCREABLES
depuis l'application : `save_quality_profile` est l'unique chemin d'ecriture, et
l'interface passait par `settings/save_profile`, qui ne transmet ni regles ni
toggles. Meme classe de defaut que les verrous de champs de la vague B1 — une
capacite complete cote backend, sans aucune porte d'entree.

CE QUE CES TESTS EPROUVENT EN PRIORITE : que RIEN du vocabulaire n'est ecrit
dans le front. Mesure du catalogue reel — 20 champs, 11 operateurs, 7 actions —
et c'est le backend qui les rend. La vague D1 a montre ce que coute l'inverse :
six poids ecrits dans le JS decrivaient un modele que le scoring ne lisait pas,
et bouger leurs curseurs remettait les vrais poids aux valeurs d'usine.

LA VALIDATION EST CELLE DU BACKEND. Il rend des erreurs numerotees par regle
(« Regle 1: au moins une condition requise ») ; les reimplementer dans le front
donnerait deux verites qui divergent — exactement le defaut de cette campagne.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

REGLES_JS = ROOT / "web" / "dashboard" / "components" / "regles-qualite.js"

_STUBS = r"""
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById() { return null; }, querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() { return { style: {}, click() {}, setAttribute() {}, appendChild() {} }; },
  body: { appendChild() {}, removeChild() {} },
};
globalThis.setTimeout = (fn) => { try { fn(); } catch (e) { /* no-op */ } return 0; };

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
globalThis.__modales = [];
function showModal(o) { globalThis.__modales.push(o); }
function closeModal() {}
globalThis.__confirmations = [];
globalThis.__accepte = true;
// FIDELE A LA PRODUCTION : ni `async`, ni valeur de retour — des RAPPELS.
function dangerConfirmModal(o) {
  globalThis.__confirmations.push(o);
  if (globalThis.__accepte === false) { if (o.onCancel) o.onCancel(); return; }
  globalThis.__enCours = o.onConfirm ? o.onConfirm() : null;
}
globalThis.__toasts = [];
function showToast(o) { globalThis.__toasts.push(o); }
"""

_EXTRA = "export const __t = __test;\nexport const __ouvrir = ouvrirReglesQualite;\n"
_EXIT = "\nprocess.exit(0);\n"

#: Le catalogue REEL, mesure sur `get_custom_rules_catalog`.
_CATALOGUE = r"""
globalThis.__reponses["quality/get_custom_rules_catalog"] = {
  ok: true,
  fields: ["video_codec", "audio_codec", "resolution", "resolution_rank", "year",
           "bitrate_kbps", "has_hdr10", "has_dv", "subtitle_langs", "warning_flags",
           "tier_before", "score_before", "file_size_gb", "tmdb_in_collection"],
  operators: ["=", "!=", "<", "<=", ">", ">=", "between", "in", "not_in", "contains", "not_contains"],
  actions: ["score_delta", "score_multiplier", "force_score", "force_tier", "cap_max", "cap_min", "flag_warning"],
};
globalThis.__reponses["quality/get_custom_rules_templates"] = {
  ok: true,
  templates: [
    { id: "trash_like", name: "TRaSH-like (equilibre)", description: "Penalise les codecs obsoletes.",
      rules: [{ id: "trash_xvid", name: "Penaliser codecs obsoletes", enabled: true, priority: 10,
                conditions: [{ field: "video_codec", op: "in", value: ["xvid", "divx"] }],
                match: "all", action: { type: "score_delta", value: -15, reason: "Codec obsolete" } }] },
    { id: "puriste", name: "Puriste", description: "Exigeant.", rules: [] },
  ],
};
"""


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(REGLES_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)


class UneReponsePERIMEENEcritRienTests(_Base):
    def test_une_reponse_PERIMEE_n_ecrit_ni_l_etat_ni_l_ecran(self) -> None:
        """LES TROIS MODALES DE LA VAGUE D PARTAGENT UN CONTENEUR UNIQUE :
        `showModal` commence par `closeModal()`. Une reponse arrivee apres qu'une
        autre generation a pris la main ne doit RIEN ecrire — ni l'etat, sur
        lequel agissent les boutons, ni la modale, qu'elle rouvrirait par-dessus
        celle que l'utilisateur regarde.

        ICI L'ENJEU N'EST PAS LE REPEINT : `_etat.regles` et `_etat.brouillon`
        portent le travail EN COURS de l'utilisateur. Une reponse tardive les
        reinitialisait sous lui — sans meme repeindre, donc sans qu'il le voie —
        et « Enregistrer » ecrivait alors ce qu'il n'avait pas saisi.
        """
        res = self._run(
            _CATALOGUE
            + r"""
globalThis.__reponses["quality/get_quality_profile"] = {
  ok: true, profile_json: { id: "P", weights: {}, tiers: {}, custom_rules: [] },
};
let debloquer;
const catalogue = globalThis.__reponses["quality/get_custom_rules_catalog"];
globalThis.__reponses["quality/get_custom_rules_catalog"] = new Promise((r) => { debloquer = r; });
const enVol = M.__t._charger();          // generation 1 : reste en vol

globalThis.__reponses["quality/get_custom_rules_catalog"] = catalogue;
globalThis.__reponses["quality/get_quality_profile"] = {
  ok: true,
  profile_json: { id: "P", weights: {}, tiers: {},
                  custom_rules: [{ id: "deja", name: "Regle deja la", enabled: true, priority: 1,
                                   conditions: [], match: "all",
                                   action: { type: "score_delta", value: -5 } }] },
};
await M.__t._charger();                  // generation 2 : terminee
// L'utilisateur ajoute une regle et commence a en saisir une autre.
M.__t._etat.regles.push({ id: "sienne", name: "Sa regle a lui", enabled: true, priority: 2,
                          conditions: [], match: "all", action: { type: "score_delta", value: 3 } });
M.__t._etat.brouillon.name = "saisie en cours";

debloquer(catalogue);                    // la generation 1 arrive TROP TARD
await enVol;
__emit({
  regles: M.__t._etat.regles.map((r) => r.id),
  brouillon: M.__t._etat.brouillon.name,
});
"""
        )
        self.assertEqual(
            res["regles"],
            ["deja", "sienne"],
            "une reponse perimee a reinitialise les regles : le travail de l'utilisateur est perdu",
        )
        self.assertEqual(res["brouillon"], "saisie en cours", "la saisie en cours a ete effacee")


class LeVocabulaireVientDuBACKENDTests(_Base):
    """Aucun champ, aucun operateur, aucune action n'est ecrit dans le front."""

    def test_le_catalogue_est_DEMANDE_pas_ecrit(self) -> None:
        res = self._run(
            _CATALOGUE + "await M.__t._charger();\n__emit({ routes: globalThis.__appels.map((a) => a.route).sort() });"
        )

        self.assertEqual(
            res["routes"],
            [
                "quality/get_custom_rules_catalog",
                "quality/get_custom_rules_templates",
                "quality/get_quality_profile",
            ],
            "le builder n'interroge pas le catalogue, ou ne lit pas les regles DEJA dans le profil",
        )

    def test_les_champs_du_backend_apparaissent_dans_le_formulaire(self) -> None:
        res = self._run(_CATALOGUE + "await M.__t._charger();\n__emit({ html: M.__t._corps() });")

        for attendu in ("video_codec", "tmdb_in_collection", "not_contains", "score_multiplier", "flag_warning"):
            self.assertIn(attendu, res["html"], f"« {attendu} » vient du backend et n'est pas propose")

    def test_le_module_n_ecrit_AUCUN_champ_en_dur(self) -> None:
        """Le brouillon vierge prend ses valeurs du catalogue CHARGE.

        Sans catalogue, il ne doit rien inventer : proposer un champ qui n'existe
        pas cote backend produirait une regle rejetee que l'utilisateur ne
        saurait pas corriger.
        """
        res = self._run("M.__t._etat.catalogue = null;\n__emit({ vierge: M.__t._brouillonVierge() });")

        self.assertEqual(res["vierge"]["conditions"][0]["field"], "")
        self.assertEqual(res["vierge"]["action"]["type"], "")

    def test_un_catalogue_ILLISIBLE_bloque_l_edition_et_le_DIT(self) -> None:
        """Editer sans vocabulaire produirait des regles invalides en silence."""
        res = self._run(
            'globalThis.__reponses["quality/get_custom_rules_catalog"] = { ok: false, user_message: "Store indisponible." };\n'
            "await M.__t._charger();\n__emit({ html: M.__t._corps(), catalogue: M.__t._etat.catalogue });"
        )

        self.assertIn("Store indisponible.", res["html"])
        self.assertIn('role="alert"', res["html"])
        self.assertIsNone(res["catalogue"])


class LaVALIDATIONEstCELLEDuBackendTests(_Base):
    def test_les_erreurs_du_backend_sont_affichees_TELLES_QUELLES(self) -> None:
        res = self._run(
            _CATALOGUE
            + r"""
await M.__t._charger();
globalThis.__reponses["quality/validate_custom_rules"] = {
  ok: false, errors: ["Regle 1: au moins une condition requise", "Regle 1: action manquante"], normalized: [],
};
await M.__t._ajouterLaRegle();
__emit({ html: M.__t._corps(), regles: M.__t._etat.regles.length });
"""
        )
        self.assertIn("Regle 1: au moins une condition requise", res["html"])
        self.assertIn("Regle 1: action manquante", res["html"])
        self.assertEqual(res["regles"], 0, "une regle invalide a ete ajoutee a la liste")

    def test_une_regle_VALIDE_est_ajoutee_sous_sa_forme_NORMALISEE(self) -> None:
        """Le backend normalise : garder la forme brute ferait diverger l'ecran
        de ce qui sera enregistre."""
        res = self._run(
            _CATALOGUE
            + r"""
await M.__t._charger();
globalThis.__reponses["quality/validate_custom_rules"] = {
  ok: true, errors: [],
  normalized: [{ id: "r1", name: "Ma regle", enabled: true, priority: 10,
                 conditions: [{ field: "video_codec", op: "=", value: "hevc" }],
                 match: "all", action: { type: "score_delta", value: 5 } }],
};
M.__t._etat.brouillon.name = "Ma regle";
await M.__t._ajouterLaRegle();
__emit({ regles: M.__t._etat.regles, erreurs: M.__t._etat.erreurs });
"""
        )
        self.assertEqual(len(res["regles"]), 1)
        self.assertEqual(res["regles"][0]["id"], "r1", "la forme normalisee du backend n'a pas ete retenue")
        self.assertEqual(res["erreurs"], [])

    def test_l_operande_d_un_IN_est_une_LISTE_pas_une_chaine(self) -> None:
        """`between` et `in` n'attendent pas un scalaire. Envoyer « xvid, divx »
        comme une seule chaine produirait une regle qui ne matche jamais."""
        res = self._run(
            "__emit({ liste: M.__t._valeurSaisie(' xvid , divx ', 'liste'),"
            " scalaire: M.__t._valeurSaisie(' hevc ', 'scalaire'),"
            " formeIn: M.__t._formeDeLOperande('in'),"
            " formeEgal: M.__t._formeDeLOperande('=') });"
        )

        self.assertEqual(res["liste"], ["xvid", "divx"])
        self.assertEqual(res["scalaire"], "hevc")
        self.assertEqual(res["formeIn"], "liste")
        self.assertEqual(res["formeEgal"], "scalaire")


class AppliquerUnMODELEEstDestructifTests(_Base):
    """Remplacer n'est pas ajouter : les regles courantes disparaissent."""

    def test_sur_une_liste_VIDE_aucune_confirmation_n_est_demandee(self) -> None:
        """Une confirmation sur une action sans perte devient un reflexe."""
        res = self._run(
            _CATALOGUE + "await M.__t._charger();\nM.__t._etat.regles = [];\nM.__t._appliquerLeModele('trash_like');\n"
            "__emit({ confirmations: globalThis.__confirmations.length, regles: M.__t._etat.regles.length });"
        )

        self.assertEqual(res["confirmations"], 0)
        self.assertEqual(res["regles"], 1)

    def test_sur_une_liste_NON_VIDE_la_perte_est_annoncee(self) -> None:
        res = self._run(
            _CATALOGUE
            + r"""
await M.__t._charger();
M.__t._etat.regles = [{ name: "La mienne", enabled: true }];
globalThis.__accepte = false;
M.__t._appliquerLeModele("trash_like");
const c = globalThis.__confirmations[0];
__emit({ items: c.items, consequence: c.consequence, regles: M.__t._etat.regles.length });
"""
        )
        self.assertEqual(res["items"], ["La mienne"], "la liste des regles perdues n'est pas annoncee")
        self.assertIn("REMPLAC", res["consequence"])
        self.assertIn("rien n'est écrit", res["consequence"].lower())
        self.assertEqual(res["regles"], 1, "les regles ont ete remplacees malgre le refus")

    def test_un_modele_INCONNU_ne_touche_a_rien(self) -> None:
        res = self._run(
            _CATALOGUE + "await M.__t._charger();\nM.__t._etat.regles = [{ name: 'A' }];\n"
            "M.__t._appliquerLeModele('__proto__');\nM.__t._appliquerLeModele('inexistant');\n"
            "__emit({ regles: M.__t._etat.regles.length, confirmations: globalThis.__confirmations.length });"
        )

        self.assertEqual(res["regles"], 1)
        self.assertEqual(res["confirmations"], 0)


class LEnregistrementPasseParLeSEULCheminDEcritureTests(_Base):
    def test_il_greffe_les_regles_sur_le_profil_EXISTANT(self) -> None:
        """Ecrire un profil neuf effacerait seuils, poids et toggles."""
        res = self._run(
            _CATALOGUE
            + r"""
await M.__t._charger();
M.__t._etat.regles = [{ id: "r1", name: "X" }];
globalThis.__reponses["quality/validate_custom_rules"] = { ok: true, errors: [], normalized: [{ id: "r1", name: "X" }] };
globalThis.__reponses["quality/get_quality_profile"] = {
  ok: true, profile_json: { id: "MonProfil", weights: { video: 70, audio: 20, extras: 10 }, tiers: { platinum: 70 } },
};
await M.__t._enregistrer();
const ecriture = globalThis.__appels.filter((a) => a.route === "quality/save_quality_profile")[0];
__emit({ envoye: ecriture ? ecriture.params.profile_json : null });
"""
        )
        envoye = res["envoye"]
        self.assertIsNotNone(envoye, "aucune ecriture n'a eu lieu")
        self.assertEqual(envoye["weights"], {"video": 70, "audio": 20, "extras": 10}, "les poids ont ete perdus")
        self.assertEqual(envoye["tiers"], {"platinum": 70}, "les seuils ont ete perdus")
        self.assertEqual(envoye["custom_rules"], [{"id": "r1", "name": "X"}])

    def test_un_profil_ILLISIBLE_n_ecrit_RIEN(self) -> None:
        """Sans profil de base, ecrire reviendrait a en inventer un."""
        res = self._run(
            _CATALOGUE
            + r"""
await M.__t._charger();
M.__t._etat.regles = [{ id: "r1" }];
globalThis.__reponses["quality/validate_custom_rules"] = { ok: true, errors: [], normalized: [{ id: "r1" }] };
globalThis.__reponses["quality/get_quality_profile"] = { ok: false, user_message: "Base verrouillee." };
await M.__t._enregistrer();
__emit({ ecritures: globalThis.__appels.filter((a) => a.route === "quality/save_quality_profile").length,
         toasts: globalThis.__toasts.map((t) => t.type) });
"""
        )
        self.assertEqual(res["ecritures"], 0, "un profil a ete ecrit alors qu'aucun n'a pu etre lu")
        self.assertIn("error", res["toasts"])

    def test_des_regles_INVALIDES_n_ecrivent_RIEN(self) -> None:
        res = self._run(
            _CATALOGUE
            + r"""
await M.__t._charger();
M.__t._etat.regles = [{ id: "r1" }];
globalThis.__reponses["quality/validate_custom_rules"] = { ok: false, errors: ["Regle 1: action manquante"], normalized: [] };
await M.__t._enregistrer();
__emit({ ecritures: globalThis.__appels.filter((a) => a.route === "quality/save_quality_profile").length,
         html: M.__t._corps() });
"""
        )
        self.assertEqual(res["ecritures"], 0)
        self.assertIn("Regle 1: action manquante", res["html"])


class UneRegleSeLitCommeUnePHRASETests(_Base):
    def test_le_rendu_nomme_le_champ_l_operateur_et_la_valeur(self) -> None:
        res = self._run(
            r"""
__emit({ html: M.__t._rendreRegle({
  name: "Penaliser CAM", enabled: true, priority: 30, match: "any",
  conditions: [{ field: "warning_flags", op: "contains", value: "cam" }],
  action: { type: "force_tier", value: "Reject", reason: "Source CAM" },
}, 0) });
"""
        )
        html = res["html"]
        self.assertIn("Penaliser CAM", html)
        self.assertIn("warning_flags contains cam", html)
        self.assertIn("force_tier Reject", html)
        self.assertIn("Source CAM", html)
        self.assertIn("au moins une", html, "la liaison entre conditions n'est pas dite")
        self.assertIn("prio 30", html)

    def test_une_regle_DESACTIVEE_reste_lisible_et_se_voit(self) -> None:
        res = self._run(
            '__emit({ actif: M.__t._rendreRegle({ name: "A", enabled: true, conditions: [], action: {} }, 0),'
            ' inactif: M.__t._rendreRegle({ name: "A", enabled: false, conditions: [], action: {} }, 0) });'
        )

        self.assertIn("regle--inactive", res["inactif"])
        self.assertNotIn("regle--inactive", res["actif"])
        self.assertIn("A", res["inactif"], "une regle desactivee doit rester relisible")


if __name__ == "__main__":
    unittest.main()
