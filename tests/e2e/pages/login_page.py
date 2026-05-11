"""Page Object pour la page de login du dashboard."""

from __future__ import annotations

from .base_page import BasePage


class LoginPage(BasePage):
    """Interactions avec le formulaire de login."""

    TOKEN_INPUT = "#loginToken"
    PERSIST_CHECKBOX = "#loginPersist"
    LOGIN_BTN = "#loginBtn"
    LOGIN_MSG = "#loginMsg"
    LOGIN_SPINNER = "#loginSpinner"

    def fill_token(self, token: str) -> None:
        """Remplit le champ token."""
        self.page.fill(self.TOKEN_INPUT, token)

    def check_persist(self, checked: bool = True) -> None:
        """Coche ou decoche 'Rester connecte'."""
        cb = self.page.query_selector(self.PERSIST_CHECKBOX)
        if cb:
            is_checked = cb.is_checked()
            if is_checked != checked:
                cb.click()

    def click_login(self) -> None:
        """Clique sur le bouton de connexion."""
        self.page.click(self.LOGIN_BTN)

    def login(self, token: str, persist: bool = False) -> None:
        """Login complet : remplir + cliquer + attendre le shell."""
        self.fill_token(token)
        if persist:
            self.check_persist(True)
        self.click_login()
        self.page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)

    def login_expect_error(self, token: str) -> str:
        """Login qui s'attend a une erreur. Retourne le message."""
        self.fill_token(token)
        self.click_login()
        self.page.wait_for_timeout(2000)
        return self.get_error_message()

    def get_error_message(self) -> str:
        """Retourne le texte du message d'erreur."""
        el = self.page.query_selector(self.LOGIN_MSG)
        return el.inner_text().strip() if el else ""

    def is_spinner_visible(self) -> bool:
        """Verifie si le spinner est visible."""
        el = self.page.query_selector(self.LOGIN_SPINNER)
        return el is not None and el.is_visible()

    def is_button_disabled(self) -> bool:
        """Verifie si le bouton login est desactive."""
        el = self.page.query_selector(self.LOGIN_BTN)
        return el.is_disabled() if el else True

    def submit_with_enter(self, token: str) -> None:
        """Soumet le formulaire avec Enter."""
        self.fill_token(token)
        self.page.press(self.TOKEN_INPUT, "Enter")
