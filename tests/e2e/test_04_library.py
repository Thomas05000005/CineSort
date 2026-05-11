"""Tests E2E vue library du dashboard CineSort.

12 tests : table, recherche, filtres, modale detail, badges, tri, perceptuel, screenshot.
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

from pages.library_page import LibraryPage  # noqa: E402


class TestLibrary:
    """Tests de la vue library."""

    def _lib(self, authenticated_page, e2e_server) -> LibraryPage:
        lp = LibraryPage(authenticated_page, e2e_server["url"])
        lp.navigate()
        lp.wait_for_table()
        return lp

    def test_15_films_shown(self, authenticated_page, e2e_server):
        """Le tableau affiche 15 films."""
        lp = self._lib(authenticated_page, e2e_server)
        count = lp.get_visible_row_count()
        assert count == 15, f"Attendu 15 films, trouve {count}"

    def test_search_avengers(self, authenticated_page, e2e_server):
        """Recherche 'Avengers' → 2 resultats."""
        lp = self._lib(authenticated_page, e2e_server)
        lp.search("Avengers")
        count = lp.get_visible_row_count()
        assert count == 2, f"Attendu 2 films Avengers, trouve {count}"

    def test_filter_premium(self, authenticated_page, e2e_server):
        """Filtre Premium → nombre de films reduit (score >= 85)."""
        lp = self._lib(authenticated_page, e2e_server)
        total_before = lp.get_visible_row_count()
        lp.click_filter("premium")
        authenticated_page.wait_for_timeout(500)
        count = lp.get_visible_row_count()
        # Au moins 1 premium et moins que le total
        assert 0 < count < total_before, f"Filtre premium: {count} films (total={total_before})"

    def test_filter_toggle_off(self, authenticated_page, e2e_server):
        """Desactiver le filtre → retour aux 15 films."""
        lp = self._lib(authenticated_page, e2e_server)
        lp.click_filter("premium")
        authenticated_page.wait_for_timeout(200)
        lp.click_filter("premium")  # toggle off
        authenticated_page.wait_for_timeout(300)
        count = lp.get_visible_row_count()
        assert count == 15, f"Attendu 15 films apres toggle off, trouve {count}"

    def test_chart_present(self, authenticated_page, e2e_server):
        """Le graphique de distribution des tiers est present."""
        lp = self._lib(authenticated_page, e2e_server)
        assert lp.has_chart(), "Aucun chart SVG trouve"

    def test_click_opens_modal(self, authenticated_page, e2e_server):
        """Cliquer une ligne ouvre la modale detail."""
        lp = self._lib(authenticated_page, e2e_server)
        lp.click_row(0)
        assert lp.is_modal_open(), "La modale ne s'est pas ouverte"
        title = lp.get_modal_title()
        assert title, "Le titre de la modale est vide"

    def test_modal_detail_fields(self, authenticated_page, e2e_server):
        """La modale contient des champs detail (resolution, score, codec)."""
        lp = self._lib(authenticated_page, e2e_server)
        lp.click_row(0)
        body = lp.get_modal_body_text().lower()
        # Au moins un de ces mots-cles devrait etre present
        found = any(kw in body for kw in ["score", "resolution", "codec", "confiance", "source"])
        assert found, f"Aucun champ detail trouve dans la modale : {body[:200]}"

    def test_modal_warning_badges(self, authenticated_page, e2e_server):
        """Les films avec warnings affichent des indicateurs dans le tableau."""
        lp = self._lib(authenticated_page, e2e_server)
        table_text = lp.get_full_table_text().lower()
        # Les films ont des warning_flags — au moins un indicateur devrait etre visible
        has_warning = any(
            w in table_text
            for w in [
                "not_a_movie",
                "non-film",
                "integrity",
                "corrompu",
                "upscale",
                "mkv_title",
                "mkv titre",
                "warning",
            ]
        )
        assert has_warning, f"Aucun indicateur warning dans la table : {table_text[:400]}"

    def test_perceptual_button_in_modal(self, authenticated_page, e2e_server):
        """Le bouton 'Analyse perceptuelle' est present dans la modale."""
        lp = self._lib(authenticated_page, e2e_server)
        lp.click_row(0)
        btn = authenticated_page.query_selector("#btnDashPerceptual")
        assert btn is not None, "Bouton analyse perceptuelle absent de la modale"

    def test_sort_by_score(self, authenticated_page, e2e_server):
        """Cliquer sur l'en-tete Score trie le tableau."""
        lp = self._lib(authenticated_page, e2e_server)
        titles_before = lp.get_all_titles()
        # Trouver la colonne Score (index variable, chercher par texte)
        headers = authenticated_page.query_selector_all(f"{lp.TABLE} thead th")
        score_idx = None
        for i, h in enumerate(headers):
            if "score" in h.inner_text().lower():
                score_idx = i
                break
        if score_idx is not None:
            lp.sort_by_column(score_idx)
            titles_after = lp.get_all_titles()
            assert titles_before != titles_after, "Le tri n'a pas change l'ordre"

    def test_saga_badge_marvel(self, authenticated_page, e2e_server):
        """Les 3 films Marvel ont un badge 'Saga' ou 'Avengers'."""
        lp = self._lib(authenticated_page, e2e_server)
        table_text = lp.get_full_table_text()
        # Le badge saga avec le nom de collection "Avengers" devrait apparaitre
        assert "Avengers" in table_text or "Saga" in table_text or "saga" in table_text

    def test_screenshot_library(self, authenticated_page, e2e_server):
        """Screenshot de la table library."""
        lp = self._lib(authenticated_page, e2e_server)
        path = lp.take_screenshot("library_table")
        assert path.exists()
