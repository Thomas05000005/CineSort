"""H-5 — virtualisation tables UI.

Verifie que :
- Le helper `web/components/virtual-table.js` existe avec les bons exports.
- `validation.js` utilise le helper pour les listes >500 films.
- Le helper est inclus dans `index.html` apres les autres composants.
- La syntaxe JS est valide (via `node --check`).
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "web" / "components" / "virtual-table.js"
VALIDATION = ROOT / "web" / "views" / "validation.js"
INDEX_HTML = ROOT / "web" / "index.html"


class VirtualTableHelperTests(unittest.TestCase):
    def test_helper_file_exists(self) -> None:
        self.assertTrue(HELPER.exists(), f"Missing {HELPER}")

    def test_helper_exposes_window_global(self) -> None:
        src = HELPER.read_text(encoding="utf-8")
        self.assertIn("window.VirtualTable", src)
        self.assertIn("virtualizeTbody", src)

    def test_helper_threshold_default(self) -> None:
        src = HELPER.read_text(encoding="utf-8")
        # Default threshold doit etre 500 (commentaire + constante)
        self.assertIn("DEFAULT_THRESHOLD = 500", src)

    def test_helper_uses_overscan_and_spacers(self) -> None:
        src = HELPER.read_text(encoding="utf-8")
        self.assertIn("DEFAULT_OVERSCAN", src)
        self.assertIn("virt-spacer", src)
        self.assertIn('data-virt="top"', src)
        self.assertIn('data-virt="bottom"', src)

    def test_helper_uses_raf_for_scroll(self) -> None:
        src = HELPER.read_text(encoding="utf-8")
        self.assertIn("requestAnimationFrame", src)
        # Listener passive pour ne pas bloquer le scroll
        self.assertIn("{ passive: true }", src)

    def test_helper_below_threshold_falls_through(self) -> None:
        """Sous le seuil, le helper retombe sur tbody.innerHTML simple."""
        src = HELPER.read_text(encoding="utf-8")
        # Branche fallback presente
        self.assertIn("rows.length <= threshold", src)

    def test_helper_returns_destroy_handle(self) -> None:
        src = HELPER.read_text(encoding="utf-8")
        self.assertIn("destroy", src)
        self.assertIn("scrollToIndex", src)


class ValidationIntegrationTests(unittest.TestCase):
    def test_validation_uses_virtual_table(self) -> None:
        src = VALIDATION.read_text(encoding="utf-8")
        self.assertIn("window.VirtualTable", src)
        self.assertIn("virtualizeTbody", src)

    def test_validation_extracts_row_renderer(self) -> None:
        src = VALIDATION.read_text(encoding="utf-8")
        self.assertIn("_renderValidationRowHtml", src)

    def test_validation_threshold_500(self) -> None:
        src = VALIDATION.read_text(encoding="utf-8")
        self.assertIn("threshold: 500", src)

    def test_bulk_check_iterates_filtered_not_dom(self) -> None:
        """Bulk check/uncheck doit iterer sur getFilteredRows() pour
        couvrir aussi les lignes hors fenetre virtualisee."""
        import re

        src = VALIDATION.read_text(encoding="utf-8")
        self.assertNotIn(
            "qsa(\"#planTbody input[type='checkbox'][data-ok]\").forEach(ch => {\n      ch.checked = true;",
            src,
        )
        # btnCheckVisible doit declencher une boucle sur getFilteredRows
        m = re.search(
            r"btnCheckVisible[^}]*?for \(const row of getFilteredRows\(\)\)",
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "btnCheckVisible doit iterer sur getFilteredRows()")

    def test_index_html_includes_helper_before_validation_view(self) -> None:
        src = INDEX_HTML.read_text(encoding="utf-8")
        i_helper = src.find("components/virtual-table.js")
        i_validation = src.find("views/validation.js")
        self.assertGreater(i_helper, 0, "virtual-table.js absent du HTML")
        if i_validation > 0:
            self.assertLess(i_helper, i_validation, "Le helper doit etre charge avant validation.js")


class JsSyntaxTests(unittest.TestCase):
    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node introuvable dans le PATH")

    def _node_check(self, path: Path) -> None:
        result = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, f"node --check {path}: {result.stderr}")

    def test_helper_syntax_valid(self) -> None:
        self._node_check(HELPER)

    def test_validation_syntax_valid(self) -> None:
        self._node_check(VALIDATION)


if __name__ == "__main__":
    unittest.main()
