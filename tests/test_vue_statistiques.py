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

    def test_le_tier_suit_le_score(self) -> None:
        """Les couleurs de tier sont invariantes dans toute l'app : un score ne
        change pas de couleur selon l'ecran qui l'affiche."""
        res = self._run(
            r"""
__emit({
  p: M.__t._tierDuScore(92), g: M.__t._tierDuScore(75),
  s: M.__t._tierDuScore(60), b: M.__t._tierDuScore(45),
  r: M.__t._tierDuScore(12), n: M.__t._tierDuScore(null),
});
"""
        )
        self.assertEqual(
            [res["p"], res["g"], res["s"], res["b"], res["r"], res["n"]],
            ["platinum", "gold", "silver", "bronze", "reject", "unknown"],
        )

    def test_les_mois_sont_lisibles_en_francais(self) -> None:
        res = self._run('__emit({ a: M.__t._moisCourt("2026-08"), b: M.__t._moisCourt("bidon") });')
        self.assertEqual(res["a"], "août 26")
        self.assertEqual(res["b"], "bidon", "une entree illisible doit passer telle quelle, pas devenir vide")


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
