from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

import live_env


class PywebviewNativeLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.capability = live_env.require_pywebview_live()
        cls.repo_root = Path(__file__).resolve().parents[2]

    def test_stable_ui_bootstraps_in_real_pywebview_with_js_bridge(self) -> None:
        script = textwrap.dedent(
            """
            import json
            from pathlib import Path

            import app
            import webview
            from cinesort.ui.api.cinesort_api import CineSortApi

            payload = {
                "loaded": False,
                "ready": False,
                "bridge": {},
                "error": None,
                "ui_variant": "stable",
            }

            index_rel, title = app.resolve_ui_entrypoint("stable")
            url = Path(app.resource_path(index_rel)).resolve().as_uri()
            window = webview.create_window(
                title,
                url=url,
                js_api=CineSortApi(),
                width=1250,
                height=820,
                min_size=(1000, 700),
                hidden=True,
            )

            def runner():
                try:
                    if not window.events.loaded.wait(20):
                        payload["error"] = "loaded timeout"
                        return
                    payload["loaded"] = True
                    if hasattr(window.events, "_pywebviewready") and window.events._pywebviewready.wait(20):
                        payload["ready"] = True
                    payload["bridge"] = {
                        "pywebview": window.evaluate_js("typeof window.pywebview"),
                        "api_start_plan": window.evaluate_js(
                            "typeof window.pywebview !== 'undefined' && window.pywebview.api ? typeof window.pywebview.api.start_plan : 'missing'"
                        ),
                        "document_title": window.evaluate_js("document.title"),
                    }
                except Exception as exc:
                    payload["error"] = repr(exc)
                finally:
                    try:
                        window.destroy()
                    except Exception as exc:
                        if payload["error"] is None:
                            payload["error"] = f"destroy error: {exc!r}"

            webview.start(runner, debug=False)
            print(json.dumps(payload, ensure_ascii=False))
            if payload["error"] is not None:
                raise SystemExit(1)
            """
        ).strip()

        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60.0,
        )
        stdout_lines = [line.strip() for line in str(completed.stdout or "").splitlines() if line.strip()]
        payload = json.loads(stdout_lines[-1]) if stdout_lines else {}

        self.assertEqual(completed.returncode, 0, f"stdout={completed.stdout}\nstderr={completed.stderr}")
        self.assertEqual(payload.get("ui_variant"), "stable", payload)
        self.assertTrue(payload.get("loaded"), payload)
        self.assertTrue(payload.get("ready"), payload)
        bridge = payload.get("bridge", {})
        self.assertEqual(bridge.get("pywebview"), "object", payload)
        self.assertEqual(bridge.get("api_start_plan"), "function", payload)
        self.assertEqual(bridge.get("document_title"), "CineSort", payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
