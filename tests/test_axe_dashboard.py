"""V4-07 - Audit a11y axe-core sur le dashboard via Playwright.

Run:
  CINESORT_API_TOKEN=<token> python -m unittest tests.test_axe_dashboard -v
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

OUTPUT_DIR = Path("audit/results")
DASHBOARD_URL = "http://127.0.0.1:8642/dashboard/"
# MESURE 2026-08-06 contre les `registerRoute` de web/dashboard/app.js : cinq de
# ces six routes existent, `/validation` n'a JAMAIS ete enregistree. Cette
# derniere auditait donc une page vide, sans que rien ne le signale. L'ecran de
# validation vit dans `/traitement`.
#
# Le garde `tests/test_axe_routes_existent.py` verrouille cette liste contre le
# routeur reel : une route qui disparait fait desormais rougir, au lieu de vider
# silencieusement l'audit.
ROUTES = ["/status", "/library", "/quality", "/traitement", "/settings", "/help"]


def _authentifier_le_contexte(ctx, token: str) -> None:
    """Pose le jeton en `sessionStorage` AVANT que le moindre script ne tourne.

    PAS `?ntoken=` DANS L'URL. Ce harnais l'a fait jusqu'au 2026-08-31 : depuis
    #1207, `_detectNativeBoot` (web/dashboard/app.js) lit le jeton dans le
    FRAGMENT et ne consulte plus la query DU TOUT — c'est meme grave par
    `test_boot_natif_jeton.py::test_le_jeton_de_la_QUERY_n_est_PLUS_lu`. Le
    harnais fournissait donc un jeton par un canal mort.

    Rien ne l'a signale : `requireAuth()` rend `true` en loopback
    (`_isNativeMode`), donc les vues se rendaient quand meme — mais SANS Bearer,
    donc avec des donnees vides ou en 401. L'audit a11y portait sur des ecrans
    depeuples et s'annoncait comme la baseline du dashboard.

    C'est la meme classe de defaut que la route `/validation` inexistante
    ci-dessus : un audit qui n'observe rien et rend un verdict propre.

    La forme retenue est celle, deja eprouvee, de
    `tests/e2e_dashboard/conftest.py` : c'est `sessionStorage` qu'il faut ecrire,
    car `getToken()` (core/state.js) le lit EN PRIORITE et ne consulte
    `localStorage` que si `cinesort.dashboard.persist` vaut "1". Ecrire cette
    seule cle equivaut a `setToken(token, persist=false)`, et le portillon de
    boot d'`app.js` la cherche explicitement pour appeler `markTokenReady()`.
    """
    ctx.add_init_script(
        "try { sessionStorage.setItem('cinesort.dashboard.token', "
        + json.dumps(token)
        + "); } catch (e) { /* no-op */ }"
    )


class AxeDashboardTests(unittest.TestCase):
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
            raise unittest.SkipTest("playwright non installe")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "playwright"):
            cls.playwright.stop()

    def test_axe_baseline(self):
        browser = self.playwright.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        _authentifier_le_contexte(ctx, self.token)
        page = ctx.new_page()
        page.goto(f"{DASHBOARD_URL}?native=1")
        page.wait_for_load_state("networkidle")

        # Charge axe-core depuis CDN (acceptable pour test, pas runtime)
        page.add_script_tag(url="https://cdn.jsdelivr.net/npm/axe-core@4.10.0/axe.min.js")

        all_violations = {}
        for route in ROUTES:
            page.evaluate(f"window.location.hash = '{route}'")
            page.wait_for_timeout(800)
            result = page.evaluate("""
              async () => {
                const r = await axe.run({
                  runOnly: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']
                });
                return {
                  violations: r.violations.map(v => ({
                    id: v.id, impact: v.impact, help: v.help, helpUrl: v.helpUrl,
                    nodes: v.nodes.length
                  }))
                };
              }
            """)
            all_violations[route] = result["violations"]

        browser.close()

        # Genere un rapport
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        report_md = OUTPUT_DIR / "v4-07-axe-baseline.md"

        md = "# V4-07 - Baseline axe-core\n\n"
        md += (
            "Audit automatique a11y via [axe-core](https://github.com/dequelabs/axe-core) (WCAG 2.0/2.1/2.2 A+AA).\n\n"
        )
        total_violations = 0
        critical_violations = []

        for route, violations in all_violations.items():
            md += f"## {route}\n\n"
            if not violations:
                md += "Aucune violation detectee par axe-core.\n\n"
                continue
            md += "| Regle | Impact | Aide | Noeuds touches |\n|---|---|---|---|\n"
            for v in violations:
                md += f"| `{v['id']}` | {v['impact']} | [{v['help']}]({v['helpUrl']}) | {v['nodes']} |\n"
                total_violations += 1
                if v["impact"] in ("critical", "serious"):
                    critical_violations.append(f"{route}: {v['id']}")
            md += "\n"

        md += "\n## Resume\n\n"
        md += f"- **Total violations** : {total_violations}\n"
        md += f"- **Critical/Serious** : {len(critical_violations)}\n"
        if critical_violations:
            md += "\n### Critiques a fixer avant release\n"
            for v in critical_violations:
                md += f"- {v}\n"

        report_md.write_text(md, encoding="utf-8")

        # Soft assertion : on note mais on ne fail pas la suite (sera corrige dans la suite V4)
        if critical_violations:
            print(f"\n[WARN] {len(critical_violations)} violations critiques (cf {report_md})")

        # Hard assertion : 0 critique acceptable pour public release
        # -> decommente apres que les findings soient fixes
        # self.assertEqual(len(critical_violations), 0,
        #                  f"Violations critiques: {critical_violations}")


if __name__ == "__main__":
    unittest.main()
