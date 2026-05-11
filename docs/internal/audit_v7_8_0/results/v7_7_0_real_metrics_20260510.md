# CineSort — Mesures objectives codebase

**Date** : 2026-05-10 23:14:38
**Branche** : polish_total_v7_7_0
**Commit** : `9d2acff`
**Python** : 3.13.13

Script : `scripts/measure_codebase_health.py` — reproductible cross-machine.

---

## Taille codebase

| Métrique | Valeur |
|----------|--------|
| Fichiers Python (cinesort/) | 139 |
| LOC Python total | 47,049 |
| Fichiers JS (web/) | 124 |
| LOC JS total | 32,372 |
| Fichiers Python > 500L | 23 |
| Migrations SQL | 21 |
| Composants JS dupliqués (desktop ↔ dashboard) | 22 |

## Tests

| Métrique | Valeur |
|----------|--------|
| Fonctions test_* totales | 4187 |
| Tests skip cumulés (@skip / @unittest.skip) | 31 |

### Raisons de skip les plus fréquentes

| Raison (extrait) | Occurrences |
|------------------|-------------|
| `V5C-01: dashboard/views/status.js supprime — adaptation v5 d` | 8 |
| `V5C-01: dashboard/views/review.js supprime — adaptation v5 d` | 7 |
| `V5C-01: dashboard/views/review.js supprime (remplace par pro` | 2 |
| `V5C-01: dashboard/views/quality.js supprime — editeur custom` | 1 |
| `V5C-01: dashboard/views/quality.js supprime — la vue Qualite` | 1 |
| `V5C-01: dashboard/views/settings.js supprime — settings v5 p` | 1 |
| `V5C-01: dashboard/views/help.js supprime — la vue Aide est d` | 1 |
| `V5C-01: dashboard/views/help.js supprime — la vue Aide dashb` | 1 |
| `V5B-01: sidebar v5 rendue dynamiquement par sidebar-v5.js, p` | 1 |
| `V5C-01: dashboard/views/help.js supprime — desktop et dashbo` | 1 |
| `V5C-01: dashboard/views/quality.js supprime — bouton simulat` | 1 |
| `V5C-01: dashboard/views/library/ supprime — score V2 desorma` | 1 |
| `V5C-01: dashboard/views/help.js supprime — vue Aide portee e` | 1 |

## Qualité (Ruff)

Comptés en activant **uniquement** la règle (config actuelle ignore probablement) :

| Règle Ruff | Description | Violations |
|------------|-------------|------------|
| `BLE001` | blind except (`except Exception`) | 11 |
| `PLR2004` | magic value comparison | 276 |
| `PLR0913` | too many arguments (>5) | 120 |
| `C901` | complexity > 10 | 86 |
| `SIM105` | try/except/pass → suppress | 20 |
| `ARG001` | argument inutilisé | 35 |
| `B007` | variable de boucle inutilisée | 3 |
| `RUF100` | `# noqa` inutile | 23 |

## Anti-patterns mesurés par AST

| Métrique | Valeur |
|----------|--------|
| `except Exception` / bare except | **28** |
| Fonctions > 100L | **49** |
| Fonctions > 150L | **17** |
| Fonctions avec ≥ 10 paramètres | **30** |
| Imports lazy (`import cinesort.X` indenté) | **161** |
| `console.log` actifs (web/, hors preview) | **22** |

### Top 15 fonctions > 150L

