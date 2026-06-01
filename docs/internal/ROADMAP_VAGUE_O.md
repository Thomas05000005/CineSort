# Roadmap Vague O - Performance & infra court-terme

> **Branche** : `fix/v150-batch-bugs`
> **Date** : 2026-06-01
> **Statut** : **NOGO** (mini-recovery doc, sans tag) - corrections requises avant execution
> **Total annonce** : 4 items / 86.25h / 4 sub-lots (somme reelle des lots = 69h, voir section 7)
> **Verdict source** : Workflow Deep (audits VO-1 a VO-4) + Logic adversariel + web research (radarr-custom-formats, sqlite_wal_pragmas_2026, vague_o_parallel_fs_scan, strenum_migration)

---

## 1. Introduction

Apres la Vague N (revisee), la Vague O regroupe **4 chantiers court-terme** centres sur la **performance** et **l'infra technique** :

1. **VO-A** Foundations DB & Storage : profils de pragmas SQLite adaptes au stockage (local SSD / local HDD / NAS SMB / NAS SMB lent), validation terrain et garde-fou NAS.
2. **VO-B** Scan parallel walker : ThreadPoolExecutor sur la phase de discovery (gain x5-x8 sur SMB).
3. **VO-C** Score breakdown waterfall + parite Custom Formats Radarr : exposer dans l'UI les `categories`, `baseline`, `suggestions` et `applied_rule_ids` deja calcules par `explain_score.py` et `custom_rules.py`.
4. **VO-D** Probe `OpType StrEnum` + apply audit (qualite domain) : migration ciblee Python 3.11+ `StrEnum`.

**Mini-recovery NOGO** : la critique adversariale a identifie **plusieurs violations memoire et incoherences serieuses** (voir section 7). Le tag `mini-recovery-o` n'est PAS pose ; ce document sert de socle pour la prochaine revue post-fixes.

---

## 2. Tableau des sub-lots

| lot_id | Titre | Items | Heures | Depends_on |
|--------|-------|-------|--------|------------|
| **VO-A** | Foundations DB & Storage (pragmas profils + NAS validation) | 1 | 26 | - |
| **VO-B** | Scan parallel walker (perf NAS/SMB) | 1 | 22 | VO-A |
| **VO-C** | Score breakdown waterfall + custom formats parite Radarr (UI) | 1 | 13 | - |
| **VO-D** | Probe OpType StrEnum + apply audit (qualite domain) | 1 | 8 | - |
| **TOTAL items** | | **4** | **69h** (somme reelle) / **86.25h** (annonce plan) | |

> **Ecart 17.25h non justifie** par le plan source : overhead docs / tests / integration probable mais non chiffre. A clarifier avant execution.

---

## 3. Items detailles par sub-lot

### VO-A - Foundations DB & Storage - 26h

#### Item VO-2-SQLITE-PRAGMAS-2026

