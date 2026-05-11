"""Tests contrat pour l'UI unifiee (desktop ouvre le dashboard via pywebview)."""

from __future__ import annotations

import unittest
from pathlib import Path


class UnifiedUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.app_py = (cls.root / "app.py").read_text(encoding="utf-8")
        cls.dash_app_js = (cls.root / "web" / "dashboard" / "app.js").read_text(encoding="utf-8")
        cls.rest_py = (cls.root / "cinesort" / "infra" / "rest_server.py").read_text(encoding="utf-8")
        cls.dash_drop = cls.root / "web" / "dashboard" / "core" / "drop.js"
        cls.dash_cmd = cls.root / "web" / "dashboard" / "components" / "command-palette.js"
        cls.dash_confetti = cls.root / "web" / "dashboard" / "components" / "confetti.js"
        cls.dash_copy = cls.root / "web" / "dashboard" / "components" / "copy-to-clipboard.js"
        cls.dash_tooltip = cls.root / "web" / "dashboard" / "components" / "auto-tooltip.js"
        cls.dash_keyboard = (cls.root / "web" / "dashboard" / "core" / "keyboard.js").read_text(encoding="utf-8")

    # --- app.py : nouveau flow de demarrage ---
    def test_app_starts_rest_before_pywebview(self):
        self.assertIn("_start_rest_server", self.app_py)
        self.assertIn("settings_early", self.app_py)
        self.assertIn("rest_server = _start_rest_server(api, settings_early)", self.app_py)

    def test_app_points_to_dashboard_url(self):
        self.assertIn("http://127.0.0.1", self.app_py)
        self.assertIn("/dashboard/", self.app_py)

    def test_app_injects_token_for_native_mode(self):
        self.assertIn("__CINESORT_NATIVE__", self.app_py)
        self.assertIn("cinesort.dashboard.token", self.app_py)

    def test_app_falls_back_to_legacy_if_no_server(self):
        self.assertIn("rest_server is not None", self.app_py)

    # --- REST server : bind address configurable ---
    def test_rest_server_supports_host_param(self):
        self.assertIn("host: str", self.rest_py)
        self.assertIn("self._host", self.rest_py)
        self.assertIn("(self._host, self._port)", self.rest_py)

    # --- Dashboard app.js : detection native + auto-login ---
    def test_dashboard_detects_native(self):
        self.assertIn("__CINESORT_NATIVE__", self.dash_app_js)
        self.assertIn("isNative", self.dash_app_js)
        self.assertIn("is-native", self.dash_app_js)

    def test_dashboard_bypasses_login_in_native(self):
        # V5B-01 : redirection native vers #/home (au lieu de #/status).
        self.assertIn("isNative && hasToken()", self.dash_app_js)
        self.assertIn("#/home", self.dash_app_js)

    # --- Composants portes ---
    def test_drop_js_exists_and_native_guard(self):
        self.assertTrue(self.dash_drop.exists())
        content = self.dash_drop.read_text(encoding="utf-8")
        self.assertIn("__CINESORT_NATIVE__", content)
        self.assertIn("initDropHandlers", content)
        self.assertIn("validate_dropped_path", content)

    def test_command_palette_exists(self):
        self.assertTrue(self.dash_cmd.exists())
        content = self.dash_cmd.read_text(encoding="utf-8")
        self.assertIn("initCommandPalette", content)
        self.assertIn("cmd-palette", content)
        self.assertIn("Ctrl+K", content) or self.assertIn("Ctrl", content)

    def test_confetti_exists(self):
        self.assertTrue(self.dash_confetti.exists())
        content = self.dash_confetti.read_text(encoding="utf-8")
        self.assertIn("launchConfetti", content)
        self.assertIn("export function", content)

    def test_copy_to_clipboard_exists(self):
        self.assertTrue(self.dash_copy.exists())
        content = self.dash_copy.read_text(encoding="utf-8")
        self.assertIn("initCopyToClipboard", content)
        self.assertIn("data-copy", content)

    def test_auto_tooltip_exists(self):
        self.assertTrue(self.dash_tooltip.exists())
        content = self.dash_tooltip.read_text(encoding="utf-8")
        self.assertIn("initAutoTooltip", content)

    # --- Keyboard : alignement sur desktop ---
    def test_keyboard_has_alt_shortcuts(self):
        self.assertIn("altKey", self.dash_keyboard)
        # Alt+1..8 navigation
        self.assertIn("e.altKey", self.dash_keyboard)

    def test_keyboard_has_ctrl_s(self):
        self.assertIn('toLowerCase() === "s"', self.dash_keyboard)
        self.assertIn("cinesort:save-request", self.dash_keyboard)

    def test_keyboard_has_ctrl_k(self):
        self.assertIn('toLowerCase() === "k"', self.dash_keyboard)
        self.assertIn("cinesort:command-palette", self.dash_keyboard)

    def test_keyboard_has_f1(self):
        self.assertIn("F1", self.dash_keyboard)

    # --- App.js : tous les inits branches ---
    def test_app_initializes_all_native_features(self):
        self.assertIn("initDropHandlers", self.dash_app_js)
        self.assertIn("initCommandPalette", self.dash_app_js)
        self.assertIn("initCopyToClipboard", self.dash_app_js)
        self.assertIn("initAutoTooltip", self.dash_app_js)
        self.assertIn('import "./components/confetti.js"', self.dash_app_js)


if __name__ == "__main__":
    unittest.main()
