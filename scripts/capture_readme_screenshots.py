#!/usr/bin/env python3
"""V4-04 — Capture les screenshots du README via Playwright.

Demarre un serveur REST mock (donnees deterministes du module e2e) puis
capture les vues principales du dashboard. Reutilise le scaffolding de
tests/e2e/visual_catalog.py pour eviter de demander a l'utilisateur de
lancer l'app manuellement.

Usage :
    .venv313/Scripts/python.exe scripts/capture_readme_screenshots.py
    .venv313/Scripts/python.exe scripts/capture_readme_screenshots.py --headed

Genere :
    docs/screenshots/01_home.png       (Accueil/status)
    docs/screenshots/02_library.png    (Bibliotheque)
    docs/screenshots/03_quality.png    (Qualite — onglet library filtre Premium)
    docs/screenshots/04_validation.png (Review)
    docs/screenshots/05_settings.png   (Reglages)
    docs/screenshots/06_runs.png       (Runs/historique)
    docs/screenshots/theme_<name>.png  (4 captures themes)
"""

from __future__ import annotations

import argparse
import shutil
import socket
import sys
import tempfile
import time
from http.client import HTTPConnection
from pathlib import Path

# Reutilise le bootstrap mock du catalogue visuel E2E
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_E2E_DIR = _PROJECT_ROOT / "tests" / "e2e"
for _p in (_E2E_DIR, _PROJECT_ROOT):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from create_test_data import (  # noqa: E402
    _TOKEN,
    build_plan_rows,
    get_settings_dict,
    populate_database,
    write_plan_file,
)

OUTPUT_DIR = _PROJECT_ROOT / "docs" / "screenshots"
VIEWPORT = {"width": 1280, "height": 800}

# Vues principales : (route, filename, attente extra ms)
CAPTURES = [
    ("status", "01_home.png", 1500),
    ("library", "02_library.png", 2000),
    ("quality", "03_quality.png", 2000),
    ("review", "04_validation.png", 4000),
    ("settings", "05_settings.png", 1500),
    ("runs", "06_runs.png", 1500),
]

THEMES = ["studio", "cinema", "luxe", "neon"]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_server(port: int, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        c = None
        try:
            c = HTTPConnection("127.0.0.1", port, timeout=1)
            c.request("GET", "/api/health")
            if c.getresponse().status == 200:
                return
        except (ConnectionRefusedError, OSError):
            pass
        finally:
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass
        time.sleep(0.1)
    raise TimeoutError(f"Serveur non pret sur le port {port}")


def _start_server():
    """Demarre un serveur REST mock avec donnees deterministes."""
    import cinesort.ui.api.cinesort_api as backend
    from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir
    from cinesort.infra.rest_server import RestApiServer

    tmp = tempfile.mkdtemp(prefix="cinesort_readme_")
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
    _wait_server(port)

    return server, {
        "dashboard_url": f"http://127.0.0.1:{port}/dashboard/",
        "token": _TOKEN,
        "tmp": tmp,
    }


def _login(page, info: dict) -> None:
    page.goto(info["dashboard_url"])
    page.wait_for_selector("#loginToken", timeout=5000)
    page.fill("#loginToken", info["token"])
    page.click("#loginBtn")
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)


def _navigate(page, route: str, wait_ms: int) -> None:
    # Force le hash + dispatch un hashchange pour declencher le router meme si
    # on est deja sur cette route.
    page.evaluate(
        "(r) => {"
        " const t = '#/' + r;"
        " if (window.location.hash === t) {"
        "   window.dispatchEvent(new HashChangeEvent('hashchange'));"
        " } else {"
        "   window.location.hash = t;"
        " }"
        "}",
        route,
    )
    page.wait_for_timeout(wait_ms)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(150)


def _snap(page, output: Path, full_page: bool = False) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(output), full_page=full_page)
    print(f"  OK {output.relative_to(_PROJECT_ROOT)}")


def capture_main_views(page, info: dict) -> int:
    count = 0
    for route, filename, wait_ms in CAPTURES:
        _navigate(page, route, wait_ms)
        _snap(page, OUTPUT_DIR / filename)
        count += 1
    return count


def capture_themes(page) -> int:
    _navigate(page, "library", 2000)
    count = 0
    for theme in THEMES:
        page.evaluate(f"document.body.dataset.theme = '{theme}'")
        page.wait_for_timeout(500)
        _snap(page, OUTPUT_DIR / f"theme_{theme}.png")
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture screenshots README CineSort")
    parser.add_argument("--headed", action="store_true", help="Navigateur visible")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[readme-shots] Demarrage du serveur mock...")
    server, info = _start_server()

    try:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("ERR Playwright non installe. Run: pip install playwright && playwright install chromium")
            return 1

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed)
            ctx = browser.new_context(
                viewport=VIEWPORT,
                locale="fr-FR",
                timezone_id="Europe/Paris",
            )
            page = ctx.new_page()

            print("[readme-shots] Connexion au dashboard...")
            _login(page, info)

            print("[readme-shots] Capture vues principales...")
            n = capture_main_views(page, info)

            print("[readme-shots] Capture des 4 themes...")
            n += capture_themes(page)

            browser.close()

        print(f"[readme-shots] {n} screenshots generes dans {OUTPUT_DIR.relative_to(_PROJECT_ROOT)}/")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[readme-shots] ERREUR : {exc}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        server.stop()
        shutil.rmtree(info["tmp"], ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
