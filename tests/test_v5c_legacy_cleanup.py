"""V5C-03 + V6 — Verifie le cleanup post-migration v5.

V6 : `_legacy_globals.js` (shim global) a ete supprime et remplace par
`web/views/_legacy_compat.js` (module ESM importe explicitement). Les vues v5
portees n'utilisent plus de globals `window.X` implicites.

Ces tests verifient :
- Le shim global `_legacy_globals.js` n'existe plus.
- index.html ne charge plus le shim.
- `_legacy_compat.js` ESM existe et expose les helpers.
- home.js (le seul vrai consommateur) importe depuis _legacy_compat.js.
- Les composants v5 shell ne referencent pas window.state/apiCall.
- Documentation `audit/results/v5c-03-shim-restant.md` toujours presente
  (rationale historique conservee pour traçabilite).
"""

from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
LEGACY_GLOBALS_SHIM = REPO / "web" / "dashboard" / "_legacy_globals.js"
LEGACY_COMPAT_ESM = REPO / "web" / "views" / "_legacy_compat.js"
INDEX = REPO / "web" / "dashboard" / "index.html"
HOME_VIEW = REPO / "web" / "views" / "home.js"
DOC = REPO / "audit" / "results" / "v5c-03-shim-restant.md"
COMPONENTS_V5 = (
    "sidebar-v5.js",
    "top-bar-v5.js",
    "breadcrumb.js",
)


class V6LegacyCompatTests(unittest.TestCase):
    """V6 : verifie la migration shim global -> ES module."""

    def test_legacy_globals_shim_removed(self) -> None:
        """V6 : le shim global a ete supprime."""
        self.assertFalse(
            LEGACY_GLOBALS_SHIM.is_file(),
            f"V6 : shim global devrait etre supprime : {LEGACY_GLOBALS_SHIM}",
        )

    def test_legacy_compat_esm_exists(self) -> None:
        """V6 : le remplacant ESM existe."""
        self.assertTrue(
            LEGACY_COMPAT_ESM.is_file(),
            f"V6 : module ESM manquant : {LEGACY_COMPAT_ESM}",
        )

    def test_legacy_compat_exports_all_helpers(self) -> None:
        """V6 : tous les helpers historiques sont exportes."""
        src = LEGACY_COMPAT_ESM.read_text(encoding="utf-8")
        expected = (
            "state",
            "apiCall",
            "setStatusMessage",
            "setPill",
            "flashActionButton",
            "setLastRunContext",
            "appendLogs",
            "loadTable",
            "showView",
            "openPathWithFeedback",
            "resetRunScopedState",
            "fmtSpeed",
            "fmtEta",
            "shortPath",
            "uiConfirm",
        )
        for name in expected:
            with self.subTest(helper=name):
                # Accepte "export const NAME" ou "export function NAME"
                pattern = rf"\bexport\s+(?:const|function|let|var)\s+{name}\b"
                self.assertRegex(
                    src,
                    pattern,
                    f"V6 : helper '{name}' non exporte par _legacy_compat.js",
                )

    def test_index_no_longer_loads_shim(self) -> None:
        """V6 : index.html ne charge plus le shim global."""
        html = INDEX.read_text(encoding="utf-8")
        self.assertNotIn("_legacy_globals.js", html)

    def test_home_imports_from_legacy_compat(self) -> None:
        """V6 : home.js (le vrai consommateur) importe depuis le module ESM."""
        src = HOME_VIEW.read_text(encoding="utf-8")
        self.assertIn(
            './_legacy_compat.js"',
            src,
            "V6 : home.js doit importer depuis ./_legacy_compat.js",
        )

    def test_v5_components_no_window_state(self) -> None:
        """Les composants v5 shell n'utilisent pas window.state ni window.apiCall."""
        components_dir = REPO / "web" / "dashboard" / "components"
        forbidden = ("window.state", "window.apiCall")
        for comp_name in COMPONENTS_V5:
            comp_path = components_dir / comp_name
            if not comp_path.is_file():
                continue
            content = comp_path.read_text(encoding="utf-8")
            for pattern in forbidden:
                with self.subTest(component=comp_name, forbidden=pattern):
                    self.assertNotIn(
                        pattern,
                        content,
                        f"{comp_name} ne devrait pas utiliser {pattern}",
                    )

    def test_audit_doc_still_present(self) -> None:
        """La doc V5C-03 reste pour tracabilite historique."""
        self.assertTrue(DOC.is_file(), f"Doc audit manquante : {DOC}")


if __name__ == "__main__":
    unittest.main()
