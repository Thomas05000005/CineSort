"""V2-07 — Tests structurels du composant EmptyState.

Verifie que :
- la factory buildEmptyState et le helper bindEmptyStateCta existent
- les vues quality.js et validation.js (desktop) utilisent le composant
- les classes CSS .empty-state* sont definies (variantes + CTA)
- la version ES module existe pour le dashboard distant
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class EmptyStateComponentTests(unittest.TestCase):
    def test_buildEmptyState_function_exists(self) -> None:
        src = (_ROOT / "web/components/empty-state.js").read_text(encoding="utf-8")
        self.assertIn("function buildEmptyState(", src)
        self.assertIn("function bindEmptyStateCta(", src)
        # Backwards-compat : les anciennes fonctions doivent rester en place.
        self.assertIn("function buildEmptyStateHtml(", src)
        self.assertIn("function buildTableEmptyRow(", src)

    def test_dashboard_es_module_mirror_exists(self) -> None:
        src = (_ROOT / "web/dashboard/components/empty-state.js").read_text(encoding="utf-8")
        self.assertIn("export function buildEmptyState(", src)
        self.assertIn("export function bindEmptyStateCta(", src)

    def test_views_use_component(self) -> None:
        for view in ["web/views/quality.js", "web/views/validation.js"]:
            src = (_ROOT / view).read_text(encoding="utf-8")
            # Au moins l'un des 2 helpers doit etre appele.
            self.assertTrue(
                "buildEmptyState(" in src or "bindEmptyStateCta(" in src,
                f"{view} : ne semble pas utiliser le composant EmptyState",
            )

    @unittest.skip("V5C-01: dashboard/views/quality.js supprime — la vue Qualite est desormais qij-v5 (couvert par test_v5b_activation et test_qij_v5_ported)")
    def test_dashboard_quality_uses_component(self) -> None:
        src = (_ROOT / "web/dashboard/views/quality.js").read_text(encoding="utf-8")
        self.assertIn("buildEmptyState", src)
        self.assertIn("bindEmptyStateCta", src)
        # L'import ES module doit etre present.
        self.assertIn('from "../components/empty-state.js"', src)

    def test_library_history_use_component_indirectly(self) -> None:
        # library-v5.js utilise window.buildEmptyState, history.js passe par
        # renderGenericTable qui supporte desormais emptyCta (V2-07).
        lib_src = (_ROOT / "web/views/library-v5.js").read_text(encoding="utf-8")
        self.assertIn("buildEmptyState", lib_src)
        hist_src = (_ROOT / "web/views/history.js").read_text(encoding="utf-8")
        self.assertIn("emptyCta", hist_src)
        table_src = (_ROOT / "web/components/table.js").read_text(encoding="utf-8")
        self.assertIn("emptyCta", table_src)
        self.assertIn("buildEmptyState", table_src)

    def test_css_classes_defined(self) -> None:
        css_files = [
            _ROOT / "web/styles.css",
            _ROOT / "web/dashboard/styles.css",
        ]
        for f in css_files:
            self.assertTrue(f.exists(), f"CSS introuvable : {f}")
            css = f.read_text(encoding="utf-8")
            self.assertIn(".empty-state", css, f"{f.name} : .empty-state manquant")
            self.assertIn(".empty-state__cta", css, f"{f.name} : .empty-state__cta manquant")
            # Au moins une variante doit etre definie.
            self.assertTrue(
                ".empty-state--card" in css or ".empty-state--inline" in css or ".empty-state--fullscreen" in css,
                f"{f.name} : aucune variante .empty-state-- definie",
            )


if __name__ == "__main__":
    unittest.main()
