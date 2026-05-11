# V5bis-01 — Port `home.js` (IIFE → ES module)

**Branche** : `feat/v5bis-port-home`
**Worktree** : `.claude/worktrees/feat-v5bis-port-home/`
**Effort** : 4-6h
**Mode** : 🟢 Parallélisable (mais APRÈS V5bis-00 mergée)
**Fichiers concernés** :
- `web/views/home.js` (port en place)
- `tests/test_home_v5_ported.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE + V5bis-00 PRÉ-REQUIS)

```bash
cd /c/Users/blanc/projects/CineSort
# Vérifier que V5bis-00 est mergée (sinon attendre)
git log --oneline audit_qa_v7_6_0_dev_20260428 | grep -q "v5-helpers" || echo "⚠ V5bis-00 pas encore mergée — attends"

git worktree add -b feat/v5bis-port-home .claude/worktrees/feat-v5bis-port-home audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5bis-port-home

# Vérifier que _v5_helpers.js existe
test -f web/views/_v5_helpers.js && echo "✅ helpers présents" || echo "❌ helpers manquants — V5bis-00 pas mergée"

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `web/views/home.js` + son test.

RÈGLE PRESERVATION : conserver TOUTES les features (V5A a porté V1-V4 dans cette vue, il ne faut RIEN perdre). Le port est uniquement structural (IIFE → ESM, window.pywebview.api → apiPost).

RÈGLE V5 : conserver la palette v5, le design "data-first", les classes `v5-*`.

---

## CONTEXTE

`web/views/home.js` (~895L après V5A — banner V1-07 + demo wizard V3-05 + CTA V1-06 + allSettled V2-04 + skeleton V2-08) est actuellement un script global IIFE qui :
- Expose des fonctions globales (`refreshHomeOverview`, `startPlan`, etc.)
- Appelle `window.pywebview.api.X()` directement (10 sites)

**Mission** : convertir en ES module qui :
- Exporte `initHome(container, opts)` (pattern standard V5bis)
- Utilise `apiPost(method, params)` depuis `_v5_helpers.js`
- Utilise `escapeHtml`, `$`, etc. depuis `_v5_helpers.js`
- Préserve TOUT le comportement existant

---

## MISSION

### Étape 1 — Lire l'existant

