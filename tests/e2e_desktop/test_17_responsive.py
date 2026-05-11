"""Test E2E desktop — 17. Responsive (redimensionnement fenetre).

Lancer : CINESORT_E2E=1 pytest tests/e2e_desktop/test_17_responsive.py -v

Note : pywebview/CDP peut ne pas supporter set_viewport_size.
Les tests utilisent des verifications CSS en fallback.
"""

from __future__ import annotations

import os

import pytest

try:
    import allure
except ImportError:
    allure = None

from .pages.base_page import BasePage


@pytest.mark.skipif(os.environ.get("CINESORT_E2E") != "1", reason="CINESORT_E2E non defini")
class TestResponsive:
    """Tests de responsivite et layout a differentes tailles."""

    def test_sidebar_visible_at_default_size(self, page):
        """La sidebar est visible a la taille par defaut."""
        base = BasePage(page)
        base.navigate_to("home")
        page.wait_for_timeout(500)
        sidebar_visible = page.evaluate("""() => {
            const sidebar = document.querySelector('.sidebar, nav, [role="navigation"]');
            if (!sidebar) return false;
            const style = getComputedStyle(sidebar);
            return style.display !== 'none' && style.visibility !== 'hidden';
        }""")
        BasePage(page).screenshot("17_01_default_size")
        assert sidebar_visible, "La sidebar n'est pas visible a la taille par defaut"

    def test_no_horizontal_overflow(self, page):
        """Pas de debordement horizontal a la taille actuelle."""
        base = BasePage(page)
        base.navigate_to("home")
        page.wait_for_timeout(500)
        overflow = page.evaluate("""() => {
            return document.documentElement.scrollWidth > document.documentElement.clientWidth;
        }""")
        BasePage(page).screenshot("17_02_no_overflow")
        assert not overflow, "Debordement horizontal detecte"

    def test_tables_dont_overflow(self, page):
        """Les tables ne debordent pas de leur conteneur."""
        base = BasePage(page)
        # Naviguer vers la validation (table)
        page.evaluate("() => { if (typeof showView === 'function') showView('validation'); }")
        page.wait_for_timeout(500)
        overflow = page.evaluate("""() => {
            const tables = document.querySelectorAll('.tbl, table');
            for (const t of tables) {
                const parent = t.closest('.table-wrap') || t.parentElement;
                if (parent && t.scrollWidth > parent.clientWidth + 10) return true;
            }
            return false;
        }""")
        BasePage(page).screenshot("17_03_tables_layout")
        # Les tables avec .table-wrap ont overflow-x auto, donc pas de debordement reel
        assert not overflow, "Une table deborde de son conteneur"
