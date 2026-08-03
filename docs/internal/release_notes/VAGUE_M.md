# Vague M - Convergence v166 + Cloture #84 (partiel) + Dataclasses Domain

> Date : 2026-06-01
> Branche : `fix/v150-batch-bugs` (HEAD `186688e`)
> Verdict workflow `verify` : **GO_WITH_FIXES**
> Tag git : `vague-m-complete`
> Version : pas de bump (decision differee, voir open_question)

---

## Resume technique

La Vague M referme la convergence post-v166 et termine le decoupage architectural
amorce par les issues #83 (cycle domain<->app) et #84 (god class CineSortApi).

Elle se compose de 9 items (M-00 a M-08), tous **done** sauf M-03 qui reste
**partial** (cloture pragmatique : ~20 lazy imports restants reportes a une
vague dediee).

Trois axes majeurs :

1. **Convergence v166** (M-00, M-01) : inventaire fige de l'arborescence reelle
   post-v166 et tests de regression 1:1 pour les 9 bugs UI critiques corriges
   dans le commit `198a33a` (compteurs Validation, scan 1006->~1300 films,
   apply skip identical, progress bars manquantes, toasts empiles).

2. **Decoupage architectural** (M-04, M-05, M-06, M-07) : extractions ciblees
   sans changement de comportement :
   - `infra/probe/normalize.py` (739 LOC) split en 4 sous-modules + facade
     re-export (M-04).
   - `domain/probe_models.py` etendu avec `ProbeSources`, `RenameProposal`,
     `ProbeResult` (M-05, EXTENSION strict, `NormalizedProbe` inchangee).
   - `domain/tiers_helpers.py` extrait pour centraliser la deduplication
     legacy premium/bon/moyen/faible (M-06).
   - `ui/api/_run_state.py` extrait de `cinesort_api.py` (2823 -> 2668 LOC, M-07).

3. **Outillage et garde-fous** (M-02, M-03, M-08) :
   - Snapshot facades regenere + test `test_no_orphan_impl_method` (M-02).
   - Inventaire des 69 lazy imports residuels + garde-fou
     `MAX_LAZY_IMPORTS=69` (M-03 partial).
   - `pyproject.toml` complete en PEP 621 (deps, dev, build, urls) + audit
     workflows CI (M-08).

**Aucun bump VERSION** : la decision (v1.5.3-beta ? v7.8.0 ?) est reportee
a une question utilisateur ulterieure. Pas de tag `v*.*.*` cree.

---

## Changements par item (M-00 a M-08)

### M-00-SPRINT0-INVENTORY (done) - commit `47622cc`

Sprint 0 anti-NOGO post-v166.

- `docs/internal/inventory_post_v166.md` : inventaire reel de l'arborescence
  (56 domain / 25 app / 45 infra / 45 ui_api / 6 facades / 8 repositories /
  30 views / 34 components / 6 shared / 27 migrations / 343 tests).
- `tests/_helpers.py` : ajoute `existing_db_fixture(target_schema_version)`
  mutualisee pour les futurs items SQLite (memoire user : tester DB pre-existante).
- `tests/test_existing_db_fixture_v77.py` : 6 cas couvrant v0, v5, v27 latest,
  apply next migration, override migrations_dir, dir invalide.
- Decisions tranchees : (a) Playwright -> fallback tests CSS unitaires,
  (b) ESM -> R-02 differe post-ESM.
- Tag git intermediaire `sprint-0-inventory` pose pour revert mecanique.

3 fichiers / +564 LOC.

### M-01-FINISH-V166-BUGS (done) - commit `4d1f96c`

Tests de regression 1:1 pour les 9 bugs corriges dans `198a33a` (fix(ui): v166).

Mapping :
- VAL-1 : dashboard kpis exposent `validated_count` + `rejected_count`
- VAL-2 : pas de `slice(0, 100)` ni `slice(0, 50)` dans Validation/Verification
- VAL-3 : filtres confiance + toggle-reasons + `aria-sort` presents
- APPLY-1 : `_norm_compare` utilise NFC + casefold (smoke test NFD vs NFC)
- APPLY-2 : payload status expose cle `apply` (apply_running/total/done)
- DUP-1 : `doublons.js` expose indicateur d'avancement bulk perceptual
- DUP-2 : `run_flow_support.check_duplicates` fusionne decisions persistees
- SCAN-1 : `VIDEO_EXTS_DEFAULT` contient m4v/mov/wmv/flv/ts/webm (>=10)
- TOAST-1 : `toast.js` utilise `_activeToasts` Map + dedup + max stack

10/10 tests passent. 1 fichier / +258 LOC.

