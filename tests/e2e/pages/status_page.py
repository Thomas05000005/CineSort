"""Page Object pour la vue status du dashboard."""

from __future__ import annotations

from .base_page import BasePage


class StatusPage(BasePage):
    """Interactions avec la vue status / accueil."""

    VIEW = "#view-status"
    CONTENT = "#statusContent"
    BTN_START = "#btnStartScan"
    KPI_GRID = ".kpi-grid"
    HEALTH_LIST = ".status-health-list"

    def navigate(self) -> None:
        """Navigue vers /status et attend le contenu."""
        self.navigate_to("status")
        self.page.wait_for_timeout(2000)  # laisser les appels API se terminer

    def wait_for_loaded(self, timeout: int = 8000) -> None:
        """Attend que le contenu status soit charge (KPIs ou texte)."""
        self.page.wait_for_selector(f"{self.CONTENT} .kpi-grid, {self.CONTENT} .card", timeout=timeout)

    def get_kpi_values(self) -> dict:
        """Extrait les valeurs KPI sous forme {label: value}."""
        cards = self.page.query_selector_all(".kpi-card")
        result = {}
        for card in cards:
            label_el = card.query_selector(".kpi-header span, .kpi-label")
            value_el = card.query_selector(".kpi-value")
            if label_el and value_el:
                label = label_el.inner_text().strip()
                value = value_el.inner_text().strip()
                result[label] = value
        return result

    def get_health_text(self) -> str:
        """Retourne le texte complet de la section sante."""
        el = self.page.query_selector(self.HEALTH_LIST)
        return el.inner_text() if el else ""

    def is_scan_button_visible(self) -> bool:
        """Verifie que le bouton 'Lancer un scan' est visible."""
        btn = self.page.query_selector(self.BTN_START)
        return btn is not None and btn.is_visible()

    def get_full_page_text(self) -> str:
        """Retourne tout le texte du contenu status."""
        el = self.page.query_selector(self.CONTENT)
        return el.inner_text() if el else ""
