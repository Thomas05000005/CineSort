"""La vue Statistiques doit rendre les CHIFFRES du serveur, sans en inventer.

Trois analyses existaient cote backend, testees, et qu'AUCUN code du dashboard
n'appelait : `library/get_library_podiums`, `library/get_library_timeline`,
`library/get_scoring_rollup`. Leur CSS survivait pourtant dans la feuille de
style — signe d'une vue supprimee, pas de code mort.

CE QUE CE FICHIER EPROUVE. Un ecran d'analyse n'a que deux facons de trahir :
appeler la mauvaise route, ou deformer ce qu'on lui donne. Les deux sont
verifiees sur la VRAIE source (cf. `tests/_jsexec.py`).

LE PIEGE PARTICULIER A CET ECRAN : rendre une absence comme un zero. Un mois
sans film et un mois NON MESURE se ressemblent a l'ecran, et un score absent
n'est pas un score nul. Trois tests portent la-dessus, parce que c'est
exactement ce qu'un graphique fait dire a des donnees quand personne ne
regarde.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

STATS_JS = ROOT / "web" / "dashboard" / "views" / "statistiques.js"

_STUBS = r"""
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById() { return null; }, querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() { return { style: {}, classList: { add() {}, remove() {} } }; },
  body: { appendChild() {}, removeChild() {} },
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
globalThis.__toasts = [];
function showToast(o) { globalThis.__toasts.push(o); }
"""

_EXTRA = "export const __t = __test;\nexport const __init = initStatistiques;\nexport const __unmount = unmountStatistiques;\n"
_EXIT = "\nprocess.exit(0);\n"

#: Un hote minimal : le seul membre que la vue touche est `innerHTML`, plus
#: add/removeEventListener. On enregistre les ecouteurs pour pouvoir verifier
#: que le demontage les retire vraiment, ET on GARDE le rappel — sans lui, on ne
#: peut eprouver que l'etat interne de la vue, jamais ce qu'elle envoie.
_HOTE = r"""
function fauxHote() {
  return {
    innerHTML: "",
    ecouteurs: 0,
    rappel: null,
    addEventListener(_type, fn) { this.ecouteurs += 1; this.rappel = fn; },
    removeEventListener() { this.ecouteurs -= 1; this.rappel = null; },
  };
}

/** Declenche le VRAI gestionnaire de la vue sur un bouton porteur de `dataset`. */
function cliquer(hote, dataset) {
  const cible = { dataset, closest: () => cible };
  hote.rappel({ target: cible });
}
"""


class LesTroisROUTESSontCELLESAttenduesTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(STATS_JS, stubs=_STUBS, extra=_EXTRA, driver=_HOTE + driver + _EXIT, timeout=90)

    def test_l_onglet_par_defaut_charge_les_podiums(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["library/get_library_podiums"] = { ok: true, total_films: 3, release_groups: [] };
const h = fauxHote();
M.__init(h);
await new Promise((r) => setTimeout(r, 0));
__emit({ routes: globalThis.__appels.map((a) => a.route) });
"""
        )
        self.assertEqual(res["routes"], ["library/get_library_podiums"])

    def test_la_fenetre_de_mois_est_TRANSMISE(self) -> None:
        """Un selecteur qui n'envoie pas son choix affiche toujours la meme chose.

        CE TEST A DEJA ETE UN FAUX VERT. Sa premiere version posait
        `M.__t._state.mois = 24` puis assertait `_state.mois === 24` : elle
        verifiait que la valeur qu'elle venait d'ecrire etait celle qu'elle avait
        ecrite. Elle serait restee verte si la vue avait cesse d'envoyer `months`
        au backend — c'est-a-dire dans le seul cas qu'elle pretendait couvrir.
        Elle porte desormais sur le PARAMETRE REELLEMENT ENVOYE, en declenchant
        le vrai gestionnaire de clic.
        """
        res = self._run(
            r"""
globalThis.__reponses["library/get_library_podiums"] = { ok: true, release_groups: [] };
globalThis.__reponses["library/get_library_timeline"] = { ok: true, months: [] };
const h = fauxHote();
M.__init(h);
await new Promise((r) => setTimeout(r, 0));
globalThis.__appels.length = 0;
cliquer(h, { statsOnglet: "timeline" });
await new Promise((r) => setTimeout(r, 0));
cliquer(h, { statsMois: "24" });
await new Promise((r) => setTimeout(r, 0));
const t = globalThis.__appels.filter((a) => a.route === "library/get_library_timeline");
__emit({ dernier: t.length ? t[t.length - 1].params : null, nb: t.length });
"""
        )
        self.assertGreaterEqual(res["nb"], 1, "aucun appel a la chronologie n'a ete emis")
        self.assertEqual(
            res["dernier"],
            {"months": 24},
            "la fenetre choisie n'est pas transmise au backend : le selecteur est decoratif",
        )

    def test_la_DIMENSION_du_rollup_est_TRANSMISE(self) -> None:
        """Meme contrat pour l'autre selecteur de la vue."""
        res = self._run(
            r"""
globalThis.__reponses["library/get_library_podiums"] = { ok: true, release_groups: [] };
globalThis.__reponses["library/get_scoring_rollup"] = { ok: true, groups: [] };
const h = fauxHote();
M.__init(h);
await new Promise((r) => setTimeout(r, 0));
globalThis.__appels.length = 0;
cliquer(h, { statsDimension: "codec" });
await new Promise((r) => setTimeout(r, 0));
const t = globalThis.__appels.filter((a) => a.route === "library/get_scoring_rollup");
__emit({ dernier: t.length ? t[t.length - 1].params : null });
"""
        )
        self.assertEqual(res["dernier"], {"by": "codec"})


