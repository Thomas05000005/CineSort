"""Le cadenas de la fiche film doit poser le nom de champ QUI PROTEGE.

CE QUE CES TESTS EPROUVENT, ET POURQUOI C'EST CELUI-LA. Les trois endpoints de
verrous existaient depuis longtemps, testes cote backend, et n'avaient AUCUNE
interface : `grep -rn "set_field_lock" web/` ne rendait rien. Deux choses les
rendaient incablables, toutes deux mesurees :

1. `get_film_full` n'exposait pas de `film_id`, et la forme `path:<sha1(...)>`
   n'est pas calculable dans un navigateur. Le front n'avait donc aucun moyen de
   NOMMER le film.
2. La docstring de `set_field_lock` donnait `"title"` en exemple — un nom qui
   rend `ok: true`, affiche un cadenas ferme, et laisse le titre se faire
   ecraser au rescan (mesure du 2026-08-07). Cabler l'interface sur cet exemple
   aurait livre une fonctionnalite entierement vide, verte de bout en bout.

Le backend refuse desormais les noms inconnus (#1017). Ces tests ne s'appuient
PAS sur ce refus : une interface correcte ne doit pas dependre d'une garde
d'en face pour poser le bon nom. Ils verifient donc la valeur reellement
transmise, pas seulement que l'appel aboutit.

Ils tournent sous Node sur la VRAIE source `web/dashboard/components/film-detail.js`
(cf. `tests/_jsexec.py`) : un test qui chercherait la chaine `set_field_lock` dans
le fichier passerait au vert sur du code mort.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, require_node, run_module_test

FILM_DETAIL_JS = ROOT / "web" / "dashboard" / "components" / "film-detail.js"

#: Les imports du composant sont neutralises par le harnais ; on rend ici les
#: seuls symboles que le chemin teste touche reellement. `apiPost` enregistre
#: ses appels : c'est LUI la grandeur observee.
_STUBS = r"""
// Le composant s'attache a `window` et interroge le DOM au chargement : sans ces
// deux-la, le module leve `ReferenceError` avant meme le premier test, et le
// harnais rendrait un echec qui ne parle pas du sujet.
globalThis.window = { addEventListener() {}, removeEventListener() {}, location: { hash: "" } };
globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById() { return null; }, querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement() { return { style: {}, classList: { add() {}, remove() {} }, appendChild() {} }; },
  body: { appendChild() {}, classList: { add() {}, remove() {} } },
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
function posterProxyUrl() { return ""; }
function showToast(o) { globalThis.__toasts.push(o); }
globalThis.__toasts = [];
const rightPanel = { setWidth() {}, setExpanded() {}, setContent() {} };
function openPerceptualModal() {}
function dangerConfirmModal() { return Promise.resolve(true); }
function labelForFlag(f) { return String(f); }
function formatBytes() { return ""; }
function t(k) { return String(k); }
"""

#: Le composant n'exporte ni son etat ni ses helpers de rendu : on les re-expose
#: pour interroger le rendu ET l'action, c'est-a-dire les deux moities de
#: l'affordance.
_EXTRA = (
    "export const __state = _state;\n"
    "export const __cadenasHtml = cadenasHtml;\n"
    "export const __basculer = _basculerLeVerrou;\n"
)

_EXIT = "\nprocess.exit(0);\n"


def _bouton(champ: str, verrouille: bool = False) -> str:
    """Le bouton tel que le DOM le porterait, dataset compris."""
    return (
        "{ dataset: { fieldName: %r, fieldValue: 'Matrix', locked: %r }, disabled: false }"
        % (champ, "1" if verrouille else "0")
    ).replace("'", '"')


class LeCadenasNEstRenduQueSiLeFilmAUneIDENTITETests(unittest.TestCase):
    """Sans `film_id`, un cadenas cliquable echouerait en silence."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(FILM_DETAIL_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)

    def test_sans_film_id_aucun_cadenas(self) -> None:
        res = self._run(
            r"""
M.__state.data = { row: {}, _verrous: [] };
__emit({ html: M.__cadenasHtml("proposed_title", "Matrix") });
"""
        )
        self.assertEqual(
            res["html"],
            "",
            "un cadenas est propose alors que le film n'a pas d'identite : le clic "
            "ne pourrait nommer aucun film et echouerait sans le dire.",
        )

    def test_avec_film_id_le_cadenas_apparait(self) -> None:
        res = self._run(
            r"""
M.__state.data = { film_id: "tmdb:603", row: {}, _verrous: [] };
__emit({ html: M.__cadenasHtml("proposed_title", "Matrix") });
"""
        )
        self.assertIn('data-film-action="toggle-field-lock"', res["html"])
        self.assertIn('data-field-name="proposed_title"', res["html"])

    def test_un_champ_INCONNU_n_a_pas_de_cadenas(self) -> None:
        """`"title"` est un libelle d'affichage : il ne protege rien."""
        res = self._run(
            r"""
M.__state.data = { film_id: "tmdb:603", row: {}, _verrous: [] };
__emit({ titre: M.__cadenasHtml("title", "Matrix"), annee: M.__cadenasHtml("year", 1999) });
"""
        )
        self.assertEqual(res["titre"], "")
        self.assertEqual(res["annee"], "")


class LEtatDuCadenasSUITLaBaseTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(FILM_DETAIL_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)

    def test_ferme_quand_un_verrou_existe(self) -> None:
        res = self._run(
            r"""
M.__state.data = { film_id: "tmdb:603", row: {}, _verrous: [{ field_name: "proposed_title" }] };
__emit({ html: M.__cadenasHtml("proposed_title", "Matrix") });
"""
        )
        self.assertIn('data-locked="1"', res["html"])
        self.assertIn('aria-pressed="true"', res["html"])
        self.assertIn("🔒", res["html"])

    def test_ouvert_quand_aucun_verrou(self) -> None:
        res = self._run(
            r"""
M.__state.data = { film_id: "tmdb:603", row: {}, _verrous: [] };
__emit({ html: M.__cadenasHtml("proposed_title", "Matrix") });
"""
        )
        self.assertIn('data-locked="0"', res["html"])
        self.assertIn('aria-pressed="false"', res["html"])
        self.assertIn("🔓", res["html"])

    def test_le_verrou_d_un_AUTRE_champ_ne_ferme_pas_celui_ci(self) -> None:
        res = self._run(
            r"""
M.__state.data = { film_id: "tmdb:603", row: {}, _verrous: [{ field_name: "proposed_year" }] };
__emit({ titre: M.__cadenasHtml("proposed_title", "Matrix"), annee: M.__cadenasHtml("proposed_year", 1999) });
"""
        )
        self.assertIn('data-locked="0"', res["titre"])
        self.assertIn('data-locked="1"', res["annee"])


class LAppelPOSTELeNomQuiPROTEGETests(unittest.TestCase):
    """LE test de ce fichier. C'est le nom transmis qui decide de tout."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        return run_module_test(FILM_DETAIL_JS, stubs=_STUBS, extra=_EXTRA, driver=driver + _EXIT, timeout=90)

    def test_poser_un_verrou_envoie_proposed_title(self) -> None:
        res = self._run(
            r"""
M.__state.data = { film_id: "tmdb:603", row: {}, _verrous: [] };
M.__state.rowId = "r1"; M.__state.loadSeq = 1;
globalThis.__reponses["library/set_field_lock"] = { ok: true };
globalThis.__reponses["library/list_field_locks"] = { ok: true, locks: [{ field_name: "proposed_title" }] };
await M.__basculer({ dataset: { fieldName: "proposed_title", fieldValue: "Matrix", locked: "0" }, disabled: false });
__emit({ appels: globalThis.__appels });
"""
        )
        poses = [a for a in res["appels"] if a["route"] == "library/set_field_lock"]
        self.assertEqual(len(poses), 1, f"un seul POST attendu, obtenu {res['appels']}")
        self.assertEqual(
            poses[0]["params"]["field_name"],
            "proposed_title",
            "l'interface pose un nom qui ne protege rien : cadenas ferme a l'ecran, titre ecrase au rescan.",
        )
        self.assertEqual(poses[0]["params"]["film_id"], "tmdb:603")
        self.assertEqual(poses[0]["params"]["locked_value"], "Matrix")

    def test_retirer_un_verrou_appelle_clear_et_pas_set(self) -> None:
        res = self._run(
            r"""
M.__state.data = { film_id: "tmdb:603", row: {}, _verrous: [{ field_name: "proposed_year" }] };
M.__state.rowId = "r1"; M.__state.loadSeq = 1;
globalThis.__reponses["library/clear_field_lock"] = { ok: true, removed: true };
globalThis.__reponses["library/list_field_locks"] = { ok: true, locks: [] };
await M.__basculer({ dataset: { fieldName: "proposed_year", fieldValue: "1999", locked: "1" }, disabled: false });
__emit({ routes: globalThis.__appels.map((a) => a.route) });
"""
        )
        self.assertIn("library/clear_field_lock", res["routes"])
        self.assertNotIn("library/set_field_lock", res["routes"])

    def test_un_REFUS_du_serveur_ne_ment_pas_a_l_utilisateur(self) -> None:
        """L'icone ne bascule pas localement : on relit l'etat reel.

        Un cadenas qui se ferme sur un refus serait le meme defaut que celui que
        #1017 a corrige cote backend, deplace dans l'interface.
        """
        res = self._run(
            r"""
M.__state.data = { film_id: "tmdb:603", row: {}, _verrous: [] };
M.__state.rowId = "r1"; M.__state.loadSeq = 1;
globalThis.__reponses["library/set_field_lock"] = { ok: false, user_message: "Champ inconnu" };
await M.__basculer({ dataset: { fieldName: "proposed_title", fieldValue: "Matrix", locked: "0" }, disabled: false });
__emit({
  verrous: M.__state.data._verrous,
  toasts: globalThis.__toasts.map((t) => t.type),
  relu: globalThis.__appels.some((a) => a.route === "library/list_field_locks"),
});
"""
        )
        self.assertEqual(res["verrous"], [], "l'etat local a ete modifie malgre le refus")
        self.assertIn("error", res["toasts"], "le refus n'a pas ete signale a l'utilisateur")
        self.assertFalse(res["relu"], "inutile de relire l'etat quand le serveur a refuse")


if __name__ == "__main__":
    unittest.main()
