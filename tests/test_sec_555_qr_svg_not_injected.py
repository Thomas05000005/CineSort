"""Issue #555 — le SVG du QR code n'est plus injecte comme markup.

Defaut d'origine (`web/dashboard/views/parametres.js`) :

    ${qrSvg ? `<div class="parametres-qr-svg">${qrSvg}</div>` : ""}

Le SVG renvoye par `settings/get_dashboard_qr` etait interpole brut dans
`host.innerHTML`, alors que l'URL voisine du MEME template passait deja par
`_esc()`. Severite basse et assumee telle quelle : le SVG est genere par segno
cote serveur, pas saisi par l'utilisateur. Le grief vaut en defense en
profondeur — le jour ou segno change, ou ou le backend renvoie autre chose.

Correctif : le SVG est rendu via `<img src="data:image/svg+xml,...">`. Un SVG
charge en contexte IMAGE ne peut ni executer de script ni charger de ressource
externe (specification SVG), et `encodeURIComponent` percent-encode `<`, `>`,
`"` et `&`, donc la chaine ne peut pas sortir de l'attribut. Aucune liste noire
de balises a maintenir.

Les tests executent la VRAIE source du module sous Node (imports stubbes, corps
des fonctions intact) : c'est bien le template de production qui produit la
chaine qu'on inspecte, pas une reimplementation.
"""

from __future__ import annotations

import json
import unittest

from tests._jsexec import ROOT, node_check, require_node, run_module_test

JS = ROOT / "web" / "dashboard" / "views" / "parametres.js"

STUBS = r"""
globalThis.__qrPayload = { ok: true, svg: "", url: "http://192.168.1.20:8642/dashboard/" };
const apiPost = async (endpoint) => {
  if (endpoint === "settings/get_dashboard_qr") return { status: 200, data: globalThis.__qrPayload };
  if (endpoint === "settings/get_server_info") {
    return { status: 200, data: { ok: true, dashboard_url: "http://192.168.1.20:8642/dashboard/" } };
  }
  return { status: 200, data: { ok: true } };
};
const invalidateSettingsCache = () => {};
const escapeHtml = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
const dangerConfirmModal = () => {};
const showModal = () => {};
const trapFocus = () => () => {};

function __el(name) {
  const el = {
    _name: name, _html: "",
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
globalThis.__host = __el("qr-host");
globalThis.__container = __el("container");
globalThis.__container.querySelector = (sel) => (
  String(sel).includes("data-qr-dashboard") ? globalThis.__host : null
);
globalThis.window = globalThis.window || { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = globalThis.document || {
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  createElement: () => __el("created"), addEventListener() {}, removeEventListener() {},
  body: Object.assign(__el("body"), { appendChild() {} }), documentElement: __el("html"),
};
globalThis.localStorage = globalThis.localStorage || { getItem: () => null, setItem() {}, removeItem() {} };
"""

EXTRA = r"""
export const __h = {
  state: _state,
  loadQrDashboard: _loadQrDashboard,
  svgToDataUri: _qrSvgToDataUri,
};
"""

# SVG reellement emis par segno (scale=5, border=2, svgns=True).
SEGNO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="165" height="165" class="segno">'
    '<g transform="scale(5)"><path fill="#0a0a0f" d="M0 0h33v33h-33z"/>'
    '<path class="qrline" stroke="#e0e0e8" d="M2 2.5h7m2 0h1"/></g></svg>\n'
)

# Charges hostiles : ce que renverrait un backend compromis ou une future
# bibliotheque de generation qui laisserait passer autre chose qu'un QR.
HOSTILE = (
    '<svg xmlns="http://www.w3.org/2000/svg" onload="globalThis.__PWNED = 1">'
    "<script>globalThis.__PWNED = 2;</script>"
    '<image href="x" onerror="globalThis.__PWNED = 3">'
    "</svg>"
)


class QrSvgRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _render(self, svg: str) -> dict:
        driver = """
const st = M.__h.state;
st.settings = { rest_api_enabled: true, rest_api_token: "un-token-de-32-caracteres-minimum" };
globalThis.__qrPayload = { ok: true, svg: %s, url: "http://192.168.1.20:8642/dashboard/" };
await M.__h.loadQrDashboard(globalThis.__container);
__emit({ html: globalThis.__host.innerHTML, pwned: globalThis.__PWNED ?? null });
""" % json.dumps(svg)
        return run_module_test(JS, stubs=STUBS, extra=EXTRA, driver=driver)

    # ---------------------------------------------------------------- ROUGE
    def test_le_markup_hostile_natteint_jamais_le_dom(self) -> None:
        """ROUGE avant fix : `<script>` et `onload=` arrivaient tels quels dans
        `host.innerHTML`."""
        res = self._render(HOSTILE)
        html = res["html"]

        self.assertNotIn("<script", html, f"markup de script injecte dans le DOM : {html!r}")
        self.assertNotIn("onload=", html, "gestionnaire d'evenement injecte dans le DOM")
        self.assertNotIn("onerror=", html)
        self.assertNotIn("<svg", html, "le SVG ne doit plus etre insere en tant que markup")
        self.assertIsNone(res["pwned"], "du code du payload s'est execute")

    def test_le_svg_hostile_est_percent_encode_dans_lattribut(self) -> None:
        """Le contenu n'est pas jete : il est neutralise. On verifie qu'il est
        bien present, mais sous forme encodee — sinon le test precedent
        passerait aussi avec un correctif qui supprime le QR."""
        res = self._render(HOSTILE)
        html = res["html"]

        self.assertIn("data:image/svg+xml", html, "le QR doit toujours etre rendu")
        self.assertIn("%3Cscript%3E", html, "le markup doit etre percent-encode, pas supprime")

    # -------------------------------------------------- NON-REGRESSION
    def test_le_qr_legitime_reste_rendu_a_lidentique(self) -> None:
        """Le QR de segno doit rester affichable : le data URI doit redonner le
        SVG d'origine, octet pour octet."""
        res = self._render(SEGNO_SVG)
        html = res["html"]

        self.assertIn('<img src="data:image/svg+xml;charset=utf-8,', html)
        debut = html.index("data:image/svg+xml;charset=utf-8,") + len("data:image/svg+xml;charset=utf-8,")
        fin = html.index('"', debut)
        from urllib.parse import unquote

        self.assertEqual(
            unquote(html[debut:fin]),
            SEGNO_SVG.strip(),
            "le SVG doit etre restitue tel quel : sinon le QR ne serait plus scannable",
        )
        self.assertIn("alt=", html, "l'image doit rester accessible (lecteur d'ecran)")

    def test_le_namespace_svg_est_present_dans_le_data_uri(self) -> None:
        """Un SVG charge en contexte IMAGE doit etre un document autonome :
        sans `xmlns`, le navigateur n'affiche rien. C'est ce qui justifie
        `svgns=True` cote backend."""
        res = self._render(SEGNO_SVG)
        self.assertIn("http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg", res["html"])

    def test_absence_de_qr_naffiche_pas_de_conteneur_vide(self) -> None:
        res = self._render("")
        self.assertNotIn("data:image/svg+xml", res["html"])
        self.assertNotIn("parametres-qr-svg", res["html"])

    def test_lurl_voisine_reste_echappee(self) -> None:
        """Non-regression sur l'echappement deja en place dans le meme template."""
        driver = r"""
const st = M.__h.state;
st.settings = { rest_api_enabled: true, rest_api_token: "un-token-de-32-caracteres-minimum" };
globalThis.__qrPayload = { ok: true, svg: "", url: "http://x/<img onerror=1>" };
await M.__h.loadQrDashboard(globalThis.__container);
__emit({ html: globalThis.__host.innerHTML, pwned: globalThis.__PWNED ?? null });
"""
        res = run_module_test(JS, stubs=STUBS, extra=EXTRA, driver=driver)
        self.assertNotIn("<img onerror", res["html"])
        self.assertIn("&lt;img", res["html"])

    def test_helper_de_conversion_sur_entree_vide(self) -> None:
        res = run_module_test(
            JS,
            stubs=STUBS,
            extra=EXTRA,
            driver=r"""
__emit({
  vide: M.__h.svgToDataUri(""),
  nul: M.__h.svgToDataUri(null),
  indef: M.__h.svgToDataUri(undefined),
  espaces: M.__h.svgToDataUri("   "),
});
""",
        )
        self.assertEqual(res["vide"], "")
        self.assertEqual(res["nul"], "")
        self.assertEqual(res["indef"], "")
        self.assertEqual(res["espaces"], "")

    def test_nonreg_syntaxe_du_module(self) -> None:
        node_check(self, JS)


class QrBackendPayloadTests(unittest.TestCase):
    """Le SVG produit doit rester un document AUTONOME.

    Le rendu en `<img src="data:...">` impose le namespace SVG : sans lui, le
    navigateur n'affiche rien du tout. C'est la contrepartie backend du
    correctif frontend, et elle doit etre verrouillee cote serveur — le test JS
    ci-dessus travaille sur une constante et ne verrait pas cette regression.
    """

    def test_le_svg_genere_porte_le_namespace(self) -> None:
        from cinesort.ui.api.cinesort_api import CineSortApi

        result = CineSortApi()._get_dashboard_qr_impl()

        self.assertTrue(result["ok"])
        self.assertIn(
            'xmlns="http://www.w3.org/2000/svg"',
            result["svg"],
            'sans xmlns, le QR rendu via <img src="data:image/svg+xml,..."> reste blanc',
        )
        self.assertTrue(result["svg"].strip().startswith("<svg"))


if __name__ == "__main__":
    unittest.main()
