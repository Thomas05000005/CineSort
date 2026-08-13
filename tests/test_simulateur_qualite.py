"""Le simulateur doit rendre les chiffres du backend, et ne rien ecrire.

L'INTERFACE ORDONNAIT DEJA DE S'EN SERVIR SANS L'OFFRIR. `parametres.js`
avertit, a propos de la hierarchie qualite : « Activer ce mode peut redistribuer
30-40 % de votre bibliotheque actuelle — utilisez la simulation avant
d'activer. » `quality/simulate_quality_preset` existait, testee, et aucun code du
dashboard ne l'appelait.

LE PIEGE PRINCIPAL DE CET ECRAN, RELEVE AVANT D'ECRIRE UNE LIGNE DE VUE :
`_count_tiers` (backend) rend ses cles CAPITALISEES — « Platinum », « Gold »… —
la ou les classes CSS et le reste de l'application sont en minuscules. Lire
`tiers.platinum` sur cette reponse rendrait `undefined` pour chaque niveau, et
l'ecran afficherait cinq zeros SANS JAMAIS ECHOUER. C'est exactement la forme du
defaut `group_name` de la vague C : une cle qui ne correspond a rien n'echoue
pas, elle affiche du vide.

LE SECOND : `warnings`. Le backend a une raison precise a donner (« ce preset
modifie peu votre bibliotheque ») ; sans elle, deux colonnes presque identiques
laissent l'utilisateur conclure seul.

RIEN N'EST ECRIT tant qu'on ne demande pas l'enregistrement. C'est ce qui permet
d'ouvrir cet ecran sans confirmation, et c'est verifie ici.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

SIMU_JS = ROOT / "web" / "dashboard" / "components" / "simulateur-qualite.js"

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
// FIDELE AU CONTENEUR PARTAGE. `showModal` retient QUI possede la modale et
// `closeModal` le relache : c'est exactement ce que fait `modal.js`. Un stub qui
// s'en ecarterait rendrait le jeton de peremption intestable — or c'est
// precisement ce jeton qu'on eprouve ici.
globalThis.__proprietaire = "";
function showModal(o) {
  globalThis.__modales.push(o);
  globalThis.__proprietaire = String((o && o.proprietaire) || "");
}
function closeModal() { globalThis.__proprietaire = ""; }
function modaleCourante() { return globalThis.__proprietaire; }
// Exposees au PILOTE : les stubs vivent dans la portee du module, et un test qui
// veut simuler « l'utilisateur ferme, puis ouvre une autre modale » doit pouvoir
// les appeler de l'exterieur.
globalThis.showModal = showModal;
globalThis.closeModal = closeModal;
globalThis.modaleCourante = modaleCourante;
globalThis.__toasts = [];
function showToast(o) { globalThis.__toasts.push(o); }
"""

_EXTRA = "export const __t = __test;\nexport const __ouvrir = ouvrirSimulateurQualite;\n"
_EXIT = "\nprocess.exit(0);\n"

#: Une reponse REALISTE : tiers CAPITALISES, comme `_count_tiers` les rend.
_REPONSE = r"""
globalThis.__reponses["quality/simulate_quality_preset"] = {
  ok: true,
  preset_id: "remux_strict", preset_label: "Remux strict", scope: "run",
  films_count: 1284, elapsed_ms: 812,
  before: { avg_score: 64.2, profile_name: "Actuel",
            tiers: { Platinum: 142, Gold: 387, Silver: 512, Bronze: 150, Reject: 93 } },
  after:  { avg_score: 71.5, profile_name: "Remux strict",
            tiers: { Platinum: 198, Gold: 402, Silver: 498, Bronze: 145, Reject: 41 } },
  delta: { avg_score_delta: 7.3, net_tier_improvement: 218,
           net_tier_degradation: 43, unchanged_count: 1023 },
  top_winners: [{ title: "Heat", year: 1995, score_before: 62, score_after: 88, delta: 26 }],
  top_losers: [{ title: "Alien 3", year: 1992, score_before: 79, score_after: 54, delta: -25 }],
  warnings: ["Ce preset modifie peu votre bibliotheque."],
};
"""


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(SIMU_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)


