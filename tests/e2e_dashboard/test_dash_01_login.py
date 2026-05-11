"""Test E2E dashboard — 01. Login et authentification.

Lancer : pytest tests/e2e_dashboard/test_dash_01_login.py -v
"""

from __future__ import annotations


class TestDashLogin:
    """Tests d'authentification au dashboard distant."""

    def test_login_page_displayed(self, page, e2e_server):
        """La page de login s'affiche avec tous les elements interactifs."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=8000)
        assert page.is_visible("#loginToken"), "Champ token absent"
        assert page.is_visible("#loginBtn"), "Bouton login absent"
        assert page.is_visible("#loginPersist"), "Checkbox persist absente"
        # Le shell doit etre cache
        shell_hidden = page.evaluate("() => document.getElementById('app-shell')?.classList.contains('hidden')")
        assert shell_hidden, "Le shell devrait etre cache avant login"
        # Le champ token doit etre editable
        page.fill("#loginToken", "test")
        val = page.input_value("#loginToken")
        assert val == "test", "Le champ token n'est pas editable"

    def test_login_valid_token(self, page, e2e_server):
        """Se connecter avec un token valide affiche le shell et masque le login."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=8000)
        page.fill("#loginToken", e2e_server["token"])
        page.click("#loginBtn")
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=15000)
        assert page.is_visible("#app-shell"), "Le shell n'est pas visible apres login"
        # Le formulaire de login doit etre masque
        login_hidden = page.evaluate("() => document.getElementById('view-login')?.classList.contains('hidden')")
        assert login_hidden, "Le formulaire de login devrait etre masque apres login"
        # Le hash doit pointer vers /status
        hash_val = page.evaluate("() => window.location.hash")
        assert "/status" in hash_val, f"Hash inattendu apres login: {hash_val}"

    def test_login_invalid_token(self, page, e2e_server):
        """Un token invalide affiche un message d'erreur et le shell reste cache."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=8000)
        page.fill("#loginToken", "mauvais-token-xxxxx")
        page.click("#loginBtn")
        page.wait_for_timeout(3000)
        # Le shell ne doit PAS etre visible
        shell_hidden = page.evaluate("() => document.getElementById('app-shell')?.classList.contains('hidden')")
        assert shell_hidden, "Le shell est visible avec un token invalide"
        # Un message d'erreur doit etre affiche
        msg = page.evaluate("() => document.getElementById('loginMsg')?.textContent || ''")
        assert msg, "Aucun message d'erreur affiche pour token invalide"

    def test_login_empty_token(self, page, e2e_server):
        """Soumettre un token vide ne provoque pas de connexion."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=8000)
        page.fill("#loginToken", "")
        page.click("#loginBtn")
        page.wait_for_timeout(1000)
        shell_hidden = page.evaluate("() => document.getElementById('app-shell')?.classList.contains('hidden')")
        assert shell_hidden, "Le shell ne doit pas apparaitre avec un token vide"

    def test_login_button_disabled_during_request(self, page, e2e_server):
        """Le bouton est desactive pendant la requete de login."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=8000)
        page.fill("#loginToken", e2e_server["token"])
        # Intercepter le clic et verifier le state du bouton
        page.evaluate("""() => {
            window._btnStates = [];
            const btn = document.getElementById('loginBtn');
            const orig = btn.click;
            const obs = new MutationObserver(() => {
                window._btnStates.push(btn.disabled);
            });
            obs.observe(btn, { attributes: true, attributeFilter: ['disabled'] });
        }""")
        page.click("#loginBtn")
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=15000)
        states = page.evaluate("() => window._btnStates || []")
        # Le bouton doit avoir ete desactive puis reactive
        assert len(states) >= 2, f"Le bouton doit changer de state: {states}"
        assert states[0] is True, "Le bouton doit etre desactive pendant la requete"

    def test_login_persist_checkbox(self, page, e2e_server):
        """La checkbox 'Rester connecte' stocke le token en localStorage."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginPersist", timeout=8000)
        page.check("#loginPersist")
        page.fill("#loginToken", e2e_server["token"])
        page.click("#loginBtn")
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=15000)
        token_stored = page.evaluate("() => !!localStorage.getItem('cinesort.dashboard.token')")
        assert token_stored, "Le token n'est pas stocke en localStorage avec persist"

    def test_login_screenshot(self, page, e2e_server):
        """Capture de la page de login."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=8000)
        page.screenshot(path="tests/e2e_dashboard/screenshots/dash_01_login.png")

    def test_no_js_console_errors_on_load(self, page, e2e_server):
        """Aucune erreur JS critique au chargement du dashboard."""
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=8000)
        page.wait_for_timeout(1000)
        assert not errors, f"Erreurs JS au chargement: {errors}"
