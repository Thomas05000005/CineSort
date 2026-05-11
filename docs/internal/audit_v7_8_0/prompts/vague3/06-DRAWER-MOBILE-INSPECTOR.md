# V3-06 — Drawer mobile inspector Validation

**Branche** : `feat/drawer-mobile-inspector`
**Worktree** : `.claude/worktrees/feat-drawer-mobile-inspector/`
**Effort** : 4-6h
**Priorité** : 🟢 NICE-TO-HAVE (UX mobile/tablette dashboard distant)
**Fichiers concernés** :
- `web/dashboard/views/review.js` (vue Validation distante)
- `web/dashboard/styles.css` (style drawer mobile)
- `tests/test_drawer_mobile.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/drawer-mobile-inspector .claude/worktrees/feat-drawer-mobile-inspector audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-drawer-mobile-inspector

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT la vue Validation dashboard (`review.js`)
+ son CSS responsive. Pas la logique métier.

---

## CONTEXTE

L'utilisateur teste CineSort dashboard distant depuis son téléphone (LAN). La vue
Validation a un panneau "Inspecteur" à droite (détails film, candidats TMDb, warnings)
qui est inutilisable sur mobile (déborde / s'affiche en dessous mal).

**Solution** : sur viewport `< 768px`, transformer le panneau inspecteur en **drawer
slide-in** depuis la droite, déclenché par un bouton "Inspecter" sur chaque ligne. Sur
desktop, comportement inchangé.

---

## MISSION

### Étape 1 — Lire les modules

- `web/dashboard/views/review.js` (chercher la section inspector / detail panel)
- `web/dashboard/styles.css` (chercher media queries `768px`)
- Valider que le panneau existe ET pose problème en < 768px (taille / scroll)

### Étape 2 — Ajouter un bouton "Inspecter" par ligne en mobile

Dans le rendu de chaque ligne du tableau Validation, ajouter (côté actions ou colonne
dédiée) :

```javascript
html += `
  <button class="btn btn--small btn-inspect-mobile" data-row-id="${row.id}" aria-label="Inspecter ce film">
    Inspecter
  </button>
`;
```

Ce bouton sera visible uniquement en mobile via CSS.

### Étape 3 — Drawer container

Dans le markup principal de la vue, ajouter un drawer (caché par défaut) :

```javascript
html += `
  <aside class="inspector-drawer" id="inspectorDrawer" aria-hidden="true" role="dialog" aria-label="Inspecteur film">
    <div class="inspector-drawer__header">
      <h3>Inspecteur</h3>
      <button class="btn btn--icon" id="btnCloseDrawer" aria-label="Fermer">×</button>
    </div>
    <div class="inspector-drawer__body" id="inspectorDrawerBody"></div>
  </aside>
  <div class="inspector-drawer__overlay" id="inspectorDrawerOverlay" hidden></div>
`;
```

### Étape 4 — Logique ouverture/fermeture

```javascript
function _openInspectorDrawer(rowId) {
  const drawer = document.getElementById("inspectorDrawer");
  const overlay = document.getElementById("inspectorDrawerOverlay");
  const body = document.getElementById("inspectorDrawerBody");
  // Réutiliser la logique render existante du panneau inspector desktop
  body.innerHTML = _renderInspectorContent(rowId); // fonction existante
  drawer.classList.add("inspector-drawer--open");
  drawer.setAttribute("aria-hidden", "false");
  overlay.hidden = false;
  // Focus trap : focus sur le bouton fermer
  document.getElementById("btnCloseDrawer").focus();
}

function _closeInspectorDrawer() {
  const drawer = document.getElementById("inspectorDrawer");
  const overlay = document.getElementById("inspectorDrawerOverlay");
  drawer.classList.remove("inspector-drawer--open");
  drawer.setAttribute("aria-hidden", "true");
  overlay.hidden = true;
}

// Wire-up event listeners
document.addEventListener("click", (ev) => {
  const btn = ev.target.closest(".btn-inspect-mobile");
  if (btn) { _openInspectorDrawer(btn.dataset.rowId); return; }
  if (ev.target.id === "btnCloseDrawer" || ev.target.id === "inspectorDrawerOverlay") {
    _closeInspectorDrawer();
  }
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") _closeInspectorDrawer();
});
```

### Étape 5 — Style CSS responsive

Dans `web/dashboard/styles.css` :

```css
/* V3-06 — Drawer mobile inspector */
.btn-inspect-mobile { display: none; }

@media (max-width: 768px) {
  .btn-inspect-mobile { display: inline-flex; }

  /* Cacher le panneau inspector desktop quand mobile (drawer prend le relais) */
  .inspector-panel-desktop { display: none; }

  .inspector-drawer {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(420px, 92vw);
    background: var(--surface-elevated);
    border-left: 1px solid var(--accent-border);
    transform: translateX(100%);
    transition: transform 0.25s ease-out;
    z-index: 9999;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }
  .inspector-drawer--open { transform: translateX(0); }

  .inspector-drawer__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 1.25rem;
    border-bottom: 1px solid var(--accent-border);
  }
  .inspector-drawer__body {
    padding: 1rem 1.25rem;
    flex: 1;
    overflow-y: auto;
  }
  .inspector-drawer__overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.5);
    z-index: 9998;
  }
}

@media (prefers-reduced-motion: reduce) {
  .inspector-drawer { transition: none; }
}
```

### Étape 6 — Tests

```python
"""V3-06 — Drawer mobile inspector validation."""
from __future__ import annotations
import unittest
from pathlib import Path


class DrawerMobileTests(unittest.TestCase):
    def setUp(self):
        self.review_js = Path("web/dashboard/views/review.js").read_text(encoding="utf-8")
        self.css = Path("web/dashboard/styles.css").read_text(encoding="utf-8")

    def test_drawer_markup_present(self):
        self.assertIn("inspector-drawer", self.review_js)
        self.assertIn("inspectorDrawer", self.review_js)
        self.assertIn("aria-hidden", self.review_js)
        self.assertIn('role="dialog"', self.review_js)

    def test_inspect_button_present(self):
        self.assertIn("btn-inspect-mobile", self.review_js)

    def test_open_close_logic(self):
        self.assertIn("_openInspectorDrawer", self.review_js)
        self.assertIn("_closeInspectorDrawer", self.review_js)

    def test_escape_handler(self):
        self.assertIn("Escape", self.review_js)

    def test_css_responsive(self):
        self.assertIn(".inspector-drawer", self.css)
        self.assertIn("max-width: 768px", self.css)
        self.assertIn("translateX", self.css)

    def test_reduced_motion_respected(self):
        self.assertIn("prefers-reduced-motion", self.css)


if __name__ == "__main__":
    unittest.main()
```

### Étape 7 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_drawer_mobile -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 8 — Commits

- `feat(dashboard): mobile drawer inspector for validation view (V3-06)`
- `style(dashboard): responsive drawer + reduced motion support`
- `test(dashboard): drawer mobile structural tests`

---

## LIVRABLES

Récap :
- Drawer slide-in droite sur viewport < 768px
- Bouton "Inspecter" par ligne en mobile
- Overlay + Escape close
- A11y : role=dialog, aria-hidden, focus trap
- Reduced motion respecté
- 0 régression
- 3 commits sur `feat/drawer-mobile-inspector`
