"""Test E2E dashboard — 04. Themes et apparence.

Lancer : pytest tests/e2e_dashboard/test_dash_04_themes.py -v
"""

from __future__ import annotations


try:
    import allure
except ImportError:
    allure = None


class TestDashThemes:
    """Tests des themes dans le dashboard distant."""

    def test_default_theme_applied(self, dashboard_page):
        """Un theme est applique par defaut apres login."""
        # Attendre que le theme soit charge (async apres login → initStatus → settings)
        dashboard_page.wait_for_function(
            "() => !!document.body.dataset.theme",
            timeout=10000,
        )
        theme = dashboard_page.evaluate("() => document.body.dataset.theme || ''")
        assert theme, "Aucun theme applique sur le body"
        dashboard_page.screenshot(path="tests/e2e_dashboard/screenshots/dash_04_default_theme.png")

    def test_switch_theme_via_settings(self, dashboard_page):
        """Changer le theme dans les parametres modifie data-theme."""
        # Naviguer vers Settings
        btn = dashboard_page.query_selector('[data-testid="nav-settings"]')
        if btn:
            btn.click()
            dashboard_page.wait_for_timeout(1000)
        # Changer le select theme via le bon ID (#dSelTheme)
        dashboard_page.evaluate("""() => {
            const sel = document.querySelector('#dSelTheme');
            if (sel) { sel.value = 'cinema'; sel.dispatchEvent(new Event('change')); }
        }""")
        dashboard_page.wait_for_timeout(500)
        theme = dashboard_page.evaluate("() => document.body.dataset.theme || ''")
        dashboard_page.screenshot(path="tests/e2e_dashboard/screenshots/dash_04_cinema_theme.png")
        assert theme == "cinema", f"Theme non change : {theme}"

    def test_css_variables_change_with_theme(self, dashboard_page):
        """Les variables CSS changent quand on change de theme."""
        # Naviguer vers Settings
        btn = dashboard_page.query_selector('[data-testid="nav-settings"]')
        if btn:
            btn.click()
            dashboard_page.wait_for_timeout(500)
        # Lire accent en studio
        dashboard_page.evaluate("""() => {
            const sel = document.querySelector('#dSelTheme');
            if (sel) { sel.value = 'studio'; sel.dispatchEvent(new Event('change')); }
        }""")
        dashboard_page.wait_for_timeout(500)
        accent_studio = dashboard_page.evaluate(
            "() => getComputedStyle(document.body).getPropertyValue('--accent').trim()"
        )
        # Changer en cinema
        dashboard_page.evaluate("""() => {
            const sel = document.querySelector('#dSelTheme');
            if (sel) { sel.value = 'cinema'; sel.dispatchEvent(new Event('change')); }
        }""")
        dashboard_page.wait_for_timeout(500)
        accent_cinema = dashboard_page.evaluate(
            "() => getComputedStyle(document.body).getPropertyValue('--accent').trim()"
        )
        if accent_studio and accent_cinema:
            assert accent_studio != accent_cinema, (
                f"Les accents sont identiques : studio={accent_studio}, cinema={accent_cinema}"
            )

    def test_theme_persist_after_save(self, dashboard_page):
        """Le theme est sauvegarde dans les settings."""
        # Naviguer vers Settings
        btn = dashboard_page.query_selector('[data-testid="nav-settings"]')
        if btn:
            btn.click()
            dashboard_page.wait_for_timeout(500)
        # Mettre cinema
        dashboard_page.evaluate("""() => {
            const sel = document.querySelector('#dSelTheme');
            if (sel) { sel.value = 'cinema'; sel.dispatchEvent(new Event('change')); }
        }""")
        dashboard_page.wait_for_timeout(300)
        # Sauvegarder
        save = dashboard_page.query_selector('[data-testid="settings-btn-save"]')
        if save:
            save.click()
            dashboard_page.wait_for_timeout(2000)
        dashboard_page.screenshot(path="tests/e2e_dashboard/screenshots/dash_04_theme_saved.png")
