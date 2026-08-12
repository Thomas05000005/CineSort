"""Le rapport de calibration doit s'afficher, et un import doit se voir venir.

L'INTERFACE PROMETTAIT LE RAPPORT SANS L'AFFICHER NULLE PART. `film-detail.js`
dit a l'utilisateur : « votre feedback alimente le rapport de calibration ».
`quality/get_calibration_report` existait, testee, et aucun ecran ne la montrait.
Le feedback partait donc dans un rapport que personne ne pouvait lire.

DEUX GRANDEURS QUE CES TESTS EPROUVENT EN PRIORITE.

1. `suggestion` VAUT `null` TANT QU'IL N'Y A PAS ASSEZ DE RETOURS (mesure sur un
   store neuf : `bias.total_feedbacks = 0`, `suggestion = null`). Un ecran qui
   n'affiche alors RIEN a l'air casse. Il doit DIRE pourquoi, et ou en est le
   compte — c'est la seule facon de transformer une absence en information.

2. UN IMPORT REMPLACE LE PROFIL DE L'UTILISATEUR. Il montre donc son DIFF avant
   d'ecrire. Ecrire d'abord et prevenir ensuite serait le contraire de la regle
   n3 du depot : ici la perte n'est pas un fichier, c'est un reglage.

Les TOGGLES viennent du profil, jamais d'une liste ecrite dans le front — meme
regle que les regles custom (D3) et les poids (D1), et pour la meme raison.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

CALIB_JS = ROOT / "web" / "dashboard" / "components" / "calibration-qualite.js"

_STUBS = r"""
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.URL = { createObjectURL() { return "blob:faux"; }, revokeObjectURL() {} };
globalThis.Blob = function (parts) { this.parts = parts; globalThis.__dernierBlob = this; };
globalThis.__telechargements = [];
globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById() { return null; }, querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() { return { style: {}, click() { globalThis.__telechargements.push(this.download); } }; },
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
function dangerConfirmModal(o) {
  globalThis.__confirmations.push(o);
  if (globalThis.__accepte === false) { if (o.onCancel) o.onCancel(); return; }
  globalThis.__enCours = o.onConfirm ? o.onConfirm() : null;
}
globalThis.__toasts = [];
function showToast(o) { globalThis.__toasts.push(o); }
"""

_EXTRA = "export const __t = __test;\nexport const __ouvrir = ouvrirCalibrationQualite;\n"
_EXIT = "\nprocess.exit(0);\n"

_PROFIL = r"""
globalThis.__reponses["quality/get_quality_profile"] = {
  ok: true,
  profile_json: {
    id: "MonProfil",
    weights: { video: 60, audio: 30, extras: 10 },
    tiers: { platinum: 70, gold: 66, silver: 55, bronze: 40 },
    toggles: { include_metadata: false, include_naming: false, enable_4k_light: true, include_subtitles: false },
    custom_rules: [],
  },
};
"""

_RAPPORT_RICHE = r"""
globalThis.__reponses["quality/get_calibration_report"] = {
  ok: true,
  bias: { total_feedbacks: 47, accord_pct: 62.0, mean_delta: 6.2,
          bias_direction: "up", bias_strength: "strong",
          category_bias: { video: 8, audio: -1, extras: 0 } },
  current_weights: { video: 60, audio: 30, extras: 10 },
  suggestion: { weights: { video: 66, audio: 26, extras: 8 } },
  sample_feedbacks: [],
};
"""

_RAPPORT_MAIGRE = r"""
globalThis.__reponses["quality/get_calibration_report"] = {
  ok: true,
  bias: { total_feedbacks: 12, accord_pct: 0, mean_delta: 0,
          bias_direction: "neutral", bias_strength: "none",
          category_bias: { video: 0, audio: 0, extras: 0 } },
  current_weights: { video: 60, audio: 30, extras: 10 },
  suggestion: null, sample_feedbacks: [],
};
"""


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(CALIB_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)


class UneABSENCEDeSuggestionSExpliqueTests(_Base):
    """LE cas le plus frequent au debut, et le plus facile a bacler."""

    def test_sous_le_seuil_l_ecran_DIT_pourquoi_et_ou_on_en_est(self) -> None:
        res = self._run(_PROFIL + _RAPPORT_MAIGRE + "await M.__t._charger();\n__emit({ html: M.__t._corps() });")

        self.assertIn("Pas encore assez", res["html"], "l'ecran reste muet sur l'absence de suggestion")
        self.assertIn("12 / 20", res["html"], "le compte n'est pas dit : l'utilisateur ne sait pas ce qui manque")

    def test_au_dessus_du_seuil_SANS_biais_le_dit_aussi(self) -> None:
        """« Aucune suggestion » n'est pas la meme chose que « pas assez de
        donnees » : les confondre laisserait croire que l'ecran ne marche pas."""
        res = self._run(
            _PROFIL
            + r"""
globalThis.__reponses["quality/get_calibration_report"] = {
  ok: true, bias: { total_feedbacks: 60, accord_pct: 95, mean_delta: 0.1,
                    bias_direction: "neutral", bias_strength: "none", category_bias: {} },
  current_weights: { video: 60 }, suggestion: null, sample_feedbacks: [],
};
await M.__t._charger();
__emit({ html: M.__t._corps() });
"""
        )
        self.assertIn("suivent le profil", res["html"])
        self.assertNotIn("Pas encore assez", res["html"])