| Fichier | Fonction | Ligne | Longueur |
|---------|----------|-------|----------|
| `cinesort/ui/api/perceptual_support.py` | `_execute_perceptual_analysis` | 115 | **309L** |
| `cinesort/app/apply_core.py` | `apply_rows` | 779 | **271L** |
| `cinesort/ui/api/dashboard_support.py` | `_build_dashboard_section` | 124 | **241L** |
| `cinesort/ui/api/apply_support.py` | `_execute_apply` | 1028 | **227L** |
| `cinesort/ui/api/apply_support.py` | `_execute_undo_ops` | 279 | **207L** |
| `cinesort/app/plan_support.py` | `_plan_item` | 1515 | **182L** |
| `cinesort/domain/quality_score.py` | `compute_quality_score` | 1255 | **181L** |
| `cinesort/ui/api/settings_support.py` | `apply_settings_defaults` | 553 | **180L** |
| `cinesort/domain/librarian.py` | `generate_suggestions` | 25 | **178L** |
| `cinesort/domain/quality_score.py` | `_score_video` | 444 | **178L** |
| `cinesort/domain/perceptual/audio_perceptual.py` | `analyze_audio_perceptual` | 305 | **169L** |
| `cinesort/ui/api/quality_report_support.py` | `get_quality_report` | 140 | **162L** |
| `cinesort/app/apply_core.py` | `move_file_with_collision_policy` | 478 | **153L** |
| `cinesort/ui/api/perceptual_support.py` | `_video_task` | 152 | **153L** |
| `cinesort/ui/api/apply_support.py` | `apply_changes` | 1631 | **152L** |

### Top 20 fonctions > 100L

| Fichier | Fonction | Ligne | Longueur |
|---------|----------|-------|----------|
| `cinesort/ui/api/perceptual_support.py` | `_execute_perceptual_analysis` | 115 | 309L |
| `cinesort/app/apply_core.py` | `apply_rows` | 779 | 271L |
| `cinesort/ui/api/dashboard_support.py` | `_build_dashboard_section` | 124 | 241L |
| `cinesort/ui/api/apply_support.py` | `_execute_apply` | 1028 | 227L |
| `cinesort/ui/api/apply_support.py` | `_execute_undo_ops` | 279 | 207L |
| `cinesort/app/plan_support.py` | `_plan_item` | 1515 | 182L |
| `cinesort/domain/quality_score.py` | `compute_quality_score` | 1255 | 181L |
| `cinesort/ui/api/settings_support.py` | `apply_settings_defaults` | 553 | 180L |
| `cinesort/domain/librarian.py` | `generate_suggestions` | 25 | 178L |
| `cinesort/domain/quality_score.py` | `_score_video` | 444 | 178L |
| `cinesort/domain/perceptual/audio_perceptual.py` | `analyze_audio_perceptual` | 305 | 169L |
| `cinesort/ui/api/quality_report_support.py` | `get_quality_report` | 140 | 162L |
| `cinesort/app/apply_core.py` | `move_file_with_collision_policy` | 478 | 153L |
| `cinesort/ui/api/perceptual_support.py` | `_video_task` | 152 | 153L |
| `cinesort/ui/api/apply_support.py` | `apply_changes` | 1631 | 152L |
| `cinesort/ui/api/dashboard_support.py` | `get_global_stats` | 1150 | 152L |
| `cinesort/ui/api/apply_support.py` | `build_apply_preview` | 1848 | 151L |
| `cinesort/ui/api/run_flow_support.py` | `_build_plan_job_fn` | 324 | 148L |
| `cinesort/app/job_runner.py` | `_run_worker` | 186 | 144L |
| `cinesort/ui/api/apply_support.py` | `_summarize_apply` | 1348 | 143L |

### Top 15 fonctions à paramètres nombreux (≥ 10)

| Fichier | Fonction | Ligne | Params |
|---------|----------|-------|--------|
| `cinesort/app/plan_support.py` | `_build_resolved_row` | 1311 | 20 |
| `cinesort/domain/quality_score.py` | `_build_quality_metrics_helper` | 1173 | 19 |
| `cinesort/app/plan_support.py` | `_build_unresolved_row` | 1194 | 17 |
| `cinesort/infra/db/_perceptual_mixin.py` | `upsert_perceptual_report` | 19 | 17 |
| `cinesort/app/apply_core.py` | `apply_single` | 1052 | 15 |
| `cinesort/app/apply_core.py` | `apply_collection_item` | 1178 | 15 |
| `cinesort/domain/perceptual/comparison.py` | `extract_aligned_frames` | 32 | 14 |
| `cinesort/app/plan_support.py` | `_plan_item` | 1515 | 13 |
| `cinesort/ui/api/apply_support.py` | `_execute_apply` | 1028 | 13 |
| `cinesort/ui/api/apply_support.py` | `_summarize_apply` | 1348 | 13 |
| `cinesort/app/apply_core.py` | `move_file_with_collision_policy` | 478 | 12 |
| `cinesort/app/apply_core.py` | `merge_dir_safe` | 633 | 12 |
| `cinesort/app/plan_support.py` | `_plan_single` | 1699 | 12 |
| `cinesort/app/plan_support.py` | `_plan_collection_item` | 1731 | 12 |
| `cinesort/domain/core.py` | `build_plan_note` | 943 | 12 |

