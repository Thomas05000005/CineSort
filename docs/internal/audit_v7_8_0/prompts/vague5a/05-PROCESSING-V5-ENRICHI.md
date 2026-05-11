# V5A-05 — Processing v5 enrichi (5 features V1-V4)

**Branche** : `feat/v5a-processing-port`
**Worktree** : `.claude/worktrees/feat-v5a-processing-port/`
**Effort** : 1 jour
**Mode** : 🟢 Parallélisable
**Fichiers concernés** :
- `web/views/processing.js` (enrichissement)
- `tests/test_processing_v5_features.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5a-processing-port .claude/worktrees/feat-v5a-processing-port audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5a-processing-port

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `web/views/processing.js` + son test.

RÈGLE V5 : préserver le workflow F1 unifié (3 steps continus scan → review → apply, stepper).

---

## CONTEXTE

`processing.js` (543L) est le workflow F1 v7.6.0. Il manque 5 features critiques V1-V4 :

1. **V2-03** : Draft auto validation (localStorage debounce 500ms + restore banner intelligent)
2. **V3-06** : Drawer mobile inspector validation (< 768px)
3. **V2-07** : Composant `<EmptyState>` pour les états vides
4. **V2-08** : Skeleton loading states
5. **V2-04** : Promise.allSettled (résilience)

---

## MISSION

### Étape 1 — Lire l'existant

- `web/views/processing.js` (543L — le fichier à enrichir)
- `web/dashboard/views/review.js` (référence V2-03 draft + V3-06 drawer v4)
- `web/dashboard/components/empty-state.js` (composant V2-07)
- `web/dashboard/views/lib-validation.js` (référence skeleton + autres patterns)

### Étape 2 — V2-04 Promise.allSettled

Cherche les `Promise.all([...])` et migre vers `Promise.allSettled`. Adapter consommation des résultats.

### Étape 3 — V2-08 Skeleton states

Pour chaque step (scan, review, apply), ajouter un état skeleton avant chargement données :

```javascript
function _renderSkeletonForStep(stepEl, stepId) {
  if (stepId === "scan") {
    stepEl.innerHTML = `<div class="v5-skeleton v5-skeleton--scan">...</div>`;
  } else if (stepId === "review") {
    stepEl.innerHTML = `<div class="v5-skeleton-table">
      ${"<div class='v5-skeleton-row'></div>".repeat(10)}
    </div>`;
  } else if (stepId === "apply") {
    stepEl.innerHTML = `<div class="v5-skeleton v5-skeleton--apply">...</div>`;
  }
}
```

### Étape 4 — V2-07 EmptyState

Importer le composant et l'utiliser pour les états vides :

```javascript
import { buildEmptyState, bindEmptyStateCta } from "../dashboard/components/empty-state.js";
// (adapter le path si besoin de shim)

// Step Review sans rows :
if (rows.length === 0) {
  container.innerHTML = buildEmptyState({
    icon: "scan",
    title: "Aucun film à valider",
    description: "Lance un scan pour commencer.",
    cta: { label: "Lancer un scan", route: "#/processing?step=scan" },
  });
  bindEmptyStateCta(container, () => _goToStep("scan"));
  return;
}
```

### Étape 5 — V2-03 Draft auto validation

Pattern complet à porter (référence : `web/dashboard/views/review.js` autour de la fonction `_initDraft` ou similaire) :

```javascript
const DRAFT_KEY_PREFIX = "cinesort.processing.draft.";
const DRAFT_TTL_MS = 30 * 24 * 3600 * 1000; // 30 jours
let _draftSaveTimer = null;

function _draftKey(runId) { return `${DRAFT_KEY_PREFIX}${runId}`; }

/** Sauvegarde debounce 500ms du draft de validation. */
function _scheduleDraftSave(runId, decisions) {
  clearTimeout(_draftSaveTimer);
  _draftSaveTimer = setTimeout(() => {
    try {
      const payload = { ts: Date.now(), decisions };
      localStorage.setItem(_draftKey(runId), JSON.stringify(payload));
    } catch (e) { /* quota dépassé : silencieux */ }
  }, 500);
}

/** Charge un draft s'il existe et n'est pas expiré. */
function _loadDraft(runId) {
  try {
    const raw = localStorage.getItem(_draftKey(runId));
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (Date.now() - data.ts > DRAFT_TTL_MS) {
      localStorage.removeItem(_draftKey(runId));
      return null;
    }
    return data.decisions;
  } catch { return null; }
}

/** Compare draft vs état serveur et propose la restauration si différent. */
async function _checkAndOfferRestore(runId, currentDecisions) {
  const draft = _loadDraft(runId);
  if (!draft) return;
  // Compare clés/valeurs avec currentDecisions
  const isDifferent = JSON.stringify(draft) !== JSON.stringify(currentDecisions);
  if (!isDifferent) return; // identique, rien à proposer

  // Affiche bannière "Brouillon non sauvegardé trouvé"
  _showRestoreBanner(runId, draft);
}

