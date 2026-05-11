"""Page Object pour la vue review du dashboard."""

from __future__ import annotations

import re
from .base_page import BasePage


class ReviewPage(BasePage):
    """Interactions avec la vue review / triage."""

    VIEW = "#view-review"
    CONTENT = "#reviewContent"
    TABLE = "#reviewTable"
    COUNTERS = "#reviewCounters"
    BTN_BULK_APPROVE = "#btnBulkApprove"
    BTN_BULK_REJECT = "#btnBulkReject"
    BTN_BULK_RESET = "#btnBulkReset"
    BTN_SAVE = "#btnReviewSave"
    BTN_APPLY = "#btnReviewApply"
    BTN_PREVIEW = "#btnReviewPreview"
    MSG = "#reviewMsg"

    def navigate(self) -> None:
        """Navigue vers /review et attend le contenu."""
        self.navigate_to("review")
        self.page.wait_for_timeout(4000)  # 3 appels API sequentiels (health + stats + get_plan)

    def wait_for_table(self, timeout: int = 15000) -> None:
        """Attend que le tableau review contienne des lignes."""
        self.page.wait_for_selector(f"{self.TABLE} tbody tr", timeout=timeout)

    def get_row_count(self) -> int:
        """Compte les lignes du tableau review."""
        rows = self.page.query_selector_all(f"{self.TABLE} tbody tr")
        return len(rows)

    def get_counters_text(self) -> str:
        """Retourne le texte brut des compteurs."""
        el = self.page.query_selector(self.COUNTERS)
        return el.inner_text() if el else ""

    def get_counters(self) -> dict:
        """Parse les compteurs : {approved, rejected, pending}."""
        text = self.get_counters_text()
        nums = re.findall(r"(\d+)", text)
        # Format attendu : "N approuve(s) N rejete(s) N en attente"
        return {
            "approved": int(nums[0]) if len(nums) > 0 else 0,
            "rejected": int(nums[1]) if len(nums) > 1 else 0,
            "pending": int(nums[2]) if len(nums) > 2 else 0,
        }

    def approve_row(self, row_id: str) -> None:
        """Clique sur le bouton approuver d'une ligne."""
        self.page.click(f'.btn-review[data-action="approve"][data-rid="{row_id}"]')
        self.page.wait_for_timeout(200)

    def reject_row(self, row_id: str) -> None:
        """Clique sur le bouton rejeter d'une ligne."""
        self.page.click(f'.btn-review[data-action="reject"][data-rid="{row_id}"]')
        self.page.wait_for_timeout(500)  # laisser le re-render du table

    def is_row_approved(self, row_id: str) -> bool:
        """Verifie si une ligne est marquee approved."""
        btn = self.page.query_selector(f'.btn-review.btn-approve[data-rid="{row_id}"]')
        return btn is not None and "active" in (btn.get_attribute("class") or "")

    def is_row_rejected(self, row_id: str) -> bool:
        """Verifie si une ligne est marquee rejected."""
        btn = self.page.query_selector(f'.btn-review.btn-reject[data-rid="{row_id}"]')
        return btn is not None and "active" in (btn.get_attribute("class") or "")

    def click_bulk_approve(self) -> None:
        """Clique sur 'Approuver les surs'."""
        self.page.click(self.BTN_BULK_APPROVE)
        self.page.wait_for_timeout(300)

    def click_bulk_reset(self) -> None:
        """Clique sur 'Reinitialiser'."""
        self.page.click(self.BTN_BULK_RESET)
        self.page.wait_for_timeout(300)

    def click_save(self) -> None:
        """Clique sur 'Sauvegarder'."""
        self.page.click(self.BTN_SAVE)
        self.page.wait_for_timeout(500)

    def get_status_message(self) -> str:
        """Retourne le texte du message de statut."""
        el = self.page.query_selector(self.MSG)
        return el.inner_text().strip() if el else ""

    def get_full_table_text(self) -> str:
        """Retourne le texte complet du tableau review."""
        el = self.page.query_selector(self.TABLE)
        return el.inner_text() if el else ""

    def get_content_text(self) -> str:
        """Retourne le texte complet du contenu review."""
        el = self.page.query_selector(self.CONTENT)
        return el.inner_text() if el else ""
