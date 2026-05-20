"""Tests Phase 6 — Spec transverse « Design system 100% ».

Couvre les deux derniers manques de l'audit (passage 93% -> 100%) :

1. ``web/shared/typography.css`` dedie :
   - Existe et contient les classes utilitaires .text-h1..h4, .text-body*,
     .text-caption, .text-overline, .text-label, .text-display, .text-mono,
     .text-truncate, .text-clamp-{2,3}, et les couleurs invariantes.
   - Reference dans ``web/dashboard/index.html`` APRES ``tokens.css`` (les
     classes utilisent les tokens --font-*/--fs-*/--fw-*).

2. Theme « contraste eleve » WCAG AAA :
   - 5e theme ``data-theme="aaa"`` ajoute dans themes.css.
   - Override des couleurs de texte invariantes (--text-primary/secondary)
     pour atteindre AAA (>= 7:1 texte normal).
   - Top-bar v5 expose ce 5e theme dans la liste THEMES.
   - Cles de locale ``topbar.themes.aaa`` presentes en fr + en.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SHARED = _ROOT / "web" / "shared"
_DASH = _ROOT / "web" / "dashboard"
_LOCALES = _ROOT / "locales"

_TYPOGRAPHY_CSS = _SHARED / "typography.css"
_THEMES_CSS = _SHARED / "themes.css"
_INDEX_HTML = _DASH / "index.html"
_TOPBAR_JS = _DASH / "components" / "top-bar-v5.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TypographyCssTests(unittest.TestCase):
    def test_typography_file_exists(self) -> None:
        self.assertTrue(_TYPOGRAPHY_CSS.is_file(), f"manquant : {_TYPOGRAPHY_CSS}")

    def test_headings_classes_present(self) -> None:
        css = _read(_TYPOGRAPHY_CSS)
        for cls in (".text-h1", ".text-h2", ".text-h3", ".text-h4"):
            self.assertIn(cls, css, f"classe heading manquante : {cls}")

    def test_body_classes_present(self) -> None:
        css = _read(_TYPOGRAPHY_CSS)
        for cls in (".text-body", ".text-body-lg", ".text-body-sm"):
            self.assertIn(cls, css, f"classe body manquante : {cls}")

    def test_caption_overline_label(self) -> None:
        css = _read(_TYPOGRAPHY_CSS)
        for cls in (".text-caption", ".text-overline", ".text-label"):
            self.assertIn(cls, css, f"classe meta manquante : {cls}")

    def test_display_and_mono(self) -> None:
        css = _read(_TYPOGRAPHY_CSS)
        self.assertIn(".text-display", css)
        self.assertIn(".text-mono", css)

    def test_color_utility_classes(self) -> None:
        css = _read(_TYPOGRAPHY_CSS)
        for cls in (".text-primary", ".text-secondary", ".text-muted",
                    ".text-disabled", ".text-inverse"):
            self.assertIn(cls, css, f"classe couleur manquante : {cls}")

    def test_tabular_and_truncate(self) -> None:
        css = _read(_TYPOGRAPHY_CSS)
        for cls in (".text-tabular", ".text-truncate", ".text-clamp-2", ".text-clamp-3"):
            self.assertIn(cls, css, f"classe utilitaire manquante : {cls}")

    def test_uses_tokens_no_hardcoded_hex(self) -> None:
        css = _read(_TYPOGRAPHY_CSS)
        self.assertIn("var(--font-family-base)", css)
        self.assertIn("var(--fs-base)", css)
        self.assertIn("var(--fw-regular)", css)
        decls = re.findall(r"color:\s*(#[0-9A-Fa-f]{3,8})\s*;", css)
        self.assertEqual(decls, [], f"hex hardcode interdit dans typography.css : {decls}")

    def test_referenced_in_dashboard_index(self) -> None:
        html = _read(_INDEX_HTML)
        self.assertIn('href="/shared/typography.css"', html)

    def test_referenced_after_tokens(self) -> None:
        html = _read(_INDEX_HTML)
        pos_tokens = html.find('href="/shared/tokens.css"')
        pos_typo = html.find('href="/shared/typography.css"')
        self.assertGreater(pos_tokens, 0)
        self.assertGreater(pos_typo, 0)
        self.assertLess(pos_tokens, pos_typo, "typography.css doit etre charge APRES tokens.css")


class ThemeAaaTests(unittest.TestCase):
    def test_aaa_theme_defined_in_themes_css(self) -> None:
        css = _read(_THEMES_CSS)
        self.assertIn('[data-theme="aaa"]', css)

    def test_aaa_theme_redefines_bg_surface_accent(self) -> None:
        css = _read(_THEMES_CSS)
        start = css.find('[data-theme="aaa"]')
        self.assertNotEqual(start, -1)
        end = css.find("}", start)
        block = css[start:end]
        self.assertIn("--bg:", block)
        self.assertIn("--surface-1:", block)
        self.assertIn("--accent:", block)
        self.assertIn("--focus-ring:", block)

    def test_aaa_theme_overrides_text_for_contrast(self) -> None:
        css = _read(_THEMES_CSS)
        start = css.find('[data-theme="aaa"]')
        end = css.find("}", start)
        block = css[start:end]
        self.assertIn("--text-primary:", block)
        self.assertIn("--text-secondary:", block)
        self.assertIn("#FFFFFF", block)
        self.assertIn("#000000", block)

    def test_aaa_theme_not_overriding_tier_or_severity(self) -> None:
        css = _read(_THEMES_CSS)
        start = css.find('[data-theme="aaa"]')
        end = css.find("}", start)
        block = css[start:end]
        self.assertNotIn("--tier-platinum-solid", block,
                         "AAA ne doit pas redefinir tier colors")
        self.assertNotIn("--sev-info-solid", block,
                         "AAA ne doit pas redefinir severities")

    def test_topbar_lists_aaa_theme(self) -> None:
        js = _read(_TOPBAR_JS)
        self.assertIn('id: "aaa"', js)
        self.assertIn('"topbar.themes.aaa"', js)

    def test_locales_have_aaa_label(self) -> None:
        for loc in ("fr.json", "en.json"):
            data = json.loads(_read(_LOCALES / loc))
            themes = data.get("topbar", {}).get("themes", {})
            self.assertIn("aaa", themes, f"cle topbar.themes.aaa manquante dans {loc}")
            self.assertTrue(themes["aaa"], f"label aaa vide dans {loc}")


if __name__ == "__main__":
    unittest.main()
