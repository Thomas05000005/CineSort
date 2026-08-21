"""L'ecran Parametres effacait les planchers de hierarchie du profil qualite.

MEME FAMILLE QUE #1097 — « l'ecran efface des reglages qu'il ne possede pas ».
Le remede pose alors, `_payloadPossede`, n'a jamais ete etendu au profil : ici
c'est pire qu'un oubli, `_mergeTierHierarchy` RETIRE activement les sections.

Le brouillon de profil de `parametres.js` est construit avec exactement
``{id, label, tiers, weights, tier_hierarchy}`` — le fichier le dit lui-meme
(commentaire du bouton « regles de qualite », ou le meme defaut avait deja
detruit les `custom_rules`). `_mergeTierHierarchy` ne recopie que ``enabled`` et
``order`` ; les six sections de planchers et plafonds
(``resolution_floors``, ``resolution_ceilings``, ``codec_floors``,
``hdr_floors``, ``audio_floors``, ``group_floors``) disparaissaient du brouillon,
donc du POST ``settings/save_profile``.

Et ce POST n'est pas additif : `profiles_support_crud.save_profile` fait
« Replace si meme id, sinon append », puis `validate_quality_profile` ->
`normalize_hierarchy_config` recomplete les sections ABSENTES avec les defauts
TRaSH. L'enregistrement ne perdait donc pas les valeurs de l'utilisateur dans le
vide : il les REMPLACAIT par d'autres, sans qu'aucun element d'ecran ne les ait
jamais montrees.

ATTEIGNABILITE, mesuree et non supposee. Un profil visible de cet ecran peut
porter des planchers non-defaut par le round-trip Recyclarr, que l'ecran met
lui-meme en avant : `_profile_to_recyclarr_dict` encapsule
``"cinesort_profile": copy.deepcopy(profile)`` (donc `tier_hierarchy` entier),
`_recyclarr_dict_to_profile` le relit, et `import_recyclarr_yaml` persiste par
`_crud.save_profile` dans `settings.custom_quality_profiles` — d'ou
`get_profiles` le ressort. Les presets embarques
(`cinesort/data/presets/tier_preset_trash_2026.json`) portent eux aussi de
vraies valeurs non-defaut : `puriste_dv` met `hdr_floors.dolby_vision` a
``Platinum`` et pose un `resolution_ceilings["1080p"]` que le defaut n'a pas ;
`qualite_max_audio` ajoute `audio_floors.dts_x = "Gold"`.

Le harnais charge la SOURCE DE PRODUCTION sous Node et pilote la vraie chaine
`_loadProfiles` -> `_saveProfileAsNew`, pour observer ce qui est REELLEMENT
poste. Une assertion sur le texte du fichier n'aurait rien prouve.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, node_check, require_node, run_module_test

PARAMETRES_JS = ROOT / "web" / "dashboard" / "views" / "parametres.js"


_STUBS = r"""
globalThis.__posts = [];

const apiPost = async (route, payload) => {
  globalThis.__posts.push({ route, payload });
  if (route === "settings/get_profiles") {
    return { data: { ok: true, active_profile_id: "mon_profil", profiles: [globalThis.__profilActif] } };
  }
  return { data: { ok: true } };
};
const invalidateSettingsCache = () => {};
const escapeHtml = (s) => String(s == null ? "" : s);
const formatBytes = (n) => String(n);
const dangerConfirmModal = () => {};
const trapFocus = () => {};
// La modale de nommage est pilotee : on declenche l'action « Creer » comme le
// ferait un clic utilisateur, sans reecrire `_promptNewProfileName`.
const showModal = (opts) => {
  const creer = (opts.actions || []).find((a) => a.label === "Créer");
  if (creer) creer.onClick();
};
const ouvrirSimulateurQualite = () => {};
const ouvrirReglesQualite = () => {};
const ouvrirCalibrationQualite = () => {};

