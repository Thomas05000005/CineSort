"""Le rapport d'un run doit se telecharger avec son contenu EXACT.

`run/export_run_report` existait, testee cote backend, et n'etait appelee par
AUCUN code du dashboard : `grep -rn "export_run_report" web/` ne rendait rien.

CE QUI SEMBLAIT L'EXCLURE, ET POURQUOI C'ETAIT FAUX. Elle ecrit un fichier cote
SERVEUR (`write_run_report_file`), et un navigateur ne peut pas aller le
chercher. Mais elle rend AUSSI son contenu dans la reponse, et le commentaire de
production le dit mot pour mot : « l'UI telecharge via Blob et exige `content` ».
Le fichier serveur est un effet de bord, pas le livrable.

LE TEXTE EST PRIS TEL QUEL, ET C'EST LA PROPRIETE QUI COMPTE. Le CSV porte un
BOM UTF-8 et des CRLF, poses expres pour qu'Excel le lise -- le backend a meme
un correctif dedie pour ne pas les perdre a la relecture (`read_bytes().decode`
au lieu de `read_text`, apres un `TypeError` sur Python 3.12 qui avait tue
l'export entier). Reserialiser cote front, par exemple via un `JSON.stringify`
sur un objet reconstruit, les perdrait tous les deux et annulerait ce travail.

CE FICHIER N'EPROUVE PAS le contenu du rapport (le backend s'en charge) mais le
CHEMIN qui l'amene a l'utilisateur : la bonne route, le bon format, le contenu
non altere, et le refus signale plutot qu'avale.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

HISTORIQUE_JS = ROOT / "web" / "dashboard" / "views" / "historique.js"

#: Un CSV realiste : BOM UTF-8 en tete, CRLF en fin de ligne. Si le front
#: reserialise, l'un ou l'autre disparait — et Excel ne lit plus le fichier.
_CSV_REEL = "﻿row_id;titre\r\nr1;Heat\r\n"

_STUBS = r"""
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.__telechargements = [];
globalThis.__revoques = 0;

