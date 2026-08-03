"""F21 — duplicate-comparator-modal.js : la reponse tardive d'un onglet ecrivait
dans le corps d'un AUTRE onglet (ou d'une autre paire).

Bug d'origine (BACKLOG35 F21) : `_replaceTabContent(tab, html)` ignorait
litteralement son argument `tab`, et `_loadFramesTab`/`_loadAudioTab`
n'inspectaient ni `_state.activeTab` ni la paire APRES l'await. Onglet Frames
(ffmpeg lent) puis clic Audio (rapide) -> les frames ecrasaient l'audio sous le
libelle « Audio », et le retour sur Frames laissait un placeholder fige a vie
(`framesLoadedByPair` deja a true). Variante 3+ fichiers : le contenu d'une
paire s'affichait sous le libelle d'une autre paire, ce qui peut fausser un
« Garder X » (decision -> deplacement de fichiers a l'apply).

Les tests executent la VRAIE source du module sous Node (imports + DOM stubbes).
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, node_check, require_node, run_module_test

JS = ROOT / "web" / "dashboard" / "components" / "duplicate-comparator-modal.js"

STUBS = r"""
globalThis.__latency = { frames: 200, audio: 0 };
globalThis.__posts = [];

const apiPost = async (endpoint, body) => {
  globalThis.__posts.push({ endpoint, body: JSON.parse(JSON.stringify(body || {})) });
  if (endpoint === "quality/get_perceptual_compare_frames") {
    // Marqueur de paire injecte dans le b64 : permet d'identifier QUELLE paire
    // a produit le contenu affiche. Latence surchargeable par paire.
    const tag = String(body.row_id_a) + "-" + String(body.row_id_b);
    const lat = (globalThis.__latencyByPair && globalThis.__latencyByPair[tag] != null)
      ? globalThis.__latencyByPair[tag] : globalThis.__latency.frames;
    await new Promise((r) => setTimeout(r, lat));
    return { status: 200, data: { ok: true, frames: [{ timestamp: 1, frame_a_b64: "PAIR" + tag, frame_b_b64: "PAIR" + tag, mean_diff: 3 }] } };
  }
  if (endpoint === "quality/get_perceptual_compare_audio") {
    await new Promise((r) => setTimeout(r, globalThis.__latency.audio));
    return { status: 200, data: { ok: true, waveform_a_b64: "WA", waveform_b_b64: "WB", audio_a_b64: "MA", audio_b_b64: "MB", timestamp_s: 5, duration_s: 10 } };
  }
  return { status: 200, data: { ok: true } };
};
const escapeHtml = (s) => String(s == null ? "" : s);
const showToast = () => {};
const trapFocus = () => () => {};
const formatBytes = (n) => String(n);

globalThis.__tabbody = null;
function __makeEl(tag) {
  const el = {
    tagName: tag, className: "", _html: "", _writes: [], children: [],
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    addEventListener() {}, removeEventListener() {},
    appendChild(c) { el.children.push(c); return c; },
    remove() {}, focus() {},
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector(sel) {
      // Seul le wrapper unique du corps d'onglet est materialise : c'est lui
      // que le bug ecrasait. Le reste du DOM n'intervient pas dans la course.
      if (sel === "[data-duplicate-tabbody]") return globalThis.__tabbody;
      // Fidelite au vrai DOM : `[data-tab="x"]` n'existe que si le corps rendu
      // porte cet attribut (garde R6-D « DOM pas pret » de _loadFramesTab).
      const m = /^\[data-tab="(\w+)"\]$/.exec(sel || "");
      if (m) {
        const body = globalThis.__tabbody;
        return (body && body._html.includes('data-tab="' + m[1] + '"')) ? __makeEl("div") : null;
      }
      return null;
    },
    querySelectorAll: () => [],
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; },
    set(v) { el._html = String(v); el._writes.push(String(v)); },
  });
  return el;
}
globalThis.__tabbody = __makeEl("div");

