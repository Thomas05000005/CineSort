# V3-01 — Découvrabilité Intégrations (sidebar toujours visible)

**Branche** : `feat/sidebar-integrations-discovery`
**Worktree** : `.claude/worktrees/feat-sidebar-integrations-discovery/`
**Effort** : 2-3h
**Priorité** : 🟠 IMPORTANT (UX découvrabilité — 2000 users débutants en attente)
**Fichiers concernés** :
- `web/dashboard/app.js` (logique masquage)
- `web/dashboard/styles.css` (style "désactivé")
- `web/dashboard/index.html` (vérifier sidebar)
- `tests/test_sidebar_integrations_visible.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/sidebar-integrations-discovery .claude/worktrees/feat-sidebar-integrations-discovery audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-sidebar-integrations-discovery

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT le bloc "Intégrations" du dashboard
(sidebar + style désactivé). Pas d'autres vues, pas de logique métier.

---

## CONTEXTE

Audit V2-07 a révélé : le dashboard masque les onglets Jellyfin/Plex/Radarr de la
sidebar tant que `jellyfin_enabled` / `plex_enabled` / `radarr_enabled` sont `false`.

Code coupable (à modifier) : `web/dashboard/app.js` autour de la ligne 264 :
```javascript
setNavVisible(".nav-btn-jellyfin", !!s.jellyfin_enabled);
setNavVisible(".nav-btn-plex", !!s.plex_enabled);
setNavVisible(".nav-btn-radarr", !!s.radarr_enabled);
```

**Problème** : les 2000 users débutants ne savent pas que Jellyfin/Plex/Radarr existent
puisqu'ils ne voient même pas les onglets. Feature morte.

**Solution (option A choisie par l'utilisateur)** : toujours afficher les 3 onglets,
mais avec un état visuel "désactivé" + tooltip qui explique comment activer.

---

## MISSION

### Étape 1 — Lire les modules

- `web/dashboard/app.js` (chercher `setNavVisible` + le block intégrations)
- `web/dashboard/index.html` (vérifier sidebar lignes ~93-104, classes `nav-btn-jellyfin/plex/radarr`)
- `web/dashboard/styles.css` (chercher `.nav-btn` pour comprendre les états existants)

### Étape 2 — Modifier app.js

Remplace les 3 lignes `setNavVisible(...)` par :

```javascript
// V3-01 — Toujours afficher les onglets intégrations, marquer "désactivé" si pas configuré
_markNavIntegrationState(".nav-btn-jellyfin", !!s.jellyfin_enabled, "Jellyfin");
_markNavIntegrationState(".nav-btn-plex", !!s.plex_enabled, "Plex");
_markNavIntegrationState(".nav-btn-radarr", !!s.radarr_enabled, "Radarr");
```

Ajoute la fonction helper (en haut du fichier ou juste avant l'usage) :

```javascript
function _markNavIntegrationState(selector, enabled, label) {
  const el = document.querySelector(selector);
  if (!el) return;
  // Toujours visible (suppression du masquage)
  el.style.display = "";
  el.classList.toggle("nav-btn--disabled", !enabled);
  if (!enabled) {
    el.setAttribute("title", `${label} non configuré — clique pour l'activer dans Paramètres`);
    el.setAttribute("aria-disabled", "true");
  } else {
    el.removeAttribute("title");
    el.removeAttribute("aria-disabled");
  }
}
```

### Étape 3 — Comportement au clic sur onglet désactivé

Si l'utilisateur clique sur un onglet désactivé → rediriger vers la vue Paramètres
section Intégrations au lieu d'ouvrir une vue vide.

Cherche le routeur dans `web/dashboard/core/router.js` ou `app.js`. Intercepte le clic
sur `.nav-btn--disabled` :

```javascript
document.addEventListener("click", (ev) => {
  const btn = ev.target.closest(".nav-btn--disabled");
  if (!btn) return;
  ev.preventDefault();
  ev.stopPropagation();
  // Naviguer vers Paramètres section Intégrations
  window.location.hash = "#/settings?focus=integrations";
}, true);
```

### Étape 4 — Style CSS désactivé

Dans `web/dashboard/styles.css`, ajouter :

```css
/* V3-01 — Onglets intégrations désactivés */
.nav-btn--disabled {
  opacity: 0.5;
  filter: grayscale(0.7);
  cursor: pointer; /* clic = redirection Paramètres */
  position: relative;
}
.nav-btn--disabled::after {
  content: "🔌";
  font-size: 0.7rem;
  position: absolute;
  right: 0.5rem;
  top: 50%;
  transform: translateY(-50%);
  opacity: 0.7;
}
.nav-btn--disabled:hover {
  opacity: 0.7;
  filter: grayscale(0.4);
}
```

### Étape 5 — Tests

Crée `tests/test_sidebar_integrations_visible.py` :

```python
"""V3-01 — Vérifie que la logique sidebar n'utilise plus setNavVisible pour intégrations."""
from __future__ import annotations
import unittest
from pathlib import Path


class SidebarIntegrationsTests(unittest.TestCase):
    def setUp(self):
        self.app_js = Path("web/dashboard/app.js").read_text(encoding="utf-8")
        self.css = Path("web/dashboard/styles.css").read_text(encoding="utf-8")

    def test_no_setnavvisible_for_integrations(self):
        """Les 3 lignes setNavVisible(.nav-btn-jellyfin/plex/radarr) ont disparu."""
        self.assertNotIn('setNavVisible(".nav-btn-jellyfin"', self.app_js)
        self.assertNotIn('setNavVisible(".nav-btn-plex"', self.app_js)
        self.assertNotIn('setNavVisible(".nav-btn-radarr"', self.app_js)

    def test_mark_state_helper_present(self):
        self.assertIn("_markNavIntegrationState", self.app_js)

    def test_disabled_class_styled(self):
        self.assertIn(".nav-btn--disabled", self.css)
        self.assertIn("opacity", self.css.split(".nav-btn--disabled")[1][:200])

    def test_redirect_to_settings_on_disabled_click(self):
        self.assertIn("nav-btn--disabled", self.app_js)
        self.assertIn("#/settings", self.app_js)


if __name__ == "__main__":
    unittest.main()
```

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_sidebar_integrations_visible -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 7 — Commits

- `feat(dashboard): always show integration tabs with disabled state (V3-01)`
- `test(dashboard): structural test for sidebar integrations visibility`

---

## LIVRABLES

Récap :
- Sidebar toujours affiche Jellyfin / Plex / Radarr
- État "désactivé" visible (opacity + grayscale + 🔌)
- Clic sur désactivé → redirige Paramètres
- Tooltip explicatif
- 0 régression
- 2 commits sur `feat/sidebar-integrations-discovery`
