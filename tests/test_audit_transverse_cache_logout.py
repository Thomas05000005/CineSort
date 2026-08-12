"""Audit transverse 2026-08-09 : la deconnexion laissait la bibliotheque en clair.

`apiPost` archive dans `localStorage` un instantane des reponses de la whitelist
`_CACHEABLE` de `web/dashboard/core/cache.js` — dont `run/get_dashboard` (titres
et chemins des films) et `settings/get_settings` (racine de bibliotheque, URL
Jellyfin/Plex). Ce repli hors ligne a un TTL de 24 h.

`clearCache()` existe depuis J14 pour purger ces entrees. Mesure du 2026-08-09 :
il n'avait AUCUN appelant en production (une seule occurrence dans tout `web/`,
sa propre definition). `clearToken()` — invoque par la commande « Se deconnecter
(token) » de la palette et par le 401 en mode web — retirait le token et laissait
les donnees. Le dashboard LAN est justement fait pour etre consulte depuis un
autre appareil : l'utilisateur qui se deconnecte croit partir, il laisse 24 h de
bibliotheque derriere lui.

Les tests tournent sous Node sur la VRAIE source (`tests/_jsexec`) : `cache.js`
est inline tel quel, donc c'est le `clearCache()` livre qui s'execute, pas une
reecriture du testeur. Un test qui chercherait la chaine « clearCache » dans
`state.js` passerait au vert sur un appel mort.
"""

from __future__ import annotations

import unittest

from tests._jsexec import ROOT, inline_module, node_check, require_node, run_module_test

STATE_JS = ROOT / "web" / "dashboard" / "core" / "state.js"

_CACHE_PREFIX = "cinesort.cache."

# Storage minimal mais COMPLET : `clearCache()` balaye `localStorage` par
# `length` + `key(i)`, deux membres qu'un stub naif a base d'objet nu n'a pas.
# Sans eux la purge ne verrait aucune cle et le test passerait au vert pour la
# mauvaise raison.
_STORAGE_STUB = r"""
globalThis.__local = new Map();
globalThis.__session = new Map();

function __mkStorage(map) {
  return {
    getItem: (k) => (map.has(String(k)) ? map.get(String(k)) : null),
    setItem: (k, v) => { map.set(String(k), String(v)); },
    removeItem: (k) => { map.delete(String(k)); },
    key: (i) => { const ks = Array.from(map.keys()); return i < ks.length ? ks[i] : null; },
    get length() { return map.size; },
  };
}

globalThis.localStorage = __mkStorage(globalThis.__local);
globalThis.sessionStorage = __mkStorage(globalThis.__session);
"""

# `cache.js` n'a aucun import : on l'injecte tel quel (cf. inline_module), ce qui
# fait tourner le vrai couple ecrivain/balai plutot qu'une imitation.
_STUBS = _STORAGE_STUB + "\n" + inline_module("core/cache.js")

# `saveSnapshot`/`loadSnapshot` vivent dans les stubs, donc hors des exports de
# `state.js`. On les re-expose pour interroger l'ECRIVAIN et le LECTEUR du repli
# hors ligne, et pas seulement l'etat brut du storage.
_EXTRA = "export const __loadSnapshot = loadSnapshot;\nexport const __saveSnapshot = saveSnapshot;\n"

# `state.js` arme au chargement un `setTimeout` de 2 s (deadline du token-gate).
# Sans sortie explicite, chaque driver ferait attendre Node d'autant.
_EXIT = "\nprocess.exit(0);\n"

# Ce que le dashboard a reellement archive avant la deconnexion. On passe par
# `__saveSnapshot`, donc par le format d'enveloppe de production : un seed ecrit
# a la main pourrait diverger du schema et rendre la purge trivialement verte.
_SEED = r"""
M.__saveSnapshot("run/get_dashboard", { films: [{ title: "Heat", folder: "D:/Films/Heat (1995)" }] });
M.__saveSnapshot("settings/get_settings", { root: "D:/Films", jellyfin_url: "http://192.168.1.20:8096" });
M.__saveSnapshot("integrations/get_plex_libraries", { libraries: ["Films"] });
"""