class UneAUTREModaleMePERIMETests(_Base):
    """LES TROIS MODALES PARTAGENT UN CONTENEUR UNIQUE, ET LE JETON L'IGNORAIT.

    `showModal` commence par `closeModal()` : ouvrir les regles DETRUIT la modale
    du simulateur. Mais le jeton de generation etait declare DANS chaque module
    (`let _generation = 0`, trois fois) : pour le simulateur, sa propre reponse en
    vol restait « courante », elle appelait `_reouvrir()` — donc `showModal` — et
    detruisait la modale que l'utilisateur venait d'ouvrir, brouillon compris.

    Le compteur ne detectait pas non plus la FERMETURE : ni `closeModal`, ni le
    bouton « Fermer », ni Echap n'incrementaient quoi que ce soit, alors que le
    commentaire de tete du jeton affirmait le contraire.

    La question a poser n'est pas « ma requete est-elle la plus recente ? » mais
    « suis-je encore la modale a l'ecran ? », et elle ne se repond que dans
    `modal.js`, ou vit le conteneur partage.
    """

    def test_une_autre_modale_ouverte_PERIME_ma_reponse_en_vol(self) -> None:
        res = self._run(
            r"""
let debloquer;
globalThis.__reponses["quality/simulate_quality_preset"] = new Promise((r) => { debloquer = r; });
const enVol = M.__t._simuler();          // ma modale s'ouvre, ma requete part

// L'utilisateur ferme et ouvre une AUTRE modale : le conteneur change de main.
closeModal();
showModal({ proprietaire: "regles", title: "Regles", body: "", actions: [] });
const modalesAvant = globalThis.__modales.length;

debloquer({ ok: true, preset_id: "A", films_count: 1,
            before: { avg_score: 1, tiers: {} }, after: { avg_score: 2, tiers: {} },
            delta: {}, top_winners: [], top_losers: [], warnings: [] });
await enVol;
__emit({
  modalesEnPlus: globalThis.__modales.length - modalesAvant,
  proprietaire: modaleCourante(),
  resultat: !!M.__t._etat.resultat,
});
"""
        )
        self.assertEqual(
            res["modalesEnPlus"],
            0,
            "ma reponse en vol a ROUVERT ma modale par-dessus celle de l'autre module",
        )
        self.assertEqual(res["proprietaire"], "regles", "la modale de l'autre module a ete detruite")
        self.assertFalse(res["resultat"], "une reponse perimee a quand meme ecrit l'etat")

    def test_une_FERMETURE_simple_perime_aussi(self) -> None:
        """Echap ou « Fermer » : le compteur seul ne les voyait pas."""
        res = self._run(
            r"""
let debloquer;
globalThis.__reponses["quality/simulate_quality_preset"] = new Promise((r) => { debloquer = r; });
const enVol = M.__t._simuler();
closeModal();                            // l'utilisateur ferme
const modalesAvant = globalThis.__modales.length;
debloquer({ ok: true, preset_id: "A", films_count: 1,
            before: { avg_score: 1, tiers: {} }, after: { avg_score: 2, tiers: {} },
            delta: {}, top_winners: [], top_losers: [], warnings: [] });
await enVol;
__emit({ modalesEnPlus: globalThis.__modales.length - modalesAvant, resultat: !!M.__t._etat.resultat });
"""
        )
        self.assertEqual(res["modalesEnPlus"], 0, "une modale FERMEE s'est rouverte toute seule")
        self.assertFalse(res["resultat"], "une reponse arrivee apres la fermeture a ecrit l'etat")


class UneReponsePERIMEENEcritRienTests(_Base):
    def test_une_reponse_PERIMEE_n_ecrit_ni_l_etat_ni_l_ecran(self) -> None:
        """LES TROIS MODALES DE LA VAGUE D PARTAGENT UN CONTENEUR UNIQUE :
        `showModal` commence par `closeModal()`. Une reponse arrivee apres qu'une
        autre generation a pris la main ne doit RIEN ecrire — ni l'etat, sur
        lequel agissent les boutons, ni la modale, qu'elle rouvrirait par-dessus
        celle que l'utilisateur regarde."""
        res = self._run(
            r"""
let debloquer;
globalThis.__reponses["quality/simulate_quality_preset"] = new Promise((r) => { debloquer = r; });
const enVol = M.__t._simuler();          // generation 1 : preset A, reste en vol

globalThis.__reponses["quality/simulate_quality_preset"] = {
  ok: true, preset_id: "B", films_count: 222,
  before: { avg_score: 1, tiers: {} }, after: { avg_score: 2, tiers: {} },
  delta: {}, top_winners: [], top_losers: [], warnings: [],
};
await M.__t._simuler();                  // generation 2 : preset B, terminee
const modalesApresG2 = globalThis.__modales.length;

debloquer({                              // le preset A arrive TROP TARD
  ok: true, preset_id: "A", films_count: 999,
  before: { avg_score: 9, tiers: {} }, after: { avg_score: 9, tiers: {} },
  delta: {}, top_winners: [], top_losers: [], warnings: [],
});
await enVol;
__emit({
  preset: M.__t._etat.resultat && M.__t._etat.resultat.preset_id,
  films: M.__t._etat.resultat && M.__t._etat.resultat.films_count,
  modalesEnPlus: globalThis.__modales.length - modalesApresG2,
});
"""
        )
        self.assertEqual(res["preset"], "B", "l'ecran garde le resultat d'une simulation ABANDONNEE")
        self.assertEqual(res["films"], 222, "« Enregistrer ce preset » figerait des chiffres perimes")
        self.assertEqual(res["modalesEnPlus"], 0, "une reponse perimee a ROUVERT une modale")


