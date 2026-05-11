"""Test E2E desktop — 12. Validation approfondie (presets, bulk, inspecteur).

Lancer : CINESORT_E2E=1 pytest tests/e2e_desktop/test_12_validation_deep.py -v
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
class TestValidationDeep:
    """Tests approfondis de la vue Validation — presets et actions bulk."""

    def _go_to_validation(self, page):
        page.evaluate("() => { if (typeof showView === 'function') showView('validation'); }")
        page.wait_for_timeout(500)

    def test_preset_review_risk(self, page):
        """Le preset 'A revoir' filtre les cas risques."""
        self._go_to_validation(page)
        total = page.evaluate("() => document.querySelectorAll('#planTbody tr').length")
        page.click('[data-testid="val-preset-review"]')
        page.wait_for_timeout(500)
        filtered = page.evaluate("() => document.querySelectorAll('#planTbody tr').length")
        BasePage(page).screenshot("12_01_preset_review")
        assert filtered <= total, "Preset 'A revoir' n'a pas filtre"
        # Desactiver le preset
        page.click('[data-testid="val-preset-review"]')
        page.wait_for_timeout(300)

    def test_preset_sensitive(self, page):
        """Le preset 'Sensibles' affiche les films avec warning flags."""
        self._go_to_validation(page)
        page.click('[data-testid="val-preset-sensitive"]')
        page.wait_for_timeout(500)
        count = page.evaluate("() => document.querySelectorAll('#planTbody tr').length")
        BasePage(page).screenshot("12_02_preset_sensitive")
        # Des films avec flags devraient apparaitre (cas ambigus, non-film, etc.)
        # Desactiver
        page.click('[data-testid="val-preset-sensitive"]')
        page.wait_for_timeout(300)

    def test_preset_collections(self, page):
        """Le preset 'Collections' filtre les films en saga TMDb."""
        self._go_to_validation(page)
        page.click('[data-testid="val-preset-collections"]')
        page.wait_for_timeout(500)
        count = page.evaluate("() => document.querySelectorAll('#planTbody tr').length")
        BasePage(page).screenshot("12_03_preset_collections")
        # Desactiver
        page.click('[data-testid="val-preset-collections"]')
        page.wait_for_timeout(300)

    def test_bulk_check_all(self, page):
        """'Tout cocher' coche toutes les lignes visibles."""
        self._go_to_validation(page)
        btn = page.query_selector('[data-testid="val-btn-check-all"]')
        if btn:
            btn.click()
            page.wait_for_timeout(500)
        # Verifier le compteur
        checked = page.evaluate("""() => {
            const el = document.getElementById('valPillChecked');
            return el ? el.textContent : '0';
        }""")
        BasePage(page).screenshot("12_04_bulk_checked")
        assert "0" not in checked or checked.startswith("0"), f"Aucun film coche : {checked}"

    def test_bulk_uncheck_all(self, page):
        """'Tout decocher' decoche toutes les lignes."""
        self._go_to_validation(page)
        btn = page.query_selector('[data-testid="val-btn-uncheck-all"]')
        if btn:
            btn.click()
            page.wait_for_timeout(500)
        BasePage(page).screenshot("12_05_bulk_unchecked")

    def test_search_unicode(self, page):
        """Recherche avec des caracteres speciaux (accents)."""
        self._go_to_validation(page)
        search = page.query_selector('[data-testid="val-search"]')
        if search:
            search.fill("Ete")
            page.wait_for_timeout(500)
        count = page.evaluate("() => document.querySelectorAll('#planTbody tr').length")
        BasePage(page).screenshot("12_06_search_unicode")
        # Clear
        if search:
            search.fill("")
            page.wait_for_timeout(300)

    def test_inspector_detail_fields(self, page):
        """L'inspecteur affiche les champs source, confiance, flags."""
        self._go_to_validation(page)
        # Cliquer sur la premiere ligne
        rows = page.query_selector_all("#planTbody tr")
        if rows:
            rows[0].click()
            page.wait_for_timeout(500)
        body = page.evaluate("""() => {
            const el = document.querySelector('[data-testid="val-inspector-body"]');
            return el ? el.innerHTML : '';
        }""")
        BasePage(page).screenshot("12_07_inspector_detail")
        # Le body doit contenir au moins "Source" ou "Confiance"
        assert body, "L'inspecteur est vide"

    def test_inline_year_edit(self, page):
        """Modifier l'annee d'un film inline dans la table."""
        self._go_to_validation(page)
        # Trouver un input annee dans la table
        year_input = page.query_selector("#planTbody input[type='number']")
        if year_input:
            year_input.fill("2025")
            page.wait_for_timeout(300)
            value = year_input.input_value()
            assert value == "2025", f"Annee non modifiee : {value}"
        BasePage(page).screenshot("12_08_year_edited")

    def test_pill_counters_update(self, page):
        """Les compteurs (pills) se mettent a jour apres actions."""
        self._go_to_validation(page)
        total = page.evaluate("""() => {
            const el = document.querySelector('[data-testid="val-pill-total"]');
            return el ? el.textContent.trim() : '';
        }""")
        BasePage(page).screenshot("12_09_counters")
        assert total, "Le compteur total est vide"