class PurgeDuCacheAuLogoutTests(unittest.TestCase):
    """`clearToken()` doit emporter le repli hors ligne avec le token."""

    def setUp(self) -> None:
        require_node(self)

    def _run(self, driver: str) -> dict:
        """Chaque scenario part d'un cache DEJA arme : c'est l'etat d'un
        utilisateur qui a navigue avant de se deconnecter."""
        return run_module_test(STATE_JS, stubs=_STUBS, extra=_EXTRA, driver=_SEED + driver + _EXIT, timeout=90)

    def test_les_instantanes_ne_survivent_pas_a_la_deconnexion(self) -> None:
        """ROUGE sans l'appel a clearCache() : les 3 entrees restaient apres logout."""
        res = self._run(
            r"""
M.setToken("abcDEF123", true);
const avant = Array.from(globalThis.__local.keys()).filter((k) => k.startsWith("cinesort.cache."));
M.clearToken();
const apres = Array.from(globalThis.__local.keys()).filter((k) => k.startsWith("cinesort.cache."));
__emit({ avant, apres, token: M.getToken() });
"""
        )
        self.assertEqual(
            len(res["avant"]),
            3,
            "le seed doit bien avoir arme le cache, sinon le test ne prouve rien",
        )
        self.assertEqual(
            res["apres"],
            [],
            f"instantanes survivants apres deconnexion : {res['apres']}",
        )
        self.assertEqual(res["token"], "", "le token doit partir, comme avant")

    def test_le_lecteur_hors_ligne_ne_rend_plus_rien(self) -> None:
        """Le contrat utile n'est pas « la cle a disparu » mais « plus personne ne
        peut relire la bibliotheque ». On interroge donc `loadSnapshot`,
        c'est-a-dire le lecteur reel du repli hors ligne."""
        res = self._run(
            r"""
const avant = M.__loadSnapshot("run/get_dashboard");
M.clearToken();
const apres = M.__loadSnapshot("run/get_dashboard");
__emit({
  avantLisible: avant !== null && avant.data.films[0].title === "Heat",
  apres,
});
"""
        )
        self.assertTrue(res["avantLisible"], "avant la deconnexion, l'instantane doit etre lisible")
        self.assertIsNone(res["apres"], "apres la deconnexion, plus aucun instantane ne doit etre servi")

    def test_la_purge_ne_deborde_pas_sur_les_autres_cles(self) -> None:
        """Garde-fou contre un correctif trop large : un `localStorage.clear()`
        emporterait la langue, le drapeau natif et les brouillons de decisions.
        Seul le prefixe `cinesort.cache.` est du perimetre."""
        res = self._run(
            r"""
globalThis.localStorage.setItem("cinesort_locale", "fr");
globalThis.localStorage.setItem("cinesort.native", "1");
globalThis.localStorage.setItem("cinesort.drafts.run42", "{}");
M.clearToken();
__emit({ restantes: Array.from(globalThis.__local.keys()).sort() });
"""
        )
        self.assertEqual(
            res["restantes"],
            ["cinesort.drafts.run42", "cinesort.native", "cinesort_locale"],
            "la purge doit se limiter au prefixe du cache d'instantanes",
        )

    def test_lecrivain_utilise_bien_le_prefixe_purge(self) -> None:
        """La purge balaye par prefixe : elle couvrira les futures entrees de la
        whitelist `_CACHEABLE` sans rien changer, tant que `saveSnapshot` ecrit
        sous ce meme prefixe. C'est cette hypothese que fige ce test — le fait
        que la purge reprenne ce que l'ecrivain a pose est, lui, etabli par
        `test_les_instantanes_ne_survivent_pas_a_la_deconnexion`, dont le seed
        passe par `saveSnapshot`."""
        res = self._run(
            r"""
__emit({ ecrites: Array.from(globalThis.__local.keys()).sort() });
"""
        )
        self.assertEqual(len(res["ecrites"]), 3)
        for cle in res["ecrites"]:
            self.assertTrue(cle.startswith(_CACHE_PREFIX), f"prefixe inattendu a l'ecriture : {cle}")

    def test_nonreg_syntaxe(self) -> None:
        node_check(self, STATE_JS)


if __name__ == "__main__":
    unittest.main()