- `web/views/home.js` (~895L — l'actuel à porter)
- `web/views/_v5_helpers.js` (helpers V5bis-00)
- `web/dashboard/views/status.js` (référence : la vue v4 actuelle qui utilise déjà `apiPost`)

### Étape 2 — Identifier les appels API

Cherche tous les `window.pywebview.api.X(...)` dans `home.js` :

```bash
grep -n "window.pywebview.api" web/views/home.js
```

Pour chaque appel, note :
- Méthode appelée
- Arguments (positional)
- Comment ils sont consommés

### Étape 3 — Convertir IIFE → ES module

Remplacer le pattern :

```javascript
(function() {
  function refreshHomeOverview() { ... }
  // ...
  window.refreshHomeOverview = refreshHomeOverview;
})();
```

Par :

```javascript
import { apiPost, escapeHtml, $, $$, el, renderSkeleton, renderError, initView } from "./_v5_helpers.js";

let _state = { /* état module-level */ };
let _container = null;

/** Point d'entrée standard pour les vues v5 portées. */
export async function initHome(container, opts = {}) {
  _container = container;
  await initView(container, _loadHomeData, _renderHome, { skeletonType: "default" });
}

async function _loadHomeData() {
  // Promise.allSettled pour résilience (V2-04 préservé)
  const results = await Promise.allSettled([
    apiPost("get_global_stats"),
    apiPost("get_settings"),
    apiPost("get_probe_tools_status"),
  ]);
  return {
    stats: results[0].status === "fulfilled" ? results[0].value.data : null,
    settings: results[1].status === "fulfilled" ? results[1].value.data : {},
    probe: results[2].status === "fulfilled" ? results[2].value.data : null,
  };
}

function _renderHome(container, data) {
  container.innerHTML = `
    ${_renderProbeBanner(data.probe)}
    ${_renderIntegrationsCTA(data.settings)}
    ${_renderHomeWidgets(data.stats)}
    ${/* ... reste du HTML */}
  `;
  _bindEvents(container, data);
}

// ... (toutes les fonctions internes converties pour utiliser apiPost)
```

### Étape 4 — Migrer chaque appel API

Pour chaque `window.pywebview.api.X(...)` :

```javascript
// AVANT
const stats = await window.pywebview.api.get_global_stats();
if (stats) { renderStats(stats); }

// APRÈS
const res = await apiPost("get_global_stats");
if (res.data) { renderStats(res.data); }
```

⚠ **Attention pour les méthodes avec plusieurs args positionnels** :

```javascript
// AVANT
await window.pywebview.api.start_plan(settings, root);

// APRÈS — backend Python fait `def start_plan(self, settings, root, ...)`
// donc REST splatte le dict en kwargs :
await apiPost("start_plan", { settings, root });
```

Si un appel a un argument list (ex. `[a, b, c]`), passer comme `{name: [a,b,c]}`. Vérifier la signature backend dans `cinesort/ui/api/cinesort_api.py`.

### Étape 5 — Préserver V1-V4 features

Vérifie que les features suivantes (portées par V5A-04) restent intactes :

- ✅ V2-04 Promise.allSettled
- ✅ V2-08 Skeleton (utiliser `renderSkeleton` du helper)
- ✅ V1-07 Banner outils manquants (`get_probe_tools_status` + `auto_install_probe_tools`)
- ✅ V1-06 CTA Configurer Jellyfin/Plex/Radarr
- ✅ V3-05 Demo wizard premier-run

### Étape 6 — Demo wizard cross-folder import

Le demo wizard est dans `web/dashboard/views/demo-wizard.js`. Pour l'importer depuis `web/views/home.js` :

```javascript
import { showDemoWizardIfFirstRun, renderDemoBanner } from "../dashboard/views/demo-wizard.js";
```

⚠ **À vérifier** : que le serveur HTTP local sert bien les 2 dossiers `/web/views/` et `/web/dashboard/views/`. Si le serveur ne sert que `/dashboard/`, créer un shim ou copier le module.

### Étape 7 — Tests structurels

Crée `tests/test_home_v5_ported.py` :

```python
"""V5bis-01 — Vérifie home.js porté vers ES module."""
from __future__ import annotations
import re
import unittest
from pathlib import Path


class HomeV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/home.js").read_text(encoding="utf-8")

    def test_es_module_exports_init(self):
        self.assertIn("export async function initHome", self.src)

    def test_no_more_iife(self):
        # Pas de "(function() { ... })();" en début
        self.assertNotRegex(self.src.lstrip()[:50], r"\(function\s*\(\s*\)\s*\{")

    def test_imports_helpers(self):
        self.assertIn('from "./_v5_helpers.js"', self.src)
        self.assertIn("apiPost", self.src)

    def test_no_more_pywebview_api(self):
        # Plus aucun appel direct à window.pywebview.api
        self.assertNotIn("window.pywebview.api", self.src)

    def test_v1_07_banner_preserved(self):
        self.assertIn("get_probe_tools_status", self.src)
        self.assertIn("auto_install_probe_tools", self.src)

    def test_v1_06_integrations_cta_preserved(self):
        self.assertIn("focus=jellyfin", self.src)
        self.assertIn("Configurer", self.src)

    def test_v3_05_demo_wizard_preserved(self):
        self.assertIn("showDemoWizardIfFirstRun", self.src)

    def test_v2_04_allsettled_preserved(self):
        self.assertIn("Promise.allSettled", self.src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 8 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_home_v5_ported -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/home.js 2>&1 | tail -2
```

### Étape 9 — Commits

- `refactor(home-v5): convert IIFE to ES module + REST apiPost (V5bis-01)`
- `refactor(home-v5): migrate window.pywebview.api calls → apiPost`
- `test(home-v5): structural tests confirm port + V1-V4 features preserved`

---

## LIVRABLES

- `home.js` converti IIFE → ES module exportant `initHome(container, opts)`
- 0 appel `window.pywebview.api` restant
- V1-V4 features préservées (V2-04, V2-08, V1-07, V1-06, V3-05)
- Test structurel
- 3 commits sur `feat/v5bis-port-home`

---

## ⚠️ Si bloqué

- Backend method signature inconnue → grep dans `cinesort/ui/api/cinesort_api.py`
- Cross-folder import problème → créer shim dans `web/views/_demo_wizard_shim.js` qui ré-exporte
- Doute sur préservation feature V1-V4 → comparer avant/après avec `git diff`
