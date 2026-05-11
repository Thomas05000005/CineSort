# Setup git worktrees — OBLIGATOIRE pour orchestration parallèle

## Pourquoi

Le repo `C:\Users\blanc\projects\CineSort` est partagé par plusieurs instances
Claude Code en parallèle. **Sans worktree** :
- Instance A : `git checkout -b branchA`
- Instance B : `git checkout -b branchB` (HEAD bascule)
- Instance A : `git commit` → tombe sur **branchB** (corruption)

**Avec worktree** : chaque instance a son propre dossier `.claude/worktrees/<NOM>/`
avec son propre HEAD git. Les fichiers sont séparés sur disque, mais le `.git/`
est partagé (économique). Zéro collision.

---

## Conventions

- Dossier des worktrees : `.claude/worktrees/<NOM>/` à la racine du repo
- Nom du worktree = nom de la branche avec `/` remplacé par `-`
  - Branche `fix/license-mit` → worktree `.claude/worktrees/fix-license-mit/`
- Branche de base pour TOUS les worktrees : `audit_qa_v7_6_0_dev_20260428`

---

## Procédure standard pour CHAQUE instance

### Cas 1 — Nouvelle mission (branche n'existe pas encore)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b <BRANCHE> .claude/worktrees/<NOM> audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/<NOM>
```

### Cas 2 — Reprise (branche existe déjà, ex: instance précédente plantée)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add .claude/worktrees/<NOM> <BRANCHE>
cd .claude/worktrees/<NOM>
```

### Vérification (à faire après chaque création)

```bash
pwd                          # doit afficher .../.claude/worktrees/<NOM>
git branch --show-current    # doit afficher <BRANCHE>
git status                   # working tree clean
```

---

## Règles dans le worktree

À partir du moment où tu as `cd .claude/worktrees/<NOM>` :

- ✅ **TOUS** tes `git`, `Edit`, `Read`, `Write`, `Bash` se font DANS ce dossier
- ✅ Les chemins absolus restent corrects (le worktree contient une copie de l'arbre)
- ✅ `.venv313` est partagé (symlink sous Windows / accessible depuis le worktree)
- ❌ NE SORS JAMAIS du worktree pour faire un commit
- ❌ NE FAIS JAMAIS `git checkout <autre-branche>` (ça brise l'isolation)
- ❌ NE FAIS JAMAIS `cd ..` puis git commit dans le repo principal

---

## Cleanup à la fin (après merge de la branche)

L'orchestrateur principal nettoiera :

```bash
cd /c/Users/blanc/projects/CineSort
git worktree remove .claude/worktrees/<NOM>
git branch -d <BRANCHE>  # ou -D si force
```

NE FAIS PAS le cleanup toi-même — laisse l'orchestrateur le faire après merge.

---

## En cas de problème

**"fatal: '<NOM>' already exists"** :
- Worktree déjà créé par une autre instance plantée
- Solution : `git worktree remove .claude/worktrees/<NOM> --force` puis recréer

**"fatal: '<BRANCHE>' is already checked out at <path>"** :
- La branche est déjà checked-out dans un autre worktree
- Vérifie : `git worktree list`
- Soit utilise ce worktree existant, soit force-remove l'autre

**HEAD bascule alors que tu es dans le worktree** :
- Quelqu'un fait des opérations dans le repo principal qui touchent ta branche
- Vérifie : `git worktree list` → ta branche doit être listée comme "(detached HEAD)" ou avec le path du worktree
- Si problème : signale immédiatement à l'orchestrateur

---

## Rappel des associations branche ↔ worktree pour la Vague 1

| Mission | Branche | Worktree |
|---|---|---|
| V1-01 | `fix/license-mit` | `fix-license-mit` |
| V1-02 | `fix/ci-bundle-limit` | `fix-ci-bundle-limit` |
| V1-03 | `fix/cve-deps-bump` | `fix-cve-deps-bump` |
| V1-04 | `fix/accent-rester-connecte` | `fix-accent-rester-connecte` |
| V1-05 | `fix/empty-state-quality-cta` | `fix-empty-state-quality-cta` |
| V1-06 | `fix/integrations-link-to-settings` | `fix-integrations-link-to-settings` |
| V1-07 | `fix/alert-warning-outils-banner` | `fix-alert-warning-outils-banner` |
| V1-08 | `feat/migration-020-indexes` | `feat-migration-020-indexes` |
| V1-09 | `feat/db-integrity-boot-check` | `feat-db-integrity-boot-check` |
| V1-10 | `feat/settings-json-auto-backup` | `feat-settings-json-auto-backup` |
| V1-11 | `feat/http-retry-helper` | `feat-http-retry-helper` |
| V1-12 | `feat/footer-about-support` | `feat-footer-about-support` |
| V1-13 | `feat/auto-update-github-releases` | `feat-auto-update-github-releases` |
| V1-14 | `feat/help-view-faq-glossary` | `feat-help-view-faq-glossary` |
