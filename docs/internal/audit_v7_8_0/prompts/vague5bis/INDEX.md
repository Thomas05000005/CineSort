# Index Vague 5-bis — Port vues v5 IIFE → ES modules + REST apiPost

**Date** : 2 mai 2026
**Pré-requis** : Vague 5A mergée ✅
**Cause** : audit V5B-01 a révélé que les vues v5 dans `web/views/*.js` sont des **scripts globaux IIFE** appelant `window.pywebview.api.X()` directement. Inutilisables tels quels dans le SPA dashboard (qui charge des ES modules + REST).

---

## ⚠️ Décision architecturale

Au lieu d'activer V5B brut (qui aurait crashé), on **port d'abord les 7 vues v5** vers le pattern ES module + REST apiPost. Une fois ce port fait, V5B (activation) devient trivial.

---

## 🌊 Missions Phase V5-bis

### Préparatoire (séquentiel, à faire EN PREMIER)

| # | Fichier | Effort | Status |
|---|---|---|---|
| **V5bis-00** | [00-HELPERS-SHARED.md](00-HELPERS-SHARED.md) | 2-3h | À lancer en premier (les autres en dépendent) |

### Port vues (7 missions parallèles, après V5bis-00)

| # | Vue | Branche | Worktree | Lignes source | Effort |
|---|---|---|---|---|---|
| V5bis-01 | [01-PORT-HOME.md](01-PORT-HOME.md) | `feat/v5bis-port-home` | `feat-v5bis-port-home` | 718L | 4-6h |
| V5bis-02 | [02-PORT-LIBRARY.md](02-PORT-LIBRARY.md) | `feat/v5bis-port-library` | `feat-v5bis-port-library` | 310L | 3-4h |
| V5bis-03 | [03-PORT-QIJ.md](03-PORT-QIJ.md) | `feat/v5bis-port-qij` | `feat-v5bis-port-qij` | 475L | 4-6h |
| V5bis-04 | [04-PORT-PROCESSING.md](04-PORT-PROCESSING.md) | `feat/v5bis-port-processing` | `feat-v5bis-port-processing` | 543L | 6-8h (le plus lourd) |
| V5bis-05 | [05-PORT-SETTINGS.md](05-PORT-SETTINGS.md) | `feat/v5bis-port-settings` | `feat-v5bis-port-settings` | 855L | 6-8h (le plus lourd) |
| V5bis-06 | [06-PORT-FILM-DETAIL.md](06-PORT-FILM-DETAIL.md) | `feat/v5bis-port-film-detail` | `feat-v5bis-port-film-detail` | 507L | 4-6h |
| V5bis-07 | [07-PORT-HELP.md](07-PORT-HELP.md) | `feat/v5bis-port-help` | `feat-v5bis-port-help` | 376L | 2-3h |

**Estimation parallèle (7 instances)** : ~1 jour
**Estimation séquentielle** : 4-5 jours

---

## 🚀 Quand toutes les V5bis sont mergées

Reviens vers l'orchestrateur avec : **« V5bis done, génère V5B »**.

V5B = 1 mission monolithique (refonte `app.js` + `index.html` pour activer le shell v5 + utiliser les vues v5 portées).

V5C = cleanup (suppression vues v4 obsolètes + ancienne sidebar HTML statique).

---

## 🎯 Pattern de port (référence)

### AVANT (IIFE legacy webview)

```javascript
(function() {
  function _apiCall(method, args) {
    return window.pywebview.api[method](...args);
  }
  function mount(container, opts) {
    container.innerHTML = "...";
    _apiCall("get_dashboard", []).then(data => render(data));
  }
  window.LibraryV5 = { mount };
})();
```

### APRÈS (ES module SPA dashboard)

```javascript
import { apiPost } from "./_v5_helpers.js";  // helper shared (V5bis-00)
import { escapeHtml } from "./_v5_helpers.js";

export async function initLibrary(container, opts) {
  container.innerHTML = "...";
  const res = await apiPost("get_dashboard");
  if (res.data) render(res.data);
}
```

### Mapping API

| AVANT | APRÈS |
|---|---|
| `window.pywebview.api.get_settings()` | `(await apiPost("get_settings")).data` |
| `window.pywebview.api.save_settings(settings)` | `await apiPost("save_settings", { settings })` |
| `window.pywebview.api.start_plan(settings, root)` | `await apiPost("start_plan", { settings, root })` |
| `window.pywebview.api.X()` (positionnel) | `await apiPost("X", { ...kwargs })` (kwargs) |

⚠ **Important** : `apiPost` envoie le body JSON splatté en `**params` côté backend Python. Donc passe les arguments comme un objet `{key: value}`, pas un array positionnel.

### Mapping mounting

| AVANT | APRÈS |
|---|---|
| `window.LibraryV5.mount(container, opts)` | `initLibrary(container, opts)` |
| Auto-attachement IIFE au load | Export ESM appelé explicitement |
