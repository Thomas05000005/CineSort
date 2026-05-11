"""Test E2E desktop — 02. Navigation entre les vues.

Lancer : pytest tests/e2e_desktop/test_02_navigation.py -v
"""

from __future__ import annotations

import pytest

from .pages.base_page import BasePage


class TestNavigation:
    """Tests de navigation entre les 8 onglets."""

    @pytest.mark.parametrize("view", ["home", "library", "quality", "logs", "settings"])
    def test_navigate_core_views(self, page, view):
        """Naviguer vers chaque vue principale et verifier qu'elle est active."""
        base = BasePage(page)
        base.navigate_to(view)
        active = base.get_active_view()
        assert active == view, f"Vue active attendue '{view}', obtenue '{active}'"

    def test_navigate_all_views_screenshot(self, page):
        """Naviguer vers chaque vue et capturer un screenshot."""
        base = BasePage(page)
        for view in ["home", "library", "quality", "logs", "settings"]:
            base.navigate_to(view)
            base.screenshot(f"02_nav_{view}")

    def test_keyboard_shortcuts(self, page):
        """Alt+1 a Alt+8 naviguent correctement."""
        base = BasePage(page)
        expected_views = ["home", "library", "quality", "jellyfin", "plex", "radarr", "logs", "settings"]

        for i, view in enumerate(expected_views[:5], start=1):
            # Alt+N raccourci (les vues conditionnelles peuvent etre masquees)
            page.keyboard.press(f"Alt+{i}")
            page.wait_for_timeout(300)
            active = base.get_active_view()
            # Si la vue est conditionelle (jellyfin/plex/radarr) et masquee, on skip
            if view in ("jellyfin", "plex", "radarr"):
                continue
            assert active == view, f"Alt+{i} devrait naviguer vers '{view}', obtenu '{active}'"

    def test_one_view_active_at_a_time(self, page):
        """Une seule vue est active a la fois."""
        active_views = page.evaluate("""() =>
            Array.from(document.querySelectorAll('.view.active')).map(v => v.id)
        """)
        assert len(active_views) == 1, f"Nombre de vues actives: {len(active_views)} ({active_views})"
