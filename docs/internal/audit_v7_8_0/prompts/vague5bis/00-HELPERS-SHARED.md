# V5bis-00 — Module helpers shared pour les vues v5 portées

**Branche** : `feat/v5bis-helpers-shared`
**Worktree** : `.claude/worktrees/feat-v5bis-helpers-shared/`
**Effort** : 2-3h
**Mode** : 🟠 SÉQUENTIEL (à faire EN PREMIER, les 7 autres missions V5bis en dépendent)
**Fichiers concernés** :
- `web/views/_v5_helpers.js` (nouveau — module shared)
- `tests/test_v5_helpers.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5bis-helpers-shared .claude/worktrees/feat-v5bis-helpers-shared audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5bis-helpers-shared

pwd && git branch --show-current && git status
```

---

## CONTEXTE

Avant de porter les 7 vues v5 (V5bis-01 à 07), on crée le module shared
`_v5_helpers.js` qui mutualise :

1. **`apiPost(method, params)`** : wrapper REST qui marche en mode SPA distant (HTTP) ET en mode pywebview natif (avec fallback `window.pywebview.api.X` si présent — pour rétrocompatibilité tant que les 2 systèmes coexistent pendant V5bis).

2. **Helpers DOM** : `escapeHtml`, `$`, `$$`, etc. (déjà partiellement disponibles dans `web/dashboard/core/dom.js` mais on consolide pour les vues v5).

3. **Pattern d'init standardisé** : utilitaires pour skeleton, error state, etc.

---

## MISSION

### Étape 1 — Lire l'existant

- `web/dashboard/core/api.js` (la fonction `apiPost` du SPA)
- `web/dashboard/core/dom.js` (helpers DOM dashboard)
- `web/core/api.js` (helper apiCall legacy avec window.pywebview.api)

### Étape 2 — Créer `_v5_helpers.js`

Crée `web/views/_v5_helpers.js` :

```javascript
/* _v5_helpers.js — Module shared pour les vues v5 portées (V5bis)
 *
 * Pattern : ES modules + REST apiPost (compatible SPA dashboard distant
 * ET pywebview natif via le serveur REST local).
 *
 * Compat : tant que web/views/*.js IIFE coexiste, ce module ne casse rien
 * (les vues IIFE n'importent rien). Quand V5C supprimera l'ancienne
 * couche, ce helper restera la base unique.
 */

// Re-export depuis le client REST du SPA dashboard
// ⚠ Chemin résolu depuis web/views/*.js → ../dashboard/core/api.js
import { apiPost as _spaApiPost, apiGet as _spaApiGet } from "../dashboard/core/api.js";
import { escapeHtml as _escapeHtml, $, $$, el } from "../dashboard/core/dom.js";

/**
 * Wrapper apiPost compatible SPA + pywebview legacy.
 * Préfère le client REST (qui marche partout). Fallback window.pywebview.api
 * pour les migrations partielles (à supprimer en V5C).
 *
 * @param {string} method - nom de la méthode CineSortApi
 * @param {object} [params] - paramètres en kwargs (objet, pas array)
 * @returns {Promise<{data?, ok?, error?, ...}>}
 */
export async function apiPost(method, params) {
  try {
    return await _spaApiPost(method, params || {});
  } catch (e) {
    // Si REST indisponible mais pywebview natif présent, on bascule
    if (typeof window !== "undefined" && window.pywebview?.api?.[method]) {
      try {
        const args = _kwargsToPositional(method, params);
        const res = await window.pywebview.api[method](...args);
        // Normalise la réponse pywebview pour matcher le format REST {data, ok}
        return _normalizePywebviewResponse(res);
      } catch (e2) {
        return { ok: false, error: String(e2) };
      }
    }
    return { ok: false, error: String(e) };
  }
}

/** Convertit les kwargs en positional pour pywebview (si nécessaire). */
function _kwargsToPositional(method, params) {
  if (!params || typeof params !== "object") return [];
  // Cas simple : 1 seul param objet, on le passe tel quel
  // Pour les méthodes qui ont plusieurs args nommés, le frontend devra
  // passer dans le bon ordre. Ce helper est imparfait — préférer REST.
  return Object.values(params);
}

function _normalizePywebviewResponse(res) {
  // pywebview retourne directement la valeur (pas wrappée).
  // On wrappe pour matcher le format REST {data, ok}.
  if (res && typeof res === "object" && ("data" in res || "ok" in res)) {
    return res;
  }
  return { data: res, ok: true };
}

/** Helper apiGet (pour /health, /spec). */
export async function apiGet(path) {
  return _spaApiGet(path);
}

/** Re-export DOM helpers. */
export const escapeHtml = _escapeHtml;
export { $, $$, el };

/* ============================================================
   Pattern d'init standardisé
   ============================================================ */

/** Affiche un skeleton générique pendant le chargement. */
export function renderSkeleton(container, type = "default") {
  const skeletons = {
    default: `<div class="v5-skeleton">${"<div class='v5-skeleton-row'></div>".repeat(5)}</div>`,
    table: `<div class="v5-skeleton-table">${"<div class='v5-skeleton-row'></div>".repeat(10)}</div>`,
    grid: `<div class="v5-skeleton-grid">${"<div class='v5-skeleton-card'></div>".repeat(8)}</div>`,
    form: `<div class="v5-skeleton-form">${"<div class='v5-skeleton-field'></div>".repeat(6)}</div>`,
  };
  container.innerHTML = skeletons[type] || skeletons.default;
}

/** Affiche un état d'erreur. */
export function renderError(container, error, retryFn) {
  container.innerHTML = `
    <div class="v5-error-state">
      <h3>Une erreur est survenue</h3>
      <p>${escapeHtml(error?.message || error || "Erreur inconnue")}</p>
      ${retryFn ? `<button class="v5-btn v5-btn--primary" data-v5-retry>Réessayer</button>` : ""}
    </div>
  `;
  if (retryFn) {
    container.querySelector("[data-v5-retry]")?.addEventListener("click", retryFn);
  }
}

/** Wrapper standard pour init de vue : skeleton → load → render | error. */
export async function initView(container, loader, renderer, opts = {}) {
  if (!container) return;
  renderSkeleton(container, opts.skeletonType || "default");
  try {
    const data = await loader();
    renderer(container, data);
  } catch (e) {
    renderError(container, e, () => initView(container, loader, renderer, opts));
  }
}

/* ============================================================
   Utilitaires métier
   ============================================================ */

/** Détecte si on tourne en pywebview natif. */
export function isNativeMode() {
  return !!window.__CINESORT_NATIVE__;
}

/** Format une taille en bytes vers KB/MB/GB lisible. */
export function formatSize(bytes) {
  if (!bytes || bytes < 0) return "—";
  const units = ["o", "Ko", "Mo", "Go", "To"];
  let i = 0; let v = bytes;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

/** Format ms → "X s" / "X min" lisible. */
export function formatDuration(ms) {
  if (!ms) return "—";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r > 0 ? `${m} min ${r} s` : `${m} min`;
}
```

