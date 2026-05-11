# V4-02 — Resultats contraste WCAG 2.2 AA

**Date** : 2026-05-01
**Branche** : `test/contrast-themes-wcag`
**Test** : [tests/test_contrast_wcag.py](../../tests/test_contrast_wcag.py)
**Sources** : [web/shared/tokens.css](../../web/shared/tokens.css), [web/shared/themes.css](../../web/shared/themes.css)

---

## Methode

Test Python (`unittest`) qui :

1. Parse `web/shared/tokens.css` (`:root`) et `web/shared/themes.css` (blocs `[data-theme="..."]`).
2. Resout `var(--token)` recursivement.
3. Calcule la luminance relative WCAG 2.2 (formule sRGB officielle) et le ratio
   de contraste pour 5 combinaisons critiques par theme.
4. Fail si un ratio est strictement inferieur au seuil exige.

Les **tokens texte** (`--text-primary`, `--text-secondary`, `--text-muted`) sont
**invariants** dans `tokens.css` ; seuls `--bg`, `--bg-raised` et `--accent`
changent par theme.

### Seuils appliques

| Combinaison | Seuil WCAG 2.2 | Justification |
|---|---|---|
| `--text-primary` sur `--bg` | 4.5:1 (AA texte normal) | Texte standard |
| `--text-primary` sur `--bg-raised` | 4.5:1 (AA texte normal) | Cartes / panneaux |
| `--text-secondary` sur `--bg` | 4.5:1 (AA texte normal) | Sous-titres / metadata |
| `--text-muted` sur `--bg` | 3.0:1 (AA texte large/UI ≥18pt ou 14pt bold) | Hints, captions |
| `--accent` sur `--bg` | 3.0:1 (AA composants UI non-texte) | Borders, icones, focus |

---

## Resultats par theme

| Theme | text-primary / bg | text-primary / bg-raised | text-secondary / bg | text-muted / bg | accent / bg | Verdict |
|---|---|---|---|---|---|---|
| **Studio** | **16.80:1** | 15.96:1 | 6.75:1 | 4.60:1 | 7.84:1 | ✅ AA (et AAA pour le texte) |
| **Cinema** | **16.86:1** | 16.45:1 | 6.78:1 | 4.61:1 | 4.14:1 | ✅ AA |
| **Luxe** | **16.85:1** | 16.11:1 | 6.77:1 | 4.61:1 | 11.98:1 | ✅ AA (et AAA pour le texte) |
| **Neon** | **16.91:1** | 16.19:1 | 6.79:1 | 4.63:1 | 5.07:1 | ✅ AA |

### Lecture detaillee

**Studio** (`#06090F` / `#0B111A`, accent `#60A5FA`)
- Tous textes >= 4.5:1, accent confortable a 7.84:1.
- `--text-muted #6B7A95` sur fond le plus sombre : 4.60:1 — passe AA texte normal de justesse mais reste positif.

**Cinema** (`#0C0708` / `#130A0B`, accent `#DC2626`)
- L'accent rouge a le ratio le plus faible (4.14:1), suffisant pour des
  composants UI non-texte (>= 3:1) mais **insuffisant pour utiliser
  `--accent` comme couleur de TEXTE** sur `--bg`. A surveiller si du texte
  rouge (errors) est rendu directement sur le fond.
- Tous les textes (primary/secondary/muted) sont conformes AA.

**Luxe** (`#0A0806` / `#120F0A`, accent `#FBBF24`)
- Accent jaune-or excellent a 11.98:1.
- Ratios texte parmi les plus eleves des quatre themes.

**Neon** (`#050714` / `#0A0D22`, accent `#A855F7`)
- Accent violet a 5.07:1 — confortable pour UI ET utilisable comme texte AA.
- Fond le plus sombre des quatre themes => ratios texte legerement boostes.

---

## Tokens corriges

**Aucun.** Les 4 themes respectent deja WCAG 2.2 AA pour les 5 combinaisons
testees, sans modification.

---

## Limitations connues

- Le test couvre les **tokens** (couleurs declarees). Il ne valide PAS le
  rendu effectif lorsqu'une couche `--surface-1/2/3` (rgba transparent) ou un
  `--atmosphere-overlay` (scan-lines, grain, shimmer) est superposee. Ces
  overlays ont des opacites tres faibles (0.025-0.08) et n'alterent
  visuellement le contraste que de quelques pourcent ; un audit visuel
  Playwright (V4-01) reste recommande pour confirmer le rendu compose.
- Les **tier colors** (`--tier-platinum/gold/silver/bronze/reject/unknown`)
  ne sont pas dans le perimetre : invariantes par design, validees lors de
  V3-x. Idem severities (`--sev-*`).
- Le **seuil 3:1 pour --accent** assume un usage non-texte (focus rings,
  icones, borders). Pour Cinema (4.14:1), eviter d'utiliser `--accent` comme
  couleur de **texte normal** (sous le seuil 4.5:1) ; preferer
  `--accent-hover` (`#EF4444`, **5.32:1** sur `#0C0708`) qui passe AA.

## Verdict global

✅ **Les 4 themes (Studio, Cinema, Luxe, Neon) sont conformes WCAG 2.2 AA**
pour les 5 combinaisons texte/UI critiques.

Le test `tests/test_contrast_wcag.py` est integre a la suite et fail si une
modification future degrade un ratio sous son seuil.