**Backend**
- Nouveau `cinesort/infra/db/pragma_profile.py` (~150 LOC) : `PROFILES = {local_ssd, local_hdd, nas_smb, nas_smb_slow}` + `detect_storage_type()` (UNC path detection, `GetDriveType` via ctypes, fallback heuristique).
- Profil **NAS critique** : `mmap_size=0` (corruption silencieuse SMB confirmee Sonarr #1886), `busy_timeout=30000ms`, `synchronous=FULL`, `wal_autocheckpoint=200`.
- Modifier `cinesort/infra/db/connection.py` : signature retrocompatible `connect_sqlite(db_path, *, busy_timeout_ms=5000, profile=None)` ; chaque PRAGMA en `try/except` dedie + log readback via `get_pragma_snapshot()`.
- Modifier `cinesort/infra/db/sqlite_store.py` : nouveau kwarg `pragma_profile_name`.

**Migration**
- `migrations/028_pragma_history.sql` : ordre `CREATE TABLE -> CREATE INDEX` strict (PAS d'`ALTER TABLE` per `feedback_sqlite_migration_test_existing_db`).
- Test : `existing_db_fixture(target=27)` -> apply 028 + cas profile-switch NAS sur DB v27 pre-existante avec WAL non-checkpointe.

**UI / endpoint**
- `cinesort/ui/api/settings_support.py` : `get/set_advanced_pragma_settings` tri-etat (`auto / local_ssd / nas_smb`).
- Bascule `locking_mode=EXCLUSIVE` : **OBLIGATOIREMENT** via `dangerConfirmModal` avec liste consequences + delai 3s (memoire `feedback_cinesort_actions_dangereuses`). JAMAIS `window.confirm`.

**NAS validation**
- Nouveau `cinesort/infra/db/nas_validation.py` (~200 LOC) : `run_nas_benchmark(n_writes=1000, n_reads=10000)` -> `{p50, p95, p99, wal_growth_kb, checkpoint_count}` exporte JSON dans `state_dir/diagnostics/`.
- Patterns web : `DB_LOCAL_GUARD` bloquer UNC path detecte, `PRAGMA wal_checkpoint(TRUNCATE)` au startup, `PRAGMA optimize` on close (deja en place).

**Acceptance criteria**
- [ ] 4 profils selectionnables + auto-detect fonctionnel.
- [ ] DB sur UNC path -> erreur bloquante au startup (DB_LOCAL_GUARD).
- [ ] Migration 028 testee sur DB v27 pre-existante.
- [ ] Bascule EXCLUSIVE refusee si user clique "Annuler" dans dangerConfirmModal.
- [ ] Benchmark JSON ecrit dans `state_dir/diagnostics/` avec p50/p95/p99 + wal_growth.

---

### VO-B - Scan parallel walker (perf NAS/SMB) - 22h

#### Item VO-3-SCAN-PARALLEL

**Backend**
- Refactor `cinesort/ui/api/plan_support.py::_filter_dossiers_phase` (L718-820, boucle for sequentielle) -> `ThreadPoolExecutor max_workers=32 configurable`.
- Reutiliser `cinesort/domain/perceptual/parallelism.py::run_batch_parallel` (258 LOC, cancel_event + fallback sequentiel + ordre preserve).
- Pattern producteur / consommateur : N workers FS lecture (scandir thread-safe par construction via `iter_videos`) + Queue + 1 writer SQLite dedie (WAL = single writer).
- Connection-per-thread via `threading.local()` + `check_same_thread=False`.

**Synergie VO-A**
- Reutiliser `detect_storage_type()` : NAS -> `max_workers=32-64`, local SSD -> `max_workers=4-8`.
- **NE PAS** migrer vers `python3.13t` (overhead PyInstaller `--onefile` + WebView2 non valide, gain nul I/O-bound).

**Config**
- Ajouter `Config.scan_parallel_enabled` + `Config.scan_parallel_workers` dans `cinesort/domain/core.py` (L210-285).
- `cancel_event` coopere avec `test_pause_cooperative_v77` existant.
- `OSError` resilience SMB disconnect transient (try/except autour `is_dir()` / `stat()`).

**Tests**
- `tests/test_scan_parallel_vo3.py` (mock NAS slow scandir aleatoire).
- `tests/test_scan_writer_queue_vo3.py` (1 writer dedie + batch transactions 2000 rows).
- `tests/test_scan_cancel_vo3.py` (cancel_event mid-scan).
- Pas de migration SQL.

**Acceptance criteria**
- [ ] Gain x5-x8 mesure sur dossier 1000 films via mock NAS slow.
- [ ] Pas de `database is locked` sur 10000 rows batchees.
- [ ] cancel_event arrete les workers en <500ms.
- [ ] Fallback sequentiel si `scan_parallel_enabled=False`.

> **ALERTE critique** : voir section 7 - `_filter_dossiers_phase` mute `ctx.rows`/`ctx.stats`/`folders_seen_for_prune`, appelle `_classify_and_plan_folder` (-> `tmdb.search()` HTTP), emet `progress(idx, discover_total)` strictement ordonne, appelle `wait_while_paused()` et `persist_folder_cache`. Le 22h est massivement sous-estime.

---

### VO-C - Score breakdown waterfall + custom formats parite Radarr (UI) - 13h

#### Item VO-1-SCORE-BREAKDOWN-WATERFALL

**Backend (lecture seule, pas de logique nouvelle)**
- `cinesort/ui/api/dashboard_support.py::_build_row_payload` (L721-774) : injecter `quality_score_explanation_full` dict (categories, baseline, suggestions, applied_rule_ids).
- `cinesort/ui/api/library_support.py::_build_library_rows` (L161) : meme injection.
- Backend `domain/explain_score.py` + `domain/custom_rules.py` DEJA en place depuis Vague J/M.

> **A clarifier** (open question) : le plan parle d'`applied_rules` mais `custom_rules.py::apply_custom_rules` retourne `applied_rule_ids` (pas `applied_rules`). Choisir UNE convention.

**Frontend - nouveau composant**
- Nouveau `web/dashboard/components/score-waterfall.js` (~200 LOC).
- 4 helpers :
  1. `renderScoreWaterfallHtml(explanation)` : bars empilees additives (base + deltas).
  2. `renderCustomFormatsImpact(applied_rules_detail)` : parite Radarr `"CF X +50pts"`.
  3. `renderBaselineGauge(baseline)` : `"X pts du tier Y"`.
  4. `renderSuggestionsList(suggestions)` : actionnable FR.

**CSS - invariants**
- Tier colors HEX **INVARIANTES** : import `var(--tier-platinum/gold/silver/bronze/reject)` depuis `styles.css` existant. AUCUNE redefinition (memoire `feedback_cinesort_v76_ui`).
- Prefix CSS `.score-waterfall-*` **exclusif** (memoire `feedback_js_release_checks` : pas de classe CSS partagee entre composants DOM differents).

**Integration inspecteurs**
- `lib-validation.js::_showInspector` (L370-410) : ajout apres `detail-grid`.
- `lib-verification.js::_showWhyModal` (L198-225) : section "Score breakdown".
- **A revoir** : `perceptual-modal.js::_renderBreakdownSection` (L374-419) - voir section 7, VIOLATION memoire `perceptual_reports != quality_reports`.
- `score-v2.js::renderScoreV2Container` : extension opt `showWaterfall=true`.

**Tests**
- `test_score_breakdown_v77.py` (contrat backend categories/baseline/suggestions/applied_rule_ids, coherence weighted_delta).
- `test_score_waterfall_frontend_v77.py` (data-testid + regex CSS prefix exclusif).
- `test_custom_formats_radarr_parity_v77.py` (joindre `profile.custom_rules` par id, filtrage securitaire).
- Pas d'action destructive -> `dangerConfirmModal` NON APPLICABLE.
- Pas de migration SQL.

**Acceptance criteria**
- [ ] Backend expose `quality_score_explanation_full` dans `_build_row_payload` et `_build_library_rows`.
- [ ] Waterfall affichable dans 3 inspecteurs (validation, verification, score-v2).
- [ ] Tier colors HEX inchangees (test regression visuel).
- [ ] CSS prefix `.score-waterfall-*` exclusif valide par grep.

---

### VO-D - Probe OpType StrEnum + apply audit (qualite domain) - 8h

#### Item VO-4-OPTYPE-STRENUM

> **ALERTE** : voir section 7 - le plan reference `RenameOpType` et `op_type RenameProposal` mais `cinesort/domain/probe_models.py` n'a **PAS** d'Enum a migrer (op_type est `str` brut avec constantes `OP_TYPE_RENAME`). Item entierement a recadrer.

**Recadrage propose** (a valider) :
- Soit : creer `RenameOpType(StrEnum)` ex nihilo dans `probe_models.py` (passage `str` -> `StrEnum`) et propager.
- Soit : migrer SEULEMENT les `class Foo(str, Enum)` existants reels du repo (audit ruff `UP042`).

**Synergie**
- `StrEnum` simplifie API JSON facade entre domain/app/ui (50 methodes facade), evite breaking change Python 3.13 (`str(Enum.FOO) == 'MyEnum.FOO'` pour Enum classique vs `'foo'` pour `StrEnum`).

**Verifications**
- `cinesort/app/apply_audit.py` (281 LOC) : aucune ref `RenameOpType|OpType` trouvee (grep 0 match). Item a redefinir.
- `cinesort/infra/probe/normalize.py` (92 LOC post M-04) + sous-modules : impact NUL.

**Tests** (a recadrer)
- `tests/test_optype_strenum_vo4.py` (`isinstance(OpType.MOVE, str)` True, `json.dumps` direct, f-string format).
- `tests/test_apply_audit_strenum_vo4.py` (apply_audit consume RenameProposal nouveau format).
- Architecture import-linter respectee (domain isole).
- Pas de migration SQL.

**Acceptance criteria** (a recadrer)
- [ ] Definir le perimetre exact (introduction OU migration).
- [ ] `ruff UP042` clean sur perimetre cible.
- [ ] Tests `StrEnum` serialisation JSON / f-string verts.

---

## 4. Convergences Deep + Logic + Web Research

Les **4 convergences principales** qui justifient la Vague O :

1. **VO-1 + WEB radarr-custom-formats** : backend CineSort a **DEJA** `explain_score.py` (factors enrichis, baseline, suggestions) + `custom_rules.py` (17 fields, 11 operators, 7 actions, parite Radarr). **Gap = UI uniquement**. La recherche web confirme que MEME Radarr/Sonarr echouent a exposer le score breakdown des fichiers existants (Sonarr Issue #4693 closed not planned). **Opportunite produit nette** : waterfall additif visuel + custom formats impact panel = differenciateur.

2. **VO-2 + WEB sqlite_wal_pragmas_2026** : convergence FORTE sur 8 points :
   - WAL + `synchronous=NORMAL` est sweet spot.
   - `busy_timeout` per-connection 5-30s.
   - `mmap=256MB` safe.
   - **mmap DANGEREUX sur SMB** (corruption silencieuse confirmee Sonarr #1886).
   - DB locale obligatoire jamais sur NAS.
   - `PRAGMA optimize` on close.
   - `wal_checkpoint(TRUNCATE)` au boot.
   - `PRAGMA integrity_check` au boot.
   - **CineSort fait DEJA 7/8** - reste profil NAS-safe + checkpoint(TRUNCATE) explicit + DB_LOCAL_GUARD.

3. **VO-3 + WEB vague_o_parallel_fs_scan** : convergence sur scandir 8-9x faster (deja en place CineSort Phase 1), `ThreadPoolExecutor` I/O-bound ideal 32-64 workers SMB, GIL relache pendant syscalls, pattern producteur / consommateur + 1 writer SQLite dedie + Queue, `OSError` resilience SMB disconnect transient. Pattern `parallelism.py` de perceptual EXISTE deja dans CineSort (`run_batch_parallel`) - reutilisable directement.

4. **VO-4 + WEB strenum_migration** : `StrEnum` (Python 3.11+) elimine `.value`, `ruff UP042` detecte vieux patterns `class Foo(str, Enum)`. Synergie avec normalisation `OpType` deja amorcee. **A recadrer** : verifier d'abord ce qui est reellement migrable dans le repo.

---

## 5. Memoires respectees / a verifier

| Memoire | Lot | Statut |
|---------|-----|--------|
| `feedback_sqlite_migration_test_existing_db` | VO-A | OK : `existing_db_fixture(target=27)` -> apply 028, ordre CREATE TABLE -> CREATE INDEX. |
| `feedback_cinesort_actions_dangereuses` | VO-A | OK : `dangerConfirmModal` + delai 3s + liste consequences pour bascule EXCLUSIVE. |
| `feedback_cinesort_v76_ui` (tier colors invariantes) | VO-C | OK : reutilisation `var(--tier-*)`, AUCUNE redefinition. |
| `feedback_js_release_checks` (pas de classe CSS partagee) | VO-C | OK : prefix `.score-waterfall-*` exclusif. |
| `feedback_cinesort_design` (perceptual_reports != quality_reports) | VO-C | **VIOLATION** : remplacer `perceptual-modal._renderBreakdownSection` par waterfall quality_score melange deux scores distincts. Voir section 7. |
| Architecture import-linter (domain isole) | Tous | OK : `pragma_profile.py` + `nas_validation.py` dans `infra/db`, VO-B place `scan_parallel` dans `plan_support.py` (app). |

---

## 6. Pour toi

Vague O concerne la performance et l'infra : scans plus rapides sur SMB (gain x5-x8 potentiel), affichage transparent des scores (waterfall additif inspire de Radarr), database SQLite optimisee 2026 (WAL pragmas), et typing moderne probe pipeline.

---

## 7. Verdict NOGO - corrections requises avant tag

La revue adversariale (memoire `feedback_sereo_revue_adversaire_iterative` applique a CineSort) a identifie **plusieurs incoherences serieuses** qui interdisent le tag immediat de la Vague O. Conformement a la regle "ecrire le doc avec open_questions, ne pas tagger".

### 7.1 Violations memoire identifiees

**VIOLATION VO-C - memoire `feedback_cinesort_design` (`perceptual_reports != quality_reports`)** :
- `perceptual-modal.js::_renderBreakdownSection` (L374-419) rend le breakdown **PerceptualScore V2** (composantes audio/video/grain/HDR ponderees).
- Le plan veut le REMPLACER par un waterfall du **quality_score** (categories video/audio/extras + custom rules).
- Ce sont deux scores distincts avec deux backends distincts.
- Le "fallback explicite si `d.score_explanation` absent" propose ne resout pas le melange semantique.
- **Action requise** : ne PAS toucher a `perceptual-modal._renderBreakdownSection`. Integrer le waterfall quality_score uniquement dans les inspecteurs qui exposent deja le quality_score (lib-validation, lib-verification, score-v2).

### 7.2 Incoherences factuelles

**VO-C - applied_rules vs applied_rule_ids** :
- Le plan promet `applied_rules/applied_rule_ids` melanges.
- `custom_rules.py::apply_custom_rules` retourne `applied_rule_ids` uniquement.
- `explain_score.py` ne retourne PAS `applied_rules`.
- **Action requise** : trancher (probablement `applied_rule_ids` + lookup cote frontend dans `profile.custom_rules`).

**VO-D - `RenameOpType` inexistant** :
- `cinesort/domain/probe_models.py` L131 `RenameProposal` existe, mais `op_type` est type `str` (L144) avec constantes `OP_TYPE_RENAME = 'RENAME'` (L14-17). **AUCUN Enum/StrEnum a migrer**.
- `cinesort/app/apply_audit.py` (281 LOC) : grep `RenameOpType|OpType` -> **0 match**. Aucune ref `.value` a remplacer.
- **Action requise** : redefinir VO-4. Soit creer ex nihilo, soit changer de cible (audit `ruff UP042` sur tout le repo, perimetre estime 4-5j).

**VO-B - sous-estimation 22h massivement** :
- `_filter_dossiers_phase` n'est PAS une simple "boucle for sequentielle".
- Elle (1) mute `ctx.rows`/`ctx.stats`/`folders_seen_for_prune` en flot, (2) appelle `_classify_and_plan_folder` qui appelle `tmdb.search()` (HTTP, possiblement non thread-safe), (3) emet `progress(idx, discover_total)` UI strictement ordonne, (4) appelle `wait_while_paused()` pause cooperative conceptuellement sequentielle, (5) appelle `persist_folder_cache`.
- **Action requise** : re-budgetiser VO-B (40-60h plus realiste) ou reduire le perimetre (extraire la sous-phase paralelisable uniquement).

**Total arithmetique faux** :
- 26 + 22 + 13 + 8 = **69h** mais plan annonce **86.25h**.
- Ecart de **17.25h non justifie**.
- **Action requise** : justifier (overhead docs/tests/integration ?) ou corriger le total.

### 7.3 Open questions a trancher avant execution

1. **VO-A endpoint settings UI tri-etat `auto/local_ssd/nas_smb`** : exposer aussi `nas_smb_slow` (busy_timeout=30s, synchronous=FULL) ou reserver auto-detect uniquement pour eviter mauvaise config user ?

2. **VO-C backward compat `perceptual-modal._renderBreakdownSection`** : garder l'ancien rendu en fallback explicite (toggle UI) ou ne PAS toucher du tout (recommande, voir 7.1) ?

3. **VO-B scan parallele seuil par defaut `max_workers`** : web recommande 32-64 pour SMB mais CineSort cible aussi local SSD ou 4-8 suffit. Auto-detect via `detect_storage_type()` partage avec VO-A (synergie) ?

4. **VO-D migration StrEnum perimetre** : migrer SEULEMENT `op_type RenameProposal` (perimetre M-05) ou auditer les ~38 enums du projet en une passe (`ruff UP042`) ? Impact effort 1-2j vs 4-5j. **A recadrer** car `RenameOpType` n'existe pas (voir 7.2).

5. **Coordination migrations SQL Vague O** : confirmer 028 reservee VO-2 (`pragma_history`), 029/030 disponibles si VO-3/VO-4 en demandent (a priori NON selon audits). Eviter conflit numerotation.

### 7.4 Plan de remediation propose

1. Recadrer VO-D (definir clairement le perimetre : creation ex nihilo ou migration audit-wide).
2. Recadrer VO-C : enlever `perceptual-modal._renderBreakdownSection` du perimetre.
3. Re-budgetiser VO-B (analyse fine de `_filter_dossiers_phase` -> extraire la sous-phase reellement paralelisable).
4. Trancher `applied_rules` vs `applied_rule_ids`.
5. Justifier ou corriger le total 69h vs 86.25h.
6. Re-soumettre a la revue adversariale, viser GO ou GO_WITH_FIXES.

---

*Document genere en mini-recovery NOGO post-audits Vague O. Tag `mini-recovery-o` NON POSE. A re-soumettre apres remediation des points section 7.*
