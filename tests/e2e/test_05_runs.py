"""Tests E2E vue runs du dashboard CineSort.

V1-05 (Polish v7.7.0) : la vue dashboard /runs et son conteneur HTML
#view-runs / #runsContent ont ete supprimes par FIX-4 CRIT-5
(sections orphelines retirees de index.html). L'historique des runs
est desormais accessible depuis QIJ tab Journal (#/qij ou #/logs).

L'ensemble du module est marque pytest.skip jusqu'a un re-port complet
des tests vers la nouvelle UI (tracking : V2-XX a planifier).
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

import pytest  # noqa: E402

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

from pages.runs_page import RunsPage  # noqa: E402

pytestmark = pytest.mark.skip(reason=(
    "V1-05 : vue /runs supprimee par FIX-4 CRIT-5 (consolidee dans QIJ tab "
    "Journal). Tests a re-porter vers la nouvelle UI."
))


class TestRuns:
    """Tests de la vue historique des runs."""

    def _runs(self, authenticated_page, e2e_server) -> RunsPage:
        rp = RunsPage(authenticated_page, e2e_server["url"])
        rp.navigate()
        rp.wait_for_table()
        return rp

    def test_runs_shown(self, authenticated_page, e2e_server):
        """Le tableau affiche au moins 1 run."""
        rp = self._runs(authenticated_page, e2e_server)
        count = rp.get_run_count()
        assert count >= 1, f"Attendu au moins 1 run, trouve {count}"

    def test_columns_present(self, authenticated_page, e2e_server):
        """Les colonnes cles sont presentes."""
        rp = self._runs(authenticated_page, e2e_server)
        headers = rp.get_column_headers()
        headers_lower = [h.lower() for h in headers]
        # Au moins "date" ou "run" et "films" ou "score" ou "statut"
        assert any("date" in h or "run" in h for h in headers_lower), f"Pas de colonne date/run : {headers}"

    def test_status_shown(self, authenticated_page, e2e_server):
        """Le statut des runs est affiche."""
        rp = self._runs(authenticated_page, e2e_server)
        text = rp.get_content_text().upper()
        # Au moins un statut est affiche (DONE, TERMINE, ou un badge)
        assert any(s in text for s in ["DONE", "TERMINE", "STATUT", "OK"]), f"Pas de statut dans : {text[:200]}"

    def test_timeline_svg_present(self, authenticated_page, e2e_server):
        """Le SVG timeline est present."""
        rp = self._runs(authenticated_page, e2e_server)
        content = rp.get_content_text()
        # La timeline ou un SVG devrait etre present
        has_svg = rp.has_timeline_svg()
        # Si pas de SVG, le contenu devrait quand meme avoir des donnees
        assert has_svg or len(content) > 50

    def test_content_not_empty(self, authenticated_page, e2e_server):
        """La vue runs affiche du contenu (pas juste 'Aucun run')."""
        rp = self._runs(authenticated_page, e2e_server)
        text = rp.get_content_text()
        assert len(text) > 20, f"Contenu runs trop court : {text[:100]}"

    def test_export_json_button(self, authenticated_page, e2e_server):
        """Le bouton d'export JSON est present."""
        rp = self._runs(authenticated_page, e2e_server)
        content = rp.get_content_text()
        assert "json" in content.lower() or "JSON" in content

    def test_export_csv_button(self, authenticated_page, e2e_server):
        """Le bouton d'export CSV est present."""
        rp = self._runs(authenticated_page, e2e_server)
        content = rp.get_content_text()
        assert "csv" in content.lower() or "CSV" in content

    def test_screenshot_runs(self, authenticated_page, e2e_server):
        """Screenshot de la vue runs."""
        rp = self._runs(authenticated_page, e2e_server)
        path = rp.take_screenshot("runs_page")
        assert path.exists()
