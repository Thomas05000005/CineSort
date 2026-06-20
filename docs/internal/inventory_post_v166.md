# Inventaire post-v166 (Sprint 0 Vague M)

> Date : 2026-05-31
> Item : M-00-SPRINT0-INVENTORY (Vague M)
> Source : recovery workflow w2rozrg13 + verifications FS directes
> Branche : `fix/v150-batch-bugs` (HEAD `198a33a`)
> Version courante : `1.5.2-beta`

Ce document fige l'etat reel de l'arborescence CineSort AVANT le refactor Vague M.
Il sert de reference pour tous les items ulterieurs (M-01..M-08, N, O, P, Q, R) :
**aucun chemin n'est considere comme valide s'il ne figure pas ici**.

Memoires utilisateur appliquees au plan derive de cet inventaire :

- (1) Tier colors hex Platinum/Gold/Silver/Bronze INVARIANTES (N-02 R1 ecartee).
- (2) `dangerConfirmModal` systematique (P-10 R1 ecartee).
- (3) Subprocess direct ffprobe/mediainfo (robuste binaires absents).
- (4) Bundle taille non plafonnee (jsdiff embarque, pas DL).
- (5) Migrations SQLite testees DB pre-existante (fixture mutualisee ci-dessous).
- (6) MAJ CLAUDE.md + BILAN_PHASES.md fin de vague.
- (7) Release notes narratives style Sereo + section "Pour toi".
- (8) `node --check` avant release JS.
- (9) Pas de classe CSS partagee entre composants DOM differents.
- (10) Co-Authored-By Claude Opus 4.7 sur chaque commit.

---

## 1. Packages backend `cinesort/`

### 1.1 `cinesort/domain/` — 56 fichiers, 19 454 LOC

Logique metier pure (sans I/O). Sous-packages : `perceptual/`.

Principaux modules :
`probe_models.py`, `quality_score.py`, `run_models.py`, `naming.py`,
`librarian.py`, `release_name_parser.py`, `scene_parser.py`, `runtime_matching.py`,
`duplicate_compare.py`, `duplicate_support.py`, `edition_helpers.py`,
`encode_analysis.py`, `audio_analysis.py`, `calibration.py`, `conversions.py`,
`explain_score.py`, `film_history.py`, `genre_rules.py`, `i18n_messages.py`,
`integrity_check.py`, `custom_rules*.py`, `mkv_title_check.py`, `profile_exchange.py`,
`scan_helpers.py`, `subtitle_helpers.py`, `tv_helpers.py`, `title_*.py`,
`runtime_matching.py`, `core.py`, `_runners.py`.

Cible Vague M :
- `probe_models.py` : EXTENSION dataclasses `ProbeSources` + `RenameProposal` (M-05),
  SANS casser `NormalizedProbe`.
- `naming.py` : split (M-04) — pre-requis dataclasses M-05.
- `run_models.py` : extraction `RunState` (M-07 reevalue 20h).

### 1.2 `cinesort/app/` — 25 fichiers, 8 497 LOC

Couche service / orchestration (subprocess, FS, IO).
`apply_audit.py`, `apply_core.py`, `cleanup.py`, `disk_space_check.py`,
`email_report.py`, `export_support.py`, `jellyfin_sync.py`, `jellyfin_validation.py`,
`job_runner.py`, `move_journal.py`, `move_reconciliation.py`, `notify_service.py`,
`omdb_cross_check.py`, `plan_support.py`, `plugin_hooks.py`, `radarr_sync.py`,
`retention_cleanup.py`, `runtime_probe_check.py`, `updater.py`, `watcher.py`,
`watchlist.py`, helpers `_dir_utils.py`, `_fuzzy_utils.py`, `_path_utils.py`.

Convention `_runtime_` : aucun package `cinesort/runtime/` n'existe.
Tout module futur "runtime" doit aller dans `cinesort/app/` (orchestration)
ou `cinesort/infra/` (I/O), avec convention documentee.

### 1.3 `cinesort/infra/` — 45 fichiers, 12 045 LOC

Acces externes (DB, HTTP, FS, subprocess, OS). Sous-packages : `db/`, `probe/`.

