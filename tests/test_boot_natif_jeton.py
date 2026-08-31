# -*- coding: utf-8 -*-
"""LE FILET, pose AVANT de toucher au transit du jeton (T-SEC-5).

Pourquoi ce fichier existe
--------------------------
`app.py` passe le jeton REST au dashboard en QUERY STRING
(`/dashboard/?ntoken=...&native=1`). Une query string part au serveur, entre
dans son journal de requetes, et WebView2 l'archive dans son historique — c'est
ainsi que le jeton de l'utilisateur s'est retrouve dans quatre artefacts locaux
(`History`, `Top Sites`, `Favicons`, `Local Storage/leveldb`).

La reponse est le FRAGMENT (`#ntoken=...`) : il n'est jamais envoye au serveur.
Mais il entre en collision avec le routeur, qui utilise deja le hash
(`#/accueil`, `#/login`), et `_detectNativeBoot` n'avait AUCUN test.

Ce fichier ne corrige rien. Il FIGE le comportement actuel, pour que le
correctif suivant ait quelque chose a casser. C'est l'ordre impose : le filet
d'abord, la preuve ensuite — un test ecrit APRES le correctif ne prouve que ce
que le correctif fait, jamais ce qu'il a change sans le vouloir.

Comment le harnais tient
------------------------
`_detectNativeBoot` est une IIFE au milieu de `web/dashboard/app.js`, un module
de 1011 lignes qui importe une quarantaine de symboles et enregistre 40 routes
au chargement. `tests/_jsexec.py` blanchit les imports ; il reste a fournir un
stub pour chaque symbole importe.

CES STUBS SONT DERIVES DU FICHIER, pas ecrits a la main. Une liste manuelle
diverge des que `app.js` gagne un import, et la divergence se manifeste par une
`ReferenceError` au milieu du harnais — un echec de HARNAIS qu'on prend
volontiers pour un defaut du code. `test_les_stubs_couvrent_TOUS_les_imports`
epingle la derivation elle-meme.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests import _jsexec

_RACINE = Path(__file__).resolve().parents[1]
_APP_JS = _RACINE / "web" / "dashboard" / "app.js"

_IMPORT_NOMME = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"'][^\"']+[\"']", re.S)
_IMPORT_NAMESPACE = re.compile(r"import\s*\*\s*as\s+(\w+)\s+from\s*[\"'][^\"']+[\"']")


def symboles_importes(source: str) -> tuple[set[str], set[str]]:
    """(symboles nommes, espaces de noms) importes par le module."""
    nommes: set[str] = set()
    for bloc in _IMPORT_NOMME.findall(source):
        for brut in bloc.split(","):
            morceau = brut.strip()
            if not morceau:
                continue
            # `x as y` : c'est `y` qui est visible dans le module.
            nommes.add(morceau.split(" as ")[-1].strip())
    espaces = set(_IMPORT_NAMESPACE.findall(source))
    return nommes - espaces, espaces


def _stubs() -> str:
    source = _APP_JS.read_text(encoding="utf-8")
    nommes, espaces = symboles_importes(source)

    # `setToken` et `markTokenReady` sont les OBSERVABLES : ils sont redefinis
    # plus bas, apres les stubs generiques, pour enregistrer leurs appels.
    lignes = [f"globalThis.{nom} = function () {{ return undefined; }};" for nom in sorted(nommes)]
    lignes += [
        f"globalThis.{nom} = new Proxy({{}}, {{ get: () => function () {{ return undefined; }} }});"
        for nom in sorted(espaces)
    ]
    return "\n".join(lignes)


_ENVIRONNEMENT = r"""
// --- environnement navigateur minimal -------------------------------------
globalThis.__journal = { setToken: [], markTokenReady: 0, markTokenAbsent: 0, replaceState: [] };

function stockageFactice() {
  const donnees = new Map();
  return {
    getItem: (k) => (donnees.has(k) ? donnees.get(k) : null),
    setItem: (k, v) => { donnees.set(k, String(v)); },
    removeItem: (k) => { donnees.delete(k); },
    __donnees: donnees,
  };
}
globalThis.localStorage = stockageFactice();
globalThis.sessionStorage = stockageFactice();

