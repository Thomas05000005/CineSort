"""Visual audit capture script — UI pywebview principale (web/index.html).

Sert web/ via un serveur HTTP local, injecte un mock window.pywebview.api
riche, et capture chaque vue + chaque overlay v5 a plusieurs viewports.

Usage :
    .venv313/Scripts/python.exe tests/manual/visual_audit_pywebview.py [--out DIR]

Sortie : tests/manual/screenshots/audit_YYYYMMDD/pywebview/...
"""

from __future__ import annotations

import argparse
import datetime
import http.server
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

from playwright.sync_api import sync_playwright  # noqa: E402


VIEWPORTS = [
    {"name": "1366x768", "width": 1366, "height": 768},
    {"name": "1920x1080", "width": 1920, "height": 1080},
]

# Vues legacy accessibles via navigateTo("name", {legacy: true}) pour bypasser
# les redirections vers overlays v5
LEGACY_VIEWS = ["home", "library", "validation", "execution", "quality", "history", "settings", "jellyfin", "plex", "radarr"]

# Overlays v5 accessibles via navigateTo standard
V5_OVERLAYS = [
    ("processing", None),
    ("settings-v5/sources", None),
    ("quality-v5", None),
    ("integrations-v5", None),
    ("journal-v5", None),
    ("film/r1", None),  # FilmDetail overlay
]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass


def _start_http_server(web_dir: Path, port: int = 0) -> tuple[socketserver.TCPServer, int]:
    handler = lambda *a, **kw: _QuietHandler(*a, directory=str(web_dir), **kw)  # noqa: E731
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    actual_port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, actual_port


def _capture(page, out_dir: Path, name: str, full_page: bool = False) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=str, default=None)
    parser.add_argument("--quick", action="store_true", help="1 viewport seulement (1366)")
    args = parser.parse_args()

    web_dir = _PROJECT_ROOT / "web"
    if not (web_dir / "index.html").is_file():
        print(f"ERREUR : {web_dir / 'index.html'} introuvable", flush=True)
        return 1

    if args.out:
        out_root = Path(args.out)
    else:
        date_tag = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_root = _PROJECT_ROOT / "tests" / "manual" / "screenshots" / f"audit_pywebview_{date_tag}"

    print("=== Visual Audit Capture (UI pywebview principale) ===", flush=True)
    print(f"Sortie : {out_root}", flush=True)

    # Charger le mock JS
    mock_js_path = _PROJECT_ROOT / "tests" / "manual" / "pywebview_api_mock.js"
    mock_js = mock_js_path.read_text(encoding="utf-8")

    # Lancer le serveur HTTP
    print("Demarrage serveur HTTP local pour web/...", flush=True)
    httpd, port = _start_http_server(web_dir)
    base_url = f"http://127.0.0.1:{port}"
    print(f"  Serveur : {base_url}", flush=True)

    viewports = VIEWPORTS[0:1] if args.quick else VIEWPORTS
    n_captures = 0

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
                    # Injecter le mock AVANT chargement
                    page.add_init_script(mock_js)

                    # Charger l'app
                    page.goto(f"{base_url}/index.html")
                    page.wait_for_load_state("networkidle", timeout=15000)
                    page.wait_for_timeout(2000)  # boot app + premiers loads

                    # Capture initiale
                    out_dir = out_root / "pywebview" / viewport["name"]
                    capture_path = _capture(page, out_dir, "00_boot")
                    n_captures += 1
                    print(f"  [{n_captures}] 00_boot @ {viewport['name']}", flush=True)

                    # 1. Capture chaque vue legacy
                    for i, view in enumerate(LEGACY_VIEWS):
                        try:
                            # Le router accepte un 2e arg {legacy: true} pour acceder aux vues legacy
                            page.evaluate(f"window.navigateTo && window.navigateTo('{view}', {{legacy: true}})")
                            page.wait_for_timeout(1500)
                            n_captures += 1
                            _capture(page, out_dir, f"{i+1:02d}_legacy_{view}")
                            print(f"  [{n_captures}] legacy/{view}", flush=True)
                        except Exception as exc:
                            print(f"  [erreur] legacy/{view} : {exc}", flush=True)

                    # 2. Capture chaque overlay v5
                    for j, (overlay, _) in enumerate(V5_OVERLAYS):
                        try:
                            page.evaluate(f"window.navigateTo && window.navigateTo('{overlay}')")
                            page.wait_for_timeout(2000)
                            n_captures += 1
                            safe_name = overlay.replace("/", "_")
                            _capture(page, out_dir, f"{20+j:02d}_overlay_{safe_name}")
                            print(f"  [{n_captures}] overlay/{overlay}", flush=True)
                        except Exception as exc:
                            print(f"  [erreur] overlay/{overlay} : {exc}", flush=True)

                    # 3. Capture full-page de la home (souvent longue)
                    try:
                        page.evaluate("window.navigateTo && window.navigateTo('home', {legacy: true})")
                        page.wait_for_timeout(1500)
                        n_captures += 1
                        _capture(page, out_dir, "30_home_fullpage", full_page=True)
                    except Exception:
                        pass

                    # 4. Etat hover sur un bouton primaire (si trouvable)
                    try:
                        page.hover('button.btn--primary, button.v5-btn--primary', timeout=2000)
                        page.wait_for_timeout(400)
                        n_captures += 1
                        _capture(page, out_dir, "40_hover_primary_btn")
                    except Exception:
                        pass

                    # 5. Etat focus Tab
                    try:
                        page.evaluate("document.body.focus()")
                        for _ in range(3):
                            page.keyboard.press("Tab")
                            page.wait_for_timeout(200)
                        n_captures += 1
                        _capture(page, out_dir, "41_focus_tab3")
                    except Exception:
                        pass

                    context.close()
            finally:
                browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()

    print(f"\n=== Termine ===", flush=True)
    print(f"Captures : {n_captures} fichiers dans {out_root}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
