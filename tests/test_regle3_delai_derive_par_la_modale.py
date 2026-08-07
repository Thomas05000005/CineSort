"""Regle n3 : les derniers appelants qui RECALCULAIENT le delai ont un trou a 42-50.

CONTEXTE. La PR #988 a deplace le seuil DANS `dangerConfirmModal` : un appelant
qui passe `itemCount` (et non `countdownSeconds`) obtient le delai gradue de
`gradedCountdownSeconds`. Quatre sites ont continue de calculer le leur avec la
ternaire `n > 50 ? 3 : 0`, et un cinquieme repliquait la formule en attendant la
fusion des deux branches.

L'ECART, MESURE SUR LE VRAI HELPER (ce fichier le calcule, il ne le recopie pas) :

    n = 41   graduee -> 0 s    ternaire -> 0 s     d'accord
    n = 42   graduee -> 1 s    ternaire -> 0 s     DIVERGENT
    n = 50   graduee -> 1 s    ternaire -> 0 s     DIVERGENT
    n = 51   graduee -> 3 s    ternaire -> 3 s     d'accord

Entre 42 et 50 elements, ces quatre sites confirmaient donc au premier clic une
action que la regle partagee protege d'une seconde. Le commentaire pose dans
`historique.js` par la branche voisine l'avait annonce mot pour mot : « cet ecart
aurait SURVECU a la fusion ». Il y a survecu.

LES ASSERTIONS S'EXECUTENT, ELLES NE LISENT PAS LE SOURCE. Le depot proscrit les
tests qui comparent une chaine de code : ils passent au vert des qu'on ecrit la
bonne chaine et rougissent des que le code s'ameliore. Ici :

- `modal.js` est charge et `gradedCountdownSeconds` reellement appelee ;
- `parametres.js` est charge tel quel, son bouton « Vider maintenant » clique,
  et c'est l'objet REELLEMENT passe a `dangerConfirmModal` qui est observe.

Les deux ensemble donnent le delai effectif : la modale derive si et seulement si
l'appelant ne fournit pas `countdownSeconds`.
"""

from __future__ import annotations

import unittest

from tests._jsexec import DASHBOARD, require_node, run_module_test

_MODAL = DASHBOARD / "components" / "modal.js"
_PARAMETRES = DASHBOARD / "views" / "parametres.js"

# `modal.js` n'importe que deux helpers DOM ; ils ne sont pas sur le chemin de
# `gradedCountdownSeconds`, qui est une fonction pure.
_STUBS_MODAL = r"""
const $ = () => null;
const escapeHtml = (s) => String(s == null ? "" : s);
globalThis.document = { getElementById: () => null, querySelector: () => null,
                        querySelectorAll: () => [], addEventListener() {} };
"""

_EXTRA_MODAL = r"""
export const __graded = gradedCountdownSeconds;
"""


class LeHelperGradueEstLaReferenceTests(unittest.TestCase):
    """Le delai de reference vient du helper LIVRE, pas d'une copie du test."""

    def setUp(self) -> None:
        require_node(self)

    def _delais(self, valeurs: list) -> dict:
        driver = f"""
            const out = {{}};
            for (const n of {valeurs!r}) {{ out[String(n)] = M.__graded(n); }}
            __emit(out);
        """
        return run_module_test(_MODAL, stubs=_STUBS_MODAL, extra=_EXTRA_MODAL, driver=driver)

    def test_la_zone_42_50_vaut_UNE_seconde_et_pas_zero(self) -> None:
        """C'est tout l'ecart : la ternaire des appelants y rendait 0."""
        delais = self._delais([42, 45, 50])

        self.assertEqual(delais["42"], 1)
        self.assertEqual(delais["45"], 1)
        self.assertEqual(delais["50"], 1)

    def test_les_bornes_de_la_regle_utilisateur_sont_tenues(self) -> None:
        delais = self._delais([0, 30, 41, 51, 500])

        self.assertEqual(delais["0"], 0)
        self.assertEqual(delais["30"], 0)
        self.assertEqual(delais["41"], 0, "sous 42, ternaire et graduee sont d'accord")
        self.assertEqual(delais["51"], 3, "regle projet n3 : au-dela de 50, trois secondes")
        self.assertEqual(delais["500"], 3, "pas d'interpolation au-dela du seuil")