class UnOngletINCONNUNeDeclencheRienTests(unittest.TestCase):
    """L'id d'onglet vient du `dataset` d'un bouton, donc du DOM.

    Une recherche par cle NON STATIQUE sur un objet litteral traverse aussi son
    prototype : `_ROUTES["constructor"]` rend `Object`, qui est VRAI. Le garde
    `if (!fab) return;` laissait donc passer, et `fab()` s'executait. Le scenario
    est improbable — les trois ids sont ecrits par cette vue — mais le garde ne
    depend d'aucune supposition sur l'appelant, et c'est ce qui en fait un garde.
    """

    def setUp(self) -> None:
        require_node(self)

    def test_un_onglet_inconnu_ne_change_NI_l_etat_NI_l_ecran(self) -> None:
        """CE TEST A DEJA ETE UN FAUX VERT.

        Sa premiere version n'assertait que « aucune requete emise ». Or aucune
        requete n'etait emise NON PLUS sans le correctif : la vue partait en
        rejet de promesse avant d'appeler `apiPost`. Les deux mutations
        (retrait du garde, retrait du controle de type) la laissaient VERTE.

        Les grandeurs qui distinguent vraiment les deux mondes sont l'ETAT — un
        id inconnu ne doit pas devenir l'onglet courant, sinon l'ecran se vide —
        et l'absence de REJET NON TRAITE.
        """
        res = run_module_test(
            STATS_JS,
            stubs=_STUBS,
            extra=_EXTRA,
            driver=_HOTE
            + r"""
globalThis.__rejets = [];
process.on("unhandledRejection", (e) => { globalThis.__rejets.push(String((e && e.message) || e)); });
globalThis.__reponses["library/get_library_podiums"] = { ok: true, release_groups: [] };
const h = fauxHote();
M.__init(h);
await new Promise((r) => setTimeout(r, 0));
globalThis.__appels.length = 0;
for (const nom of ["constructor", "__proto__", "toString", "inconnu"]) {
  cliquer(h, { statsOnglet: nom });
  await new Promise((r) => setTimeout(r, 0));
}
// Laisser au moteur le temps de signaler un rejet non traite.
await new Promise((r) => setTimeout(r, 20));
__emit({ appels: globalThis.__appels.map((a) => a.route), onglet: M.__t._state.onglet, rejets: globalThis.__rejets });
"""
            + _EXIT,
            timeout=90,
        )
        self.assertEqual(
            res["onglet"],
            "podiums",
            "un id d'onglet inconnu est devenu l'onglet courant : l'ecran se vide",
        )
        self.assertEqual(res["rejets"], [], "un onglet herite du prototype a produit un rejet non traite")
        self.assertEqual(res["appels"], [], "un onglet inconnu a declenche une requete")

    def test_le_chargeur_lui_meme_refuse_une_cle_heritee(self) -> None:
        """La SECONDE barriere, eprouvee a son propre niveau.

        La validation d'entree rend ce garde inatteignable depuis un clic : les
        mutations qui le retirent laissaient donc la suite verte. Une garde
        qu'aucun test ne peut voir n'en est pas une. On appelle donc `_charger`
        directement, comme le ferait un futur appelant qui oublierait de valider.
        """
        res = run_module_test(
            STATS_JS,
            stubs=_STUBS,
            extra=_EXTRA,
            driver=_HOTE
            + r"""
globalThis.__rejets = [];
process.on("unhandledRejection", (e) => { globalThis.__rejets.push(String((e && e.message) || e)); });
const h = fauxHote();
globalThis.__appels.length = 0;
for (const nom of ["constructor", "__proto__", "valueOf", "hasOwnProperty"]) {
  await M.__t._charger(nom, h);
}
await new Promise((r) => setTimeout(r, 20));
__emit({ appels: globalThis.__appels.map((a) => a.route), rejets: globalThis.__rejets });
"""
            + _EXIT,
            timeout=90,
        )
        self.assertEqual(res["appels"], [], "une cle heritee du prototype a declenche une requete")
        self.assertEqual(res["rejets"], [], "une cle heritee du prototype a fait lever le chargeur")

    def test_une_dimension_inconnue_ne_change_pas_l_etat(self) -> None:
        res = run_module_test(
            STATS_JS,
            stubs=_STUBS,
            extra=_EXTRA,
            driver=_HOTE
            + r"""
globalThis.__reponses["library/get_library_podiums"] = { ok: true, release_groups: [] };
const h = fauxHote();
M.__init(h);
await new Promise((r) => setTimeout(r, 0));
globalThis.__appels.length = 0;
cliquer(h, { statsDimension: "constructor" });
await new Promise((r) => setTimeout(r, 0));
__emit({ dimension: M.__t._state.dimension, appels: globalThis.__appels.map((a) => a.route) });
"""
            + _EXIT,
            timeout=90,
        )
        self.assertNotEqual(res["dimension"], "constructor")
        self.assertEqual(res["appels"], [])


