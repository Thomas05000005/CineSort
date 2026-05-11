# V3-10 — 30 hardcodes couleurs → tokens CSS

**Branche** : `refactor/hardcodes-to-css-tokens`
**Worktree** : `.claude/worktrees/refactor-hardcodes-to-css-tokens/`
**Effort** : 4-6h
**Priorité** : 🟢 NICE-TO-HAVE (cohérence design system)
**Fichiers concernés** :
- `web/dashboard/styles.css` (la majorité)
- `web/dashboard/views/*.js` (style inline)
- `web/views/*.js` (idem si touché)
- `web/shared/tokens.css` (ajouter tokens manquants)
- `tests/test_no_hardcoded_colors.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b refactor/hardcodes-to-css-tokens .claude/worktrees/refactor-hardcodes-to-css-tokens audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/refactor-hardcodes-to-css-tokens

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT le CSS et les styles inline dans les JS.
Aucune modif logique métier.

RÈGLE PRESERVATION : tu DOIS préserver les **tier colors** invariantes
(Premium/Bon/Moyen/Mauvais) — elles doivent rester identiques cross-thèmes (test
`test_themes_do_not_redefine_tiers` du projet l'exige).

---

## CONTEXTE

L'audit visuel a identifié ~30 couleurs hex hardcodées dans le CSS et JS qui devraient
utiliser les tokens du design system v5 (`web/shared/tokens.css` et `web/shared/themes.css`).

Conséquence des hardcodes :
- Inconsistant entre thèmes (le hardcode reste fixe quand le thème change)
- Gestion fastidieuse si on veut ajuster une couleur

**Solution** : remplacer chaque couleur hex par un token CSS variable. Si le token
n'existe pas, l'ajouter dans `tokens.css` (couleur générique) ou `themes.css` (couleur
qui doit varier par thème).

---

## MISSION

### Étape 1 — Inventaire des hardcodes

```bash
grep -rn -E "#[0-9a-fA-F]{3,8}\b" web/dashboard/ web/views/ web/components/ \
  --include="*.css" --include="*.js" --include="*.html" \
  | grep -v "^[^:]*:[^:]*://" \
  | grep -v "/\*" \
  | head -60
```

Note dans un fichier temporaire `_hardcodes_inventory.md` chaque hardcode trouvé,
classé en 3 catégories :
1. **Tier colors** (NE PAS TOUCHER — invariantes) : ex. `#10B981` (Premium green)
2. **Couleur générique** (token globalspour toute palette) : ex. `#FFFFFF` blanc, `#000` noir
3. **Couleur thématique** (varie selon thème) : ex. `#3B82F6` accent bleu Studio

### Étape 2 — Vérifier tokens existants

Lis `web/shared/tokens.css` et `web/shared/themes.css`. Note les tokens disponibles :
- `--accent`, `--accent-border`, `--accent-rgb`
- `--text-primary`, `--text-muted`, `--text-secondary`
- `--bg-primary`, `--bg-elevated`, `--surface-elevated`
- `--accent-success`, `--accent-warning`, `--accent-danger`
- `--radius-*`, `--shadow-*`, etc.

### Étape 3 — Ajouter tokens manquants

Si un hardcode n'a pas d'équivalent token, ajoute-le dans :
- `tokens.css` si la couleur doit être identique sur tous les thèmes
- `themes.css` (un par thème) si elle doit varier

Exemple : si tu trouves `#FBBF24` (warning amber) répété 5 fois et qu'il n'y a pas
`--accent-warning`, ajoute-le.

### Étape 4 — Remplacer les hardcodes

Pour chaque hardcode catégorie 2 ou 3, remplace par `var(--token-name)`.

⚠ **NE PAS toucher** :
- Couleurs dans les SVG inline (peut casser le rendu visuel attendu)
- Couleurs `rgba(0,0,0,0.X)` pour ombres (sauf si tu crées un token shadow)
- Tier colors (Premium #10B981, Bon #06B6D4, Moyen #F59E0B, Mauvais #EF4444 — vérifier
  les valeurs exactes dans le code)

