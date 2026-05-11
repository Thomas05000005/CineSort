# V5bis-04 — Port `processing.js` (workflow F1, le plus lourd)

**Branche** : `feat/v5bis-port-processing`
**Worktree** : `.claude/worktrees/feat-v5bis-port-processing/`
**Effort** : 6-8h
**Mode** : 🟢 Parallélisable (après V5bis-00)
**Fichiers concernés** :
- `web/views/processing.js` (port en place)
- `tests/test_processing_v5_ported.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5bis-port-processing .claude/worktrees/feat-v5bis-port-processing audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5bis-port-processing

test -f web/views/_v5_helpers.js && echo "✅" || echo "❌"
pwd && git branch --show-current && git status
```

---

## CONTEXTE

`processing.js` (~845L après V5A — workflow F1 unifié 3 steps + draft + drawer + EmptyState + Skeleton + allSettled). IIFE expose `window.ProcessingV5.mount(...)`. 11 sites d'appels API.

C'est la mission la plus lourde de V5bis car le code est complexe (3 steps cohérents, draft localStorage, drawer mobile, etc.).

---

## RÈGLES GLOBALES

Standard V5bis. **Préserver impérativement** :
- V5 workflow F1 (3 steps continus)
- V2-03 Draft auto localStorage
- V3-06 Drawer mobile
- V2-07 EmptyState
- V2-08 Skeleton
- V2-04 Promise.allSettled

---

## MISSION

### Étape 1 — Lire + analyser

- `web/views/processing.js` (~845L)
- `web/views/_v5_helpers.js`
- Identifier les 3 steps (scan/review/apply) et leur logique

### Étape 2 — IIFE → ES module

```javascript
import { apiPost, escapeHtml, renderSkeleton, renderError } from "./_v5_helpers.js";
import { buildEmptyState, bindEmptyStateCta } from "../dashboard/components/empty-state.js";

const STEP_IDS = ["scan", "review", "apply"];
const DRAFT_KEY_PREFIX = "cinesort.processing.draft.";
const DRAFT_TTL_MS = 30 * 24 * 3600 * 1000;

let _state = {
  currentStep: "scan",
  runId: null,
  decisions: {},
  // ...
};
let _draftSaveTimer = null;

export async function initProcessing(container, opts = {}) {
  _state.container = container;
  _state.currentStep = (opts.step || "scan");
  _renderShell(container);
  await _initCurrentStep();
}

function _renderShell(container) {
  container.innerHTML = `
    <div class="v5-processing">
      <nav class="v5-processing-stepper" role="tablist">
        ${STEP_IDS.map((id, i) => _renderStepperItem(id, i)).join("")}
      </nav>
      <div class="v5-processing-content" id="v5ProcessingContent"></div>
    </div>
  `;
}

async function _initCurrentStep() {
  const content = document.getElementById("v5ProcessingContent");
  if (_state.currentStep === "scan") await _initScanStep(content);
  else if (_state.currentStep === "review") await _initReviewStep(content);
  else if (_state.currentStep === "apply") await _initApplyStep(content);
}

// ... 3 fonctions step + draft + drawer mobile + ... (port en gros bloc)
```

### Étape 3 — Migrer API (11 sites)

Méthodes attendues : `start_plan`, `get_status`, `get_plan`, `load_validation`, `save_validation`, `check_duplicates`, `apply`, `cancel_run`, `undo_last_apply_preview`, `undo_last_apply`, etc.

```javascript
// AVANT
const status = await window.pywebview.api.get_status(runId);

// APRÈS
const res = await apiPost("get_status", { run_id: runId });
const status = res.data;
```

### Étape 4 — Draft auto (V2-03)

Conserver le pattern complet :

```javascript
function _scheduleDraftSave(runId, decisions) {
  clearTimeout(_draftSaveTimer);
  _draftSaveTimer = setTimeout(() => {
    try {
      localStorage.setItem(DRAFT_KEY_PREFIX + runId, JSON.stringify({ ts: Date.now(), decisions }));
    } catch (e) { /* quota */ }
  }, 500);
}

function _loadDraft(runId) {
  try {
    const raw = localStorage.getItem(DRAFT_KEY_PREFIX + runId);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (Date.now() - data.ts > DRAFT_TTL_MS) {
      localStorage.removeItem(DRAFT_KEY_PREFIX + runId);
      return null;
    }
    return data.decisions;
  } catch { return null; }
}

async function _checkAndOfferRestore(runId) {
  const draft = _loadDraft(runId);
  if (!draft) return;
  const currentRes = await apiPost("load_validation", { run_id: runId });
  const current = currentRes.data?.decisions || {};
  if (JSON.stringify(draft) === JSON.stringify(current)) return;
  _showRestoreBanner(runId, draft);
}
```

### Étape 5 — Drawer mobile (V3-06)

Conserver le pattern. Adapter pour utiliser les helpers ESM.

### Étape 6 — Tests

Crée `tests/test_processing_v5_ported.py` :

```python
"""V5bis-04 — Vérifie processing.js porté."""
from __future__ import annotations
import unittest
from pathlib import Path


class ProcessingV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/processing.js").read_text(encoding="utf-8")

    def test_es_module_export(self):
        self.assertIn("export async function initProcessing", self.src)

    def test_no_iife(self):
        self.assertNotIn("window.ProcessingV5", self.src)

    def test_no_pywebview_api(self):
        self.assertNotIn("window.pywebview.api", self.src)

    def test_helpers_imported(self):
        self.assertIn('from "./_v5_helpers.js"', self.src)

    def test_v2_03_draft_preserved(self):
        self.assertIn("DRAFT_KEY_PREFIX", self.src)
        self.assertIn("_scheduleDraftSave", self.src)
        self.assertIn("_checkAndOfferRestore", self.src)
        self.assertIn("localStorage", self.src)

    def test_v3_06_drawer_preserved(self):
        self.assertIn("v5ProcessingInspectorDrawer", self.src)

    def test_v2_07_emptystate_preserved(self):
        self.assertIn("buildEmptyState", self.src)

    def test_v2_04_allsettled_preserved(self):
        self.assertIn("Promise.allSettled", self.src)

    def test_three_steps_present(self):
        self.assertIn("_initScanStep", self.src)
        self.assertIn("_initReviewStep", self.src)
        self.assertIn("_initApplyStep", self.src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 7 — Vérif + Commits

```bash
.venv313/Scripts/python.exe -m unittest tests.test_processing_v5_ported -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/processing.js 2>&1 | tail -2
```

- `refactor(processing-v5): convert IIFE to ES module + REST apiPost (V5bis-04)`
- `refactor(processing-v5): migrate 11 window.pywebview.api calls → apiPost`
- `refactor(processing-v5): preserve V2-03 draft + V3-06 drawer + V2-07/V2-08 + V2-04`
- `test(processing-v5): structural tests confirm port + V5A features intact`

---

## LIVRABLES

- `processing.js` ES module exporting `initProcessing(container, opts)`
- Workflow F1 préservé (3 steps continus)
- V2-03 / V3-06 / V2-07 / V2-08 / V2-04 préservés
- 0 pywebview.api, 0 IIFE
- 4 commits sur `feat/v5bis-port-processing`
