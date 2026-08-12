"""La generation des .nfo d'un run : apercu d'abord, ecriture ensuite.

POURQUOI CETTE METHODE ETAIT DECLAREE NON CABLABLE, ET POURQUOI C'ETAIT FAUX.
La vague B4 a refuse `run.export_run_nfo` au motif « parametre inerte et rows
sans les champs necessaires ». Le motif etait ERRONE : le parametre inerte est
`sample_row_id` de `preview_naming_template` (issue #460), une AUTRE methode,
dont le defaut est d'ailleurs deja traite — la branche morte a ete retiree et la
reponse DIT desormais `sample_row_id_applied: False`.

MESURE, sur une ligne de rapport reelle construite par `_build_row_payload` :

    folder / video / proposed_title / proposed_year / decision_title /
    decision_year -> tous presents
    export_nfo_for_run(dry_run=True) -> written 1, skipped_no_data 0, errors 0

Un motif de refus FAUX est pire que pas de motif : il arrete la personne
suivante. Celui-ci est corrige, et la methode cablee.

CE QUE CE FICHIER EPROUVE. L'action ECRIT sur le disque de l'utilisateur, a cote
de ses films : elle tombe sous la regle n3 du depot (liste, consequence, delai
au-dela de 50 elements). Le chemin est donc en DEUX TEMPS, et c'est ce
sequencement que ces tests verrouillent — le premier appel est un `dry_run`,
c'est LUI qui fournit le compte et les chemins annonces, plutot qu'une
estimation.

LE STUB DE LA MODALE EST FIDELE A LA PRODUCTION. `dangerConfirmModal` n'est pas
`async` et ne rend AUCUNE valeur : elle rappelle `onConfirm` / `onCancel`. Un
stub qui rendrait `Promise.resolve(true)` — contrat que la production n'offre
pas — laisserait vert un appelant qui `await`erait son retour, defaut mesure sur
la vague B3.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

HISTORIQUE_JS = ROOT / "web" / "dashboard" / "views" / "historique.js"

_STUBS = r"""
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.URL = { createObjectURL() { return "blob:faux"; }, revokeObjectURL() {} };
globalThis.Blob = function () {};
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
  const cle = route + "|" + (params && params.dry_run === false ? "reel" : "apercu");
  const r = Object.prototype.hasOwnProperty.call(globalThis.__reponses, cle)
    ? globalThis.__reponses[cle]
    : globalThis.__reponses[route];
  return Promise.resolve(r === undefined ? { ok: true } : r);
}
function cachedGetSettings() { return Promise.resolve({}); }
function escapeHtml(s) { return String(s == null ? "" : s); }
function getNavSignal() { return null; }
function navigateTo() {}
function deriveRunStatus() { return "DONE"; }
globalThis.__toasts = [];
function showToast(o) { globalThis.__toasts.push(o); }

globalThis.__confirmations = [];
globalThis.__accepte = true;
globalThis.__enCours = null;
// FIDELE A LA PRODUCTION : ni `async`, ni valeur de retour — des RAPPELS.
function dangerConfirmModal(o) {
  globalThis.__confirmations.push(o);
  if (globalThis.__accepte === false) {
    if (o.onCancel) o.onCancel();
    return;
  }
  globalThis.__enCours = o.onConfirm ? o.onConfirm() : null;
}
function formatBytes() { return ""; }
function t(k) { return String(k); }
function labelForFlag(f) { return String(f); }
const rightPanel = { setWidth() {}, setExpanded() {}, setContent() {} };
"""

_EXTRA = "export const __nfo = _genererLesNfo;\n"
_EXIT = "\nprocess.exit(0);\n"
_BOUTON = 'const btn = { disabled: false, textContent: "🎬 Générer les .nfo" };\n'

#: Un apercu realiste : 2 a ecrire, 1 deja present, 1 sans donnees.
_APERCU = r"""
globalThis.__reponses["run/export_run_nfo|apercu"] = {
  ok: true, dry_run: true, written: 2, skipped_existing: 1, skipped_no_data: 1, errors: 0,
  details: [
    { path: "D:/Films/Heat (1995)/Heat.nfo", status: "would_write" },
    { path: "D:/Films/Alien (1979)/Alien.nfo", status: "would_write" },
    { path: "D:/Films/Dune (2021)/Dune.nfo", status: "skipped_existing" },
  ],
};
globalThis.__reponses["run/export_run_nfo|reel"] = { ok: true, written: 2, errors: 0 };
"""


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(HISTORIQUE_JS, stubs=_STUBS, extra=_EXTRA, driver=_BOUTON + driver + _EXIT, timeout=90)


class LAPERCUPrecedeTOUJOURSLEcritureTests(_Base):
    """LE test. Une action qui ecrit sur le disque ne part pas sans apercu."""

    def test_le_premier_appel_est_un_dry_run(self) -> None:
        res = self._run(
            _APERCU
            + r"""