### Étape 5 — Vérification visuelle

⚠ Pour chaque thème (Studio / Cinema / Luxe / Neon) :
- Vérifie qu'aucune zone n'est devenue blanche/cassée
- Vérifie que les contrastes sont préservés (lisibilité)
- Si problème → ajuster le token plutôt qu'annuler le remplacement

(Recommandation : après merge, l'utilisateur doit lancer l'app et tester visuellement
les 4 thèmes — cf checklist).

### Étape 6 — Tests

Crée `tests/test_no_hardcoded_colors.py` :

```python
"""V3-10 — Vérifie qu'on n'introduit pas de nouveaux hardcodes couleurs."""
from __future__ import annotations
import re
import unittest
from pathlib import Path


# Hardcodes tolérés (tier colors invariants + cas légitimes)
ALLOWED_HARDCODES = {
    # Tier colors (à confirmer avec les vraies valeurs du projet)
    "#10B981", "#10b981",  # Premium
    "#06B6D4", "#06b6d4",  # Bon
    "#F59E0B", "#f59e0b",  # Moyen
    "#EF4444", "#ef4444",  # Mauvais
    "#FBBF24", "#fbbf24",  # warning amber (commun)
    "#FFFFFF", "#ffffff", "#FFF", "#fff",  # blanc pur
    "#000000", "#000",  # noir pur
}


class HardcodedColorsTests(unittest.TestCase):
    HEX_PATTERN = re.compile(r"#[0-9a-fA-F]{3,8}\b")

    def _scan_file(self, path: Path) -> list[tuple[int, str]]:
        """Retourne [(line_no, hardcode), ...] pour les hardcodes non tolérés."""
        violations = []
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            # Skip commentaires obvious
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("#"):
                continue
            for match in self.HEX_PATTERN.findall(line):
                if match not in ALLOWED_HARDCODES:
                    violations.append((i, match, line.strip()))
        return violations

    def test_dashboard_styles_minimal_hardcodes(self):
        path = Path("web/dashboard/styles.css")
        violations = self._scan_file(path)
        # Tolérance : moins de 8 hardcodes restants (gradient SVG complexes acceptables)
        self.assertLessEqual(
            len(violations), 8,
            f"{len(violations)} hardcodes restants dans {path} : {violations[:5]}"
        )

    def test_views_no_inline_hardcodes(self):
        # Les vues JS ne devraient pas avoir de couleurs hex inline
        for view in Path("web/dashboard/views").rglob("*.js"):
            violations = self._scan_file(view)
            # Tolérance : 2 max par vue (cas SVG inline)
            self.assertLessEqual(
                len(violations), 2,
                f"{view.name} : {len(violations)} hardcodes inline : {violations}"
            )


if __name__ == "__main__":
    unittest.main()
```

⚠ Ajuste `ALLOWED_HARDCODES` aux vraies valeurs des tier colors du projet (lis
`web/shared/themes.css` ou tokens.css).

### Étape 7 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_no_hardcoded_colors -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2

# Test invariance tier colors (existant)
.venv313/Scripts/python.exe -m unittest tests.test_polish_v5 -v 2>&1 | grep -i "tier" | head -5
```

### Étape 8 — Commits

- `refactor(css): replace 30 hex hardcodes by design system tokens (V3-10)`
- `feat(tokens): add missing tokens for warning/info/elevated variants`
- `test(css): assert minimal hardcoded colors remain`

---

## LIVRABLES

Récap :
- ~30 hardcodes hex remplacés par `var(--token)`
- Tokens manquants ajoutés dans `tokens.css` ou `themes.css`
- **Tier colors préservées** invariantes
- Test `test_no_hardcoded_colors.py` qui empêche les régressions
- 0 régression visuelle (vérification manuelle 4 thèmes recommandée)
- 3 commits sur `refactor/hardcodes-to-css-tokens`
