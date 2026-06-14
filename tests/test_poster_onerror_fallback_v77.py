"""GATE AUDIT 2026-06-14 (R6-H) — filet de securite jaquettes (image cassee).

Le proxy /api/poster renvoie un corps JSON (404 poster indisponible / 503 cle
TMDb absente), pas une image. Sans onerror, l'<img> affiche une icone cassee.
- bibliotheque : handler 'error' delegue en phase capture -> placeholder.
- film-detail : onerror inline -> placeholder.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BIB = _ROOT / "web" / "dashboard" / "views" / "bibliotheque.js"
_FILM = _ROOT / "web" / "dashboard" / "components" / "film-detail.js"


class PosterOnErrorFallbackTests(unittest.TestCase):
    def test_bibliotheque_has_capture_error_listener(self) -> None:
        js = _BIB.read_text(encoding="utf-8")
        self.assertIn('addEventListener("error"', js, "Listener 'error' delegue attendu.")
        self.assertIn("capture: true", js, "Le listener doit etre en phase capture (error ne bouillonne pas).")
        self.assertIn("bibliotheque-card-poster-img", js)
        self.assertIn("bibliotheque-card-poster-placeholder", js)

    def test_film_detail_has_onerror_fallback(self) -> None:
        js = _FILM.read_text(encoding="utf-8")
        self.assertIn("onerror=", js, "L'<img> poster film-detail doit avoir un onerror.")
        self.assertIn("film-detail-poster--placeholder", js)


if __name__ == "__main__":
    unittest.main()
