"""GATE AUDIT 2026-06-14 (R6-I) — plus de "Alerte sans description.".

- year_missing (emis par la detection de doublons quand l'annee est
  introuvable) n'etait pas mappe -> affichait le generique muet.
- subtitle_missing_<lang> autres que fr/en (de/es/...) tombaient aussi sur le
  generique. labelForFlag les gere desormais dynamiquement.
- un flag inconnu affiche son code en clair plutot que "Alerte sans description.".
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ALERT_LABELS = Path(__file__).resolve().parents[1] / "web" / "dashboard" / "core" / "alert-labels.js"


class AlertLabelsYearMissingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ALERT_LABELS.read_text(encoding="utf-8")

    def test_year_missing_is_mapped(self) -> None:
        self.assertIn("year_missing:", self.js, "year_missing doit etre dans FLAG_MAP.")
        self.assertIn("Année introuvable", self.js)

    def test_dynamic_subtitle_missing_lang(self) -> None:
        # labelForFlag derive un libelle pour subtitle_missing_<lang> inconnu.
        self.assertIn('c.startsWith("subtitle_missing_")', self.js)

    def test_unknown_flag_shows_code(self) -> None:
        # Le fallback affiche le code en clair, plus le generique muet seul.
        self.assertIn("non documentée", self.js)


if __name__ == "__main__":
    unittest.main()
