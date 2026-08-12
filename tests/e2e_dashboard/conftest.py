"""Fixtures E2E dashboard workflow — reutilise l'infrastructure tests/e2e.

Ce conftest charge les fixtures du dashboard E2E existant (serveur REST,
authenticated_page, rate limiter reset) via pytest_plugins.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

import pytest

try:
    import allure
except ImportError:
    allure = None

# Rendre tests/e2e importable (pas de __init__.py pour eviter unittest discover)
_e2e_dir = str(Path(__file__).resolve().parent.parent / "e2e")
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

# Importer les donnees de test et les fonctions utilitaires
import contextlib
import json
import shutil
import socket
import tempfile
import time
from http.client import HTTPConnection

from create_test_data import (  # noqa: E402
    _TOKEN,
    build_plan_rows,
    get_settings_dict,
    populate_database,
    write_plan_file,
)

from tests._helpers import find_free_port as _find_free_port


def _wait_server_ready(port: int, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            if resp.status == 200:
                return
        except (ConnectionRefusedError, OSError):
            pass
        finally:
            with contextlib.suppress(Exception):
                conn.close()
        time.sleep(0.1)
    raise TimeoutError(f"Serveur non demarre en {timeout_s}s sur le port {port}")


# Lot C-fix (2026-07-08) : scope module (etait session) — en execution groupee,
# le serveur partage propageait les mutations d'un fichier de sweep au suivant
# (alertes ignorees, decisions, jobs) => 10 echecs en cascade. Un serveur par
# fichier isole les datasets ; cout ~3s/fichier.
@pytest.fixture(scope="module")
def e2e_server() -> Generator[Dict[str, Any], None, None]:
    """Demarre un serveur REST CineSort avec 15 films mock."""
    import cinesort.ui.api.cinesort_api as backend
    from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir
    from cinesort.infra.rest_server import RestApiServer

    tmp = tempfile.mkdtemp(prefix="cinesort_e2e_dash_")
    root = Path(tmp) / "root"
    state_dir = Path(tmp) / "state"
    root.mkdir()
    state_dir.mkdir()

    api = backend.CineSortApi()
    api.settings.save_settings(get_settings_dict(root, state_dir))

    db_path = db_path_for_state_dir(state_dir)
    store = SQLiteStore(db_path)
    store.initialize()

    rows = build_plan_rows()
    info = populate_database(store, root, state_dir)
    write_plan_file(state_dir, info["run_id"], rows)
    write_plan_file(state_dir, info["old_run_id"], rows[:10])

    port = _find_free_port()
    server = RestApiServer(api, port=port, token=_TOKEN)
    server.start()
    _wait_server_ready(port)

    # L'URL reste NUE. Jusqu'au 2026-08-07 le harnais ne devait son acces qu'au
    # BYPASS D'AUTH loopback — il n'eprouvait donc JAMAIS l'authentification, et
    # le retrait du bypass l'a mis a nu. Le jeton est desormais depose dans le
    # **sessionStorage** par la fixture `authenticated_page`, avant tout script
    # de la page ; voir son corps pour les deux variantes ecartees par la mesure
    # (`?ntoken=` dans l'URL, et `localStorage`).
    yield {
        "url": f"http://127.0.0.1:{port}",
        "dashboard_url": f"http://127.0.0.1:{port}/dashboard/",
        "token": _TOKEN,
        "port": port,
        "root": root,
        "state_dir": state_dir,
        "run_id": info["run_id"],
        "old_run_id": info["old_run_id"],
        "rows": rows,
        "_server": server,
        # #1002 : expose pour la fixture `scan_actif`, qui doit semer un run EN
        # COURS dans l'etat memoire de CETTE api (`_active_run_id` lit
        # `api._runs`, pas la base). Le store n'est pas expose ici : la fixture
        # prend celui de l'api via `_get_or_create_infra`, car le `store` local
        # ci-dessus est une SECONDE instance ouverte sur le meme fichier.
        "_api": api,
    }

    server.stop()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def browser_context_args() -> Dict[str, Any]:
    return {
        "locale": "fr-FR",
        "timezone_id": "Europe/Paris",
        "ignore_https_errors": True,
    }


#: Premiere attente du shell : courte, pour ne pas payer 30 s a chaque test
#: quand le dashboard repond normalement.
_SHELL_TIMEOUT_MS = 8000

#: Seconde attente, une fois etabli que l'authentification n'est PAS en cause.
#: Le runner de CI est partage et son debit varie fortement ; 8 s y sont un
#: plancher de bruit, pas une mesure. On ne paie ce budget que sur le chemin
#: lent, donc il ne coute rien quand tout va bien.
_SHELL_TIMEOUT_LENT_MS = 30000


#: Erreurs reseau TRANSITOIRES de Chromium : la ressource manque a l'instant T,
#: elle revient. Toute autre erreur (DNS, refus de connexion, TLS) designe un
#: vrai probleme et ne doit PAS etre reessayee — la reessayer retarderait un
#: diagnostic juste.
_ERREURS_RESEAU_TRANSITOIRES = ("ERR_NO_BUFFER_SPACE", "ERR_INSUFFICIENT_RESOURCES")
#: Paliers d'attente avant de recharger. Total ~1,4 s : negligeable devant les
#: 8 s d'attente du shell qui suivent, et suffisant pour qu'un port ephemere se
#: libere (TIME_WAIT court sur les runners Windows).
_PALIERS_GOTO_S = (0.0, 0.1, 0.3, 1.0)


#: Journalise chaque `fetch` AVEC SA PILE D'APPEL, pour pouvoir attribuer une
#: requete a son module d'origine.
#:
#: POURQUOI. Deux tests demandent « 0 requete de polling apres demontage de la
#: vue ». Or `components/scan-banner.js` polle `run/get_dashboard` **toutes les
#: 5 s de facon globale et permanente**, ET re-tique sur chaque `hashchange` —
#: donc a chaque navigation declenchee par le test lui-meme. Filtrer par URL ne
#: peut pas distinguer la banniere de la vue : c'est la MEME route.
#:
#: Ces tests ne s'en apercevaient pas parce que la banniere ne demarre PAS sans
#: authentification (`initScanBanner` sort si `!hasToken()`), et le harnais
#: n'avait aucun jeton — il vivait sur le bypass d'auth loopback. Le test
#: `unmount_accueil` partait donc en `skip` a chaque execution : il n'a JAMAIS
#: rien eprouve.
_JS_JOURNAL_FETCH = r"""
(() => {
  try {
    if (window.__cinesortFetchLog) return;
    window.__cinesortFetchLog = [];
    const _fetch = window.fetch;
    window.fetch = function (...args) {
      try {
        const url = String((args[0] && args[0].url) || args[0] || "");
        const pile = (new Error().stack || "");
        window.__cinesortFetchLog.push({ t: performance.now(), url, pile });
      } catch (e) { /* no-op */ }
      return _fetch.apply(this, args);
    };
  } catch (e) { /* no-op */ }
})();
"""


def journal_fetch(page, *, depuis_ms: float = 0.0, motif_url: str = "", exclure_module: str = "") -> list:
    """Requetes `fetch` observees, attribuables a leur module appelant.

    `exclure_module` filtre sur la PILE D'APPEL, pas sur l'URL : c'est le seul
    moyen de distinguer deux appelants de la meme route (cf. `_JS_JOURNAL_FETCH`).
    """
    entrees = page.evaluate("() => (window.__cinesortFetchLog || []).slice()")
    sortie = []
    for e in entrees:
        if e.get("t", 0) < depuis_ms:
            continue
        if motif_url and motif_url not in str(e.get("url", "")):
            continue
        if exclure_module and exclure_module in str(e.get("pile", "")):
            continue
        sortie.append(e)
    return sortie


def horloge_page(page) -> float:
    """`performance.now()` de la page — la meme horloge que `journal_fetch`."""
    return float(page.evaluate("() => performance.now()"))


def _aller_au_dashboard(page, e2e_server: Dict[str, Any]) -> None:
    """`page.goto` avec reprise sur une penurie de ressource reseau (#924).

    POURQUOI ICI. Le correctif keep-alive de #924 a fait passer le serveur de
    26 sockets a 1 pour 6 serveurs x 4 requetes, et la frequence de
    `net::ERR_NO_BUFFER_SPACE` s'est effondree — mais pas a zero : une
    occurrence sur ~25 executions de `main` (run 31086285725). Le diagnostic
    ajoute a l'epoque vit dans l'attente du shell, plus bas ; or cette
    occurrence-la frappe AU `goto`, donc la page n'est jamais chargee et le
    diagnostic ne se declenche pas. L'instrument etait sur la mauvaise ligne.

    Ce que fait cette fonction : elle recharge sur les seules erreurs qui
    signalent une penurie momentanee de ports ephemeres, et elle NE MASQUE
    rien — si la penurie persiste, la derniere exception est relancee, enrichie
    de l'etat du serveur au moment de l'echec (`connect_ex` sur son port), ce
    qui tranche enfin entre « le serveur est mort » et « le client n'a plus de
    socket pour l'atteindre ».
    """
    url = e2e_server["dashboard_url"]
    derniere: Optional[Exception] = None
    for attente in _PALIERS_GOTO_S:
        if attente:
            time.sleep(attente)
        try:
            page.goto(url)
            return
        except Exception as exc:  # noqa: BLE001 -- on filtre juste apres
            message = str(exc)
            if not any(motif in message for motif in _ERREURS_RESEAU_TRANSITOIRES):
                raise
            derniere = exc
    assert derniere is not None
    raise RuntimeError(_diagnostic_shell_absent(page, e2e_server, derniere)) from derniere


def _diagnostic_shell_absent(page, e2e_server: Dict[str, Any], exc: Exception) -> str:
    """Message d'echec ENRICHI quand le shell n'apparait jamais.

    Issue #924. Le shell qui ne s'affiche pas apres 30 s en CI n'est PAS de la
    lenteur — c'est « jamais ». Trois faits font converger vers un epuisement de
    ressources du runner plutot que vers un defaut applicatif : un
    `net::ERR_NO_BUFFER_SPACE` deja observe sur ce workflow, une fixture
    `e2e_server` en portee MODULE reclamee par 11 modules (donc autant de
    serveurs REST sur des ports ephemeres), et une CI deux fois plus lente que
    le poste local — donc des sockets qui vivent deux fois plus longtemps.

    Rien de tout cela n'est DEMONTRE. Le raisonnement par elimination a deja
    coute trois enquetes ; ce diagnostic capture l'etat AU MOMENT DE LA PANNE
    pour trancher a la premiere occurrence suivante, au lieu d'attendre la
    suivante encore.

    Ne leve jamais : un diagnostic qui plante masquerait l'erreur qu'il decrit.
    """
    lignes = [f"Le shell n'est jamais apparu ({_SHELL_TIMEOUT_LENT_MS} ms). {exc}"]

    port = e2e_server.get("port")
    lignes.append(f"  port du serveur de test : {port}")

    # Le serveur repond-il ENCORE ? C'est la question qui separe « application
    # lente » de « socket morte ».
    if isinstance(port, int):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3.0)
                code = s.connect_ex(("127.0.0.1", port))
            lignes.append(
                f"  connect_ex(127.0.0.1:{port}) = {code}"
                f"{'  -> le serveur ACCEPTE encore' if code == 0 else '  -> serveur INJOIGNABLE'}"
            )
        except OSError as err:
            lignes.append(f"  connect_ex impossible : {err}")

    # Etat de la page : le DOM est-il seulement arrive ?
    with contextlib.suppress(Exception):
        lignes.append(f"  page.url = {page.url}")
    with contextlib.suppress(Exception):
        shell = page.locator("#app-shell")
        lignes.append(
            f"  #app-shell present={shell.count() > 0} "
            f"class={shell.get_attribute('class') if shell.count() else '(absent)'}"
        )
    with contextlib.suppress(Exception):
        lignes.append(f"  <title> = {page.title()!r}")

    # Mesure du 2026-08-05 : le serveur REPOND (connect_ex = 0), la page est
    # chargee, `#app-shell` EXISTE mais garde sa classe `hidden`. L'epuisement
    # de sockets est donc REFUTE — le defaut est dans l'amorcage frontend.
    #
    # Restent DEUX causes que le diagnostic ne separait pas :
    #   (1) la route vaut "/login" -> router.js fait
    #       shell.classList.toggle("hidden", isLogin), donc le shell reste
    #       cache legitimement ;
    #   (2) un `await` de la chaine d'amorcage n'a jamais rendu la main —
    #       `_mountV5Shell` et `_loadDashTheme` n'ont AUCUN garde-fou de delai,
    #       contrairement a `initI18n` et `cachedGetSettings`.
    #
    # `__APP_JS_LOADED` (app.js:558/561) tranche a lui seul jusqu'ou le module
    # est alle : absent = le module n'a pas ete evalue, "module-end-reached" =
    # evalue mais DOMContentLoaded jamais declenche, "domcontentloaded-fired" =
    # l'amorcage a demarre et s'est arrete DEDANS.
    with contextlib.suppress(Exception):
        etat = page.evaluate(
            "() => ({"
            " hash: location.hash,"
            " appJs: window.__APP_JS_LOADED || '(absent)',"
            " token: !!(localStorage.getItem('cinesort_token')),"
            " loginVisible: !document.getElementById('view-login')?.classList.contains('hidden'),"
            "})"
        )
        lignes.append(
            f"  location.hash = {etat.get('hash')!r}"
            f"{'  -> route de LOGIN : le shell est cache A RAISON' if str(etat.get('hash')).startswith('#/login') else ''}"
        )
        lignes.append(f"  __APP_JS_LOADED = {etat.get('appJs')!r}")
        lignes.append(f"  token en localStorage = {etat.get('token')}")
        lignes.append(f"  #view-login visible = {etat.get('loginVisible')}")

    # Erreurs console : c'est la que ERR_NO_BUFFER_SPACE apparaitrait.
    with contextlib.suppress(Exception):
        erreurs = getattr(page, "_cinesort_console_errors", None)
        if erreurs:
            lignes.append(f"  erreurs console ({len(erreurs)}) : {erreurs[:5]}")

    return "\n".join(lignes)


def _brancher_capture_console(page) -> None:
    """Attache un ECOUTEUR de console. Sans lui, le diagnostic lisait du vide.

    Le diagnostic de la PR #925 lisait `page._cinesort_console_errors` — un
    attribut que RIEN ne peuplait. La ligne « erreurs console » ne s'affichait
    donc jamais, et une erreur JS pendant l'amorcage passait inapercue :
    precisement l'information qui manque pour trancher #924.

    Defaut de l'instrumentation, pas du code teste.
    """
    if getattr(page, "_cinesort_console_branche", False):
        return
    erreurs: List[str] = []
    page._cinesort_console_errors = erreurs
    page._cinesort_console_branche = True

    def _sur_message(msg) -> None:
        with contextlib.suppress(Exception):
            if msg.type in ("error", "warning"):
                erreurs.append(f"[{msg.type}] {msg.text}"[:300])

    def _sur_pageerror(err) -> None:
        with contextlib.suppress(Exception):
            erreurs.append(f"[pageerror] {err}"[:300])

    # Ne jamais laisser la capture casser le test qu'elle observe.
    with contextlib.suppress(Exception):
        page.on("console", _sur_message)
    with contextlib.suppress(Exception):
        page.on("pageerror", _sur_pageerror)


@pytest.fixture(scope="function")
def authenticated_page(page, e2e_server: Dict[str, Any]):
    """Page Playwright connectee au dashboard.

    Lot C (verif totale 2026-07) : depuis le bypass auth localhost
    (rest_server 2026-06-08), le dashboard saute l'ecran de login sur
    loopback et arrive directement sur le shell — les 50 tests runtime
    erroraient a attendre #loginToken. Shell d'abord, fallback login si
    le bypass est desactive (CINESORT_DISABLE_LOCAL_AUTH=1).
    """
    from playwright.sync_api import TimeoutError as PWTimeoutError

    url = e2e_server["dashboard_url"]
    token = e2e_server["token"]

    # --- Authentification, AVANT que le moindre script de la page ne tourne ---
    #
    # C'est `sessionStorage` qu'il faut ecrire, pas `localStorage` : `getToken()`
    # (core/state.js) lit sessionStorage EN PRIORITE et ne consulte localStorage
    # que si le drapeau `cinesort.dashboard.persist` vaut "1". Une version
    # intermediaire n'ecrivait que localStorage, sans ce drapeau : `getToken()`
    # rendait une chaine vide et trois tests retombaient.
    #
    # Ecrire cette seule cle equivaut exactement a `setToken(token, persist=false)`
    # — une session web connectee, sans « se souvenir de moi ». Le portillon de
    # boot d'`app.js` la cherche explicitement et appelle `markTokenReady()` :
    # les quatre requetes initiales partent donc AVEC le Bearer, sans attendre
    # le deadline de 2 s.
    #
    # POURQUOI PAS `?ntoken=` DANS L'URL, comme le fait `app.py`. Mesure : deux
    # tests de minuterie tombent. Cause ISOLEE (bypass restaure, jeton dans
    # l'URL conserve : les memes deux tombent) — ce n'est pas le retrait du
    # bypass. Quand `ntoken` est present, `app.js` appelle `setToken()` PUIS
    # purge l'URL par `history.replaceState`, ce qui decale le demarrage que ces
    # tests mesurent.
    #
    # POURQUOI ICI ET NON DANS `_aller_au_dashboard` : cette fonction traite de
    # la REPRISE RESEAU (#924) et rien d'autre. Y greffer l'authentification a
    # casse ses quatre tests unitaires, dont la page factice n'a evidemment pas
    # d'`add_init_script` — deux sujets sans rapport dans une meme fonction.
    page.add_init_script(
        "try { sessionStorage.setItem('cinesort.dashboard.token', "
        + json.dumps(token)
        + "); } catch (e) { /* no-op */ }"
    )
    page.add_init_script(_JS_JOURNAL_FETCH)

    # AVANT le goto : une erreur d'amorcage survient pendant le chargement.
    _brancher_capture_console(page)
    _aller_au_dashboard(page, e2e_server)
    try:
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=_SHELL_TIMEOUT_MS)
        return page
    except PWTimeoutError:
        pass

    # Le premier timeout a DEUX causes possibles, et l'ancienne version n'en
    # traitait qu'une : elle enchainait directement sur l'attente de
    # `#loginToken`. Or le bypass d'authentification localhost laisse le
    # formulaire de login dans le DOM mais CACHE — l'attente echouait donc sur
    # « locator resolved to hidden <input id="loginToken"> », un message qui
    # designe le mauvais coupable.
    #
    # Mesure du 2026-08-05 : cette erreur apparait dans 4 des 8 derniers runs de
    # CI en echec. La cause reelle n'est pas l'authentification, c'est que le
    # shell met parfois plus de 8 s a s'afficher sous la charge du runner.
    #
    # On distingue donc les deux cas au lieu d'en supposer un :
    #   - formulaire de login PRESENT mais CACHE  -> le bypass est actif,
    #     l'authentification n'est pas en cause : on laisse au shell le temps
    #     qu'il lui faut ;
    #   - formulaire VISIBLE                      -> le bypass est desactive
    #     (CINESORT_DISABLE_LOCAL_AUTH=1), il faut vraiment se connecter.
    login = page.locator("#loginToken")
    bypass_actif = login.count() > 0 and not login.is_visible()

    if bypass_actif:
        # Pas de repli possible ni souhaitable : si le shell n'apparait toujours
        # pas, c'est un vrai defaut, et le message doit le dire.
        try:
            page.wait_for_selector("#app-shell:not(.hidden)", timeout=_SHELL_TIMEOUT_LENT_MS)
        except PWTimeoutError as exc:
            raise PWTimeoutError(_diagnostic_shell_absent(page, e2e_server, exc)) from exc
        return page

    page.wait_for_selector("#loginToken", state="visible", timeout=_SHELL_TIMEOUT_MS)
    page.fill("#loginToken", token)
    page.click("#loginBtn")
    # Attendre que le shell devienne visible (login reussi)
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=_SHELL_TIMEOUT_LENT_MS)
    return page


@pytest.fixture(scope="function")
def dashboard_page(authenticated_page):
    """Alias pour authenticated_page."""
    return authenticated_page


@pytest.fixture(scope="function")
def scan_actif(e2e_server: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
    """Sème un run EN COURS dans l'etat memoire du serveur e2e (#1002).

    POURQUOI CETTE FIXTURE EXISTE. `accueil.js` n'arme son polling que si un
    scan est actif au boot (`if (initialScan.active)`), et le jeu de donnees de
    `e2e_server` n'en contient aucun. Le test de fuite de polling de l'Accueil
    mesurait donc une ligne de base de ZERO : son assertion « aucune fuite »
    etait trivialement vraie, et il ne pouvait rien eprouver.

    POURQUOI ELLE NE DEMARRE PAS SON PROPRE SERVEUR. C'etait la premiere des
    deux directions proposees par l'issue. Elle ajouterait un serveur REST de
    plus sur un port ephemere, alors que #924 — `net::ERR_NO_BUFFER_SPACE`,
    encore une occurrence sur ~25 executions de `main` — designe precisement le
    nombre de serveurs comme piste structurelle. Corriger un test en aggravant
    un defaut ouvert n'est pas un correctif.

    POURQUOI ELLE NE TOUCHE PAS AU JEU DE DONNEES COMMUN. C'etait la seconde
    direction. La fixture est en portee module et une cinquantaine de tests en
    dependent ; y ajouter un run actif les exposerait tous a une carte « Scan en
    cours » qu'ils n'attendent pas.

    CE QU'ELLE FAIT. Elle emprunte le chemin de PRODUCTION
    (`run_flow_support._preparer_le_run` : `_reserve_unique_run`, puis
    `_build_cfg_from_settings`, puis `RunState`) plutot que de fabriquer un
    double. Un faux objet exposant `running=True` satisferait `_active_run_id`
    sans rien prouver de ce que le dashboard recoit reellement.

    Elle retire le run en sortie : la fixture serveur est partagee par le
    module, et un run laisse en cours contaminerait les tests suivants.
    """
    from cinesort.ui.api._run_state import RunState

    api = e2e_server["_api"]
    # Le couple (store, runner) vient de l'api elle-meme, comme en production :
    # `api._runner` n'existe pas, et le store de la fixture est une SECONDE
    # instance ouverte sur le meme fichier.
    store, runner = api._get_or_create_infra(e2e_server["state_dir"])

    run_id, run_paths = api._reserve_unique_run(store, e2e_server["state_dir"])
    cfg = api._build_cfg_from_settings(
        get_settings_dict(e2e_server["root"], e2e_server["state_dir"]),
        e2e_server["root"],
    )
    rs = RunState(run_paths, cfg, runner=runner, store=store)
    # `_active_run_id` exige les DEUX : `running` vrai ET `done` faux.
    rs.running = True
    rs.done = False
    rs.total = 15
    rs.idx = 3
    rs.current_folder = "Inception (2010)"

    with api._runs_lock:
        api._runs[run_id] = rs

    try:
        yield {"run_id": run_id, "run_state": rs}
    finally:
        with api._runs_lock:
            api._runs.pop(run_id, None)


@pytest.fixture(autouse=True)
def _jeton_pour_page_nue(request):
    """Authentifie AUSSI les tests qui prennent `page` au lieu de `authenticated_page`.

    LE DEFAUT QUE CECI CORRIGE. Le retrait du bypass d'auth loopback (#1001) a
    donne un jeton a `authenticated_page`, mais les fichiers de sweep prennent
    `page` NU — 52 occurrences dans le seul `test_lotc_sweep_traitement.py`.
    Ces pages n'avaient donc plus aucun jeton, donc plus aucune donnee.

    LA CI NE POUVAIT PAS LE VOIR : son perimetre ignore `tests/e2e_dashboard`.
    Mesure A/B sur `test_lotc_sweep_accueil.py`, une seule variable :

        au commit AVANT #1001 (bypass present) : 1 failed, 8 passed
        sur `main` apres #1001                 : 9 failed
        avec cette fixture                     : 1 failed, 8 passed

    Sur le repertoire entier : 59 -> 51 echecs, 39 -> 47 passes.

    CE QUI RESTE ROUGE N'EST PAS DE CE FAIT. Les echecs residuels des fichiers
    `test_dash_*` sont ANTERIEURS : `test_dash_02` + `test_dash_04` donnent
    9 failed / 2 passed a l'IDENTIQUE avant #1001 et avec cette fixture.

    POURQUOI UNE FIXTURE AUTOUSE PLUTOT QUE 150 SUBSTITUTIONS. Le jeton se
    depose en une ligne, avant tout script de la page ; corriger fichier par
    fichier laisserait le prochain test ecrit avec `page` retomber dans le meme
    trou, en silence.

    POURQUOI UN OPT-OUT. `test_dash_01_login.py` prend `page` nu DELIBEREMENT :
    il eprouve l'ecran de login (`#loginToken`). Lui injecter un jeton ferait
    afficher le shell d'emblee et le test n'eprouverait plus rien. Il porte donc
    le marqueur `sans_jeton`.

    RESOLUTION PARESSEUSE de `e2e_server`, comme `_reset_rate_limiter` juste en
    dessous : en parametre direct, cet autouse demarrerait un serveur REST pour
    tout module qui n'en veut pas.
    """
    if request.node.get_closest_marker("sans_jeton"):
        return
    if "page" not in request.fixturenames or "e2e_server" not in request.fixturenames:
        return
    page = request.getfixturevalue("page")
    jeton = request.getfixturevalue("e2e_server")["token"]
    page.add_init_script(
        "try { sessionStorage.setItem('cinesort.dashboard.token', " + json.dumps(jeton) + "); } catch (e) {}"
    )
    page.add_init_script(_JS_JOURNAL_FETCH)


@pytest.fixture(autouse=True)
def _reset_rate_limiter(request):
    """Reset le rate limiter entre chaque test.

    R2 (revue round 2) : resolution PARESSEUSE de e2e_server — ce conftest est
    charge en plugin GLOBAL via pytest_plugins (nom dotted) par les tests
    runtime racine ; en parametre direct, l'autouse forcait un serveur REST
    module-scope pour ~100 modules unitaires etrangers dans un run groupe.
    Seuls les tests dont la fermeture demande deja e2e_server le declenchent.
    """
    if "e2e_server" not in request.fixturenames:
        return
    server = request.getfixturevalue("e2e_server").get("_server")
    if server and hasattr(server, "_rate_limiter"):
        with server._rate_limiter._lock:
            server._rate_limiter._failures.clear()


# ---------------------------------------------------------------------------
# Screenshot automatique en cas d'echec (+ Allure)
# ---------------------------------------------------------------------------

_SCREENSHOTS_DIR = Path(__file__).resolve().parent / "screenshots"
_SCREENSHOTS_DIR.mkdir(exist_ok=True)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Capture un screenshot si le test echoue."""
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        pg = item.funcargs.get("dashboard_page") or item.funcargs.get("authenticated_page") or item.funcargs.get("page")
        if pg:
            name = item.name.replace("/", "_").replace("::", "_")
            path = _SCREENSHOTS_DIR / f"FAIL_{name}.png"
            try:
                png = pg.screenshot(path=str(path))
                if allure and png:
                    allure.attach(png, name=f"FAIL_{name}", attachment_type=allure.attachment_type.PNG)
            except Exception:
                pass