globalThis.__accepte = false;
await M.__nfo("run-42", btn);
__emit({ appels: globalThis.__appels });
"""
        )
        self.assertGreaterEqual(len(res["appels"]), 1)
        self.assertEqual(res["appels"][0]["route"], "run/export_run_nfo")
        self.assertIs(res["appels"][0]["params"]["dry_run"], True, "le premier appel ecrit sur le disque")
        self.assertEqual(res["appels"][0]["params"]["run_id"], "run-42")

    def test_un_REFUS_n_ecrit_RIEN(self) -> None:
        res = self._run(
            _APERCU
            + r"""
globalThis.__accepte = false;
await M.__nfo("run-42", btn);
__emit({ reels: globalThis.__appels.filter((a) => a.params && a.params.dry_run === false).length,
         confirmations: globalThis.__confirmations.length });
"""
        )
        self.assertEqual(res["reels"], 0, "des fichiers ont ete ecrits malgre le refus")
        self.assertEqual(res["confirmations"], 1)

    def test_une_ACCEPTATION_ecrit_avec_dry_run_false(self) -> None:
        res = self._run(
            _APERCU
            + r"""
globalThis.__accepte = true;
M.__nfo("run-42", btn);
await new Promise((r) => setTimeout(r, 0));
await globalThis.__enCours;
__emit({ reels: globalThis.__appels.filter((a) => a.params && a.params.dry_run === false).map((a) => a.params),
         toasts: globalThis.__toasts.map((t) => t.type) });
"""
        )
        self.assertEqual(res["reels"], [{"run_id": "run-42", "dry_run": False}])
        self.assertIn("success", res["toasts"])


class LaCONFIRMATIONDitLesVRAISChiffresTests(_Base):
    """La regle n3 exige la liste ET la consequence. Les deux viennent de
    l'apercu, pas d'une estimation."""

    def setUp(self) -> None:
        super().setUp()

    def test_la_liste_et_le_compte_viennent_de_l_apercu(self) -> None:
        res = self._run(
            _APERCU
            + r"""
globalThis.__accepte = false;
await M.__nfo("run-42", btn);
const c = globalThis.__confirmations[0];
__emit({ items: c.items, itemCount: c.itemCount, consequence: c.consequence, titre: c.title });
"""
        )
        self.assertEqual(
            res["items"],
            ["D:/Films/Heat (1995)/Heat.nfo", "D:/Films/Alien (1979)/Alien.nfo"],
            "la liste annoncee ne contient pas les chemins reellement a ecrire",
        )
        self.assertEqual(res["itemCount"], 2)
        self.assertIn("2", res["titre"])

    def test_la_consequence_nomme_ce_qui_N_EST_PAS_touche(self) -> None:
        """« Aucun film n'est deplace » est l'information qui manque le plus a
        quelqu'un qui hesite devant une action sur ses fichiers."""
        res = self._run(
            _APERCU
            + r"""
globalThis.__accepte = false;
await M.__nfo("run-42", btn);
__emit({ consequence: globalThis.__confirmations[0].consequence });
"""
        )
        c = res["consequence"]
        self.assertIn("ÉCRITS", c)
        self.assertIn("déplacé", c)
        self.assertIn("déjà présent", c, "les .nfo existants ne sont pas annonces comme preserves")
        self.assertIn("ignorés", c, "les films sans donnees ne sont pas annonces")


