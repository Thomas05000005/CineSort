"""Fixtures pytest pour les tests E2E du dashboard CineSort.

Serveur REST auto-contenu, browser Playwright, authentification.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Dict, Generator

import pytest

import sys
from pathlib import Path as _Path

# Ajouter le dossier e2e au path pour les imports locaux (pas de __init__.py pour eviter unittest discover)
_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

from create_test_data import (  # noqa: E402
    _TOKEN,
    build_plan_rows,
    get_settings_dict,
    populate_database,
    write_plan_file,
)
import contextlib
import json as _json
from tests._helpers import find_free_port as _find_free_port


def _wait_server_ready(port: int, timeout_s: float = 5.0) -> None:
    """Polling GET /api/health jusqu'a ce que le serveur reponde (max timeout_s)."""
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
    raise TimeoutError(f"Le serveur E2E n'a pas demarre en {timeout_s}s sur le port {port}")


@pytest.fixture(scope="session")
def e2e_server() -> Generator[Dict[str, Any], None, None]:
    """Demarre un serveur REST CineSort avec 15 films mock.

    Yield un dict : {url, token, port, root, state_dir, run_id, rows, _api,
    _baseline_settings}.

    Note (audit C12 P0 / B6) : la fixture reste scope="session" pour eviter
    le cout de redemarrage du serveur HTTP (~ tmpdir + DB SQLite + 15 films
    + RestApiServer). L'isolation entre tests est assuree par la fixture
    autouse `e2e_clean_state` (scope="function") qui reset l'etat mutable.
    """
    import cinesort.ui.api.cinesort_api as backend
    from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir
    from cinesort.infra.rest_server import RestApiServer

    # Active le mode E2E AVANT toute initialisation API : ainsi l'endpoint
    # /api/test_reset est utilisable depuis la fixture clean state.
    os.environ.setdefault("CINESORT_E2E", "1")

    tmp = tempfile.mkdtemp(prefix="cinesort_e2e_")
    root = Path(tmp) / "root"
    state_dir = Path(tmp) / "state"
    root.mkdir()
    state_dir.mkdir()

    # API + settings
    api = backend.CineSortApi()
    api.settings.save_settings(get_settings_dict(root, state_dir))

    # Snapshot settings de reference pour rollback entre tests
    baseline_settings = _json.loads(_json.dumps(api.settings.get_settings()))

    # Base de donnees
    db_path = db_path_for_state_dir(state_dir)
    store = SQLiteStore(db_path)
    store.initialize()

    # Donnees mock
    rows = build_plan_rows()
    info = populate_database(store, root, state_dir)
    write_plan_file(state_dir, info["run_id"], rows)
    write_plan_file(state_dir, info["old_run_id"], rows[:10])

    # Serveur
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
        "_api": api,
        "_baseline_settings": baseline_settings,
    }

    server.stop()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def browser_context_args() -> Dict[str, Any]:
    """Override pytest-playwright : locale FR, timezone Paris."""
    return {
        "locale": "fr-FR",
        "timezone_id": "Europe/Paris",
        "ignore_https_errors": True,
    }


@pytest.fixture(scope="function")
def authenticated_page(page, e2e_server: Dict[str, Any]):
    """Page Playwright deja connectee au dashboard."""
    url = e2e_server["dashboard_url"]
    token = e2e_server["token"]
    page.goto(url)
    page.wait_for_selector("#loginToken", timeout=5000)
    page.fill("#loginToken", token)
    page.click("#loginBtn")
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)
    return page


@pytest.fixture(autouse=True)
def e2e_clean_state(e2e_server):
    """Reset l'etat mutable du serveur entre chaque test (audit C12 P0 / B6).

    Garantit l'isolation entre tests E2E meme si le serveur reste scope=session :
    - rate limiter (failures) : reset (pour eviter blocages successifs)
    - notifications store : clear via store.clear() direct
    - smart_playlists (settings.json) : rollback vers le snapshot baseline
    - runs en memoire : test_reset() endpoint (clear self._runs)

    Cette fixture rend les tests insensibles a l'ordre d'execution et
    permet la parallelisation (pytest-xdist) sans collisions inter-tests.
    """
    server = e2e_server.get("_server")
    api = e2e_server.get("_api")
    baseline = e2e_server.get("_baseline_settings") or {}

    # 1) Rate limiter : evite blocages cumules entre tests
    if server and hasattr(server, "_rate_limiter"):
        with contextlib.suppress(AttributeError, TypeError):
            with server._rate_limiter._lock:
                server._rate_limiter._failures.clear()

    # 2) Notifications : vide le store in-memory
    if api is not None:
        with contextlib.suppress(Exception):
            from cinesort.ui.api import notifications_support

            store = notifications_support._get_or_create_store(api)
            store.clear()

    # 3) Settings : rollback (efface smart_playlists ajoutees par les tests)
    if api is not None and baseline:
        with contextlib.suppress(Exception):
            api.settings.save_settings(_json.loads(_json.dumps(baseline)))

    # 4) Runs en memoire : test_reset endpoint officiel
    if api is not None and hasattr(api, "test_reset"):
        with contextlib.suppress(Exception):
            api.test_reset()

    yield


@pytest.fixture(scope="function")
def console_errors(page) -> list:
    """Collecte les erreurs console JS pendant le test."""
    errors: list = []

    def _on_console(msg):
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", _on_console)
    return errors
