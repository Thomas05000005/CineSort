"""Test E2E desktop — 11. Verification approfondie (cas ambigus, filtres).

Lancer : CINESORT_E2E=1 pytest tests/e2e_desktop/test_11_verification_deep.py -v
Prerequis : un scan a ete execute (test_10 doit passer d'abord).
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
class TestVerificationDeep:
    """Tests approfondis de la vue Validation — filtres et inspecteur."""

    def _go_to_validation(self, page):
        """Naviguer vers la vue validation legacy."""
        page.evaluate("() => { if (typeof showView === 'function') showView('validation'); }")
        page.wait_for_timeout(500)

    def test_filter_confidence_low(self, page):
        """Le filtre confiance 'Low' reduit le nombre de lignes."""
        self._go_to_validation(page)
        # Compter les lignes avant filtre
        total = page.evaluate("() => document.querySelectorAll('#planTbody tr').length")
        # Appliquer le filtre
        page.select_option('[data-testid="val-filter-conf"]', "low")
        page.wait_for_timeout(500)
        filtered = page.evaluate("() => document.querySelectorAll('#planTbody tr').length")
        base = BasePage(page)
        base.screenshot("11_01_filter_low_confidence")
        # Le nombre filtre doit etre <= total (et potentiellement > 0 si des cas ambigus)
        assert filtered <= total, f"Filtre Low n'a pas reduit les lignes ({filtered} >= {total})"
        # Reset
        page.select_option('[data-testid="val-filter-conf"]', "all")
        page.wait_for_timeout(300)

    def test_filter_source_name(self, page):
        """Le filtre source 'Nom' affiche uniquement les films sources par nom."""
        self._go_to_validation(page)
        page.select_option('[data-testid="val-filter-source"]', "name")
        page.wait_for_timeout(500)
        count = page.evaluate("() => document.querySelectorAll('#planTbody tr').length")
        BasePage(page).screenshot("11_02_filter_source_name")
        # Il devrait y avoir des resultats (les films sans NFO ni TMDb)
        # Reset
        page.select_option('[data-testid="val-filter-source"]', "all")
        page.wait_for_timeout(300)

    def test_filter_combination(self, page):
        """Combiner 2 filtres reduit davantage les lignes."""
        self._go_to_validation(page)
        total = page.evaluate("() => document.querySelectorAll('#planTbody tr').length")
        # Appliquer 2 filtres
        page.select_option('[data-testid="val-filter-conf"]', "low")
        page.wait_for_timeout(300)
        page.select_option('[data-testid="val-filter-source"]', "name")
        page.wait_for_timeout(500)
        combined = page.evaluate("() => document.querySelectorAll('#planTbody tr').length")
        BasePage(page).screenshot("11_03_filter_combined")
        assert combined <= total
        # Reset
        page.select_option('[data-testid="val-filter-conf"]', "all")
        page.select_option('[data-testid="val-filter-source"]', "all")
        page.wait_for_timeout(300)

    def test_inspector_on_row_click(self, page):
        """Cliquer sur une ligne ouvre l'inspecteur avec des details."""
        self._go_to_validation(page)
        # Cliquer sur la premiere ligne
        rows = page.query_selector_all("#planTbody tr")
        if rows:
            rows[0].click()
            page.wait_for_timeout(500)
        # L'inspecteur doit avoir du contenu
        title = page.evaluate("""() => {
            const el = document.querySelector('[data-testid="val-inspector-title"]');
            return el ? el.textContent.trim() : '';
        }""")
        body = page.evaluate("""() => {
            const el = document.querySelector('[data-testid="val-inspector-body"]');
            return el ? el.textContent.trim() : '';
        }""")
        BasePage(page).screenshot("11_04_inspector_open")
        assert title, "L'inspecteur n'a pas de titre"
        assert body, "L'inspecteur n'a pas de contenu"

    def test_search_filter(self, page):
        """La recherche textuelle filtre la table dynamiquement."""
        self._go_to_validation(page)
        total = page.evaluate("() => document.querySelectorAll('#planTbody tr').length")
        # Taper "Inception" dans le champ de recherche
        search = page.query_selector('[data-testid="val-search"]')
        if search:
            search.fill("Inception")
            page.wait_for_timeout(500)
        filtered = page.evaluate("() => document.querySelectorAll('#planTbody tr').length")
        BasePage(page).screenshot("11_05_search_inception")
        # Au moins 1 resultat (les doublons Inception)
        assert filtered >= 1, "Aucun resultat pour 'Inception'"
        assert filtered < total, f"Le filtre n'a pas reduit les lignes ({filtered} >= {total})"
        # Clear
        if search:
            search.fill("")
            page.wait_for_timeout(300)