class UneABSENCENEstPasUnZEROTests(unittest.TestCase):
    """LE piege de cet ecran : un graphique rend visible ce qu'on lui donne, y
    compris ce qu'on a invente."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(STATS_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)

    def test_un_score_NON_NUMERIQUE_se_lit_comme_une_absence(self) -> None:
        """`Number("abc")` rend NaN, et `NaN.toFixed(1)` rend la CHAINE « NaN ».

        Elle s'affichait telle quelle dans la colonne Score, sans jamais lever.
        """
        for valeur in ('"abc"', "NaN", "Infinity", "{}"):
            with self.subTest(valeur=valeur):
                res = self._run(
                    f"__emit({{ html: M.__t._rendreRollup({{ ok: true, groups: "
                    f'[{{ group_name: "X", count: 1, avg_score: {valeur} }}] }}) }});'
                )
                self.assertNotIn("NaN", res["html"])
                self.assertNotIn("Infinity", res["html"])
                self.assertIn("—", res["html"])

    def test_un_score_ABSENT_s_affiche_en_tiret_pas_en_zero(self) -> None:
        res = self._run(
            r"""
__emit({ html: M.__t._rendreRollup({ ok: true, groups: [{ group_name: "Marvel", count: 3, avg_score: null }] }) });
"""
        )
        self.assertIn("—", res["html"], "un score absent doit se lire comme absent")
        self.assertNotIn(">0.0<", res["html"], "un score absent a ete rendu comme un score nul")

    def test_une_liste_VIDE_le_dit_au_lieu_de_dessiner_un_podium_vide(self) -> None:
        res = self._run("__emit({ html: M.__t._rendrePodiums({ ok: true, total_films: 0, release_groups: [] }) });")
        self.assertIn("Aucune donnée", res["html"])

    def test_une_timeline_VIDE_le_dit(self) -> None:
        res = self._run("__emit({ html: M.__t._rendreTimeline({ ok: true, months: [] }) });")
        self.assertIn("Aucun film daté", res["html"])

    def test_un_mois_a_ZERO_ne_porte_pas_d_etiquette_de_valeur(self) -> None:
        """Zero est une mesure REELLE ici : la barre existe, mais afficher « 0 »
        au-dessus de chaque mois creux noie les mois qui comptent."""
        res = self._run(
            r"""
__emit({ html: M.__t._rendreTimeline({ ok: true, months: [{ month: "2026-01", count: 0 }, { month: "2026-02", count: 7 }] }) });
"""
        )
        self.assertIn(">7<", res["html"])
        self.assertNotIn(">0<", res["html"])


class LesCHIFFRESDuServeurSontRENDUSTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(STATS_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)

    def test_les_trois_familles_de_podium_apparaissent(self) -> None:
        res = self._run(
            r"""
