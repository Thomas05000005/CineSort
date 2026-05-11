# V1-02 — Fixer la limite CI bundle (20 MB → 60 MB)

**Branche** : `fix/ci-bundle-limit`
**Worktree** : `.claude/worktrees/fix-ci-bundle-limit/`
**Effort** : 15 min
**Priorité** : 🔴 BLOQUANT (CI cassée silencieusement)
**Fichiers concernés** :
- `.github/workflows/ci.yml`

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE avant TOUT)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b fix/ci-bundle-limit .claude/worktrees/fix-ci-bundle-limit audit_qa_v7_6_0_dev_20260428
# Si déjà existe : git worktree add .claude/worktrees/fix-ci-bundle-limit fix/ci-bundle-limit
cd .claude/worktrees/fix-ci-bundle-limit

pwd && git branch --show-current && git status
```

À partir de maintenant : tout dans ce worktree. Pas de `git checkout`. Pas de `cd ..`.

---

## RÈGLES GLOBALES

PROJET : CineSort, 2000 users en attente, publication prévue.
EXIGENCE QUALITÉ : vérifie chaque hypothèse, lis avant modifier, commits granulaires, zéro emoji.
RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT `.github/workflows/ci.yml`.

---

## MISSION

Le bundle release `dist/CineSort.exe` fait **51 MB** (mesuré).
La step CI "Verification taille EXE (max 20 MB)" exige `< 20 MB` → la CI ÉCHOUE.

La taille est légitime (LPIPS ONNX 9 MB + onnxruntime + numpy + ffmpeg embarqué).
Solution : remonter la limite à 60 MB.

### Étape 1 — Lire l'état actuel

Lis `.github/workflows/ci.yml`. Repère la step "Verification taille EXE" (probablement
ligne ~85-100) et son test `if ($size -gt 20MB)`.

### Étape 2 — Modifier la limite

Remplace `20MB` par `60MB`. Mets à jour aussi :
- Nom step : `"Verification taille EXE (max 60 MB)"`
- Message erreur : `"limite : 60 MB"`
- Commentaire au-dessus :

```yaml
# Limite portée de 20 MB à 60 MB suite à intégration moteur perceptuel V2 :
# - LPIPS AlexNet ONNX (~9 MB)
# - onnxruntime (~30 MB)
# - numpy (~15 MB)
# - ffmpeg/ffprobe/mediainfo embarqués
# Bundle actuel mesuré ~51 MB. Marge 60 MB pour absorber les évolutions.
```

### Étape 3 — Vérifications

- Diff lisible : `git diff .github/workflows/ci.yml`
- Aucun autre seuil dans ce fichier ne doit être touché

### Étape 4 — Commit

`ci: bump bundle size limit 20MB -> 60MB (perceptual ML embedded)`

---

## LIVRABLES

Récap :
- ci.yml limite mise à jour
- 1 commit sur `fix/ci-bundle-limit`
- Aucun test impact (vérifiable seulement à la prochaine GitHub Action run)
