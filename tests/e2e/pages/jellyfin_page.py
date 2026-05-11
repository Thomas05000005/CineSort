"""Page Object pour la vue Jellyfin du dashboard."""

from __future__ import annotations

from .base_page import BasePage


class JellyfinPage(BasePage):
    """Interactions avec la vue Jellyfin."""

    VIEW = "#view-jellyfin"
    CONTENT = "#jellyfinContent"

    def navigate(self) -> None:
        """Navigue vers /jellyfin et attend le contenu."""
        self.navigate_to("jellyfin")
        self.page.wait_for_timeout(2500)  # laisser test_jellyfin_connection repondre

    def get_content_text(self) -> str:
        """Retourne le texte complet du contenu jellyfin."""
        el = self.page.query_selector(self.CONTENT)
        return el.inner_text() if el else ""

    def get_connection_status(self) -> str:
        """Retourne le statut de connexion ('Connecte' ou 'Deconnecte')."""
        text = self.get_content_text()
        if "connecte" in text.lower() or "connect" in text.lower():
            if "deconnecte" in text.lower() or "disconnect" in text.lower():
                return "deconnecte"
            return "connecte"
        return "unknown"

    def is_test_button_visible(self) -> bool:
        """Verifie la presence d'un bouton test connexion."""
        content = self.get_content_text().lower()
        return "tester" in content or "test" in content

    def has_kpi_cards(self) -> bool:
        """Verifie que des KPI cards sont presentes."""
        cards = self.page.query_selector_all(f"{self.CONTENT} .kpi-card")
        return len(cards) > 0

    def has_libraries_section(self) -> bool:
        """Verifie la presence de la section libraries."""
        text = self.get_content_text().lower()
        return "biblioth" in text or "librar" in text

    def is_disabled_message_shown(self) -> bool:
        """Verifie si le message 'non configure' est affiche."""
        text = self.get_content_text().lower()
        return "non configure" in text or "desactive" in text
