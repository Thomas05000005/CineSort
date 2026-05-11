"""Test E2E dashboard — 05. Synchronisation et coherence des donnees.

Lancer : pytest tests/e2e_dashboard/test_dash_05_sync_realtime.py -v
"""

from __future__ import annotations


class TestDashSync:
    """Tests de coherence des donnees et refresh du dashboard."""

    def test_refresh_button_reloads_data(self, dashboard_page):
        """Le bouton refresh recharge les donnees sans erreur JS."""
        errors = []
        dashboard_page.on("pageerror", lambda err: errors.append(str(err)))

        dashboard_page.click('[data-testid="nav-status"]')
        dashboard_page.wait_for_timeout(1000)

        refresh = dashboard_page.query_selector('[data-testid="btn-refresh"]')
        assert refresh is not None, "Bouton refresh absent"
        refresh.click()
        dashboard_page.wait_for_timeout(2000)
        assert not errors, f"Erreurs JS pendant le refresh: {errors}"

    def test_status_shows_kpi_cards(self, dashboard_page):
        """La page Status affiche des cartes KPI avec des valeurs."""
        dashboard_page.click('[data-testid="nav-status"]')
        dashboard_page.wait_for_timeout(1500)
        kpis = dashboard_page.evaluate("""() => {
            const cards = document.querySelectorAll('.kpi-card');
            return Array.from(cards).map(c => ({
                label: c.querySelector('.kpi-label')?.textContent || '',
                value: c.querySelector('.kpi-value')?.textContent || '',
            }));
        }""")
        assert len(kpis) >= 3, f"Pas assez de KPI : {len(kpis)}"
        for kpi in kpis:
            assert kpi["value"], f"KPI sans valeur : {kpi['label']}"

    def test_status_shows_health_section(self, dashboard_page):
        """La page Status a une section sante avec des indicateurs."""
        dashboard_page.click('[data-testid="nav-status"]')
        dashboard_page.wait_for_timeout(1500)
        health_items = dashboard_page.evaluate("""() => {
            return document.querySelectorAll('.status-health-list li').length;
        }""")
        assert health_items >= 2, f"Pas assez d'indicateurs sante : {health_items}"

    def test_data_consistency_status_vs_library(self, dashboard_page):
        """Le nombre de films dans le KPI Status est >= au nombre en table Library."""
        # Extraire le KPI films depuis Status
        dashboard_page.click('[data-testid="nav-status"]')
        dashboard_page.wait_for_timeout(1500)
        kpi_films = dashboard_page.evaluate("""() => {
            const cards = document.querySelectorAll('.kpi-card');
            for (const c of cards) {
                const label = (c.querySelector('.kpi-label')?.textContent || '').toLowerCase();
                if (label.includes('film')) {
                    return parseInt(c.querySelector('.kpi-value')?.textContent || '0', 10);
                }
            }
            return -1;
        }""")
        # Compter les films dans la table Library
        dashboard_page.click('[data-testid="nav-library"]')
        dashboard_page.wait_for_timeout(1000)
        dashboard_page.click('[data-testid="lib-step-validation"]')
        dashboard_page.wait_for_timeout(2000)
        table_count = dashboard_page.evaluate("""() => {
            const table = document.querySelector('[data-testid="lib-valid-table"]');
            return table ? table.querySelectorAll('tbody tr').length : 0;
        }""")
        if kpi_films >= 0:
            assert kpi_films >= table_count, f"KPI films ({kpi_films}) < table ({table_count})"

    def test_quality_view_has_content(self, dashboard_page):
        """La vue Qualite charge et affiche des donnees."""
        errors = []
        dashboard_page.on("pageerror", lambda err: errors.append(str(err)))

        dashboard_page.click('[data-testid="nav-quality"]')
        dashboard_page.wait_for_timeout(1500)
        content_len = dashboard_page.evaluate("""() => {
            const el = document.getElementById('qualityContent');
            return el ? el.textContent.trim().length : 0;
        }""")
        assert content_len > 50, f"La vue Qualite est trop vide : {content_len} chars"
        assert not errors, f"Erreurs JS dans la vue Qualite : {errors}"

    def test_settings_view_loads(self, dashboard_page):
        """La vue Parametres charge toutes les sections."""
        dashboard_page.click('[data-testid="nav-settings"]')
        dashboard_page.wait_for_timeout(1500)
        content_len = dashboard_page.evaluate("""() => {
            const el = document.getElementById('settingsContent');
            return el ? el.textContent.trim().length : 0;
        }""")
        assert content_len > 100, f"La vue Parametres est trop vide : {content_len} chars"

    def test_logs_view_loads(self, dashboard_page):
        """La vue Journaux charge sans erreur."""
        errors = []
        dashboard_page.on("pageerror", lambda err: errors.append(str(err)))

        dashboard_page.click('[data-testid="nav-logs"]')
        dashboard_page.wait_for_timeout(1500)
        # La vue doit avoir un contenu (meme si pas de logs actifs)
        has_content = dashboard_page.evaluate("""() => {
            const el = document.getElementById('logsContent');
            return el ? el.children.length > 0 : false;
        }""")
        assert has_content, "La vue Journaux est vide"
        assert not errors, f"Erreurs JS dans la vue Journaux : {errors}"

    def test_no_console_errors_across_all_views(self, dashboard_page):
        """Naviguer dans toutes les vues ne produit aucune erreur JS."""
        errors = []
        dashboard_page.on("pageerror", lambda err: errors.append(str(err)))

        for tab in ["status", "library", "quality", "logs", "settings"]:
            dashboard_page.click(f'[data-testid="nav-{tab}"]')
            dashboard_page.wait_for_timeout(1000)

        assert not errors, f"Erreurs JS lors de la navigation: {errors}"
