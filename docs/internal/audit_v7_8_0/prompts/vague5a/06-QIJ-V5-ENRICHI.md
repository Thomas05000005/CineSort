# V5A-06 — QIJ v5 enrichi (V1-05 + V3-03 + V2-08)

**Branche** : `feat/v5a-qij-port`
**Worktree** : `.claude/worktrees/feat-v5a-qij-port/`
**Effort** : 4-6h
**Mode** : 🟢 Parallélisable
**Fichiers concernés** :
- `web/views/qij-v5.js` (enrichissement)
- `tests/test_qij_v5_features.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5a-qij-port .claude/worktrees/feat-v5a-qij-port audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5a-qij-port

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `web/views/qij-v5.js` + son test.

RÈGLE V5 : préserver la consolidation Quality+Integrations+Journal.

---

## CONTEXTE

`qij-v5.js` (475L) est la vue v5 qui consolide Quality+Integrations+Journal en une seule page (Vague 7 v7.6.0). Il manque 3 features :

1. **V1-05** : EmptyState CTA "Lancer un scan" sur la section Quality si aucun scan
2. **V3-03** : Tooltips ⓘ glossaire métier (LPIPS, perceptual, banding, etc.)
3. **V2-08** : Skeleton loading states (déjà partiel — étendre)

---

## MISSION

### Étape 1 — Lire l'existant

- `web/views/qij-v5.js` (475L — fichier à enrichir)
- `web/dashboard/views/quality.js` lignes 56-66 (référence V1-05 EmptyState v4)
- `web/dashboard/components/glossary-tooltip.js` (composant V3-03)

### Étape 2 — V1-05 EmptyState Quality

Dans la section Quality de qij-v5, si `total_films == 0` ou pas de scan, afficher :

```javascript
import { buildEmptyState, bindEmptyStateCta } from "../dashboard/components/empty-state.js";
// (créer shim si import direct impossible)

function _renderQualityEmpty(container) {
  container.innerHTML = buildEmptyState({
    icon: "quality",
    title: "Aucune analyse qualité disponible",
    description: "Lance un scan + une analyse pour voir le score perceptuel des films.",
    cta: { label: "Lancer un scan", action: "scan" },
  });
  bindEmptyStateCta(container, () => {
    window.location.hash = "#/processing?step=scan";
  });
}
```

### Étape 3 — V3-03 Glossaire ⓘ

Importer et décorer les termes techniques dans qij-v5 :

```javascript
import { glossaryTooltip } from "../dashboard/components/glossary-tooltip.js";

// Termes typiques à décorer dans cette vue :
// - "Score perceptuel" → glossaryTooltip("Score perceptuel")
// - "LPIPS" → glossaryTooltip("LPIPS")
// - "Banding" → glossaryTooltip("Banding")
// - "Tier Premium/Bon/Moyen/Mauvais" → glossaryTooltip("Tier")
// - "Faux 4K" → glossaryTooltip("Faux 4K")
// - "Re-encode dégradé" → glossaryTooltip("Re-encode dégradé")
// - "Upscale suspect" → glossaryTooltip("Upscale suspect")

// Dans les en-têtes de section, headers de tableau, légendes :
const titleHtml = `<h2>${glossaryTooltip("Score perceptuel", "Qualité perceptuelle")}</h2>`;
```

Décorer au moins 5 occurrences de termes techniques visibles à l'écran.

### Étape 4 — V2-08 Skeleton states

Étendre les skeletons existants (l'agent audit a noté que `qij-v5.js:81` utilise déjà Promise.allSettled mais pas de skeleton complet).

```javascript
function _renderSkeleton(container) {
  container.innerHTML = `
    <div class="v5-qij-skeleton">
      <div class="v5-skeleton-section">
        <div class="v5-skeleton-title"></div>
        <div class="v5-skeleton-grid">
          ${"<div class='v5-skeleton-card'></div>".repeat(6)}
        </div>
      </div>
      <div class="v5-skeleton-section">
        <div class="v5-skeleton-table">
          ${"<div class='v5-skeleton-row'></div>".repeat(8)}
        </div>
      </div>
    </div>
  `;
}

// Au boot :
export function initQij(container) {
  _renderSkeleton(container);
  _loadAndRender(container).catch(...);
}
```

### Étape 5 — Tests structurels

Crée `tests/test_qij_v5_features.py` :

```python
"""V5A-06 — Vérifie qij-v5 enrichi avec V1-05 + V3-03 + V2-08."""
from __future__ import annotations
import unittest
from pathlib import Path


class QijV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/qij-v5.js").read_text(encoding="utf-8")

    def test_v1_05_empty_state_quality(self):
        self.assertIn("buildEmptyState", self.src)
        self.assertIn("Lancer un scan", self.src)
        self.assertIn("_renderQualityEmpty", self.src)

    def test_v3_03_glossary_tooltips(self):
        self.assertIn("glossaryTooltip", self.src)
        # Au moins 5 occurrences
        self.assertGreaterEqual(self.src.count("glossaryTooltip("), 5)

    def test_v2_08_skeleton_complete(self):
        self.assertIn("_renderSkeleton", self.src)
        self.assertIn("v5-qij-skeleton", self.src)
        # Skeleton appelé au boot
        self.assertRegex(self.src, r"_renderSkeleton\(.*?\)")


if __name__ == "__main__":
    unittest.main()
```

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_qij_v5_features -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/views/qij-v5.js 2>&1 | tail -2
```

### Étape 7 — Commits

- `feat(qij-v5): V1-05 EmptyState CTA on quality section`
- `feat(qij-v5): V3-03 glossary tooltips on technical terms`
- `feat(qij-v5): V2-08 skeleton complete state on init`
- `test(qij-v5): structural tests for V5A-06`

---

## LIVRABLES

- `qij-v5.js` enrichi avec V1-05 + V3-03 + V2-08
- Test structurel
- Style v5 préservé (consolidation Q+I+J intacte)
- 4 commits sur `feat/v5a-qij-port`
