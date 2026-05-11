# V1-06 — Liens "Aller aux réglages" sur Jellyfin/Plex/Radarr non configurés

**Branche** : `fix/integrations-link-to-settings`
**Worktree** : `.claude/worktrees/fix-integrations-link-to-settings/`
**Effort** : 1-2h
**Priorité** : 🔴 BLOQUANT
**Fichiers concernés** :
- `web/views/jellyfin-view.js`
- `web/views/plex-view.js`
- `web/views/radarr-view.js`
- `web/dashboard/views/jellyfin.js`
- `web/dashboard/views/plex.js`
- `web/dashboard/views/radarr.js`

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE avant TOUT)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b fix/integrations-link-to-settings .claude/worktrees/fix-integrations-link-to-settings audit_qa_v7_6_0_dev_20260428
# Si déjà existe : git worktree add .claude/worktrees/fix-integrations-link-to-settings fix/integrations-link-to-settings
cd .claude/worktrees/fix-integrations-link-to-settings

pwd && git branch --show-current && git status
```

⚠ Cette branche existe déjà avec un commit `ce2baa0 fix(ui): add 'Lancer un scan' CTA`
qui appartient en fait à V1-05. **L'orchestrateur va nettoyer cette branche** avant
que tu commences. Vérifie `git log --oneline | head -3` : si tu vois ce commit
parasite, attends le cleanup.

---

## RÈGLES GLOBALES

EXIGENCE QUALITÉ : recherche, lis, vérifie, teste.
RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT les 6 fichiers vues intégrations listés.

---

## MISSION

Quand Jellyfin / Plex / Radarr est désactivé : la vue affiche "Intégration X désactivée.
Pour l'activer, ouvrez les réglages..." sans **aucun lien** vers les réglages.
Avec 2000 users : dead-end.

### Étape 1 — Comprendre la structure

Pour CHACUN des 6 fichiers : repère le block "non configuré" / `if (!enabled)`.

### Étape 2 — Comprendre la navigation vers Settings

Desktop : `navigateTo("settings")` (cf `web/core/router.js`)
Dashboard : `<a href="#/settings">` ou trigger hash router

### Étape 3 — Modifier les 6 vues

Desktop pattern :
```javascript
<button class="btn btn--primary" onclick="navigateTo('settings')">
  Ouvrir les réglages Jellyfin
</button>
```

Dashboard pattern :
```html
<a href="#/settings" class="btn btn--primary">Ouvrir les réglages Jellyfin</a>
```

(Adapter le texte par intégration : Jellyfin / Plex / Radarr)

### Étape 4 — Bonus si simple : scroll vers section

Si Settings a `id="settings-jellyfin"` (ou similaire) :
```javascript
navigateTo('settings');
setTimeout(() => document.getElementById('settings-jellyfin')?.scrollIntoView({behavior:'smooth'}), 100);
```

NE PAS over-engineer si pas d'ancre existante.

### Étape 5 — Tests

```bash
for f in web/views/jellyfin-view.js web/views/plex-view.js web/views/radarr-view.js \
         web/dashboard/views/jellyfin.js web/dashboard/views/plex.js web/dashboard/views/radarr.js; do
  node --check "$f"
done
.venv313/Scripts/python.exe -m unittest tests.test_jellyfin* tests.test_plex* tests.test_radarr* -v 2>&1 | tail -10
```

### Étape 6 — Commits

3 commits cohérents :
- `fix(ui): add settings link in Jellyfin disabled state (desktop + dashboard)`
- `fix(ui): add settings link in Plex disabled state (desktop + dashboard)`
- `fix(ui): add settings link in Radarr disabled state (desktop + dashboard)`

---

## LIVRABLES

Récap :
- 6 vues modifiées
- 3 commits sur `fix/integrations-link-to-settings`
- Tests : 0 régression
