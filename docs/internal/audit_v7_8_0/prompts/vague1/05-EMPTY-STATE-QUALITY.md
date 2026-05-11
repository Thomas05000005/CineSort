# V1-05 — Empty state Qualité avec CTA "Lancer un scan"

**Branche** : `fix/empty-state-quality-cta`
**Worktree** : `.claude/worktrees/fix-empty-state-quality-cta/`
**Effort** : 1-2h
**Priorité** : 🔴 BLOQUANT (friction UX)
**Fichiers concernés** :
- `web/views/quality.js` (desktop)
- `web/dashboard/views/quality.js` (dashboard distant)
- (potentiellement) `web/styles.css` ou `web/dashboard/styles.css`

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE avant TOUT)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b fix/empty-state-quality-cta .claude/worktrees/fix-empty-state-quality-cta audit_qa_v7_6_0_dev_20260428
# Si déjà existe : git worktree add .claude/worktrees/fix-empty-state-quality-cta fix/empty-state-quality-cta
cd .claude/worktrees/fix-empty-state-quality-cta

pwd && git branch --show-current && git status
```

⚠ Cette branche existe déjà avec des commits qui NE LUI appartiennent pas
(commit `cca9aaa feat(db): integrity_check` qui devrait être sur V1-09 et
commit `10298b8 fix(ui): add settings link Jellyfin` qui devrait être sur V1-06).
**L'orchestrateur va nettoyer cette branche** avant que tu commences. Vérifie
`git log --oneline | head -5` : tu ne dois voir QUE le tip de base
`audit_qa_v7_6_0_dev_20260428`. Sinon attends le cleanup.

À partir de maintenant : tout dans ce worktree.

---

## RÈGLES GLOBALES

PROJET : CineSort. EXIGENCE QUALITÉ : recherche, lis, vérifie, teste.
RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT les 2 quality.js + éventuellement CSS.

---

## MISSION

Quand la page **Qualité** est vide (aucun film scoré), elle affiche actuellement :
> "Aucun film n'a scoré. Lancez un scan pour analyser votre bibliothèque."

→ message statique sans bouton. L'utilisateur doit naviguer ailleurs pour faire le scan.

### Étape 1 — Comprendre le pattern empty state existant

Lis :
- `web/views/quality.js` — repère le bloc empty state
- `web/dashboard/views/quality.js` — idem
- `web/components/empty-state.js` — composant réutilisable existant

### Étape 2 — Voir l'API "lancer un scan"

Lis `web/views/home.js` pour voir comment est appelé `start_plan`.
Pour le dashboard distant : lis `web/dashboard/views/status.js`.

### Étape 3 — Implémenter le CTA

Pour CHACUNE des 2 vues quality.js :
- Ajouter bouton primary "Lancer un scan" dans le bloc empty state
- Au click :
  - Desktop : `navigateTo("home")` puis scroll vers le bouton scan
  - Dashboard : `navigateTo("/status")` puis scroll vers le bouton scan

CSS : utiliser les classes existantes (`.btn`, `.btn--primary`).

### Étape 4 — Tests

- node --check sur les 2 .js modifiés
- `.venv313/Scripts/python.exe -m unittest tests.test_quality* -v 2>&1 | tail -5`

### Étape 5 — Commit

`fix(ui): add 'Lancer un scan' CTA in Quality empty state (desktop + dashboard)`

---

## LIVRABLES

Récap :
- Empty state desktop quality.js : CTA ajouté
- Empty state dashboard quality.js : CTA ajouté
- Tests : 0 régression
- 1-2 commits sur `fix/empty-state-quality-cta`