### Sites `except Exception` (top 20 par fichier)

| Fichier | Occurrences |
|---------|-------------|
| `cinesort/ui/api/apply_support.py` | 6 |
| `cinesort/app/job_runner.py` | 3 |
| `cinesort/app/move_reconciliation.py` | 3 |
| `cinesort/ui/api/runtime_support.py` | 3 |
| `cinesort/ui/api/cinesort_api.py` | 3 |
| `cinesort/app/move_journal.py` | 2 |
| `cinesort/app/jellyfin_sync.py` | 1 |
| `cinesort/infra/errors.py` | 1 |
| `cinesort/infra/fs_safety.py` | 1 |
| `cinesort/infra/rest_server.py` | 1 |
| `cinesort/ui/api/reset_support.py` | 1 |
| `cinesort/infra/db/connection.py` | 1 |
| `cinesort/infra/db/sqlite_store.py` | 1 |
| `cinesort/domain/perceptual/lpips_compare.py` | 1 |

### Fichiers Python > 500L (top 25)

| Fichier | LOC |
|---------|-----|
| `cinesort/ui/api/cinesort_api.py` | 2178 |
| `cinesort/ui/api/apply_support.py` | 1999 |
| `cinesort/app/plan_support.py` | 1985 |
| `cinesort/ui/api/settings_support.py` | 1480 |
| `cinesort/domain/core.py` | 1471 |
| `cinesort/app/apply_core.py` | 1466 |
| `cinesort/domain/quality_score.py` | 1436 |
| `cinesort/ui/api/dashboard_support.py` | 1374 |
| `cinesort/infra/rest_server.py` | 1041 |
| `cinesort/ui/api/run_flow_support.py` | 878 |
| `cinesort/infra/tmdb_client.py` | 812 |
| `cinesort/ui/api/perceptual_support.py` | 776 |
| `cinesort/domain/perceptual/composite_score_v2.py` | 761 |
| `cinesort/domain/perceptual/audio_perceptual.py` | 700 |
| `cinesort/domain/perceptual/hdr_analysis.py` | 655 |
| `cinesort/domain/perceptual/constants.py` | 620 |
| `cinesort/domain/perceptual/video_analysis.py` | 618 |
| `cinesort/ui/api/library_support.py` | 611 |
| `cinesort/infra/probe/normalize.py` | 601 |
| `cinesort/infra/probe/tools_manager.py` | 555 |
| `cinesort/domain/perceptual/mel_analysis.py` | 539 |
| `cinesort/domain/perceptual/grain_analysis.py` | 537 |
| `cinesort/domain/perceptual/grain_classifier.py` | 507 |

### Composants JS dupliqués (présents desktop ET dashboard)

- `auto-tooltip.js`
- `badge.js`
- `breadcrumb.js`
- `command-palette.js`
- `confetti.js`
- `copy-to-clipboard.js`
- `empty-state.js`
- `home-charts.js`
- `home-widgets.js`
- `kpi-card.js`
- `library-components.js`
- `modal.js`
- `notification-center.js`
- `score-v2.js`
- `scraping-status.js`
- `sidebar-v5.js`
- `skeleton.js`
- `sparkline.js`
- `table.js`
- `toast.js`
- `top-bar-v5.js`
- `virtual-table.js`

## Reproduction

```bash
python scripts/measure_codebase_health.py --output audit/results/v7_X_Y_real_metrics.md
```
