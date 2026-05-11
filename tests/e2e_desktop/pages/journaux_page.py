"""Page Object pour la vue Journaux du desktop CineSort."""

from __future__ import annotations

from .base_page import BasePage


class JournauxPage(BasePage):
    """Interactions avec la vue Journaux."""

    def navigate(self) -> None:
        self.navigate_to("logs")

    def get_log_text(self) -> str:
        """Retourne le contenu du journal."""
        el = self.page.query_selector("#logboxAll")
        return el.text_content() if el else ""

    def get_runs_count(self) -> int:
        """Nombre de runs dans la table historique."""
        rows = self.page.query_selector_all("#historyTbody tr")
        return len(rows)
