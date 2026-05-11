# V2-03 — Draft auto décisions validation (localStorage)

**Branche** : `feat/validation-auto-draft`
**Worktree** : `.claude/worktrees/feat-validation-auto-draft/`
**Effort** : 1 jour
**Priorité** : 🔴 IMPORTANT (audit ID-J-002 / ID-NAV-003 — perte décisions sur crash)
**Fichiers concernés** :
- `web/views/validation.js`
- `web/dashboard/views/review.js`
- `tests/test_validation_draft.py` (nouveau)
- éventuellement `web/core/state.js` (helper localStorage générique)

⚠ Coordination avec V2-04 : V2-04 touche aussi review.js (pour Promise.allSettled).
Sections différentes du fichier — auto-merge devrait OK.

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/validation-auto-draft .claude/worktrees/feat-validation-auto-draft audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-validation-auto-draft

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

PROJET : CineSort, 2000 users en attente.
RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT validation.js + review.js + nouveau test.

---

## CONTEXTE

L'audit Lot 3 a montré : si l'utilisateur coche 47 films dans Validation puis :
- Refresh par accident
- Crash navigateur / pywebview
- Win update reboot
- Apply puis modal kill

→ **toutes les décisions perdues** (state in-memory uniquement).

Avec 2000 users, ce sera la cause #1 de plaintes "j'ai perdu mon travail".

---

## MISSION

### Étape 1 — Lire l'état actuel

Lis `web/views/validation.js` pour comprendre où sont stockées les décisions.
Probablement `state.decisions = { row_id: { ok, year, edited } }` ou similaire.

Lis `web/dashboard/views/review.js` pour le pattern dashboard.

### Étape 2 — Implémenter draft auto desktop

Dans `web/views/validation.js` :

```javascript
const VAL_DRAFT_KEY_PREFIX = "val_draft_";  // val_draft_<run_id>
const VAL_DRAFT_TTL_MS = 30 * 24 * 60 * 60 * 1000; // 30 jours

let _draftSaveTimer = null;

function _scheduleDraftSave() {
  // Debounce 500ms : éviter d'écrire à chaque clic
  if (_draftSaveTimer) clearTimeout(_draftSaveTimer);
  _draftSaveTimer = setTimeout(_saveDraft, 500);
}

function _saveDraft() {
  if (!state.runId || !state.decisions) return;
  try {
    const payload = {
      ts: Date.now(),
      runId: state.runId,
      decisions: state.decisions,
    };
    localStorage.setItem(VAL_DRAFT_KEY_PREFIX + state.runId, JSON.stringify(payload));
  } catch (e) {
    console.warn("[validation] draft save failed", e);  // quota ou private mode
  }
}

function _checkAndOfferRestore() {
  if (!state.runId) return;
  let raw;
  try {
    raw = localStorage.getItem(VAL_DRAFT_KEY_PREFIX + state.runId);
  } catch (e) { return; }
  if (!raw) return;
  let draft;
  try {
    draft = JSON.parse(raw);
  } catch (e) { return; }
  if (!draft || !draft.decisions) return;

  // Garde-fou 30 jours
  const age = Date.now() - (draft.ts || 0);
  if (age > VAL_DRAFT_TTL_MS) {
    _clearDraft();
    return;
  }

  // Banner restore
  _showRestoreBanner(draft);
}

function _showRestoreBanner(draft) {
  const date = new Date(draft.ts).toLocaleString("fr-FR");
  const count = Object.keys(draft.decisions).length;
  const html = `<div class="alert alert--info" id="valDraftBanner">
    <span>Décisions non sauvegardées du <strong>${date}</strong> (${count} films).</span>
    <button class="btn btn--compact" id="valDraftRestore">Restaurer</button>
    <button class="btn btn--compact" id="valDraftDiscard">Ignorer</button>
  </div>`;
  // Insertion en haut du conteneur validation
  const root = document.getElementById("validationContainer") || document.querySelector(".view-validation");
  if (!root) return;
  root.insertAdjacentHTML("afterbegin", html);
  document.getElementById("valDraftRestore")?.addEventListener("click", () => _restoreDraft(draft));
  document.getElementById("valDraftDiscard")?.addEventListener("click", () => _discardDraft());
}

function _restoreDraft(draft) {
  state.decisions = { ...state.decisions, ...draft.decisions };
  document.getElementById("valDraftBanner")?.remove();
  if (typeof renderValidation === "function") renderValidation();
}

function _discardDraft() {
  _clearDraft();
  document.getElementById("valDraftBanner")?.remove();
}

function _clearDraft() {
  if (!state.runId) return;
  try {
    localStorage.removeItem(VAL_DRAFT_KEY_PREFIX + state.runId);
  } catch (e) {}
}
```

### Étape 3 — Hooks dans validation.js

- À chaque mutation de `state.decisions` (toggle ok, edit year) → `_scheduleDraftSave()`
- Au mount de la vue après load_validation → `_checkAndOfferRestore()`
- Au save_validation réussi (server confirmation) → `_clearDraft()`

### Étape 4 — Pareil dans dashboard/views/review.js

Adapte pour le dashboard distant (peut-être avec `apiPost("save_validation")` au lieu de pywebview).

### Étape 5 — Tests

Crée `tests/test_validation_draft.py` :

```python
"""V2-03 — vérifie présence du système draft auto dans validation.js + review.js"""
from pathlib import Path
import unittest


class ValidationDraftTests(unittest.TestCase):
    def test_validation_uses_localstorage_draft(self):
        src = (Path(__file__).resolve().parent.parent / "web/views/validation.js").read_text(encoding="utf-8")
        self.assertIn("val_draft_", src)
        self.assertIn("localStorage.setItem", src)
        self.assertIn("localStorage.getItem", src)

    def test_validation_has_restore_banner(self):
        src = (Path(__file__).resolve().parent.parent / "web/views/validation.js").read_text(encoding="utf-8")
        self.assertIn("valDraftRestore", src)
        self.assertIn("valDraftDiscard", src)

    def test_validation_clears_draft_on_save(self):
        src = (Path(__file__).resolve().parent.parent / "web/views/validation.js").read_text(encoding="utf-8")
        self.assertIn("_clearDraft", src)

    def test_review_dashboard_has_draft(self):
        src = (Path(__file__).resolve().parent.parent / "web/dashboard/views/review.js").read_text(encoding="utf-8")
        self.assertIn("val_draft_", src)

    def test_30day_ttl_constant(self):
        src = (Path(__file__).resolve().parent.parent / "web/views/validation.js").read_text(encoding="utf-8")
        self.assertIn("VAL_DRAFT_TTL_MS", src)
```

### Étape 6 — Vérifications

```bash
node --check web/views/validation.js
node --check web/dashboard/views/review.js
.venv313/Scripts/python.exe -m unittest tests.test_validation_draft -v 2>&1 | tail -5
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 7 — Commits

- `feat(validation): localStorage draft auto + restore banner (audit ID-J-002)`
- `feat(review): localStorage draft auto for dashboard distant`
- `test(validation): structural tests for draft persistence`

---

## LIVRABLES

Récap :
- Draft auto desktop validation.js : OK
- Draft auto dashboard review.js : OK
- Banner restore avec compteur films
- TTL 30 jours
- Tests structurels
- 0 régression
- 3 commits sur `feat/validation-auto-draft`
