"""Page Object de base pour les tests E2E desktop CineSort."""

from __future__ import annotations

from pathlib import Path

SCREENSHOTS_DIR = Path(__file__).resolve().parents[1] / "screenshots"


class BasePage:
    """Page de base avec helpers communs pour les tests E2E desktop."""

    def __init__(self, page):
        self.page = page

    def navigate_to(self, view_name: str) -> None:
        """Clique sur l'onglet de navigation correspondant."""
        self.page.click(f'[data-testid="nav-{view_name}"]')
        self.page.wait_for_timeout(500)

    def screenshot(self, name: str) -> str:
        """Capture un screenshot avec nom horodate."""
        path = str(SCREENSHOTS_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def get_text(self, testid: str) -> str:
        """Retourne le texte d'un element par data-testid."""
        return self.page.text_content(f'[data-testid="{testid}"]') or ""

    def click(self, testid: str) -> None:
        """Clique sur un element par data-testid."""
        self.page.click(f'[data-testid="{testid}"]')

    def fill(self, testid: str, value: str) -> None:
        """Remplit un champ par data-testid."""
        self.page.fill(f'[data-testid="{testid}"]', value)

    def is_visible(self, testid: str) -> bool:
        """Verifie si un element est visible."""
        return self.page.is_visible(f'[data-testid="{testid}"]')

    def get_active_view(self) -> str:
        """Retourne le nom de la vue active (data-view du body)."""
        return self.page.evaluate("() => document.body.dataset.view || ''")

    def get_nav_buttons(self) -> list[str]:
        """Retourne la liste des data-view de tous les boutons nav visibles."""
        return self.page.evaluate("""() =>
            Array.from(document.querySelectorAll('.nav-btn[data-view]'))
                .filter(b => b.offsetParent !== null)
                .map(b => b.dataset.view)
        """)

    def wait_for_view(self, view_name: str, timeout: int = 5000) -> None:
        """Attend que la vue soit active."""
        self.page.wait_for_function(
            f"() => document.body.dataset.view === '{view_name}'",
            timeout=timeout,
        )
