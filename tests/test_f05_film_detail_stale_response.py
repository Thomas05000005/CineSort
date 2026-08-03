"""F05 — film-detail.js : une reponse get_film_full tardive repeignait la fiche
d'un AUTRE film, et l'action destructive portait sur le mauvais row_id.

Bug d'origine (BACKLOG35 F05) : `_reload()` ecrivait `_state.data` + rendait
sans aucun garde d'epoque. Double-clic film A (lent, TMDb froid) puis film B
(rapide) -> B s'affiche, puis la reponse de A repeint l'overlay de B alors que
`_state.rowId` vaut toujours B. `_handleAction` prenait `row` dans
`_state.data` (A, affiche) mais `rowId` dans `_state.rowId` (B) : la modale de
confirmation montrait A et `library/mark_for_deletion` partait sur B.

Les tests executent la VRAIE source du module sous Node (imports stubbes) :
c'est bien l'entrelacement reel de deux `renderFilmDetail` concurrents qui est
verifie.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, node_check, require_node, run_module_test

JS = ROOT / "web" / "dashboard" / "components" / "film-detail.js"

STUBS = r"""
globalThis.__posts = [];
globalThis.__toasts = [];
globalThis.__confirms = [];
globalThis.__latency = { ROWA: 200, ROWB: 0 };

const apiPost = async (endpoint, body) => {
  globalThis.__posts.push({ endpoint, body: JSON.parse(JSON.stringify(body || {})) });
  if (endpoint === "library/get_film_full") {
    const rid = String(body.row_id);
    await new Promise((r) => setTimeout(r, globalThis.__latency[rid] || 0));
    if (globalThis.__failRow === rid) {
      return { status: 500, data: { ok: false, user_message: "Boom " + rid } };
    }
    return {
      status: 200,
      data: {
        ok: true,
        row_id: rid,
        run_id: body.run_id,
        row: { row_id: rid, proposed_title: "FILM " + rid, proposed_year: 2001, source_path: "/x/" + rid },
        candidates: [],
      },
    };
  }
  return { status: 200, data: { ok: true } };
};
const escapeHtml = (s) => String(s == null ? "" : s);
const posterProxyUrl = (u) => u;
const labelsForFlags = () => [];
const countBySeverity = () => ({});
const dangerConfirmModal = (o) => { globalThis.__confirms.push({ title: o.title, items: o.items }); };
const showModal = () => {};
const closeModal = () => {};
const trapFocus = () => () => {};
const showToast = (o) => { globalThis.__toasts.push(o); };
const openPerceptualModal = () => {};
const rightPanel = { setWidth() {}, setExpanded() {}, setSections() {} };

function __fakeEl() {
  const el = {
    _html: "",
    _writes: [],
    addEventListener() {}, removeEventListener() {},
    querySelector: () => null,
    querySelectorAll: () => [],
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    remove() {}, focus() {},
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; },
    set(v) { el._html = String(v); el._writes.push(String(v)); },
  });
  return el;
}
globalThis.__fakeEl = __fakeEl;

globalThis.window = globalThis.window || {
  addEventListener() {}, removeEventListener() {}, location: { hash: "" },
};
globalThis.document = globalThis.document || {
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => null,
  createElement: () => __fakeEl(),
  addEventListener() {}, removeEventListener() {},
  body: { classList: { add() {}, remove() {} }, appendChild() {} },
};
"""

EXTRA = r"""
export const __h = { handleAction: _handleAction, reload: _reload };
"""


class F05StaleFilmDetailResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(JS, stubs=STUBS, extra=EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_reponse_tardive_ne_repeint_pas_la_fiche_de_lautre_film(self):
        """ROUGE avant fix : la reponse de A (lente) ecrasait la fiche de B."""
        res = self._run(r"""
const el = globalThis.__fakeEl();
const pA = M.renderFilmDetail({ mode: "B", rowId: "ROWA", runId: "run1", container: el });
await globalThis.__sleep(20);
const pB = M.renderFilmDetail({ mode: "B", rowId: "ROWB", runId: "run1", container: el });
await Promise.all([pA, pB]);
await globalThis.__sleep(400);
const st = M.__testing._state;
__emit({
  finalHtmlHasA: el.innerHTML.includes("FILM ROWA"),
  finalHtmlHasB: el.innerHTML.includes("FILM ROWB"),
  stateRowId: st.rowId,
  dataRowId: st.data ? st.data.row_id : null,
});
""")
        self.assertFalse(res["finalHtmlHasA"], "la reponse perimee de A ne doit pas repeindre l'overlay")
        self.assertTrue(res["finalHtmlHasB"], "la fiche affichee doit rester celle de B")
        self.assertEqual(res["stateRowId"], "ROWB")
        self.assertEqual(res["dataRowId"], "ROWB", "_state.data doit rester le payload de B")

    def test_action_destructive_confirme_et_poste_le_meme_film(self):
        """ROUGE avant fix : la modale confirmait FILM ROWA et le POST
        mark_for_deletion portait row_id=ROWB."""
        res = self._run(r"""