### M-04-PROBE-NORMALIZE-SPLIT (done) - commit `fd305ad`

Decoupe `cinesort/infra/probe/normalize.py` (739 LOC) :

- `_normalize_helpers.py` (139 LOC) : conversions atomiques + selection.
- `_normalize_mediainfo.py` (116 LOC) : extraction MediaInfo.
- `_normalize_ffprobe.py` (264 LOC) : extraction ffprobe + HDR/DV/Atmos.
- `_normalize_merge.py` (206 LOC) : fusion + qualite.
- `normalize.py` (92 LOC) : facade publique + re-export `__all__`.

Deduplication MAINT-DUP-CONVERT : `_to_int` / `_to_float` / `_to_bitrate_int` /
`_bool_from_text` delegueent maintenant aux `to_optional_*` ajoutees dans
`cinesort/domain/conversions.py`.

Signatures publiques inchangees. 8 fichiers / +1161 LOC nets.

### M-06-TIERS-HELPERS-CENTRAL (done) - commit `33a48c6`

Extraction `cinesort/domain/tiers_helpers.py` pour eliminer la duplication
retro-compat legacy (premium/bon/moyen/faible) dispersee dans `quality_score`,
`explain_score` et `calibration`.

API publique :
- `normalize_tiers(dict)`, `normalize_tier_string(raw)`
- `tier_order` / `tier_ordinal`, `tier_label_fr`
- `is_premium_tier`, `tier_min_score`
- `determine_tier`, `cap_tier`

SCORE-01 inclus : `explain_score._compute_baseline` aligne sur defaults v1.5.7
(70/66/55/40) au lieu des defaults legacy (85/68/54/30).

Couleurs hex Platinum/Gold/Silver/Bronze INVARIANTES (memoire user (1)).

7 fichiers / +907 LOC. 47 tests + 74 subtests sur 5 profils legacy pre-v1.5.5.

### M-08-PYPROJECT-DEPS (done) - commit `b64c434`

Migration progressive `requirements*.txt` -> `pyproject.toml [project.dependencies]`
+ audit des CI workflows.

- `[project]` enrichi PEP 621 : name, version (1.5.2-beta), description,
  readme, license MIT, authors (corrige placeholder `<PROJECT_AUTHOR>`),
  `requires-python = "==3.13.*"`, keywords, classifiers.
- `[project.dependencies]` : 8 packages alignes (pywebview, requests, urllib3,
  segno, rapidfuzz, numpy, onnxruntime, zipp).
- `[project.optional-dependencies.dev]` : pytest 9, ruff, coverage, pre-commit,
  playwright, Pillow, hypothesis, import-linter, pytest-cov.
- `[project.optional-dependencies.build]` : pyinstaller, pillow.
- `[project.urls]`, `[build-system]`, `[tool.setuptools]` declares.

3 nouveaux tests (`test_pyproject_pep621_v77`, `test_pip_install_editable_v77`,
`test_ci_workflows_pyproject_compat_v77`) -> 26 OK + 1 skip attendu hors 3.13.

`.gitignore` : `*.egg-info/` ajoute.

### M-05-DOMAIN-DATACLASSES-EXTEND (done) - commit `50046fc`

EXTENSION de `cinesort/domain/probe_models.py`. `NormalizedProbe` strictement
inchangee (back-compat).

Nouveaux types optionnels exposes via `__all__` :

- `ProbeSources` : tracking piste-par-piste (audio/video/subtitles) +
  invariant "at least one source if not manual_override" +
  `merge_audio_track(idx, field, source)`.
- `RenameProposal` : `{src_path, target_path, op_type, no_op, reason,
  confidence, source, alternatives, reasons}` + `to_dict`/`from_dict`
  roundtrip (forward-compat sur champs inconnus).
- `ProbeResult` : wrapper `{normalized, sources, raw_mediainfo, raw_ffprobe}`.

2 fichiers / +416 LOC. 24 tests v77 + 77 tests probe existants verts.

### M-07-RUNSTATE-EXTRACTION (done) - commit `5c45c80`

Extraction de la classe `RunState` (~165 LOC) de `cinesort_api.py` vers
`cinesort/ui/api/_run_state.py`.

- `cinesort_api.py` : 2823 -> 2668 LOC (re-export pour preserver les imports
  historiques : `apply_support`, `run_flow_support`, callers pywebview JS).
- `_env_truthy` duplique localement pour eviter cycle d'import.
- Logique preservee bit-a-bit (lock, `_file_log_lock`, EWMA smoothing,
  window 400 samples, persistance `ui_log.txt` best-effort).

4 fichiers / +534 LOC. 15 nouveaux tests + 23 existants (apply_progress,
vague_h_concurrency) verts.