# Doublures des imports de `parametres.js`. Seules `apiPost` et
# `dangerConfirmModal` comptent ; les autres existent pour que le module se
# charge. Calquees sur `tests/test_purge_dry_run_par_defaut.py`, qui exerce le
# meme bouton.
_STUBS_PARAMETRES = r"""
globalThis.__modales = [];
globalThis.__total = 45;

const apiPost = async (route) => {
  if (route === "run/list_quarantine_bucket") {
    return { data: { ok: true, purge_scope_files_count: __total,
                     purge_scope_size_bytes: 1048576, purge_scope_sample: ["a.mkv"] } };
  }
  return { data: { ok: true, deleted: __total, bytes_freed: 1048576 } };
};
const dangerConfirmModal = (opts) => { __modales.push(opts); };

const apiGet = async () => ({ data: {} });
const cachedGetSettings = async () => ({});
const invalidateSettingsCache = () => {};
const escapeHtml = (s) => String(s == null ? "" : s);
const showToast = () => {};
const showModal = () => {};
const closeModal = () => {};
const trapFocus = () => {};
const getNavSignal = () => ({ aborted: false });
const navigateTo = () => {};
const rightPanel = { open: () => {}, close: () => {} };
const buildEmptyState = () => "";
const t = (k) => k;
const applyTheme = () => {};
const setLocale = () => {};
const getLocale = () => "fr";

// --- faux DOM, reduit au strict necessaire ---
globalThis.__CIBLE = '[data-action="quarantine_purge_all"]';
const _el = () => ({
  addEventListener() {}, querySelector: () => _el(), querySelectorAll: () => [],
  textContent: "", innerHTML: "", value: "", disabled: false, checked: false,
  dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, className: "",
  closest: () => null, focus() {}, click() {},
});
globalThis.__bouton = null;
globalThis.__container = {
  querySelectorAll(sel) {
    if (sel !== __CIBLE) return [];
    __bouton = Object.assign(_el(), { __handlers: {},
      addEventListener(ev, h) { this.__handlers[ev] = h; } });
    return [__bouton];
  },
  querySelector: () => _el(),
  addEventListener() {},
};
globalThis.document = { getElementById: () => _el(), querySelector: () => _el(),
                        querySelectorAll: () => [], createElement: () => _el(),
                        addEventListener() {}, body: _el() };
globalThis.window = { addEventListener() {}, location: { href: "" },
                      matchMedia: () => ({ matches: false, addEventListener() {} }) };
"""

_EXTRA_PARAMETRES = r"""
export const __bindFields = _bindFields;
"""


class ViderMaintenantDelegueSonDelaiTests(unittest.TestCase):
    """« Vider maintenant » supprime definitivement des fichiers de l'utilisateur.

    C'est le site que ce harnais sait deja executer de bout en bout ; les trois
    autres appelants corriges (`doublons.js` x2, `qualite.js`) passent par le
    MEME parametre et le meme helper, verrouille par la classe ci-dessus.
    """

    def setUp(self) -> None:
        require_node(self)

    def _ouvrir_la_modale(self, total: int) -> dict:
        driver = f"""
            globalThis.__total = {total};
            M.__bindFields(__container);
            if (!__bouton) {{ throw new Error("le bouton « Vider maintenant » n'existe plus"); }}
            await __bouton.__handlers.click();
            if (!__modales.length) {{ throw new Error("aucune confirmation demandee avant une suppression"); }}
            const m = __modales[0];
            __emit({{ a_countdown_explicite: Object.prototype.hasOwnProperty.call(m, "countdownSeconds"),
                     countdown: m.countdownSeconds === undefined ? null : m.countdownSeconds,
                     itemCount: m.itemCount === undefined ? null : m.itemCount }});
        """
        return run_module_test(_PARAMETRES, stubs=_STUBS_PARAMETRES, extra=_EXTRA_PARAMETRES, driver=driver)

    def test_le_bouton_ne_recalcule_PLUS_son_propre_delai(self) -> None:
        """Une valeur explicite l'emporte sur la derivation : la fournir, c'est
        redonner a cet appelant sa convention privee."""
        modale = self._ouvrir_la_modale(45)

        self.assertFalse(
            modale["a_countdown_explicite"],
            f"le delai est encore calcule par l'appelant (countdownSeconds={modale['countdown']}) : "
            "sur 45 fichiers il vaut 0 s, la ou la regle partagee en impose 1",
        )

    def test_le_bouton_annonce_le_nombre_de_fichiers_PURGEABLES(self) -> None:
        """Sans `itemCount`, la modale retombe sur `items.length` — ici zero,
        donc aucun delai : le correctif serait sans effet."""
        modale = self._ouvrir_la_modale(45)

        self.assertEqual(modale["itemCount"], 45)

    def test_un_gros_bucket_reste_gradue_au_maximum(self) -> None:
        """Contre-epreuve : deleguer ne doit pas AFFAIBLIR le cas deja couvert."""
        modale = self._ouvrir_la_modale(120)

        self.assertEqual(modale["itemCount"], 120)
        self.assertFalse(modale["a_countdown_explicite"])


if __name__ == "__main__":
    unittest.main()
