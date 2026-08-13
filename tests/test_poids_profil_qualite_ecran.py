"""Les curseurs de poids doivent regler les poids que le SCORING applique.

LE DEFAUT. Le moteur de scoring ne lit que trois poids — `video`, `audio`,
`extras` (`quality_score.py:1403-1407`, une seule somme ponderee de ces trois
sous-scores). L'ecran Parametres affichait SIX curseurs, tires d'une constante
JS : `resolution`, `bitrate`, `codec`, `audio_bitrate`, `audio_channels`,
`subtitles_fr`. Aucun n'est lu par le scoring.

MESURE DE BOUT EN BOUT, sur un profil regle a video 70 / audio 20 / extras 10 :

    l'utilisateur bouge ses curseurs et sauvegarde  ->  ok: True
    poids APRES : video 60 / audio 30 / extras 10   <- LE DEFAUT
                  + les six cles mortes, portees sans etre lues

Autrement dit : bouger les curseurs REMETTAIT les vrais poids aux valeurs
d'usine — l'inverse exact de ce que l'utilisateur demandait — et les curseurs
eux-memes ne faisaient rien.

C'EST LA TROISIEME FORME DE LA MEME CAUSE. Le commentaire de `_DEFAULT_TIERS`
garde la trace de la premiere : la grille 85/68/54/30 etait ECRITE EN BASE au
save de profil alors que le scoring en appliquait une autre. Une constante JS
qui fait autorite a la place du backend finit toujours par diverger.

CE QUE CES TESTS EPROUVENT. Que l'ecran parle la langue du backend : ses cles,
sa forme (points de pourcentage, somme 100), et ses defauts — demandes, pas
recopies.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

PARAMETRES_JS = ROOT / "web" / "dashboard" / "views" / "parametres.js"

_STUBS = r"""
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById() { return null; }, querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() { return { style: {}, click() {} }; },
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
function cachedGetSettings() { return Promise.resolve({}); }
function invalidateSettingsCache() {}
function escapeHtml(s) { return String(s == null ? "" : s); }
globalThis.__toasts = [];
function showToast(o) { globalThis.__toasts.push(o); }
function dangerConfirmModal(o) { globalThis.__enCours = o.onConfirm ? o.onConfirm() : null; }
function t(k) { return String(k); }
function formatBytes() { return ""; }
function registerRoute() {}
function navigate() {}
const rightPanel = { setWidth() {}, setExpanded() {}, setContent() {} };

// LES TROIS MODALES DE LA VAGUE D, stubbees pour COMPTER leurs ouvertures.
// Sans elles, cliquer un bouton levait un ReferenceError — ce qu'aucun test ne
// faisait, faute de cliquer.
globalThis.__ouvertures = [];
function ouvrirSimulateurQualite(...a) { globalThis.__ouvertures.push(["simulateur", a]); }
function ouvrirReglesQualite(...a) { globalThis.__ouvertures.push(["regles", a]); }
function ouvrirCalibrationQualite(...a) { globalThis.__ouvertures.push(["calibration", a]); }
"""

_EXTRA = (
    "export const __poidsDefaut = _DEFAULT_WEIGHTS;\n"
    "export const __libelles = _WEIGHT_LABELS;\n"
    "export const __somme = _SOMME_POIDS;\n"
    "export const __reinit = _reinitialiserLeBrouillonDeProfil;\n"
    "export const __etat = _state;\n"
    "export const __bind = _bindProfilsQualite;\n"
)
_EXIT = "\nprocess.exit(0);\n"

#: Les seules cles que `quality_score.py` additionne (lignes 1403-1407).
_CLES_DU_SCORING = {"video", "audio", "extras"}


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(PARAMETRES_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)


class LesPoidsDeLEcranSontCeuxDuSCORINGTests(_Base):
    def test_les_cles_par_defaut_sont_celles_que_le_scoring_lit(self) -> None:
        res = self._run("__emit({ cles: Object.keys(M.__poidsDefaut), valeurs: M.__poidsDefaut });")

        self.assertEqual(
            set(res["cles"]),
            _CLES_DU_SCORING,
            "l'ecran propose des poids que le calcul du score n'additionne jamais",
        )
        self.assertEqual(res["valeurs"], {"video": 60, "audio": 30, "extras": 10})

    def test_la_forme_est_celle_du_BACKEND_des_points_de_pourcentage(self) -> None:
        """Une somme a 1.00 aurait fait refuser tout profil reel."""
        res = self._run(
            "__emit({ somme: M.__somme, total: Object.values(M.__poidsDefaut).reduce((s, v) => s + v, 0) });"
        )

        self.assertEqual(res["somme"], 100)
        self.assertEqual(res["total"], 100, "les poids par defaut ne totalisent pas la somme attendue")

    def test_chaque_poids_porte_un_libelle_lisible(self) -> None:
        """« extras » seul ne dit rien : le libelle doit nommer ce qu'il couvre."""
        res = self._run("__emit({ libelles: M.__libelles, cles: Object.keys(M.__poidsDefaut) });")

        for cle in res["cles"]:
            self.assertIn(cle, res["libelles"], f"le poids « {cle} » n'a pas de libelle")
            self.assertGreater(len(res["libelles"][cle]), len(cle), f"le libelle de « {cle} » n'explique rien")