class LeRAPPORTEstAFFICHEEnEntierTests(_Base):
    def test_les_six_grandeurs_du_biais_apparaissent(self) -> None:
        res = self._run(_PROFIL + _RAPPORT_RICHE + "await M.__t._charger();\n__emit({ html: M.__t._corps() });")

        html = res["html"]
        self.assertIn("47 retour", html)
        self.assertIn("62 %", html)
        self.assertIn("+6,2", html)
        self.assertIn("PLUS HAUT", html)
        self.assertIn("biais fort", html)
        self.assertIn("video", html)
        self.assertIn("+8", html, "le biais par categorie n'est pas rendu")

    def test_la_suggestion_montre_l_AVANT_et_l_APRES(self) -> None:
        res = self._run(_PROFIL + _RAPPORT_RICHE + "await M.__t._charger();\n__emit({ html: M.__t._corps() });")

        self.assertIn("60", res["html"])
        self.assertIn("66", res["html"])
        self.assertIn("Appliquer", res["html"])

    def test_appliquer_greffe_les_poids_sur_le_profil_EXISTANT(self) -> None:
        """Ecrire un profil neuf effacerait seuils, toggles et regles."""
        res = self._run(
            _PROFIL
            + _RAPPORT_RICHE
            + r"""
await M.__t._charger();
await M.__t._appliquerLaSuggestion();
const e = globalThis.__appels.filter((a) => a.route === "quality/save_quality_profile")[0];
__emit({ envoye: e ? e.params.profile_json : null });
"""
        )
        env = res["envoye"]
        self.assertIsNotNone(env, "aucune ecriture n'a eu lieu")
        self.assertEqual(env["weights"], {"video": 66, "audio": 26, "extras": 8})
        self.assertEqual(env["tiers"]["platinum"], 70, "les seuils ont ete perdus")
        self.assertIn("toggles", env, "les options ont ete perdues")

    def test_un_rapport_INDISPONIBLE_n_emporte_pas_les_options(self) -> None:
        """Deux lectures independantes : l'une qui echoue ne doit pas vider
        l'autre."""
        res = self._run(
            _PROFIL + 'globalThis.__reponses["quality/get_calibration_report"] = { ok: false, message: "boum" };\n'
            "await M.__t._charger();\n__emit({ html: M.__t._corps(), profil: !!M.__t._etat.profil });"
        )

        self.assertTrue(res["profil"])
        self.assertIn("4K allégé", res["html"], "les options ont disparu avec le rapport")


class LesOPTIONSViennentDuPROFILTests(_Base):
    def test_les_cles_rendues_sont_celles_du_profil(self) -> None:
        res = self._run(
            "M.__t._etat.profil = { toggles: { include_metadata: true, une_option_future: false } };\n"
            "__emit({ html: M.__t._rendreToggles() });"
        )

        self.assertIn("include_metadata", res["html"])
        self.assertIn("une_option_future", res["html"], "une option inconnue du front est cachee a l'utilisateur")

    def test_basculer_une_option_greffe_sur_le_profil_EXISTANT(self) -> None:
        res = self._run(
            _PROFIL
            + _RAPPORT_MAIGRE
            + r"""
await M.__t._charger();
await M.__t._basculerToggle("include_naming", true);
const e = globalThis.__appels.filter((a) => a.route === "quality/save_quality_profile")[0];
__emit({ envoye: e ? e.params.profile_json : null });
"""
        )
        env = res["envoye"]
        self.assertIs(env["toggles"]["include_naming"], True)
        self.assertIs(env["toggles"]["enable_4k_light"], True, "les autres options ont ete perdues")
        self.assertEqual(env["weights"], {"video": 60, "audio": 30, "extras": 10})


