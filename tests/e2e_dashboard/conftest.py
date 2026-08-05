"""Fixtures E2E dashboard workflow — reutilise l'infrastructure tests/e2e.

Ce conftest charge les fixtures du dashboard E2E existant (serveur REST,
authenticated_page, rate limiter reset) via pytest_plugins.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Generator

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
import shutil
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
    page.goto(url)
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
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=_SHELL_TIMEOUT_LENT_MS)
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