class LesTiersCAPITALISESSontNormalisesTests(_Base):
    """LE piege de cet ecran, et il n'echoue pas tout seul."""

    def test_les_cles_capitalisees_du_backend_sont_lues(self) -> None:
        res = self._run(
            "__emit({ n: M.__t._normaliserTiers({ Platinum: 5, Gold: 3, Silver: 0, Bronze: 1, Reject: 2 }) });"
        )

        self.assertEqual(res["n"], {"platinum": 5, "gold": 3, "silver": 0, "bronze": 1, "reject": 2})

    def test_les_comptes_apparaissent_dans_le_tableau(self) -> None:
        """La normalisation ne sert a rien si le rendu ne s'en sert pas."""
        res = self._run(
            _REPONSE
            + "__emit({ html: M.__t._rendreResultat(globalThis.__reponses['quality/simulate_quality_preset']) });"
        )

        for attendu in ("142", "198", "512", "498", "41"):
            self.assertIn(attendu, res["html"], f"le compte « {attendu} » n'apparait pas")
        self.assertNotIn(">0<", res["html"].replace(">0</td>", ""), "des niveaux se sont affiches a zero")

    def test_une_forme_INATTENDUE_ne_fait_pas_lever(self) -> None:
        for charge in ("null", "undefined", "{}", "{ inconnu: 4 }", '"texte"'):
            with self.subTest(charge=charge):
                res = self._run(f"__emit({{ n: M.__t._normaliserTiers({charge}) }});")
                self.assertEqual(set(res["n"]), {"platinum", "gold", "silver", "bronze", "reject"})


class LEcranRENDLesChiffresDuBackendTests(_Base):
    def test_le_score_moyen_et_son_delta(self) -> None:
        res = self._run(
            _REPONSE
            + "__emit({ html: M.__t._rendreResultat(globalThis.__reponses['quality/simulate_quality_preset']) });"
        )

        self.assertIn("64,2", res["html"])
        self.assertIn("71,5", res["html"])
        self.assertIn("+7,3", res["html"], "le delta du score moyen n'est pas affiche avec son signe")

    def test_le_compte_de_films_et_le_temps_de_calcul(self) -> None:
        res = self._run(
            _REPONSE
            + "__emit({ html: M.__t._rendreResultat(globalThis.__reponses['quality/simulate_quality_preset']) });"
        )

        self.assertIn("284", res["html"])
        self.assertIn("0,8", res["html"], "le temps de calcul n'est pas rendu en secondes")

    def test_les_AVERTISSEMENTS_du_backend_sont_affiches(self) -> None:
        """Sans eux, deux colonnes presque identiques laissent conclure seul."""
        res = self._run(
            _REPONSE
            + "__emit({ html: M.__t._rendreResultat(globalThis.__reponses['quality/simulate_quality_preset']) });"
        )

        self.assertIn("modifie peu votre bibliotheque", res["html"])

    def test_les_films_qui_montent_et_ceux_qui_descendent(self) -> None:
        res = self._run(
            _REPONSE
            + "__emit({ html: M.__t._rendreResultat(globalThis.__reponses['quality/simulate_quality_preset']) });"
        )

        self.assertIn("Heat", res["html"])
        self.assertIn("+26", res["html"])
        self.assertIn("Alien 3", res["html"])
        self.assertIn("−25", res["html"], "une baisse doit se lire comme une baisse")

    def test_le_signe_distingue_les_trois_cas(self) -> None:
        res = self._run("__emit({ p: M.__t._signe(7.3), n: M.__t._signe(-5), z: M.__t._signe(0) });")

        self.assertEqual([res["p"], res["n"], res["z"]], ["+7,3", "−5", "0"])