### Étape 3 — Adapter le mapping API

Le wrapper `apiPost` standardise l'API. **Important** : le client REST `_spaApiPost`
attend `(method, params)` et renvoie déjà un objet `{ data, ok, error }`. Le code
ci-dessus est cohérent.

⚠ **À vérifier** : lis `web/dashboard/core/api.js` pour confirmer la signature
exacte de `apiPost`. Si elle diffère, adapte le wrapper.

### Étape 4 — Tests

Crée `tests/test_v5_helpers.py` :

```python
"""V5bis-00 — Vérifie le module shared _v5_helpers.js."""
from __future__ import annotations
import unittest
from pathlib import Path


class V5HelpersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/_v5_helpers.js").read_text(encoding="utf-8")

    def test_apiPost_exported(self):
        self.assertIn("export async function apiPost", self.src)

    def test_apiPost_uses_rest_first(self):
        self.assertIn("_spaApiPost", self.src)
        self.assertIn("from \"../dashboard/core/api.js\"", self.src)

    def test_apiPost_fallback_pywebview(self):
        # Fallback pywebview présent
        self.assertIn("window.pywebview", self.src)

    def test_dom_helpers_exported(self):
        self.assertIn("export const escapeHtml", self.src)
        self.assertIn("export { $, $$, el }", self.src)

    def test_init_view_pattern(self):
        self.assertIn("export async function initView", self.src)
        self.assertIn("renderSkeleton", self.src)
        self.assertIn("renderError", self.src)

    def test_skeleton_types(self):
        # 4 skeletons de base
        for t in ["default", "table", "grid", "form"]:
            self.assertIn(f'"{t}"', self.src)

    def test_utility_helpers(self):
        self.assertIn("export function formatSize", self.src)
        self.assertIn("export function formatDuration", self.src)
        self.assertIn("export function isNativeMode", self.src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 5 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_v5_helpers -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/_v5_helpers.js 2>&1 | tail -2
```

### Étape 6 — Commits

- `feat(v5-helpers): create shared module for ESM-ported v5 views (V5bis-00)`
- `test(v5-helpers): structural tests for apiPost wrapper + skeleton/error/init patterns`

---

## LIVRABLES

- `web/views/_v5_helpers.js` avec :
  - `apiPost(method, params)` (REST first, fallback pywebview natif)
  - `apiGet(path)`
  - Re-export de `escapeHtml`, `$`, `$$`, `el`
  - `renderSkeleton`, `renderError`, `initView` (pattern standard)
  - `isNativeMode`, `formatSize`, `formatDuration`
- Test structurel
- 2 commits sur `feat/v5bis-helpers-shared`

---

## ⚠️ Pourquoi cette mission DOIT être faite en premier

Les 7 missions V5bis-01 à 07 importent depuis ce module shared. Si elles tournent
en parallèle SANS que `_v5_helpers.js` existe, elles cassent toutes.

**Ordre d'exécution requis** :
1. V5bis-00 mergée d'abord
2. Puis V5bis-01 à 07 en parallèle (peuvent toutes lire depuis `_v5_helpers.js`)
