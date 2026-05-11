# V3-07 — Fix focus visible thème Studio

**Branche** : `fix/focus-visible-studio`
**Worktree** : `.claude/worktrees/fix-focus-visible-studio/`
**Effort** : 2-3h
**Priorité** : 🟠 IMPORTANT (a11y WCAG 2.4.7 — bloquant pour utilisateurs clavier)
**Fichiers concernés** :
- `web/dashboard/styles.css` (focus-visible global)
- `web/shared/themes.css` (override pour les 4 thèmes)
- `web/index.html` + autres si chargement séparé
- `tests/test_focus_visible.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b fix/focus-visible-studio .claude/worktrees/fix-focus-visible-studio audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/fix-focus-visible-studio

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT le CSS focus-visible. Tu vérifies que ça
fonctionne sur les 4 thèmes (Studio, Cinema, Luxe, Neon) sans casser le visuel.

---

## CONTEXTE

Audit a11y a révélé : le thème **Studio** (bleu technique) n'affiche aucun outline
visible quand on navigue au clavier (Tab). Les utilisateurs clavier sont bloqués.
WCAG 2.4.7 (AA) exige un focus visible.

**Cause probable** : règle CSS qui fait `outline: none` sans remplacement, ou tokens
focus avec contraste insuffisant sur le fond bleu Studio.

---

## MISSION

### Étape 1 — Diagnostic

Lance la recherche dans le code :

```bash
grep -rn "outline.*none" web/ cinesort/
grep -rn "outline.*0" web/ cinesort/
grep -rn "focus-visible" web/
grep -rn ":focus" web/dashboard/styles.css web/shared/components.css
```

Identifier :
1. Toutes les règles qui désactivent l'outline (à rétablir ou compenser)
2. Les règles `:focus` existantes (vérifier leur contraste sur thème Studio)
3. La présence d'un système global `:focus-visible`

### Étape 2 — Règle globale `:focus-visible`

Dans `web/dashboard/styles.css` (ou `web/shared/components.css` selon où sont les
règles globales), garantir :

```css
/* V3-07 — Focus visible global pour clavier (WCAG 2.4.7 AA) */
*:focus-visible {
  outline: 3px solid var(--focus-ring, var(--accent));
  outline-offset: 2px;
  border-radius: 2px;
}

/* Boutons et inputs nominaux : outline + halo subtle */
button:focus-visible,
input:focus-visible,
select:focus-visible,
textarea:focus-visible,
a:focus-visible,
[role="button"]:focus-visible,
[tabindex]:focus-visible {
  outline: 3px solid var(--focus-ring, var(--accent));
  outline-offset: 2px;
  box-shadow: 0 0 0 6px rgba(var(--accent-rgb, 59, 130, 246), 0.15);
}

/* Skip mouse focus (uniquement clavier) */
*:focus:not(:focus-visible) {
  outline: none;
}
```

### Étape 3 — Définir `--focus-ring` par thème

Dans `web/shared/themes.css`, ajouter pour chaque thème un token `--focus-ring` avec
contraste suffisant :

```css
/* Thème Studio (bleu technique) — focus jaune contrasté */
[data-theme="studio"] {
  --focus-ring: #FBBF24; /* jaune ambre, contraste 7:1 sur bleu */
}

/* Thème Cinema (rouge/or velours) — focus blanc */
[data-theme="cinema"] {
  --focus-ring: #FFFFFF;
}

/* Thème Luxe (noir mat/or) — focus or vif */
[data-theme="luxe"] {
  --focus-ring: #FFD700;
}

