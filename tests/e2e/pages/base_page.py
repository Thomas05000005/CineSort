"""Page Object de base — navigation, waits, screenshots."""

from __future__ import annotations

from pathlib import Path


class BasePage:
    """Classe de base pour les Page Objects du dashboard."""

    def __init__(self, page, base_url: str):
        self.page = page
        self.base_url = base_url

    def goto_dashboard(self) -> None:
        """Navigue vers la page d'accueil du dashboard."""
        self.page.goto(f"{self.base_url}/dashboard/")

    def navigate_to(self, route: str) -> None:
        """Navigue vers une vue via le hash."""
        self.page.evaluate(f"window.location.hash = '#/{route}'")
        self.page.wait_for_selector(f"#view-{route}", timeout=5000)
        self.page.wait_for_timeout(300)  # laisser le JS initialiser la vue

    def get_active_view_id(self) -> str:
        """Retourne l'id de la vue active (.view:not(.hidden))."""
        el = self.page.query_selector(".view:not(.hidden)")
        return el.get_attribute("id") if el else ""

    def is_shell_visible(self) -> bool:
        """Verifie que #app-shell est visible."""
        el = self.page.query_selector("#app-shell")
        if not el:
            return False
        return "hidden" not in (el.get_attribute("class") or "")

    def is_login_visible(self) -> bool:
        """Verifie que #view-login est visible."""
        el = self.page.query_selector("#view-login")
        if not el:
            return False
        return "hidden" not in (el.get_attribute("class") or "")

    def take_screenshot(self, name: str, directory: str = "tests/e2e/screenshots") -> Path:
        """Capture un screenshot full-page."""
        out_dir = Path(directory)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.png"
        self.page.screenshot(path=str(path), full_page=True)
        return path

    def close_modal(self) -> None:
        """Ferme la modale ouverte (si presente)."""
        btn = self.page.query_selector(".modal-close-btn, [data-modal-close]")
        if btn:
            btn.click()
            self.page.wait_for_timeout(200)

    def is_modal_open(self) -> bool:
        """Verifie si une modale est ouverte."""
        return self.page.query_selector(".modal-overlay") is not None

    def wait_for_content(self, selector: str, timeout: int = 5000) -> None:
        """Attend qu'un element soit present et visible."""
        self.page.wait_for_selector(selector, timeout=timeout)

    def get_text(self, selector: str) -> str:
        """Retourne le texte d'un element."""
        el = self.page.query_selector(selector)
        return el.inner_text() if el else ""

    def get_nav_buttons(self) -> list:
        """Retourne les data-route des boutons de navigation."""
        btns = self.page.query_selector_all(".nav-btn[data-route]")
        return [btn.get_attribute("data-route") for btn in btns]

    def get_active_nav_route(self) -> str:
        """Retourne le data-route du bouton actif."""
        btn = self.page.query_selector('.nav-btn[aria-selected="true"]')
        return btn.get_attribute("data-route") if btn else ""
