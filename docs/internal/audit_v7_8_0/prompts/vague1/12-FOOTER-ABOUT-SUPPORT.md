# V1-12 — Footer + section About + canaux support

**Branche** : `feat/footer-about-support`
**Worktree** : `.claude/worktrees/feat-footer-about-support/`
**Effort** : 2-3h
**Priorité** : 🔴 BLOQUANT publication
**Fichiers concernés** :
- `web/index.html` (modal About + footer sidebar)
- `web/dashboard/index.html` (modal About + footer)
- `web/views/about.js` (nouveau, desktop)
- `web/dashboard/views/about.js` (nouveau, dashboard)

⚠ NE PAS toucher à `settings.js` ou `settings_support.py`.

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/footer-about-support .claude/worktrees/feat-footer-about-support audit_qa_v7_6_0_dev_20260428
# Si déjà existe : git worktree add .claude/worktrees/feat-footer-about-support feat/footer-about-support
cd .claude/worktrees/feat-footer-about-support

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

PROJET : CineSort, FR, 2000 users en attente.
RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT les fichiers listés.

---

## MISSION

Avec 2000 users : l'app doit afficher version, licence, comment signaler bug,
où sont les logs, mention privacy "no telemetry".

### Étape 1 — Recherche

WebSearch : "About modal pattern desktop app 2025 indie privacy-first"
Inspiration : Obsidian / Standard Notes / Joplin.

### Étape 2 — Lire VERSION

```bash
cat VERSION
```

Lis dynamiquement (pas hardcoder).

### Étape 3 — Constantes placeholder

```javascript
const PROJECT_GITHUB_URL = "https://github.com/PLACEHOLDER/cinesort";
const PROJECT_ISSUES_URL = `${PROJECT_GITHUB_URL}/issues`;
```

### Étape 4 — Créer la modal About (desktop)

`web/views/about.js` (IIFE pattern, cf autres views) avec :
- Version (lue via API ou fetch VERSION)
- Licence MIT mention
- Section Privacy "No telemetry, no tracking, 100% local"
- Section Support : lien GitHub Issues + path logs + bouton "Ouvrir dossier logs"
- Crédits dépendances (top 5)

Voir prompt original (audit/parallel_prompts.md backup) pour code complet.
Pattern utilisé :
```javascript
(function () {
  "use strict";
  if (!window.AboutModal) window.AboutModal = {};
  // ... open(), close(), _create(), _openLogsDir() ...
  window.AboutModal.open = open;
  window.AboutModal.close = close;
})();
```

### Étape 5 — Endpoints Python (non-blocking)

`get_app_version` et `open_logs_dir` peuvent ne pas exister. Vérifie :
```bash
grep -n "get_app_version\|open_logs_dir" cinesort/ui/api/
```

S'ils manquent : laisse un TODO + fallback hardcodé temporaire.

### Étape 6 — Modal About (dashboard distant)

`web/dashboard/views/about.js` ES module pattern, cf `web/dashboard/views/status.js`.

### Étape 7 — Footer link

`web/index.html` : ajouter petit lien "À propos" → `window.AboutModal.open()`
`web/dashboard/index.html` : idem avec href hash

### Étape 8 — Charger les nouveaux scripts

`<script defer src="./views/about.js">` dans index.html. Idem dashboard.

### Étape 9 — Vérifications

```bash
node --check web/views/about.js
node --check web/dashboard/views/about.js
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
```

### Étape 10 — Commits

- `feat(ui): add About modal with version/license/privacy/support links`
- `feat(dashboard): add About view + footer link`

---

## LIVRABLES

Récap :
- 2 vues About créées (desktop + dashboard)
- Footer link ajouté dans les 2 UIs
- TODO si endpoints get_app_version / open_logs_dir manquent
- 0 régression
- 2 commits sur `feat/footer-about-support`
