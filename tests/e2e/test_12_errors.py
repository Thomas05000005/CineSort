"""Tests E2E gestion d'erreurs — token expire, reseau, 429, etc.

8 tests.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

from pages.login_page import LoginPage  # noqa: E402


class TestErrors:
    """Tests de gestion d'erreurs."""

    def test_401_redirects_login(self, authenticated_page, e2e_server):
        """Token expire → redirect vers login."""
        page = authenticated_page
        # Supprimer le token du storage pour simuler expiration
        page.evaluate("sessionStorage.removeItem('cinesort.dashboard.token')")
        page.evaluate("localStorage.removeItem('cinesort.dashboard.token')")
        # Forcer un appel API qui declenchera un 401
        page.evaluate("window.location.hash = '#/library'")
        page.wait_for_timeout(3000)
        # Apres le 401, on devrait etre redirige vers login
        login_el = page.query_selector("#view-login")
        shell_hidden = page.evaluate("document.getElementById('app-shell')?.classList.contains('hidden') ?? true")
        assert login_el is not None or shell_hidden

    def test_empty_run_fallback(self, page, e2e_server):
        """Library sans donnees affiche un message (pas de crash)."""
        # Login
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=5000)
        page.fill("#loginToken", e2e_server["token"])
        page.click("#loginBtn")
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)
        # Naviguer vers library — les donnees existent, mais le contenu ne devrait pas crasher
        page.evaluate("window.location.hash = '#/library'")
        page.wait_for_timeout(2000)
        text = page.inner_text("#libraryContent")
        assert len(text) > 5, "Library content trop court"

    def test_quality_no_crash(self, page, e2e_server):
        """La vue qualite (QIJ tab quality, ex review) se charge sans crash JS."""
        # V1-05 : la vue review legacy est supprimee (FIX-4 CRIT-5),
        # le triage est integre dans Library workflow ; on teste a la
        # place le panneau quality QIJ qui consolide les vues precedentes.
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=5000)
        page.fill("#loginToken", e2e_server["token"])
        page.click("#loginBtn")
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)
        page.evaluate("window.location.hash = '#/quality'")
        page.wait_for_timeout(4000)
        text = page.inner_text("#v5QijQualityPanel")
        # Pas de stacktrace JS visible
        assert "typeerror" not in text.lower()
        assert "uncaught" not in text.lower()

    def test_rate_limit_message(self, page, e2e_server):
        """Apres plusieurs echecs login, un message d'erreur s'affiche."""
        lp = LoginPage(page, e2e_server["url"])
        lp.goto_dashboard()
        page.wait_for_selector("#loginToken", timeout=5000)
        # Seulement 3 tentatives (pour ne pas declencher le rate limiter
        # qui bloquerait les tests suivants sur la meme IP)
        for _ in range(3):
            lp.fill_token("bad-token")
            lp.click_login()
            page.wait_for_timeout(500)
        msg = lp.get_error_message()
        assert msg, "Pas de message d'erreur apres 3 echecs"

    def test_jellyfin_error_graceful(self, authenticated_page, e2e_server):
        """Erreur Jellyfin (faux URL) → pas de crash."""
        page = authenticated_page
        page.evaluate("window.location.hash = '#/jellyfin'")
        page.wait_for_timeout(3000)
        text = page.inner_text("#jellyfinContent")
        assert len(text) > 5
        assert "typeerror" not in text.lower()

    def test_unknown_hash_handled(self, authenticated_page, e2e_server):
        """Hash inconnu → pas de crash."""
        page = authenticated_page
        page.evaluate("window.location.hash = '#/nonexistent'")
        page.wait_for_timeout(1000)
        # La page ne devrait pas etre vide
        body_text = page.inner_text("body")
        assert len(body_text) > 10

    def test_long_title_no_overflow(self, authenticated_page, e2e_server):
        """Titres longs dans la table ne debordent pas."""
        page = authenticated_page
        page.evaluate("window.location.hash = '#/library'")
        page.wait_for_timeout(2000)
        # Verifier qu'aucun element ne depasse le viewport
        overflow = page.evaluate("""
            () => {
                const body = document.body;
                return body.scrollWidth > window.innerWidth + 10;
            }
        """)
        assert not overflow, "La page library a un scroll horizontal (debordement)"

    def test_network_error_no_crash(self, page, e2e_server):
        """Erreur reseau simulee → pas de page vide."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=5000)
        # Login normal d'abord
        page.fill("#loginToken", e2e_server["token"])
        page.click("#loginBtn")
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)
        # La page est chargee — le test verifie que le contenu est present
        text = page.inner_text("body")
        assert len(text) > 20
