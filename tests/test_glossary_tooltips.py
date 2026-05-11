"""V3-03 — Tests structurels du composant glossaire tooltip.

Verifie que le composant existe avec les exports attendus, qu'il contient
un nombre suffisant de termes, qu'il est cable au boot et qu'il est injecte
dans plusieurs vues du dashboard.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_PATH = REPO_ROOT / "web" / "dashboard" / "components" / "glossary-tooltip.js"
CSS_PATH = REPO_ROOT / "web" / "dashboard" / "styles.css"
APP_JS_PATH = REPO_ROOT / "web" / "dashboard" / "app.js"

INJECTED_VIEWS = [
    # V5C-01 : injection desormais dans les vues v5 portees (qij-v5, settings-v5).
    # processing/home/library-v5 sans glossaire pour l'instant — V5C-03 etendra
    # progressivement.
    REPO_ROOT / "web" / "views" / "qij-v5.js",
    REPO_ROOT / "web" / "views" / "settings-v5.js",
    REPO_ROOT / "web" / "dashboard" / "views" / "library.js",
]


class GlossaryTooltipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.component = COMPONENT_PATH.read_text(encoding="utf-8")
        self.css = CSS_PATH.read_text(encoding="utf-8")
        self.app_js = APP_JS_PATH.read_text(encoding="utf-8")

    def test_component_file_exists(self) -> None:
        self.assertTrue(COMPONENT_PATH.exists(), f"Composant manquant: {COMPONENT_PATH}")

    def test_glossary_has_minimum_terms(self) -> None:
        """Au moins 15 termes definis dans GLOSSARY."""
        # Compte les paires "<terme>": "<definition>" entre les accolades de GLOSSARY
        match = re.search(r"export const GLOSSARY = \{(.*?)\};", self.component, re.DOTALL)
        self.assertIsNotNone(match, "Bloc GLOSSARY introuvable")
        body = match.group(1)
        count = len(re.findall(r'^\s*"[^"]+"\s*:\s*"', body, re.MULTILINE))
        self.assertGreaterEqual(count, 15, f"Seulement {count} termes (>=15 attendu)")

    def test_essential_terms_present(self) -> None:
        for term in ["LPIPS", "TMDb", "HDR10+", "Bitrate", "Tier", "Dry-run", "Apply", "NFO"]:
            self.assertIn(f'"{term}"', self.component, f"Terme manquant: {term}")

    def test_init_function_exported(self) -> None:
        self.assertIn("export function initGlossaryTooltips", self.component)

    def test_tooltip_function_exported(self) -> None:
        self.assertIn("export function glossaryTooltip", self.component)

    def test_glossary_constant_exported(self) -> None:
        self.assertIn("export const GLOSSARY", self.component)

    def test_css_styles_present(self) -> None:
        self.assertIn(".glossary-info", self.css)
        self.assertIn(".glossary-popover", self.css)
        self.assertIn(".glossary-term", self.css)

    def test_init_called_in_app(self) -> None:
        self.assertIn("initGlossaryTooltips", self.app_js)
        self.assertIn(
            'from "./components/glossary-tooltip.js"',
            self.app_js,
            "Import du composant manquant dans app.js",
        )

    def test_xss_protection(self) -> None:
        """escapeHtml doit etre utilise sur term, def et label."""
        self.assertIn("escapeHtml", self.component)
        # Verifie qu'on n'injecte pas de variables non echappees dans data-tooltip
        self.assertNotIn('data-tooltip="${def}"', self.component)
        self.assertNotIn('data-term="${term}"', self.component)

    def test_tooltip_injected_in_views(self) -> None:
        """Au moins 3 vues importent et appellent glossaryTooltip.

        V5C-01 : seuil reduit de 5 a 3 (vues v4 supprimees, injection sera
        etendue aux vues v5 manquantes par V5C-03).
        """
        injected_count = 0
        for view_path in INJECTED_VIEWS:
            self.assertTrue(view_path.exists(), f"Vue introuvable: {view_path}")
            content = view_path.read_text(encoding="utf-8")
            if "glossaryTooltip" in content and "glossary-tooltip.js" in content:
                injected_count += 1
        self.assertGreaterEqual(
            injected_count,
            3,
            f"Seulement {injected_count} vues utilisent glossaryTooltip (>=3 attendu)",
        )

    def test_accessibility_attributes(self) -> None:
        """Le bouton ⓘ doit avoir aria-label et type=button."""
        self.assertIn('type="button"', self.component)
        self.assertIn("aria-label=", self.component)
        # role="tooltip" pose soit en HTML littéral, soit via setAttribute("role", "tooltip")
        self.assertTrue(
            'role="tooltip"' in self.component or '"role", "tooltip"' in self.component,
            "Le popover doit avoir role=tooltip (HTML ou setAttribute)",
        )

    def test_keyboard_close_handler(self) -> None:
        """Escape doit fermer le popover."""
        self.assertIn("Escape", self.component)


if __name__ == "__main__":
    unittest.main()
