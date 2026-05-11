"""Test E2E desktop — 05. Application (apply / undo).

Lancer : pytest tests/e2e_desktop/test_05_apply.py -v
"""

from __future__ import annotations


from .pages.base_page import BasePage


class TestApply:
    """Tests de l'application des decisions (dry-run, apply, undo)."""

    def test_execution_view_accessible(self, page):
        """La vue Exécution (legacy) est accessible."""
        base = BasePage(page)
        page.evaluate("() => { if (typeof showView === 'function') showView('execution'); }")
        page.wait_for_timeout(500)
        active = base.get_active_view()
        assert active == "execution", f"Vue active: {active}"

    def test_dryrun_toggle_exists(self, page):
        """Le toggle dry-run existe dans la vue Exécution."""
        page.evaluate("() => { if (typeof showView === 'function') showView('execution'); }")
        page.wait_for_timeout(500)
        assert page.is_visible('[data-testid="exec-ck-dryrun"]'), "Toggle dry-run absent"

    def test_apply_button_exists(self, page):
        """Le bouton Appliquer existe."""
        page.evaluate("() => { if (typeof showView === 'function') showView('execution'); }")
        page.wait_for_timeout(500)
        assert page.is_visible('[data-testid="exec-btn-apply"]'), "Bouton apply absent"

    def test_undo_button_exists(self, page):
        """Les boutons undo existent."""
        page.evaluate("() => { if (typeof showView === 'function') showView('execution'); }")
        page.wait_for_timeout(500)
        assert page.is_visible('[data-testid="exec-btn-undo-preview"]'), "Bouton undo preview absent"

    def test_execution_screenshot(self, page):
        """Capture de la vue Exécution."""
        base = BasePage(page)
        page.evaluate("() => { if (typeof showView === 'function') showView('execution'); }")
        page.wait_for_timeout(500)
        base.screenshot("05_execution")
