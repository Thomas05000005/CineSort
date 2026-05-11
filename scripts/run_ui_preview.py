from __future__ import annotations

import argparse
import http.server
import os
import socketserver
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

DEV_MODE_ENV_VAR = "DEV_MODE"
TRUTHY_VALUES = {"1", "true", "yes", "on"}


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def build_url(host: str, port: int, scenario: str, view: str) -> str:
    query = urlencode(
        {
            "preview": "1",
            "scenario": scenario,
            "view": view,
        }
    )
    return f"http://{host}:{port}/web/index_preview.html?{query}"


def is_dev_mode(flag: bool = False, env: dict[str, str] | None = None) -> bool:
    if flag:
        return True
    environ = env if env is not None else os.environ
    return str(environ.get(DEV_MODE_ENV_VAR, "")).strip().lower() in TRUTHY_VALUES


def ensure_dev_mode(
    flag: bool = False, tool_name: str = "preview web local", env: dict[str, str] | None = None
) -> None:
    if is_dev_mode(flag, env):
        return
    raise SystemExit(f"{tool_name} est reserve au mode dev.\nRelancez avec --dev ou {DEV_MODE_ENV_VAR}=1.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the CineSort web UI preview locally.")
    parser.add_argument(
        "--dev", action="store_true", help=f"Authorize dev-only preview mode. Alternative: {DEV_MODE_ENV_VAR}=1"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1")
    parser.add_argument("--port", default=8765, type=int, help="Bind port. Default: 8765")
    parser.add_argument("--scenario", default="run_recent_safe", help="Preview scenario id. Default: run_recent_safe")
    parser.add_argument("--view", default="home", help="Initial preview view. Default: home")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the default browser.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_dev_mode(args.dev)
    root = Path(__file__).resolve().parents[1]
    url = build_url(args.host, args.port, args.scenario, args.view)
    handler = lambda *handler_args, **handler_kwargs: NoCacheHandler(
        *handler_args,
        directory=str(root),
        **handler_kwargs,
    )

    socketserver.TCPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as server:
        print("CineSort preview server running")
        print(f"Root: {root}")
        print(f"URL : {url}")
        print("Press Ctrl+C to stop.")
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping preview server.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