class LaSIMULATIONNEcritRIENTests(_Base):
    """C'est ce qui permet d'ouvrir cet ecran sans confirmation."""

    def test_ouvrir_le_simulateur_n_appelle_AUCUNE_route(self) -> None:
        res = self._run(
            "M.__ouvrir();\n__emit({ appels: globalThis.__appels.length, modales: globalThis.__modales.length });"
        )

        self.assertEqual(res["appels"], 0, "l'ouverture declenche un appel : ce n'est plus une lecture inerte")
        self.assertEqual(res["modales"], 1)

    def test_simuler_n_appelle_QUE_la_simulation(self) -> None:
        res = self._run(
            _REPONSE + "await M.__t._simuler();\n__emit({ routes: globalThis.__appels.map((a) => a.route) });"
        )

        self.assertEqual(res["routes"], ["quality/simulate_quality_preset"])

    def test_la_simulation_transmet_le_preset_ET_la_portee(self) -> None:
        res = self._run(
            _REPONSE
            + """
M.__t._etat.preset = "compact";
M.__t._etat.portee = "library";
await M.__t._simuler();
__emit({ params: globalThis.__appels[0].params });
"""
        )
        self.assertEqual(res["params"]["preset_id"], "compact")
        self.assertEqual(res["params"]["scope"], "library")

    def test_enregistrer_envoie_le_VRAI_profil_du_preset(self) -> None:
        """LE defaut que ce test aurait du attraper des le debut.

        La reponse de simulation ne porte AUCUNE cle `profile` — sa charge utile
        est `before`/`after`/`delta`/`top_winners`… (mesure sur
        `quality_simulator_support.py`). Une premiere version envoyait
        `_etat.resultat.profile || {}` : elle enregistrait donc un profil VIDE
        sous le nom du preset, sans jamais echouer. Aucun de mes tests ne
        regardait CE QUI EST ENVOYE.
        """
        res = self._run(
            _REPONSE
            + r"""
globalThis.__reponses["quality/get_quality_presets"] = {
  ok: true,
  presets: [{ preset_id: "remux_strict", profile_id: "CinemaLux_RemuxStrict_v1",
              profile_json: { id: "CinemaLux_RemuxStrict_v1", weights: { video: 66, audio: 30, extras: 4 } } }],
};
await M.__t._simuler();
await M.__t._enregistrer();
const e = globalThis.__appels.filter((a) => a.route === "quality/save_custom_quality_preset")[0];
__emit({ envoye: e ? e.params : null });
"""
        )
        env = res["envoye"]
        self.assertIsNotNone(env, "aucun enregistrement n'a eu lieu")
        self.assertEqual(env["name"], "Remux strict")
        self.assertEqual(
            env["profile_json"]["weights"],
            {"video": 66, "audio": 30, "extras": 4},
            "un profil VIDE a ete enregistre sous le nom du preset",
        )

    def test_un_preset_INTROUVABLE_n_enregistre_RIEN(self) -> None:
        res = self._run(
            _REPONSE
            + r"""
globalThis.__reponses["quality/get_quality_presets"] = { ok: true, presets: [] };
await M.__t._simuler();
await M.__t._enregistrer();
__emit({ ecritures: globalThis.__appels.filter((a) => a.route === "quality/save_custom_quality_preset").length,
         toasts: globalThis.__toasts.map((t) => t.type) });
"""
        )
        self.assertEqual(res["ecritures"], 0)
        self.assertIn("error", res["toasts"])

    def test_changer_de_preset_PERIME_le_resultat_affiche(self) -> None:
        """Sinon l'ecran montre les chiffres d'un preset sous le nom d'un autre,
        et « Enregistrer » porte sur celui qu'on ne regarde plus.

        CE TEST A ETE FAUX-VERT. Il REJOUAIT le gestionnaire (`_etat.preset = ...;
        _etat.resultat = null;`) au lieu de le declencher — son propre commentaire
        le disait : « on rejoue exactement ce que fait le gestionnaire de clic ».
        Il eprouvait donc la main du testeur, et serait reste vert si la
        delegation cessait de perimer le resultat. On passe par le VRAI ecouteur
        pose par `_brancher()`.
        """
        res = self._run(
            _REPONSE
            + r"""
let ecouteur = null;
const hote = { addEventListener(_type, fn) { ecouteur = fn; } };
globalThis.document.querySelector = (sel) => (sel === ".simu-vue" ? hote : null);

await M.__t._simuler();
const avant = !!M.__t._etat.resultat;
M.__t._brancher();

// Un clic REEL sur le choix de preset, tel que le DOM le livrerait.
const choix = { dataset: { simuPreset: "compact" }, closest() { return this; } };
ecouteur({ target: choix });

__emit({ avant, apres: !!M.__t._etat.resultat, preset: M.__t._etat.preset });
"""
        )
        self.assertTrue(res["avant"], "la simulation n'a rien produit : le test ne prouverait rien")
        self.assertEqual(res["preset"], "compact", "le clic n'a pas change de preset")
        self.assertFalse(res["apres"], "le resultat du preset PRECEDENT reste affiche sous le nouveau nom")

    def test_changer_de_PORTEE_perime_aussi_le_resultat(self) -> None:
        """Meme cause, meme consequence : « Ce run » et « Toute la bibliotheque »
        ne donnent pas les memes chiffres."""
        res = self._run(
            _REPONSE
            + r"""
let ecouteur = null;
const hote = { addEventListener(_type, fn) { ecouteur = fn; } };
globalThis.document.querySelector = (sel) => (sel === ".simu-vue" ? hote : null);

await M.__t._simuler();
const avant = !!M.__t._etat.resultat;
M.__t._brancher();
const choix = { dataset: { simuPortee: "library" }, closest() { return this; } };
ecouteur({ target: choix });

__emit({ avant, apres: !!M.__t._etat.resultat, portee: M.__t._etat.portee });
"""
        )
        self.assertTrue(res["avant"])
        self.assertEqual(res["portee"], "library", "le clic n'a pas change de portee")
        self.assertFalse(res["apres"], "les chiffres d'une autre portee restent affiches")

    def test_un_preset_INCONNU_ne_change_rien(self) -> None:
        """Le garde `PRESETS.some(...)` doit etre ATTEIGNABLE : sans lui, un
        attribut falsifie enverrait un `preset_id` que le backend ne connait pas."""
        res = self._run(
            _REPONSE
            + r"""
let ecouteur = null;
const hote = { addEventListener(_type, fn) { ecouteur = fn; } };
globalThis.document.querySelector = (sel) => (sel === ".simu-vue" ? hote : null);

await M.__t._simuler();
M.__t._brancher();
const choix = { dataset: { simuPreset: "n_existe_pas" }, closest() { return this; } };
ecouteur({ target: choix });

__emit({ preset: M.__t._etat.preset, resultat: !!M.__t._etat.resultat });
"""
        )
        self.assertNotEqual(res["preset"], "n_existe_pas", "un preset inconnu a ete accepte")
        self.assertTrue(res["resultat"], "un clic REFUSE a quand meme jete le resultat affiche")

    def test_enregistrer_SANS_simulation_n_ecrit_rien(self) -> None:
        """Un profil qu'on n'a pas vu a l'oeuvre est exactement ce que
        l'avertissement de l'interface demande d'eviter."""
        res = self._run(
            "M.__t._etat.resultat = null;\nawait M.__t._enregistrer();\n"
            "__emit({ appels: globalThis.__appels.length, toasts: globalThis.__toasts.map((t) => t.type) });"
        )

        self.assertEqual(res["appels"], 0, "un profil a ete enregistre sans qu'aucune simulation ne l'ait montre")
        self.assertIn("info", res["toasts"])


class UnECHECEstAFFICHEPasAvaleTests(_Base):
    def test_le_message_du_backend_apparait(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["quality/simulate_quality_preset"] = { ok: false, user_message: "Aucun run analysé." };
await M.__t._simuler();
__emit({ html: M.__t._corps(), resultat: M.__t._etat.resultat });
"""
        )
        self.assertIn("Aucun run analysé.", res["html"])
        self.assertIn('role="alert"', res["html"])
        self.assertIsNone(res["resultat"], "un resultat a ete conserve malgre l'echec")

    def test_un_echec_efface_le_resultat_PRECEDENT(self) -> None:
        """Sinon l'ecran garde un tableau perime a cote d'un message d'erreur."""
        res = self._run(
            _REPONSE
            + r"""
await M.__t._simuler();
globalThis.__reponses["quality/simulate_quality_preset"] = { ok: false, message: "boum" };
await M.__t._simuler();
__emit({ resultat: M.__t._etat.resultat });
"""
        )
        self.assertIsNone(res["resultat"])


if __name__ == "__main__":
    unittest.main()
