# V2-08 — Skeleton states sur 7 vues

**Branche** : `feat/skeleton-states-everywhere`
**Worktree** : `.claude/worktrees/feat-skeleton-states-everywhere/`
**Effort** : 1-2 jours
**Priorité** : 🟠 IMPORTANT (audit D-PARENT-4)
**Fichiers concernés** :
- `web/components/skeleton.js` (existe — l'enrichir si besoin)
- 7 vues à migrer (à confirmer après lecture audit/lot3_ui_states.md) :
  - `web/dashboard/views/library/library.js`
  - `web/dashboard/views/runs.js`
  - `web/dashboard/views/review.js`
  - `web/dashboard/views/jellyfin.js`
  - `web/dashboard/views/plex.js`
  - `web/dashboard/views/radarr.js`
  - `web/dashboard/views/quality.js`
- éventuellement CSS

⚠ Coordination : V2-04 et V2-07 touchent aussi certaines de ces vues. Lis les prompts
V2-04 + V2-07 pour comprendre où ajouter le skeleton sans conflit. Le skeleton doit
être affiché PENDANT le `await Promise.allSettled(...)` (donc compatible V2-04).

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/skeleton-states-everywhere .claude/worktrees/feat-skeleton-states-everywhere audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-skeleton-states-everywhere

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT skeleton.js + 7 vues + éventuellement CSS.
NE TOUCHE PAS aux mêmes lignes que V2-04 (Promise.allSettled) ou V2-07 (EmptyState).

---

## CONTEXTE

L'audit D-PARENT-4 : seul `web/dashboard/views/status.js` (V-2 audit précédent) a un
skeleton lors du loading. 7+ autres vues affichent du blanc pendant les API calls
→ perception lente, friction UX.

---

## MISSION

### Étape 1 — Lire le pattern référence

Lis `web/components/skeleton.js` pour l'API actuelle.
Lis `web/dashboard/views/status.js` pour voir comment il est utilisé :
- skeleton-grid, skeleton--kpi, etc.
- Pattern : `el.innerHTML = "<div aria-busy='true'>...skeleton-grid...</div>"`
- Puis `await Promise.allSettled(...)` puis remplace par le vrai contenu

### Étape 2 — Identifier précisément les 7 vues sans skeleton

Lis `audit/lot3_ui_states.md` section D-PARENT-4 pour la liste exacte. Ou grep :

```bash
for f in web/dashboard/views/*.js; do
  has_skeleton=$(grep -c "skeleton" "$f" 2>/dev/null)
  echo "$f : $has_skeleton skeleton refs"
done
```

Vues sans skeleton = celles à 0.

### Étape 3 — Pour chaque vue, ajouter un skeleton

Pattern à insérer AVANT `Promise.allSettled` :

```javascript
async function _loadXXX(el) {
  // Skeleton pendant le 1er load (uniquement si conteneur vide)
  if (!el.innerHTML.trim()) {
    el.innerHTML = `<div aria-busy="true" class="skeleton-grid">
      <div class="skeleton skeleton--card"></div>
      <div class="skeleton skeleton--card"></div>
      <div class="skeleton skeleton--card"></div>
    </div>`;
  }

  const results = await Promise.allSettled([
    apiPost("..."),
    apiPost("..."),
  ]);
  // ... rendu réel
}
```

Adapte le markup skeleton à la structure de la vue (KPIs, table, grid).

### Étape 4 — CSS si manquant

Vérifie que les classes `.skeleton`, `.skeleton--card`, `.skeleton--kpi`, `.skeleton-grid`
existent dans le CSS. Si pas → ajoute :

```css
@keyframes skeletonShimmer {
  0% { background-position: -100% 0; }
  100% { background-position: 100% 0; }
}
.skeleton {
  background: linear-gradient(90deg, var(--surface-2) 0%, var(--surface-3) 50%, var(--surface-2) 100%);
  background-size: 200% 100%;
  animation: skeletonShimmer 1.4s ease-in-out infinite;
  border-radius: var(--radius-md);
}
.skeleton--card { height: 96px; }
.skeleton--kpi { height: 64px; }
.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--sp-3);
}

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {
  .skeleton { animation: none; opacity: 0.5; }
}
```

### Étape 5 — Tests

Crée `tests/test_skeleton_states.py` :

```python
"""V2-08 — vérifie que les vues critiques ont un skeleton state."""
from pathlib import Path
import unittest


class SkeletonStatesTests(unittest.TestCase):
    EXPECTED_VIEWS_WITH_SKELETON = [
        "web/dashboard/views/library/library.js",
        "web/dashboard/views/runs.js",
        "web/dashboard/views/review.js",
        "web/dashboard/views/jellyfin.js",
        "web/dashboard/views/plex.js",
        "web/dashboard/views/radarr.js",
        "web/dashboard/views/quality.js",
    ]

    def test_views_have_skeleton_or_aria_busy(self):
        root = Path(__file__).resolve().parent.parent
        for rel in self.EXPECTED_VIEWS_WITH_SKELETON:
            src = (root / rel).read_text(encoding="utf-8")
            has_skeleton = "skeleton" in src.lower() or "aria-busy" in src
            self.assertTrue(has_skeleton, f"{rel} : ni skeleton ni aria-busy trouvé")

    def test_css_skeleton_classes_defined(self):
        root = Path(__file__).resolve().parent.parent
        css_files = list(root.glob("web/**/*.css"))
        found = False
        for f in css_files:
            if ".skeleton" in f.read_text(encoding="utf-8"):
                found = True
                break
        self.assertTrue(found, "CSS .skeleton non trouvé")
```

### Étape 6 — Vérifications

```bash
for f in web/dashboard/views/library/library.js web/dashboard/views/runs.js \
         web/dashboard/views/review.js web/dashboard/views/jellyfin.js \
         web/dashboard/views/plex.js web/dashboard/views/radarr.js \
         web/dashboard/views/quality.js; do
  [ -f "$f" ] && node --check "$f"
done
.venv313/Scripts/python.exe -m unittest tests.test_skeleton_states -v 2>&1 | tail -5
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 7 — Commits

1-3 commits :
- `feat(skeleton): add CSS classes if missing`
- `feat(skeleton): apply to library/runs/review (3 vues)`
- `feat(skeleton): apply to integrations + quality (4 vues)`

---

## LIVRABLES

Récap :
- 7 vues avec skeleton state
- CSS skeleton-* OK (créé ou vérifié)
- Tests structurels
- 0 régression
- 1-3 commits sur `feat/skeleton-states-everywhere`
