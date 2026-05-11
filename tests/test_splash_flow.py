"""Tests du flow splash screen V4 — update_splash et startup flow."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock


class SplashUpdateTests(unittest.TestCase):
    """Tests pour _update_splash."""

    def test_update_splash_calls_evaluate_js(self):
        from app import _update_splash

        mock_window = MagicMock()
        _update_splash(mock_window, 1, "Test", 50)
        mock_window.evaluate_js.assert_called_once_with("updateProgress(1, 'Test', 50)")

    def test_update_splash_silent_on_error(self):
        """_update_splash ne crash pas si la fenetre est deja detruite."""
        from app import _update_splash

        mock_window = MagicMock()
        mock_window.evaluate_js.side_effect = RuntimeError("window destroyed")
        # Ne doit pas lever d'exception
        _update_splash(mock_window, 2, "Boom", 100)

    def test_update_splash_none_window(self):
        """_update_splash ne crash pas avec un window None."""
        from app import _update_splash

        _update_splash(None, 1, "Test", 0)  # type: ignore[arg-type]


class SplashHtmlTests(unittest.TestCase):
    """Tests pour le fichier splash.html."""

    def test_splash_html_exists(self):
        splash_path = Path(__file__).resolve().parents[1] / "web" / "splash.html"
        self.assertTrue(splash_path.exists(), f"web/splash.html introuvable: {splash_path}")

    def test_splash_html_contains_progress_function(self):
        splash_path = Path(__file__).resolve().parents[1] / "web" / "splash.html"
        content = splash_path.read_text(encoding="utf-8")
        self.assertIn("updateProgress", content)
        self.assertIn("setVersion", content)

    def test_splash_html_has_bar_element(self):
        splash_path = Path(__file__).resolve().parents[1] / "web" / "splash.html"
        content = splash_path.read_text(encoding="utf-8")
        self.assertIn('id="bar"', content)
        self.assertIn('id="stepText"', content)

    def test_splash_html_no_external_deps(self):
        """Le splash ne doit charger aucune ressource externe."""
        splash_path = Path(__file__).resolve().parents[1] / "web" / "splash.html"
        content = splash_path.read_text(encoding="utf-8")
        # Pas de <link> vers un CDN, pas de <script src="http">
        self.assertNotIn("http://", content)
        self.assertNotIn("https://", content)


class RuntimeHookTests(unittest.TestCase):
    """Tests pour le runtime hook simplifie."""

    def test_splash_hook_no_win32_splash(self):
        """Le runtime hook ne doit plus contenir de splash Win32."""
        hook_path = Path(__file__).resolve().parents[1] / "runtime_hooks" / "splash_hook.py"
        content = hook_path.read_text(encoding="utf-8")
        self.assertNotIn("CreateWindowExW", content)
        self.assertNotIn("WNDCLASSEXW", content)
        self.assertNotIn("Shell_NotifyIconW", content)
        self.assertIn("AllocConsole", content)


if __name__ == "__main__":
    unittest.main()
