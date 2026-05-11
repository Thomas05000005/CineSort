from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Iterable

from run_ui_preview import NoCacheHandler, build_url, ensure_dev_mode

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - runtime guidance only
    sync_playwright = None


DEFAULT_VIEWS = ["home", "validation", "execution", "quality", "history", "settings"]
CRITICAL_VIEWS = ["home", "validation", "execution", "quality", "history", "settings"]
RECOMMENDED_SCENARIOS = {
    "home": "run_recent_safe",
    "validation": "validation_loaded",
    "execution": "apply_result",
    "quality": "quality_anomalies",
    "history": "logs_artifacts",
    "settings": "settings_complete",
}
VIEW_LABELS = {
    "home": "Accueil",
    "validation": "Validation",
    "execution": "Execution",
    "quality": "Qualite",
    "history": "Historique",
    "settings": "Reglages",
}
CAPTURE_HIDE_PREVIEW_CSS = """
body.previewMode { padding-top: 0 !important; }
#previewToolbar { display: none !important; }
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture CineSort preview views.")
    parser.add_argument(
        "--dev", action="store_true", help="Authorize dev-only preview tooling. Alternative: DEV_MODE=1"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host for the local preview server.")
    parser.add_argument("--port", default=0, type=int, help="Bind port. Use 0 for an ephemeral port.")
    parser.add_argument("--scenario", default="run_recent_safe", help="Scenario id for single-scenario capture.")
    parser.add_argument("--recommended", action="store_true", help="Use the built-in recommended scenario per view.")
    parser.add_argument("--views", default=",".join(DEFAULT_VIEWS), help="Comma-separated views to capture.")
    parser.add_argument("--width", default=1600, type=int, help="Viewport width.")
    parser.add_argument("--height", default=1100, type=int, help="Viewport height.")
    parser.add_argument("--output-dir", default="", help="Output directory. Default: build/ui_preview_captures/<name>")
    return parser.parse_args()


def normalize_views(raw: str) -> list[str]:
    values = [item.strip().lower() for item in str(raw or "").split(",")]
    views = [item for item in values if item in VIEW_LABELS]
    return views or list(DEFAULT_VIEWS)


def ensure_playwright_available() -> None:
    if sync_playwright is not None:
        return
    raise SystemExit(
        "Playwright Python is not installed. Run:\n"
        "  python -m pip install -r requirements-preview.txt\n"
        "  python -m playwright install chromium"
    )


class PreviewServer:
    def __init__(self, root: Path, host: str, port: int):
        self.root = root
        self.host = host
        self.port = port
        self.server = None
        self.thread = None

    def __enter__(self) -> "PreviewServer":
        import http.server

        class QuietNoCacheHandler(NoCacheHandler):
            def log_message(self, format: str, *args) -> None:
                return

        handler = lambda *args, **kwargs: QuietNoCacheHandler(*args, directory=str(self.root), **kwargs)
        self.server = http.server.ThreadingHTTPServer((self.host, self.port), handler)
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2.0)


def scenario_for_view(args: argparse.Namespace, view: str) -> str:
    return RECOMMENDED_SCENARIOS[view] if args.recommended else args.scenario


def default_output_dir(root: Path, args: argparse.Namespace) -> Path:
    name = "recommended" if args.recommended else str(args.scenario or "run_recent_safe")
    return root / "build" / "ui_preview_captures" / name


def capture_one(page, url: str, view: str, target: Path) -> None:
    page.goto(url, wait_until="networkidle")
    page.locator("#previewToolbar").wait_for(timeout=15000)
    page.wait_for_function(
        """
        (expectedView) => {
          const bodyView = document.body && document.body.dataset ? document.body.dataset.view : "";
          const target = document.getElementById(`view-${expectedView}`);
          return bodyView === expectedView && !!target && target.classList.contains("active");
        }
        """,
        arg=view,
        timeout=15000,
    )
    page.wait_for_timeout(450)
    page.add_style_tag(content=CAPTURE_HIDE_PREVIEW_CSS)
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(target), full_page=True, animations="disabled")


def write_manifest(target_dir: Path, manifest: list[dict[str, str]]) -> Path:
    path = target_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def run_capture(args: argparse.Namespace) -> list[Path]:
    ensure_dev_mode(bool(getattr(args, "dev", False)), tool_name="les captures preview")
    ensure_playwright_available()
    root = Path(__file__).resolve().parents[1]
    views = normalize_views(args.views)
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir(root, args)
    output_dir.mkdir(parents=True, exist_ok=True)
    captures: list[Path] = []
    manifest: list[dict[str, str]] = []

    with PreviewServer(root, args.host, args.port) as server, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            color_scheme="dark",
            device_scale_factor=1,
            locale="fr-FR",
            timezone_id="Europe/Paris",
            reduced_motion="reduce",
        )
        for index, view in enumerate(views, start=1):
            scenario = scenario_for_view(args, view)
            page = context.new_page()
            url = build_url(args.host, server.port, scenario, view)
            filename = f"{index:02d}-{view}.png"
            target = output_dir / filename
            capture_one(page, url, view, target)
            page.close()
            captures.append(target)
            manifest.append(
                {
                    "view": view,
                    "label": VIEW_LABELS[view],
                    "scenario": scenario,
                    "file": filename,
                    "request_path": f"/web/index_preview.html?preview=1&scenario={scenario}&view={view}",
                }
            )
        context.close()
        browser.close()

    write_manifest(output_dir, manifest)
    return captures


def format_paths(paths: Iterable[Path]) -> str:
    return "\n".join(str(path) for path in paths)


def main() -> int:
    args = parse_args()
    captures = run_capture(args)
    print("CineSort preview captures generated")
    print(format_paths(captures))
    print(
        str(
            (
                Path(args.output_dir)
                if args.output_dir
                else default_output_dir(Path(__file__).resolve().parents[1], args)
            )
            / "manifest.json"
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
