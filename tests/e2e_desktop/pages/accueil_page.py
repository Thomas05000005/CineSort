"""Page Object pour la vue Accueil (home) du desktop CineSort."""

from __future__ import annotations

from .base_page import BasePage


class AccueilPage(BasePage):
    """Interactions avec la vue Accueil."""

    def navigate(self) -> None:
        self.navigate_to("home")

    def get_kpis(self) -> dict:
        """Retourne les KPIs affiches (films, score, anomalies, statut)."""
        return {
            "films": self.get_text("home-kpi-films"),
            "score": self.get_text("home-kpi-score"),
        }

    def is_probe_banner_visible(self) -> bool:
        """Le bandeau d'installation des outils probe est-il visible ?"""
        return self.is_visible("home-probe-banner")

    def click_start_scan(self) -> None:
        """Clique sur le bouton de demarrage du scan."""
        self.click("home-btn-scan")

    def get_progress_visible(self) -> bool:
        """La barre de progression est-elle visible ?"""
        el = self.page.query_selector("#homeScanProgress")
        if not el:
            return False
        return not el.evaluate("el => el.classList.contains('hidden')")

    def click_open_library(self) -> None:
        self.navigate_to("library")

    def click_open_quality(self) -> None:
        self.navigate_to("quality")

    def click_open_logs(self) -> None:
        self.navigate_to("logs")
