# V4-02 — Contraste 4 thèmes WCAG AA (chiffré)

**Branche** : `test/contrast-themes-wcag`
**Worktree** : `.claude/worktrees/test-contrast-themes-wcag/`
**Effort** : 3-4h
**Mode** : 🟢 Parallélisable (calcul ratio chiffré sur tokens CSS)
**Fichiers concernés** :
- `tests/test_contrast_wcag.py` (nouveau)
- `audit/results/v4-02-contrast-results.md` (nouveau — rapport)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b test/contrast-themes-wcag .claude/worktrees/test-contrast-themes-wcag audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/test-contrast-themes-wcag

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu créés un test de calcul de ratio + un rapport. Tu ne
modifies PAS les tokens CSS sauf si tu trouves une violation flagrante (et dans ce
cas tu fixes ce token précisément).

---

## CONTEXTE

CineSort propose 4 thèmes (Studio, Cinema, Luxe, Neon). WCAG 2.2 AA exige un ratio
de contraste ≥ 4.5:1 pour le texte normal, ≥ 3:1 pour le texte large (≥18pt). Audit
visuel précédent a soulevé des doutes sur certains thèmes (notamment Studio).

**Solution** : test Python qui parse les tokens CSS, calcule les ratios pour les
combinaisons critiques (texte sur fond, accent sur fond, etc.), et fail si < seuil.

---

## MISSION

### Étape 1 — Lire les modules

- `web/shared/themes.css` (4 thèmes définis : `[data-theme="studio"]`, etc.)
- `web/shared/tokens.css` (tokens partagés)
- Identifier les tokens couleur critiques :
  - `--text-primary` sur `--bg-base` / `--bg-raised` / `--bg-overlay`
  - `--text-secondary` sur idem
  - `--accent` sur `--bg-base`
  - `--text-muted` sur `--bg-base` (souvent le plus risqué)

### Étape 2 — Helper calcul ratio WCAG

Crée `tests/test_contrast_wcag.py` :

