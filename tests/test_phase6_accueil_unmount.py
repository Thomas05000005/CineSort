"""Tests Phase 6 — Spec 05 (completion 94 -> 100%) : unmountAccueil cleanup.

La vue Accueil doit exporter une fonction unmount qui :
- Stoppe les intervals de polling (scan en cours, get_dashboard).
- Abort tous les fetchs en cours via un AbortController dedie.
- Release les references container pour eviter les leaks memoire.

L'app.js doit cabler `unmountAccueil` comme cleanup callback de la route /accueil
(return value de init -> registerRoute mecanisme standard du router).
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ACCUEIL_JS = _ROOT / "web" / "dashboard" / "views" / "accueil.js"
_APP_JS = _ROOT / "web" / "dashboard" / "app.js"


class UnmountExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_unmount_accueil_exported(self) -> None:
        self.assertIn("export function unmountAccueil(", self.js)

    def test_unmount_stops_scan_polling(self) -> None:
        """unmountAccueil() doit appeler _stopScanPolling()."""
        idx = self.js.find("export function unmountAccueil(")
        self.assertGreater(idx, 0)
        body = self.js[idx : idx + 600]
        self.assertIn("_stopScanPolling()", body)

    def test_unmount_aborts_pending_fetches(self) -> None:
        """unmountAccueil() doit abort le controller des fetchs en cours."""
        idx = self.js.find("export function unmountAccueil(")
        body = self.js[idx : idx + 600]
        self.assertIn(".abort()", body)
        self.assertIn("_abortController", body)


class AbortControllerWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ACCUEIL_JS.read_text(encoding="utf-8")

    def test_abort_controller_created_in_init(self) -> None:
        """initAccueil cree un AbortController pour les fetchs de cette vue."""
        self.assertIn("new AbortController()", self.js)

    def test_init_calls_unmount_before_remount(self) -> None:
        """Re-entrant safety : initAccueil appelle unmountAccueil() en preambule."""
        idx = self.js.find("export async function initAccueil(")
        self.assertGreater(idx, 0)
        body = self.js[idx : idx + 1500]
        self.assertIn("unmountAccueil()", body)

    def test_abort_signal_passed_to_fetches(self) -> None:
        """Le signal AbortController est propage aux apiPost (run/get_dashboard, etc.)."""
        # On verifie que { signal } est passe en 3e arg d'apiPost.
        self.assertIn('apiPost("run/get_dashboard", { run_id: "latest" }, { signal })', self.js)


class AppJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_unmount_imported(self) -> None:
        """app.js importe unmountAccueil depuis views/accueil.js."""
        self.assertIn("import { initAccueil, unmountAccueil }", self.js)

    def test_route_accueil_returns_unmount(self) -> None:
        """registerRoute(/accueil) retourne unmountAccueil comme cleanup callback."""
        # Pattern : init: (el, opts) => { initAccueil(el, opts); return unmountAccueil; }
        self.assertIn('registerRoute("/accueil"', self.js)
        # On cherche le bloc complet : init handler retournant unmountAccueil.
        idx = self.js.find('registerRoute("/accueil"')
        self.assertGreater(idx, 0)
        block = self.js[idx : idx + 400]
        self.assertIn("initAccueil(el", block)
        self.assertIn("return unmountAccueil", block)


if __name__ == "__main__":
    unittest.main()
