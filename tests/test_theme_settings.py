"""Tests pour les settings du systeme de themes V4."""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.ui.api.cinesort_api import CineSortApi


class ThemeSettingsTests(unittest.TestCase):
    """Tests pour les settings theme dans apply_settings_defaults et save_settings."""

    def test_theme_has_value(self):
        """Le setting theme est present et a une valeur valide."""
        api = CineSortApi()
        s = api.get_settings()
        self.assertIn(s.get("theme"), ("cinema", "studio", "luxe", "neon"))

    def test_animation_level_has_value(self):
        api = CineSortApi()
        s = api.get_settings()
        self.assertIn(s.get("animation_level"), ("subtle", "moderate", "intense"))

    def test_effect_speed_in_range(self):
        api = CineSortApi()
        s = api.get_settings()
        self.assertGreaterEqual(s.get("effect_speed", 0), 1)
        self.assertLessEqual(s.get("effect_speed", 999), 100)

    def test_glow_intensity_in_range(self):
        api = CineSortApi()
        s = api.get_settings()
        self.assertGreaterEqual(s.get("glow_intensity", -1), 0)
        self.assertLessEqual(s.get("glow_intensity", 999), 100)

    def test_light_intensity_in_range(self):
        api = CineSortApi()
        s = api.get_settings()
        self.assertGreaterEqual(s.get("light_intensity", -1), 0)
        self.assertLessEqual(s.get("light_intensity", 999), 100)

    def test_theme_valid_values(self):
        """Seules les valeurs cinema/studio/luxe/neon sont acceptees."""
        api = CineSortApi()
        s = api.get_settings()
        s["theme"] = "cinema"
        result = api.save_settings(s)
        self.assertTrue(result.get("ok"), result)
        s2 = api.get_settings()
        self.assertEqual(s2["theme"], "cinema")

    def test_theme_invalid_fallback(self):
        """Une valeur invalide retombe sur le defaut (luxe depuis refonte V6)."""
        api = CineSortApi()
        s = api.get_settings()
        s["theme"] = "invalid"
        api.save_settings(s)
        s2 = api.get_settings()
        self.assertEqual(s2["theme"], "luxe")

    def test_effect_speed_clamp(self):
        """effect_speed est clampe entre 1 et 100."""
        api = CineSortApi()
        s = api.get_settings()
        s["effect_speed"] = 200
        api.save_settings(s)
        s2 = api.get_settings()
        self.assertEqual(s2["effect_speed"], 100)

    def test_glow_intensity_clamp_zero(self):
        """glow_intensity accepte 0 (aucun glow)."""
        api = CineSortApi()
        s = api.get_settings()
        s["glow_intensity"] = 0
        api.save_settings(s)
        s2 = api.get_settings()
        self.assertEqual(s2["glow_intensity"], 0)

    def test_settings_round_trip(self):
        """Les 5 settings theme font un round-trip correct."""
        api = CineSortApi()
        s = api.get_settings()
        s["theme"] = "neon"
        s["animation_level"] = "intense"
        s["effect_speed"] = 75
        s["glow_intensity"] = 60
        s["light_intensity"] = 40
        api.save_settings(s)
        s2 = api.get_settings()
        self.assertEqual(s2["theme"], "neon")
        self.assertEqual(s2["animation_level"], "intense")
        self.assertEqual(s2["effect_speed"], 75)
        self.assertEqual(s2["glow_intensity"], 60)
        self.assertEqual(s2["light_intensity"], 40)


class ThemesCssTests(unittest.TestCase):
    """Tests pour le fichier themes.css."""

    def test_themes_css_exists(self):
        path = Path(__file__).resolve().parents[1] / "web" / "themes.css"
        self.assertTrue(path.exists())

    def test_themes_css_has_all_palettes(self):
        path = Path(__file__).resolve().parents[1] / "web" / "themes.css"
        content = path.read_text(encoding="utf-8")
        for theme in ("cinema", "studio", "luxe", "neon"):
            self.assertIn(f'[data-theme="{theme}"]', content, f"Palette {theme} manquante")

    def test_themes_css_has_animation_levels(self):
        path = Path(__file__).resolve().parents[1] / "web" / "themes.css"
        content = path.read_text(encoding="utf-8")
        for level in ("subtle", "intense"):
            self.assertIn(f'[data-animation="{level}"]', content, f"Niveau {level} manquant")

    def test_themes_css_has_effects(self):
        """V8 Restraint Premium : verifie les animations clefs du design system actuel.

        Historique : V6 utilisait @keyframes neon-rotate et .card::after.
        V8 les a remplacees par ambientDrift (tous themes) et scanPulse.
        """
        path = Path(__file__).resolve().parents[1] / "web" / "themes.css"
        content = path.read_text(encoding="utf-8")
        self.assertIn("@keyframes ambientDrift", content)
        self.assertIn("@keyframes scanPulse", content)
        # Chaque theme doit exister dans le selecteur data-theme
        for theme in ("luxe", "studio", "cinema", "neon"):
            self.assertIn(f'[data-theme="{theme}"]', content, msg=f"theme manquant: {theme}")

    def test_themes_css_linked_in_desktop(self):
        path = Path(__file__).resolve().parents[1] / "web" / "index.html"
        content = path.read_text(encoding="utf-8")
        self.assertIn("themes.css", content)

    def test_themes_css_linked_in_dashboard(self):
        path = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "index.html"
        content = path.read_text(encoding="utf-8")
        self.assertIn("themes.css", content)


if __name__ == "__main__":
    unittest.main()