```python
"""V4-02 — Vérifie les ratios de contraste WCAG 2.2 AA pour les 4 thèmes."""
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
    if len(h) == 8:  # avec alpha → ignore alpha
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    raise ValueError(f"Format hex invalide: {hex_color}")


def rgba_to_rgb(rgba_str: str, bg_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Convertit 'rgba(r, g, b, a)' compositée sur bg_rgb."""
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)", rgba_str)
    if not m:
        raise ValueError(f"Format rgba invalide: {rgba_str}")
    r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
    a = float(m.group(4)) if m.group(4) else 1.0
    # Composition sur bg
    return (
        round(r * a + bg_rgb[0] * (1 - a)),
        round(g * a + bg_rgb[1] * (1 - a)),
        round(b * a + bg_rgb[2] * (1 - a)),
    )


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """Luminance relative WCAG (0.0 noir → 1.0 blanc)."""
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    """Ratio WCAG (1.0 = identique, 21.0 = noir/blanc)."""
    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def parse_tokens(css_content: str, theme: str | None = None) -> dict[str, str]:
    """Extrait les tokens CSS d'un bloc.

    Si theme=None → tokens globaux dans :root ou :host.
    Si theme='studio' → tokens dans [data-theme="studio"].
    """
    if theme:
        pattern = rf'\[data-theme=["\']?{theme}["\']?\]\s*\{{([^}}]*)\}}'
    else:
        pattern = r":root\s*\{([^}]*)\}"
    m = re.search(pattern, css_content, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    # Extraire --token: value;
    tokens = {}
    for line in block.split(";"):
        line = line.strip()
        if not line or not line.startswith("--"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            tokens[k.strip()] = v.strip()
    return tokens


def resolve_color(value: str, all_tokens: dict[str, str]) -> str:
    """Résout var(--name) récursivement."""
    while value.startswith("var("):
        m = re.match(r"var\((--[\w-]+)(?:,\s*([^)]+))?\)", value)
        if not m:
            break
        token_name = m.group(1)
        fallback = m.group(2)
        value = all_tokens.get(token_name, fallback or value).strip()
    return value


# Combinaisons critiques à valider
CRITICAL_PAIRS = [
    # (fg_token, bg_token, ratio_min, label)
    ("--text-primary", "--bg-base", 4.5, "Texte primaire sur fond principal"),
    ("--text-primary", "--bg-raised", 4.5, "Texte primaire sur carte élevée"),
    ("--text-secondary", "--bg-base", 4.5, "Texte secondaire sur fond"),
    ("--text-muted", "--bg-base", 3.0, "Texte muet sur fond (large text OK)"),
    ("--accent", "--bg-base", 3.0, "Accent sur fond (UI control)"),
]

THEMES = ["studio", "cinema", "luxe", "neon"]


class ContrastWcagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.themes_css = Path("web/shared/themes.css").read_text(encoding="utf-8")
        cls.tokens_css = Path("web/shared/tokens.css").read_text(encoding="utf-8") if Path("web/shared/tokens.css").exists() else ""
        cls.all_global = parse_tokens(cls.tokens_css + "\n" + cls.themes_css, theme=None)

    def _check_theme(self, theme: str):
        theme_tokens = parse_tokens(self.themes_css, theme=theme)
        merged = {**self.all_global, **theme_tokens}

        violations = []
        for fg_tok, bg_tok, ratio_min, label in CRITICAL_PAIRS:
            fg_raw = merged.get(fg_tok)
            bg_raw = merged.get(bg_tok)
            if not fg_raw or not bg_raw:
                continue  # token pas défini pour ce thème, skip

            fg_resolved = resolve_color(fg_raw, merged)
            bg_resolved = resolve_color(bg_raw, merged)

            try:
                # Si rgba sur transparent → composer sur le bg
                if fg_resolved.startswith("rgba"):
                    bg_rgb = hex_to_rgb(bg_resolved) if bg_resolved.startswith("#") else (0, 0, 0)
                    fg_rgb = rgba_to_rgb(fg_resolved, bg_rgb)
                else:
                    fg_rgb = hex_to_rgb(fg_resolved)
                bg_rgb = hex_to_rgb(bg_resolved) if bg_resolved.startswith("#") else (0, 0, 0)
            except ValueError as e:
                violations.append(f"  {label}: parse error ({e})")
                continue

            ratio = contrast_ratio(fg_rgb, bg_rgb)
            if ratio < ratio_min:
                violations.append(f"  {label}: ratio {ratio:.2f} < {ratio_min} (fg={fg_resolved}, bg={bg_resolved})")

        return violations

    def test_studio_contrast(self):
        v = self._check_theme("studio")
        self.assertEqual(v, [], f"Thème Studio violations:\n" + "\n".join(v))

    def test_cinema_contrast(self):
        v = self._check_theme("cinema")
        self.assertEqual(v, [], f"Thème Cinema violations:\n" + "\n".join(v))

    def test_luxe_contrast(self):
        v = self._check_theme("luxe")
        self.assertEqual(v, [], f"Thème Luxe violations:\n" + "\n".join(v))

    def test_neon_contrast(self):
        v = self._check_theme("neon")
        self.assertEqual(v, [], f"Thème Neon violations:\n" + "\n".join(v))


if __name__ == "__main__":
    unittest.main()
```

### Étape 3 — Si violations trouvées

Pour chaque violation, propose une correction du token dans `themes.css`. Exemple :

> Studio : `--text-muted` est `#7B8FA8` sur `--bg-base` `#0A1118` → ratio 4.21 < 4.5
> Fix : passer à `#8FA1B8` → ratio 4.73 ✅

Modifie le token, relance le test, valide.

### Étape 4 — Rapport

Crée `audit/results/v4-02-contrast-results.md` :

```markdown
# V4-02 — Résultats contraste WCAG 2.2 AA

**Date** : YYYY-MM-DD

## Résultats par thème

| Thème | Combinaisons testées | Ratios min observés | Verdict |
|---|---|---|---|
| Studio | 5 | text-primary/bg: X.XX, ... | ✅ AA / ⚠ AA partial |
| Cinema | 5 | ... | ✅ AA |
| Luxe | 5 | ... | ✅ AA |
| Neon | 5 | ... | ✅ AA |

## Tokens corrigés

- (Liste des tokens modifiés et raisons)

## Verdict global
✅ Tous les thèmes conformes WCAG 2.2 AA
```

### Étape 5 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_contrast_wcag -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 6 — Commits

- `test(a11y): WCAG 2.2 AA contrast verification for 4 themes (V4-02)`
- (si fix) `fix(themes): improve contrast ratios for theme XYZ tokens`
- `docs(audit): contrast WCAG results V4-02`

---

## LIVRABLES

- `tests/test_contrast_wcag.py` qui fail si un thème viole AA
- Tokens corrigés si violations
- `audit/results/v4-02-contrast-results.md` avec ratios chiffrés
- 0 régression
- 2-3 commits sur `test/contrast-themes-wcag`
