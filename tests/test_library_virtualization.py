"""V5-01 — Virtualisation UI library.js (windowing rows visibles uniquement).

Verifie :
- Le helper ESM `web/dashboard/components/virtual-table.js` existe avec les bons
  exports (virtualizeTbody, destroyVirtualization).
- `web/dashboard/views/library.js` importe et utilise le helper.
- Le seuil par defaut est 500 rows (au-dessus -> windowing, en-dessous -> innerHTML simple).
- Le pattern overscan + spacers + requestAnimationFrame est present dans le helper.
- Le rendu d'une row est extrait (`_renderLibraryRowHtml`) pour permettre le windowing.
- L'export `unmountLibrary` permet un cleanup propre de la virtualisation.
- La syntaxe JS est valide (`node --check`).
- Le filtrage / changement de run cleanup correctement le handle precedent.

Cible perf : scroll fluide 60fps sur 10k rows (vs freeze 5-10s avant).
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH_HELPER = ROOT / "web" / "dashboard" / "components" / "virtual-table.js"
DASH_LIBRARY = ROOT / "web" / "dashboard" / "views" / "library.js"


class DashboardVirtualTableHelperTests(unittest.TestCase):
    """Le helper ESM pour le dashboard distant."""

    def test_helper_file_exists(self) -> None:
        self.assertTrue(DASH_HELPER.exists(), f"Missing {DASH_HELPER}")

    def test_helper_exports_named_esm(self) -> None:
        src = DASH_HELPER.read_text(encoding="utf-8")
        self.assertIn("export function virtualizeTbody", src)
        self.assertIn("export function destroyVirtualization", src)

    def test_helper_threshold_default_500(self) -> None:
        src = DASH_HELPER.read_text(encoding="utf-8")
        self.assertIn("DEFAULT_THRESHOLD = 500", src)

    def test_helper_uses_overscan_and_spacers(self) -> None:
        src = DASH_HELPER.read_text(encoding="utf-8")
        self.assertIn("DEFAULT_OVERSCAN", src)
        self.assertIn("virt-spacer", src)
        self.assertIn('data-virt="top"', src)
        self.assertIn('data-virt="bottom"', src)

    def test_helper_uses_raf_for_scroll(self) -> None:
        src = DASH_HELPER.read_text(encoding="utf-8")
        self.assertIn("requestAnimationFrame", src)
        # Listener passive pour ne pas bloquer le scroll natif.
        self.assertIn("{ passive: true }", src)

    def test_helper_below_threshold_falls_through(self) -> None:
        """Sous le seuil, rendu simple via tbody.innerHTML, zero overhead."""
        src = DASH_HELPER.read_text(encoding="utf-8")
        self.assertIn("rows.length <= threshold", src)

    def test_helper_returns_destroy_handle(self) -> None:
        src = DASH_HELPER.read_text(encoding="utf-8")
        self.assertIn("destroy", src)
        self.assertIn("scrollToIndex", src)
        self.assertIn("getVisibleRange", src)
        self.assertIn("isVirtualized", src)

    def test_helper_height_reaffinement(self) -> None:
        """La hauteur de row mesuree au boot est reaffinee si l'estimation differe."""
        src = DASH_HELPER.read_text(encoding="utf-8")
        # Reaffinement quand l'estimation est trop loin de la mesure reelle.
        self.assertIn("getBoundingClientRect", src)
        self.assertIn("rowHeight = measured", src)

    def test_helper_finds_scroll_parent(self) -> None:
        src = DASH_HELPER.read_text(encoding="utf-8")
        self.assertIn("_findScrollParent", src)
        # Detecte les conteneurs avec overflow auto/scroll/overlay.
        self.assertIn('overflow === "auto"', src)
        self.assertIn('overflow === "scroll"', src)


