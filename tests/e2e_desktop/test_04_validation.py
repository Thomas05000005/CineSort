"""Test E2E desktop — 04. Validation.

Lancer : pytest tests/e2e_desktop/test_04_validation.py -v
"""

from __future__ import annotations


from .pages.base_page import BasePage


class TestValidation:
    """Tests de la vue Validation (table, filtres, inspecteur)."""

    def test_validation_view_accessible(self, page):
        """La vue Validation (legacy) est accessible via navigation interne."""
        base = BasePage(page)
        # Naviguer vers validation (vue legacy, toujours fonctionnelle)
        page.evaluate("() => { if (typeof showView === 'function') showView('validation'); }")
        page.wait_for_timeout(500)
        active = base.get_active_view()
        assert active == "validation", f"Vue active: {active}"

    def test_search_box_exists(self, page):
        """Le champ de recherche existe dans la vue Validation."""
        page.evaluate("() => { if (typeof showView === 'function') showView('validation'); }")
        page.wait_for_timeout(500)
        assert page.is_visible('[data-testid="val-search"]'), "Champ recherche non visible"

    def test_filters_exist(self, page):
        """Les filtres confiance et source existent."""
        page.evaluate("() => { if (typeof showView === 'function') showView('validation'); }")
        page.wait_for_timeout(500)
        assert page.is_visible('[data-testid="val-filter-conf"]'), "Filtre confiance absent"
        assert page.is_visible('[data-testid="val-filter-source"]'), "Filtre source absent"

    def test_save_button_exists(self, page):
        """Le bouton sauvegarder existe."""
        page.evaluate("() => { if (typeof showView === 'function') showView('validation'); }")
        page.wait_for_timeout(500)
        assert page.is_visible('[data-testid="val-btn-save"]'), "Bouton save absent"

    def test_validation_screenshot(self, page):
        """Capture de la vue Validation."""
        base = BasePage(page)
        page.evaluate("() => { if (typeof showView === 'function') showView('validation'); }")
        page.wait_for_timeout(500)
        base.screenshot("04_validation")
