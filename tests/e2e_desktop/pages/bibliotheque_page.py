"""Page Object pour la vue Bibliothèque du desktop CineSort."""

from __future__ import annotations

from .base_page import BasePage


class BibliothequePage(BasePage):
    """Interactions avec la vue Bibliothèque (scan, validation, apply)."""

    def navigate(self) -> None:
        self.navigate_to("library")

    # --- Section Analyse ---

    def start_scan(self) -> None:
        """Lance le scan depuis le bouton de la vue Home (la Bibliothèque redirige)."""
        # Le scan se lance depuis la vue Home car library-desktop.js appelle startPlan
        self.navigate_to("home")
        self.page.wait_for_timeout(500)
        self.click("home-btn-scan")

    def wait_scan_complete(self, timeout_ms: int = 300_000) -> None:
        """Attend que le scan soit termine (bouton scan re-active)."""
        self.page.wait_for_function(
            "() => !document.getElementById('btnStartPlan')?.disabled",
            timeout=timeout_ms,
        )

    def get_scan_progress(self) -> dict:
        """Retourne les infos de progression du scan."""
        return {
            "count": self.page.text_content("#progCount") or "",
            "speed": self.page.text_content("#progSpeed") or "",
            "eta": self.page.text_content("#progEta") or "",
        }

    # --- Section Validation ---

    def load_table(self) -> None:
        """Clique sur 'Charger la table de validation'."""
        self.click("home-btn-load-table")
        self.page.wait_for_timeout(1000)

    def get_films_count(self) -> int:
        """Nombre de films dans la table de validation."""
        rows = self.page.query_selector_all("#planTbody tr")
        return len(rows)

    def approve_film(self, index: int) -> None:
        """Approuve le film a l'index donne (coche la checkbox)."""
        rows = self.page.query_selector_all("#planTbody tr")
        if index < len(rows):
            cb = rows[index].query_selector("input[data-ok]")
            if cb:
                cb.check()

    def reject_film(self, index: int) -> None:
        """Rejette le film a l'index donne (decoche la checkbox)."""
        rows = self.page.query_selector_all("#planTbody tr")
        if index < len(rows):
            cb = rows[index].query_selector("input[data-ok]")
            if cb:
                cb.uncheck()

    def save_validation(self) -> None:
        """Sauvegarde les decisions de validation."""
        self.click("val-btn-save")
        self.page.wait_for_timeout(1000)

    # --- Section Application ---

    def start_apply(self, dry_run: bool = True) -> None:
        """Lance l'application des decisions."""
        if dry_run:
            ck = self.page.query_selector('[data-testid="exec-ck-dryrun"]')
            if ck and not ck.is_checked():
                ck.check()
        else:
            ck = self.page.query_selector('[data-testid="exec-ck-dryrun"]')
            if ck and ck.is_checked():
                ck.uncheck()
        self.click("exec-btn-apply")
        self.page.wait_for_timeout(2000)

    def get_apply_result(self) -> str:
        """Texte du resultat de l'apply."""
        return self.get_text("exec-apply-result")

    # --- Undo ---

    def start_undo_preview(self) -> None:
        self.click("exec-btn-undo-preview")
        self.page.wait_for_timeout(1000)