Clients : `jellyfin_client.py`, `radarr_client.py`, `plex_client.py`, `tmdb_client.py`,
`omdb_client.py`.
Infra : `rest_server.py` (1080 LOC, kill switch `CINESORT_REST_LEGACY_PASS1_ENABLED`),
`notifications.py`, `local_secret_store.py`, `single_instance.py`, `state.py`,
`run_id.py`, `_circuit_breaker.py`, `_http_utils.py`, `network_utils.py`,
`subprocess_safety.py`, `fs_safety.py`, `errors.py`, `log_context.py`,
`log_scrubber.py`, `integration_errors.py`.

#### 1.3.1 `cinesort/infra/db/` — repositories en composition (issue #85)

`repositories/` contient **8 repositories** :
`anomaly.py`, `apply.py`, `film_modal.py`, `perceptual.py`, `probe.py`,
`quality.py`, `run.py`, `scan.py` (+ `_base.py`).

`migration_manager.py` applique les SQL par ordre numerique avec :
- transactions explicites (BEGIN..COMMIT) + savepoints par statement
- tolerance idempotence (`duplicate column name`, `already exists`)
- marker `-- @manager: disable_fk` pour migrations qui recreent une table parent
- trace dans `schema_migrations` (cree par migration 012)

#### 1.3.2 `cinesort/infra/probe/`

Backends subprocess directs `ffprobe_backend.py` + `mediainfo_backend.py`
(memoire 3 : pas de wrapper Python). Robuste aux binaires absents
(degradation gracieuse, pas de crash).

### 1.4 `cinesort/ui/api/` — 45 fichiers, 22 923 LOC

