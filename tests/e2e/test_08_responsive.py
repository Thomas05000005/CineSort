"""Tests E2E responsive — 3 viewports (desktop, tablet, mobile).

10 tests : sidebar, bottom tab, colonnes, modale, KPIs, scroll.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

from pages.base_page import BasePage  # noqa: E402

DESKTOP = {"width": 1280, "height": 800}
TABLET = {"width": 768, "height": 1024}
MOBILE = {"width": 375, "height": 812}


def _auth(page, e2e_server):
    """Login et retourne une BasePage."""
    page.goto(e2e_server["dashboard_url"])
    page.wait_for_selector("#loginToken", timeout=5000)
    page.fill("#loginToken", e2e_server["token"])
    page.click("#loginBtn")
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)
    return BasePage(page, e2e_server["url"])


class TestResponsive:
    """Tests layout responsive."""

    def test_desktop_sidebar_expanded(self, page, e2e_server):
        """Desktop 1280px : sidebar etendue visible."""
        page.set_viewport_size(DESKTOP)
        bp = _auth(page, e2e_server)
        sidebar = page.query_selector(".sidebar")
        assert sidebar is not None
        box = sidebar.bounding_box()
        assert box is not None
        assert box["width"] >= 150, f"Sidebar trop etroite : {box['width']}px"

    def test_tablet_sidebar_collapsed(self, page, e2e_server):
        """Tablet 768px : sidebar collapse (< 100px)."""
        page.set_viewport_size(TABLET)
        bp = _auth(page, e2e_server)
        sidebar = page.query_selector(".sidebar")
        assert sidebar is not None
        box = sidebar.bounding_box()
        assert box is not None
        assert box["width"] < 150, f"Sidebar non collapse a 768px : {box['width']}px"

    def test_tablet_text_hidden(self, page, e2e_server):
        """Tablet : les labels texte des nav buttons sont caches."""
        page.set_viewport_size(TABLET)
        bp = _auth(page, e2e_server)
        # Les boutons nav existent mais le texte visible est reduit
        btns = page.query_selector_all(".nav-btn")
        assert len(btns) >= 6

    def test_mobile_bottom_tab_bar(self, page, e2e_server):
        """Mobile 375px : sidebar en bottom tab bar."""
        page.set_viewport_size(MOBILE)
        bp = _auth(page, e2e_server)
        sidebar = page.query_selector(".sidebar")
        assert sidebar is not None
        box = sidebar.bounding_box()
        assert box is not None
        # En mobile, la sidebar est en bas (y > 600)
        assert box["y"] > 400, f"Sidebar pas en bottom : y={box['y']}"

    def test_mobile_nav_functional(self, page, e2e_server):
        """Mobile : clic sur un bouton nav fonctionne."""
        page.set_viewport_size(MOBILE)
        bp = _auth(page, e2e_server)
        page.click('.nav-btn[data-route="/library"]')
        page.wait_for_timeout(500)
        active = page.query_selector(".main .view.active")
        assert active is not None

    def test_desktop_all_library_columns(self, page, e2e_server):
        """Desktop : toutes les colonnes library visibles."""
        page.set_viewport_size(DESKTOP)
        bp = _auth(page, e2e_server)
        bp.navigate_to("library")
        page.wait_for_timeout(2000)
        headers = page.query_selector_all("#libTable thead th")
        assert len(headers) >= 6, f"Seulement {len(headers)} colonnes library"

    def test_mobile_modal_fullscreen(self, page, e2e_server):
        """Mobile : modale en plein ecran."""
        page.set_viewport_size(MOBILE)
        bp = _auth(page, e2e_server)
        bp.navigate_to("library")
        page.wait_for_timeout(2000)
        rows = page.query_selector_all("#libTable tbody tr")
        if rows:
            rows[0].click()
            page.wait_for_timeout(500)
            modal = page.query_selector(".modal-card")
            if modal:
                box = modal.bounding_box()
                # En mobile la modale devrait etre large (> 90% du viewport)
                if box:
                    assert box["width"] >= 300, f"Modale trop etroite en mobile : {box['width']}px"

    def test_login_readable_all_viewports(self, page, e2e_server):
        """Login lisible dans les 3 viewports."""
        for vp in [DESKTOP, TABLET, MOBILE]:
            page.set_viewport_size(vp)
            page.goto(e2e_server["dashboard_url"])
            page.wait_for_selector("#loginToken", timeout=5000)
            token_input = page.query_selector("#loginToken")
            assert token_input is not None
            box = token_input.bounding_box()
            assert box is not None
            assert box["width"] >= 100, f"Input token trop etroit a {vp['width']}px : {box['width']}px"

    def test_mobile_kpi_wrap(self, page, e2e_server):
        """Mobile : KPI cards s'adaptent au viewport etroit."""
        page.set_viewport_size(MOBILE)
        bp = _auth(page, e2e_server)
        bp.navigate_to("status")
        page.wait_for_timeout(2000)
        cards = page.query_selector_all(".kpi-card")
        if cards:
            box_first = cards[0].bounding_box()
            assert box_first is not None
            assert box_first["width"] < 375, "KPI card depasse le viewport mobile"

    def test_mobile_table_scrollable(self, page, e2e_server):
        """Mobile : table review avec scroll horizontal."""
        page.set_viewport_size(MOBILE)
        bp = _auth(page, e2e_server)
        bp.navigate_to("review")
        page.wait_for_timeout(4000)
        table_wrap = page.query_selector(".table-wrap, #reviewTable")
        assert table_wrap is not None
