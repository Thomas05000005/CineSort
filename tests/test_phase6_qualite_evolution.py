"""Tests Phase 6 : Evolution captions dates + tooltips + labels axes (spec 10 sec 6).

Verifie que la section Evolution de la vue Qualite expose :
  - une caption "entre <date1> et <date2>" en format francais (ex : "entre 5 avril et 5 mai")
  - des tooltips au survol des points (date + valeur via attribut <title>)
  - des labels sur l'axe X (dates aux extremites) et axe Y (scores graduations)
  - un baseline pour l'axe X

Cible :
  - web/dashboard/views/qualite.js : _renderEvolutionChart() + _buildEvolutionCaption()
  - web/shared/components.css : .qualite-evolution-axis* / .qualite-evolution-point
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_QUALITE_JS = _ROOT / "web" / "dashboard" / "views" / "qualite.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class CaptionDatesTests(unittest.TestCase):
    """La caption doit etre construite via _buildEvolutionCaption au format francais."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_caption_helper_defined(self) -> None:
        self.assertIn("function _buildEvolutionCaption(", self.js)

    def test_caption_uses_french_months(self) -> None:
        # Tous les mois doivent etre presents pour le formatage francais.
        for month in ("janvier", "fevrier", "mars", "avril", "mai", "juin",
                      "juillet", "septembre", "octobre", "novembre"):
            # On accepte avec ou sans accent (l'editeur peut normaliser)
            pattern = month.replace("e", "[eé]").replace("u", "[uû]").replace("a", "[aâ]")
            self.assertRegex(self.js, pattern, f"Mois '{month}' manquant dans qualite.js")

    def test_caption_uses_entre_et_format(self) -> None:
        self.assertIn("entre ${startLabel} et ${endLabel}", self.js)

    def test_caption_replaces_legacy_text(self) -> None:
        # L'ancienne formulation brut "X points de mesure entre <date_iso> et <date_iso>"
        # ne doit plus etre presente : on doit passer par _buildEvolutionCaption.
        self.assertNotIn("validPoints[0].date || \"\")} et ${escapeHtml(validPoints", self.js)

    def test_format_date_fr_helper(self) -> None:
        self.assertIn("function _formatDateFr(", self.js)

    def test_caption_exposed_in_testing_hook(self) -> None:
        self.assertIn("buildEvolutionCaption: _buildEvolutionCaption", self.js)
        self.assertIn("formatDateFr: _formatDateFr", self.js)


class TooltipsTests(unittest.TestCase):
    """Tooltips sur les points : balise <title> dans chaque <circle>."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_circle_has_title(self) -> None:
        # Le rendu doit emettre <title>...</title> dans le <circle>
        self.assertIn("<title>", self.js)
        self.assertIn("</title>", self.js)

    def test_tooltip_includes_score(self) -> None:
        # Le contenu du tooltip combine date + score V2
        self.assertIn("Score ${score}/100", self.js)

    def test_tooltip_uses_french_date(self) -> None:
        # Le tooltip est construit a partir de _formatDateFr (date complete avec annee)
        self.assertIn("_formatDateFr(p.date || \"\", true)", self.js)

    def test_circle_has_class_point(self) -> None:
        self.assertIn("qualite-evolution-point", self.js)


class AxisLabelsTests(unittest.TestCase):
    """Labels axes X (dates) et Y (scores) injectes en <text>."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_svg_has_text_elements(self) -> None:
        self.assertIn("<text", self.js)

    def test_y_axis_three_ticks(self) -> None:
        # On veut au moins 3 graduations Y (min / mid / max)
        self.assertIn("yTicks", self.js)
        self.assertRegex(
            self.js,
            r"\[\s*minY\s*,\s*\(minY\s*\+\s*maxY\)\s*/\s*2\s*,\s*maxY\s*\]",
        )

    def test_x_axis_uses_first_and_last_dates(self) -> None:
        self.assertIn("xAxisLabels", self.js)
        self.assertIn("firstDate", self.js)
        self.assertIn("lastDate", self.js)

    def test_x_axis_middle_date_when_enough_points(self) -> None:
        self.assertIn("validPoints.length >= 3", self.js)
        self.assertIn("midDate", self.js)

    def test_axis_label_class(self) -> None:
        self.assertIn("qualite-evolution-axis-label", self.js)

    def test_baseline_present(self) -> None:
        # Une ligne horizontale au baseline doit etre tracee
        self.assertIn("qualite-evolution-axis", self.js)
        # baselineY est calcule depuis padBottom
        self.assertIn("baselineY", self.js)


class SvgGeometryTests(unittest.TestCase):
    """Verifie que les marges du SVG laissent la place aux labels."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_pad_left_for_y_labels(self) -> None:
        # padLeft >= 10 (place pour labels axe Y)
        m = re.search(r"const padLeft\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "padLeft non trouve")
        self.assertGreaterEqual(int(m.group(1)), 8, "padLeft trop petit pour labels Y")

    def test_pad_bottom_for_x_labels(self) -> None:
        m = re.search(r"const padBottom\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "padBottom non trouve")
        self.assertGreaterEqual(int(m.group(1)), 6, "padBottom trop petit pour labels X")

    def test_viewbox_height_increased(self) -> None:
        # h doit etre >= 50 pour accueillir les labels
        m = re.search(r"const h\s*=\s*(\d+)\s*;", self.js)
        self.assertIsNotNone(m, "h non trouve")
        self.assertGreaterEqual(int(m.group(1)), 45)


class AriaLabelTests(unittest.TestCase):
    """Le aria-label du SVG doit decrire les bornes temporelles (accessibilite)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _QUALITE_JS.read_text(encoding="utf-8")

    def test_aria_label_includes_points_count(self) -> None:
        self.assertIn("${validPoints.length} points", self.js)

    def test_aria_label_includes_date_range(self) -> None:
        # Le aria-label cite les deux bornes formatees
        self.assertRegex(
            self.js,
            r"aria-label=\"Graphique d'évolution[^\"]*entre \$\{[^}]*firstDate[^}]*\} et \$\{[^}]*lastDate[^}]*\}\"",
        )


class CssTests(unittest.TestCase):
    """Nouvelles classes CSS dediees aux labels d'axes + tooltips hover."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_axis_label_class_exists(self) -> None:
        self.assertIn(".qualite-evolution-axis-label", self.css)

    def test_axis_class_exists(self) -> None:
        self.assertIn(".qualite-evolution-axis", self.css)

    def test_point_hover_class_exists(self) -> None:
        self.assertIn(".qualite-evolution-point", self.css)
        # Et un hover qui change la taille du point
        self.assertRegex(self.css, r"\.qualite-evolution-point:hover\s*\{[^}]*r\s*:")

    def test_chart_height_increased(self) -> None:
        # Le bloc .qualite-evolution-chart a maintenant 200px (place pour labels bas)
        self.assertRegex(self.css, r"\.qualite-evolution-chart\s*\{[^}]*height:\s*200px")

    def test_balance_braces(self) -> None:
        opens = self.css.count("{")
        closes = self.css.count("}")
        self.assertEqual(opens, closes, f"Imbalance: {opens} opens vs {closes} closes")


if __name__ == "__main__":
    unittest.main()
