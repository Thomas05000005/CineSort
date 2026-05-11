"""Page Object pour la vue Paramètres du desktop CineSort."""

from __future__ import annotations

from .base_page import BasePage


class ParametresPage(BasePage):
    """Interactions avec la vue Paramètres."""

    def navigate(self) -> None:
        self.navigate_to("settings")

    def get_theme(self) -> str:
        """Retourne le thème actuellement sélectionné."""
        return self.page.evaluate("() => document.getElementById('selTheme')?.value || ''")

    def set_theme(self, name: str) -> None:
        """Change le thème (studio, cinema, luxe, neon)."""
        self.page.select_option('[data-testid="settings-theme"]', name)
        self.page.wait_for_timeout(300)

    def get_body_theme(self) -> str:
        """Retourne le data-theme du body."""
        return self.page.evaluate("() => document.body.dataset.theme || ''")

    def get_tmdb_status(self) -> bool:
        """TMDb est-il activé ?"""
        return self.page.is_checked('[data-testid="settings-tmdb-enabled"]')

    def get_probe_tools_status(self) -> dict:
        """Statut des outils probe affiché dans l'environnement."""
        text = self.page.text_content("#homeEnvProbe") or ""
        return {"ok": "OK" in text, "text": text}

    def save(self) -> None:
        """Sauvegarde les paramètres."""
        self.click("settings-btn-save")
        self.page.wait_for_timeout(1000)
