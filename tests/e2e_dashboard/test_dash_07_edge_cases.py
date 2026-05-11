"""Test E2E dashboard — 07. Cas limites et robustesse.

Lancer : pytest tests/e2e_dashboard/test_dash_07_edge_cases.py -v

Teste le comportement du dashboard dans des scenarios atypiques :
navigation rapide, polling idle, double login, tokens extremes.
"""

from __future__ import annotations


class TestDashEdgeCases:
    """Tests de robustesse et cas limites du dashboard."""

    def test_rapid_navigation_no_crash(self, dashboard_page):
        """Naviguer rapidement entre les vues ne produit pas d'erreur JS."""
        errors = []
        dashboard_page.on("pageerror", lambda err: errors.append(str(err)))

        tabs = ["status", "library", "quality", "logs", "settings", "library", "status", "quality", "settings", "logs"]
        for tab in tabs:
            dashboard_page.click(f'[data-testid="nav-{tab}"]')
            dashboard_page.wait_for_timeout(200)

        dashboard_page.wait_for_timeout(2000)
        assert not errors, f"Erreurs JS pendant la navigation rapide: {errors}"

    def test_f5_refresh_reloads_view(self, dashboard_page):
        """F5 recharge la vue sans recharger la page."""
        dashboard_page.click('[data-testid="nav-status"]')
        dashboard_page.wait_for_timeout(1000)
        hash_before = dashboard_page.evaluate("() => window.location.hash")
        dashboard_page.keyboard.press("F5")
        dashboard_page.wait_for_timeout(1500)
        hash_after = dashboard_page.evaluate("() => window.location.hash")
        assert hash_before == hash_after, "F5 a change le hash"

    def test_double_login_does_not_break(self, page, e2e_server):
        """Se connecter deux fois de suite ne casse pas l'etat."""
        url = e2e_server["dashboard_url"]
        token = e2e_server["token"]

        # Premier login
        page.goto(url)
        page.wait_for_selector("#loginToken", timeout=8000)
        page.fill("#loginToken", token)
        page.click("#loginBtn")
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=15000)

        # Retour au login
        page.evaluate("() => { window.location.hash = '#/login'; }")
        page.wait_for_timeout(500)

        # Deuxieme login
        page.fill("#loginToken", token)
        page.click("#loginBtn")
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=15000)
        assert page.is_visible("#app-shell"), "Le shell n'est pas visible apres double login"

    def test_long_token_does_not_crash(self, page, e2e_server):
        """Un token tres long ne plante pas le formulaire."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=8000)
        long_token = "x" * 5000
        page.fill("#loginToken", long_token)
        page.click("#loginBtn")
        page.wait_for_timeout(2000)
        # Doit juste echouer avec un message, pas crasher
        shell_hidden = page.evaluate("() => document.getElementById('app-shell')?.classList.contains('hidden')")
        assert shell_hidden, "Le shell ne devrait pas apparaitre avec un faux token"

    def test_polling_idle_no_js_errors(self, dashboard_page):
        """Le polling idle (refresh auto) ne produit pas d'erreur JS."""
        errors = []
        dashboard_page.on("pageerror", lambda err: errors.append(str(err)))

        dashboard_page.click('[data-testid="nav-status"]')
        # Attendre assez pour que le polling idle se declenche (15s interval)
        dashboard_page.wait_for_timeout(18000)
        assert not errors, f"Erreurs JS pendant le polling idle: {errors}"

    def test_direct_hash_navigation(self, dashboard_page):
        """Changer le hash manuellement navigue vers la vue correcte."""
        dashboard_page.evaluate("() => { window.location.hash = '#/settings'; }")
        dashboard_page.wait_for_timeout(800)
        hash_val = dashboard_page.evaluate("() => window.location.hash")
        assert "/settings" in hash_val

    def test_invalid_hash_redirects(self, dashboard_page):
        """Un hash invalide redirige vers le login ou une vue par defaut."""
        dashboard_page.evaluate("() => { window.location.hash = '#/nonexistent'; }")
        dashboard_page.wait_for_timeout(500)
        hash_val = dashboard_page.evaluate("() => window.location.hash")
        # Doit etre redirige vers login ou rester sur la vue precedente
        assert hash_val != "#/nonexistent", f"Route invalide non interceptee: {hash_val}"

    def test_all_views_have_content(self, dashboard_page):
        """Chaque vue a un contenu non vide apres chargement."""
        views = {
            "status": "statusContent",
            "library": "libraryContent",
            "quality": "qualityContent",
            "logs": "logsContent",
            "settings": "settingsContent",
        }
        for tab, container_id in views.items():
            dashboard_page.click(f'[data-testid="nav-{tab}"]')
            dashboard_page.wait_for_timeout(1500)
            content_len = dashboard_page.evaluate(f"""() => {{
                const el = document.getElementById('{container_id}');
                return el ? el.innerHTML.trim().length : 0;
            }}""")
            assert content_len > 0, f"Vue '{tab}' est vide (container: {container_id})"
