# V5A-02 — Top-bar v5 enrichi (port V3-08 + V4-09)

**Branche** : `feat/v5a-topbar-port`
**Worktree** : `.claude/worktrees/feat-v5a-topbar-port/`
**Effort** : 2-3h
**Mode** : 🟢 Parallélisable
**Fichiers concernés** :
- `web/dashboard/components/top-bar-v5.js` (enrichissement)
- `tests/test_topbar_v5_features.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/v5a-topbar-port .claude/worktrees/feat-v5a-topbar-port audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/feat-v5a-topbar-port

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `top-bar-v5.js` + son test. Pas d'autre fichier.

RÈGLE V5 : conserve le style v5 (préfixe `v5-*`, ARIA, design "data-first").

---

## CONTEXTE

`top-bar-v5.js` (6 258 octets, créé v7.6.0) a déjà : titre/sous-titre, search bar Cmd+K, cloche notifications avec compteur, menu thèmes dropdown. Il manque :

1. **V3-08** : FAB "?" coin bas-droit pour ouvrir vue Aide raccourcis (en complément de la search)
2. **V4-09** : avatar topbar avec mismatch label visible/aria — adapter le pattern `<span aria-hidden>CS</span><span class="v5u-sr-only">Profil utilisateur</span>` (mais top-bar-v5 n'a PAS d'avatar — à voir si on l'ajoute)

---

## MISSION

### Étape 1 — Lire l'existant

- `web/dashboard/components/top-bar-v5.js` (l'actuel)
- `web/dashboard/index.html` lignes 152-168 (top-bar v4 actuelle pour référence)
- `web/dashboard/app.js` lignes 393-413 (`_hookHelpFab` actuel)

### Étape 2 — Décision sur l'avatar

L'avatar `topbarAvatar` n'existe pas dans top-bar-v5 (c'est exclusivement v4). Question : doit-on l'ajouter ?

**Décision** : NON pour Phase A. C'est cosmétique, l'avatar v4 actuel n'a pas de fonctionnalité (juste affichage des initiales). On ne le porte pas en v5. Documenter dans le commit.

V4-09 adresse alors juste `top-bar-v5.js` aria-related : aucune correction nécessaire (le composant n'a pas d'élément avec mismatch).

### Étape 3 — Ajouter FAB Aide (V3-08)

Le FAB "?" est actuellement en bas-droit de l'écran (cf `app.js:393-413`). Il n'est PAS dans la top-bar mais flottant. Vu que c'est un composant global, on l'expose ici via une fonction utilitaire qu'on importera dans `app.js` au moment de l'activation v5.

Ajouter en bas de `top-bar-v5.js` :

```javascript
/* ============================================================
   V3-08 — FAB Aide (Help Floating Action Button)
   Bouton flottant coin bas-droit qui ouvre la vue Aide.
   ============================================================ */

/** Crée et insère le FAB dans le body. Idempotent. */
export function mountHelpFab(opts = {}) {
  if (document.getElementById("v5HelpFab")) return; // déjà monté
  const btn = document.createElement("button");
  btn.id = "v5HelpFab";
  btn.type = "button";
  btn.className = "v5-help-fab";
  btn.setAttribute("aria-label", "Aide raccourcis clavier (?)");
  btn.title = "Appuie sur ? pour les raccourcis";
  btn.textContent = "?";
  btn.addEventListener("click", () => {
    if (typeof opts.onClick === "function") {
      opts.onClick();
    } else {
      window.location.hash = "#/help";
    }
  });
  document.body.appendChild(btn);
}

/** Retire le FAB. */
export function unmountHelpFab() {
  const el = document.getElementById("v5HelpFab");
  if (el) el.remove();
}
```

CSS attendu (mention dans commit) : `.v5-help-fab { position: fixed; bottom: 1.5rem; right: 1.5rem; ... }` — la classe existe déjà dans `web/dashboard/styles.css` ligne ~2113 sous le nom `.help-fab`. Réutiliser ce nom OU créer alias `.v5-help-fab` qui hérite. Décision : utiliser `.v5-help-fab` pour cohérence prefix v5, et l'ajouter dans `web/shared/components.css` (si possible dans cette mission via simple ajout 10 lignes).

### Étape 4 — Améliorer la cloche notification pour mounting dynamique

La top-bar a déjà la cloche. Mais le compteur est statique (passé à l'init). Ajouter une fonction qui permet de le mettre à jour dynamiquement :

```javascript
/** V7.6.0 Notification Center — met à jour le badge count de la cloche dynamiquement. */
export function updateNotificationBadge(count) {
  const wrap = document.querySelector("[data-v5-notif-trigger] .v5-top-bar-notif-wrap");
  if (!wrap) return;
  let badge = wrap.querySelector("[data-v5-notif-badge]");
  if (count > 0) {
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "v5-top-bar-notif-badge";
      badge.setAttribute("data-v5-notif-badge", "");
      wrap.appendChild(badge);
    }
    badge.textContent = count > 99 ? "99+" : String(count);
  } else if (badge) {
    badge.remove();
  }
  // Mettre à jour aria-label du bouton
  const btn = document.querySelector("[data-v5-notif-trigger]");
  if (btn) btn.setAttribute("aria-label", `Notifications (${count} non lues)`);
}
```

### Étape 5 — Tests structurels

Crée `tests/test_topbar_v5_features.py` :

```python
"""V5A-02 — Vérifie top-bar-v5 enrichi avec FAB + notification dynamic + V4-09 audit."""
from __future__ import annotations
import unittest
from pathlib import Path


class TopBarV5FeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/dashboard/components/top-bar-v5.js").read_text(encoding="utf-8")

    def test_v3_08_help_fab_export(self):
        self.assertIn("export function mountHelpFab", self.src)
        self.assertIn("export function unmountHelpFab", self.src)
        self.assertIn("v5HelpFab", self.src)
        self.assertIn("v5-help-fab", self.src)

    def test_notification_badge_dynamic_export(self):
        self.assertIn("export function updateNotificationBadge", self.src)
        self.assertIn("data-v5-notif-badge", self.src)

    def test_v4_09_no_aria_mismatch(self):
        # top-bar-v5 ne doit PAS avoir l'avatar avec aria-label="Profil utilisateur" + texte visible "CS"
        # (c'est uniquement dans v4 — top-bar-v5 ne l'a jamais eu)
        self.assertNotIn("topbarAvatar", self.src)

    def test_existing_features_preserved(self):
        # Search Cmd+K
        self.assertIn("data-v5-search-trigger", self.src)
        # Theme menu
        self.assertIn("data-v5-theme-trigger", self.src)
        # Notification cloche
        self.assertIn("data-v5-notif-trigger", self.src)


if __name__ == "__main__":
    unittest.main()
```

### Étape 6 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_topbar_v5_features -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
node --check web/dashboard/components/top-bar-v5.js 2>&1 | tail -2
```

### Étape 7 — Commits

- `feat(topbar-v5): port V3-08 Help FAB (mount/unmount exports)`
- `feat(topbar-v5): expose updateNotificationBadge for dynamic count`
- `test(topbar-v5): structural tests for V5A-02 features`

---

## LIVRABLES

- `top-bar-v5.js` enrichi avec 2 fonctions exportées (`mountHelpFab`, `unmountHelpFab`, `updateNotificationBadge`)
- Test structurel
- Style v5 préservé
- Pas d'avatar (décision documentée)
- 3 commits sur `feat/v5a-topbar-port`
