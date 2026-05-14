"""Tests statiques pour le cleanup des intervals dashboard (issue #89).

Verifie par inspection du source JS que :
1. state.js expose onClearToken/removeOnClearToken
2. clearToken() invoque les callbacks enregistrees
3. dashboard/app.js stocke les setInterval IDs et les clear au logout
4. Le polling notification fallback verifie hasToken() a chaque tick
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_JS = PROJECT_ROOT / "web" / "dashboard" / "core" / "state.js"
DASH_APP_JS = PROJECT_ROOT / "web" / "dashboard" / "app.js"


class StateOnClearTokenContractTests(unittest.TestCase):
    """state.js doit exposer onClearToken + clearToken invoque les callbacks."""

    def setUp(self) -> None:
        self.src = STATE_JS.read_text(encoding="utf-8")

    def test_on_clear_token_export(self) -> None:
        self.assertIn("export function onClearToken", self.src)

    def test_remove_on_clear_token_export(self) -> None:
        self.assertIn("export function removeOnClearToken", self.src)

    def test_clear_token_invokes_callbacks(self) -> None:
        """clearToken doit boucler sur _onClearCallbacks et appeler chaque cb."""
        # Apres la signature `export function clearToken`, on doit trouver
        # une iteration `for (const cb of _onClearCallbacks)` avant la fin.
        start = self.src.find("export function clearToken")
        self.assertGreater(start, 0)
        # Cherche le pattern d'invocation des callbacks dans les 600 chars
        # qui suivent (corps de la fonction).
        body_window = self.src[start : start + 600]
        self.assertIn("_onClearCallbacks", body_window)
        self.assertIn("cb()", body_window)


class DashboardAppIntervalCleanupTests(unittest.TestCase):
    """dashboard/app.js doit stocker les interval IDs et les clear via onClearToken."""

    def setUp(self) -> None:
        self.src = DASH_APP_JS.read_text(encoding="utf-8")

    def test_imports_on_clear_token(self) -> None:
        self.assertIn("onClearToken", self.src)

    def test_registers_cleanup_callback(self) -> None:
        """Un appel onClearToken(...) doit etre present pour cleanup les intervals."""
        self.assertIn("onClearToken(()", self.src)

    def test_clears_sidebar_counters_interval(self) -> None:
        self.assertIn("_sidebarCountersInterval", self.src)
        self.assertIn("clearInterval(_sidebarCountersInterval)", self.src)

    def test_clears_update_badge_interval(self) -> None:
        self.assertIn("_updateBadgeInterval", self.src)
        self.assertIn("clearInterval(_updateBadgeInterval)", self.src)

    def test_clears_notification_fallback_interval(self) -> None:
        self.assertIn("_notificationFallbackInterval", self.src)
        self.assertIn("clearInterval(_notificationFallbackInterval)", self.src)

    def test_notification_fallback_checks_has_token(self) -> None:
        """Le fallback setInterval doit faire if (!hasToken()) return; au debut."""
        # On cherche la boucle interval et un check hasToken a l'interieur
        match = re.search(
            r"_notificationFallbackInterval\s*=\s*setInterval\(async\s*\(\)\s*=>\s*\{[^}]*?hasToken\(\)",
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Le tick fallback doit verifier hasToken()")


if __name__ == "__main__":
    unittest.main(verbosity=2)
