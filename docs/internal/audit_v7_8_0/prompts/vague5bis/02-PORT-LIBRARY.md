# V5bis-02 — Port `library-v5.js` (IIFE → ES module)

**Branche** : `feat/v5bis-port-library`
**Worktree** : `.claude/worktrees/feat-v5bis-port-library/`
**Effort** : 3-4h
**Mode** : 🟢 Parallélisable (après V5bis-00 mergée)
**Fichiers concernés** :
- `web/views/library-v5.js` (port en place)
- `tests/test_library_v5_ported.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5bis-port-library .claude/worktrees/feat-v5bis-port-library audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5bis-port-library

test -f web/views/_v5_helpers.js && echo "✅ helpers présents" || echo "❌ helpers manquants — V5bis-00 pas mergée"

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `web/views/library-v5.js` + son test.

RÈGLE PRESERVATION : conserver TOUTES les features V5A (V2-04 allSettled, V2-08 skeleton).

---

## CONTEXTE

`library-v5.js` (~347L après V5A) est une IIFE qui expose `window.LibraryV5.mount(container, opts)` et utilise `window.pywebview.api.X()` (6 sites).

Features de la vue : table/grid toggle, smart playlists CRUD, 10 filtres, persist localStorage 3 keys.

---

## MISSION

### Étape 1 — Lire l'existant

- `web/views/library-v5.js`
- `web/views/_v5_helpers.js`

### Étape 2 — Identifier les API calls

```bash
grep -n "window.pywebview.api" web/views/library-v5.js
```

Méthodes utilisées (à vérifier) : `get_library_filtered`, `get_smart_playlists`, `save_smart_playlist`, `delete_smart_playlist`, etc.

### Étape 3 — Convertir IIFE → ES module

Remplacer :

```javascript
(function(global) {
  function mount(container, opts) { ... }
  global.LibraryV5 = { mount };
})(window);
```

Par :

```javascript
import { apiPost, escapeHtml, $, $$, el, renderSkeleton, renderError, initView } from "./_v5_helpers.js";

export async function initLibrary(container, opts = {}) {
  await initView(container, _loadLibraryData, _renderLibrary, { skeletonType: "grid" });
}

async function _loadLibraryData(filters) {
  const results = await Promise.allSettled([
    apiPost("get_library_filtered", filters || {}),
    apiPost("get_smart_playlists"),
  ]);
  return {
    library: results[0].status === "fulfilled" ? results[0].value.data : null,
    playlists: results[1].status === "fulfilled" ? results[1].value.data : [],
  };
}

// ... (logique mount actuelle adaptée)
```

### Étape 4 — Migrer les appels API

| AVANT | APRÈS |
|---|---|
| `window.pywebview.api.get_library_filtered(filters)` | `(await apiPost("get_library_filtered", filters)).data` |
| `window.pywebview.api.get_smart_playlists()` | `(await apiPost("get_smart_playlists")).data` |
| `window.pywebview.api.save_smart_playlist(playlist)` | `apiPost("save_smart_playlist", { playlist })` |
| `window.pywebview.api.delete_smart_playlist(id)` | `apiPost("delete_smart_playlist", { playlist_id: id })` |

⚠ Vérifier les noms de paramètres dans `cinesort/ui/api/cinesort_api.py`.

### Étape 5 — Préserver features V5A + design v5

- ✅ V2-04 Promise.allSettled (déjà présent)
- ✅ V2-08 Skeleton (utiliser `renderSkeleton(container, "grid")`)
- ✅ Smart playlists CRUD
- ✅ 10 filtres
- ✅ Toggle table/grid
- ✅ Persist localStorage 3 keys

### Étape 6 — Tests structurels

Crée `tests/test_library_v5_ported.py` :

```python
"""V5bis-02 — Vérifie library-v5.js porté."""
from __future__ import annotations
import unittest
from pathlib import Path


class LibraryV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/library-v5.js").read_text(encoding="utf-8")

    def test_es_module_export(self):
        self.assertIn("export async function initLibrary", self.src)

    def test_no_more_iife_global(self):
        self.assertNotIn("window.LibraryV5", self.src)

    def test_imports_helpers(self):
        self.assertIn('from "./_v5_helpers.js"', self.src)

    def test_no_pywebview_api(self):
        self.assertNotIn("window.pywebview.api", self.src)

    def test_apiPost_used(self):
        self.assertIn("apiPost", self.src)
        self.assertIn("get_library_filtered", self.src)

    def test_v2_04_allsettled(self):
        self.assertIn("Promise.allSettled", self.src)

    def test_smart_playlists_crud(self):
        self.assertIn("get_smart_playlists", self.src)
        self.assertIn("save_smart_playlist", self.src)
        self.assertIn("delete_smart_playlist", self.src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 7 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_library_v5_ported -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/library-v5.js 2>&1 | tail -2
```

### Étape 8 — Commits

- `refactor(library-v5): convert IIFE to ES module + REST apiPost (V5bis-02)`
- `refactor(library-v5): migrate window.pywebview.api calls → apiPost`
- `test(library-v5): structural tests confirm port + features preserved`

---

## LIVRABLES

- `library-v5.js` converti, exporte `initLibrary(container, opts)`
- 0 appel `window.pywebview.api`
- Smart playlists, filtres, table/grid toggle préservés
- V2-04 + V2-08 préservés
- 3 commits sur `feat/v5bis-port-library`
