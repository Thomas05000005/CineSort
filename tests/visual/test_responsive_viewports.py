"""V4-06 — Captures Playwright sur tous les viewports cibles + détection débordements.

Run:
  CINESORT_API_TOKEN=<token> python -m unittest tests.visual.test_responsive_viewports -v

Génère:
  audit/results/v4-06-screenshots/<viewport>/<view>.png
  audit/results/v4-06-overflow.md (si débordements détectés)
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

OUTPUT_DIR = Path("audit/results/v4-06-screenshots")
OVERFLOW_REPORT = Path("audit/results/v4-06-overflow.md")
DASHBOARD_URL = "http://127.0.0.1:8642/dashboard/"

VIEWPORTS = [
    ("mobile_320", 320, 568),  # iPhone SE 1ère gen
    ("mobile_375", 375, 667),  # iPhone SE 2/3
    ("mobile_414", 414, 896),  # iPhone Plus
    ("tablet_768", 768, 1024),  # iPad portrait
    ("laptop_1024", 1024, 768),  # netbook
    ("laptop_1280", 1280, 800),  # MacBook 13"
    ("desktop_1366", 1366, 768),  # PC commun Win10/Win11
    ("desktop_1440", 1440, 900),  # MacBook 15"
    ("desktop_1920", 1920, 1080),  # Full HD
    ("4k_3840", 3840, 2160),  # 4K
]

ROUTES = ["/status", "/library", "/quality", "/validation", "/settings", "/help"]


def _authentifier_le_contexte(ctx, token: str) -> None:
    """Pose le jeton en `sessionStorage` AVANT que le moindre script ne tourne.

    PAS `?ntoken=` DANS L'URL. Ce harnais l'a fait jusqu'au 2026-08-31 : depuis
    #1207, `_detectNativeBoot` (web/dashboard/app.js) lit le jeton dans le
    FRAGMENT et ne consulte plus la query DU TOUT. Le harnais fournissait donc
    un jeton par un canal mort, et sans que rien ne le signale — `requireAuth()`
    rend `true` en loopback, donc les vues se rendaient, mais SANS Bearer.

    Consequence propre a CE harnais : sur des ecrans vides, `scrollWidth` ne
    depasse jamais `clientWidth`, donc la detection de debordement horizontal ne
    pouvait plus rien trouver — dix viewports rendaient un verdict vert sans
    avoir rien observe, et les captures montraient des vues depeuplees.

    Forme reprise de `tests/e2e_dashboard/conftest.py` : `sessionStorage` et pas
    `localStorage`, car `getToken()` (core/state.js) le lit EN PRIORITE et ne
    consulte `localStorage` que si `cinesort.dashboard.persist` vaut "1".
    """
    ctx.add_init_script(
        "try { sessionStorage.setItem('cinesort.dashboard.token', "
        + json.dumps(token)
        + "); } catch (e) { /* no-op */ }"
    )


class ResponsiveViewportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        token = os.environ.get("CINESORT_API_TOKEN")
        if not token:
            raise unittest.SkipTest("CINESORT_API_TOKEN required")
        cls.token = token

        try:
            from playwright.sync_api import sync_playwright

            cls.playwright = sync_playwright().start()
        except ImportError:
            raise unittest.SkipTest("playwright non installé")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "playwright"):
            cls.playwright.stop()

    def test_capture_all_viewports(self):
        overflow_findings = []

        for vp_name, w, h in VIEWPORTS:
            vp_dir = OUTPUT_DIR / vp_name
            vp_dir.mkdir(exist_ok=True)

            browser = self.playwright.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": w, "height": h})
            _authentifier_le_contexte(ctx, self.token)
            page = ctx.new_page()
            page.goto(f"{DASHBOARD_URL}?native=1")
            page.wait_for_load_state("networkidle")

            for route in ROUTES:
                page.evaluate(f"window.location.hash = '{route}'")
                page.wait_for_timeout(800)

                # Capture
                fname = route.replace("/", "_").strip("_") + ".png"
                page.screenshot(path=str(vp_dir / fname), full_page=False)

                # Détection débordement horizontal
                overflow = page.evaluate("""
                  () => {
                    const docW = document.documentElement.clientWidth;
                    const scrollW = document.documentElement.scrollWidth;
                    return scrollW > docW + 5; // tolérance 5px
                  }
                """)
                if overflow:
                    overflow_findings.append(
                        {
                            "viewport": vp_name,
                            "route": route,
                            "doc_width": w,
                            "scroll_width": page.evaluate("document.documentElement.scrollWidth"),
                        }
                    )

            browser.close()

        # Rapport overflow
        if overflow_findings:
            md = "# V4-06 — Débordements détectés\n\n"
            md += "| Viewport | Route | Largeur viewport | Largeur scroll |\n"
            md += "|---|---|---|---|\n"
            for f in overflow_findings:
                md += f"| {f['viewport']} | {f['route']} | {f['doc_width']}px | {f['scroll_width']}px |\n"
            OVERFLOW_REPORT.write_text(md, encoding="utf-8")

        # Soft assertion : info, ne fail pas la CI mais on note
        if overflow_findings:
            print(f"\n⚠ {len(overflow_findings)} débordements horizontaux détectés (cf {OVERFLOW_REPORT})")


if __name__ == "__main__":
    unittest.main()