### M-02-REGEN-SNAPSHOT-FACADES (done) - commit `698fbb5`

Snapshot du contrat des 6 facades CineSortApi + test couverture facade.

- `tests/snapshots/facade_methods_v77.json` :
  - 6 facades (library/quality/run/runtime/settings/integrations)
  - 148 methodes publiques totales sur facades
  - 133 `_impl` methods sur CineSortApi
  - 3 publiques residuelles (log_api_exception, open_path, test_reset)
- `tests/test_facade_coverage_no_orphan_impl_v77.py` :
  - `test_no_orphan_impl_method` : echec si `_X_impl` ajoutee sans facade
    qui la delegate (ARCH-02).
  - `test_no_facade_method_removed` : echec si methode publique retiree
    d'une facade (ARCH-01).
  - `test_no_residual_method_removed`, `test_no_internal_method_exposed_via_facade`.

2 fichiers / +415 LOC. Helper `regenerate_facade_snapshot()` pour rebase
apres modif intentionnelle.

### M-03-FINISH-REFACTOR-84 (partial) - commit `186688e`

Cloture pragmatique du refactor #84 etapes 2-4.

Apres Issue #83 (mai 2026, 150 lazy imports convertis), il restait
**73 lazy imports** residuels, pas les 179 du re-budget pessimiste.

Strategie minimal-viable :
- Inventaire des 69 restants par categorie (deps optionnelles segno/onnxruntime/
  rapidfuzz, cycles intentionnels documentes, platform-specific msvcrt/fcntl,
  endpoints ponctuels avec `# noqa: PLC0415`).
- 4 conversions stdlib safes :
  - `settings_support.py` : `re`, `secrets` -> top-level
  - `quality_simulator_support.py` : `re` -> top-level
  - `migration_manager.py` : `Path` doublon supprime
- Garde-fou `tests/test_refactor_84_progress_v77.py` borne le compte a
  `MAX_LAZY_IMPORTS=69`.

**Status PARTIAL** : les ~20 candidats convertibles restants demandent une
analyse fine du graphe d'imports par cas. Reporte a une Vague N+.

6 fichiers / +235 LOC. 169 tests verts (facades + misc + snapshot + garde-fou).

---

## Tests ajoutes

| Item | Fichier | Cas |
|------|---------|-----|
| M-00 | `tests/test_existing_db_fixture_v77.py` | 6 |
| M-01 | `tests/test_bugfix_v166_regression.py` | 10 |
| M-04 | `tests/test_probe_normalize_split_imports_v77.py` | 5 |
| M-04 | `tests/test_conversions_dedup_with_normalize_v77.py` | 5 |
| M-05 | `tests/test_probe_models_extensions_v77.py` | 24 |
| M-06 | `tests/test_explain_score_aligned_defaults_v77.py` | ~10 |
| M-06 | `tests/test_legacy_profile_pre_v155_v77.py` | ~15 |
| M-06 | `tests/test_tiers_helpers_legacy_alias_v77.py` | ~22 |
| M-07 | `tests/test_run_state_extraction_v77.py` | 15 |
| M-02 | `tests/test_facade_coverage_no_orphan_impl_v77.py` | ~6 |
| M-03 | `tests/test_refactor_84_progress_v77.py` | ~4 |
| M-08 | `tests/test_pyproject_pep621_v77.py` | 14 |
| M-08 | `tests/test_pip_install_editable_v77.py` | 5 |
| M-08 | `tests/test_ci_workflows_pyproject_compat_v77.py` | 7 |

**Total : ~14 nouveaux fichiers de tests, ~148 cas**.

Aucune regression sur les suites existantes (apply_progress, vague_h_concurrency,
probe/normalize/quality_score, facades).

---

## Items reportes (deferred_to)

- **M-03 etapes 2-4 complete** : les ~20 lazy imports residuels qui
  pourraient encore etre convertis (graphe d'imports a analyser cas par cas).
  Reporte a une Vague N+ dediee. Detail dans
  `docs/internal/REFACTOR_PLAN_84.md` section "M-03".
- **Bump VERSION (v1.5.3-beta ? v7.8.0 ?)** : decision differee, voir
  open_question. Pas de tag `v*.*.*` cree dans cette vague.
- **R-02 (port Linux/macOS)** : differe post-ESM (decision M-00).

---

## Pour toi

Cette mise a jour finalise les correctifs des 9 bugs critiques v166
(compteurs validation live, ~300 films supplementaires scannes, plus de
propositions de renommages inutiles, etc) et prepare le terrain pour les
prochaines vagues (controles utilisateur, observabilite). Aucune action
requise de ta part - tout marche pareil mais en mieux.