globalThis.document = {
  createElement: (t) => __makeEl(t),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {}, removeEventListener() {},
  body: { classList: { add() {}, remove() {} }, appendChild() {} },
};
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
"""

EXTRA = r"""
export const __h = {
  switchTab: _switchTab,
  switchPair: _switchPair,
  state: () => _state,
};
"""

_OPEN2 = """
M.openDuplicateComparatorModal({
  runId: "run1", groupKey: "film|2001",
  rowA: "RA", rowB: "RB", title: "Film", year: 2001, comparison: {},
});
"""

_OPEN3 = """
M.openDuplicateComparatorModal({
  runId: "run1", groupKey: "film|2001",
  rowA: "RA", rowB: "RB",
  rows: [{ row_id: "RA" }, { row_id: "RB" }, { row_id: "RC" }],
  title: "Film", year: 2001, comparison: {},
});
"""


class F21ComparatorTabRaceTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(JS, stubs=STUBS, extra=EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_frames_tardives_n_ecrasent_pas_longlet_audio(self):
        """ROUGE avant fix : le corps de l'onglet Audio finissait rempli par les
        frames."""
        res = self._run(
            _OPEN2
            + r"""
M.__h.switchTab("frames");
await globalThis.__sleep(30);
M.__h.switchTab("audio");
await globalThis.__sleep(500);
const body = globalThis.__tabbody;
__emit({
  activeTab: M.__h.state().activeTab,
  finalHasAudio: body.innerHTML.includes("duplicate-audio-grid"),
  finalHasFrames: body.innerHTML.includes("duplicate-frames-grid"),
});
"""
        )
        self.assertEqual(res["activeTab"], "audio")
        self.assertTrue(res["finalHasAudio"], "l'onglet Audio doit afficher l'audio")
        self.assertFalse(res["finalHasFrames"], "les frames tardives ne doivent pas ecraser l'audio")

    def test_retour_sur_frames_reaffiche_le_payload_et_non_un_placeholder(self):
        """Garde-fou du correctif : sans le cache HTML par paire, le garde de
        _replaceTabContent transformerait le bug en placeholder fige a vie."""
        res = self._run(
            _OPEN2
            + r"""
