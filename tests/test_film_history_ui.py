"""P3.3 : tests introspection UI historique film (desktop)."""

from __future__ import annotations

import unittest
from pathlib import Path


class FilmHistoryUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (Path(__file__).resolve().parents[1] / "web" / "views" / "validation.js").read_text(encoding="utf-8")
        cls.html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    def test_film_history_modal_exists(self):
        self.assertIn('id="modalFilmHistory"', self.html)
        self.assertIn('id="filmHistoryBody"', self.html)

    def test_full_render_composition(self):
        """_renderFilmHistoryFull compose header + sparkline + timeline."""
        self.assertIn("_renderFilmHistoryFull", self.js)
        self.assertIn("_renderFilmHistoryHeader", self.js)
        self.assertIn("_renderScoreSparkline", self.js)
        self.assertIn("_renderTimelineEvents", self.js)

    def test_sparkline_svg_uses_thresholds(self):
        """Le sparkline doit indiquer les seuils Platinum/Gold/Silver."""
        self.assertIn("#A78BFA", self.js)  # Platinum line color
        self.assertIn("#FBBF24", self.js)  # Gold line color
        self.assertIn("#9CA3AF", self.js)  # Silver line color

    def test_sparkline_svg_viewbox(self):
        self.assertIn("viewBox", self.js)
        self.assertIn("<path", self.js)
        self.assertIn("<circle", self.js)

    def test_header_uses_tierPill(self):
        # Le header affiche le tier actuel via tierPill (P3.2)
        self.assertIn("tierPill(lastTier", self.js)

    def test_timeline_event_types_supported(self):
        for etype in ('"scan"', '"score"', '"apply"'):
            self.assertIn(etype, self.js)

    def test_timeline_icons_present(self):
        # Les icônes emoji par type
        self.assertIn("🔍", self.js)
        self.assertIn("⭐", self.js)
        self.assertIn("📁", self.js)

    def test_timeline_connector_line(self):
        """Une ligne verticale relie les events (visual timeline stepper)."""
        self.assertIn("background:var(--border)", self.js)

    def test_opens_modal_instead_of_overwriting_inspector(self):
        self.assertIn('openModal("modalFilmHistory")', self.js)

    def test_shortened_paths_helper(self):
        self.assertIn("_shortenHistoryPath", self.js)

    def test_score_delta_colored(self):
        self.assertIn("#34D399", self.js)  # delta positif vert
        self.assertIn("#EF4444", self.js)  # delta négatif rouge


if __name__ == "__main__":
    unittest.main()
