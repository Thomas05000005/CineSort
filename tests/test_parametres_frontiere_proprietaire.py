"""Issue #1094 — l'ecran Parametres effacait des reglages qu'il ne possede pas.

`settings/save_settings` porte la bonne garde cote backend : « cle ABSENTE =
silence, cle presente et VIDE = demande » (`settings_support.py`,
`_save_section_quality_profiles` / `_save_section_probe` /
`_save_section_scan_max_workers`). Le diagnostic qui l'a fait ecrire est juste.

Mais elle ne pouvait JAMAIS se declencher depuis l'ecran :

1. `apply_settings_defaults` injecte TOUJOURS ces cles dans le payload du GET
   (via `_LITERAL_DEFAULTS`), et `_mask_secrets` ne les touche pas ;
2. l'ecran fige ce payload a l'ouverture (`_state.settings = res.data.data`) et
   le re-POSTe EN BLOC a chaque champ modifie (`_scheduleSave`) ;
3. des routes DEDIEES ecrivent ces memes cles derriere l'ecran
   (`save_profile`, `set_active_profile`, `auto_install_probe_tools`,
   `set_scan_max_workers`) sans jamais mettre `_state.settings` a jour.

D'ou trois sequences vecues, toutes sous un « ✓ Sauvegarde a HH:MM:SS » :
un profil qualite cree disparait ; une activation de profil se defait ; les
chemins d'outils qu'on vient d'installer sont effaces.

Le correctif ne REMPLACE pas la garde du backend : il la rend ATTEIGNABLE.
L'ecran cesse d'envoyer ce qu'il ne possede pas, et reporte a la source les
deux cles qu'il possede vraiment.

Les tests executent la VRAIE source du module sous Node (imports stubbes, corps
des fonctions intact) : c'est la charge utile REELLEMENT postee qui est lue,
pas la presence d'une chaine dans le fichier.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

JS = ROOT / "web" / "dashboard" / "views" / "parametres.js"

STUBS = r"""
globalThis.__calls = [];
const apiPost = async (endpoint, body) => {
  globalThis.__calls.push({ endpoint, body: JSON.parse(JSON.stringify(body || {})) });
  if (endpoint === "settings/get_settings") {
    return { status: 200, data: { ok: true, data: globalThis.__serverSettings || {} } };
  }
  return { status: 200, data: { ok: true } };
};
const invalidateSettingsCache = () => {};
const escapeHtml = (s) => String(s == null ? "" : s);
const dangerConfirmModal = () => {};
const showModal = () => {};
const trapFocus = () => () => {};