Couche pywebview js_api + REST. Architecture facade pattern (issue #84).

#### 1.4.1 Facades — 6 fichiers reels dans `cinesort/ui/api/facades/`

| Facade                  | Attribut `api.X` | Fichier                                       |
|-------------------------|------------------|------------------------------------------------|
| `IntegrationsFacade`    | `integrations`   | `facades/integrations_facade.py`              |
| `LibraryFacade`         | `library`        | `facades/library_facade.py`                   |
| `QualityFacade`         | `quality`        | `facades/quality_facade.py`                   |
| `RunFacade`             | `run`            | `facades/run_facade.py`                       |
| `RuntimeFacade`         | `runtime`        | `facades/runtime_facade.py`                   |
| `SettingsFacade`        | `settings`       | `facades/settings_facade.py`                  |

`facades/__init__.py` ne fournit PAS encore `_FACADE_ATTR_NAMES`
(preconisation ARCH-04 audit : introspection `__all__` au prochain refactor).

#### 1.4.2 Support modules `*_support.py` — 37 fichiers

Glue entre facade et helpers domain/app/infra. Inclut notamment :
`runtime_support.py` (cible O-01/O-05/O-13), `library_support.py` (P-01/P-12),
`apply_support.py`, `quality_support.py`, `probe_support.py`,
`notifications_support.py`, `tmdb_support.py`, `dashboard_support.py`,
`run_flow_support.py`, `run_control_support.py`, `run_read_support.py`,
`run_data_support.py`, `library_actions_support.py`, `library_audit_support.py`,
`library_podiums_support.py`, `library_timeline_support.py`,
`history_support.py`, `film_history_support.py`, `film_support.py`,
`profiles_support.py`, `quality_audit_support.py`, `quality_internal_support.py`,
`quality_profile_support.py`, `quality_report_support.py`,
`quality_simulator_support.py`, `perceptual_support.py`, `settings_support.py`,
`reset_support.py`, `dashboard_cache_support.py`, `demo_support.py`,
`diagnostics_support.py`, `export_support.py`, `docs_whitelist.py`.

Plus `cinesort_api.py` (point d'entree pywebview), `_responses.py`, `_validators.py`.

---

## 2. Frontend `web/`

### 2.1 `web/dashboard/views/` — 30 fichiers, 20 780 LOC

Pages SPA : `accueil.js`, `bibliotheque.js`, `traitement.js`, `qualite.js`,
`doublons.js`, `historique.js`, `film-detail.js`, `parametres.js`,
`logs.js`, `status.js`, `processing.js`, `quality.js`, `quality-simulator.js`,
`quality-simulator.js`, `qij.js`, `custom-rules-editor.js`, `about.js`,
`aide.js`, `help.js`, `login.js`, `demo-wizard.js`, `radarr.js`,
`plex.js`, `jellyfin.js`, helpers `_v5_helpers.js`.

Sous-package `web/dashboard/views/library/` — 6 fichiers, 1 863 LOC :
`lib-validation.js`, `lib-verification.js`, `lib-apply.js`, `lib-analyse.js`,
`lib-duplicates.js`, `lib-shared.js`.

> Vague Q migre `library/` legacy IIFE vers ESM + ajoute diff jsdiff
> (PAS de nouvelle vue from scratch).

### 2.2 `web/dashboard/components/` — 34 fichiers, 7 738 LOC

`activity-feed.js`, `auto-tooltip.js`, `badge.js`, `breadcrumb.js`,
`command-palette.js`, `confetti.js`, `copy-to-clipboard.js`,
`duplicate-comparator-modal.js`, `empty-state.js`, `film-detail.js`,
`glossary-tooltip.js`, `home-charts.js`, `home-widgets.js`, `kpi-card.js`,
`library-advanced-drawer.js`, `library-podiums.js`, `library-timeline.js`,
`modal.js`, `notification-center.js`, `omdb-status.js`, `perceptual-modal.js`,
`qualite-filters-drawer.js`, `right-panel.js`, `score-v2.js`,
`scraping-status.js`, `services-grid.js`, `shortcut-tooltip.js`,
`sidebar-v5.js`, `skeleton.js`, `sparkline.js`, `table.js`, `toast.js`,
`top-bar-v5.js`, `virtual-table.js`.

Conflits parallel-safe (cf. cross-cutting concern 5) : `modal.js` (N-04/P-11),
`toast.js` (N-06/P-07/Q-04), `runtime-pulse-poller.js` a creer (O-05/O-07).

### 2.3 `web/shared/` — 6 fichiers, 10 896 LOC

`tokens.css`, `themes.css`, `components.css` (9 697 LOC monolithique,
**R-02 differe post-ESM**), `utilities.css`, `animations.css`,
`typography.css`, + sous-dossier `fonts/`.

---

## 3. Tests `tests/`

343 fichiers `test_*.py` (recovery `tests=19` correspondait aux groupes
historiques ; le compte actuel reel est de 343 fichiers depuis #86).
1 helper partage : `tests/_helpers.py` (`find_free_port`, `create_file`,
`wait_run_done`).

Cible Vague M : EXTENSION `_helpers.py` avec `existing_db_fixture(schema_version)`
(mutualisee par P-04 undo, P-05 quarantine 030, O-06 timeline 028, R-04 HDR).

---

## 4. Migrations SQL `cinesort/infra/db/migrations/`

27 migrations ordonnees (001..027) :

| Version | Fichier                                  | Theme                                        |
|--------:|------------------------------------------|----------------------------------------------|
| 001     | `001_init_runs_errors.sql`               | Tables `runs` + `errors` initiales           |
| 002     | `002_probe_cache.sql`                    | Cache probe                                  |
| 003     | `003_quality_score_tables.sql`           | Tables `quality_reports` + `quality_score`   |
| 004     | `004_anomalies_table.sql`                | Anomalies                                    |
| 005     | `005_apply_undo_journal.sql`             | Undo apply (apply_batches / apply_operations)|
| 006     | `006_incremental_scan_cache.sql`         | Cache scan incremental                       |
| 007     | `007_undo_v5_row_id.sql`                 | Colonne `row_id` undo                        |
| 008     | `008_incr_row_cache.sql`                 | Cache row incremental                        |
| 009     | `009_perceptual_reports.sql`             | Rapports perceptuels                         |
| 010     | `010_add_missing_indexes.sql`            | Indexes manquants                            |
| 011     | `011_rename_tiers.sql`                   | Renommage tiers                              |
| 012     | `012_schema_history.sql`                 | Table `schema_migrations`                    |
| 013     | `013_apply_ops_checksum.sql`             | Checksum apply ops                           |
| 014     | `014_user_quality_feedback.sql`          | Feedback utilisateur qualite                 |
| 015     | `015_audio_fingerprint.sql`              | Empreinte audio                              |
| 016     | `016_audio_spectral.sql`                 | Spectral audio                               |
| 017     | `017_ssim_self_ref.sql`                  | SSIM ref                                     |
| 018     | `018_global_score_v2.sql`                | Score global v2                              |
| 019     | `019_apply_pending_moves.sql`            | Apply pending moves                          |
| 020     | `020_quality_reports_perf_indexes.sql`   | Index perf quality reports                   |
| 021     | `021_fk_cascade.sql`                     | FK cascade                                   |
| 022     | `022_drop_redundant_indexes.sql`         | Drop indexes redondants                      |
| 023     | `023_film_modal_state.sql`               | Etat modal film (`-- @manager: disable_fk`)  |
| 024     | `024_duplicate_decisions.sql`            | Decisions doublons                           |
| 025     | `025_run_pause_status.sql`               | Statut pause run                             |
| 026     | `026_self_healing_023.sql`               | Self-healing post-023                        |
| 027     | `027_self_healing_023_v2.sql`            | Self-healing v2                              |

Migrations a venir (planifiees) :
- **028** : `028_timeline_events.sql` (O-06)
- **029** : ALTER `apply_operations ADD COLUMN committed_at TIMESTAMP` (P-04 EXTEND 005)
- **030** : `030_quarantine_viewer.sql` (P-05)

Ordre strict CREATE TABLE -> ALTER TABLE -> CREATE INDEX, idempotence
`IF NOT EXISTS` systematique. Chaque migration testee :
- DB fresh (apply complet 001..N)
- DB pre-existante (apply ancien -> nouvelles seulement)
- Re-run (idempotence 2eme startup)

---

## 5. Decisions Sprint 0 (open_questions tranchees)

### 5.1 DECISION PLAYWRIGHT VISUAL REGRESSION

**Open_question :** R1 R-09 propose 16h Chrome stable + snapshots themes.
Infra actuellement bloquee (WebView2).

**Decision plan actuel (par defaut) : (b) FALLBACK TESTS CSS UNITAIRES**.

- Pas de debloquage infra Playwright en Vague M.
- A la place : tests CSS unitaires en Vague N :
  - `grep` hex tier-colors hardcoded != tokens autorises.
  - `grep` `z-index` hardcoded hors tokens.
  - Snapshots JSON par theme par composant.
- Etendu a P-09 EXTRA visuels : `test_extra_themes_invariance_v77.py`.
- Bascule possible vers (a) si infra debloquee sous 8h (gain +16h).

### 5.2 DECISION ESM MIGRATION

**Open_question :** R-02 (split `components.css` 9 697 LOC) AVANT migration
ESM (Option B refonte 2026-05) = cimente legacy.

**Decision plan actuel : R-02 DIFFERE POST-ESM**.

- Vague R contient seulement consolidation tooltip / icons / overlay sans
  toucher au monolithe CSS.
- Vague S future (~30-40h) sera dediee a la migration ESM, AVANT toute
  reorganisation de `components.css`.
- Memoire `project_cinesort_refonte_ui_2026_05` respectee.

---

## 6. Fixture `tests/_helpers.py::existing_db_fixture`

Ajout Sprint 0 (memoire 5) : helper mutualise pour tester migrations
sur DB pre-existante. Signature :

```python
def existing_db_fixture(target_schema_version: int) -> tuple[Path, sqlite3.Connection]:
    """Cree une SQLite vierge, applique migrations 001..N <= target_schema_version,
    retourne (path tempfile, connexion ouverte).

    Reutilise MigrationManager du repo (cinesort.infra.db.migration_manager).
    Le caller est responsable de fermer la connexion / supprimer le fichier.
    """
```

Reutilise par : P-04 (undo extend 005), P-05 (quarantine 030), O-06 (timeline 028),
R-04 (HDR structured), plus tout futur test SQL.

---

## 7. Tag git intermediaire

`sprint-0-inventory` pose sur le commit du present document + fixture mutualisee.
Permet revert mecanique `git reset --hard sprint-0-inventory` si refactor M
casse l'integration.

---

## 8. Recapitulatif numerique

| Couche / package                         | Fichiers | LOC      |
|------------------------------------------|---------:|---------:|
| `cinesort/domain/`                       |       56 |  19 454  |
| `cinesort/app/`                          |       25 |   8 497  |
| `cinesort/infra/`                        |       45 |  12 045  |
| `cinesort/ui/api/`                       |       45 |  22 923  |
| `cinesort/ui/api/facades/` (sous-total)  |        6 |    -     |
| `cinesort/infra/db/repositories/`        |        8 |    -     |
| `web/dashboard/views/`                   |       30 |  20 780  |
| `web/dashboard/views/library/`           |        6 |   1 863  |
| `web/dashboard/components/`              |       34 |   7 738  |
| `web/shared/`                            |        6 |  10 896  |
| `tests/test_*.py`                        |      343 |    -     |
| `cinesort/infra/db/migrations/*.sql`     |       27 |    -     |

> Source : `git log -1 198a33a` (HEAD au moment de l'inventaire), `os.walk` Python.
> Toute divergence ulterieure doit etre justifiee par un commit explicite.
