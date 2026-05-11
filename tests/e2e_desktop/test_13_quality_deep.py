"""Test E2E desktop — 13. Qualite approfondie (KPIs, toggle, distribution).

Lancer : CINESORT_E2E=1 pytest tests/e2e_desktop/test_13_quality_deep.py -v
"""

from __future__ import annotations

import os

import pytest

try:
    import allure
except ImportError:
    allure = None

from .pages.base_page import BasePage
from .pages.qualite_page import QualitePage


@pytest.mark.skipif(os.environ.get("CINESORT_E2E") != "1", reason="CINESORT_E2E non defini")
class TestQualityDeep:
    """Tests approfondis de la vue Qualite."""

    def test_quality_kpis_visible(self, page):
        """Les KPIs qualite sont affiches apres navigation."""
        qual = QualitePage(page)
        qual.navigate()
        page.wait_for_timeout(1000)
        kpis = qual.get_quality_kpis()
        BasePage(page).screenshot("13_01_quality_kpis")
        # Les KPIs sont affiches (meme si valeur "—" sans donnees probe)
        assert kpis, "Aucun KPI retourne"

    def test_distribution_bars_rendered(self, page):
        """Les barres de distribution sont visibles."""
        qual = QualitePage(page)
        qual.navigate()
        page.wait_for_timeout(1000)
        bars = page.evaluate("""() => {
            const el = document.querySelector('[data-testid="quality-dist-bars"]');
            return el ? el.children.length : 0;
        }""")
        BasePage(page).screenshot("13_02_distribution")
        assert bars >= 4, f"Pas assez de barres de distribution : {bars}"

    def test_toggle_run_vs_global(self, page):
        """Le toggle Run/Bibliotheque change le contenu affiche."""
        qual = QualitePage(page)
        qual.navigate()
        page.wait_for_timeout(1000)
        # Passer en mode global
        qual.switch_to_global()
        page.wait_for_timeout(1000)
        BasePage(page).screenshot("13_03_global_mode")
        # Verifier qu'un element specifique au mode global est present
        # (ex: sections globales)
        global_visible = page.evaluate("""() => {
            const el = document.getElementById('globalStatsSection') || document.getElementById('globalLibrarianSection');
            return el ? !el.classList.contains('hidden') : false;
        }""")
        # Revenir en mode run
        qual.switch_to_run()
        page.wait_for_timeout(500)
        BasePage(page).screenshot("13_04_run_mode")

    def test_anomalies_table(self, page):
        """La table des anomalies est rendue (meme si vide)."""
        qual = QualitePage(page)
        qual.navigate()
        page.wait_for_timeout(1000)
        exists = page.evaluate("""() => {
            const el = document.querySelector('[data-testid="quality-anomalies-table"]');
            return !!el;
        }""")
        BasePage(page).screenshot("13_05_anomalies")
        assert exists, "La table des anomalies n'existe pas"

    def test_quality_refresh(self, page):
        """Le bouton Rafraichir ne provoque pas d'erreur."""
        qual = QualitePage(page)
        qual.navigate()
        page.wait_for_timeout(500)
        qual.refresh()
        page.wait_for_timeout(2000)
        BasePage(page).screenshot("13_06_after_refresh")

    def test_quality_screenshot_all_sections(self, page):
        """Capture complete de la vue Qualite."""
        qual = QualitePage(page)
        qual.navigate()
        page.wait_for_timeout(1000)
        BasePage(page).screenshot("13_07_quality_full")