function __el() {
  const el = {
    _html: "",
    addEventListener() {}, removeEventListener() {},
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    classList: { add() {}, remove() {}, toggle() {} },
    dataset: {}, style: { setProperty() {} },
    querySelector: () => null, querySelectorAll: () => [],
    focus() {}, select() {},
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; },
    set(v) { el._html = String(v); },
  });
  return el;
}
globalThis.window = globalThis.window || { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = globalThis.document || {
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  createElement: () => __el(), addEventListener() {}, removeEventListener() {},
  body: Object.assign(__el(), { appendChild() {} }), documentElement: __el(),
};
globalThis.localStorage = globalThis.localStorage || { getItem: () => null, setItem() {}, removeItem() {} };
"""

EXTRA = r"""
export const __h = {
  state: _state,
  scheduleSave: _scheduleSave,
  reporterLesCheminsOutils: _reporterLesCheminsOutils,
};
"""

# L'instantane tel que le GET le rend : les cles possedees ailleurs sont
# TOUJOURS presentes (c'est tout le probleme), et les chemins d'outils sont
# vides tant que rien n'est installe.
INSTANTANE_OUVERTURE = r"""
st.settings = {
  theme: "luxe",
  custom_quality_profiles: [],
  active_quality_profile_id: "",
  scan_max_workers_mode: "auto",
  scan_max_workers_value: 0,
  ffprobe_path: "",
  mediainfo_path: "",
};
"""


class FrontiereDeProprietaireTests(unittest.TestCase):
    """L'autosave ne doit poster que ce que l'ecran possede."""

    def setUp(self) -> None:
        require_node(self)

    def _poster(self, driver: str) -> dict:
        return run_module_test(JS, stubs=STUBS, extra=EXTRA, driver=driver)

    def test_l_autosave_n_envoie_pas_les_cles_possedees_ailleurs(self):
        """ROUGE avant le correctif : les 4 cles partaient avec l'instantane
        perime, et le backend les ECRASAIT (cle presente = demande)."""
        res = self._poster(
            r"""
const st = M.__h.state;
st.containerRef = { querySelector: () => null };
"""
            + INSTANTANE_OUVERTURE
            + r"""
M.__h.scheduleSave();
await globalThis.__sleep(700);
const saves = globalThis.__calls.filter((c) => c.endpoint === "settings/save_settings");
__emit({
  nbSaves: saves.length,
  clesPostees: saves.length ? Object.keys(saves[0].body.settings).sort() : [],
});
"""
        )
        self.assertEqual(res["nbSaves"], 1, "l'autosave doit bien partir")
        postees = set(res["clesPostees"])
        for cle in (
            "custom_quality_profiles",
            "active_quality_profile_id",
            "scan_max_workers_mode",
            "scan_max_workers_value",
        ):
            self.assertNotIn(
                cle,
                postees,
                f"`{cle}` est ecrite par une route DEDIEE : la poster depuis "
                "l'instantane fige de l'ecran ecrase la valeur reelle",
            )

    def test_les_cles_possedees_par_l_ecran_partent_toujours(self):
        """Contre-test : le filtre ne doit pas manger les vrais champs.

        `ffprobe_path` et `mediainfo_path` SONT des champs de cet ecran — les
        filtrer empecherait l'utilisateur de les vider a la main, ce qui
        remplacerait un defaut par un autre.
        """
        res = self._poster(
            r"""
const st = M.__h.state;
st.containerRef = { querySelector: () => null };
"""
            + INSTANTANE_OUVERTURE
            + r"""
st.settings.ffprobe_path = "";        // l'utilisateur vide le champ a la main
st.settings.mediainfo_path = "D:/outils/mediainfo.exe";
M.__h.scheduleSave();
await globalThis.__sleep(700);
const saves = globalThis.__calls.filter((c) => c.endpoint === "settings/save_settings");
const s = saves.length ? saves[0].body.settings : {};
__emit({
  aTheme: Object.prototype.hasOwnProperty.call(s, "theme"),
  aFfprobe: Object.prototype.hasOwnProperty.call(s, "ffprobe_path"),
  aMediainfo: Object.prototype.hasOwnProperty.call(s, "mediainfo_path"),
  mediainfo: s.mediainfo_path,
});
"""
        )
        self.assertTrue(res["aTheme"], "les champs ordinaires doivent partir")
        self.assertTrue(
            res["aFfprobe"],
            "vider `ffprobe_path` a la main est une DEMANDE de l'utilisateur : "
            "la cle doit partir, sinon le champ devient inutilisable",
        )
        self.assertTrue(res["aMediainfo"])
        self.assertEqual(res["mediainfo"], "D:/outils/mediainfo.exe")

    def test_les_chemins_installes_sont_reportes_dans_l_instantane(self):
        """ROUGE avant le correctif : `_state.settings` gardait les chaines
        vides d'ouverture, que l'autosave suivant repostait — et que
        `_save_section_probe` lit comme « cle presente et VIDE = EFFACE »."""
        res = self._poster(
            r"""
const st = M.__h.state;
st.containerRef = { querySelector: () => null };
"""
            + INSTANTANE_OUVERTURE
            + r"""
// Ce que renvoie `runtime/auto_install_probe_tools` apres installation.
M.__h.reporterLesCheminsOutils({
  ffprobe_path: "C:/outils/ffprobe.exe",
  mediainfo_path: "C:/outils/mediainfo.exe",
});
M.__h.scheduleSave();
await globalThis.__sleep(700);
const saves = globalThis.__calls.filter((c) => c.endpoint === "settings/save_settings");
const s = saves.length ? saves[0].body.settings : {};
__emit({ ffprobe: s.ffprobe_path, mediainfo: s.mediainfo_path });
"""
        )
        self.assertEqual(
            res["ffprobe"],
            "C:/outils/ffprobe.exe",
            "sans le report, l'autosave reposte la chaine VIDE d'ouverture et "
            "efface le chemin qu'on vient d'installer",
        )
        self.assertEqual(res["mediainfo"], "C:/outils/mediainfo.exe")

    def test_un_status_partiel_n_efface_rien(self):
        """Le report ne doit ecrire que ce qui est REELLEMENT resolu : un
        `status` sans chemin (installation partielle) ne doit pas remplacer une
        valeur existante par une chaine vide."""
        res = self._poster(
            r"""
const st = M.__h.state;
st.containerRef = { querySelector: () => null };
"""
            + INSTANTANE_OUVERTURE
            + r"""
st.settings.ffprobe_path = "C:/deja/ffprobe.exe";
M.__h.reporterLesCheminsOutils({ ffprobe_path: "", mediainfo_path: null });
__emit({ ffprobe: st.settings.ffprobe_path, mediainfo: st.settings.mediainfo_path });
"""
        )
        self.assertEqual(
            res["ffprobe"],
            "C:/deja/ffprobe.exe",
            "un status vide ne doit PAS ecraser un chemin deja connu",
        )
        self.assertEqual(res["mediainfo"], "")


if __name__ == "__main__":
    unittest.main()