const el = globalThis.__fakeEl();
const pA = M.renderFilmDetail({ mode: "B", rowId: "ROWA", runId: "run1", container: el });
await globalThis.__sleep(20);
const pB = M.renderFilmDetail({ mode: "B", rowId: "ROWB", runId: "run1", container: el });
await Promise.all([pA, pB]);
await globalThis.__sleep(400);
await M.__h.handleAction("mark-delete", null);
__emit({ confirms: globalThis.__confirms, toasts: globalThis.__toasts });
""")
        self.assertEqual(len(res["confirms"]), 1, "la modale de confirmation doit s'ouvrir")
        items = " | ".join(res["confirms"][0]["items"])
        self.assertIn("FILM ROWB", items, "la confirmation doit porter sur le film affiche (B)")
        self.assertNotIn("FILM ROWA", items)

    def test_erreur_tardive_n_efface_pas_la_fiche_affichee(self):
        """ROUGE avant fix : l'echec du chargement de A vidait _state.data et
        remplacait la fiche de B par un ecran d'erreur."""
        res = self._run(r"""
globalThis.__failRow = "ROWA";
const el = globalThis.__fakeEl();
const pA = M.renderFilmDetail({ mode: "B", rowId: "ROWA", runId: "run1", container: el });
await globalThis.__sleep(20);
const pB = M.renderFilmDetail({ mode: "B", rowId: "ROWB", runId: "run1", container: el });
await Promise.all([pA, pB]);
await globalThis.__sleep(400);
const st = M.__testing._state;
__emit({
  hasError: el.innerHTML.includes("data-film-retry"),
  dataRowId: st.data ? st.data.row_id : null,
  htmlHasB: el.innerHTML.includes("FILM ROWB"),
});
""")
        self.assertFalse(res["hasError"], "l'ecran d'erreur de A ne doit pas remplacer la fiche de B")
        self.assertEqual(res["dataRowId"], "ROWB")
        self.assertTrue(res["htmlHasB"])

    def test_fermeture_pendant_le_vol_ne_repeint_rien(self):
        """closeFilmDetail() doit invalider la reponse encore en vol."""
        res = self._run(r"""
const el = globalThis.__fakeEl();
const pA = M.renderFilmDetail({ mode: "B", rowId: "ROWA", runId: "run1", container: el });
await globalThis.__sleep(20);
M.closeFilmDetail();
await pA;
await globalThis.__sleep(400);
const st = M.__testing._state;
__emit({ dataAfter: st.data, rowIdAfter: st.rowId, htmlHasA: el.innerHTML.includes("FILM ROWA") });
""")
        self.assertIsNone(res["dataAfter"], "aucune donnee ne doit etre publiee apres fermeture")
        self.assertIsNone(res["rowIdAfter"])
        self.assertFalse(res["htmlHasA"])

    # -------------------------------------------------- NON-REGRESSION
    def test_nonreg_ouverture_simple_affiche_bien_le_film(self):
        """Le cas nominal (une seule ouverture) doit rester intact : skeleton
        puis fiche complete, _state.data publie."""
        res = self._run(r"""
const el = globalThis.__fakeEl();
await M.renderFilmDetail({ mode: "B", rowId: "ROWB", runId: "run1", container: el });
const st = M.__testing._state;
__emit({
  writes: el._writes.length,
  firstIsSkeleton: el._writes[0].includes("film-detail-skeleton") || el._writes[0].includes("skeleton"),
  htmlHasB: el.innerHTML.includes("FILM ROWB"),
  dataRowId: st.data ? st.data.row_id : null,
  loading: st.loading,
});
""")
        self.assertGreaterEqual(res["writes"], 2, "skeleton puis rendu final")
        self.assertTrue(res["firstIsSkeleton"])
        self.assertTrue(res["htmlHasB"])
        self.assertEqual(res["dataRowId"], "ROWB")
        self.assertFalse(res["loading"])

    def test_nonreg_action_destructive_nominale_poste_le_bon_row_id(self):
        """Sans concurrence, mark-delete confirme ET poste le film ouvert."""
        res = self._run(r"""
const el = globalThis.__fakeEl();
await M.renderFilmDetail({ mode: "B", rowId: "ROWB", runId: "run1", container: el });
await M.__h.handleAction("mark-delete", null);
__emit({ confirms: globalThis.__confirms, toasts: globalThis.__toasts });
""")
        self.assertEqual(len(res["confirms"]), 1)
        self.assertIn("FILM ROWB", " | ".join(res["confirms"][0]["items"]))
        self.assertEqual(res["toasts"], [], "aucun toast d'avertissement dans le cas nominal")

    def test_nonreg_rechargement_successif_du_meme_film(self):
        """Deux _reload() successifs sur le meme film : le dernier gagne, la
        fiche reste peinte (le garde d'epoque ne doit rien bloquer ici)."""
        res = self._run(r"""
const el = globalThis.__fakeEl();
await M.renderFilmDetail({ mode: "B", rowId: "ROWB", runId: "run1", container: el });
await M.__h.reload();
await M.__h.reload();
const st = M.__testing._state;
__emit({ htmlHasB: el.innerHTML.includes("FILM ROWB"), dataRowId: st.data ? st.data.row_id : null });
""")
        self.assertTrue(res["htmlHasB"])
        self.assertEqual(res["dataRowId"], "ROWB")

    def test_nonreg_syntaxe_du_module(self):
        node_check(self, JS)


if __name__ == "__main__":
    unittest.main()
