"""Page Object pour la vue Qualité du desktop CineSort."""

from __future__ import annotations

from .base_page import BasePage


class QualitePage(BasePage):
    """Interactions avec la vue Qualité."""

    def navigate(self) -> None:
        self.navigate_to("quality")

    def get_quality_kpis(self) -> dict:
        """Retourne les KPIs qualite affiches."""
        return {
            "score": self.page.text_content("#qKpiScore") or "—",
            "premium": self.page.text_content("#qKpiPremium") or "—",
            "films": self.page.text_content("#qKpiFilms") or "—",
            "partial": self.page.text_content("#qKpiPartial") or "—",
        }

    def switch_to_global(self) -> None:
        """Bascule vers le mode Bibliothèque (global)."""
        btns = self.page.query_selector_all('#qualityModeToggle button[data-qmode="global"]')
        if btns:
            btns[0].click()
            self.page.wait_for_timeout(500)

    def switch_to_run(self) -> None:
        """Bascule vers le mode Run courant."""
        btns = self.page.query_selector_all('#qualityModeToggle button[data-qmode="run"]')
        if btns:
            btns[0].click()
            self.page.wait_for_timeout(500)

    def refresh(self) -> None:
        """Rafraichit la vue qualite."""
        self.click("quality-btn-refresh")
        self.page.wait_for_timeout(1000)
