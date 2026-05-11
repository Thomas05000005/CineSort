# Chantier Phase 13.x — Pollution d'etat globale inter-tests

**Date** : 2026-05-11
**Status** : INVESTIGATION uniquement, fix reporte v7.9.0
**Symptome** : 26 tests echouent dans `python -m unittest discover` mais passent a **100 %** en isolation.

---

## Tests affectes (26 au total)

Regroupes par module :

| Module | Tests failants | Pattern d'echec |
|--------|----------------|-----------------|
| `test_undo_apply` | 6 | `start_plan` retourne `ok` mais `get_plan` rend `rows: []` |
| `test_quality_score` | 5 | meme pattern (`_prepare_single_run` line 113) |
| `test_incremental_scan` | 4 | meme pattern |
| `test_scan_streaming` | 3 | meme pattern |
| `test_undo_checksum` | 1 | meme pattern |
| `test_tv_detection` | 1 | meme pattern |
| `test_multi_root` | 1 | meme pattern |
| `test_run_report_export` | 1 | meme pattern |
| `test_perceptual_parallel` | 1 | flake threading lie au pool |
| `test_release_hygiene` | 2 | `test_no_personal_strings_in_repo` + UI terminology — orthogonaux |

---

## Caracteristique commune

Tous les tests affectes invoquent `api.start_plan(...)` puis `api.get_plan(run_id)` et trouvent un plan vide. Cela signifie que la phase de **scan filesystem ou de filtrage video** rejette tous les fichiers du temp directory du test.

Aucune erreur n'est leve : `start_plan.get("ok") = True` et `get_plan.get("ok") = True`. C'est silencieusement le scan qui ne trouve plus rien.

---

## Hypotheses ecartees

1. **`core.MIN_VIDEO_BYTES` mute** : tous les tests touchant cette valeur la restaurent via `setUp/tearDown` ou `addCleanup`. Verifie par grep cross-tests.
2. **`_NFO_SIG_CACHE` global** (`plan_support.py:241`) : cache keye sur `(path_str, size, mtime_ns)` — chaque test utilise un temp dir different, donc cle differente, donc cache miss = recompute. Pas de fuite.
3. **`_resolve_path_cached` lru_cache** (`plan_support.py:852`) : LRU 16 slots keyed sur string. Different paths = different keys.
4. **Suite cycle guard** (`test_import_cycle_guard.py`) : snapshot/restore complete de `sys.modules` apres mon fix Phase 10. Verifie OK.

---

## Hypothese restante (a investiguer en session dediee)

**Probable** : une singleton dans `CineSortApi.__init__()` ou dans un sous-module (probe service ? job_runner ? notification_store ?) retient un etat (lock, thread pool, file handler) entre instances API successives. Apres N tests, l'etat sature et le scan s'effondre.

Indice : les tests affectes appellent tous `api.start_plan()` qui implique :
- Creation d'un thread daemon via `JobRunner`
- Acces au `SQLiteStore` partage
- Resolution `cfg.root` via `_resolve_path_cached` LRU
- Reconciliation au boot via `_RECONCILED_STATE_DIRS` (set module-level dans `runtime_support.py`)

Le set `_RECONCILED_STATE_DIRS` ne degrade pas la correction, mais pourrait creer une condition de course si threads daemons se chevauchent.

---

## Reproduction

```bash
# Echec deterministe en suite complete
python -m unittest discover -s tests -p "test_*.py" -v
# 25 failures + 1 error sur 3949 tests

# Passe a 100 % en isolation
python -m unittest tests.test_undo_apply
# 8/8 OK

python -m unittest tests.test_quality_score
# 8/8 OK (pour les tests qui passent)
```

---

## Verifie : NON cause par cette session

Sur la base state **avant les changements de cette session** (`git stash` Vague 1 + Vague 2), MEMES failures, MEME comportement. Donc :

> Cette pollution est **pre-existante** a v7.8.0 — probablement liee a la migration desktop → dashboard ou aux refactors precedents (V5C, V6). Pas une regression de cette session.

---

## Plan de remediation (v7.9.0)

1. **Bisecter** : pour chaque test failant, identifier le test predecesseur qui declenche la pollution (binary search sur l'ordre alphabetique).
2. **Profiler** : ajouter un setUp/tearDown commun qui logge l'etat des singletons (locks, pools, sets) avant/apres chaque test.
3. **Fix root cause** : selon le coupable identifie, soit (a) reset explicite dans `CineSortApi.__init__()`, (b) `reset_for_tests()` helper systematique, (c) eliminer le singleton.
4. **Cliquet** : ajouter un test meta qui asserte que la suite passe a 100 % en mode random order (`unittest --testRunner=... --random-order` via pytest-randomly).

**Budget estime** : 1-2 jours de bisection + fix.

---

## Impact actuel

- **Tests passent en CI sequentiel** : seulement si on isole les modules failants.
- **Coverage gate** : 80 % seuil est respecte malgre les fails (les chemins de code sont exerces, juste les asserts qui flag).
- **Production** : aucun impact (le code prod fonctionne, c'est l'env de test seul qui pollue).
- **Confiance** : **0 regression imputable v7.8.0** car le comportement est identique sur la base state pre-session.
