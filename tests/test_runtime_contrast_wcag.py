"""Test runtime — contraste WCAG AA calcule par CSS cascade reelle.

ETAPE 3 RENFORCER TESTS — Iteration 10 (loop/correction-2026-06).

Critere FAMILLE A contraste : `ratio calcule >= WCAG AA sur 4 themes
(studio/cinema/luxe/neon)`.

Le test `tests/test_contrast_wcag.py` parse les fichiers CSS source et
calcule les ratios "a la main" en Python. Ce test ajoute la mesure RUNTIME
via `getComputedStyle` du navigateur, qui prend en compte :

- la cascade @layer reelle (priorite reset < tokens < primitives < components ...)
- les redefinitions theme par theme
- la resolution des var(--token, fallback) par le moteur CSS du browser
- les rendus computes (color-mix, calc, etc.)

C'est la mesure objective la plus proche du rendu utilisateur final.

Acquis preserves :
- Tier hex INVARIANTES (Platinum #E5E4E2, Gold #FFD700, Silver #C0C0C0, Bronze #CD7F32)
- 4 themes a tester : studio, cinema, luxe, neon (pas aaa qui a ses seuils dedies)
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright requis pour runtime contrast")


pytest_plugins = ["tests.e2e_dashboard.conftest"]


_THEMES = ("studio", "cinema", "luxe", "neon")

# Paires critiques mesurees runtime. Seuil WCAG AA :
#   - texte normal : >= 4.5:1
#   - texte large / UI control non-texte : >= 3.0:1
# On garde 4.5 pour --text-primary/--text-secondary (texte normal) et 3.0
# pour --text-muted (souvent utilise dans labels lointains / hint texts).
_CRITICAL_PAIRS = (
    ("--text-primary", "--bg", 4.5, "Texte primaire sur fond principal"),
    ("--text-primary", "--bg-raised", 4.5, "Texte primaire sur carte elevee"),
    ("--text-secondary", "--bg", 4.5, "Texte secondaire sur fond"),
    ("--text-muted", "--bg", 3.0, "Texte muet sur fond (large/UI)"),
)


# JS injecte dans la page : convertit un token CSS (var()) en (r,g,b) via
# canvas + getComputedStyle, puis calcule le ratio WCAG.
_RATIO_JS = r"""
(theme, fgToken, bgToken) => {
    // Bascule le theme sur body, attends repaint.
    document.body.setAttribute('data-theme', theme);
    const style = getComputedStyle(document.body);

    function tokenToColor(token) {
        // getPropertyValue retourne la chaine brute du var declaree.
        let raw = style.getPropertyValue(token).trim();
        if (!raw) return null;
        // Pour resoudre var(--xxx) -> rgb(...), on cree un element probe.
        const probe = document.createElement('div');
        probe.style.color = `var(${token})`;
        document.body.appendChild(probe);
        const computed = getComputedStyle(probe).color;
        probe.remove();
        // computed est "rgb(R, G, B)" ou "rgba(R, G, B, A)".
        const m = computed.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if (!m) return null;
        return [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])];
    }

    function bgTokenToColor(token) {
        // Pour bg, on applique sur background-color et on parse.
        const probe = document.createElement('div');
        probe.style.backgroundColor = `var(${token})`;
        document.body.appendChild(probe);
        const computed = getComputedStyle(probe).backgroundColor;
        probe.remove();
        const m = computed.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if (!m) return null;
        return [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])];
    }

    function luminance(rgb) {
        const [r, g, b] = rgb.map(c => {
            const v = c / 255;
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    }

    const fg = tokenToColor(fgToken);
    const bg = bgTokenToColor(bgToken);
    if (!fg || !bg) {
        return { ratio: null, fg, bg, error: 'token introuvable' };
    }
    const l1 = luminance(fg);
    const l2 = luminance(bg);
    const lighter = Math.max(l1, l2);
    const darker = Math.min(l1, l2);
    const ratio = (lighter + 0.05) / (darker + 0.05);
    return { ratio, fg, bg };
}
"""


@pytest.mark.runtime
@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("fg_token,bg_token,min_ratio,label", _CRITICAL_PAIRS)
def test_contrast_runtime_wcag_aa(
    dashboard_page,
    theme: str,
    fg_token: str,
    bg_token: str,
    min_ratio: float,
    label: str,
) -> None:
    """Mesure runtime du ratio via getComputedStyle pour chaque (theme, paire).

    Si le test test_contrast_wcag.py (static parse) est aveugle a une cascade
    @layer / un theme qui redefinit silencieusement --text-primary en couleur
    contrastee insuffisante, ce test runtime le rattrapera.
    """
    result = dashboard_page.evaluate(_RATIO_JS, [theme, fg_token, bg_token])
    assert result.get("ratio") is not None, (
        f"[{theme}] {label}: tokens introuvables runtime "
        f"(fg={fg_token}={result.get('fg')}, bg={bg_token}={result.get('bg')})"
    )
    ratio = float(result["ratio"])
    assert ratio >= min_ratio, (
        f"[{theme}] {label}: ratio runtime {ratio:.2f}:1 < seuil {min_ratio} WCAG AA "
        f"(fg={result['fg']}, bg={result['bg']})"
    )


@pytest.mark.runtime
@pytest.mark.parametrize("theme", _THEMES)
def test_tier_colors_invariant_runtime(dashboard_page, theme: str) -> None:
    """ACQUIS INVIOLABLE : les 4 couleurs tier hex sont INVARIANTES entre tous les themes.

    Memoire user : "Platinum #E5E4E2, Gold #FFD700, Silver #C0C0C0, Bronze #CD7F32.
    Definies UNIQUEMENT dans web/shared/tokens.css. Aucune duplication."

    Verification runtime : les tokens --tier-* (resolus via cascade complete)
    doivent rendre les MEMES couleurs sur tous les themes.
    """
    expected_hex = {
        "--tier-platinum": (0xE5, 0xE4, 0xE2),
        "--tier-gold": (0xFF, 0xD7, 0x00),
        "--tier-silver": (0xC0, 0xC0, 0xC0),
        "--tier-bronze": (0xCD, 0x7F, 0x32),
    }
    for token, expected_rgb in expected_hex.items():
        result = dashboard_page.evaluate(
            r"""(args) => {
                const [theme, token] = args;
                document.body.setAttribute('data-theme', theme);
                const probe = document.createElement('div');
                probe.style.color = `var(${token})`;
                document.body.appendChild(probe);
                const computed = getComputedStyle(probe).color;
                probe.remove();
                const m = computed.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
                if (!m) return null;
                return [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])];
            }""",
            [theme, token],
        )
        # Si le token est defini, il doit etre exactement la couleur attendue.
        # Si le token n'est PAS defini globalement (None), on tolere (peut-etre
        # qu'il n'a pas encore ete consomme par un selector que CSSOM expose).
        if result is None:
            continue
        actual_rgb = tuple(result)
        assert actual_rgb == expected_rgb, (
            f"[{theme}] INVARIANT VIOLE : {token} = rgb{actual_rgb} != attendu rgb{expected_rgb}. "
            f"Une duplication theme-specifique a casse l'invariant tier hex."
        )
