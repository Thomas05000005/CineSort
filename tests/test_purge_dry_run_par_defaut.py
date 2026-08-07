"""Une route de purge exposee en REST ne doit pas supprimer sur un corps VIDE.

Les deux methodes de purge de la quarantaine sont atteignables en
`POST /api/run/purge_quarantine_bucket[_all]`. Leur `dry_run` valait **False**
par defaut : un appel sans aucun parametre supprimait donc des fichiers de
l'utilisateur.

Sur une frontiere destructive, l'omission doit produire l'APERCU, jamais l'effet.
Les appelants dont le travail EST de supprimer le disent maintenant
explicitement — c'est un parametre visible en review, plus un defaut invisible.

CE QUE CE CORRECTIF NE FAIT PAS : rendre la purge impossible. Le cron TTL et le
bouton « Vider maintenant » fonctionnent exactement comme avant.

LES CONTRE-EPREUVES S'EXECUTENT, ELLES NE LISENT PLUS LE SOURCE. Une premiere
version verifiait les deux appelants par expression reguliere sur leur code
source (`re.findall` sur `quarantine_ttl.py`, `assertRegex` sur
`parametres.js`). C'est l'anti-patron que ce depot proscrit : une telle
assertion passe au vert des qu'on ecrit la bonne chaine, meme si la logique est
fausse, et elle rougit des que le code s'ameliore sans rien casser. Le cron est
donc appele pour de vrai, et le bouton de l'UI est execute sous Node par le
harnais `_jsexec` — c'est bien `parametres.js` livre qui tourne.
"""

from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace

from cinesort.app.quarantine_ttl import _run_purge_once
from cinesort.ui.api.facades.run_facade import RunFacade
from tests._jsexec import DASHBOARD, require_node, run_module_test

_JS = DASHBOARD / "views" / "parametres.js"


class DefautDesRoutesDePurgeTests(unittest.TestCase):
    def test_purge_par_ttl_previsualise_par_defaut(self) -> None:
        defaut = inspect.signature(RunFacade.purge_quarantine_bucket).parameters["dry_run"].default

        self.assertIs(defaut, True, "un POST au corps vide supprime des fichiers")

    def test_purge_totale_previsualise_par_defaut(self) -> None:
        defaut = inspect.signature(RunFacade.purge_quarantine_bucket_all).parameters["dry_run"].default

        self.assertIs(defaut, True, "un POST au corps vide vide toute la quarantaine")


class LeCronTTLSupprimeTOUJOURSTests(unittest.TestCase):
    """Contre-epreuve : basculer le defaut ne doit pas rendre la purge inoperante.

    Le cron TTL s'appuyait sur le defaut. Sans ce parametre explicite, il
    deviendrait un no-op SILENCIEUX et la quarantaine croitrait sans borne — un
    correctif de securite qui casse la fonction qu'il protege.
    """

    def _appeler_le_cron(self, resultat: object) -> list:
        recu: list = []

        class _FakeRun:
            def purge_quarantine_bucket(self, ttl_days: int, dry_run: bool = True):
                recu.append({"ttl_days": ttl_days, "dry_run": dry_run})
                return resultat

        _run_purge_once(SimpleNamespace(run=_FakeRun()), 15)
        return recu

    def test_le_cron_passe_dry_run_FALSE(self) -> None:
        """Le coeur de la contre-epreuve : c'est l'EXECUTION qui le dit."""
        recu = self._appeler_le_cron({"ok": True, "deleted": 7})

        self.assertEqual(len(recu), 1, "le cron n'a pas appele la purge")
        self.assertIs(recu[0]["dry_run"], False, "le cron previsualiserait : la quarantaine croitrait sans borne")

    def test_le_cron_transmet_le_ttl_recu(self) -> None:
        recu = self._appeler_le_cron({"ok": True, "deleted": 0})

        self.assertEqual(recu[0]["ttl_days"], 15)

    def test_une_reponse_en_echec_ne_fait_pas_exploser_le_thread(self) -> None:
        """Le cron tourne en thread daemon : une exception le tuerait pour de bon."""
        self._appeler_le_cron({"ok": False, "message": "verrou"})


