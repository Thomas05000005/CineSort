"""V3-02 — Verifie le systeme expert_mode (toggle settings avances).

Couvre :
- Default `expert_mode=False` dans apply_settings_defaults (round-trip via CineSortApi).
- Normalisation bool dans _save_section_scan_flags (accepte True/False natifs ET
  strings "true"/"false" comme l'envoie le frontend).
- Presence du toggle UI + flag advanced dans web/dashboard/views/settings.js.
- Presence du filtrage CSS pour body.expert-mode-off [data-advanced].
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.ui.api.settings_support import _save_section_scan_flags
from cinesort.ui.api.cinesort_api import CineSortApi


class ExpertModeBackendTests(unittest.TestCase):
    def test_expert_mode_default_false(self):
        """Le setting expert_mode est present et faux par defaut (mode debutant)."""
        api = CineSortApi()
        s = api.get_settings()
        self.assertIn("expert_mode", s)
        self.assertFalse(s["expert_mode"])

    def test_expert_mode_normalized_true_string(self):
        """_save_section_scan_flags coerce 'true' string en bool True."""
        out = _save_section_scan_flags({"expert_mode": "true"})
        self.assertIs(type(out["expert_mode"]), bool)
        self.assertTrue(out["expert_mode"])

    def test_expert_mode_normalized_native_bool(self):
        """_save_section_scan_flags conserve le bool natif."""
        out_true = _save_section_scan_flags({"expert_mode": True})
        out_false = _save_section_scan_flags({"expert_mode": False})
        self.assertTrue(out_true["expert_mode"])
        self.assertFalse(out_false["expert_mode"])

    def test_expert_mode_missing_defaults_to_false(self):
        """expert_mode absent du payload → False (mode debutant)."""
        out = _save_section_scan_flags({})
        self.assertFalse(out["expert_mode"])

    def test_expert_mode_round_trip(self):
        """save_settings(expert_mode=True) → get_settings retourne True."""
        api = CineSortApi()
        s = api.get_settings()
        s["expert_mode"] = True
        result = api.save_settings(s)
        self.assertTrue(result.get("ok"), result)
        try:
            s2 = api.get_settings()
            self.assertTrue(s2["expert_mode"])
        finally:
            # Restore default pour ne pas polluer les autres tests
            s2 = api.get_settings()
            s2["expert_mode"] = False
            api.save_settings(s2)


@unittest.skip(
    "V5C-01: dashboard/views/settings.js supprime — settings v5 portee dans web/views/settings-v5.js (couvert par test_settings_v5_ported)"
)
class ExpertModeFrontendTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.js = (root / "web" / "dashboard" / "views" / "settings.js").read_text(encoding="utf-8")
        self.css = (root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_advanced_flag_used(self):
        """Au moins un element du settings.js est marque data-advanced='true'."""
        self.assertIn('data-advanced="true"', self.js)

    def test_expert_toggle_present(self):
        """Le toggle ckExpertMode est rendu et lie au setting expert_mode."""
        self.assertIn("ckExpertMode", self.js)
        self.assertIn("expert_mode", self.js)

    def test_apply_expert_mode_helper(self):
        """La helper _applyExpertMode existe (bascule classe body)."""
        self.assertIn("_applyExpertMode", self.js)
        self.assertIn("expert-mode-on", self.js)
        self.assertIn("expert-mode-off", self.js)

    def test_css_filter_advanced(self):
        """Le CSS cache les data-advanced en mode debutant."""
        self.assertIn('body.expert-mode-off [data-advanced="true"]', self.css)
        self.assertIn(".expert-toggle-card", self.css)


if __name__ == "__main__":
    unittest.main()
