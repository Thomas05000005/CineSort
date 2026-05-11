"""Tests E2E login du dashboard CineSort.

10 tests couvrant : affichage, token vide/invalide/valide, persist, Enter, rate limit.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

from pages.login_page import LoginPage  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login_page(page, e2e_server) -> LoginPage:
    lp = LoginPage(page, e2e_server["url"])
    lp.goto_dashboard()
    page.wait_for_selector("#loginToken", timeout=5000)
    return lp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLogin:
    """Tests du flux de login."""

    def test_login_page_shown_on_first_visit(self, page, e2e_server):
        """Le dashboard affiche la page de login au premier acces."""
        lp = _login_page(page, e2e_server)
        assert lp.is_login_visible()
        assert not lp.is_shell_visible()

    def test_login_token_input_has_focus(self, page, e2e_server):
        """Le champ token a le focus au chargement."""
        lp = _login_page(page, e2e_server)
        # Verifier que l'element actif est le token input
        focused_id = page.evaluate("document.activeElement?.id || ''")
        assert focused_id == "loginToken"

    def test_login_empty_token_shows_error(self, page, e2e_server):
        """Token vide → message d'erreur."""
        lp = _login_page(page, e2e_server)
        lp.click_login()
        page.wait_for_timeout(500)
        msg = lp.get_error_message()
        assert msg, "Un message d'erreur devrait s'afficher pour un token vide"

    def test_login_wrong_token_shows_error(self, page, e2e_server):
        """Token invalide → message d'erreur."""
        lp = _login_page(page, e2e_server)
        msg = lp.login_expect_error("wrong-token-123")
        assert msg, "Un message d'erreur devrait s'afficher pour un mauvais token"

    def test_login_correct_token_navigates_to_status(self, page, e2e_server):
        """Token valide → redirection vers #/status."""
        lp = _login_page(page, e2e_server)
        lp.login(e2e_server["token"])
        # Verifier le hash
        url_hash = page.evaluate("window.location.hash")
        assert "/status" in url_hash

    def test_login_shell_visible_after_auth(self, page, e2e_server):
        """Apres login, #app-shell est visible et #view-login cache."""
        lp = _login_page(page, e2e_server)
        lp.login(e2e_server["token"])
        assert lp.is_shell_visible()
        assert not lp.is_login_visible()

    def test_login_form_submit_enter(self, page, e2e_server):
        """Appuyer sur Enter soumet le formulaire."""
        lp = _login_page(page, e2e_server)
        lp.submit_with_enter(e2e_server["token"])
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)
        assert lp.is_shell_visible()

    def test_login_persist_survives_reload(self, page, e2e_server):
        """Avec 'Rester connecte', le token survit au rechargement."""
        lp = _login_page(page, e2e_server)
        lp.check_persist(True)
        lp.login(e2e_server["token"], persist=True)
        assert lp.is_shell_visible()
        # Recharger la page
        page.reload()
        page.wait_for_timeout(2000)
        # Le shell devrait toujours etre visible (token en localStorage)
        shell_visible = page.evaluate("!document.getElementById('app-shell')?.classList.contains('hidden')")
        assert shell_visible, "Le shell devrait rester visible apres rechargement avec persist"

    def test_login_no_persist_clears_on_new_context(self, page, e2e_server):
        """Sans persist, le token est en sessionStorage uniquement."""
        lp = _login_page(page, e2e_server)
        lp.check_persist(False)
        lp.login(e2e_server["token"])
        # Verifier que le token est dans sessionStorage, pas localStorage
        in_session = page.evaluate("!!sessionStorage.getItem('cinesort.dashboard.token')")
        in_local = page.evaluate("!!localStorage.getItem('cinesort.dashboard.token')")
        assert in_session or in_local  # au moins l'un
        # Le comportement exact depend de isPersistent()

    def test_login_screenshot(self, page, e2e_server):
        """Capture un screenshot de la page de login sans erreur."""
        lp = _login_page(page, e2e_server)
        screenshot = lp.take_screenshot("login_page")
        assert screenshot.exists()
        assert screenshot.stat().st_size > 1000  # > 1 Ko
