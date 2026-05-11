"""Tests E2E navigation du dashboard CineSort.

10 tests : sidebar, routing hash, aria, back/forward, version.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

from pages.base_page import BasePage  # noqa: E402

# V1-05 : sections HTML /runs et /review supprimees par FIX-4 CRIT-5
# (sections orphelines retirees de index.html). Routes conservees comme
# alias historiques mais ne sont plus dans la sidebar.
_ROUTES = ["/status", "/library", "/jellyfin", "/logs"]


class TestNavigation:
    """Tests navigation sidebar et routing hash."""

    def test_sidebar_six_nav_buttons(self, authenticated_page, e2e_server):
        """La sidebar contient au moins 4 boutons de navigation (post-FIX-4)."""
        bp = BasePage(authenticated_page, e2e_server["url"])
        routes = bp.get_nav_buttons()
        assert len(routes) >= 4
        for r in _ROUTES:
            assert r in routes, f"Route {r} manquante dans la sidebar"

    def test_click_nav_changes_view(self, authenticated_page, e2e_server):
        """Cliquer chaque bouton active la vue correspondante."""
        page = authenticated_page
        # V1-05 : /runs et /review supprimes (FIX-4 CRIT-5).
        for route in ["/library", "/status"]:
            page.click(f'.nav-btn[data-route="{route}"]')
            page.wait_for_timeout(500)
            view_id = f"view-{route.lstrip('/')}"
            el = page.query_selector(f"#{view_id}")
            assert el is not None, f"Vue #{view_id} introuvable"

    def test_active_nav_aria_selected(self, authenticated_page, e2e_server):
        """Le bouton actif a aria-selected=true."""
        page = authenticated_page
        bp = BasePage(page, e2e_server["url"])
        # On est sur /status apres login
        active = bp.get_active_nav_route()
        assert active == "/status"

    def test_one_view_active_at_a_time(self, authenticated_page, e2e_server):
        """Une seule vue a la classe .active a la fois."""
        page = authenticated_page
        page.click('.nav-btn[data-route="/library"]')
        page.wait_for_timeout(500)
        active_views = page.query_selector_all(".main .view.active")
        assert len(active_views) == 1, f"Attendu 1 vue .active, trouve {len(active_views)}"

    def test_hash_navigation_direct(self, authenticated_page, e2e_server):
        """Changer le hash directement navigue vers la bonne vue."""
        page = authenticated_page
        # V1-05 : /runs supprime (FIX-4) ; on teste /library a la place.
        page.evaluate("window.location.hash = '#/library'")
        page.wait_for_timeout(500)
        view = page.query_selector("#view-library:not(.hidden)")
        assert view is not None

    def test_unknown_hash_fallback(self, page, e2e_server):
        """Hash inconnu sans token → retour au login."""
        page.goto(e2e_server["dashboard_url"] + "#/unknown")
        page.wait_for_timeout(1000)
        login = page.query_selector("#view-login")
        assert login is not None

    def test_protected_route_no_token(self, page, e2e_server):
        """Route protegee sans token → login affiche."""
        page.goto(e2e_server["dashboard_url"] + "#/library")
        page.wait_for_timeout(1000)
        login_visible = page.evaluate("!document.getElementById('view-login')?.classList.contains('hidden')")
        assert login_visible

    def test_version_in_sidebar(self, authenticated_page, e2e_server):
        """#dashVersion contient du texte."""
        text = authenticated_page.inner_text("#dashVersion")
        assert text.strip(), "#dashVersion est vide"

    def test_brand_cinesort(self, authenticated_page, e2e_server):
        """Le texte 'CineSort' est present dans la sidebar."""
        sidebar_text = authenticated_page.inner_text(".sidebar")
        assert "CineSort" in sidebar_text

    def test_back_forward_browser(self, authenticated_page, e2e_server):
        """Browser back/forward fonctionne avec le hash routing."""
        page = authenticated_page
        # V1-05 : /runs remplace par /jellyfin (FIX-4 a supprime sections runs/review).
        page.click('.nav-btn[data-route="/library"]')
        page.wait_for_timeout(300)
        page.click('.nav-btn[data-route="/jellyfin"]')
        page.wait_for_timeout(300)
        # Back -> library
        page.go_back()
        page.wait_for_timeout(500)
        current_hash = page.evaluate("window.location.hash")
        assert "/library" in current_hash