/* Thème Neon (violet/cyan cyberpunk) — focus cyan vif */
[data-theme="neon"] {
  --focus-ring: #00FFFF;
}
```

### Étape 4 — Supprimer les `outline: none` problématiques

Pour chaque `outline: none` trouvé à l'étape 1 sans remplacement focus → soit le
supprimer, soit ajouter `:focus-visible { outline: ... }` adjacent.

⚠ Ne PAS toucher aux outlines volontaires sur états non-focus (ex. `tabindex=-1` qu'on
veut sans outline).

### Étape 5 — Vérification visuelle (instructions pour l'utilisateur)

Ajouter dans le commit message ou dans `audit/prompts/vague3/07-VERIF-MANUELLE.md` :

> Vérification manuelle requise après merge :
> 1. Lancer l'app : `python app.py`
> 2. Pour chaque thème (Studio, Cinema, Luxe, Neon) :
>    - Aller dans Paramètres → Apparence → changer thème
>    - Appuyer sur Tab plusieurs fois sur n'importe quelle vue
>    - Vérifier que le focus est **clairement visible** (anneau coloré)
>    - Si focus invisible sur un thème → ajuster `--focus-ring` dans themes.css

### Étape 6 — Tests

```python
"""V3-07 — Focus visible WCAG 2.4.7."""
from __future__ import annotations
import unittest
from pathlib import Path


class FocusVisibleTests(unittest.TestCase):
    def setUp(self):
        self.styles = Path("web/dashboard/styles.css").read_text(encoding="utf-8")
        self.themes = Path("web/shared/themes.css").read_text(encoding="utf-8") if Path("web/shared/themes.css").exists() else ""

    def test_focus_visible_global_rule(self):
        """Règle globale *:focus-visible avec outline."""
        self.assertIn(":focus-visible", self.styles)
        # Outline non-zéro sur focus-visible
        self.assertRegex(self.styles, r":focus-visible[^}]*outline:\s*\d+px")

    def test_skip_focus_when_not_visible(self):
        """*:focus:not(:focus-visible) { outline: none } pour ne pas afficher au clic souris."""
        self.assertIn(":not(:focus-visible)", self.styles)

    def test_focus_ring_token_per_theme(self):
        """Chaque thème définit son --focus-ring."""
        for theme in ("studio", "cinema", "luxe", "neon"):
            self.assertIn(f'data-theme="{theme}"', self.themes, f"Thème manquant: {theme}")
            # Le bloc du thème contient --focus-ring
            block_start = self.themes.find(f'data-theme="{theme}"')
            block_end = self.themes.find("}", block_start) + 1
            block = self.themes[block_start:block_end]
            self.assertIn("--focus-ring", block, f"--focus-ring manquant pour {theme}")

    def test_no_orphan_outline_none(self):
        """Pas de outline: none sans replacement focus-visible adjacent."""
        # Cherche les "outline: none" qui ne sont PAS dans un bloc :not(:focus-visible)
        import re
        # Compte les outline: none
        all_none = re.findall(r"outline:\s*none", self.styles)
        # Compte ceux dans :not(:focus-visible)
        legit = re.findall(r":not\(:focus-visible\)\s*\{[^}]*outline:\s*none", self.styles)
        # Tolérance : maxi 2 outline: none orphelins (cas légitimes documentés)
        orphans = len(all_none) - len(legit)
        self.assertLessEqual(orphans, 2, f"{orphans} outline: none orphelins (sans focus-visible compensation)")


if __name__ == "__main__":
    unittest.main()
```

### Étape 7 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_focus_visible -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 8 — Commits

- `fix(a11y): global :focus-visible rule + per-theme focus ring (V3-07)`
- `fix(a11y): remove orphan outline:none rules`
- `test(a11y): focus visible WCAG 2.4.7 structural tests`

---

## LIVRABLES

Récap :
- Règle globale `:focus-visible` avec outline 3px + halo
- Token `--focus-ring` par thème (jaune Studio, blanc Cinema, or Luxe, cyan Neon)
- Pas d'outline parasite au clic souris (`:not(:focus-visible)`)
- WCAG 2.4.7 conforme sur les 4 thèmes
- 0 régression
- 3 commits sur `fix/focus-visible-studio`
