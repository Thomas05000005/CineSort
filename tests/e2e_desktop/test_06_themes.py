"""Test E2E desktop — 06. Thèmes et apparence.

Lancer : pytest tests/e2e_desktop/test_06_themes.py -v
"""

from __future__ import annotations


from .pages.parametres_page import ParametresPage
from .pages.base_page import BasePage


class TestThemes:
    """Tests des thèmes et de l'apparence visuelle."""

    def test_default_theme_applied(self, page):
        """Un thème est appliqué au démarrage (correspond aux settings)."""
        params = ParametresPage(page)
        body_theme = params.get_body_theme()
        # Le thème doit être non-vide (un thème est toujours appliqué)
        assert body_theme, "Aucun thème appliqué sur le body"
        # Vérifier que le thème correspond au setting
        setting_theme = page.evaluate("""() => {
            try { return document.getElementById('selTheme')?.value || ''; }
            catch { return ''; }
        }""")
        if setting_theme:
            assert body_theme == setting_theme, f"Thème body ({body_theme}) != setting ({setting_theme})"

    def test_change_theme_to_cinema(self, page):
        """Changer le thème de studio à cinema modifie le data-theme."""
        params = ParametresPage(page)
        params.navigate()
        params.set_theme("cinema")
        page.wait_for_timeout(500)
        theme = params.get_body_theme()
        assert theme == "cinema", f"Thème après changement: {theme}"

    def test_change_theme_to_neon(self, page):
        """Changer le thème vers neon."""
        params = ParametresPage(page)
        params.navigate()
        params.set_theme("neon")
        page.wait_for_timeout(500)
        theme = params.get_body_theme()
        assert theme == "neon", f"Thème après changement: {theme}"

    def test_theme_affects_css_variables(self, page):
        """Le changement de thème modifie les variables CSS (--accent)."""
        params = ParametresPage(page)
        params.navigate()

        # Studio : accent bleu (#60A5FA)
        params.set_theme("studio")
        page.wait_for_timeout(500)
        accent_studio = page.evaluate("() => getComputedStyle(document.body).getPropertyValue('--accent').trim()")

        # Cinema : accent rouge (#E44D6E)
        params.set_theme("cinema")
        page.wait_for_timeout(500)
        accent_cinema = page.evaluate("() => getComputedStyle(document.body).getPropertyValue('--accent').trim()")

        # Les accents doivent être différents entre studio et cinema
        assert accent_studio and accent_cinema, (
            f"Variables CSS vides: studio={accent_studio!r}, cinema={accent_cinema!r}"
        )
        assert accent_studio != accent_cinema, (
            f"Les accents devraient être différents: studio={accent_studio}, cinema={accent_cinema}"
        )

    def test_theme_on_documentelement(self, page):
        """Le data-theme est aussi appliqué sur documentElement (html)."""
        params = ParametresPage(page)
        params.navigate()
        params.set_theme("luxe")
        page.wait_for_timeout(500)
        html_theme = page.evaluate("() => document.documentElement.dataset.theme || ''")
        body_theme = params.get_body_theme()
        assert html_theme == "luxe", f"documentElement.dataset.theme = {html_theme}"
        assert body_theme == "luxe", f"body.dataset.theme = {body_theme}"

    def test_visual_regression_accueil(self, page):
        """Capture un screenshot de l'accueil pour régression visuelle."""
        base = BasePage(page)
        base.navigate_to("home")
        page.wait_for_timeout(1000)
        path = base.screenshot("06_theme_accueil_baseline")
        assert path.endswith(".png")

    def test_restore_studio_theme(self, page):
        """Restaurer le thème studio après les tests."""
        params = ParametresPage(page)
        params.navigate()
        params.set_theme("studio")
        page.wait_for_timeout(300)
        assert params.get_body_theme() == "studio"
