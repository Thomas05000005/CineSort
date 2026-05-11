"""Test E2E dashboard — 02. Navigation entre les vues.

Lancer : pytest tests/e2e_dashboard/test_dash_02_navigation.py -v
"""

from __future__ import annotations


_NAV_TABS = ["status", "library", "quality", "jellyfin", "plex", "radarr", "logs", "settings"]


class TestDashNavigation:
    """Tests de navigation dans le dashboard distant."""

    def test_all_nav_buttons_present(self, dashboard_page):
        """Les 8 boutons de navigation sont presents dans le DOM."""
        for tab in _NAV_TABS:
            exists = dashboard_page.evaluate(f"""() => {{
                return !!document.querySelector('[data-testid="nav-{tab}"]');
            }}""")
            assert exists, f"Bouton nav-{tab} absent du DOM"

    def test_required_tabs_visible(self, dashboard_page):
        """Les 5 onglets principaux sont visibles."""
        for tab in ["status", "library", "quality", "logs", "settings"]:
            assert dashboard_page.is_visible(f'[data-testid="nav-{tab}"]'), f"Bouton nav-{tab} non visible"

    def test_navigate_to_each_view(self, dashboard_page):
        """Chaque navigation change le hash et affiche la vue."""
        errors = []
        dashboard_page.on("pageerror", lambda err: errors.append(str(err)))

        for tab in ["status", "library", "quality", "logs", "settings"]:
            dashboard_page.click(f'[data-testid="nav-{tab}"]')
            dashboard_page.wait_for_timeout(800)
            hash_val = dashboard_page.evaluate("() => window.location.hash")
            assert f"/{tab}" in hash_val, f"Navigation vers {tab} echouee: hash={hash_val}"

        assert not errors, f"Erreurs JS pendant la navigation: {errors}"

    def test_library_workflow_steps(self, dashboard_page):
        """La vue Bibliotheque affiche les 5 etapes du workflow."""
        dashboard_page.click('[data-testid="nav-library"]')
        dashboard_page.wait_for_timeout(1000)
        expected_steps = ["analyse", "verification", "validation", "doublons", "application"]
        for step in expected_steps:
            exists = dashboard_page.evaluate(f"""() => {{
                return !!document.querySelector('[data-testid="lib-step-{step}"]');
            }}""")
            assert exists, f"Etape workflow '{step}' absente"

    def test_active_nav_state_changes(self, dashboard_page):
        """Le bouton de navigation actif change quand on navigue."""
        # Status doit etre actif au depart
        is_active = dashboard_page.evaluate("""() => {
            const btn = document.querySelector('[data-testid="nav-status"]');
            return btn?.getAttribute('aria-selected') === 'true' || btn?.classList.contains('active');
        }""")
        assert is_active, "nav-status n'est pas actif au depart"

        # Naviguer vers library
        dashboard_page.click('[data-testid="nav-library"]')
        dashboard_page.wait_for_timeout(500)

        # Library doit etre actif, status inactif
        lib_active = dashboard_page.evaluate("""() => {
            const btn = document.querySelector('[data-testid="nav-library"]');
            return btn?.getAttribute('aria-selected') === 'true' || btn?.classList.contains('active');
        }""")
        assert lib_active, "nav-library n'est pas actif apres navigation"

        status_inactive = dashboard_page.evaluate("""() => {
            const btn = document.querySelector('[data-testid="nav-status"]');
            return btn?.getAttribute('aria-selected') !== 'true' && !btn?.classList.contains('active');
        }""")
        assert status_inactive, "nav-status devrait etre inactif"

    def test_keyboard_shortcut_navigation(self, dashboard_page):
        """Les raccourcis clavier numeriques changent de vue."""
        dashboard_page.keyboard.press("2")
        dashboard_page.wait_for_timeout(500)
        hash_val = dashboard_page.evaluate("() => window.location.hash")
        assert "/library" in hash_val, f"Touche 2 devrait aller vers library: {hash_val}"

    def test_escape_closes_modal_if_open(self, dashboard_page):
        """Echap ferme une modale ouverte sans changer de vue."""
        dashboard_page.click('[data-testid="nav-library"]')
        dashboard_page.wait_for_timeout(800)
        # Le hash avant
        hash_before = dashboard_page.evaluate("() => window.location.hash")
        dashboard_page.keyboard.press("Escape")
        dashboard_page.wait_for_timeout(300)
        hash_after = dashboard_page.evaluate("() => window.location.hash")
        assert hash_before == hash_after, "Escape ne devrait pas changer de vue"