function _showRestoreBanner(runId, draft) {
  const banner = document.createElement("div");
  banner.className = "v5-alert v5-alert--info v5-draft-restore-banner";
  banner.innerHTML = `
    <span>📝 Brouillon non sauvegardé trouvé pour ce run.</span>
    <button class="v5-btn v5-btn--sm" id="v5BtnRestoreDraft">Restaurer</button>
    <button class="v5-btn v5-btn--sm v5-btn--ghost" id="v5BtnDiscardDraft">Ignorer</button>
  `;
  document.body.insertBefore(banner, document.body.firstChild);

  document.getElementById("v5BtnRestoreDraft")?.addEventListener("click", () => {
    _applyDecisions(draft);
    banner.remove();
  });
  document.getElementById("v5BtnDiscardDraft")?.addEventListener("click", () => {
    localStorage.removeItem(_draftKey(runId));
    banner.remove();
  });
}
```

Câbler `_scheduleDraftSave(runId, currentDecisions)` à chaque modification de décision (approve/reject) dans le step Review.

Câbler `_checkAndOfferRestore(runId, currentDecisions)` au mount du step Review.

### Étape 6 — V3-06 Drawer mobile inspector

Pour les écrans < 768px, transformer le panneau "Inspector" du step Review en drawer slide-in :

```javascript
function _renderInspectorMobileDrawer() {
  // Si pas déjà monté
  if (document.getElementById("v5ProcessingInspectorDrawer")) return;
  const drawer = document.createElement("aside");
  drawer.id = "v5ProcessingInspectorDrawer";
  drawer.className = "v5-drawer v5-drawer--right v5-processing-inspector-drawer";
  drawer.setAttribute("role", "dialog");
  drawer.setAttribute("aria-modal", "true");
  drawer.setAttribute("aria-hidden", "true");
  drawer.innerHTML = `
    <div class="v5-drawer-header">
      <h3>Inspecteur film</h3>
      <button class="v5-btn v5-btn--icon" id="v5BtnCloseInspector" aria-label="Fermer">×</button>
    </div>
    <div class="v5-drawer-body" id="v5InspectorBody"></div>
  `;
  document.body.appendChild(drawer);

  document.getElementById("v5BtnCloseInspector")?.addEventListener("click", _closeInspectorDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") _closeInspectorDrawer();
  });
}

function _openInspectorDrawer(rowId) {
  if (window.matchMedia("(min-width: 768px)").matches) {
    // Desktop : utiliser le panel existant
    return;
  }
  _renderInspectorMobileDrawer();
  const drawer = document.getElementById("v5ProcessingInspectorDrawer");
  const body = document.getElementById("v5InspectorBody");
  body.innerHTML = _buildInspectorContent(rowId);
  drawer.classList.add("v5-drawer--open");
  drawer.setAttribute("aria-hidden", "false");
}

function _closeInspectorDrawer() {
  const drawer = document.getElementById("v5ProcessingInspectorDrawer");
  if (!drawer) return;
  drawer.classList.remove("v5-drawer--open");
  drawer.setAttribute("aria-hidden", "true");
}
```

Ajouter un bouton "Inspecter" sur chaque ligne du tableau Review, visible uniquement en mobile (CSS).

### Étape 7 — Tests structurels

Crée `tests/test_processing_v5_features.py` :

```python
"""V5A-05 — Vérifie processing.js v5 enrichi avec 5 features V1-V4."""
from __future__ import annotations
import unittest
from pathlib import Path


class ProcessingV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/processing.js").read_text(encoding="utf-8")

    def test_v2_04_promise_allsettled(self):
        self.assertIn("Promise.allSettled", self.src)

    def test_v2_08_skeleton(self):
        self.assertIn("v5-skeleton", self.src)
        self.assertIn("_renderSkeleton", self.src)

    def test_v2_07_emptystate_imported(self):
        self.assertIn("buildEmptyState", self.src)

    def test_v2_03_draft_auto(self):
        self.assertIn("DRAFT_KEY_PREFIX", self.src)
        self.assertIn("_scheduleDraftSave", self.src)
        self.assertIn("_loadDraft", self.src)
        self.assertIn("localStorage", self.src)
        self.assertIn("_checkAndOfferRestore", self.src)

    def test_v3_06_drawer_mobile(self):
        self.assertIn("v5ProcessingInspectorDrawer", self.src)
        self.assertIn("v5-drawer", self.src)
        self.assertIn("min-width: 768px", self.src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 8 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_processing_v5_features -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/processing.js 2>&1 | tail -2
```

### Étape 9 — Commits

- `refactor(processing-v5): V2-04 Promise.allSettled`
- `feat(processing-v5): V2-08 skeleton states for 3 steps`
- `feat(processing-v5): V2-07 EmptyState integration`
- `feat(processing-v5): V2-03 draft auto with localStorage + restore banner`
- `feat(processing-v5): V3-06 mobile drawer inspector for review step`
- `test(processing-v5): structural tests for V5A-05`

---

## LIVRABLES

- `processing.js` enrichi avec 5 features V1-V4
- Workflow F1 préservé (3 steps unifiés)
- Test structurel
- 6 commits sur `feat/v5a-processing-port`