globalThis.URL = {
  createObjectURL(blob) { globalThis.__dernierBlob = blob; return "blob:faux"; },
  revokeObjectURL() { globalThis.__revoques += 1; },
};
globalThis.Blob = function (parts, opts) {
  this.parts = parts;
  this.type = (opts && opts.type) || "";
};
globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById() { return null; }, querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() {
    return { style: {}, click() { globalThis.__telechargements.push({ href: this.href, download: this.download }); } };
  },
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
function escapeHtml(s) { return String(s == null ? "" : s); }
function getNavSignal() { return null; }
function navigateTo() {}
function deriveRunStatus() { return "DONE"; }
globalThis.__toasts = [];
function showToast(o) { globalThis.__toasts.push(o); }
function dangerConfirmModal() { return Promise.resolve(true); }
function formatBytes() { return ""; }
function t(k) { return String(k); }
function labelForFlag(f) { return String(f); }
const rightPanel = { setWidth() {}, setExpanded() {}, setContent() {} };
"""

_EXTRA = "export const __exporter = _exporterLeRapport;\n"
_EXIT = "\nprocess.exit(0);\n"

_BOUTON = 'const btn = { disabled: false, textContent: "⬇ Exporter" };\n'


class LExportAPPELLELaBonneRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(HISTORIQUE_JS, stubs=_STUBS, extra=_EXTRA, driver=_BOUTON + driver + _EXIT, timeout=90)

    def test_la_route_et_le_format_sont_transmis(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["run/export_run_report"] = { ok: true, content: "a;b", rows_total: 2 };
await M.__exporter("run-42", "csv", btn);
__emit({ appels: globalThis.__appels });
"""
        )
        self.assertEqual(len(res["appels"]), 1)
        self.assertEqual(res["appels"][0]["route"], "run/export_run_report")
        self.assertEqual(res["appels"][0]["params"]["run_id"], "run-42")
        self.assertEqual(res["appels"][0]["params"]["fmt"], "csv")

    def test_le_format_est_normalise_en_minuscules(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["run/export_run_report"] = { ok: true, content: "x" };
await M.__exporter("run-1", "CSV", btn);
__emit({ fmt: globalThis.__appels[0].params.fmt });
"""
        )
        self.assertEqual(res["fmt"], "csv")


class LeCONTENUNEstPasALTERETests(unittest.TestCase):
    """LE test. Un BOM ou un CRLF perdu rend le CSV illisible par Excel."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(HISTORIQUE_JS, stubs=_STUBS, extra=_EXTRA, driver=_BOUTON + driver + _EXIT, timeout=90)

    def test_le_texte_du_serveur_passe_tel_quel_dans_le_blob(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["run/export_run_report"] = { ok: true, content: %s, rows_total: 1 };
await M.__exporter("run-7", "csv", btn);
__emit({ parts: globalThis.__dernierBlob.parts, type: globalThis.__dernierBlob.type });
"""
            % _js_str(_CSV_REEL)
        )
        self.assertEqual(res["parts"], [_CSV_REEL], "le contenu a ete altere entre le serveur et le fichier")
        self.assertIn("csv", res["type"])

    def test_le_nom_de_fichier_porte_le_run_et_le_format(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["run/export_run_report"] = { ok: true, content: "x" };
await M.__exporter("run-99", "json", btn);
__emit({ tel: globalThis.__telechargements });
"""
        )
        self.assertEqual(len(res["tel"]), 1)
        self.assertEqual(res["tel"][0]["download"], "cinesort-rapport-run-99.json")

    def test_l_URL_temporaire_est_LIBEREE(self) -> None:
        """Sans revoke, chaque export garde son Blob en memoire pour la session."""
        res = self._run(
            r"""
globalThis.__reponses["run/export_run_report"] = { ok: true, content: "x" };
await M.__exporter("run-1", "json", btn);
__emit({ revoques: globalThis.__revoques });
"""
        )
        self.assertEqual(res["revoques"], 1)


class UnECHECEstSIGNALEPasAvaleTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(HISTORIQUE_JS, stubs=_STUBS, extra=_EXTRA, driver=_BOUTON + driver + _EXIT, timeout=90)

    def test_un_refus_du_backend_ne_telecharge_RIEN(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["run/export_run_report"] = { ok: false, user_message: "Run introuvable." };
await M.__exporter("run-x", "csv", btn);
__emit({ tel: globalThis.__telechargements.length, toasts: globalThis.__toasts.map((t) => t.type), texte: globalThis.__toasts[0].text });
"""
        )
        self.assertEqual(res["tel"], 0, "un fichier a ete telecharge malgre le refus")
        self.assertIn("error", res["toasts"])
        self.assertEqual(res["texte"], "Run introuvable.")

    def test_une_reponse_SANS_content_est_traitee_comme_un_echec(self) -> None:
        """`ok: true` sans texte donnerait un fichier VIDE, silencieusement."""
        res = self._run(
            r"""
globalThis.__reponses["run/export_run_report"] = { ok: true, rows_total: 0 };
await M.__exporter("run-y", "csv", btn);
__emit({ tel: globalThis.__telechargements.length, toasts: globalThis.__toasts.map((t) => t.type) });
"""
        )
        self.assertEqual(res["tel"], 0, "un fichier vide a ete telecharge")
        self.assertIn("error", res["toasts"])

    def test_le_bouton_est_reactive_meme_apres_un_echec(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["run/export_run_report"] = { ok: false, message: "boum" };
await M.__exporter("run-z", "csv", btn);
__emit({ disabled: btn.disabled, texte: btn.textContent });
"""
        )
        self.assertFalse(res["disabled"])
        self.assertEqual(res["texte"], "⬇ Exporter", "le libelle du bouton n'a pas ete restaure")


def _js_str(s: str) -> str:
    """Litteral JS d'une chaine, echappements compris (BOM et CRLF inclus)."""
    import json

    return json.dumps(s)


if __name__ == "__main__":
    unittest.main()