const faussenoeud = {
  value: "mon_profil",
  querySelector: () => faussenoeud,
  querySelectorAll: () => [],
  addEventListener() {},
  removeEventListener() {},
  textContent: "",
  dataset: {},
};
globalThis.document = {
  getElementById: () => faussenoeud,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  removeEventListener() {},
  createElement: () => faussenoeud,
  body: faussenoeud,
};
globalThis.window = {
  addEventListener() {},
  removeEventListener() {},
  location: { href: "", origin: "http://localhost" },
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
"""

_EXTRA = r"""
export const __h = {
  loadProfiles: () => _loadProfiles(),
  saveAsNew: () => _saveProfileAsNew(),
  draft: () => _state.profileDraft,
  merge: (raw) => _mergeTierHierarchy(raw),
};
"""

#: Profil actif porteur de planchers/plafonds NON-DEFAUT. Les valeurs sont
#: celles que le depot livre reellement dans ses presets embarques.
_PROFIL_AVEC_PLANCHERS = r"""
globalThis.__profilActif = {
  id: "mon_profil",
  label: "Mon profil",
  tiers: { platinum: 70, gold: 66, silver: 55, bronze: 40 },
  weights: { video: 60, audio: 30, extras: 10 },
  tier_hierarchy: {
    enabled: true,
    order: ["audio", "resolution", "video_codec", "hdr", "release_group"],
    audio_floors: { truehd_atmos: "Platinum", dts_x: "Gold" },
    resolution_ceilings: { "1080p": "Gold" },
    group_floors: { framestor: "Gold" },
  },
};
"""


class PlanchersDeHierarchiePreservesTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(PARAMETRES_JS, stubs=_STUBS, extra=_EXTRA, driver=driver)

    def test_la_source_reste_syntaxiquement_valide(self) -> None:
        node_check(self, PARAMETRES_JS)

    def test_les_planchers_survivent_a_l_enregistrement(self) -> None:
        """LE COEUR DU FINDING : ce qui entre par `get_profiles` doit ressortir
        par `save_profile`. Mesure avant correctif : trois sections entrantes,
        zero sortante."""
        res = self._run(
            _PROFIL_AVEC_PLANCHERS
            + r"""
await M.__h.loadProfiles();
await M.__h.saveAsNew();
const poste = globalThis.__posts.filter((p) => p.route === "settings/save_profile");
__emit({ n: poste.length, hierarchie: poste.length ? poste[0].payload.profile.tier_hierarchy : null });
"""
        )

        self.assertEqual(res["n"], 1, "le profil doit avoir ete poste")
        hierarchie = res["hierarchie"] or {}
        self.assertEqual(
            hierarchie.get("audio_floors"),
            {"truehd_atmos": "Platinum", "dts_x": "Gold"},
            f"planchers audio perdus a l'enregistrement : {hierarchie}",
        )
        self.assertEqual(
            hierarchie.get("resolution_ceilings"),
            {"1080p": "Gold"},
            f"plafond de resolution perdu a l'enregistrement : {hierarchie}",
        )
        self.assertEqual(
            hierarchie.get("group_floors"),
            {"framestor": "Gold"},
            f"plancher de release group perdu a l'enregistrement : {hierarchie}",
        )

    def test_l_ecran_garde_la_main_sur_enabled_et_l_ordre(self) -> None:
        """NON-REGRESSION : preserver les sections ne doit pas rendre l'ecran
        passif sur les deux champs qu'il POSSEDE reellement. Une dimension
        inconnue reste filtree."""
        res = self._run(
            r"""
const merged = M.__h.merge({
  enabled: false,
  order: ["hdr", "dimension_inventee", "audio"],
  audio_floors: { truehd_atmos: "Gold" },
});
__emit({ merged });
"""
        )

        self.assertIs(res["merged"]["enabled"], False)
        self.assertEqual(res["merged"]["order"], ["hdr", "audio"], "la dimension inconnue doit rester filtree")
        self.assertEqual(res["merged"]["audio_floors"], {"truehd_atmos": "Gold"})

    def test_un_profil_sans_hierarchie_recoit_les_defauts(self) -> None:
        """NON-REGRESSION : profil legacy sans la cle -> defaut OFF, 5 dimensions."""
        res = self._run(
            r"""
__emit({ vide: M.__h.merge(undefined), nul: M.__h.merge(null), texte: M.__h.merge("oui") });
"""
        )

        for cas in ("vide", "nul", "texte"):
            with self.subTest(cas=cas):
                self.assertIs(res[cas]["enabled"], False)
                self.assertEqual(len(res[cas]["order"]), 5)
                self.assertNotIn("audio_floors", res[cas])

    def test_le_brouillon_n_aliase_pas_la_reponse_d_api(self) -> None:
        """Editer le brouillon ne doit pas modifier `_state.profilesList`.

        Sans la copie de surface, les deux pointeraient sur le MEME objet et une
        edition du brouillon corromprait la liste affichee — un defaut qu'on
        aurait introduit en corrigeant le premier.
        """
        res = self._run(
            _PROFIL_AVEC_PLANCHERS
            + r"""
await M.__h.loadProfiles();
M.__h.draft().tier_hierarchy.audio_floors.dts_x = "Reject";
__emit({ source: globalThis.__profilActif.tier_hierarchy.audio_floors.dts_x });
"""
        )

        self.assertEqual(res["source"], "Gold", "le brouillon a mute l'objet rendu par l'API")


if __name__ == "__main__":
    unittest.main(verbosity=2)
