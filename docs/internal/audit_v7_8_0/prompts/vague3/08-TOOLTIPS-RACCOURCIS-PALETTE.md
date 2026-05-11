# V3-08 — Tooltips raccourcis clavier + palette Cmd+K

**Branche** : `feat/keyboard-shortcuts-tooltips`
**Worktree** : `.claude/worktrees/feat-keyboard-shortcuts-tooltips/`
**Effort** : 4-6h
**Priorité** : 🟢 NICE-TO-HAVE (UX power users)
**Fichiers concernés** :
- `web/dashboard/components/shortcut-tooltip.js` (nouveau)
- `web/dashboard/views/help.js` (vue Aide enrichie)
- `web/dashboard/styles.css` (style tooltip + palette)
- `tests/test_shortcuts_discoverability.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/keyboard-shortcuts-tooltips .claude/worktrees/feat-keyboard-shortcuts-tooltips audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-keyboard-shortcuts-tooltips

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT découvrabilité raccourcis clavier
(tooltips sur boutons + section dédiée vue Aide). Pas de modif des dispatchers
existants.

---

## CONTEXTE

CineSort a beaucoup de raccourcis clavier (Alt+1-7 navigation, Ctrl+K palette, ?
modal, Esc close, etc.) mais aucune indication visuelle dans l'UI. Les power users les
utilisent, les autres les découvrent jamais.

**Solution** :
1. Tooltip "kbd hint" sur les boutons principaux : `<kbd>Ctrl+K</kbd>` à côté du label
2. Vue Aide enrichie avec une section "Raccourcis clavier" exhaustive (tableau)
3. Indicateur "?" en bas à droite : "Astuce : appuie sur ? pour voir tous les
   raccourcis"

---

## MISSION

### Étape 1 — Inventaire des raccourcis existants

Cherche dans le code :

```bash
grep -rn "altKey\|ctrlKey\|metaKey\|key ===" web/dashboard/ web/views/ web/core/
grep -rn "addEventListener.*keydown" web/
```

Liste exhaustive attendue (à confirmer dans le code) :
- **Navigation** : Alt+1 Accueil, Alt+2 Bibliothèque, Alt+3 Validation, Alt+4 Application, Alt+5 Qualité, Alt+6 Journaux, Alt+7 Paramètres, Alt+8 Aide
- **Actions globales** : Ctrl+K palette, Ctrl+S sauvegarde, F5 refresh, ? aide raccourcis, Esc close modal/drawer
- **Validation** : flèches/jk navigation, Espace/a approuver, r rejeter, i inspecteur, Ctrl+A tout approuver

### Étape 2 — Composant tooltip kbd

Crée `web/dashboard/components/shortcut-tooltip.js` :

```javascript
// V3-08 — Tooltip raccourci clavier (kbd hint)
import { escapeHtml } from "../core/dom.js";

/**
 * Génère un span "kbd hint" à côté d'un libellé bouton.
 * @param {string} keys - Combinaison ex. "Ctrl+K" ou "Alt+3"
 * @returns {string} HTML
 */
export function kbdHint(keys) {
  if (!keys) return "";
  const parts = keys.split("+").map(k => `<kbd>${escapeHtml(k)}</kbd>`).join("+");
  return `<span class="kbd-hint" aria-label="Raccourci ${escapeHtml(keys)}">${parts}</span>`;
}

/**
 * Décore un bouton existant avec son raccourci clavier.
 * @param {HTMLElement|string} target - élément ou sélecteur
 * @param {string} keys
 */
export function decorateWithKbd(target, keys) {
  const el = typeof target === "string" ? document.querySelector(target) : target;
  if (!el || el.querySelector(".kbd-hint")) return;
  el.insertAdjacentHTML("beforeend", " " + kbdHint(keys));
}
```

### Étape 3 — Décorer les boutons principaux

Dans le boot dashboard ou dans les vues concernées :

```javascript
import { decorateWithKbd } from "./components/shortcut-tooltip.js";