function classeListe() {
  const vues = new Set();
  return { add: (c) => vues.add(c), remove: (c) => vues.delete(c), contains: (c) => vues.has(c), __vues: vues };
}
globalThis.document = {
  addEventListener() {}, removeEventListener() {},
  getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
  createElement: () => ({ style: {}, classList: classeListe(), appendChild() {} }),
  documentElement: { classList: classeListe() },
  body: { classList: classeListe(), appendChild() {} },
};

// `setInterval` doit rendre un handle SANS armer de minuterie : `app.js` en
// pose une a 3 600 000 ms au chargement, et Node resterait vivant jusqu'au
// timeout du harnais — un test qui n'en finit pas ressemble a un test lent.
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};
globalThis.setTimeout = (fn) => { if (typeof fn === "function") fn(); return 0; };

globalThis.__poserURL = (href) => {
  const u = new URL(href);
  globalThis.window.location = {
    href, search: u.search, hash: u.hash, pathname: u.pathname, origin: u.origin,
  };
};
globalThis.window = {
  addEventListener() {}, removeEventListener() {},
  history: {
    replaceState(_etat, _titre, url) {
      globalThis.__journal.replaceState.push(url);
      globalThis.__poserURL(globalThis.window.location.origin + url);
    },
  },
};
globalThis.__poserURL(globalThis.__URL_DE_DEPART);

// --- observables : redefinis APRES les stubs generes ----------------------
globalThis.setToken = function (valeur, persiste) {
  globalThis.__journal.setToken.push({ valeur, persiste });
};
globalThis.markTokenReady = function () { globalThis.__journal.markTokenReady += 1; };
globalThis.markTokenAbsent = function () { globalThis.__journal.markTokenAbsent += 1; };
globalThis.hasToken = function () { return false; };
"""

_PILOTE = r"""
__emit({
  setToken: globalThis.__journal.setToken,
  markTokenReady: globalThis.__journal.markTokenReady,
  replaceState: globalThis.__journal.replaceState,
  natif: globalThis.window.__CINESORT_NATIVE__ === true,
  drapeauStocke: globalThis.localStorage.getItem("cinesort.native"),
  urlFinale: globalThis.window.location.href,
  chargementAtteint: globalThis.window.__APP_JS_LOADED,
});
"""


def _boot(url: str) -> dict:
    """Charge `app.js` avec `window.location` positionnee sur `url`."""
    stubs = f"globalThis.__URL_DE_DEPART = {url!r};\n" + _stubs() + "\n" + _ENVIRONNEMENT
    return _jsexec.run_module_test(_APP_JS, stubs=stubs, extra="", driver=_PILOTE, timeout=60)


class LeHarnaisTientTests(unittest.TestCase):
    """Ce que le harnais doit prouver AVANT qu'on lui fasse confiance."""

    def test_les_stubs_couvrent_TOUS_les_imports(self) -> None:
        """La derivation, epinglee. Si `app.js` gagne un import et que la
        generation cesse de le voir, ce test rougit ICI plutot qu'au milieu
        d'une `ReferenceError` illisible.
        """
        source = _APP_JS.read_text(encoding="utf-8")
        nommes, espaces = symboles_importes(source)

        self.assertGreater(len(nommes), 30, f"extraction suspecte : {len(nommes)} symbole(s) nomme(s)")
        self.assertGreater(len(espaces), 3, f"extraction suspecte : {len(espaces)} espace(s) de noms")
        for attendu in ("setToken", "markTokenReady", "registerRoute", "startRouter"):
            self.assertIn(attendu, nommes, f"{attendu} n'est plus vu comme importe")
        self.assertIn("sidebarV5", espaces)

    def test_le_module_se_CHARGE_entierement(self) -> None:
        """`app.js` pose `__APP_JS_LOADED = "module-end-reached"` a sa derniere
        ligne de premier niveau. Sans cette assertion, une exception avalee en
        cours de route laisserait les observables a leur valeur initiale, et
        « aucun appel a setToken » passerait pour un resultat.
        """
        _jsexec.require_node(self)
        etat = _boot("http://127.0.0.1:8642/dashboard/?ntoken=JETON-DE-TEST&native=1")

        self.assertEqual(etat["chargementAtteint"], "module-end-reached")


