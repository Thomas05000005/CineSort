#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ITER10 v2 - mesure ciblee steps Traitement labels."""

from __future__ import annotations
import json, os, socket, subprocess, sys, time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CAPTURE_DIR = PROJECT_ROOT / "docs/internal/observe/2026-06-08_ITER10_LISIBILITE"
OUT_FILE = CAPTURE_DIR / "iter10_gate_lisibilite_v2_steps.json"
CDP_PORT = 9225

# Les libelles d'etapes ont UNE source : le gate v1. Les reecrire ici en faisait
# un troisieme exemplaire, libre de diverger sans que rien ne rougisse.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _iter10_gate_lisibilite import STEP_LABEL_SELECTOR, STEP_LABELS


def _wait_port(host, port, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=1)
            s.close()
            return True
        except OSError:
            time.sleep(1)
    return False


isolated_state = CAPTURE_DIR / "_iter10_state_v2"
isolated_state.mkdir(parents=True, exist_ok=True)
(isolated_state / "CineSort").mkdir(exist_ok=True)
seed = {
    "root": str(PROJECT_ROOT / "test_library"),
    "roots": [str(PROJECT_ROOT / "test_library")],
    "tmdb_enabled": False,
    "auto_check_updates": False,
    "rest_api_port": 8652,
}
(isolated_state / "CineSort" / "settings.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")

env = os.environ.copy()
env["CINESORT_E2E"] = "1"
env["CINESORT_CDP_PORT"] = str(CDP_PORT)
env["LOCALAPPDATA"] = str(isolated_state)
env["CINESORT_OBSERVE_FORCE_DEV"] = "1"

proc = subprocess.Popen(
    [sys.executable, str(PROJECT_ROOT / "app.py"), "--dev"],
    cwd=str(PROJECT_ROOT),
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)

out = {"ts": datetime.now().isoformat(timespec="seconds")}
try:
    if not _wait_port("127.0.0.1", CDP_PORT, timeout=90):
        out["error"] = f"CDP {CDP_PORT} unreachable"
    else:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            ctx = browser.contexts[0]
            page = None
            for p in ctx.pages:
                if "/dashboard" in (p.url or ""):
                    page = p
                    break
            if page is None:
                page = ctx.pages[0]
            try:
                page.wait_for_function(
                    "() => window.__APP_READY__ === true || document.readyState === 'complete'",
                    timeout=30000,
                )
            except Exception:
                pass
            # Naviguer vers traitement
            page.evaluate("() => { window.location.hash = '/traitement'; }")
            page.wait_for_timeout(4000)
            steps = page.evaluate(
                r"""(selector) => {
                    const labels = Array.from(document.querySelectorAll(selector));
                    return labels.map(l => ({
                        text: l.textContent || '',
                        hex: Array.from(l.textContent || '').map(c => c.codePointAt(0).toString(16)).join(',')
                    }));
                }""",
                STEP_LABEL_SELECTOR,
            )
            out["steps"] = steps
            expected = STEP_LABELS
            matches = []
            for i, exp in enumerate(expected):
                actual = steps[i]["text"] if i < len(steps) else ""
                matches.append(
                    {
                        "expected": exp,
                        "actual": actual,
                        "expected_hex": ",".join(c.encode("utf-8").hex() for c in exp),
                        "actual_hex": steps[i]["hex"] if i < len(steps) else "",
                        "ok": actual.strip() == exp,
                    }
                )
            out["matches"] = matches
            out["all_ok"] = all(m["ok"] for m in matches)
            browser.close()
finally:
    try:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:
        pass

OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
print(f"wrote {OUT_FILE}")
print(f"all_ok={out.get('all_ok')}")
