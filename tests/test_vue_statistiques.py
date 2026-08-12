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
#: que le demontage les retire vraiment.
_HOTE = r"""
function fauxHote() {
  return {
    innerHTML: "",
    ecouteurs: 0,
    addEventListener() { this.ecouteurs += 1; },
    removeEventListener() { this.ecouteurs -= 1; },
  };
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
        """Un selecteur qui n'envoie pas son choix affiche toujours la meme chose."""
        res = self._run(
            r"""
globalThis.__reponses["library/get_library_podiums"] = { ok: true, release_groups: [] };
globalThis.__reponses["library/get_library_timeline"] = { ok: true, months: [] };
const h = fauxHote();
M.__init(h);
await new Promise((r) => setTimeout(r, 0));
M.__t._state.mois = 24;
M.__t._state.onglet = "timeline";
globalThis.__appels.length = 0;
await new Promise((r) => setTimeout(r, 0));
__emit({ etat: M.__t._state.mois });
"""
        )
        self.assertEqual(res["etat"], 24)


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
__emit({ html: M.__t._rendreRollup({ ok: true, groups: [{ group: "Marvel", count: 3, avg_score: null }] }) });
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