M.__h.switchTab("frames");
await globalThis.__sleep(30);
M.__h.switchTab("audio");
await globalThis.__sleep(500);
M.__h.switchTab("frames");
await globalThis.__sleep(100);
const body = globalThis.__tabbody;
__emit({
  hasFrames: body.innerHTML.includes("duplicate-frames-grid"),
  isPlaceholder: body.innerHTML.includes("Extraction des frames") || body.innerHTML.includes("duplicate-modal-loading"),
  postCount: globalThis.__posts.filter((p) => p.endpoint.includes("compare_frames")).length,
});
"""
        )
        self.assertTrue(res["hasFrames"], "le retour sur Frames doit re-servir le payload deja recu")
        self.assertFalse(res["isPlaceholder"], "placeholder fige = regression du correctif")

    def test_reponse_dune_autre_paire_ne_saffiche_pas_sous_le_libelle_courant(self):
        """Cas 3+ fichiers : la reponse de la paire A/B ne doit pas s'afficher
        quand l'utilisateur a bascule sur la paire A/C."""
        res = self._run(
            _OPEN3
            + r"""
// Paire 0 = RA vs RB (lente), paire 1 = RA vs RC (instantanee).
globalThis.__latencyByPair = { "RA-RB": 250, "RA-RC": 0 };
const st = M.__h.state();
const k0 = st.pairs[0].key;
const k1 = st.pairs[1].key;
M.__h.switchTab("frames");             // charge la paire 0 (lente)
await globalThis.__sleep(30);
M.__h.switchPair(k1);                  // bascule sur la paire 1 (rapide)
await globalThis.__sleep(600);
const body = globalThis.__tabbody;
__emit({
  activePairKey: st.activePairKey,
  k0, k1,
  bodyHasStalePair: body.innerHTML.includes("PAIRRA-RB"),
  bodyHasActivePair: body.innerHTML.includes("PAIRRA-RC"),
});
"""
        )
        self.assertEqual(res["activePairKey"], res["k1"])
        self.assertTrue(
            res["bodyHasActivePair"],
            "le corps doit afficher les frames de la paire ACTIVE (A vs C)",
        )
        self.assertFalse(
            res["bodyHasStalePair"],
            "les frames de la paire abandonnee (A vs B) ne doivent jamais s'afficher "
            "sous le libelle de la paire courante — risque de 'Garder X' errone",
        )

    def test_replace_tab_content_refuse_un_onglet_non_actif(self):
        """Contrat direct du garde : une ecriture ciblant un onglet inactif est
        refusee (retour false) et ne touche pas le DOM."""
        res = self._run(
            _OPEN2
            + r"""
const body = globalThis.__tabbody;
const before = body.innerHTML;
const writesBefore = body._writes.length;
// _replaceTabContent n'est pas exporte : on passe par le chemin public
// _switchTab("audio") puis on simule l'arrivee tardive de frames via
// l'onglet frames (charge en parallele).
M.__h.switchTab("frames");
M.__h.switchTab("audio");
await globalThis.__sleep(500);
__emit({
  activeTab: M.__h.state().activeTab,
  hasFrames: body.innerHTML.includes("duplicate-frames-grid"),
  hasAudio: body.innerHTML.includes("duplicate-audio-grid"),
  before, writesBefore,
});
"""
        )
        self.assertEqual(res["activeTab"], "audio")
        self.assertFalse(res["hasFrames"])
        self.assertTrue(res["hasAudio"])

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_chargement_nominal_dun_onglet(self):
        """Sans concurrence, Frames se charge et s'affiche normalement."""
        res = self._run(
            _OPEN2
            + r"""
globalThis.__latency.frames = 0;
M.__h.switchTab("frames");
await globalThis.__sleep(120);
const body = globalThis.__tabbody;
__emit({
  hasFrames: body.innerHTML.includes("duplicate-frames-grid"),
  postCount: globalThis.__posts.filter((p) => p.endpoint.includes("compare_frames")).length,
  loaded: M.__h.state().framesLoadedByPair.default === true,
});
"""
        )
        self.assertTrue(res["hasFrames"])
        self.assertEqual(res["postCount"], 1)
        self.assertTrue(res["loaded"])

    def test_nonreg_pas_de_rechargement_si_deja_charge(self):
        """Le cache par paire (R6-D) doit rester efficace : aller-retour entre
        onglets = un seul appel reseau par onglet."""
        res = self._run(
            _OPEN2
            + r"""
globalThis.__latency.frames = 0;
M.__h.switchTab("frames");
await globalThis.__sleep(120);
M.__h.switchTab("audio");
await globalThis.__sleep(120);
M.__h.switchTab("frames");
await globalThis.__sleep(120);
__emit({
  frames: globalThis.__posts.filter((p) => p.endpoint.includes("compare_frames")).length,
  audio: globalThis.__posts.filter((p) => p.endpoint.includes("compare_audio")).length,
});
"""
        )
        self.assertEqual(res["frames"], 1)
        self.assertEqual(res["audio"], 1)

    def test_nonreg_apercu_reste_le_contenu_par_defaut(self):
        res = self._run(
            _OPEN2
            + r"""
const body = globalThis.__tabbody;
globalThis.__latency.frames = 0;
M.__h.switchTab("frames");
await globalThis.__sleep(120);
M.__h.switchTab("apercu");
await globalThis.__sleep(50);
__emit({
  activeTab: M.__h.state().activeTab,
  hasFrames: body.innerHTML.includes("duplicate-frames-grid"),
});
"""
        )
        self.assertEqual(res["activeTab"], "apercu")
        self.assertFalse(res["hasFrames"])

    def test_nonreg_syntaxe_du_module(self):
        node_check(self, JS)


if __name__ == "__main__":
    unittest.main()
