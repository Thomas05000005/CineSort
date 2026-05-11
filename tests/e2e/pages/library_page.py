"""Page Object pour la vue library du dashboard."""

from __future__ import annotations

from .base_page import BasePage


class LibraryPage(BasePage):
    """Interactions avec la vue library / bibliotheque."""

    VIEW = "#view-library"
    CONTENT = "#libraryContent"
    SEARCH = "#librarySearch"
    TABLE = "#libTable"
    CHART = ".tier-chart"

    def navigate(self) -> None:
        """Navigue vers /library et attend le tableau."""
        self.navigate_to("library")
        self.page.wait_for_timeout(1500)  # laisser l'API charger

    def wait_for_table(self, timeout: int = 8000) -> None:
        """Attend que le tableau library contienne des lignes."""
        self.page.wait_for_selector(f"{self.TABLE} tbody tr", timeout=timeout)

    def get_visible_row_count(self) -> int:
        """Compte les lignes visibles dans le tableau."""
        rows = self.page.query_selector_all(f"{self.TABLE} tbody tr")
        return len([r for r in rows if r.is_visible()])

    def get_all_titles(self) -> list:
        """Extrait les titres des films depuis la premiere colonne."""
        cells = self.page.query_selector_all(f"{self.TABLE} tbody tr td:first-child")
        return [c.inner_text().strip() for c in cells]

    def search(self, query: str) -> None:
        """Tape dans le champ de recherche et attend le debounce."""
        self.page.fill(self.SEARCH, query)
        self.page.wait_for_timeout(500)

    def clear_search(self) -> None:
        """Vide le champ de recherche."""
        self.page.fill(self.SEARCH, "")
        self.page.wait_for_timeout(500)

    def click_filter(self, tier: str) -> None:
        """Clique sur le bouton filtre pour un tier donne."""
        self.page.click(f'.btn-filter[data-filter-key="{tier}"]')
        self.page.wait_for_timeout(300)

    def is_filter_active(self, tier: str) -> bool:
        """Verifie si un filtre est actif."""
        btn = self.page.query_selector(f'.btn-filter[data-filter-key="{tier}"]')
        if not btn:
            return False
        return "active" in (btn.get_attribute("class") or "")

    def click_row(self, index: int) -> None:
        """Clique sur la ligne N du tableau pour ouvrir la modale detail."""
        rows = self.page.query_selector_all(f"{self.TABLE} tbody tr")
        if index < len(rows):
            rows[index].click()
            self.page.wait_for_timeout(500)

    def get_modal_title(self) -> str:
        """Retourne le titre de la modale ouverte."""
        el = self.page.query_selector(".modal-header h3")
        return el.inner_text().strip() if el else ""

    def get_modal_body_text(self) -> str:
        """Retourne le texte du corps de la modale."""
        el = self.page.query_selector(".modal-body")
        return el.inner_text() if el else ""

    def has_chart(self) -> bool:
        """Verifie que le graphique des tiers est present."""
        return self.page.query_selector(self.CHART) is not None or self.page.query_selector("svg") is not None

    def click_perceptual_btn(self) -> None:
        """Clique sur le bouton analyse perceptuelle dans la modale."""
        btn = self.page.query_selector("#btnDashPerceptual")
        if btn:
            btn.click()
            self.page.wait_for_timeout(1000)

    def sort_by_column(self, col_index: int) -> None:
        """Clique sur l'en-tete de colonne pour trier."""
        headers = self.page.query_selector_all(f"{self.TABLE} thead th")
        if col_index < len(headers):
            headers[col_index].click()
            self.page.wait_for_timeout(300)

    def get_full_table_text(self) -> str:
        """Retourne tout le texte du tableau."""
        el = self.page.query_selector(self.TABLE)
        return el.inner_text() if el else ""
