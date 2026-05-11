# V5A-07 — Library + Film v5 enrichis (V2-04 + V2-08 + V3-06)

**Branche** : `feat/v5a-library-film-port`
**Worktree** : `.claude/worktrees/feat-v5a-library-film-port/`
**Effort** : 4-6h
**Mode** : 🟢 Parallélisable
**Fichiers concernés** :
- `web/views/library-v5.js` (enrichissement)
- `web/views/film-detail.js` (enrichissement)
- `tests/test_library_film_v5_features.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5a-library-film-port .claude/worktrees/feat-v5a-library-film-port audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5a-library-film-port

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `library-v5.js` + `film-detail.js` + leurs tests.

RÈGLE V5 : préserver smart playlists + 10 filtres + grid/table toggle (library) ET 4 tabs + hero band poster (film-detail).

---

## CONTEXTE

`library-v5.js` (310L) et `film-detail.js` (~507L) sont les vues v5 modernes. Elles ont besoin de :

1. **V2-04** : Promise.allSettled (résilience endpoints qui plantent)
2. **V2-08** : Skeleton loading states
3. **V3-06** : Drawer mobile pour film-detail (hero + tabs en colonne sur < 768px)

---

## MISSION

### Étape 1 — Lire l'existant

- `web/views/library-v5.js` (310L)
- `web/views/film-detail.js` (~507L)
- `web/dashboard/views/library/library.js` (référence skeleton + Promise.allSettled v4)
- `web/dashboard/components/empty-state.js` (composant V2-07 — déjà partiellement utilisé en library-v5)

### Étape 2 — V2-04 Promise.allSettled

Dans `library-v5.js` ET `film-detail.js`, cherche les `Promise.all([...])` et migre vers `Promise.allSettled`. Adapter les consommations :

```javascript
// AVANT
const [lib, playlists] = await Promise.all([
  apiPost("get_library_filtered", filters),
  apiPost("get_smart_playlists"),
]);
renderLibrary(lib.data);

// APRÈS
const results = await Promise.allSettled([
  apiPost("get_library_filtered", filters),
  apiPost("get_smart_playlists"),
]);
const libData = results[0].status === "fulfilled" ? results[0].value.data : null;
const playlists = results[1].status === "fulfilled" ? results[1].value.data : [];
if (libData) renderLibrary(libData);
else renderError("Bibliothèque indisponible");
// Les playlists qui plantent ne bloquent pas la lib
```

### Étape 3 — V2-08 Skeleton states

#### library-v5.js

```javascript
function _renderLibrarySkeleton(container) {
  container.innerHTML = `
    <div class="v5-library-skeleton">
      <div class="v5-skeleton-toolbar"></div>
      <div class="v5-skeleton-filters">
        ${"<div class='v5-skeleton-chip'></div>".repeat(5)}
      </div>
      <div class="v5-skeleton-grid v5-skeleton-grid--cards">
        ${"<div class='v5-skeleton-card'></div>".repeat(12)}
      </div>
    </div>
  `;
}

// Au boot :
export function initLibrary(container) {
  _renderLibrarySkeleton(container);
  _loadAndRender(container).catch(...);
}
```

#### film-detail.js

```javascript
function _renderFilmDetailSkeleton(container) {
  container.innerHTML = `
    <div class="v5-film-detail-skeleton">
      <div class="v5-skeleton-hero"></div>
      <div class="v5-skeleton-tabs"></div>
      <div class="v5-skeleton-content">
        ${"<div class='v5-skeleton-row'></div>".repeat(6)}
      </div>
    </div>
  `;
}

export function initFilmDetail(container, filmId) {
  _renderFilmDetailSkeleton(container);
  _loadFilmAndRender(container, filmId).catch(...);
}
```

### Étape 4 — V3-06 Drawer mobile film-detail

Sur mobile (< 768px), transformer le panneau hero + tabs en layout vertical scrollable + tabs sticky en haut. Si l'utilisateur a cliqué un film depuis la liste library mobile, l'ouverture peut se faire en drawer slide-up plutôt qu'en page complète :

```javascript
function _shouldUseDrawerMode() {
  return window.matchMedia("(max-width: 767px)").matches;
}

function _renderAsDrawer(container, filmId) {
  // Crée un drawer mobile slide-up depuis le bas
  const drawer = document.createElement("div");
  drawer.className = "v5-drawer v5-drawer--bottom v5-film-drawer";
  drawer.setAttribute("role", "dialog");
  drawer.setAttribute("aria-modal", "true");
  drawer.innerHTML = `
    <div class="v5-drawer-handle"></div>
    <div class="v5-drawer-header">
      <button class="v5-btn v5-btn--icon" id="v5BtnCloseFilmDrawer" aria-label="Fermer">×</button>
    </div>
    <div class="v5-drawer-body" id="v5FilmDrawerBody"></div>
  `;
  document.body.appendChild(drawer);
  // Charger le contenu film dans v5FilmDrawerBody
  // ...
  document.getElementById("v5BtnCloseFilmDrawer")?.addEventListener("click", () => drawer.remove());
}
```

⚠ Pour Phase A, on ajoute juste l'export `mountFilmDetailDrawer(container, filmId)` qui sera utilisé en Phase B. Ne pas câbler par défaut.

### Étape 5 — Tests structurels

Crée `tests/test_library_film_v5_features.py` :

```python
"""V5A-07 — Vérifie library-v5 + film-detail enrichis avec V2-04 + V2-08 + V3-06."""
from __future__ import annotations
import unittest
from pathlib import Path


class LibraryV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/library-v5.js").read_text(encoding="utf-8")

    def test_v2_04_promise_allsettled(self):
        self.assertIn("Promise.allSettled", self.src)

    def test_v2_08_skeleton(self):
        self.assertIn("_renderLibrarySkeleton", self.src)
        self.assertIn("v5-library-skeleton", self.src)


class FilmDetailV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/film-detail.js").read_text(encoding="utf-8")

    def test_v2_04_promise_allsettled(self):
        self.assertIn("Promise.allSettled", self.src)

    def test_v2_08_skeleton(self):
        self.assertIn("_renderFilmDetailSkeleton", self.src)

    def test_v3_06_drawer_mode(self):
        self.assertIn("v5-film-drawer", self.src)
        self.assertIn("max-width: 767px", self.src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_library_film_v5_features -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/library-v5.js web/views/film-detail.js 2>&1 | tail -3
```

### Étape 7 — Commits

- `refactor(library-v5,film-v5): V2-04 Promise.allSettled`
- `feat(library-v5): V2-08 skeleton state`
- `feat(film-v5): V2-08 skeleton state`
- `feat(film-v5): V3-06 mobile drawer mode (export only, not activated)`
- `test(library-film-v5): structural tests for V5A-07`

---

## LIVRABLES

- `library-v5.js` + `film-detail.js` enrichis avec 3 features V1-V4
- Test structurel
- Smart playlists + filtres + grid/table préservés (library)
- 4 tabs + hero band préservés (film-detail)
- 5 commits sur `feat/v5a-library-film-port`
