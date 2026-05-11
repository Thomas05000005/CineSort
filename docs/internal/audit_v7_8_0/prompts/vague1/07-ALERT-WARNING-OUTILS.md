# V1-07 — Bandeau "Outils manquants" stylé en .alert--warning

**Branche** : `fix/alert-warning-outils-banner`
**Worktree** : `.claude/worktrees/fix-alert-warning-outils-banner/`
**Effort** : 1h
**Priorité** : 🔴 BLOQUANT
**Fichiers concernés** :
- `web/views/home.js`
- (potentiellement) `web/views/library.js` ou `web/views/library-v5.js`
- (vérifier) `web/styles.css` ou `web/shared/components.css`

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b fix/alert-warning-outils-banner .claude/worktrees/fix-alert-warning-outils-banner audit_qa_v7_6_0_dev_20260428
# Si déjà existe : git worktree add .claude/worktrees/fix-alert-warning-outils-banner fix/alert-warning-outils-banner
cd .claude/worktrees/fix-alert-warning-outils-banner

pwd && git branch --show-current && git status
```

⚠ Cette mission a probablement déjà été faite (commit `1db1d86` sur la branche).
Vérifie : `git log --oneline | head -3`. Si fait → "déjà fait" et termine.

---

## RÈGLES GLOBALES

EXIGENCE QUALITÉ.
RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT les fichiers home.js / library*.js + CSS si la classe doit être créée/enrichie.

---

## MISSION

Le bandeau "Outils d'analyse vidéo manquants : FFprobe, MediaInfo" est rendu comme
une card neutre. Doit être un warning visuel clair.

### Étape 1 — Vérifier si .alert--warning existe

```bash
grep -rn "\.alert--warning" web/styles.css web/shared/*.css web/dashboard/styles.css 2>&1 | head -5
```

**Si la classe existe** : aller à l'Étape 3.
**Si N'EXISTE PAS** : aller à l'Étape 2.

### Étape 2 — Créer .alert--warning si absente

Lis `web/shared/tokens.css` pour les tokens warning. Ajoute dans `web/styles.css` :

```css
/* Audit ID-F-004 / D-PARENT-3 : warning banner */
.alert {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  padding: var(--sp-3);
  border-radius: var(--radius-md);
  border: 1px solid;
}
.alert--warning {
  background: rgb(from var(--warning) r g b / 12%);
  border-color: rgb(from var(--warning) r g b / 45%);
  color: var(--text-primary);
}
.alert--warning::before {
  content: "⚠";
  color: var(--warning);
  font-size: 1.2em;
  flex-shrink: 0;
  font-weight: bold;
}
```

### Étape 3 — Localiser le bandeau

Lis `web/views/home.js`. Cherche `home-probe-banner` ou "Outils d'analyse vidéo manquants".

### Étape 4 — Appliquer .alert--warning

```javascript
`<div class="alert alert--warning">
  <span>Outils d'analyse vidéo manquants : ${missing.join(", ")}</span>
  <button class="btn btn--compact" onclick="...">Installer automatiquement</button>
</div>`
```

### Étape 5 — Vérifier library hub

Grep `Outils d.analyse|outils.manquants|home-probe-banner` dans web/views/.
Si présent ailleurs (library*.js) : appliquer le même fix.

### Étape 6 — Tests

```bash
node --check web/views/home.js
[ -f web/views/library.js ] && node --check web/views/library.js
[ -f web/views/library-v5.js ] && node --check web/views/library-v5.js
.venv313/Scripts/python.exe -m unittest tests.test_home* tests.test_library* -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m ruff check . | tail -3
```

### Étape 7 — Commit

`fix(ui): style 'Outils manquants' banner with .alert--warning hierarchy`

---

## LIVRABLES

Récap :
- .alert--warning : créée OU déjà existante
- Bandeau home.js stylé OK
- Bandeau library*.js si applicable
- Tests : 0 régression
- 1-2 commits sur `fix/alert-warning-outils-banner`
