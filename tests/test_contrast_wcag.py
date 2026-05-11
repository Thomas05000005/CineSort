"""V4-02 — Verifie les ratios de contraste WCAG 2.2 AA pour les 4 themes.

Tokens reels CineSort (verifies dans web/shared/{tokens,themes}.css):
- Texte invariant dans tokens.css : --text-primary, --text-secondary, --text-muted
- Fonds par theme dans themes.css : --bg, --bg-raised
- Accent par theme : --accent

Le bloc Studio utilise un selecteur compose `:root, [data-theme="studio"]`,
le parser doit donc gerer ce cas (et pas seulement `[data-theme="..."]` strict).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convertit '#RRGGBB' ou '#RGB' en (r, g, b) 0-255."""
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 6:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if len(h) == 8:  # avec alpha -> ignore alpha
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    raise ValueError(f"Format hex invalide: {hex_color}")


def rgba_to_rgb(rgba_str: str, bg_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Compose 'rgba(r, g, b, a)' sur bg_rgb (alpha blending)."""
    m = re.match(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)",
        rgba_str,
    )
    if not m:
        raise ValueError(f"Format rgba invalide: {rgba_str}")
    r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
    a = float(m.group(4)) if m.group(4) else 1.0
    return (
        round(r * a + bg_rgb[0] * (1 - a)),
        round(g * a + bg_rgb[1] * (1 - a)),
        round(b * a + bg_rgb[2] * (1 - a)),
    )


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """Luminance relative WCAG (0.0 noir -> 1.0 blanc)."""

    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    """Ratio WCAG (1.0 = identique, 21.0 = noir/blanc max)."""
    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


_BLOCK_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(css_content: str) -> str:
    return _COMMENT_RE.sub("", css_content)


def _iter_blocks(css_content: str):
    """Itere (selector, body) sur les blocs simples (commentaires retires, pas de nesting)."""
    cleaned = _strip_comments(css_content)
    for m in _BLOCK_RE.finditer(cleaned):
        yield m.group(1).strip(), m.group(2)


def _extract_tokens_from_body(body: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for line in body.split(";"):
        line = line.strip()
        if not line or not line.startswith("--"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            tokens[k.strip()] = v.strip()
    return tokens


def parse_tokens(css_content: str, theme: str | None = None) -> dict[str, str]:
    """Extrait les tokens CSS.

    - theme=None : aggregat de tous les blocs `:root` (pas ceux scopes a un theme).
    - theme='studio' : blocs dont le selecteur contient `[data-theme="studio"]`
      OU le selecteur :root standalone (Studio est le defaut, defini sur
      `:root, [data-theme="studio"]`).
    Pour les autres themes (cinema/luxe/neon), seuls les blocs explicites scopes
    a `[data-theme="<theme>"]` sont retenus.
    """
    aggregated: dict[str, str] = {}
    target = f'[data-theme="{theme}"]' if theme else None

    for selector, body in _iter_blocks(css_content):
        sels = [s.strip() for s in selector.split(",")]
        is_root_only = sels == [":root"]
        contains_target = target is not None and any(target in s for s in sels)

        if theme is None:
            # On veut juste le :root global pur (tokens.css)
            if is_root_only:
                aggregated.update(_extract_tokens_from_body(body))
        else:
            if contains_target:
                aggregated.update(_extract_tokens_from_body(body))

    return aggregated


def resolve_color(value: str, all_tokens: dict[str, str]) -> str:
    """Resout var(--name[, fallback]) recursivement (max 8 iterations)."""
    for _ in range(8):
        if not value.startswith("var("):
            break
        m = re.match(r"var\((--[\w-]+)(?:\s*,\s*(.+))?\)\s*$", value)
        if not m:
            break
        token_name = m.group(1)
        fallback = (m.group(2) or "").strip()
        next_val = all_tokens.get(token_name, fallback)
        if not next_val or next_val == value:
            break
        value = next_val.strip()
    return value


# Combinaisons critiques a valider
# (fg_token, bg_token, ratio_min, label)
CRITICAL_PAIRS: list[tuple[str, str, float, str]] = [
    ("--text-primary", "--bg", 4.5, "Texte primaire sur fond principal"),
    ("--text-primary", "--bg-raised", 4.5, "Texte primaire sur carte elevee"),
    ("--text-secondary", "--bg", 4.5, "Texte secondaire sur fond"),
    ("--text-muted", "--bg", 3.0, "Texte muet sur fond (large text/UI)"),
    ("--accent", "--bg", 3.0, "Accent sur fond (UI control non-texte)"),
]

THEMES = ["studio", "cinema", "luxe", "neon"]


def compute_ratio(fg_raw: str, bg_raw: str, merged_tokens: dict[str, str]) -> tuple[float, str, str]:
    """Resout fg/bg et calcule le ratio. Retourne (ratio, fg_resolved, bg_resolved)."""
    fg_resolved = resolve_color(fg_raw, merged_tokens)
    bg_resolved = resolve_color(bg_raw, merged_tokens)

    # bg : doit etre opaque (hex). Si rgba transparent, on echoue clairement.
    if not bg_resolved.startswith("#"):
        raise ValueError(f"bg non hexadecimal: {bg_resolved}")
    bg_rgb = hex_to_rgb(bg_resolved)

    if fg_resolved.startswith("rgba") or fg_resolved.startswith("rgb("):
        fg_rgb = rgba_to_rgb(fg_resolved, bg_rgb)
    else:
        fg_rgb = hex_to_rgb(fg_resolved)

    return contrast_ratio(fg_rgb, bg_rgb), fg_resolved, bg_resolved


_REPO_ROOT = Path(__file__).resolve().parents[1]


class ContrastWcagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.themes_css = (_REPO_ROOT / "web/shared/themes.css").read_text(encoding="utf-8")
        tokens_path = _REPO_ROOT / "web/shared/tokens.css"
        cls.tokens_css = tokens_path.read_text(encoding="utf-8") if tokens_path.exists() else ""
        cls.global_tokens = parse_tokens(cls.tokens_css, theme=None)

    def _check_theme(self, theme: str) -> tuple[list[str], list[tuple[str, float]]]:
        """Retourne (violations, ratios_par_pair)."""
        theme_tokens = parse_tokens(self.themes_css, theme=theme)
        merged: dict[str, str] = {**self.global_tokens, **theme_tokens}

        violations: list[str] = []
        ratios: list[tuple[str, float]] = []

        for fg_tok, bg_tok, ratio_min, label in CRITICAL_PAIRS:
            fg_raw = merged.get(fg_tok)
            bg_raw = merged.get(bg_tok)
            if not fg_raw or not bg_raw:
                violations.append(f"  {label}: token manquant (fg={fg_tok}={fg_raw}, bg={bg_tok}={bg_raw})")
                continue
            try:
                ratio, fg_r, bg_r = compute_ratio(fg_raw, bg_raw, merged)
            except ValueError as e:
                violations.append(f"  {label}: parse error ({e})")
                continue

            ratios.append((label, ratio))
            if ratio < ratio_min:
                violations.append(f"  {label}: ratio {ratio:.2f} < {ratio_min} (fg={fg_r}, bg={bg_r})")
        return violations, ratios

    def test_studio_contrast(self) -> None:
        v, _ = self._check_theme("studio")
        self.assertEqual(v, [], "Theme Studio violations:\n" + "\n".join(v))

    def test_cinema_contrast(self) -> None:
        v, _ = self._check_theme("cinema")
        self.assertEqual(v, [], "Theme Cinema violations:\n" + "\n".join(v))

    def test_luxe_contrast(self) -> None:
        v, _ = self._check_theme("luxe")
        self.assertEqual(v, [], "Theme Luxe violations:\n" + "\n".join(v))

    def test_neon_contrast(self) -> None:
        v, _ = self._check_theme("neon")
        self.assertEqual(v, [], "Theme Neon violations:\n" + "\n".join(v))


if __name__ == "__main__":
    # Mode CLI : affiche tous les ratios par theme avant assertions
    import sys

    suite = unittest.TestLoader().loadTestsFromTestCase(ContrastWcagTests)
    if "--report" in sys.argv:
        ContrastWcagTests.setUpClass()
        instance = ContrastWcagTests()
        for theme in THEMES:
            print(f"\n=== Theme {theme.upper()} ===")
            violations, ratios = instance._check_theme(theme)
            for label, ratio in ratios:
                tag = "OK" if ratio >= 4.5 else ("AA-large" if ratio >= 3.0 else "FAIL")
                print(f"  [{tag:8s}] {ratio:5.2f}:1 — {label}")
            if violations:
                print("  Violations:")
                for v in violations:
                    print(v)
    else:
        runner = unittest.TextTestRunner(verbosity=2)
        runner.run(suite)
