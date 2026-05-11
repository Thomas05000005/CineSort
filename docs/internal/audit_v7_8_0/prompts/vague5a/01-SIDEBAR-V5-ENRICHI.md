# V5A-01 — Sidebar v5 enrichi (port V1-V4)

**Branche** : `feat/v5a-sidebar-port`
**Worktree** : `.claude/worktrees/feat-v5a-sidebar-port/`
**Effort** : 3-4h
**Mode** : 🟢 Parallélisable (un seul fichier v5 + tests)
**Fichiers concernés** :
- `web/dashboard/components/sidebar-v5.js` (enrichissement)
- `tests/test_sidebar_v5_features.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5a-sidebar-port .claude/worktrees/feat-v5a-sidebar-port audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5a-sidebar-port

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `sidebar-v5.js` + son test. Pas d'autre fichier.

RÈGLE V5 : conserve le style v5 (`v5-*` prefix, structure ARIA propre, raccourcis visibles).

RÈGLE NO-ACTIVATION : tu n'actives PAS v5 dans `app.js`. Le fichier est enrichi, mais reste dormant.

---

## CONTEXTE

`sidebar-v5.js` (5 887 octets, créé v7.6.0 le 23 avril) propose une sidebar moderne avec 7 NAV_ITEMS, raccourcis Alt+1-7 visibles, collapse persistant. Mais 5 features ajoutées en V1/V3/V4 sur la sidebar v4 actuelle ne sont pas dedans :

1. **V3-04** : badges sidebar dynamiques (compteurs Validation/Application/Qualité avec polling 30s)
2. **V3-01** : intégrations toujours visibles avec état "désactivé" si pas activé
3. **V1-12** : bouton "À propos" dans le footer
4. **V1-13** : badge "•" sur item Paramètres si MAJ disponible
5. **V1-14** : entrée "Aide" dans la nav (nav v5 a 7 items, pas d'Aide)
6. **V4-09** : `aria-current="page"` au lieu de `aria-selected` (sidebar-v5 utilise encore aria-selected)

---

## MISSION

### Étape 1 — Lire l'existant

- `web/dashboard/components/sidebar-v5.js` (l'actuel à enrichir)
- `web/dashboard/index.html` lignes 60-135 (sidebar v4 actuelle pour référence)
- `web/dashboard/app.js` lignes 188-213 (logique `_loadSidebarCounters`)
- `web/dashboard/app.js` lignes 280-326 (logique `_markNavIntegrationState`)
- `web/dashboard/app.js` lignes 349-369 (logique `_checkUpdateBadge`)

### Étape 2 — Étendre NAV_ITEMS avec entrée Aide (V1-14)

Dans `sidebar-v5.js`, ajouter à la liste `NAV_ITEMS` (en respectant le format existant) :

```javascript
{ id: "help", label: "Aide", shortcut: "Alt+8",
  svg: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>' },
```

### Étape 3 — Migrer aria-selected → aria-current (V4-09)

Dans `_buildItemHtml`, remplacer :
```javascript
role="tab" aria-selected="${active ? "true" : "false"}"
```
par :
```javascript
${active ? 'aria-current="page"' : ''}
```

Et retirer `role="tab"` (ce n'est pas un tab dans listbox/tablist au sens ARIA, c'est de la navigation).
Au niveau parent (`.v5-sidebar-nav`), retirer `role="tablist"`. Garder `role="navigation"` sur l'aside.

### Étape 4 — Ajouter badges sidebar (V3-04)

Dans `_buildItemHtml`, ajouter conditionnellement un badge pour les items qui ont un `badgeKey` :

Définir dans NAV_ITEMS pour les 3 concernés :
```javascript
{ id: "library", ..., badgeKey: "validation" },  // ou bien l'id correspondant
{ id: "processing", ..., badgeKey: "application" },
{ id: "quality", ..., badgeKey: "quality" },
```

Adapter selon ton mapping d'items v5 (cf NAV_ITEMS existants).

Dans `_buildItemHtml`, après le label :
```javascript
${item.badgeKey ? `<span class="v5-sidebar-badge" data-badge-key="${escapeHtml(item.badgeKey)}" role="status" aria-live="polite" aria-label="Compteur ${escapeHtml(item.label)}"></span>` : ''}
```

Exporter une fonction utilitaire :
```javascript
/** V3-04 — Met à jour les badges sidebar avec un mapping {key: count}. */
export function updateSidebarBadges(counters) {
  document.querySelectorAll(".v5-sidebar-badge[data-badge-key]").forEach((el) => {
    const key = el.dataset.badgeKey;
    const v = Number((counters || {})[key] || 0);
    el.textContent = v > 0 ? String(v) : "";
    el.classList.toggle("v5-sidebar-badge--active", v > 0);
  });
}
```

NE PAS câbler le polling ici — c'est `app.js` qui le fera lors de l'activation Phase B.

### Étape 5 — Sidebar intégrations (V3-01)

**Note importante** : sidebar-v5 a un seul item agrégé "Intégrations" (pas Jellyfin/Plex/Radarr séparés). Décision :

**Option recommandée** : éclater l'item `integrations` en 3 sous-items conditionnels Jellyfin/Plex/Radarr, alignés sur la sidebar v4. Ça permet de garder V3-01 (état désactivé visible).

Modifier NAV_ITEMS : remplacer le seul `integrations` par 3 entrées spécifiques + 1 entrée parent éventuelle. Adapter l'icône (utilise les SVG actuels d'index.html lignes 102, 106, 110).

Ajouter une fonction utilitaire :
```javascript
/** V3-01 — Marque un item intégration comme désactivé (visuel grisé + redirige settings au clic). */
export function markIntegrationState(itemId, enabled, label) {
  const el = document.querySelector(`.v5-sidebar-item[data-route="${itemId}"]`);
  if (!el) return;
  el.classList.toggle("v5-sidebar-item--disabled", !enabled);
  if (!enabled) {
    el.setAttribute("title", `${label} non configuré — clique pour l'activer dans Paramètres`);
    el.setAttribute("aria-disabled", "true");
  } else {
    el.removeAttribute("aria-disabled");
  }
}
```

CSS attendu (à ajouter via doc, pas via fichier dans cette mission) : `.v5-sidebar-item--disabled { opacity: 0.5; filter: grayscale(0.7); }`. Mention dans le commit message ou ajout dans `web/shared/components.css` si simple.

### Étape 6 — Bouton "À propos" footer (V1-12)

Dans `_buildHtml`, modifier `.v5-sidebar-footer` pour inclure :

```javascript
<div class="v5-sidebar-footer">
  <button type="button" class="v5-btn v5-btn--icon v5-btn--ghost" data-v5-about-btn
          aria-label="À propos de CineSort">
    ${_svgIcon('<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>')}
  </button>
  <button type="button" class="v5-sidebar-collapse-btn" data-v5-collapse-btn
          aria-label="${collapsed ? "Déployer" : "Réduire"} la sidebar">
    ${_svgIcon(collapsed ? '<polyline points="9 18 15 12 9 6"/>' : '<polyline points="15 18 9 12 15 6"/>')}
  </button>
</div>
```

Dans `_bindEvents`, ajouter listener sur `[data-v5-about-btn]` qui appelle `opts.onAboutClick`.

### Étape 7 — Badge update item Paramètres (V1-13)

Exporter une fonction :

```javascript
/** V1-13 — Affiche un badge "•" sur l'item Paramètres si MAJ dispo. */
export function setUpdateBadge(itemId, available, latestVersion) {
  const el = document.querySelector(`.v5-sidebar-item[data-route="${itemId}"]`);
  if (!el) return;
  let badge = el.querySelector(".v5-sidebar-update-badge");
  if (available) {
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "v5-sidebar-update-badge";
      badge.textContent = "•";
      el.appendChild(badge);
    }
    badge.title = `Nouvelle version : ${latestVersion}`;
  } else {
    if (badge) badge.remove();
  }
}
```

### Étape 8 — Tests structurels

Crée `tests/test_sidebar_v5_features.py` :

```python
"""V5A-01 — Vérifie que sidebar-v5 contient les 5 features V1-V4 portées."""
from __future__ import annotations
import unittest
from pathlib import Path


