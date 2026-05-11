# Script de cleanup après incident worktree

**Date** : 1er mai 2026
**Contexte** : Lors du premier lancement parallèle (sans worktrees), des commits sont
tombés sur les mauvaises branches. Aucun travail n'est perdu, juste à réorganiser.

---

## 🔍 État actuel à reconstituer

```
fix/license-mit                     : VIDE (commit V1-01 a fini sur feat/migration-020-indexes)
fix/ci-bundle-limit                 : ✅ V1-02 OK (6061bf3)
fix/cve-deps-bump                   : VIDE (V1-03 jamais lancée)
fix/accent-rester-connecte          : ✅ V1-04 OK (6932f69, dans son worktree)
fix/empty-state-quality-cta         : ❌ contient V1-09 (cca9aaa) + V1-06 (10298b8) parasites
fix/integrations-link-to-settings   : ❌ contient V1-05 (ce2baa0) parasite
fix/alert-warning-outils-banner     : ✅ V1-07 OK (1db1d86)
feat/migration-020-indexes          : ❌ contient V1-01 (8ba18bc) parasite
feat/db-integrity-boot-check        : VIDE (V1-09 a fini sur fix/empty-state-quality-cta)
feat/settings-json-auto-backup      : ❌ contient V1-10 (cbabb9c) OK + V1-08 (a0abfdf) parasite
feat/v1m10-settings-backup          : VIDE (branche dupliquée par erreur)
```

Plus 3 fichiers untracked dans le working tree principal :
- `tests/test_db_indexes.py` (V1-08 — créé mais jamais committé)
- `tests/test_db_integrity_boot.py` (V1-09 — créé mais jamais committé)
- `cinesort/infra/db/migrations/020_quality_reports_perf_indexes.sql` (V1-08)

---

## ✅ Plan de cleanup (à exécuter par l'utilisateur humain)

⚠ **Sauvegarde d'abord** : `git tag backup/avant-cleanup-20260501-incident` sur HEAD
actuel pour pouvoir revenir si besoin.

### Phase A — Stash les untracked

```bash
cd /c/Users/blanc/projects/CineSort
git checkout audit_qa_v7_6_0_dev_20260428  # branche stable
git stash push -u -m "WIP files V1-08/V1-09 avant cleanup" -- \
  tests/test_db_indexes.py \
  tests/test_db_integrity_boot.py \
  cinesort/infra/db/migrations/020_quality_reports_perf_indexes.sql
```

### Phase B — Identifier les SHA des commits parasites

```bash
git log --all --oneline --source 1970267..HEAD 2>&1 | head -20
```

Note les SHA exacts (à adapter si différents) :
- `8ba18bc` = V1-01 LICENSE → à déplacer sur `fix/license-mit`
- `cca9aaa` = V1-09 integrity_check → à déplacer sur `feat/db-integrity-boot-check`
- `10298b8` = V1-06 Jellyfin link → à déplacer sur `fix/integrations-link-to-settings`
- `ce2baa0` = V1-05 Quality CTA → à déplacer sur `fix/empty-state-quality-cta`
- `a0abfdf` = V1-08 migration 020 → à déplacer sur `feat/migration-020-indexes`

### Phase C — Cherry-pick chaque commit sur sa bonne branche

#### V1-01 : déplacer 8ba18bc vers fix/license-mit

```bash
git checkout fix/license-mit
git cherry-pick 8ba18bc
# Résultat : fix/license-mit a maintenant le commit LICENSE
```

#### V1-09 : déplacer cca9aaa vers feat/db-integrity-boot-check

```bash
git checkout feat/db-integrity-boot-check
git cherry-pick cca9aaa
```

#### V1-06 : déplacer 10298b8 vers fix/integrations-link-to-settings

```bash
git checkout fix/integrations-link-to-settings
# Reset d'abord la branche (vire le commit V1-05 parasite ce2baa0)
git reset --hard 1970267
# Cherry-pick le bon commit V1-06
git cherry-pick 10298b8
```

#### V1-05 : déplacer ce2baa0 vers fix/empty-state-quality-cta

```bash
git checkout fix/empty-state-quality-cta
# Reset d'abord (vire les 2 commits parasites cca9aaa + 10298b8)
git reset --hard 1970267
# Cherry-pick le bon commit V1-05
git cherry-pick ce2baa0
```

#### V1-08 : déplacer a0abfdf vers feat/migration-020-indexes

```bash
git checkout feat/migration-020-indexes
# Reset d'abord (vire le commit LICENSE parasite 8ba18bc)
git reset --hard 1970267
# Cherry-pick V1-08 migration
git cherry-pick a0abfdf
# Restorer les fichiers stashés (test + migration SQL)
git stash pop
git add tests/test_db_indexes.py cinesort/infra/db/migrations/020_quality_reports_perf_indexes.sql
git commit -m "test(db): add test_db_indexes for migration 020"
```

#### V1-10 : nettoyer feat/settings-json-auto-backup

