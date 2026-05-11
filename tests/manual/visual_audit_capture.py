"""Visual audit capture script — Dashboard distant SPA.

Lance le serveur REST mocke (reutilise la logique de tests/e2e/conftest.py),
puis prend des captures full-page du dashboard a 4 viewports desktop +
captures d'etats speciaux (modales, hover, focus, scroll, vide).

Usage :
    .venv313/Scripts/python.exe tests/manual/visual_audit_capture.py [--out DIR]

Sortie : tests/manual/screenshots/audit_YYYYMMDD/dashboard/...
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import socket
import sys
import tempfile
import time
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Dict, List, Tuple

# --- Path setup pour reutiliser tests/e2e/create_test_data ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Le projet root doit etre dans sys.path pour importer cinesort
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "tests" / "e2e"))

import cinesort.ui.api.cinesort_api as backend  # noqa: E402
from create_test_data import (  # noqa: E402
    _TOKEN,
    build_plan_rows,
    get_settings_dict,
    populate_database,
    write_plan_file,
)
from playwright.sync_api import sync_playwright  # noqa: E402
from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir  # noqa: E402
from cinesort.infra.rest_server import RestApiServer  # noqa: E402


VIEWPORTS = [
    {"name": "1024x768", "width": 1024, "height": 768},
    {"name": "1366x768", "width": 1366, "height": 768},
    {"name": "1440x900", "width": 1440, "height": 900},
    {"name": "1920x1080", "width": 1920, "height": 1080},
]

VIEWS = [
    "status",
    "library",
    "runs",
    "review",
    "jellyfin",
    "plex",
    "radarr",
    "quality",
    "settings",
]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_server_ready(port: int, timeout_s: float = 10.0) -> None:
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
        time.sleep(0.2)
    raise TimeoutError(f"Le serveur n'a pas demarre en {timeout_s}s sur le port {port}")


def _start_server() -> Tuple[Dict[str, Any], Any]:
    """Demarre serveur REST mocke. Retourne (info_dict, cleanup_fn)."""
    tmp = tempfile.mkdtemp(prefix="cinesort_visualaudit_")
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

    info_dict = {
        "url": f"http://127.0.0.1:{port}",
        "dashboard_url": f"http://127.0.0.1:{port}/dashboard/",
        "token": _TOKEN,
        "port": port,
    }

    def cleanup():
        server.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    return info_dict, cleanup


def _login(page, info: Dict[str, Any], viewport: Dict[str, int]) -> None:
    page.set_viewport_size({"width": viewport["width"], "height": viewport["height"]})
    page.goto(info["dashboard_url"])
    page.wait_for_selector("#loginToken", timeout=10000)
    page.fill("#loginToken", info["token"])
    page.click("#loginBtn")
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)


def _navigate(page, view: str) -> None:
    page.click(f'[data-testid="nav-{view}"]')
    page.wait_for_timeout(1500)


def _capture(page, out_dir: Path, name: str, full_page: bool = True) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page)
    return path


def capture_view_x_viewport(page, info, view: str, viewport: Dict[str, Any], out_root: Path) -> List[Path]:
    """Capture une vue a un viewport (login, navigate, capture full + viewport)."""
    out_dir = out_root / "dashboard" / viewport["name"]
    captures = []
    try:
        _login(page, info, viewport)
        if view != "status":
            _navigate(page, view)
        else:
            page.wait_for_timeout(1500)
        # Login screenshot first if status
        captures.append(_capture(page, out_dir, f"{view}_full", full_page=True))
        captures.append(_capture(page, out_dir, f"{view}_viewport", full_page=False))
    except Exception as exc:
        print(f"  [erreur] {view} @ {viewport['name']} : {exc}", flush=True)
    return captures


def capture_special_states(page, info, out_root: Path) -> List[Path]:
    """Capture des etats speciaux a 1366x768 (le plus standard)."""
    viewport = {"name": "1366x768", "width": 1366, "height": 768}
    out_dir = out_root / "dashboard" / "states"
    captures: List[Path] = []

    # 1. Login screen vide
    page.set_viewport_size({"width": viewport["width"], "height": viewport["height"]})
    page.goto(info["dashboard_url"])
    page.wait_for_selector("#loginToken", timeout=10000)
    page.wait_for_timeout(800)
    captures.append(_capture(page, out_dir, "login_empty", full_page=False))

    # 2. Login avec mauvais token
    page.fill("#loginToken", "wrong_token_123")
    page.click("#loginBtn")
    page.wait_for_timeout(1500)
    captures.append(_capture(page, out_dir, "login_error", full_page=False))

    # 3. Login OK puis tester etats vues
    page.fill("#loginToken", info["token"])
    page.click("#loginBtn")
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)
    page.wait_for_timeout(1500)

    # 4. Hover sur boutons sidebar
    try:
        page.hover('[data-testid="nav-library"]')
        page.wait_for_timeout(400)
        captures.append(_capture(page, out_dir, "hover_sidebar_library", full_page=False))
    except Exception:
        pass

    # 5. Focus via Tab clavier
    try:
        page.evaluate("document.body.focus()")
        for _ in range(3):
            page.keyboard.press("Tab")
            page.wait_for_timeout(150)
        captures.append(_capture(page, out_dir, "focus_keyboard_tab3", full_page=False))
    except Exception:
        pass

    # 6. Library remplie + scroll bas
    try:
        _navigate(page, "library")
        page.wait_for_timeout(1500)
        captures.append(_capture(page, out_dir, "library_top", full_page=False))
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)
        captures.append(_capture(page, out_dir, "library_bottom", full_page=False))
    except Exception:
        pass

    # 7. Settings full (souvent long)
    try:
        _navigate(page, "settings")
        page.wait_for_timeout(2000)
        captures.append(_capture(page, out_dir, "settings_full_page", full_page=True))
    except Exception:
        pass

    return captures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=str, default=None, help="Dossier de sortie (defaut: tests/manual/screenshots/audit_YYYYMMDD)")
    parser.add_argument("--quick", action="store_true", help="Mode rapide : 1 viewport seulement (1366)")
    args = parser.parse_args()

    if args.out:
        out_root = Path(args.out)
    else:
        date_tag = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_root = _PROJECT_ROOT / "tests" / "manual" / "screenshots" / f"audit_{date_tag}"

    print(f"=== Visual Audit Capture (Dashboard) ===", flush=True)
    print(f"Sortie : {out_root}", flush=True)

    print("Demarrage serveur REST mocke...", flush=True)
    info, cleanup = _start_server()
    print(f"  Serveur : {info['dashboard_url']}", flush=True)

    viewports = VIEWPORTS[1:2] if args.quick else VIEWPORTS
    total = len(viewports) * len(VIEWS)
    done = 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for viewport in viewports:
                    print(f"\n--- Viewport {viewport['name']} ({viewport['width']}x{viewport['height']}) ---", flush=True)
                    context = browser.new_context(
                        viewport={"width": viewport["width"], "height": viewport["height"]},
                        locale="fr-FR",
                    )
                    page = context.new_page()
                    for view in VIEWS:
                        done += 1
                        print(f"  [{done}/{total}] {view} @ {viewport['name']}", flush=True)
                        capture_view_x_viewport(page, info, view, viewport, out_root)
                    context.close()

                if not args.quick:
                    print("\n--- Etats speciaux (1366x768) ---", flush=True)
                    context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="fr-FR")
                    page = context.new_page()
                    capture_special_states(page, info, out_root)
                    context.close()
            finally:
                browser.close()
    finally:
        cleanup()

    print(f"\n=== Termine ===", flush=True)
    print(f"Captures dans : {out_root}", flush=True)
    n_files = sum(1 for _ in out_root.rglob("*.png"))
    print(f"Total fichiers : {n_files}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
