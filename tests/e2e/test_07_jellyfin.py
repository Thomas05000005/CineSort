"""Tests E2E vue Jellyfin du dashboard CineSort.

8 tests : affichage, KPIs, statut connexion, boutons, erreur, screenshot.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

from pages.jellyfin_page import JellyfinPage  # noqa: E402


class TestJellyfin:
    """Tests de la vue Jellyfin."""

    def _jf(self, authenticated_page, e2e_server) -> JellyfinPage:
        jp = JellyfinPage(authenticated_page, e2e_server["url"])
        jp.navigate()
        return jp

    def test_view_loads(self, authenticated_page, e2e_server):
        """La vue Jellyfin se charge sans erreur JS fatale."""
        jp = self._jf(authenticated_page, e2e_server)
        text = jp.get_content_text()
        assert len(text) > 10, f"Contenu Jellyfin trop court : {text}"

    def test_kpi_cards_present(self, authenticated_page, e2e_server):
        """Des KPI cards sont rendues."""
        jp = self._jf(authenticated_page, e2e_server)
        # Soit des KPI, soit le message "non configure"
        has_kpi = jp.has_kpi_cards()
        has_msg = jp.is_disabled_message_shown()
        assert has_kpi or has_msg, "Ni KPIs ni message affiche"

    def test_connection_status_shown(self, authenticated_page, e2e_server):
        """Le statut de connexion est affiche."""
        jp = self._jf(authenticated_page, e2e_server)
        text = jp.get_content_text().lower()
        # Soit connecte/deconnecte, soit erreur, soit "non configure"
        has_status = any(s in text for s in ["connect", "deconnect", "erreur", "non configure", "statut"])
        assert has_status, f"Pas de statut dans : {text[:200]}"

    def test_error_graceful(self, authenticated_page, e2e_server):
        """L'erreur de connexion Jellyfin (faux URL) ne crashe pas la page."""
        jp = self._jf(authenticated_page, e2e_server)
        # La page doit afficher du contenu (pas vide, pas de page vide)
        text = jp.get_content_text()
        assert len(text) > 10
        # Verifier qu'il n'y a pas de stacktrace JS visible
        assert "uncaught" not in text.lower()
        assert "typeerror" not in text.lower()

    def test_server_name_in_content(self, authenticated_page, e2e_server):
        """Le nom du serveur est mentionne quelque part (ou '--' si deconnecte)."""
        jp = self._jf(authenticated_page, e2e_server)
        text = jp.get_content_text()
        # KPI "Serveur" avec une valeur
        assert "Serveur" in text or "serveur" in text.lower() or "non configure" in text.lower()

    def test_version_in_content(self, authenticated_page, e2e_server):
        """La version est mentionnee (ou '--')."""
        jp = self._jf(authenticated_page, e2e_server)
        text = jp.get_content_text()
        assert "Version" in text or "version" in text.lower() or "non configure" in text.lower()

    def test_libraries_or_disabled(self, authenticated_page, e2e_server):
        """La section libraries est presente OU le message 'non configure'."""
        jp = self._jf(authenticated_page, e2e_server)
        has_lib = jp.has_libraries_section()
        has_disabled = jp.is_disabled_message_shown()
        assert has_lib or has_disabled

    def test_screenshot_jellyfin(self, authenticated_page, e2e_server):
        """Screenshot de la vue Jellyfin."""
        jp = self._jf(authenticated_page, e2e_server)
        path = jp.take_screenshot("jellyfin_page")
        assert path.exists()
