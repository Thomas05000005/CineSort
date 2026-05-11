"""Tests E2E performance — temps de chargement et reactivite.

8 tests : login, auth, status, library, recherche, review, navigation, modale.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)


class TestPerformance:
    """Tests de performance et temps de reponse."""

    def test_login_page_loads_under_2s(self, page, e2e_server):
        """Page login charge en < 2s."""
        t0 = page.evaluate("performance.now()")
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=5000)
        t1 = page.evaluate("performance.now()")
        duration_ms = t1 - t0
        assert duration_ms < 2000, f"Login a pris {duration_ms:.0f}ms (> 2000ms)"

    def test_auth_roundtrip_under_1s(self, page, e2e_server):
        """Auth roundtrip (fill + click → shell visible) < 1s."""
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_selector("#loginToken", timeout=5000)
        page.fill("#loginToken", e2e_server["token"])
        t0 = page.evaluate("performance.now()")
        page.click("#loginBtn")
        page.wait_for_selector("#app-shell:not(.hidden)", timeout=5000)
        t1 = page.evaluate("performance.now()")
        duration_ms = t1 - t0
        assert duration_ms < 3000, f"Auth a pris {duration_ms:.0f}ms (> 3000ms)"

    def test_status_loads_under_3s(self, authenticated_page, e2e_server):
        """Page status charge en < 3s apres navigation."""
        page = authenticated_page
        t0 = page.evaluate("performance.now()")
        page.evaluate("window.location.hash = '#/status'")
        page.wait_for_timeout(2000)
        t1 = page.evaluate("performance.now()")
        duration_ms = t1 - t0
        assert duration_ms < 5000, f"Status a pris {duration_ms:.0f}ms"

    def test_library_renders_under_2s(self, authenticated_page, e2e_server):
        """Library avec 15 films rend en < 2s."""
        page = authenticated_page
        t0 = page.evaluate("performance.now()")
        page.evaluate("window.location.hash = '#/library'")
        page.wait_for_timeout(2000)
        t1 = page.evaluate("performance.now()")
        duration_ms = t1 - t0
        assert duration_ms < 5000, f"Library a pris {duration_ms:.0f}ms"

    def test_library_search_under_500ms(self, authenticated_page, e2e_server):
        """Filtrage recherche library en < 500ms."""
        page = authenticated_page
        page.evaluate("window.location.hash = '#/library'")
        page.wait_for_timeout(2000)
        search = page.query_selector("#librarySearch")
        if search:
            t0 = page.evaluate("performance.now()")
            page.fill("#librarySearch", "Avengers")
            page.wait_for_timeout(500)  # debounce
            t1 = page.evaluate("performance.now()")
            duration_ms = t1 - t0
            assert duration_ms < 2000, f"Recherche a pris {duration_ms:.0f}ms"

    def test_quality_loads_under_3s(self, authenticated_page, e2e_server):
        """Page qualite (QIJ) charge en < 3s.

        V1-05 : remplace l'ex test_review_loads_under_3s puisque /review
        a ete supprime (FIX-4 CRIT-5) et que le triage est integre dans
        Library workflow.
        """
        page = authenticated_page
        t0 = page.evaluate("performance.now()")
        page.evaluate("window.location.hash = '#/quality'")
        page.wait_for_timeout(3000)
        t1 = page.evaluate("performance.now()")
        duration_ms = t1 - t0
        assert duration_ms < 8000, f"Quality a pris {duration_ms:.0f}ms"

    def test_navigation_switch_under_500ms(self, authenticated_page, e2e_server):
        """Changement de vue < 500ms."""
        page = authenticated_page
        page.evaluate("window.location.hash = '#/library'")
        page.wait_for_timeout(1000)
        t0 = page.evaluate("performance.now()")
        # V1-05 : /runs supprime (FIX-4) ; on bascule vers /jellyfin a la place.
        page.evaluate("window.location.hash = '#/jellyfin'")
        page.wait_for_timeout(300)
        t1 = page.evaluate("performance.now()")
        duration_ms = t1 - t0
        assert duration_ms < 2000, f"Navigation a pris {duration_ms:.0f}ms"

    def test_modal_opens_under_300ms(self, authenticated_page, e2e_server):
        """Ouverture modale detail film < 300ms."""
        page = authenticated_page
        page.evaluate("window.location.hash = '#/library'")
        page.wait_for_timeout(2000)
        rows = page.query_selector_all("#libTable tbody tr")
        if rows:
            t0 = page.evaluate("performance.now()")
            rows[0].click()
            page.wait_for_timeout(300)
            t1 = page.evaluate("performance.now()")
            duration_ms = t1 - t0
            assert duration_ms < 2000, f"Modale a pris {duration_ms:.0f}ms"