class UneActionSANSEFFETNeDemandeRienTests(_Base):
    """Une confirmation sur une action qui ne ferait rien devient un reflexe,
    donc plus une garde."""

    def test_zero_a_ecrire_n_ouvre_aucune_modale(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["run/export_run_nfo|apercu"] = {
  ok: true, dry_run: true, written: 0, skipped_existing: 3, skipped_no_data: 0, details: [],
};
await M.__nfo("run-42", btn);
__emit({ confirmations: globalThis.__confirmations.length,
         reels: globalThis.__appels.filter((a) => a.params && a.params.dry_run === false).length,
         texte: globalThis.__toasts.length ? globalThis.__toasts[0].text : "" });
"""
        )
        self.assertEqual(res["confirmations"], 0)
        self.assertEqual(res["reels"], 0)
        self.assertIn("déjà", res["texte"])

    def test_aucun_film_exploitable_le_DIT(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["run/export_run_nfo|apercu"] = {
  ok: true, dry_run: true, written: 0, skipped_existing: 0, skipped_no_data: 4, details: [],
};
await M.__nfo("run-42", btn);
__emit({ texte: globalThis.__toasts.length ? globalThis.__toasts[0].text : "", type: globalThis.__toasts[0].type });
"""
        )
        self.assertIn("données", res["texte"])
        self.assertEqual(res["type"], "info")


class UnECHECEstSIGNALEPasAvaleTests(_Base):
    def test_un_apercu_en_echec_n_ouvre_aucune_modale(self) -> None:
        res = self._run(
            r"""
globalThis.__reponses["run/export_run_nfo|apercu"] = { ok: false, user_message: "Run introuvable." };
await M.__nfo("run-x", btn);
__emit({ confirmations: globalThis.__confirmations.length, toasts: globalThis.__toasts.map((t) => t.type),
         texte: globalThis.__toasts[0].text, disabled: btn.disabled, etiquette: btn.textContent });
"""
        )
        self.assertEqual(res["confirmations"], 0, "une confirmation a ete demandee alors que l'apercu a echoue")
        self.assertIn("error", res["toasts"])
        self.assertEqual(res["texte"], "Run introuvable.")
        self.assertFalse(res["disabled"], "le bouton reste desactive apres un echec")
        self.assertEqual(res["etiquette"], "🎬 Générer les .nfo")

    def test_un_echec_a_l_ECRITURE_est_dit(self) -> None:
        res = self._run(
            _APERCU
            + r"""
globalThis.__reponses["run/export_run_nfo|reel"] = { ok: false, user_message: "Disque plein." };
globalThis.__accepte = true;
M.__nfo("run-42", btn);
await new Promise((r) => setTimeout(r, 0));
await globalThis.__enCours;
__emit({ toasts: globalThis.__toasts.map((t) => t.type), texte: globalThis.__toasts[0].text });
"""
        )
        self.assertIn("error", res["toasts"])
        self.assertEqual(res["texte"], "Disque plein.")

    def test_des_ERREURS_PARTIELLES_ne_passent_pas_pour_un_succes(self) -> None:
        """`ok: true` avec `errors > 0` est un succes PARTIEL : le dire."""
        res = self._run(
            _APERCU
            + r"""
globalThis.__reponses["run/export_run_nfo|reel"] = { ok: true, written: 1, errors: 1 };
globalThis.__accepte = true;
M.__nfo("run-42", btn);
await new Promise((r) => setTimeout(r, 0));
await globalThis.__enCours;
__emit({ type: globalThis.__toasts[0].type, texte: globalThis.__toasts[0].text });
"""
        )
        self.assertEqual(res["type"], "warning", "un succes partiel a ete annonce comme un succes")
        self.assertIn("erreur", res["texte"])


if __name__ == "__main__":
    unittest.main()
