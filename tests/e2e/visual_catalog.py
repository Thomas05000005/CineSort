#!/usr/bin/env python3
"""Capture visuelle complete du dashboard CineSort — catalogue de screenshots.

Genere ~60-80 screenshots couvrant chaque vue, modale, etat et viewport.

Usage :
    python tests/e2e/visual_catalog.py                  # headless
    python tests/e2e/visual_catalog.py --headed          # navigateur visible
    python tests/e2e/visual_catalog.py --output shots/   # dossier de sortie custom
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

# Ajouter le dossier e2e et la racine projet au path
_e2e_dir = str(Path(__file__).resolve().parent)
_project_root = str(Path(__file__).resolve().parents[2])
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from create_test_data import (
    _TOKEN,
    build_plan_rows,
    get_settings_dict,
    populate_database,
    write_plan_file,
)
import contextlib

VIEWPORTS = {
    "desktop": {"width": 1920, "height": 1080},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 375, "height": 812},
}

VIEWS = ["status", "library", "runs", "review", "jellyfin", "logs"]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_server(port: int, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            c = HTTPConnection("127.0.0.1", port, timeout=1)
            c.request("GET", "/api/health")
            if c.getresponse().status == 200:
                return
        except (ConnectionRefusedError, OSError):
            pass
        finally:
            with contextlib.suppress(Exception):
                c.close()
        time.sleep(0.1)
    raise TimeoutError(f"Serveur non pret sur le port {port}")


def _start_server():
    """Demarre le serveur REST avec donnees mock. Retourne (server, info)."""
    import cinesort.ui.api.cinesort_api as backend
    from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir
    from cinesort.infra.rest_server import RestApiServer

    tmp = tempfile.mkdtemp(prefix="cinesort_catalog_")
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
    _wait_server(port)

    return server, {
        "url": f"http://127.0.0.1:{port}",
        "dashboard_url": f"http://127.0.0.1:{port}/dashboard/",
        "token": _TOKEN,
        "port": port,
        "tmp": tmp,
        "rows": rows,
    }


def _login(page, info: dict) -> None:
    """Connexion au dashboard."""
    page.goto(info["dashboard_url"])
    page.wait_for_selector("#loginToken", timeout=5000)
    page.fill("#loginToken", info["token"])
    page.click("#loginBtn")
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)


def _scroll_and_capture(page, path: Path) -> None:
    """Scroll complet puis capture full-page."""
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(300)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(200)
    page.screenshot(path=str(path), full_page=True)


def _navigate(page, route: str, wait_ms: int = 2000) -> None:
    """Navigue vers une vue et attend le chargement."""
    page.evaluate(f"window.location.hash = '#/{route}'")
    page.wait_for_timeout(wait_ms)


def _close_modal(page) -> None:
    """Ferme la modale si ouverte."""
    btn = page.query_selector(".modal-close-btn, [data-modal-close]")
    if btn:
        btn.click()
        page.wait_for_timeout(300)


def capture_all(page, info: dict, out_dir: Path) -> int:
    """Capture toutes les vues et etats. Retourne le nombre de screenshots."""
    count = 0

    for vp_name, vp_size in VIEWPORTS.items():
        page.set_viewport_size(vp_size)
        print(f"  [{vp_name}] {vp_size['width']}x{vp_size['height']}")

        # --- Login (avant connexion) ---
        page.goto(info["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=5000)
        _scroll_and_capture(page, out_dir / f"{vp_name}_login.png")
        count += 1

        # Token invalide
        page.fill("#loginToken", "bad-token")
        page.click("#loginBtn")
        page.wait_for_timeout(1500)
        _scroll_and_capture(page, out_dir / f"{vp_name}_login_error.png")
        count += 1

        # --- Connexion ---
        _login(page, info)

        # --- Vues principales ---
        for view in VIEWS:
            wait = 4000 if view == "review" else 2000
            _navigate(page, view, wait)
            _scroll_and_capture(page, out_dir / f"{vp_name}_{view}.png")
            count += 1

        # --- Modales library ---
        _navigate(page, "library", 2000)

        # Films specifiques par index dans la table
        modal_targets = [
            (0, "avengers_endgame"),
            (3, "blade_runner_imax"),
            (7, "the_room_not_a_movie"),
            (9, "corrupted"),
            (13, "oppenheimer_mkv_imax"),
        ]
        for row_idx, label in modal_targets:
            try:
                _navigate(page, "library", 2000)
                rows_els = page.query_selector_all("#libTable tbody tr")
                if row_idx < len(rows_els):
                    rows_els[row_idx].click()
                    page.wait_for_timeout(800)
                    _scroll_and_capture(page, out_dir / f"{vp_name}_library_modal_{label}.png")
                    count += 1
                    _close_modal(page)
            except Exception:
                pass  # skip cette modale si erreur

        # --- Filtre library Premium ---
        try:
            _navigate(page, "library", 2000)
            btn_premium = page.query_selector('.btn-filter[data-filter-key="premium"]')
            if btn_premium:
                btn_premium.click()
                page.wait_for_timeout(500)
                _scroll_and_capture(page, out_dir / f"{vp_name}_library_filter_premium.png")
                count += 1
                btn_premium.click()
                page.wait_for_timeout(300)
        except Exception:
            pass

        # Recherche "Dune"
        try:
            _navigate(page, "library", 2000)
            search = page.query_selector("#librarySearch")
            if search:
                page.fill("#librarySearch", "Dune")
                page.wait_for_timeout(500)
                _scroll_and_capture(page, out_dir / f"{vp_name}_library_search_dune.png")
                count += 1
                page.fill("#librarySearch", "")
                page.wait_for_timeout(300)
        except Exception:
            pass

        # --- Review avec decisions ---
        try:
            _navigate(page, "review", 4000)
            approve_btns = page.query_selector_all('.btn-review[data-action="approve"]')
            for i in range(min(3, len(approve_btns))):
                approve_btns[i].click()
                page.wait_for_timeout(200)
            reject_btns = page.query_selector_all('.btn-review[data-action="reject"]')
            for i in range(min(2, len(reject_btns))):
                if i + 3 < len(reject_btns):
                    reject_btns[i + 3].click()
                    page.wait_for_timeout(200)
            page.wait_for_timeout(300)
            _scroll_and_capture(page, out_dir / f"{vp_name}_review_decisions.png")
            count += 1
        except Exception:
            pass

        # Nettoyage storage pour le viewport suivant
        page.evaluate("sessionStorage.clear(); localStorage.clear()")

    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Catalogue visuel du dashboard CineSort")
    parser.add_argument("--headed", action="store_true", help="Navigateur visible")
    parser.add_argument("--output", default="tests/e2e/screenshots/catalog", help="Dossier de sortie")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[catalog] Demarrage du serveur...")
    server, info = _start_server()

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed)
            context = browser.new_context(locale="fr-FR", timezone_id="Europe/Paris")
            page = context.new_page()

            print("[catalog] Capture en cours...")
            count = capture_all(page, info, out_dir)

            browser.close()

        print(f"[catalog] {count} screenshots generes dans {out_dir}/")
        return 0
    except Exception as exc:
        print(f"[catalog] Erreur : {exc}")
        return 1
    finally:
        server.stop()
        shutil.rmtree(info["tmp"], ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