class LaREINITIALISATIONDemandeSesValeursAuBackendTests(_Base):
    """Une valeur par defaut recopiee dans le front est une verite en double."""

    def test_elle_appelle_la_route_en_DRY_RUN(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["quality/reset_quality_profile"] = {
  ok: true, profile: { tiers: { platinum: 70, gold: 66, silver: 55, bronze: 40 },
                       weights: { video: 60, audio: 30, extras: 10 } },
};
await M.__reinit();
__emit({ appels: globalThis.__appels });
"""
        )
        self.assertEqual(len(res["appels"]), 1)
        self.assertEqual(res["appels"][0]["route"], "quality/reset_quality_profile")
        self.assertIs(
            res["appels"][0]["params"]["dry_run"],
            True,
            "la reinitialisation ECRIT en base au lieu de seulement lire les defauts",
        )

    def test_le_brouillon_prend_les_valeurs_RENDUES_pas_des_constantes(self) -> None:
        """Le backend fait foi, meme si ses valeurs different de celles du front."""
        res = self._run(
            r"""
globalThis.__reponses["quality/reset_quality_profile"] = {
  ok: true, profile: { tiers: { platinum: 77, gold: 66, silver: 55, bronze: 44 },
                       weights: { video: 50, audio: 40, extras: 10 } },
};
await M.__reinit();
__emit({ tiers: M.__etat.profileDraft.tiers, poids: M.__etat.profileDraft.weights });
"""
        )
        self.assertEqual(res["tiers"], {"platinum": 77, "gold": 66, "silver": 55, "bronze": 44})
        self.assertEqual(res["poids"], {"video": 50, "audio": 40, "extras": 10})

    def test_un_echec_ne_restaure_RIEN_et_le_DIT(self) -> None:
        """Restaurer des valeurs inventees serait le defaut qu'on corrige."""
        res = self._run(
            r"""
M.__etat.profileDraft = { id: "X", label: "X", tiers: { platinum: 1 }, weights: { video: 99 } };
globalThis.__reponses["quality/reset_quality_profile"] = { ok: false, user_message: "Store indisponible." };
await M.__reinit();
__emit({ brouillon: M.__etat.profileDraft });
"""
        )
        self.assertEqual(
            res["brouillon"]["weights"],
            {"video": 99},
            "le brouillon a ete ecrase alors que les defauts n'ont pas pu etre lus",
        )


class LeBOUTONEstVraimentBRANCHETests(_Base):
    """Muter le SITE D'APPEL separement, et pas seulement la fonction.

    Les tests ci-dessus appellent `_reinitialiserLeBrouillonDeProfil`
    directement : ils restaient tous VERTS quand on rebranchait le bouton sur
    l'ancienne recopie de constantes. Une fonction juste ne sert a rien si le
    bouton ne l'atteint pas.
    """

    def test_le_clic_sur_Reinitialiser_demande_les_defauts_au_backend(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["quality/reset_quality_profile"] = {
  ok: true, profile: { tiers: { platinum: 70, gold: 66, silver: 55, bronze: 40 },
                       weights: { video: 60, audio: 30, extras: 10 } },
};
// Un conteneur minimal : seul le selecteur des boutons d'action rend quelque
// chose, les autres bindings de la section recoivent une liste vide.
const boutons = [{ dataset: { parametresProfilsAction: "reset" }, rappel: null,
                   addEventListener(_t, fn) { this.rappel = fn; } }];
const conteneur = {
  querySelectorAll(sel) { return sel.indexOf("parametres-profils-action") >= 0 ? boutons : []; },
  querySelector() { return null; },
};
M.__bind(conteneur);
// Le binding de la section charge aussi d'autres donnees ; on ne retient que
// les appels DECLENCHES PAR LE CLIC.
globalThis.__appels.length = 0;
boutons[0].rappel();
await new Promise((r) => setTimeout(r, 0));
__emit({ appels: globalThis.__appels.map((a) => a.route) });
"""
        )
        self.assertEqual(
            res["appels"],
            ["quality/reset_quality_profile"],
            "le bouton « Reinitialiser » n'atteint pas la lecture des defauts du backend",
        )


class LesTroisBoutonsDeLaVagueDOuvrentVraimentTests(_Base):
    """Cinquieme fois dans cette campagne : une fonction juste et inatteignable.

    CES TESTS ONT DEJA ETE FAUX-VERTS. Ils assertaient
    `typeof boutons[0].rappel === "function"` — vrai d'un gestionnaire au corps
    VIDE. Mesure : remplacer les trois `() => ouvrir...()` par `() => {}` laissait
    les 9 tests du fichier au vert, alors que les trois fonctionnalites entieres
    de la vague D devenaient inatteignables depuis l'application. C'est le piege
    n2 du CLAUDE.md (« un test qui verifie la PRESENCE d'une garde reste vert
    quand elle est neutralisee »), applique a un CABLAGE plutot qu'a une garde.

    On CLIQUE donc, et on observe l'ouverture.
    """

    def _clic(self, marqueur: str) -> dict:
        return self._run(
            r"""
const boutons = [{ dataset: {}, rappel: null, addEventListener(_t, fn) { this.rappel = fn; } }];
const conteneur = {
  querySelectorAll(sel) { return sel.indexOf("MARQUEUR") >= 0 ? boutons : []; },
  querySelector() { return null; },
};
M.__bind(conteneur);
const branche = typeof boutons[0].rappel === "function";
globalThis.__ouvertures.length = 0;
if (branche) boutons[0].rappel();
__emit({ branche, ouvertures: globalThis.__ouvertures.map((o) => o[0]),
         arguments: globalThis.__ouvertures.map((o) => o[1].length) });
""".replace("MARQUEUR", marqueur)
        )

    def test_le_clic_OUVRE_le_simulateur(self) -> None:
        res = self._clic("parametres-ouvrir-simulateur")

        self.assertTrue(res["branche"], "le bouton « Simuler un profil » n'a aucun gestionnaire")
        self.assertEqual(res["ouvertures"], ["simulateur"], "le clic n'ouvre pas le simulateur")

    def test_le_clic_OUVRE_le_builder_de_regles(self) -> None:
        """Sixieme fois : une capacite complete et inatteignable."""
        res = self._clic("parametres-ouvrir-regles")

        self.assertTrue(res["branche"], "le bouton « Règles personnalisées » n'a aucun gestionnaire")
        self.assertEqual(res["ouvertures"], ["regles"], "le clic n'ouvre pas le builder de regles")
        self.assertEqual(
            res["arguments"],
            [0],
            "le builder recoit un argument : il lit ses regles LUI-MEME, a la source qu'il ecrit "
            "(lui passer `_state.profileDraft.custom_rules` revenait a passer `undefined`)",
        )

    def test_le_clic_OUVRE_la_calibration(self) -> None:
        res = self._clic("parametres-ouvrir-calibration")

        self.assertTrue(res["branche"], "le bouton « Réglages fins » n'a aucun gestionnaire")
        self.assertEqual(res["ouvertures"], ["calibration"], "le clic n'ouvre pas les reglages fins")


if __name__ == "__main__":
    unittest.main()