```bash
git checkout feat/settings-json-auto-backup
# Vire le commit migration parasite (a0abfdf), garde V1-10 (cbabb9c)
git rebase --onto 1970267 a0abfdf cbabb9c
# Vérifier
git log --oneline | head -3  # doit montrer cbabb9c en tête
```

#### V1-09 : ajouter le test untracked

```bash
git checkout feat/db-integrity-boot-check
git stash pop  # si pas déjà fait
git add tests/test_db_integrity_boot.py
git commit -m "test(db): add test_db_integrity_boot for boot integrity check"
```

#### Phase D — Nettoyer la branche dupliquée

```bash
git branch -d feat/v1m10-settings-backup  # ou -D si force
```

#### Phase E — Vérifier l'état final

```bash
git log --all --oneline --source 1970267..HEAD 2>&1 | head -30
```

Attendu :
```
fix/license-mit                    : 1 commit (V1-01)
fix/ci-bundle-limit                : 1 commit (V1-02)
fix/accent-rester-connecte         : 1 commit (V1-04)
fix/empty-state-quality-cta        : 1 commit (V1-05)
fix/integrations-link-to-settings  : 1 commit (V1-06)
fix/alert-warning-outils-banner    : 1 commit (V1-07)
feat/migration-020-indexes         : 2 commits (V1-08 + test)
feat/db-integrity-boot-check       : 2 commits (V1-09 + test)
feat/settings-json-auto-backup     : 1 commit (V1-10)
```

Branches encore vides (à faire) :
- `fix/cve-deps-bump` (V1-03 jamais lancée)
- Pas de branches V1-11, V1-12, V1-13, V1-14 (jamais lancées)

---

## 🔄 Phase F — Setup des worktrees pour relancer proprement

Après cleanup, créer les worktrees pour les missions restantes :

```bash
# Missions à finir
git worktree add .claude/worktrees/fix-cve-deps-bump fix/cve-deps-bump 2>/dev/null || \
  git worktree add -b fix/cve-deps-bump .claude/worktrees/fix-cve-deps-bump audit_qa_v7_6_0_dev_20260428

git worktree add -b feat/http-retry-helper .claude/worktrees/feat-http-retry-helper audit_qa_v7_6_0_dev_20260428
git worktree add -b feat/footer-about-support .claude/worktrees/feat-footer-about-support audit_qa_v7_6_0_dev_20260428
git worktree add -b feat/auto-update-github-releases .claude/worktrees/feat-auto-update-github-releases audit_qa_v7_6_0_dev_20260428
git worktree add -b feat/help-view-faq-glossary .claude/worktrees/feat-help-view-faq-glossary audit_qa_v7_6_0_dev_20260428
```

Vérifier :
```bash
git worktree list
```

---

## 📋 Statut par mission après cleanup

| # | Mission | Branche | Statut |
|---|---|---|---|
| V1-01 | LICENSE MIT | `fix/license-mit` | ⚠ partiel (LICENSE seulement, pyproject + README à faire) |
| V1-02 | CI bundle limit | `fix/ci-bundle-limit` | ✅ FAIT |
| V1-03 | CVE deps bump | `fix/cve-deps-bump` | ❌ À FAIRE |
| V1-04 | Accent connecté | `fix/accent-rester-connecte` | ✅ FAIT |
| V1-05 | Empty state Quality | `fix/empty-state-quality-cta` | ✅ FAIT |
| V1-06 | Liens intégrations | `fix/integrations-link-to-settings` | ⚠ partiel (Jellyfin seulement, Plex+Radarr à faire) |
| V1-07 | Alert warning outils | `fix/alert-warning-outils-banner` | ✅ FAIT |
| V1-08 | Migration 020 indexes | `feat/migration-020-indexes` | ✅ FAIT (avec test ajouté) |
| V1-09 | PRAGMA integrity boot | `feat/db-integrity-boot-check` | ✅ FAIT (avec test ajouté) |
| V1-10 | Backup settings.json | `feat/settings-json-auto-backup` | ✅ FAIT |
| V1-11 | Helper retry HTTP | `feat/http-retry-helper` | ❌ À FAIRE |
| V1-12 | Footer + About | `feat/footer-about-support` | ❌ À FAIRE |
| V1-13 | Update auto GitHub | `feat/auto-update-github-releases` | ❌ À FAIRE |
| V1-14 | Vue Aide FAQ | `feat/help-view-faq-glossary` | ❌ À FAIRE |

**Total restant** : 4 missions complètes (V1-03, V1-11, V1-12, V1-13, V1-14) + 2 partielles (V1-01 finir pyproject+README, V1-06 finir Plex+Radarr).

= **6 instances à relancer en parallèle**, dans leurs worktrees respectifs.

---

## ⚠️ Précautions pour le relancement

1. CHAQUE instance lit son fichier `audit/prompts/vague1/0X-XXX.md`
2. CHAQUE instance fait `git worktree add` (étape 0)
3. CHAQUE instance vérifie `git log --oneline | head -3` AVANT de coder :
   - Si elle voit des commits, c'est OK, elle continue / complète
   - Si elle voit des commits qui ne lui appartiennent pas, elle signale STOP
4. AUCUNE instance ne fait `git checkout` autre que celui de l'étape 0