class LeBootNatifActuelTests(unittest.TestCase):
    """Le comportement d'AUJOURD'HUI, fige. Aucune de ces assertions ne dit
    qu'il est bon — seulement qu'il est celui-la.
    """

    def setUp(self) -> None:
        _jsexec.require_node(self)

    def test_le_jeton_de_la_QUERY_est_lu_et_persiste(self) -> None:
        etat = _boot("http://127.0.0.1:8642/dashboard/?ntoken=JETON-DE-TEST&native=1")

        self.assertEqual(etat["setToken"], [{"valeur": "JETON-DE-TEST", "persiste": True}])
        self.assertTrue(etat["natif"])
        self.assertEqual(etat["drapeauStocke"], "1")

    def test_l_URL_est_PURGEE_du_jeton(self) -> None:
        """Le code purge deja `?ntoken=` de l'URL « pour ne pas le laisser dans
        l'historique ». Cette purge arrive APRES que WebView2 a enregistre la
        navigation : elle nettoie la barre d'adresse, pas l'historique. C'est
        precisement ce que le passage au fragment corrigera.
        """
        etat = _boot("http://127.0.0.1:8642/dashboard/?ntoken=JETON-DE-TEST&native=1")

        self.assertNotIn("ntoken", etat["urlFinale"])
        self.assertIn("native=1", etat["urlFinale"])

    def test_la_ligne_QUI_PURGE_est_morte(self) -> None:
        """TROUVAILLE DU HARNAIS, et la raison d'ecrire un filet avant un correctif.

        `url.searchParams.delete("ntoken")` porte le commentaire « purger le
        token de l'URL pour ne pas le laisser dans l'historique ». Cette ligne
        NE FAIT RIEN : l'URL finale est reconstruite a partir de `url.pathname`
        et d'un `?native=1` ecrit en dur, et `url.search` n'est jamais relu.

        Mesure : remplacer l'appel par `void 0` laisse les HUIT tests de ce
        fichier VERTS, alors que muter le parametre lu, l'appel a `setToken` ou
        le hash force en tue un ou trois. La purge existe — elle vient de la
        RECONSTRUCTION, pas de la ligne qui pretend la faire.

        La consequence n'est pas cosmetique : quelqu'un qui lit ce code croit
        qu'une purge explicite protege l'historique, et pourrait remplacer la
        reconstruction par un `url.toString()` « equivalent » — qui, lui,
        REINTRODUIRAIT le jeton, la ligne morte ne le retirant pas la ou il
        compte. Ce test epingle l'etat reel pour que le lot suivant tranche :
        soit la ligne devient effective, soit elle part avec son commentaire.
        """
        etat = _boot("http://127.0.0.1:8642/dashboard/?ntoken=JETON-DE-TEST&native=1")

        # L'URL passee a `replaceState` est construite de toutes pieces : elle
        # ne contient QUE le chemin, `?native=1` et le hash de route.
        self.assertEqual(len(etat["replaceState"]), 1, etat["replaceState"])
        self.assertEqual(etat["replaceState"][0], "/dashboard/?native=1#/accueil")

    def test_le_hash_LOGIN_est_remplace_par_accueil(self) -> None:
        etat = _boot("http://127.0.0.1:8642/dashboard/?ntoken=JETON-DE-TEST&native=1#/login")

        self.assertTrue(etat["urlFinale"].endswith("#/accueil"), etat["urlFinale"])

    def test_un_hash_de_route_VALIDE_est_conserve(self) -> None:
        etat = _boot("http://127.0.0.1:8642/dashboard/?ntoken=JETON-DE-TEST&native=1#/qualite")

        self.assertTrue(etat["urlFinale"].endswith("#/qualite"), etat["urlFinale"])

    def test_sans_ntoken_setToken_n_est_PAS_appele(self) -> None:
        """Contre-epreuve : sans elle, un harnais qui n'executerait jamais la
        branche `if (ntoken)` passerait les tests ci-dessus par accident.
        """
        etat = _boot("http://127.0.0.1:8642/dashboard/?native=1")

        self.assertEqual(etat["setToken"], [])

    def test_le_FRAGMENT_n_est_pas_lu_aujourd_hui(self) -> None:
        """L'etat de depart du correctif a venir. `#ntoken=...` est ignore :
        c'est ce que la PR suivante doit faire changer, et ce test devra alors
        etre inverse — deliberement, pas par surprise.
        """
        etat = _boot("http://127.0.0.1:8642/dashboard/?native=1#ntoken=JETON-DE-TEST")

        self.assertEqual(etat["setToken"], [])


if __name__ == "__main__":
    unittest.main()
