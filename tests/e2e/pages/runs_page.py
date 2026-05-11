"""Page Object pour la vue runs du dashboard."""

from __future__ import annotations

from .base_page import BasePage


class RunsPage(BasePage):
    """Interactions avec la vue historique des runs."""

    VIEW = "#view-runs"
    CONTENT = "#runsContent"
    TABLE = "#runsContent table"

    def navigate(self) -> None:
        """Navigue vers /runs et attend le contenu."""
        self.navigate_to("runs")
        self.page.wait_for_timeout(2000)  # laisser l'API get_global_stats repondre

    def wait_for_table(self, timeout: int = 8000) -> None:
        """Attend que le tableau des runs soit charge."""
        self.page.wait_for_selector(f"{self.TABLE} tbody tr", timeout=timeout)

    def get_run_count(self) -> int:
        """Compte les lignes du tableau."""
        rows = self.page.query_selector_all(f"{self.TABLE} tbody tr")
        return len(rows)

    def get_table_text(self) -> str:
        """Retourne le texte complet du tableau."""
        el = self.page.query_selector(self.TABLE)
        return el.inner_text() if el else ""

    def get_column_headers(self) -> list:
        """Retourne les textes des en-tetes de colonnes."""
        headers = self.page.query_selector_all(f"{self.TABLE} thead th")
        return [h.inner_text().strip() for h in headers]

    def has_timeline_svg(self) -> bool:
        """Verifie la presence d'un SVG timeline."""
        content = self.page.query_selector(self.CONTENT)
        if not content:
            return False
        return content.query_selector("svg") is not None

    def get_export_buttons(self) -> list:
        """Retourne les formats d'export disponibles (texte des boutons)."""
        btns = self.page.query_selector_all(f"{self.CONTENT} button")
        return [
            b.inner_text().strip()
            for b in btns
            if "export" in b.inner_text().lower() or b.inner_text().strip() in ("CSV", "HTML", "JSON")
        ]

    def get_content_text(self) -> str:
        """Retourne tout le texte du contenu runs."""
        el = self.page.query_selector(self.CONTENT)
        return el.inner_text() if el else ""