class SidebarV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/dashboard/components/sidebar-v5.js").read_text(encoding="utf-8")

    def test_v3_04_badge_data_key(self):
        self.assertIn("data-badge-key", self.src)
        self.assertIn("v5-sidebar-badge", self.src)
        self.assertIn("updateSidebarBadges", self.src)

    def test_v3_01_integration_disabled(self):
        self.assertIn("markIntegrationState", self.src)
        self.assertIn("v5-sidebar-item--disabled", self.src)

    def test_v1_12_about_button(self):
        self.assertIn("data-v5-about-btn", self.src)
        self.assertIn("onAboutClick", self.src)

    def test_v1_13_update_badge(self):
        self.assertIn("setUpdateBadge", self.src)
        self.assertIn("v5-sidebar-update-badge", self.src)

    def test_v1_14_help_entry(self):
        self.assertIn('"help"', self.src)
        # La nav doit avoir au moins 8 items (7 originaux + Aide)
        nav_items_count = self.src.count('shortcut: "Alt+')
        self.assertGreaterEqual(nav_items_count, 8)

    def test_v4_09_aria_current(self):
        self.assertIn('aria-current="page"', self.src)
        # Plus de aria-selected en mode navigation
        self.assertNotIn('aria-selected="true"', self.src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 9 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_sidebar_v5_features -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/dashboard/components/sidebar-v5.js 2>&1 | tail -2
```

### Étape 10 — Commits

- `feat(sidebar-v5): port V3-04 badges + V3-01 integrations disabled state`
- `feat(sidebar-v5): port V1-12 About button + V1-13 update badge + V1-14 Help entry`
- `fix(sidebar-v5): V4-09 aria-current="page" instead of aria-selected for navigation`
- `test(sidebar-v5): structural tests for 5 V1-V4 features ported`

---

## LIVRABLES

- `sidebar-v5.js` enrichi avec 5 features V1-V4 + V4-09 a11y fix
- 4 fonctions exportées : `updateSidebarBadges()`, `markIntegrationState()`, `setUpdateBadge()`, options `onAboutClick`
- NAV_ITEMS étendu (Aide + intégrations éclatées)
- Test structurel
- 0 régression suite tests
- Style v5 préservé (préfixe `v5-*`, structure ARIA propre)
- 4 commits sur `feat/v5a-sidebar-port`