__emit({ html: M.__t._rendrePodiums({
  ok: true, total_films: 1284,
  release_groups: [{ name: "RARBG", count: 142 }],
  codecs: [{ name: "x265", count: 1200 }],
  sources: [{ name: "BluRay", count: 800 }],
}) });
"""
        )
        for attendu in ("RARBG", "x265", "BluRay", "142", "200"):
            self.assertIn(attendu, res["html"], f"« {attendu} » manque a l'affichage")

    def test_la_source_des_dates_est_DITE(self) -> None:
        """Un graphe de dates dont on ignore la provenance se lit mal : Jellyfin
        et la date du fichier ne mesurent pas la meme chose."""
        res = self._run(
            r"""
__emit({
  jf: M.__t._rendreTimeline({ ok: true, source: "jellyfin", months: [{ month: "2026-01", count: 1 }] }),
  fs: M.__t._rendreTimeline({ ok: true, source: "filesystem", months: [{ month: "2026-01", count: 1 }] }),
});
"""
        )
        self.assertIn("Jellyfin", res["jf"])
        self.assertIn("disque", res["fs"])

    def test_la_repartition_vient_du_BACKEND_pas_d_un_calcul_local(self) -> None:
        """CE TEST REMPLACE UN TEST QUI VERROUILLAIT UNE GRILLE FAUSSE.

        L'ancien `test_le_tier_suit_le_score` figeait 85/70/55/40 tout en
        affirmant dans sa docstring que « les tiers sont invariants dans toute
        l'app ». Ils l'etaient — mais a 70/66/55/40
        (`default_quality_profile()["tiers"]`, repris a l'identique par
        `_DEFAULT_TIERS` dans `parametres.js:510`). Un film a 72 s'affichait
        « Gold » ici et « Platinum » partout ailleurs.

        Et SURTOUT : ces seuils sont REGLABLES par l'utilisateur — c'est l'objet
        meme du profil de qualite. Aucune grille en dur ne peut etre juste. Le
        test verrouillait donc une erreur de conception, pas seulement des
        chiffres.

        La vue affiche desormais `tier_distribution`, que le backend compte film
        par film avec le profil ACTIF. Il n'y a plus de seuil dans le front, donc
        plus rien a faire diverger.
        """
        res = self._run(
            r"""
__emit({ html: M.__t._celluleDeRepartition({
  tier_distribution: { platinum: 2, gold: 5, silver: 0, bronze: 1, reject: 0, unknown: 0 },
}) });
"""
        )
        html = res["html"]
        self.assertIn("Platinum 2", html)
        self.assertIn("Gold 5", html)
        self.assertIn("Bronze 1", html)
        self.assertNotIn("Silver", html, "un tier a ZERO film ne doit pas encombrer la ligne")
        self.assertIn("stats-part--platinum", html)

    def test_une_repartition_ABSENTE_ne_devient_pas_une_repartition_vide(self) -> None:
        """Un groupe sans distribution n'est pas un groupe sans films."""
        for charge in ("{}", "{ tier_distribution: {} }", "{ tier_distribution: null }"):
            with self.subTest(charge=charge):
                res = self._run(f"__emit({{ html: M.__t._celluleDeRepartition({charge}) }});")
                self.assertIn("—", res["html"])
                self.assertNotIn("stats-part--", res["html"])

    def test_le_compte_accompagne_TOUJOURS_la_couleur(self) -> None:
        """WCAG 1.4.1 : `silver` et `platinum` sont indistinguables pour un
        daltonien comme en impression noir et blanc.

        LE DETAIL DOIT ETRE VISIBLE, pas seulement dans un attribut. Une
        premiere version n'assertait que `aria-label` et `title` : retirer le
        texte affiche la laissait VERTE, alors que l'ecran ne montrait plus que
        des couleurs.
        """
        res = self._run(
            r"""
__emit({ html: M.__t._celluleDeRepartition({ tier_distribution: { platinum: 3, silver: 4 } }) });
"""
        )
        self.assertIn('aria-label="Platinum 3 · Silver 4"', res["html"])
        self.assertIn('title="Platinum : 3"', res["html"])
        self.assertIn(
            '<span class="stats-repartition-texte">Platinum 3 · Silver 4</span>',
            res["html"],
            "le detail chiffre n'est plus AFFICHE : il ne reste que la couleur",
        )

    def test_le_NOM_du_groupe_est_affiche(self) -> None:
        """La cle est `group_name` — verifiee cote backend par
        `tests/test_contrat_payload_statistiques.py`. Une premiere version de la
        vue lisait `g.group || g.name || g.key` : aucune de ces trois cles
        n'existe, donc chaque ligne affichait « — ». Aucun test ne l'a vu, parce
        qu'aucun n'assertait sur le NOM rendu.
        """
        res = self._run(
            r"""
__emit({ html: M.__t._rendreRollup({ ok: true, groups: [
  { group_name: "Marvel Cinematic Universe", count: 12, avg_score: 71.5 },
] }) });
"""
        )
        self.assertIn("Marvel Cinematic Universe", res["html"], "le nom du groupe n'est pas rendu")
        self.assertNotIn(
            '<td class="stats-nom" title="—">',
            res["html"],
            "la ligne affiche « — » a la place du nom : la vue lit la mauvaise cle",
        )

    def test_les_mois_sont_lisibles_en_francais(self) -> None:
        res = self._run('__emit({ a: M.__t._moisCourt("2026-08"), b: M.__t._moisCourt("bidon") });')
        self.assertEqual(res["a"], "août 26")
        self.assertEqual(res["b"], "bidon", "une entree illisible doit passer telle quelle, pas devenir vide")