class UnIMPORTSeVoitVenirTests(_Base):
    """Un import REMPLACE le profil : la perte se montre avant de l'ecrire."""

    _ENTRANT = (
        '{"profile": {"weights": {"video": 55, "audio": 25, "extras": 20},'
        ' "tiers": {"platinum": 74, "gold": 68, "silver": 55, "bronze": 40},'
        ' "toggles": {"include_metadata": false, "include_naming": false,'
        ' "enable_4k_light": true, "include_subtitles": false},'
        ' "custom_rules": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}}'
    )

    def test_preparer_un_import_n_ECRIT_RIEN(self) -> None:
        res = self._run(
            _PROFIL
            + _RAPPORT_MAIGRE
            + f"await M.__t._charger();\nglobalThis.__appels.length = 0;\nM.__t._preparerImport({self._ENTRANT!r});\n"
            "__emit({ appels: globalThis.__appels.length, diff: !!M.__t._etat.diffImport });"
        )

        self.assertEqual(res["appels"], 0, "l'import a ecrit avant meme de montrer ce qu'il change")
        self.assertTrue(res["diff"])

    def test_le_diff_nomme_CE_QUI_change(self) -> None:
        res = self._run(
            _PROFIL
            + _RAPPORT_MAIGRE
            + f"await M.__t._charger();\nM.__t._preparerImport({self._ENTRANT!r});\n__emit({{ html: M.__t._corps() }});"
        )

        html = res["html"]
        self.assertIn("55", html)
        self.assertIn("74", html)
        self.assertIn("Règles", html, "le changement du nombre de regles n'est pas annonce")
        self.assertIn("Remplacer mon profil", html)

    def test_un_profil_IDENTIQUE_le_dit_au_lieu_d_un_tableau_vide(self) -> None:
        res = self._run(
            _PROFIL
            + _RAPPORT_MAIGRE
            + "await M.__t._charger();\nM.__t._preparerImport(JSON.stringify({ profile: M.__t._etat.profil }));\n"
            "__emit({ html: M.__t._corps() });"
        )

        self.assertIn("identique au vôtre", res["html"])

    def test_un_fichier_ILLISIBLE_est_refuse_sans_rien_toucher(self) -> None:
        for contenu in ('"pas du json"', '"{}"', '"[1,2,3]"'):
            with self.subTest(contenu=contenu):
                res = self._run(
                    _PROFIL
                    + _RAPPORT_MAIGRE
                    + f"await M.__t._charger();\nglobalThis.__appels.length = 0;\nM.__t._preparerImport({contenu});\n"
                    "__emit({ appels: globalThis.__appels.length, diff: !!M.__t._etat.diffImport,"
                    " toasts: globalThis.__toasts.map((t) => t.type) });"
                )
                self.assertEqual(res["appels"], 0)
                self.assertFalse(res["diff"])

    def test_la_confirmation_NOMME_la_consequence_et_le_recalcul(self) -> None:
        res = self._run(
            _PROFIL
            + _RAPPORT_MAIGRE
            + f"""
await M.__t._charger();
M.__t._preparerImport({self._ENTRANT!r});
globalThis.__accepte = false;
M.__t._confirmerImport();
const c = globalThis.__confirmations[0];
__emit({{ items: c.items.length, consequence: c.consequence }});
"""
        )
        self.assertGreater(res["items"], 0, "la liste des changements n'est pas annoncee")
        self.assertIn("REMPLAC", res["consequence"])
        self.assertIn("recalcul", res["consequence"].lower(), "l'effet sur les scores n'est pas dit")

    def test_un_REFUS_n_importe_RIEN(self) -> None:
        res = self._run(
            _PROFIL
            + _RAPPORT_MAIGRE
            + f"""
await M.__t._charger();
M.__t._preparerImport({self._ENTRANT!r});
globalThis.__accepte = false;
M.__t._confirmerImport();
__emit({{ imports: globalThis.__appels.filter((a) => a.route === "quality/import_shareable_profile").length }});
"""
        )
        self.assertEqual(res["imports"], 0)

    def test_une_ACCEPTATION_transmet_le_CONTENU_tel_quel(self) -> None:
        res = self._run(
            _PROFIL
            + _RAPPORT_MAIGRE
            + f"""
await M.__t._charger();
M.__t._preparerImport({self._ENTRANT!r});
globalThis.__accepte = true;
M.__t._confirmerImport();
await globalThis.__enCours;
const i = globalThis.__appels.filter((a) => a.route === "quality/import_shareable_profile")[0];
__emit({{ params: i ? i.params : null }});
"""
        )
        self.assertIsNotNone(res["params"])
        self.assertEqual(res["params"]["content"], self._ENTRANT, "le contenu a ete altere avant l'envoi")
        self.assertIs(res["params"]["activate"], True)


class LEXPORTPasseLeContenuTELQUELTests(_Base):
    def test_le_texte_du_serveur_part_sans_etre_reserialise(self) -> None:
        res = self._run(
            'globalThis.__reponses["quality/export_shareable_profile"] = { ok: true, content: "{\\n  \\"a\\": 1\\n}", filename_suggestion: "mon.json" };\n'
            "await M.__t._exporter();\n"
            "__emit({ parts: globalThis.__dernierBlob.parts, tel: globalThis.__telechargements });"
        )

        self.assertEqual(res["parts"], ['{\n  "a": 1\n}'], "le contenu a ete altere entre le serveur et le fichier")
        self.assertEqual(res["tel"], ["mon.json"])

    def test_un_echec_ne_telecharge_RIEN(self) -> None:
        res = self._run(
            'globalThis.__reponses["quality/export_shareable_profile"] = { ok: false, user_message: "Base verrouillée." };\n'
            "await M.__t._exporter();\n"
            "__emit({ tel: globalThis.__telechargements.length, texte: globalThis.__toasts[0].text });"
        )

        self.assertEqual(res["tel"], 0)
        self.assertEqual(res["texte"], "Base verrouillée.")


if __name__ == "__main__":
    unittest.main()
