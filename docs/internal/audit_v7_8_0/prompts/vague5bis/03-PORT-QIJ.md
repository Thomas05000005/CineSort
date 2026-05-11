# V5bis-03 — Port `qij-v5.js` (Quality + Integrations + Journal)

**Branche** : `feat/v5bis-port-qij`
**Worktree** : `.claude/worktrees/feat-v5bis-port-qij/`
**Effort** : 4-6h
**Mode** : 🟢 Parallélisable (après V5bis-00)
**Fichiers concernés** :
- `web/views/qij-v5.js` (port en place)
- `tests/test_qij_v5_ported.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5bis-port-qij .claude/worktrees/feat-v5bis-port-qij audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5bis-port-qij

test -f web/views/_v5_helpers.js && echo "✅ helpers OK" || echo "❌ V5bis-00 manquante"
pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

Standard V5bis — préserver V5A features (V1-05 EmptyState + V3-03 glossaire + V2-08 skeleton).

---

## CONTEXTE

`qij-v5.js` (~570L après V5A) consolide Quality + Integrations + Journal en une seule vue (Vague 7 v7.6.0). IIFE expose 3 objets globaux : `window.QualityV5.mount(...)`, `window.IntegrationsV5.mount(...)`, `window.JournalV5.mount(...)`.

9 sites d'appels `window.pywebview.api.X()`.

---

## MISSION

### Étape 1 — Lire + grep API

- `web/views/qij-v5.js`
- `web/views/_v5_helpers.js`
- `grep -n "window.pywebview.api" web/views/qij-v5.js`

### Étape 2 — Convertir 3 IIFE → 3 exports nommés

```javascript
import { apiPost, escapeHtml, renderSkeleton, initView } from "./_v5_helpers.js";
import { glossaryTooltip } from "../dashboard/components/glossary-tooltip.js";
import { buildEmptyState, bindEmptyStateCta } from "../dashboard/components/empty-state.js";

export async function initQuality(container, opts = {}) {
  await initView(container, _loadQualityData, _renderQuality, { skeletonType: "table" });
}

export async function initIntegrations(container, opts = {}) {
  await initView(container, _loadIntegrationsData, _renderIntegrations);
}

export async function initJournal(container, opts = {}) {
  await initView(container, _loadJournalData, _renderJournal, { skeletonType: "table" });
}

// Pour QIJ consolidé :
export async function initQij(container, opts = {}) {
  // Vue parent qui contient les 3 sous-vues comme tabs
  const html = `
    <div class="v5-qij-tabs">
      <button data-qij-tab="quality" class="is-active">Qualité</button>
      <button data-qij-tab="integrations">Intégrations</button>
      <button data-qij-tab="journal">Journal</button>
    </div>
    <div id="v5QijQualityPanel"></div>
    <div id="v5QijIntegrationsPanel" hidden></div>
    <div id="v5QijJournalPanel" hidden></div>
  `;
  container.innerHTML = html;
  await initQuality(document.getElementById("v5QijQualityPanel"), opts);
  // ... wire tab switch
}
```

### Étape 3 — Migrer API

| AVANT | APRÈS |
|---|---|
| `window.pywebview.api.get_global_stats()` | `apiPost("get_global_stats")` |
| `window.pywebview.api.get_scoring_rollup(by, limit)` | `apiPost("get_scoring_rollup", { by, limit })` |
| `window.pywebview.api.test_jellyfin_connection(url, key, timeout)` | `apiPost("test_jellyfin_connection", { url, api_key: key, timeout_s: timeout })` |
| `window.pywebview.api.get_jellyfin_libraries()` | `apiPost("get_jellyfin_libraries")` |

Vérifier la signature backend dans `cinesort_api.py`.

### Étape 4 — Préserver V5A

- ✅ V1-05 EmptyState CTA Quality (`buildEmptyState` import)
- ✅ V3-03 Glossary tooltips (≥ 5 occurrences)
- ✅ V2-08 Skeleton complete

### Étape 5 — Tests

Crée `tests/test_qij_v5_ported.py` :

```python
"""V5bis-03 — Vérifie qij-v5.js porté."""
from __future__ import annotations
import unittest
from pathlib import Path


class QijV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/qij-v5.js").read_text(encoding="utf-8")

    def test_es_module_exports(self):
        self.assertIn("export async function initQuality", self.src)
        self.assertIn("export async function initIntegrations", self.src)
        self.assertIn("export async function initJournal", self.src)
        self.assertIn("export async function initQij", self.src)

    def test_no_iife_globals(self):
        for g in ["window.QualityV5", "window.IntegrationsV5", "window.JournalV5"]:
            self.assertNotIn(g, self.src, f"Global encore présent: {g}")

    def test_no_pywebview_api(self):
        self.assertNotIn("window.pywebview.api", self.src)

    def test_helpers_imported(self):
        self.assertIn('from "./_v5_helpers.js"', self.src)
        self.assertIn("glossaryTooltip", self.src)
        self.assertIn("buildEmptyState", self.src)

    def test_v1_05_empty_state(self):
        self.assertIn("buildEmptyState", self.src)
        self.assertIn("Lancer un scan", self.src)

    def test_v3_03_glossary(self):
        self.assertGreaterEqual(self.src.count("glossaryTooltip("), 5)


if __name__ == "__main__":
    unittest.main()
```

### Étape 6 — Vérif + Commits

```bash
.venv313/Scripts/python.exe -m unittest tests.test_qij_v5_ported -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/qij-v5.js 2>&1 | tail -2
```

- `refactor(qij-v5): convert 3 IIFE → ES module exports (V5bis-03)`
- `refactor(qij-v5): migrate window.pywebview.api → apiPost`
- `test(qij-v5): structural tests confirm port + V5A features`

---

## LIVRABLES

- `qij-v5.js` exporte `initQuality`, `initIntegrations`, `initJournal`, `initQij`
- 0 IIFE, 0 pywebview.api
- V1-05 + V3-03 + V2-08 préservés
- 3 commits sur `feat/v5bis-port-qij`
