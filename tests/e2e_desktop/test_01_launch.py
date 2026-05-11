"""Test E2E desktop — 01. Lancement de l'application.

Prerequis : CINESORT_E2E=1 et l'app lancee via conftest.py.
Lancer : pytest tests/e2e_desktop/test_01_launch.py -v
"""

from __future__ import annotations


from .pages.base_page import BasePage
from .pages.accueil_page import AccueilPage


class TestAppLaunch:
    """Tests de lancement et d'initialisation."""

    def test_app_starts(self, page):
        """L'app se lance sans crash et __APP_READY__ est True."""
        ready = page.evaluate("() => window.__APP_READY__")
        assert ready is True, "L'app n'est pas prete (__APP_READY__ != true)"

    def test_sidebar_visible(self, page):
        """Les 8 onglets de navigation sont visibles."""
        base = BasePage(page)
        nav_buttons = base.get_nav_buttons()
        assert len(nav_buttons) == 8, f"Attendu 8 onglets, trouve {len(nav_buttons)}: {nav_buttons}"
        expected = {"home", "library", "quality", "jellyfin", "plex", "radarr", "logs", "settings"}
        # Jellyfin/Plex/Radarr peuvent etre masques si desactives
        visible = set(nav_buttons)
        core = {"home", "library", "quality", "logs", "settings"}
        assert core.issubset(visible), f"Onglets manquants: {core - visible}"

    def test_accueil_loaded(self, page):
        """La vue Accueil est chargee avec les KPIs (meme si vides)."""
        accueil = AccueilPage(page)
        accueil.navigate()
        # Les KPIs doivent exister (meme avec "—")
        kpis = accueil.get_kpis()
        assert "films" in kpis
        assert "score" in kpis

    def test_accueil_screenshot(self, page):
        """Capture un screenshot de la vue Accueil."""
        accueil = AccueilPage(page)
        accueil.navigate()
        path = accueil.screenshot("01_accueil")
        assert path.endswith(".png")
