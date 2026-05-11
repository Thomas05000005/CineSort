# V2-04 — Migration Promise.all → Promise.allSettled (9 vues)

**Branche** : `refactor/promise-allsettled`
**Worktree** : `.claude/worktrees/refactor-promise-allsettled/`
**Effort** : 1 jour
**Priorité** : 🟠 MEDIUM (audit ID-ROB-002)
**Fichiers concernés** :
- `web/views/execution.js`
- `web/views/home.js`
- `web/views/qij-v5.js`
- `web/dashboard/views/jellyfin.js`
- `web/dashboard/views/library/lib-validation.js`
- `web/dashboard/views/library/library.js`
- `web/dashboard/views/logs.js`
- `web/dashboard/views/quality.js`
- `web/dashboard/views/review.js`

⚠ Coordination avec V2-03 : V2-03 touche aussi review.js (draft auto) — sections différentes.

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b refactor/promise-allsettled .claude/worktrees/refactor-promise-allsettled audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/refactor-promise-allsettled

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT les 9 fichiers JS listés.

---

## CONTEXTE

L'audit Lot 2 a montré : 9 vues utilisent encore `Promise.all` (au lieu de
`Promise.allSettled`).

Si UN endpoint plante, `Promise.all` rejette → **TOUTE la vue plante**.
Pattern correct = `Promise.allSettled` : chaque endpoint isolé, vue affiche ce qui a
fonctionné même si certains échouent.

Pattern référence déjà appliqué dans `web/dashboard/views/status.js` (V-2 audit
précédent).

---

## MISSION

### Étape 1 — Lire le pattern référence

Lis `web/dashboard/views/status.js` :
```javascript
const results = await Promise.allSettled([
  apiPost("get_health"),
  apiPost("get_global_stats"),
  apiPost("get_settings"),
  apiPost("get_probe_tools_status"),
]);
const _val = (r) => (r && r.status === "fulfilled" && r.value ? r.value.data || {} : {});
const [healthRes, statsRes, settingsRes, probeRes] = results.map(_val);
```

Note : si tu as un skeleton/loading state pendant le load, conserve-le.

### Étape 2 — Pour CHACUN des 9 fichiers

#### a. Localiser le `Promise.all`

Grep dans le fichier pour trouver l'occurrence :
```bash
grep -n "Promise.all" web/views/execution.js
```

#### b. Identifier la structure actuelle

Probablement :
```javascript
const [a, b] = await Promise.all([apiCall(...), apiCall(...)]);
// ... utilise a, b directement
```

Si try/catch global : à conserver ou supprimer (decision case-by-case).

#### c. Migrer vers Promise.allSettled

```javascript
const results = await Promise.allSettled([apiCall(...), apiCall(...)]);
const _val = (r) => (r && r.status === "fulfilled" && r.value ? r.value.data || r.value : null);
const [a, b] = results.map(_val);

// Gérer les nulls : afficher placeholder ou skeleton si endpoint HS
if (!a) console.warn("[<vue>] endpoint A failed");
if (!b) console.warn("[<vue>] endpoint B failed");
```

⚠ Adapter `_val` selon la signature de chaque fichier (apiCall vs apiPost retournent
différemment dans certaines vues).

#### d. Vérifier le rendu UI

Si la vue affiche maintenant `null` pour un endpoint HS, ajouter un fallback gracieux
("Données indisponibles" ou skeleton qui reste, ou message d'erreur ciblé).

### Étape 3 — Tests

Pas de tests unitaires JS automatiques. Vérifications :
- `node --check` sur chacun des 9 fichiers
- Tests Python qui vérifient la structure (test_polish_v5 ou similaires)

```bash
for f in web/views/execution.js web/views/home.js web/views/qij-v5.js \
         web/dashboard/views/jellyfin.js web/dashboard/views/library/lib-validation.js \
         web/dashboard/views/library/library.js web/dashboard/views/logs.js \
         web/dashboard/views/quality.js web/dashboard/views/review.js; do
  echo "=== $f ==="
  node --check "$f"
  grep -c "Promise.all\b" "$f"  # doit être 0
  grep -c "Promise.allSettled" "$f"  # doit être ≥1
done
```

Crée éventuellement `tests/test_promise_allsettled.py` :

```python
"""V2-04 — vérifie qu'aucune vue ne reste sur Promise.all (sauf docs)"""
from pathlib import Path
import unittest


class PromiseAllSettledTests(unittest.TestCase):
    EXPECTED_MIGRATED = [
        "web/views/execution.js",
        "web/views/home.js",
        "web/views/qij-v5.js",
        "web/dashboard/views/jellyfin.js",
        "web/dashboard/views/library/lib-validation.js",
        "web/dashboard/views/library/library.js",
        "web/dashboard/views/logs.js",
        "web/dashboard/views/quality.js",
        "web/dashboard/views/review.js",
    ]

    def test_no_promise_all_in_migrated_files(self):
        root = Path(__file__).resolve().parent.parent
        for rel in self.EXPECTED_MIGRATED:
            src = (root / rel).read_text(encoding="utf-8")
            # Promise.all (sans Settled) ne doit plus apparaître
            self.assertNotIn("Promise.all(", src, f"{rel} : encore Promise.all !")
            # Doit avoir au moins 1 Promise.allSettled
            self.assertIn("Promise.allSettled", src, f"{rel} : pas de Promise.allSettled !")
```

### Étape 4 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_promise_allsettled -v 2>&1 | tail -5
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 5 — Commits

1-3 commits :
- `refactor(ui): migrate Promise.all → Promise.allSettled in 9 views (audit ID-ROB-002)`
- `test(ui): add structural test for Promise.allSettled migration`

(Possible de splitter desktop / dashboard si tu préfères 2 commits.)

---

## LIVRABLES

Récap :
- 9 fichiers migrés
- Test structurel ajouté
- 0 régression
- 1-2 commits sur `refactor/promise-allsettled`
