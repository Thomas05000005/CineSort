"""Tests E2E erreurs console JS — aucune erreur inattendue.

7 tests : chaque vue + cycle complet.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

from pages.base_page import BasePage  # noqa: E402

# Patterns d'erreurs attendues (connexion Jellyfin fake, etc.)
_EXPECTED_PATTERNS = [
    "[jellyfin]",  # erreur connexion Jellyfin (URL fake)
    "fetch",  # erreur reseau
    "ERR_CONNECTION_REFUSED",
    "Failed to fetch",
    "NetworkError",
]


def _is_expected_error(msg: str) -> bool:
    """Verifie si une erreur console est attendue (pas un vrai bug)."""
    return any(pat.lower() in msg.lower() for pat in _EXPECTED_PATTERNS)


def _collect_and_auth(page, e2e_server) -> list:
    """Login, collecte les erreurs console, retourne la liste."""
    errors = []

    def _on_console(msg):
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", _on_console)

    page.goto(e2e_server["dashboard_url"])
    page.wait_for_selector("#loginToken", timeout=5000)
    page.fill("#loginToken", e2e_server["token"])
    page.click("#loginBtn")
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)
    return errors


def _filter_unexpected(errors: list) -> list:
    """Filtre les erreurs inattendues (pas de connexion Jellyfin, etc.)."""
    return [e for e in errors if not _is_expected_error(e)]


class TestConsoleErrors:
    """Verifier 0 erreur JS inattendue dans la console."""

    def test_login_no_errors(self, page, e2e_server):
        """Page login → 0 erreur JS."""
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.goto(e2e_server["dashboard_url"])
        page.wait_for_timeout(2000)
        unexpected = _filter_unexpected(errors)
        assert not unexpected, f"Erreurs console sur login : {unexpected}"

    def test_status_no_errors(self, page, e2e_server):
        """Vue status → 0 erreur JS inattendue."""
        errors = _collect_and_auth(page, e2e_server)
        bp = BasePage(page, e2e_server["url"])
        bp.navigate_to("status")
        page.wait_for_timeout(2000)
        unexpected = _filter_unexpected(errors)
        assert not unexpected, f"Erreurs console sur status : {unexpected}"

    def test_library_no_errors(self, page, e2e_server):
        """Vue library → 0 erreur JS inattendue."""
        errors = _collect_and_auth(page, e2e_server)
        bp = BasePage(page, e2e_server["url"])
        bp.navigate_to("library")
        page.wait_for_timeout(2000)
        unexpected = _filter_unexpected(errors)
        assert not unexpected, f"Erreurs console sur library : {unexpected}"

    def test_runs_no_errors(self, page, e2e_server):
        """Vue runs → 0 erreur JS inattendue."""
        errors = _collect_and_auth(page, e2e_server)
        bp = BasePage(page, e2e_server["url"])
        bp.navigate_to("runs")
        page.wait_for_timeout(2000)
        unexpected = _filter_unexpected(errors)
        assert not unexpected, f"Erreurs console sur runs : {unexpected}"

    def test_review_no_errors(self, page, e2e_server):
        """Vue review → 0 erreur JS inattendue."""
        errors = _collect_and_auth(page, e2e_server)
        bp = BasePage(page, e2e_server["url"])
        bp.navigate_to("review")
        page.wait_for_timeout(4000)
        unexpected = _filter_unexpected(errors)
        assert not unexpected, f"Erreurs console sur review : {unexpected}"

    def test_jellyfin_no_unexpected_errors(self, page, e2e_server):
        """Vue jellyfin → 0 erreur JS inattendue (erreur connexion attendue)."""
        errors = _collect_and_auth(page, e2e_server)
        bp = BasePage(page, e2e_server["url"])
        bp.navigate_to("jellyfin")
        page.wait_for_timeout(3000)
        unexpected = _filter_unexpected(errors)
        assert not unexpected, f"Erreurs console inattendues sur jellyfin : {unexpected}"

    def test_full_navigation_cycle(self, page, e2e_server):
        """Cycle complet (toutes les vues) → 0 erreur inattendue."""
        errors = _collect_and_auth(page, e2e_server)
        bp = BasePage(page, e2e_server["url"])
        for route in ["status", "library", "runs", "review", "jellyfin", "logs", "status"]:
            bp.navigate_to(route)
            page.wait_for_timeout(1500)
        unexpected = _filter_unexpected(errors)
        assert not unexpected, f"Erreurs console pendant le cycle : {unexpected}"
