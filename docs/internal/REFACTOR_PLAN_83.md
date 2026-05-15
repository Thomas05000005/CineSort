# Plan refactor #83 — Briser le cycle domain↔app

**Version** : 1.0 (initiale, 2026-05-15)
**Auteur** : Claude Code (session post-#84)
**Statut** : ⏳ Étape 1 mergée (PR #144). Étapes 2-4 en attente.

## Contexte

Issue [#83](https://github.com/Thomas05000005/CineSort/issues/83) ARCH-P0 : **162 lazy imports + cycle domain↔app + 3 violations layering**.

C'est la **suite logique du #84** (façades sur l'UI). Tant que le cycle `domain → app` n'est pas cassé, refactor futur reste dangereux (tests qui passent par hasard à cause de l'ordre de chargement Python).

## État au 2026-05-15

| # | Phase | Statut | PR |
|---|---|---|---|
| 1 | Service Locator perceptual → infra | ✅ Fait | #126 |
| 2 | Migrer callers `core_X.X` aliases | ✅ Fait | #128 |
| 3 étape 1 | Migrer 17 callers externes `core.plan_library` / `core._build_apply_context` | ✅ Fait | #144 |
| **3 étape 2** | **Casser le cycle réel `domain → app`** | ⏳ TODO | — |
| 3 étape 3 | Convertir 179 lazy imports → top-level | ⏳ TODO | — |
| 4 | Installer `import-linter` en CI | ⏳ TODO | — |

## Audit terrain

### Violations layering restantes

| Niveau | Status | Détail |
|---|---|---|
| L1 `domain → app` | ❌ **Critique** | 4 imports top-level dans `cinesort/domain/core.py` (lignes 39, 59, 60-64, 66) |
| L2 `domain → infra` | ✅ Résolu | PR #126 (Service Locator) |
| L3 `app → infra` | ✅ Légitime | Pas une violation (app peut utiliser infra) |

### 4 imports top-level à enlever (`cinesort/domain/core.py`)

```python
import cinesort.app.apply_core as core_apply_support                    # ligne 39
from cinesort.app.apply_core import apply_rows as _apply_rows_support   # ligne 59
from cinesort.app.cleanup import (                                       # lignes 60-64
    _move_empty_top_level_dirs,
    _move_residual_top_level_dirs,
    preview_cleanup_residual_folders,
)
import cinesort.app.plan_support as core_plan_support                    # ligne 66
```

### 38 re-exports à supprimer (`cinesort/domain/core.py:1236-1512`)

Forme typique :
```python
_cfg_signature_for_incremental = core_plan_support.cfg_signature_for_incremental
_build_apply_context = core_apply_support.build_apply_context
plan_library = core_plan_support.plan_library
move_collection_folder = core_apply_support.move_collection_folder
# ... (38 au total)
```

### Pourquoi c'est compliqué

**Le code interne de `domain/core.py` USE certains de ces helpers au runtime**, pas juste re-export. Exemples :

```python
# Ligne 1349 :
def _sha1_quick(p: Path) -> str:
    return core_apply_support.sha1_quick(p)  # appelle app !

# Ligne 1395 :
def _mkdir_counted(path, *, dry_run, log, res, record_op=None) -> None:
    core_apply_support.mkdir_counted(...)  # appelle app !

# Lignes 1461-1484 :
def _can_merge_single_without_blocking(...):
    return core_duplicate_support.can_merge_single_without_blocking(
        ...,
        is_managed_merge_file=core_apply_support.is_managed_merge_file,   # injecte app
        files_identical_quick=core_apply_support.files_identical_quick,   # injecte app
    )
```

Donc supprimer les imports top-level **casse** ces fonctions. Deux options architecturales :

**Option (a) : Bouger les fonctions vers `app/`**
- Bouger `_sha1_quick`, `_mkdir_counted`, `_can_merge_*`, `_existing_movie_folder_index`, etc. de `domain/core.py` vers `app/apply_core.py` ou `app/plan_support.py`
- Effort : ~3-5 jours, risque MOYEN
- Avantage : couches propres, le domain reste vraiment domain (métier pur)

**Option (b) : Injection de dépendances (DI)**
- Faire passer les helpers en paramètres aux fonctions de `domain/core.py`
- Par exemple : `_sha1_quick` reçoit `hash_fn` en paramètre
- Effort : ~2-3 jours, risque FAIBLE
- Avantage : moins invasif, mais signatures des fonctions explosent

**Option (c) : Garder lazy imports**
- C'est l'état actuel. Le cycle existe mais est masqué par les imports lazy
- Pas idéal mais **pragmatique** : si on n'a pas le temps, c'est OK de reporter

## Plan détaillé étape 3 (à exécuter en sessions futures)

### Étape 2a — Décision architecturale (~30 min)

Choisir entre (a) bouger les fonctions ou (b) DI. **Recommandation : (a) bouger**, car le domain ne devrait avoir aucun helper qui dépend des operations filesystem (apply, cleanup). C'est de l'app/orchestration.

### Étape 2b — Bouger les fonctions vers `app/` (~2-3 jours)

Liste des fonctions à bouger de `domain/core.py` vers `app/apply_core.py` :
- `_sha1_quick`, `_sha1_quick_cached`, `_files_identical_quick`
- `_mkdir_counted`
- `_existing_movie_folder_index`, `_movie_dir_title_year`, `_movie_key`, `_planned_target_folder`
- `_can_merge_single_without_blocking`, `_can_merge_collection_item_without_blocking`
- `_single_folder_is_conform`
- `find_duplicate_targets` (la fonction PUBLIQUE — attention aux callers)
- `is_under_collection_root`

À chaque déplacement :
1. Couper la fonction du module source
2. Coller dans le module cible
3. Ajuster les imports (le `import core_xxx_support` n'est plus nécessaire)
4. Migrer les callers externes via grep `from cinesort.domain.core import X`
5. Run tests
6. Commit + push

### Étape 2c — Supprimer les imports + re-exports (~30 min)

Une fois toutes les fonctions bougées :
- Supprimer les 4 imports top-level (lignes 39, 59, 60-64, 66 de `core.py`)
- Supprimer les 38 re-exports (lignes 1236-1512 de `core.py`)
- Verify tests pass

### Étape 3 — Lazy imports → top-level (~1 jour)

Maintenant que le cycle est cassé :
- Pour chacun des 179 lazy imports (script auto possible), tenter de remonter au top
- Si import circulaire au boot → laisser lazy avec comment expliquant pourquoi
- Sinon → top-level

### Étape 4 — `import-linter` CI (~2 heures)

`pip install import-linter` + créer `.importlinter` avec contracts :
- `domain` ne peut PAS importer `app`, `infra`, `ui`
- `app` ne peut PAS importer `ui`
- `infra` ne peut PAS importer `app`, `domain`, `ui`

Brancher dans CI workflow.

## Tag de backup

Avant chaque PR de cette phase : `git tag backup-before-83-prX` (rollback trivial).

## Effort total estimé

- Étape 3 + 4 (le gros) : **3-5 jours** de travail concentré
- À répartir sur 2-3 sessions

## Risques résiduels

1. **Casser les tests E2E** : si une fonction privée est utilisée par un test E2E pas couvert par grep
2. **Casser le build PyInstaller** : les imports top-level peuvent révéler de nouveaux problèmes au bundle
3. **Performance** : top-level imports allongent le boot de quelques ms (négligeable, ~10ms max)

Mitigation : tag backup + tests après chaque PR + smoke test EXE.

## Référence

- Issue [#83](https://github.com/Thomas05000005/CineSort/issues/83)
- PRs précédentes mergées : #126 (Service Locator), #128 (callers externes), #144 (cette session : 17 callers)
- Issue #84 (god class refactor) — mergée — c'est cette PR là qui a établi le pattern Strangler Fig + Adapter qu'on réutilise ici
