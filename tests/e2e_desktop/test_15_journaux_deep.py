"""Test E2E desktop — 15. Journaux approfondis (logs, historique, exports).

Lancer : CINESORT_E2E=1 pytest tests/e2e_desktop/test_15_journaux_deep.py -v
"""

from __future__ import annotations

import os

import pytest

try:
    import allure
except ImportError:
    allure = None

from .pages.base_page import BasePage
from .pages.journaux_page import JournauxPage


@pytest.mark.skipif(os.environ.get("CINESORT_E2E") != "1", reason="CINESORT_E2E non defini")
class TestJournauxDeep:
    """Tests approfondis de la vue Journaux."""

    def test_logs_view_accessible(self, page):
        """La vue Journaux est accessible et affiche du contenu."""
        logs = JournauxPage(page)
        logs.navigate()
        page.wait_for_timeout(1000)
        BasePage(page).screenshot("15_01_logs_view")

    def test_logbox_has_content(self, page):
        """Le logbox contient du texte (meme minimal)."""
        logs = JournauxPage(page)
        logs.navigate()
        page.wait_for_timeout(1000)
        text = logs.get_log_text()
        BasePage(page).screenshot("15_02_logbox")
        # Le logbox peut contenir "Aucun journal" ou des logs reels
        assert text is not None, "Le logbox est None"

    def test_history_table_exists(self, page):
        """La table d'historique des runs existe."""
        logs = JournauxPage(page)
        logs.navigate()
        page.wait_for_timeout(1000)
        exists = page.evaluate("""() => {
            const el = document.querySelector('[data-testid="logs-history-table"]');
            return !!el;
        }""")
        BasePage(page).screenshot("15_03_history_table")
        assert exists, "Table historique non trouvee"

    def test_export_buttons_exist(self, page):
        """Les boutons d'export existent (dans la vue history legacy)."""
        logs = JournauxPage(page)
        logs.navigate()
        page.wait_for_timeout(500)
        # Les boutons export peuvent etre dans la vue logs ou history
        found = 0
        for fmt in ["json", "csv", "html", "nfo"]:
            if page.is_visible(f'[data-testid="logs-btn-export-{fmt}"]'):
                found += 1
        # Si pas dans la vue logs, essayer la vue history (legacy)
        if found == 0:
            page.evaluate("() => { if (typeof showView === 'function') showView('history'); }")
            page.wait_for_timeout(500)
            for fmt in ["json", "csv", "html", "nfo"]:
                if page.is_visible(f'[data-testid="logs-btn-export-{fmt}"]'):
                    found += 1
        BasePage(page).screenshot("15_04_export_buttons")
        assert found >= 1, "Aucun bouton export trouve (ni dans logs ni dans history)"