class LeBoutonViderMaintenantSupprimeTOUJOURSTests(unittest.TestCase):
    """Le bouton de l'UI, execute — pas relu.

    `_bindFields` attache le gestionnaire a `[data-action="quarantine_purge_all"]`.
    Le faux DOM ne rend visible QUE ce bouton (les six autres `querySelectorAll`
    du meme bloc rendent une liste vide), puis le driver declenche le clic et
    confirme la modale.
    """

    # Doublures des imports de `parametres.js`. Seules `apiPost` et
    # `dangerConfirmModal` comptent ; les autres existent pour que le module se
    # charge.
    _STUBS = r"""
globalThis.__appels = [];
globalThis.__modales = [];
globalThis.__total = 120;

const apiPost = async (route, params) => {
  __appels.push({ route, params });
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

    _EXTRA = r"""
export const __bindFields = _bindFields;
"""

    def _cliquer(self, total: int) -> dict:
        driver = f"""
            globalThis.__total = {total};
            M.__bindFields(__container);
            if (!__bouton) {{ throw new Error("le bouton « Vider maintenant » n'existe plus"); }}
            await __bouton.__handlers.click();
            if (!__modales.length) {{ throw new Error("aucune confirmation demandee avant une suppression"); }}
            await __modales[0].onConfirm();
            __emit({{ appels: __appels, modales: __modales.map(m => (
              {{ titre: m.title, countdown: m.countdownSeconds }})) }});
        """
        return run_module_test(_JS, stubs=self._STUBS, extra=self._EXTRA, driver=driver)

    def setUp(self) -> None:
        require_node(self)

    def test_le_bouton_demande_la_SUPPRESSION_pas_un_apercu(self) -> None:
        """Le defaut que le nouveau defaut de facade rendrait invisible : sans
        `dry_run: false`, le bouton previsualiserait et ne supprimerait rien,
        tout en affichant « supprime(s) »."""
        res = self._cliquer(120)

        purges = [a for a in res["appels"] if a["route"] == "run/purge_quarantine_bucket_all"]
        self.assertEqual(len(purges), 1, f"la purge n'a pas ete demandee : {res['appels']}")
        # `.get` et non `[...]` : un parametre ABSENT est precisement le defaut
        # a detecter, et un KeyError le rapporterait moins clairement qu'un
        # `None is not False`.
        self.assertIs(purges[0]["params"].get("dry_run"), False, "le bouton previsualiserait au lieu de supprimer")

    def test_aucune_suppression_AVANT_la_confirmation(self) -> None:
        """Regle n3, mesuree au bon instant.

        On compte les purges APRES le clic mais AVANT `onConfirm` : c'est le
        seul moment ou l'assertion a un sens. `_bindFields` cable aussi d'autres
        champs qui emettent leurs propres `apiPost` — asserter sur la PREMIERE
        route du journal mesurerait donc un voisin sans rapport.
        """
        driver = """
            globalThis.__total = 120;
            M.__bindFields(__container);
            await __bouton.__handlers.click();
            const avant = __appels.filter(a => a.route.startsWith("run/purge")).length;
            await __modales[0].onConfirm();
            const apres = __appels.filter(a => a.route.startsWith("run/purge")).length;
            __emit({ avant, apres, modales: __modales.length });
        """
        res = run_module_test(_JS, stubs=self._STUBS, extra=self._EXTRA, driver=driver)

        self.assertEqual(res["avant"], 0, "des fichiers sont supprimes AVANT que l'utilisateur ait confirme")
        self.assertEqual(res["apres"], 1, "la confirmation ne declenche aucune suppression")
        self.assertEqual(res["modales"], 1, "aucune confirmation demandee")

    def test_un_bucket_VIDE_ne_propose_aucune_suppression(self) -> None:
        """Contre-epreuve : une modale destructive qui ne supprimerait rien
        userait la confirmation exactement quand elle doit porter."""
        driver = """
            globalThis.__total = 0;
            M.__bindFields(__container);
            await __bouton.__handlers.click();
            __emit({ modales: __modales.length,
                     purges: __appels.filter(a => a.route.startsWith("run/purge")).length });
        """
        res = run_module_test(_JS, stubs=self._STUBS, extra=self._EXTRA, driver=driver)

        self.assertEqual(res["modales"], 0)
        self.assertEqual(res["purges"], 0)


if __name__ == "__main__":
    unittest.main()
