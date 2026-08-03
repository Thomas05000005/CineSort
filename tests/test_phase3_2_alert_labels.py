"""Tests Phase 3.2 : core/alert-labels.js + integration film-detail (spec 06)."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ALERT_LABELS = _ROOT / "web" / "dashboard" / "core" / "alert-labels.js"
# R8-053/054/055 (F5, D1) : vue standalone views/film-detail.js SUPPRIMÉE ;
# le composant components/film-detail.js est la fiche film canonique (intègre
# alert-labels avec les mêmes features, classes film-detail-alert* au lieu de v5-film-alert*).
_FILM_DETAIL = _ROOT / "web" / "dashboard" / "components" / "film-detail.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FileExistsTests(unittest.TestCase):
    def test_alert_labels_exists(self) -> None:
        self.assertTrue(_ALERT_LABELS.is_file())


class AlertLabelsApiTests(unittest.TestCase):
    """Spec 06 §3.3 : alertes humanisees, mapping flag -> label/icon/severity."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ALERT_LABELS.read_text(encoding="utf-8")

    def test_exports(self) -> None:
        for fn in ("labelForFlag", "labelsForFlags", "countBySeverity", "worstSeverity"):
            self.assertIn(f"export function {fn}", self.js)

    def test_main_flags_mapped(self) -> None:
        """Flags identifies dans cinesort/{app,domain} sont tous mappes."""
        for flag in (
            "nfo_title_mismatch",
            "nfo_file_mismatch",
            "nfo_year_mismatch",
            "title_ambiguity_detected",
            "year_conflict_folder_file",
            "tmdb_year_delta",
            "omdb_disagree",
            "root_level_source",
            "not_a_movie",
            "integrity_header_invalid",
            "subtitle_missing_fr",
            "subtitle_missing",
            "subtitle_orphan",
            "subtitle_duplicate_lang",
            "duplicate_cross_root",
            "low_bitrate",
            "runtime_mismatch",
        ):
            self.assertIn(f"{flag}:", self.js, f"flag {flag} non mappe")

    def test_severities(self) -> None:
        for sev in ('"critical"', '"warning"', '"info"'):
            self.assertIn(sev, self.js)

    def test_default_fallback(self) -> None:
        """Si flag inconnu, code brut utilise en label."""
        self.assertIn("DEFAULT", self.js)


class FilmDetailIntegrationTests(unittest.TestCase):
    """Spec 06 §3.3 : film-detail.js utilise alert-labels.js."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _FILM_DETAIL.read_text(encoding="utf-8")

    def test_imports_alert_labels(self) -> None:
        self.assertIn("alert-labels.js", self.js)
        self.assertIn("labelsForFlags", self.js)
        self.assertIn("countBySeverity", self.js)

    def test_renders_alerts_section(self) -> None:
        # R8 (D1) : classes du composant (film-detail-alert*) ; l'ancienne vue utilisait v5-film-alert*.
        self.assertIn("film-detail-alerts-list", self.js)
        self.assertIn("film-detail-alert--", self.js)

    def test_renders_alert_metadata(self) -> None:
        for attr in ("a.severity", "a.icon", "a.label", "a.description"):
            self.assertIn(attr, self.js)

    def test_action_button_rendered(self) -> None:
        # R8 (D1) : attribut du composant (data-film-alert-action) ; vue = data-v5-alert-action.
        self.assertIn("data-film-alert-action", self.js)
        self.assertIn("a.action", self.js)

    def test_merges_warning_flags_and_perceptual_warnings(self) -> None:
        """Doit fusionner row.warning_flags ET perceptual.global_score_v2.warnings."""
        self.assertIn("row.warning_flags", self.js)
        self.assertIn("gv2.warnings", self.js)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_alert_classes(self) -> None:
        for cls in (
            ".v5-film-alerts-list",
            ".v5-film-alert",
            ".v5-film-alert--warning",
            ".v5-film-alert--critical",
            ".v5-film-alert-head",
            ".v5-film-alert-icon",
            ".v5-film-alert-label",
            ".v5-film-alert-desc",
            ".v5-alert-count",
        ):
            self.assertIn(cls, self.css)


if __name__ == "__main__":
    unittest.main()
