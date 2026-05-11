"""Tests Phases D+E — UI comparaison qualite doublons.

Couvre :
- Desktop execution.js : table comparative, badges, score, formatFileSize, comparison fallback
- Dashboard review.js : vue cote-a-cote dans modale, badges, formatSize
- CSS : classes comparaison dans app + dashboard
- HTML : modale compare presente
"""

from __future__ import annotations

import unittest
from pathlib import Path


# ---------------------------------------------------------------------------
# Desktop — execution.js
# ---------------------------------------------------------------------------


class ExecutionCompareStructureTests(unittest.TestCase):
    """Tests structure de la comparaison dans execution.js."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (Path(__file__).resolve().parents[1] / "web" / "views" / "execution.js").read_text(encoding="utf-8")

    def test_render_comparison_badge(self) -> None:
        self.assertIn("_renderComparisonBadge", self.js)

    def test_show_comparison_modal(self) -> None:
        self.assertIn("_showComparisonModal", self.js)

    def test_build_comparison_html(self) -> None:
        self.assertIn("_buildComparisonHtml", self.js)

    def test_criterion_badge(self) -> None:
        self.assertIn("_criterionBadge", self.js)

    def test_format_file_size(self) -> None:
        self.assertIn("_formatFileSize", self.js)

    def test_format_file_size_units(self) -> None:
        """fmtFileSize (mutualise dans core/format.js) gere Ko, Mo, Go, To."""
        fmt_js = (Path(__file__).resolve().parents[1] / "web" / "core" / "format.js").read_text(encoding="utf-8")
        for unit in ("Ko", "Mo", "Go"):
            self.assertIn(unit, fmt_js)

    def test_comparison_has_side_by_side_cards(self) -> None:
        """P3.1 : rendu côte-à-côte avec cards Version A / Version B."""
        self.assertIn("compare-card", self.js)
        self.assertIn("Version ${side.toUpperCase()}", self.js)

    def test_comparison_details_table_still_present(self) -> None:
        """Table détail critère par critère conservée en details (expand)."""
        self.assertIn("compare-table", self.js)
        self.assertIn("Critère", self.js)  # accent déjà utilisé
        self.assertIn("Version A", self.js)
        self.assertIn("Version B", self.js)

    def test_verdict_displayed_in_card(self) -> None:
        """P3.1 : chaque card affiche un verdict (À conserver / Supprimable)."""
        self.assertIn("verdict_a", self.js)
        self.assertIn("verdict_b", self.js)

    def test_quality_info_in_card(self) -> None:
        """P3.1 : la card contient score + tier."""
        self.assertIn("quality_a", self.js)
        self.assertIn("quality_b", self.js)

    def test_file_name_in_card(self) -> None:
        self.assertIn("file_a_name", self.js)
        self.assertIn("file_b_name", self.js)

    def test_size_savings_display(self) -> None:
        self.assertIn("size_savings", self.js)

    def test_recommendation_display(self) -> None:
        self.assertIn("recommendation", self.js)

    def test_fallback_without_comparison(self) -> None:
        """Sans comparison, l'ancienne vue est affichee (pas de regression)."""
        # Le code verifie g.comparison avant d'afficher la vue enrichie
        self.assertIn("g.comparison", self.js)


class DesktopHtmlCompareTests(unittest.TestCase):
    """Tests HTML : modale comparaison presente."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    def test_modal_compare_exists(self) -> None:
        self.assertIn('id="modalCompare"', self.html)

    def test_modal_compare_has_body(self) -> None:
        self.assertIn("modal-body", self.html)

    def test_modal_compare_has_close(self) -> None:
        self.assertIn('data-close="modalCompare"', self.html)


class DesktopCssCompareTests(unittest.TestCase):
    """Tests CSS comparaison dans app desktop."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = (Path(__file__).resolve().parents[1] / "web" / "styles.css").read_text(encoding="utf-8")

    def test_compare_table_class(self) -> None:
        self.assertIn(".compare-table", self.css)

    def test_compare_score_class(self) -> None:
        self.assertIn(".compare-score", self.css)

    def test_compare_winner_class(self) -> None:
        self.assertIn(".compare-winner", self.css)


# ---------------------------------------------------------------------------
# Dashboard — review.js
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/review.js supprime — adaptation v5 deferee a V5C-03")
class DashboardReviewCompareTests(unittest.TestCase):
    """Tests comparaison dans le dashboard review.js."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "review.js").read_text(
            encoding="utf-8"
        )

    def test_build_dash_comparison_html(self) -> None:
        self.assertIn("_buildDashComparisonHtml", self.js)

    def test_format_size(self) -> None:
        self.assertIn("_fmtSize", self.js)

    def test_comparison_check_in_preview(self) -> None:
        """_onPreview verifie g.comparison pour afficher la vue enrichie."""
        self.assertIn("g.comparison", self.js)

    def test_comparison_table_in_dashboard(self) -> None:
        """Table détail critères toujours présente (en details)."""
        self.assertIn("compare-table", self.js)

    def test_comparison_cards_side_by_side(self) -> None:
        """P3.1 : rendu côte-à-côte (cards Version A / Version B)."""
        self.assertIn("compare-card", self.js)
        self.assertIn("Version A", self.js)
        self.assertIn("Version B", self.js)

    def test_comparison_verdict_dashboard(self) -> None:
        """P3.1 : verdict par card (À conserver / Supprimable)."""
        self.assertIn("verdict_a", self.js)
        self.assertIn("verdict_b", self.js)

    def test_comparison_quality_info_dashboard(self) -> None:
        """P3.1 : score + tier affiché dans la card."""
        self.assertIn("quality_a", self.js)
        self.assertIn("quality_b", self.js)

    def test_size_savings_in_dashboard(self) -> None:
        self.assertIn("size_savings", self.js)

    def test_fallback_without_comparison_dashboard(self) -> None:
        """Sans comparison, un texte simple est affiche (doublon ou conflit plan)."""
        self.assertIn("plan_conflict", self.js)

    def test_groups_iteration(self) -> None:
        """Le preview itere sur les groups (pas sur duplicates/conflicts)."""
        self.assertIn("for (const g of groups)", self.js)

    def test_format_size_units(self) -> None:
        """fmtBytes (mutualise dans dashboard/core/format.js) gere Ko, Mo, Go, To."""
        fmt_js = (Path(__file__).resolve().parents[1] / "web" / "dashboard" / "core" / "format.js").read_text(
            encoding="utf-8"
        )
        for unit in ("Ko", "Go"):
            self.assertIn(unit, fmt_js)


class DashboardCssCompareTests(unittest.TestCase):
    """Tests CSS comparaison dans le dashboard."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = (Path(__file__).resolve().parents[1] / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_compare_table_class(self) -> None:
        self.assertIn(".compare-table", self.css)

    def test_compare_score_class(self) -> None:
        self.assertIn(".compare-score", self.css)


if __name__ == "__main__":
    unittest.main()
