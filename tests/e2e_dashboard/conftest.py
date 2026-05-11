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
from create_test_data import (  # noqa: E402
    _TOKEN,
    build_plan_rows,
    get_settings_dict,
    populate_database,
    write_plan_file,
)

import shutil
import socket
import tempfile
import time
from http.client import HTTPConnection


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
            try:
                conn.close()
            except Exception:
                pass
        time.sleep(0.1)
    raise TimeoutError(f"Serveur non demarre en {timeout_s}s sur le port {port}")


@pytest.fixture(scope="session")
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
    api.save_settings(get_settings_dict(root, state_dir))

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


@pytest.fixture(scope="function")
def authenticated_page(page, e2e_server: Dict[str, Any]):
    """Page Playwright connectee au dashboard."""
    url = e2e_server["dashboard_url"]
    token = e2e_server["token"]
    page.goto(url)
    page.wait_for_selector("#loginToken", timeout=8000)
    page.fill("#loginToken", token)
    page.click("#loginBtn")
    # Attendre que le shell devienne visible (login reussi)
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=15000)
    return page


@pytest.fixture(scope="function")
def dashboard_page(authenticated_page):
    """Alias pour authenticated_page."""
    return authenticated_page


@pytest.fixture(autouse=True)
def _reset_rate_limiter(e2e_server):
    """Reset le rate limiter entre chaque test."""
    server = e2e_server.get("_server")
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