class UneREPONSEPERIMEENEcrasePasLaFraicheTests(unittest.TestCase):
    """Deux clics rapides emettent deux requetes ; rien ne garantit l'ordre.

    Sans jeton d'invalidation, la reponse LENTE ecrase la rapide : l'ecran
    affiche 6 mois alors que le bouton 24 est actif — un chiffre faux sous une
    etiquette juste, et rien pour le signaler.
    """

    def setUp(self) -> None:
        require_node(self)

    def test_la_reponse_lente_d_un_appel_DOUBLE_est_ignoree(self) -> None:
        res = run_module_test(
            STATS_JS,
            stubs=_STUBS,
            extra=_EXTRA,
            driver=_HOTE
            + r"""
// Le stub rend `Promise.resolve(__reponses[route])`, qui ADOPTE une promesse :
// on peut donc y deposer une promesse EN ATTENTE et la resoudre quand on veut.
globalThis.__reponses["library/get_library_podiums"] = { ok: true, release_groups: [] };
let libererLeLent = null;
globalThis.__reponses["library/get_library_timeline"] = new Promise((r) => { libererLeLent = r; });
const h = fauxHote();
M.__init(h);
await new Promise((r) => setTimeout(r, 0));
M.__t._state.onglet = "timeline";

M.__t._charger("timeline", h);        // appel LENT : sa reponse est en attente
// Le second appel repond tout de suite.
globalThis.__reponses["library/get_library_timeline"] = { ok: true, months: [{ month: "2026-01", count: 222 }] };
M.__t._charger("timeline", h);        // appel RAPIDE
await new Promise((r) => setTimeout(r, 0));

libererLeLent({ ok: true, months: [{ month: "2026-01", count: 111 }] });  // le lent revient EN DERNIER
await new Promise((r) => setTimeout(r, 0));
__emit({ compte: M.__t._state.data.timeline.months[0].count });
"""
            + _EXIT,
            timeout=90,
        )
        self.assertEqual(
            res["compte"],
            222,
            "la reponse perimee a ecrase la fraiche : l'ecran montre un chiffre qui n'est plus le bon",
        )


class LeDEMONTAGERetireSonEcouteurTests(unittest.TestCase):
    """Sans cela, chaque retour sur la vue empile un ecouteur, et un clic finit
    par declencher N chargements."""

    def setUp(self) -> None:
        require_node(self)

    def test_l_ecouteur_est_retire(self) -> None:
        res = run_module_test(
            STATS_JS,
            stubs=_STUBS,
            extra=_EXTRA,
            driver=_HOTE
            + r"""
globalThis.__reponses["library/get_library_podiums"] = { ok: true, release_groups: [] };
const h = fauxHote();
M.__init(h);
const apresInit = h.ecouteurs;
M.__unmount();
__emit({ apresInit, apresUnmount: h.ecouteurs });
"""
            + _EXIT,
            timeout=90,
        )
        self.assertEqual(res["apresInit"], 1)
        self.assertEqual(res["apresUnmount"], 0, "l'ecouteur survit au demontage : il s'empilera au retour")


class UnECHECEstAFFICHEPasAvaleTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def test_le_message_du_backend_apparait(self) -> None:
        res = run_module_test(
            STATS_JS,
            stubs=_STUBS,
            extra=_EXTRA,
            driver=_HOTE
            + r"""
globalThis.__reponses["library/get_library_podiums"] = { ok: false, user_message: "Aucun run analysé." };
const h = fauxHote();
M.__init(h);
await new Promise((r) => setTimeout(r, 0));
__emit({ html: h.innerHTML });
"""
            + _EXIT,
            timeout=90,
        )
        self.assertIn("Aucun run analysé.", res["html"])
        self.assertIn('role="alert"', res["html"])


if __name__ == "__main__":
    unittest.main()