// Au boot après que la sidebar est rendue
decorateWithKbd("[data-route='/home']", "Alt+1");
decorateWithKbd("[data-route='/library']", "Alt+2");
decorateWithKbd("[data-route='/validation']", "Alt+3");
// ... idem pour les autres
decorateWithKbd("#btnSearchPalette", "Ctrl+K");
decorateWithKbd("#btnSaveValidation", "Ctrl+S");
```

### Étape 4 — Vue Aide enrichie

Dans `web/dashboard/views/help.js` (créée en V1-14), ajouter une section dédiée :

```javascript
function _renderShortcutsSection() {
  const shortcuts = [
    { category: "Navigation", items: [
      { keys: "Alt+1", desc: "Accueil" },
      { keys: "Alt+2", desc: "Bibliothèque" },
      { keys: "Alt+3", desc: "Validation" },
      { keys: "Alt+4", desc: "Application" },
      { keys: "Alt+5", desc: "Qualité" },
      { keys: "Alt+6", desc: "Journaux" },
      { keys: "Alt+7", desc: "Paramètres" },
      { keys: "Alt+8", desc: "Aide" },
    ]},
    { category: "Actions globales", items: [
      { keys: "Ctrl+K", desc: "Ouvrir la palette de commandes (recherche)" },
      { keys: "Ctrl+S", desc: "Sauvegarder les décisions de validation" },
      { keys: "F5", desc: "Rafraîchir la vue active" },
      { keys: "?", desc: "Afficher cette aide" },
      { keys: "Esc", desc: "Fermer la modale ou le drawer actif" },
    ]},
    { category: "Validation (vue Validation active)", items: [
      { keys: "↑ ↓ / j k", desc: "Naviguer entre les films" },
      { keys: "Espace / a", desc: "Approuver le film sélectionné" },
      { keys: "r", desc: "Rejeter le film sélectionné" },
      { keys: "i", desc: "Ouvrir l'inspecteur" },
      { keys: "Ctrl+A", desc: "Tout approuver" },
    ]},
  ];

  let html = `<section class="help-shortcuts"><h2>Raccourcis clavier</h2>`;
  for (const cat of shortcuts) {
    html += `<h3>${escapeHtml(cat.category)}</h3><table class="shortcuts-table">`;
    html += `<thead><tr><th>Raccourci</th><th>Action</th></tr></thead><tbody>`;
    for (const it of cat.items) {
      const keys = it.keys.split(" / ").map(k => k.split("+").map(p => `<kbd>${escapeHtml(p)}</kbd>`).join("+")).join(" / ");
      html += `<tr><td>${keys}</td><td>${escapeHtml(it.desc)}</td></tr>`;
    }
    html += `</tbody></table>`;
  }
  html += `</section>`;
  return html;
}
```

Ajouter cette section dans la fonction qui rend la vue Aide.

### Étape 5 — Indicateur "?" coin bas-droit

Dans `web/dashboard/index.html` ou via JS au boot :

```html
<button class="help-fab" id="helpFab" aria-label="Aide raccourcis clavier" title="Appuie sur ? pour les raccourcis">
  <span aria-hidden="true">?</span>
</button>
```

```javascript
document.getElementById("helpFab")?.addEventListener("click", () => {
  window.location.hash = "#/help#shortcuts";
});
```

### Étape 6 — CSS

```css
/* V3-08 — Kbd hint + raccourcis */
.kbd-hint {
  display: inline-flex;
  gap: 2px;
  margin-left: 0.5rem;
  align-items: center;
}
kbd {
  display: inline-block;
  padding: 1px 6px;
  font: 600 0.75rem/1 monospace;
  background: var(--bg-elevated);
  border: 1px solid var(--accent-border);
  border-radius: 4px;
  color: var(--text-muted);
  white-space: nowrap;
}
.shortcuts-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 1.5rem;
}
.shortcuts-table th, .shortcuts-table td {
  padding: 0.5rem 0.75rem;
  text-align: left;
  border-bottom: 1px solid var(--accent-border);
}
.help-fab {
  position: fixed;
  bottom: 1.5rem;
  right: 1.5rem;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--bg-primary);
  border: none;
  font-size: 1.25rem;
  font-weight: 700;
  cursor: pointer;
  z-index: 100;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}
.help-fab:hover { transform: scale(1.05); }
@media (prefers-reduced-motion: reduce) {
  .help-fab:hover { transform: none; }
}
```

### Étape 7 — Tests

```python
"""V3-08 — Tooltips raccourcis + vue aide enrichie."""
from __future__ import annotations
import unittest
from pathlib import Path


class ShortcutsTests(unittest.TestCase):
    def setUp(self):
        self.tooltip = Path("web/dashboard/components/shortcut-tooltip.js").read_text(encoding="utf-8")
        self.help = Path("web/dashboard/views/help.js").read_text(encoding="utf-8") if Path("web/dashboard/views/help.js").exists() else ""
        self.css = Path("web/dashboard/styles.css").read_text(encoding="utf-8")

    def test_kbd_hint_function(self):
        self.assertIn("export function kbdHint", self.tooltip)
        self.assertIn("export function decorateWithKbd", self.tooltip)

    def test_help_has_shortcuts_section(self):
        if self.help:
            self.assertIn("Raccourcis clavier", self.help)
            # Au moins 10 raccourcis listés
            kbd_count = self.help.count("<kbd>")
            self.assertGreaterEqual(kbd_count, 20)  # 10 raccourcis × 2 touches min

    def test_css_kbd_styled(self):
        self.assertIn(".kbd-hint", self.css)
        self.assertIn("kbd ", self.css.replace("\n", " "))  # règle kbd globale

    def test_help_fab_present(self):
        self.assertIn("help-fab", self.css)


if __name__ == "__main__":
    unittest.main()
```

### Étape 8 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_shortcuts_discoverability -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 9 — Commits

- `feat(dashboard): kbd hint component + decorate buttons (V3-08)`
- `feat(dashboard): help view enriched with shortcuts table`
- `style(dashboard): kbd elements + help fab button`
- `test(dashboard): shortcuts discoverability structural tests`

---

## LIVRABLES

Récap :
- Composant `kbdHint(keys)` réutilisable
- Boutons principaux (sidebar + actions globales) décorés avec `<kbd>` indicator
- Vue Aide enrichie avec tableau exhaustif (>=15 raccourcis, 3 catégories)
- FAB "?" coin bas-droit pour ouvrir l'aide rapidement
- 0 régression
- 4 commits sur `feat/keyboard-shortcuts-tooltips`
