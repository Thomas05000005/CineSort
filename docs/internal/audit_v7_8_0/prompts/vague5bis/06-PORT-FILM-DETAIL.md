# V5bis-06 — Port `film-detail.js` (4 tabs + hero band)

**Branche** : `feat/v5bis-port-film-detail`
**Worktree** : `.claude/worktrees/feat-v5bis-port-film-detail/`
**Effort** : 4-6h
**Mode** : 🟢 Parallélisable (après V5bis-00)
**Fichiers concernés** :
- `web/views/film-detail.js` (port en place)
- `tests/test_film_detail_v5_ported.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5bis-port-film-detail .claude/worktrees/feat-v5bis-port-film-detail audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5bis-port-film-detail

test -f web/views/_v5_helpers.js && echo "✅" || echo "❌"
pwd && git branch --show-current && git status
```

---

## CONTEXTE

`film-detail.js` (~580L après V5A) est la page Film standalone v7.6.0 :
- 4 tabs (Aperçu / Analyse V2 / Historique / Comparaison)
- Hero band poster blur background
- V2-04 Promise.allSettled
- V2-08 Skeleton
- V3-06 Drawer mode mobile (export only, not activated)

IIFE expose `window.FilmDetail.mount(container, filmId, opts)`. 4 sites API.

---

## RÈGLES GLOBALES

Standard V5bis. Préserver les 4 tabs + hero + drawer mobile export.

---

## MISSION

### Étape 1 — Lire + grep

- `web/views/film-detail.js` (~580L)

### Étape 2 — IIFE → ES module

```javascript
import { apiPost, escapeHtml, renderSkeleton, renderError, initView } from "./_v5_helpers.js";

export async function initFilmDetail(container, opts = {}) {
  const filmId = opts.filmId || _extractFilmIdFromHash();
  if (!filmId) {
    renderError(container, "Film ID manquant");
    return;
  }

  await initView(
    container,
    () => _loadFilmFull(filmId),
    (c, data) => _renderFilmDetail(c, data, opts),
    { skeletonType: "default" }
  );
}

async function _loadFilmFull(filmId) {
  const results = await Promise.allSettled([
    apiPost("get_film_full", { row_id: filmId }),
    apiPost("get_film_history", { film_id: filmId }),
  ]);
  return {
    full: results[0].status === "fulfilled" ? results[0].value.data : null,
    history: results[1].status === "fulfilled" ? results[1].value.data : null,
  };
}

function _renderFilmDetail(container, data, opts) {
  // ... (4 tabs + hero préservés)
}

/** Export drawer mobile mode pour V5C ou usage futur. */
export function mountFilmDetailDrawer(container, filmId, opts = {}) {
  // ... (préservé tel quel, juste ESM)
}

function _extractFilmIdFromHash() {
  // hash "#/film/abc123" → "abc123"
  const m = window.location.hash.match(/^#\/film\/([^\/?]+)/);
  return m ? m[1] : null;
}
```

### Étape 3 — Migrer API

Méthodes : `get_film_full`, `get_film_history`, `analyze_perceptual_batch` (si lancement perceptual depuis ici), `compare_perceptual` (tab Comparaison).

### Étape 4 — Tests

Crée `tests/test_film_detail_v5_ported.py` :

```python
"""V5bis-06 — Vérifie film-detail.js porté."""
from __future__ import annotations
import unittest
from pathlib import Path


class FilmDetailV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/film-detail.js").read_text(encoding="utf-8")

    def test_es_module_init(self):
        self.assertIn("export async function initFilmDetail", self.src)

    def test_es_module_drawer_export(self):
        self.assertIn("export function mountFilmDetailDrawer", self.src)

    def test_no_iife(self):
        self.assertNotIn("window.FilmDetail", self.src)

    def test_no_pywebview_api(self):
        self.assertNotIn("window.pywebview.api", self.src)

    def test_helpers_imported(self):
        self.assertIn('from "./_v5_helpers.js"', self.src)

    def test_get_film_full_used(self):
        self.assertIn("get_film_full", self.src)

    def test_v2_04_allsettled(self):
        self.assertIn("Promise.allSettled", self.src)

    def test_4_tabs_preserved(self):
        # Référence aux 4 tabs (Aperçu / Analyse V2 / Historique / Comparaison)
        for tab in ["overview", "analysis", "history", "comparison"]:
            self.assertIn(tab, self.src.lower(), f"Tab manquant: {tab}")


if __name__ == "__main__":
    unittest.main()
```

### Étape 5 — Vérif + Commits

```bash
.venv313/Scripts/python.exe -m unittest tests.test_film_detail_v5_ported -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/film-detail.js 2>&1 | tail -2
```

- `refactor(film-detail-v5): convert IIFE to ES module + REST apiPost (V5bis-06)`
- `refactor(film-detail-v5): migrate window.pywebview.api → apiPost`
- `test(film-detail-v5): structural tests confirm port + 4 tabs + drawer`

---

## LIVRABLES

- `film-detail.js` ES module : `initFilmDetail(container, opts)` + `mountFilmDetailDrawer(...)`
- 4 tabs préservés
- V2-04 + V2-08 + V3-06 préservés
- 3 commits sur `feat/v5bis-port-film-detail`
