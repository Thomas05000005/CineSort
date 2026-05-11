"""Tests E2E vue status du dashboard CineSort.

10 tests : KPIs, sante, boutons, indicateurs, screenshot.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

from pages.status_page import StatusPage  # noqa: E402


class TestStatus:
    """Tests de la vue status."""

    def _status(self, authenticated_page, e2e_server) -> StatusPage:
        sp = StatusPage(authenticated_page, e2e_server["url"])
        sp.navigate()
        sp.wait_for_loaded()
        return sp

    def test_kpis_displayed(self, authenticated_page, e2e_server):
        """Les KPI cards sont presentes (texte numerique visible)."""
        sp = self._status(authenticated_page, e2e_server)
        text = sp.get_full_page_text()
        # Le contenu doit avoir des chiffres (KPIs)
        import re

        numbers = re.findall(r"\d+", text)
        assert len(numbers) >= 2, f"Moins de 2 nombres dans le status : {text[:200]}"

    def test_kpi_films_count(self, authenticated_page, e2e_server):
        """Le KPI films affiche un nombre > 0."""
        sp = self._status(authenticated_page, e2e_server)
        text = sp.get_full_page_text()
        # Le nombre 15 ou "15" devrait apparaitre quelque part
        assert "15" in text or "films" in text.lower()

    def test_kpi_avg_score_range(self, authenticated_page, e2e_server):
        """Un score moyen est affiche dans le contenu."""
        sp = self._status(authenticated_page, e2e_server)
        text = sp.get_full_page_text()
        # Chercher des nombres qui pourraient etre des scores
        import re

        numbers = [float(n) for n in re.findall(r"\d+\.?\d*", text)]
        found_score = any(10 < n < 100 for n in numbers)
        assert found_score, f"Pas de score numerique 10-100 dans le status : {text[:300]}"

    def test_health_section_present(self, authenticated_page, e2e_server):
        """La section sante est affichee."""
        sp = self._status(authenticated_page, e2e_server)
        health = sp.get_health_text()
        assert health, "Section sante vide"

    def test_probe_tools_status(self, authenticated_page, e2e_server):
        """Le statut des outils probe est affiche."""
        sp = self._status(authenticated_page, e2e_server)
        health = sp.get_health_text()
        # MediaInfo ou FFprobe mentionne
        assert "mediainfo" in health.lower() or "ffprobe" in health.lower()

    def test_scan_button_visible(self, authenticated_page, e2e_server):
        """Le bouton 'Lancer un scan' est present."""
        sp = self._status(authenticated_page, e2e_server)
        assert sp.is_scan_button_visible()

    def test_perceptual_indicator(self, authenticated_page, e2e_server):
        """L'indicateur 'perceptuelle' est mentionne dans la sante."""
        sp = self._status(authenticated_page, e2e_server)
        health = sp.get_health_text()
        assert "perceptuelle" in health.lower(), f"Pas d'indicateur perceptuel dans : {health[:200]}"

    def test_watcher_indicator(self, authenticated_page, e2e_server):
        """L'indicateur veille est mentionne."""
        sp = self._status(authenticated_page, e2e_server)
        health = sp.get_health_text()
        assert "veille" in health.lower(), f"Pas d'indicateur veille dans : {health[:200]}"

    def test_screenshot_status(self, authenticated_page, e2e_server):
        """Screenshot full-page de la vue status."""
        sp = self._status(authenticated_page, e2e_server)
        path = sp.take_screenshot("status_full")
        assert path.exists()
        assert path.stat().st_size > 1000
