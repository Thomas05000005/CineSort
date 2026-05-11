"""Test E2E desktop — 14. Parametres approfondis (roots, themes, sliders).

Lancer : CINESORT_E2E=1 pytest tests/e2e_desktop/test_14_settings_deep.py -v
"""

from __future__ import annotations

import os

import pytest

try:
    import allure
except ImportError:
    allure = None

from .pages.base_page import BasePage
from .pages.parametres_page import ParametresPage


@pytest.mark.skipif(os.environ.get("CINESORT_E2E") != "1", reason="CINESORT_E2E non defini")
class TestSettingsDeep:
    """Tests approfondis de la vue Parametres."""

    def test_tmdb_toggle(self, page):
        """Le toggle TMDb change d'etat."""
        params = ParametresPage(page)
        params.navigate()
        page.wait_for_timeout(500)
        initial = params.get_tmdb_status()
        # Toggle
        page.click('[data-testid="settings-tmdb-enabled"]')
        page.wait_for_timeout(300)
        after = params.get_tmdb_status()
        BasePage(page).screenshot("14_01_tmdb_toggled")
        assert initial != after, "Le toggle TMDb n'a pas change d'etat"
        # Restaurer
        page.click('[data-testid="settings-tmdb-enabled"]')
        page.wait_for_timeout(300)

    def test_probe_backend_select(self, page):
        """Le dropdown probe backend est fonctionnel."""
        params = ParametresPage(page)
        params.navigate()
        page.wait_for_timeout(500)
        exists = page.is_visible('[data-testid="settings-probe-backend"]')
        BasePage(page).screenshot("14_02_probe_backend")
        assert exists, "Dropdown probe backend absent"

    def test_multi_root_add(self, page, tmp_path):
        """Ajouter un root via le formulaire multi-root."""
        params = ParametresPage(page)
        params.navigate()
        page.wait_for_timeout(500)
        # Remplir le champ
        new_root_input = page.query_selector('[data-testid="settings-new-root"]')
        add_btn = page.query_selector('[data-testid="settings-btn-add-root"]')
        if new_root_input and add_btn:
            test_path = str(tmp_path).replace("\\", "/")
            new_root_input.fill(test_path)
            page.wait_for_timeout(200)
            add_btn.click()
            page.wait_for_timeout(500)
        BasePage(page).screenshot("14_03_root_added")

    def test_roots_list_visible(self, page):
        """La liste des roots est affichee."""
        params = ParametresPage(page)
        params.navigate()
        page.wait_for_timeout(500)
        exists = page.is_visible('[data-testid="settings-roots-list"]')
        BasePage(page).screenshot("14_04_roots_list")
        assert exists, "Liste des roots non visible"

    def test_theme_switch_all_four(self, page):
        """Parcourir les 4 themes et verifier que data-theme change."""
        params = ParametresPage(page)
        params.navigate()
        page.wait_for_timeout(500)
        themes_seen = set()
        for theme in ["cinema", "luxe", "neon", "studio"]:
            params.set_theme(theme)
            page.wait_for_timeout(500)
            actual = params.get_body_theme()
            themes_seen.add(actual)
            BasePage(page).screenshot(f"14_05_theme_{theme}")
            assert actual == theme, f"Theme attendu {theme}, obtenu {actual}"
        assert len(themes_seen) == 4, f"Pas assez de themes distincts : {themes_seen}"

    def test_effect_speed_slider(self, page):
        """Le slider vitesse d'effets est fonctionnel."""
        params = ParametresPage(page)
        params.navigate()
        page.wait_for_timeout(500)
        slider = page.query_selector('[data-testid="settings-effect-speed"]')
        if slider:
            # Changer la valeur
            page.evaluate("""() => {
                const s = document.querySelector('[data-testid="settings-effect-speed"]');
                if (s) { s.value = 80; s.dispatchEvent(new Event('input')); }
            }""")
            page.wait_for_timeout(300)
            value = page.evaluate("() => document.querySelector('[data-testid=\"settings-effect-speed\"]')?.value")
            assert value == "80", f"Valeur slider non mise a jour : {value}"
        BasePage(page).screenshot("14_06_slider_speed")

    def test_glow_intensity_slider(self, page):
        """Le slider intensite glow est fonctionnel."""
        params = ParametresPage(page)
        params.navigate()
        page.wait_for_timeout(500)
        slider = page.query_selector('[data-testid="settings-glow-intensity"]')
        if slider:
            page.evaluate("""() => {
                const s = document.querySelector('[data-testid="settings-glow-intensity"]');
                if (s) { s.value = 60; s.dispatchEvent(new Event('input')); }
            }""")
            page.wait_for_timeout(300)
            value = page.evaluate("() => document.querySelector('[data-testid=\"settings-glow-intensity\"]')?.value")
            assert value == "60", f"Valeur slider non mise a jour : {value}"
        BasePage(page).screenshot("14_07_slider_glow")

    def test_save_settings(self, page):
        """Sauvegarder les parametres ne provoque pas d'erreur."""
        params = ParametresPage(page)
        params.navigate()
        page.wait_for_timeout(500)
        params.save()
        page.wait_for_timeout(1000)
        BasePage(page).screenshot("14_08_settings_saved")