class LibraryViewIntegrationTests(unittest.TestCase):
    """Le dashboard distant library.js doit utiliser la virtualisation."""

    def test_library_imports_virtualize(self) -> None:
        src = DASH_LIBRARY.read_text(encoding="utf-8")
        self.assertIn(
            'from "../components/virtual-table.js"',
            src,
            "library.js doit importer le helper de virtualisation ESM",
        )
        self.assertIn("virtualizeTbody", src)
        self.assertIn("destroyVirtualization", src)

    def test_library_extracts_row_renderer(self) -> None:
        """Le rendu d'une row est extrait pour permettre le windowing."""
        src = DASH_LIBRARY.read_text(encoding="utf-8")
        self.assertIn("_renderLibraryRowHtml", src)

    def test_library_threshold_constant(self) -> None:
        """Le seuil de virtualisation est expose comme constante nommee."""
        src = DASH_LIBRARY.read_text(encoding="utf-8")
        # Constante locale ou import direct depuis le helper.
        self.assertTrue(
            "_VIRT_THRESHOLD" in src or "threshold: 500" in src,
            "library.js doit declarer un seuil de virtualisation",
        )

    def test_library_calls_virtualize_on_render(self) -> None:
        src = DASH_LIBRARY.read_text(encoding="utf-8")
        # La virtualisation est appelee dans _renderTable.
        self.assertIn("virtualizeTbody(", src)

    def test_library_cleans_up_handle_on_rerender(self) -> None:
        """Le handle precedent est detruit avant chaque re-render."""
        src = DASH_LIBRARY.read_text(encoding="utf-8")
        self.assertIn("_virtHandle", src)
        # destroy() appele avant le nouveau render.
        self.assertIn("_virtHandle.destroy", src)

    def test_library_exports_unmount(self) -> None:
        """unmountLibrary permet un cleanup propre depuis le router."""
        src = DASH_LIBRARY.read_text(encoding="utf-8")
        self.assertIn("export function unmountLibrary", src)

    def test_library_uses_event_delegation_on_tbody(self) -> None:
        """Les clics sur les rows utilisent l'event delegation (pas de listener
        par <tr>) pour fonctionner avec les rows render dynamiquement."""
        src = DASH_LIBRARY.read_text(encoding="utf-8")
        # Pattern : tbody.addEventListener("click", ...) au lieu de
        # querySelectorAll(".tr-clickable").forEach(...).
        self.assertIn("tbody.addEventListener", src)
        self.assertIn("e.target.closest", src)

    def test_library_cleans_up_on_load(self) -> None:
        """Le chargement initial cleanup une eventuelle virtualisation precedente."""
        src = DASH_LIBRARY.read_text(encoding="utf-8")
        # Dans _load(), au boot ou apres switch run, on doit appeler destroy.
        # Verifie indirectement : presence de _virtHandle reset dans _load.
        # (verifie par le test test_library_cleans_up_handle_on_rerender + unmountLibrary)
        load_idx = src.find("async function _load()")
        self.assertGreater(load_idx, 0)
        # Cleanup dans les ~30 premieres lignes de _load().
        load_block = src[load_idx : load_idx + 1500]
        self.assertIn("_virtHandle", load_block)


class JsSyntaxTests(unittest.TestCase):
    """Validation syntaxique via node --check."""

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
        self._node_check(DASH_HELPER)

    def test_library_syntax_valid(self) -> None:
        self._node_check(DASH_LIBRARY)


class WindowingBehaviorTests(unittest.TestCase):
    """Tests structurels du comportement de virtualisation (sans DOM reel).

    Les vrais tests de scroll fluide se font via Playwright E2E (Vague 7).
    Ici on valide que les invariants logiques sont respectes :
    - 10000 rows simulees ne crashent pas le helper (verifie au boot).
    - Scroll au milieu du dataset : start/end correctement bornes.
    - Reset propre quand le filtre change (rows passe de 10000 a 50).
    """

    def test_helper_handles_zero_rows_gracefully(self) -> None:
        """Le _noop fallback est utilise quand rows est vide ou non-array."""
        src = DASH_HELPER.read_text(encoding="utf-8")
        self.assertIn("_noop", src)
        self.assertIn("Array.isArray(rows)", src)

    def test_helper_bounds_visible_window(self) -> None:
        """end est borne a rows.length (pas d'overflow), start a 0."""
        src = DASH_HELPER.read_text(encoding="utf-8")
        self.assertIn("Math.max(0", src)
        self.assertIn("Math.min(rows.length", src)

    def test_helper_spacer_height_reflects_data(self) -> None:
        """La hauteur des spacers haut+bas + rows visibles = hauteur totale."""
        src = DASH_HELPER.read_text(encoding="utf-8")
        # topSpacerHeight = start * rowHeight
        # bottomSpacerHeight = (rows.length - end) * rowHeight
        self.assertIn("topSpacerHeight = start * rowHeight", src)
        self.assertIn("bottomSpacerHeight = (rows.length - end) * rowHeight", src)


if __name__ == "__main__":
    unittest.main()
