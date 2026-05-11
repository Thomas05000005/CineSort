"""V2-03 — verifie presence du systeme draft auto dans validation.js (audit ID-J-002).

V5C-01 : la vue dashboard review.js a ete supprimee (remplacee par processing v5).
Les tests qui ciblaient REVIEW_JS sont skippes — le draft auto est porte
en v5 dans web/views/processing.js (couvert par test_processing_v5_ported).
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALIDATION_JS = ROOT / "web/views/validation.js"


class ValidationDraftTests(unittest.TestCase):
    def test_validation_uses_localstorage_draft(self):
        src = VALIDATION_JS.read_text(encoding="utf-8")
        self.assertIn("val_draft_", src)
        self.assertIn("localStorage.setItem", src)
        self.assertIn("localStorage.getItem", src)

    def test_validation_has_restore_banner(self):
        src = VALIDATION_JS.read_text(encoding="utf-8")
        self.assertIn("valDraftRestore", src)
        self.assertIn("valDraftDiscard", src)

    def test_validation_clears_draft_on_save(self):
        src = VALIDATION_JS.read_text(encoding="utf-8")
        self.assertIn("_clearDraft", src)
        # Le clear doit etre appele cote saveValidationFromUI apres ok serveur.
        self.assertRegex(
            src,
            r"if\s*\(\s*r\?\.ok\s*\)\s*\{[^}]*_clearDraft\(\)",
        )

    def test_validation_debounces_draft_save(self):
        src = VALIDATION_JS.read_text(encoding="utf-8")
        self.assertIn("_scheduleDraftSave", src)
        # Debounce par setTimeout pour eviter une ecriture par clic.
        self.assertIn("setTimeout(_saveDraft, 500)", src)

    def test_validation_offers_restore_after_load(self):
        src = VALIDATION_JS.read_text(encoding="utf-8")
        self.assertIn("_checkAndOfferRestore", src)

    def test_30day_ttl_constant(self):
        src = VALIDATION_JS.read_text(encoding="utf-8")
        self.assertIn("VAL_DRAFT_TTL_MS", src, msg="TTL constant missing in validation.js")
        # 30 jours en millisecondes : 30 * 24 * 60 * 60 * 1000.
        self.assertIn("30 * 24 * 60 * 60 * 1000", src, msg="TTL formula missing in validation.js")


if __name__ == "__main__":
    unittest.main()
