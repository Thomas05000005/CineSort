# V1-14 — Vue Aide #/help (FAQ + glossaire métier)

**Branche** : `feat/help-view-faq-glossary`
**Worktree** : `.claude/worktrees/feat-help-view-faq-glossary/`
**Effort** : 4-6h
**Priorité** : 🔴 BLOQUANT publication (2000 users non-tech)
**Fichiers concernés** :
- `web/dashboard/views/help.js` (nouveau)
- `web/views/help.js` (nouveau, IIFE pour pywebview)
- `web/dashboard/index.html` (ajouter conteneur view-help + lien sidebar)
- `web/index.html` (ajouter section view-help + bouton navigation)
- `web/dashboard/app.js` ou router (route /help)
- `web/core/router.js` (route help pour desktop)

⚠ NE PAS toucher à `web/views/about.js` (mission V1-12).

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b feat/help-view-faq-glossary .claude/worktrees/feat-help-view-faq-glossary audit_qa_v7_6_0_dev_20260428
# Si déjà existe : git worktree add .claude/worktrees/feat-help-view-faq-glossary feat/help-view-faq-glossary
cd .claude/worktrees/feat-help-view-faq-glossary

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

PROJET : CineSort, FR francophone, 2000 users en attente.
RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT les fichiers listés.

---

## MISSION

Avec 2000 users non-tech : vue Aide #/help avec FAQ + glossaire métier + lien
support. Sans cette vue : 2000 mails "c'est quoi un dry-run ?".

### Étape 1 — Recherche

WebSearch : "in-app help FAQ pattern desktop 2025"
Inspire-toi : Obsidian Help, Linear /help, Notion /help.

### Étape 2 — Lire CLAUDE.md sections métier

Lis `CLAUDE.md` sections : Quality scoring, Tiers, Dry-run/quarantine/undo, Profils
de renommage, Détection doublons → source de vérité pour le glossaire.

### Étape 3 — Contenu FAQ (15 questions)

Reformule en langage utilisateur. Couvre :
- Comment lancer mon premier scan ?
- C'est quoi un dry-run ?
- Comment fonctionne l'auto-approbation ?
- Mes décisions ont disparu après refresh, pourquoi ?
- Comment annuler un apply ?
- Comment configurer Jellyfin/Plex/Radarr ?
- Mon scan ne trouve pas de films, que faire ?
- C'est quoi le mode perceptuel ?
- Comment installer ffmpeg/mediainfo ?
- Comment partager mes logs pour signaler un bug ?
- Mon antivirus dit que CineSort est dangereux
- Le dashboard distant ne se connecte pas
- Que veut dire 'tier Platinum/Gold/Silver/Bronze/Reject' ?
- Comment exporter un rapport de mon analyse ?
- Puis-je utiliser CineSort sans connexion Internet ?

### Étape 4 — Glossaire (15 termes)

- Probe, Tier, Score V2, Score V1, Confidence, Edition, Saga TMDb, Perceptual,
  LPIPS, Grain era, DRC, SSIM, Chromaprint, Dry-run, Quarantine, NFO

(Définitions courtes, langage utilisateur — voir CLAUDE.md pour les sources)

### Étape 5 — Créer web/dashboard/views/help.js (ES module)

Pattern cf web/dashboard/views/status.js. Structure :
- Search bar (filtre FAQ + glossaire en temps réel)
- Section FAQ (`<details>` + `<summary>`)
- Section Glossaire (`<dl>`)
- Section Support (lien GitHub Issues + path logs)

```javascript
import { $ } from "../core/dom.js";

const FAQ_ITEMS = [ /* cf Étape 3 */ ];
const GLOSSARY = [ /* cf Étape 4 */ ];
const PROJECT_GITHUB_URL = "https://github.com/PLACEHOLDER/cinesort";

let _mounted = false;

export function initHelp(el) {
  if (!_mounted) {
    _mounted = true;
    _render(el);
    _hookEvents();
  }
}
// ... _render(), _hookEvents(), _esc(), _lower() ...
```

### Étape 6 — Créer web/views/help.js (IIFE pywebview)

Adapter en IIFE avec `window.HelpView.open()`.

### Étape 7 — Routes

Dashboard : ajouter route `/help` dans `web/dashboard/app.js` ou router :
```javascript
import { initHelp } from "./views/help.js";
"/help": (el) => initHelp(el),
```

Conteneur dans `web/dashboard/index.html` :
```html
<div id="view-help" class="view">
  <div id="helpContent"></div>
</div>
```

Sidebar : `<a href="#/help">Aide</a>`.

Desktop : entrée sidebar OU bouton "?" qui appelle `window.HelpView.open()`.

### Étape 8 — Raccourci F1

Modifier `web/core/keyboard.js` : F1/? ouvre la vue Aide (au lieu de la modale
raccourcis simple). Garder Ctrl+K pour la palette.

⚠ Vérifie d'abord que personne d'autre ne touche keyboard.js. Si conflit
potentiel : laisse keyboard.js + ajouter Help via sidebar.

### Étape 9 — Tests

`tests/test_help_view.py` :
- Vérifie fichiers existent
- Vérifie contenu FAQ (≥10 questions)
- Vérifie glossaire (≥15 termes)
- Vérifie présence lien GitHub Issues

### Étape 10 — Vérifications

```bash
node --check web/views/help.js
node --check web/dashboard/views/help.js
.venv313/Scripts/python.exe -m unittest tests.test_help_view -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . | tail -3
```

### Étape 11 — Commits

- `feat(help): add help view with FAQ + glossary (15 terms, 15 questions)`
- `feat(router): add /help route + sidebar link (desktop + dashboard)`
- `test(help): structural tests for help view content`

---

## LIVRABLES

Récap :
- 2 vues help créées
- 15 questions FAQ + 15 termes glossaire
- Search bar pour filtrer en temps réel
- Lien GitHub Issues + path logs visibles
- Route /help (dashboard) + bouton/sidebar (desktop)
- Tests structurels
- 0 régression
- 3 commits sur `feat/help-view-faq-glossary`
