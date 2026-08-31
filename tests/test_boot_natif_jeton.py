# -*- coding: utf-8 -*-
"""Le jeton du boot natif ne transite QUE par le fragment (T-SEC-5).

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

CE FICHIER A ETE ECRIT EN DEUX TEMPS, et l'ordre etait le sujet.

L'etape 1 ne corrigeait rien : elle figeait le comportement d'alors, pour que le
correctif ait quelque chose a casser. Un test ecrit APRES un correctif ne prouve
que ce que le correctif fait, jamais ce qu'il a change sans le vouloir.

Le passage au fragment a fait rougir CINQ de ses tests — un par changement de
comportement. Chacun a ete traite separement, jamais efface en bloc :

    le jeton lu dans la query        -> inverse : la query n'est PLUS lue
    l'URL purgee du jeton            -> l'URL ne le porte NULLE PART
    la ligne de purge morte          -> retiree ; c'est la RECONSTRUCTION qui purge
    le hash `#/login` -> `#/accueil` -> inchange, mais la forme d'URL change
    le fragment ignore               -> inverse : le fragment EST le canal

Et l'etape 1 avait deja rapporte quelque chose qu'aucune relecture n'avait vu :
`url.searchParams.delete("ntoken")`, commentee « purger le token de l'URL »,
ne faisait RIEN — seul `url.pathname` etait relu. La remplacer par `void 0`
laissait les huit tests verts. Elle est retiree.

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


class LeJetonNeTransiteQueParLeFRAGMENTTests(unittest.TestCase):
    """LE CONTRAT APRES T-SEC-5. Chacune de ces assertions remplace une
    assertion de l'etape 1, et le remplacement est DELIBERE : le filet a
    rougi cinq fois, une fois par changement de comportement, et chaque rouge
    a ete traite separement au lieu d'etre efface en bloc.
    """

    def setUp(self) -> None:
        _jsexec.require_node(self)

    def test_le_jeton_du_FRAGMENT_est_lu_et_persiste(self) -> None:
        etat = _boot("http://127.0.0.1:8642/dashboard/?native=1#ntoken=JETON-DE-TEST")

        self.assertEqual(etat["setToken"], [{"valeur": "JETON-DE-TEST", "persiste": True}])
        self.assertTrue(etat["natif"])
        self.assertEqual(etat["drapeauStocke"], "1")

    def test_le_jeton_de_la_QUERY_n_est_PLUS_lu(self) -> None:
        """INVERSION ASSUMEE de `test_le_jeton_de_la_QUERY_est_lu_et_persiste`.

        Garder la query en repli aurait garde le defaut : une URL heritee, un
        signet, un raccourci, et le jeton repart dans la ligne de requete. Le
        canal est unique par choix.
        """
        etat = _boot("http://127.0.0.1:8642/dashboard/?ntoken=JETON-DE-TEST&native=1")

        self.assertEqual(etat["setToken"], [])

    def test_l_URL_finale_ne_porte_le_jeton_NULLE_PART(self) -> None:
        etat = _boot("http://127.0.0.1:8642/dashboard/?native=1#ntoken=JETON-DE-TEST")

        self.assertNotIn("JETON-DE-TEST", etat["urlFinale"])
        self.assertNotIn("ntoken", etat["urlFinale"])
        self.assertEqual(etat["replaceState"], ["/dashboard/?native=1#/accueil"])

    def test_le_hash_devient_ACCUEIL(self) -> None:
        """Le hash a servi au jeton, il ne porte donc aucune route. Le code
        d'origine « preservait un hash valide », mais les deux seuls cas qu'il
        rencontrait — hash vide, ou `#/login` restaure par WebView2 — menaient
        deja tous les deux a `#/accueil`.
        """
        etat = _boot("http://127.0.0.1:8642/dashboard/?native=1#ntoken=JETON-DE-TEST")

        self.assertTrue(str(etat["urlFinale"]).endswith("#/accueil"), etat["urlFinale"])

    def test_sans_jeton_setToken_n_est_PAS_appele(self) -> None:
        """Contre-epreuve : sans elle, un harnais qui n'entrerait jamais dans
        la branche `if (ntoken)` passerait tout le reste par accident.
        """
        etat = _boot("http://127.0.0.1:8642/dashboard/?native=1")

        self.assertEqual(etat["setToken"], [])

    def test_une_ROUTE_dans_le_hash_n_est_pas_prise_pour_un_jeton(self) -> None:
        """`#/accueil` parse en `URLSearchParams` donne une cle `/accueil` sans
        valeur. Si `get("ntoken")` y rendait autre chose que `null`, un reload
        WebView2 appellerait `setToken` avec n'importe quoi.
        """
        for hash_de_route in ("#/accueil", "#/login", "#/qualite"):
            with self.subTest(hash=hash_de_route):
                etat = _boot(f"http://127.0.0.1:8642/dashboard/?native=1{hash_de_route}")
                self.assertEqual(etat["setToken"], [])


class LeServeurNeVOITJamaisLeJetonTests(unittest.TestCase):
    """La propriete qui justifie tout le lot, MESUREE — pas invoquee.

    Un fragment n'est pas envoye au serveur. C'est la specification HTTP, mais
    le depot a paye assez cher des proprietes « evidentes » non mesurees pour
    que celle-ci vive dans la suite plutot que dans un message de commit.

    Aucun composant CineSort ici : un socket nu, pour que le test mesure le
    PROTOCOLE et non une implementation qui pourrait le contourner.

    CE QUE CE TEST MESURE EXACTEMENT : qu'un client HTTP CONFORME n'envoie pas
    le fragment. Le client est `urllib`, pas WebView2 — la propriete tient de la
    RFC 3986 §3.5 (« le fragment est separe du reste de l'URI AVANT tout
    dereferencement »), et tout client conforme s'y tient, Chromium compris.
    Mais c'est une DEDUCTION sur WebView2, pas une mesure de WebView2. Ce que ce
    test prouve sans reserve, c'est que le SERVEUR ne peut pas recevoir le
    fragment ; ce qu'il ne dit pas, c'est ce que le navigateur en garde dans son
    propre historique.
    """

    def test_la_ligne_de_requete_perd_le_jeton(self) -> None:
        import socket
        import threading
        import urllib.error
        import urllib.request

        recues: list[str] = []
        serveur = socket.socket()
        serveur.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        serveur.bind(("127.0.0.1", 0))
        serveur.listen(2)
        port = serveur.getsockname()[1]

        def servir() -> None:
            for _ in range(2):
                try:
                    client, _adresse = serveur.accept()
                except OSError:
                    return
                with client:
                    recues.append(client.recv(4096).decode("latin-1").splitlines()[0])
                    client.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")

        fil = threading.Thread(target=servir, daemon=True)
        fil.start()
        try:
            for suffixe in ("?ntoken=JETON-TEMOIN&native=1", "?native=1#ntoken=JETON-TEMOIN"):
                with contextlib_suppress():
                    # `noqa` couvre ruff, `nosec` couvre bandit : poser
                    # l'une ne fait pas taire l'autre, et le meme appel change
                    # de libelle a chaque outil. Ici le schema est un litteral
                    # `http://` et l'hote est le socket ouvert quelques lignes
                    # plus haut : aucune entree exterieure n'atteint cette URL.
                    # Temoin : sans la marque, bandit rend 1 resultat B310 sur
                    # cette ligne exacte ; avec, 0 sur 280 lignes scannees.
                    urllib.request.urlopen(  # nosec B310  # noqa: S310
                        f"http://127.0.0.1:{port}/dashboard/{suffixe}", timeout=5
                    ).read()
            fil.join(timeout=5)
        finally:
            serveur.close()

        self.assertEqual(len(recues), 2, recues)
        par_query, par_fragment = recues
        self.assertIn("JETON-TEMOIN", par_query, "temoin positif : la query, elle, porte bien le jeton")
        self.assertNotIn("JETON-TEMOIN", par_fragment, par_fragment)

    def test_app_py_emet_bien_un_FRAGMENT(self) -> None:
        """L'URL est APPELEE, plus cherchee dans le source.

        La premiere version de ce test grepait `main_url = f` dans `app.py` et
        verifiait l'absence de `?ntoken=`. L'extraction d'`url_de_boot_natif`
        (imposee par le cliquet de taille) a fait disparaitre cette ligne : le
        test serait devenu un FAUX VERT — zero ligne trouvee, zero assertion
        violee. Un test qui compare une chaine de code source tombe quand le
        code s'ameliore et ne detecte rien quand il casse.
        """
        from app import url_de_boot_natif

        url = url_de_boot_natif("http", 8642, "JETON-DE-TEST")

        self.assertIn("#ntoken=JETON-DE-TEST", url)
        self.assertNotIn("?ntoken=", url)
        self.assertNotIn("&ntoken=", url)
        # `?native=1` reste dans la query : ce n'est pas un secret, et
        # `_detectNativeBoot` le lit avant meme de regarder le jeton.
        self.assertIn("?native=1", url.split("#", 1)[0])

    def test_sans_jeton_l_URL_ne_porte_aucun_fragment(self) -> None:
        """Contre-epreuve : sans elle, une fonction qui collerait toujours un
        `#ntoken=` — meme vide — passerait le test precedent.
        """
        from app import url_de_boot_natif

        self.assertNotIn("#", url_de_boot_natif("http", 8642, ""))

    def test_le_journal_de_diagnostic_DERIVE_l_URL(self) -> None:
        """La version precedente imprimait `?ntoken=...&native=1` — la forme
        d'AVANT ce lot. Un message de diagnostic qui decrit une URL que le code
        ne construit plus envoie chercher le defaut au mauvais endroit.
        """
        from app import empreinte_jeton, url_de_boot_natif, url_de_boot_redigee

        jeton = "JETON-DE-TEST-COMPLET"
        redigee = url_de_boot_redigee("http", 8642, jeton)

        # INVERSION ASSUMEE : cette assertion exigeait `jeton[:8] in redigee`,
        # parce que c'etait le comportement d'avant. CodeQL
        # `py/clear-text-logging` l'a signale et il avait raison — huit
        # caracteres d'un `token_urlsafe` de trente-deux, c'est divulguer une
        # partie du secret. L'empreinte repond a la MEME question sans en
        # reveler un seul caractere.
        self.assertNotIn(jeton, redigee)
        for depart in range(len(jeton) - 5):
            with self.subTest(morceau=jeton[depart : depart + 6]):
                self.assertNotIn(jeton[depart : depart + 6], redigee)
        self.assertIn(empreinte_jeton(jeton), redigee)
        self.assertTrue(redigee.startswith(url_de_boot_natif("http", 8642, "")))

    def test_l_empreinte_est_un_HMAC_pas_un_hash_du_secret(self) -> None:
        """CodeQL `py/weak-sensitive-data-hashing` ne reproche pas SHA-256 : il
        reproche de hacher un SECRET avec une primitive rapide, ce qui laisse
        une attaque par dictionnaire sur l'empreinte. Le secret doit etre la
        CLE, pas le message — meme parti que `plan_support_core.py`, qui a
        ferme l'alerte #264 le meme jour.
        """
        import hashlib
        import hmac

        from app import empreinte_jeton

        jeton = "JETON-DE-TEST-COMPLET"

        self.assertNotEqual(
            empreinte_jeton(jeton),
            hashlib.sha256(jeton.encode()).hexdigest()[:12],
            "l'empreinte est un sha256 nu du secret : c'est le geste que CodeQL refuse",
        )
        self.assertEqual(
            empreinte_jeton(jeton),
            hmac.new(
                key=jeton.encode("utf-8", "replace"),
                msg=b"cinesort:boot_token_fingerprint:v1",
                digestmod=hashlib.sha256,
            ).hexdigest()[:12],
        )
        self.assertNotEqual(empreinte_jeton("A"), empreinte_jeton("B"))


def contextlib_suppress():
    """`contextlib.suppress(Exception)`, nomme pour que l'intention se lise :
    l'appel PEUT echouer (le faux serveur ferme la connexion), seul compte ce
    que le socket a RECU.
    """
    import contextlib

    return contextlib.suppress(Exception)


class LeDiagnosticNEcritJamaisLeJetonTests(unittest.TestCase):
    """CodeQL `py/clear-text-logging-sensitive-data` a signale QUATRE
    expressions de `main()` qui journalisaient le jeton sous `CINESORT_DEBUG` :
    la liste de ses codepoints, ses caracteres non-ASCII un a un, et DEUX fois
    sa forme encodee.

    Elles existaient pour une raison reelle (2026-06-07 : les puces U+2022 du
    masquage de secret arrivaient jusqu'au boot et `quote` les transformait en
    `%E2%80%A2`). Aucune de ces questions ne demandait la VALEUR.
    """

    def test_le_diagnostic_ne_contient_pas_le_jeton(self) -> None:
        from app import diagnostic_jeton

        jeton = "JETON-SECRET-DE-TEST-abc123"
        rendu = diagnostic_jeton(jeton)

        self.assertNotIn(jeton, rendu)
        for morceau in (jeton[:8], jeton[-8:], jeton[10:20]):
            with self.subTest(morceau=morceau):
                self.assertNotIn(morceau, rendu)

    def test_il_distingue_les_DEUX_corruptions_historiques(self) -> None:
        """Contre-epreuve : un diagnostic qui ne dirait rien serait aussi sans
        fuite. Il doit nommer la corruption, position et codepoint compris.
        """
        from app import diagnostic_jeton

        puce = diagnostic_jeton("abc\u2022def")
        self.assertIn("ascii_pur=False", puce)
        self.assertIn("U+2022", puce)
        self.assertIn("(3,", puce)

        bom = diagnostic_jeton("\ufeffabcdef")
        self.assertIn("U+FEFF", bom)
        self.assertIn("(0,", bom)

    def test_un_jeton_SAIN_est_annonce_sain(self) -> None:
        """L'autre sens : sans lui, un diagnostic qui crierait toujours
        « corrompu » passerait le test precedent.
        """
        from app import diagnostic_jeton

        rendu = diagnostic_jeton("aBc-123_xyz")

        self.assertIn("ascii_pur=True", rendu)
        self.assertIn("pourcents=0", rendu)
        self.assertIn("non_ascii=[]", rendu)

    def test_l_empreinte_DISTINGUE_deux_jetons(self) -> None:
        """Le remplacant du dump de codepoints : ce qu'on cherchait etait
        « est-ce le MEME jeton qu'a l'autre bout ? ». Une empreinte repond, et
        se compare d'un coup d'oeil.
        """
        from app import diagnostic_jeton

        self.assertNotEqual(diagnostic_jeton("jeton-A"), diagnostic_jeton("jeton-B"))
        self.assertEqual(diagnostic_jeton("jeton-A"), diagnostic_jeton("jeton-A"))

    def test_aucun_PRINT_de_app_py_ne_formate_le_jeton(self) -> None:
        """Garde de non-retour, pose a l'AST et non au grep.

        Le defaut n'etait pas une ligne mais une HABITUDE : CINQ expressions
        ecrites a des moments differents, dans DEUX fonctions, toutes pour
        diagnostiquer le meme bug de 2026-06-07. Une premiere version de ce
        garde cherchait les motifs ligne par ligne — et accusait la docstring de
        `diagnostic_jeton`, qui DECRIT les expressions retirees. Un garde qui
        mord la documentation de son propre correctif finit desactive.

        Il n'inspecte donc que les ARGUMENTS des appels a `print` : c'est la
        seule chose qui atteint reellement stderr.
        """
        import ast

        source = (_RACINE / "app.py").read_text(encoding="utf-8")
        arbre = ast.parse(source)

        interdits = ("codepoints=", "_encoded_token", "char={c", "{value}", "{token}")
        coupables = []
        for noeud in ast.walk(arbre):
            if not (isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name) and noeud.func.id == "print"):
                continue
            for argument in noeud.args:
                extrait = ast.get_source_segment(source, argument) or ""
                for motif in interdits:
                    if motif in extrait:
                        coupables.append(f"app.py:{noeud.lineno} {motif} dans {extrait[:60]}")

        self.assertEqual(
            coupables,
            [],
            "un print d'app.py reformate une valeur derivee du jeton : " + " | ".join(coupables),
        )

    def test_le_garde_AST_voit_bien_les_print(self) -> None:
        """Contre-epreuve du garde : `ast.get_source_segment` rend None si le
        module n'a pas ete parse avec `type_comments`, ou si les positions sont
        absentes. Un garde qui n'inspecte rien rend zero coupable — et zero
        ressemble a « rien a signaler ».
        """
        import ast

        source = (_RACINE / "app.py").read_text(encoding="utf-8")
        arbre = ast.parse(source)

        appels = [
            n
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
        ]
        self.assertGreater(len(appels), 20, f"{len(appels)} appels a print trouves : extraction suspecte")
        extraits = [ast.get_source_segment(source, a) for n in appels for a in n.args]
        self.assertTrue(any(extraits), "aucun argument de print n'a pu etre relu depuis le source")

    def test_l_URL_redigee_ne_FABRIQUE_jamais_la_chaine_complete(self) -> None:
        """« Construire puis retrancher » est plus faible que « ne jamais
        construire ».

        La version precedente appelait `url_de_boot_natif(proto, port, jeton)`
        puis decoupait sur `#ntoken=`. CodeQL `py/clear-text-logging` a suivi ce
        flux jusqu'au `print` — et ne signalait PAS un faux positif : la chaine
        contenant le jeton existait vraiment, on la tranchait apres coup. Il
        suffit qu'un jour quelqu'un journalise la valeur intermediaire, ou
        qu'une exception passe entre les deux, pour que le secret sorte.

        Ce test lit l'AST : le seul argument que `url_de_boot_redigee` a le
        droit de passer a `url_de_boot_natif` est la chaine VIDE.
        """
        import ast

        source = (_RACINE / "app.py").read_text(encoding="utf-8")
        arbre = ast.parse(source)

        fonction = next(
            n for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef) and n.name == "url_de_boot_redigee"
        )
        appels = [
            n
            for n in ast.walk(fonction)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "url_de_boot_natif"
        ]

        self.assertEqual(len(appels), 1, "extraction suspecte : un seul appel est attendu")
        dernier = appels[0].args[-1]
        self.assertIsInstance(dernier, ast.Constant, ast.get_source_segment(source, dernier))
        self.assertEqual(dernier.value, "", "le jeton ne doit JAMAIS entrer dans l'URL construite ici")

    def test_le_jeton_n_atteint_que_l_EMPREINTE(self) -> None:
        """Contre-epreuve du precedent : il verifie ou le jeton ne va PAS ;
        celui-ci verifie qu'il va bien quelque part, sinon la fonction aurait
        cesse d'identifier quoi que ce soit.
        """
        from app import empreinte_jeton, url_de_boot_redigee

        a = url_de_boot_redigee("http", 8642, "jeton-A")
        b = url_de_boot_redigee("http", 8642, "jeton-B")

        self.assertNotEqual(a, b, "deux jetons differents rendent la meme trace : elle n'identifie rien")
        self.assertIn(empreinte_jeton("jeton-A"), a)
