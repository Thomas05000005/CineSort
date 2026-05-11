"""V5C-02 — Verifie l'etat des vues integrations post-decision (Option B retenue)."""

from __future__ import annotations

import unittest
from pathlib import Path


_VIEWS = ("jellyfin.js", "plex.js", "radarr.js", "logs.js")
_DASHBOARD_VIEWS_DIR = Path("web/dashboard/views")


class V5CIntegrationsTests(unittest.TestCase):
    """Tests structurels minimaux post-V5C-02 (Option B : conservation v4)."""

    def test_decision_documented(self) -> None:
        """La decision V5C-02 doit etre documentee dans audit/results/."""
        decision = Path("audit/results/v5c-02-decision.md")
        self.assertTrue(decision.exists(), "Le fichier de decision V5C-02 doit exister")
        content = decision.read_text(encoding="utf-8")
        self.assertIn("Option B", content, "La decision doit mentionner Option B")
        self.assertIn("Conservation v4", content)

    def test_views_still_exist(self) -> None:
        """Les 4 vues integrations doivent toujours exister."""
        for view in _VIEWS:
            path = _DASHBOARD_VIEWS_DIR / view
            self.assertTrue(path.exists(), f"{view} doit exister")

    def test_views_use_apiPost(self) -> None:
        """Pattern moderne (pas window.pywebview.api direct)."""
        for view in _VIEWS:
            content = (_DASHBOARD_VIEWS_DIR / view).read_text(encoding="utf-8")
            self.assertNotIn(
                "window.pywebview.api",
                content,
                f"Pattern legacy detecte dans {view}",
            )

    def test_views_are_es_modules(self) -> None:
        """Toutes les vues doivent exporter une fonction init via ESM."""
        for view in _VIEWS:
            content = (_DASHBOARD_VIEWS_DIR / view).read_text(encoding="utf-8")
            self.assertIn("export function init", content,
                          f"{view} doit exposer un export ESM init*()")
            self.assertIn("import", content, f"{view} doit utiliser des imports ESM")

    def test_btn_compact_defined_in_dashboard_styles(self) -> None:
        """Alignement minimal V5C-02 : .btn--compact ajoute au CSS du dashboard."""
        styles = Path("web/dashboard/styles.css").read_text(encoding="utf-8")
        self.assertIn(".btn--compact", styles,
                      "La classe .btn--compact doit etre definie pour Plex/Radarr/Logs")


if __name__ == "__main__":
    unittest.main()
