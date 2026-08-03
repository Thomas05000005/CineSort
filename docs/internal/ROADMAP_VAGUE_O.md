# Roadmap Vague O - Performance & infra court-terme

> **Branche** : `fix/v150-batch-bugs`
> **Date** : 2026-06-01
> **Statut** : **GO_WITH_FIXES (R2)** - remediations NOGO R1 appliquees, en attente revue adversariale R2
> **Total revise** : 4 items / **77h reel** + **19.25h buffer integration (25%)** = **96.25h** ceiling
> **Verdict source** : Workflow Deep (audits VO-1 a VO-4) + Logic adversariel R1 (NOGO) + remediations R2 (ce doc)

---

## 1. Introduction

Apres la Vague N (revisee), la Vague O regroupe **4 chantiers court-terme** centres sur la **performance** et **l'infra technique** :

1. **VO-A** Foundations DB & Storage : profils de pragmas SQLite adaptes au stockage (local SSD / local HDD / NAS SMB / NAS SMB lent), validation terrain et garde-fou NAS.
2. **VO-B** Scan parallel walker (perimetre reduit) : ThreadPoolExecutor uniquement sur la sous-phase FS locale (scandir + extraction metadata locale) AVANT l'appel `tmdb.search()`. La phase TMDb + progress UI reste sequentielle.
3. **VO-C** Score breakdown waterfall + parite Custom Formats Radarr : exposer dans l'UI le `quality_score_explanation_full` deja calcule par `explain_score.py` et `custom_rules.py`. Integration **uniquement** dans `lib-validation.js`, `lib-verification.js`, `score-v2.js` (qui montrent deja le `quality_score`). `perceptual-modal.js` **HORS perimetre** (memoire `feedback_cinesort_design`).
4. **VO-D** Probe `OpType StrEnum` (ex nihilo) : creer un `StrEnum OpType` dans `probe_models.py` et migrer les ~10-20 call-sites des constantes `OP_TYPE_RENAME/MOVE/...` vers `OpType.RENAME/MOVE/...`. Pas d'audit `ruff UP042` repo-wide (hors scope).

**Statut R2** : la critique adversariale R1 (section 7) a identifie 5 motifs NOGO ; ce document applique les remediations correspondantes et passe en **GO_WITH_FIXES**. Le tag `mini-recovery-o` reste **NON POSE** jusqu'a revue adversariale R2.

---

## 2. Tableau des sub-lots (revises R2)

| lot_id | Titre | Items | Heures reelles | Depends_on |
|--------|-------|-------|----------------|------------|
| **VO-A** | Foundations DB & Storage (pragmas profils + NAS validation) | 1 | 26 | - |
| **VO-B** | Scan parallel walker - sous-phase FS locale uniquement (perf NAS/SMB) | 1 | **30** (revise R2, ex 22) | VO-A |
| **VO-C** | Score breakdown waterfall + custom formats parite Radarr (UI, perimetre reduit) | 1 | 13 | - |
| **VO-D** | Probe OpType StrEnum ex nihilo (qualite domain) | 1 | 8 | - |
| **SOUS-TOTAL items** | | **4** | **77h reel** | |
| **Buffer integration 25%** | docs / tests d'integration croises / smoke E2E / regression | - | **+19.25h** | - |
| **TOTAL ceiling annonce** | | **4** | **96.25h** | |

**Arithmetique R2** : 26 + 30 + 13 + 8 = **77h reel**. Buffer 25% (= 19.25h) couvre docs internes, tests d'integration croises (VO-A + VO-B synergie `detect_storage_type`), smoke E2E, regression visuelle tier colors. Ecart documente : ne plus annoncer 86.25h, ceiling officiel = **96.25h** dont 19.25h buffer.

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
- [ ] Migration 028 testee sur DB v27 pre-existante (via `existing_db_fixture`).
- [ ] Bascule EXCLUSIVE refusee si user clique "Annuler" dans dangerConfirmModal.
- [ ] Benchmark JSON ecrit dans `state_dir/diagnostics/` avec p50/p95/p99 + wal_growth.

---

### VO-B - Scan parallel walker (sous-phase FS locale uniquement) - 30h (revise R2)

#### Item VO-3-SCAN-PARALLEL

**Recadrage R2** : l'audit R1 a montre que `_filter_dossiers_phase` (`cinesort/app/plan_support.py` L718-820) ne peut PAS etre paralelisee dans son ensemble car elle mute `ctx.rows/stats/folders_seen`, appelle `tmdb.search()` (HTTP, ordre TMDb non thread-safe), emet `progress(idx, discover_total)` strictement ordonne, appelle `wait_while_paused()` (cooperatif sequentiel) et `persist_folder_cache`.

**Sous-phase reellement paralelisable** : la **lecture FS locale** (scandir + extraction metadata locale via `iter_videos`/`extract_local_metadata`) **AVANT** l'appel `tmdb.search()`. Cette sous-phase est I/O-bound pure (GIL relache pendant syscalls SMB), sans mutation d'etat partage, sans ordre UI requis (resultats agreges puis traites sequentiellement ensuite).

**Backend**
- Refactor `_filter_dossiers_phase` : decouper en 2 phases :
  - **Phase 1 (parallele)** : `ThreadPoolExecutor max_workers=32 configurable` sur la lecture FS + extraction metadata locale. Resultats agreges dans une liste ordonnee par dossier path.
  - **Phase 2 (sequentielle, inchangee)** : iteration sur la liste agregee, `_classify_and_plan_folder` -> `tmdb.search()`, `progress(idx, discover_total)`, mutation `ctx.rows/stats`, `wait_while_paused()`, `persist_folder_cache`.
- Reutiliser `cinesort/domain/perceptual/parallelism.py::run_batch_parallel` (258 LOC) pour la Phase 1 uniquement : cancel_event + fallback sequentiel + ordre preserve.
- Pas de writer SQLite parallele : la phase 2 reste single-threaded (WAL = single writer respecte).
- `OSError` resilience SMB disconnect transient (try/except autour `is_dir()` / `stat()` dans Phase 1).

**Synergie VO-A**
- Reutiliser `detect_storage_type()` : NAS -> Phase 1 `max_workers=32-64`, local SSD -> `max_workers=4-8`.
- **NE PAS** migrer vers `python3.13t` (overhead PyInstaller `--onefile` + WebView2 non valide, gain nul I/O-bound).

**Config**
- Ajouter `Config.scan_parallel_enabled` + `Config.scan_parallel_workers` dans `cinesort/domain/core.py` (L210-285).
- `scan_parallel_enabled=False` -> fallback sequentiel pur (Phase 1 inlinee dans Phase 2).
- `cancel_event` coopere avec `test_pause_cooperative_v77` existant.

**Tests**
- `tests/test_scan_parallel_vo3.py` (mock NAS slow scandir aleatoire, mesure gain Phase 1 seule).
- `tests/test_scan_phase2_sequential_vo3.py` (verifie que Phase 2 reste sequentielle : ordre `progress(idx, discover_total)` + mutation `ctx.rows` deterministe).
- `tests/test_scan_cancel_vo3.py` (cancel_event arrete les workers Phase 1 en <500ms).
- `tests/test_scan_fallback_sequential_vo3.py` (`scan_parallel_enabled=False` -> aucun ThreadPoolExecutor cree).
- `tests/test_scan_benchmark_vo3.py` (mesure gain x5-x8 sur Phase 1 mock NAS, vs total scan).
- Pas de migration SQL.

**Acceptance criteria**
- [ ] Gain x5-x8 mesure **sur Phase 1 seule** (lecture FS) via mock NAS slow.
- [ ] Phase 2 (TMDb + progress + ctx mutation) reste sequentielle et deterministe.
- [ ] Pas de `database is locked` : aucun writer SQLite parallele introduit.
- [ ] cancel_event arrete les workers Phase 1 en <500ms.
- [ ] Fallback sequentiel pur si `scan_parallel_enabled=False`.
- [ ] Benchmark documente le gain total scan (Phase 1 + Phase 2) realiste (typiquement x2-x3 end-to-end car TMDb domine sur petits scans).

**Budget revise** : 30h = 8h analyse fine `_filter_dossiers_phase` + decoupage Phase 1/Phase 2 + 8h implementation ThreadPoolExecutor + connection-per-thread non requis + 8h tests (5 tests + benchmark) + 6h integration synergie VO-A + fallback. Plus realiste que les 22h initiaux.

---

### VO-C - Score breakdown waterfall + custom formats parite Radarr (UI, perimetre reduit) - 13h

#### Item VO-1-SCORE-BREAKDOWN-WATERFALL

**Recadrage R2** : audit R1 a confirme VIOLATION memoire `feedback_cinesort_design` si on touche `perceptual-modal.js::_renderBreakdownSection`. **Perimetre reduit** : integration **uniquement** dans les 3 inspecteurs qui exposent deja le `quality_score` (et non le `PerceptualScore V2`).

**Backend (lecture seule, pas de logique nouvelle)**
- `cinesort/ui/api/dashboard_support.py::_build_row_payload` (L721-774) : injecter `quality_score_explanation_full` dict (`categories`, `baseline`, `suggestions`, **`applied_rule_ids`**).
- `cinesort/ui/api/library_support.py::_build_library_rows` (L161) : meme injection.
- Backend `domain/explain_score.py` + `domain/custom_rules.py` DEJA en place depuis Vague J/M.

**Fusion backend (contrat d'integration)**
- Le payload `quality_score_explanation_full` est issu d'un appel sequentiel a 2 fonctions backend distinctes :
  1. `domain/explain_score.py::build_rich_explanation(probe, score)` -> dict `{categories, baseline, suggestions, weighted_delta}` (decomposition additive du score baseline + factors).
  2. `domain/custom_rules.py::apply_custom_rules(probe, profile)` -> dict `{applied_rule_ids: List[int], delta: int}` (impact des regles user).
- **Contrat de fusion** : le support layer (`dashboard_support.py` / `library_support.py`) merge ces 2 dicts en un seul payload unifie :
  ```
  quality_score_explanation_full = {
      **build_rich_explanation(probe, score),  # categories, baseline, suggestions
      "applied_rule_ids": apply_custom_rules(probe, profile)["applied_rule_ids"],
  }
  ```
- Aucun nouveau champ backend invente : `applied_rule_ids` est deja produit par `custom_rules.py`, et le lookup nom lisible est cote frontend via `profile.custom_rules` joint par `id` (cf. tranche R2 `applied_rules` vs `applied_rule_ids` ci-dessus).
- L'ordre d'appel est libre (pas de dependance entre les 2 fonctions), mais l'appel doit etre **dans le meme support layer** pour eviter une N+1 query si custom_rules accede a la DB.

**Tranchage `applied_rules` vs `applied_rule_ids` (R2)** : on retient **`applied_rule_ids`** cote backend (deja produit par `custom_rules.py::apply_custom_rules`). Le **lookup nom lisible** se fait cote frontend en joignant `profile.custom_rules` (deja transmis a l'UI via `get_active_profile`) par `id`. Aucun nouveau champ backend a inventer, aucune duplication de donnees.

**Frontend - nouveau composant**
- Nouveau `web/dashboard/components/score-waterfall.js` (~200 LOC).
- 4 helpers :
  1. `renderScoreWaterfallHtml(explanation)` : bars empilees additives (base + deltas).
  2. `renderCustomFormatsImpact(applied_rule_ids, profileRulesById)` : parite Radarr `"CF X +50pts"`, lookup via `profileRulesById[id]`.
  3. `renderBaselineGauge(baseline)` : `"X pts du tier Y"`.
  4. `renderSuggestionsList(suggestions)` : actionnable FR.

**CSS - invariants**
- Tier colors HEX **INVARIANTES** : import `var(--tier-platinum/gold/silver/bronze/reject)` depuis `styles.css` existant. AUCUNE redefinition (memoire `feedback_cinesort_v76_ui`).
- Prefix CSS `.score-waterfall-*` **exclusif** (memoire `feedback_js_release_checks` : pas de classe CSS partagee entre composants DOM differents).

**Integration inspecteurs (perimetre R2)**
- `lib-validation.js::_showInspector` (L370-410) : ajout apres `detail-grid`.
- `lib-verification.js::_showWhyModal` (L198-225) : section "Score breakdown".
- `score-v2.js::renderScoreV2Container` : extension opt `showWaterfall=true`.
- **HORS perimetre R2** : `perceptual-modal.js::_renderBreakdownSection` (L374-419) **NON TOUCHE**. Rend `PerceptualScore V2` (audio/video/grain/HDR ponderes), score distinct du `quality_score` (memoire `feedback_cinesort_design`).

**Tests**
- `test_score_breakdown_v77.py` (contrat backend categories/baseline/suggestions/`applied_rule_ids`, coherence weighted_delta).
- `test_score_waterfall_frontend_v77.py` (data-testid + regex CSS prefix exclusif + test absence dans `perceptual-modal`).
- `test_custom_formats_radarr_parity_v77.py` (joindre `profile.custom_rules` par `id` cote frontend, filtrage securitaire).
- Pas d'action destructive -> `dangerConfirmModal` NON APPLICABLE.
- Pas de migration SQL.

**Acceptance criteria**
- [ ] Backend expose `quality_score_explanation_full` (avec `applied_rule_ids`) dans `_build_row_payload` et `_build_library_rows`.
- [ ] Waterfall affichable dans **3 inspecteurs uniquement** : `lib-validation`, `lib-verification`, `score-v2`.
- [ ] `perceptual-modal.js` **non modifie** (test regression verifie l'absence du waterfall quality_score dans ce composant).
- [ ] Custom formats panel resout nom via `profileRulesById[id]` cote frontend.
- [ ] Tier colors HEX inchangees (test regression visuel).
- [ ] CSS prefix `.score-waterfall-*` exclusif valide par grep.

---

### VO-D - Probe OpType StrEnum ex nihilo (qualite domain) - 8h

#### Item VO-4-OPTYPE-STRENUM

**Recadrage R2** : audit R1 a confirme que **`RenameOpType` n'existe pas** dans le repo. `cinesort/domain/probe_models.py` L14-17 definit des constantes `str` (`OP_TYPE_RENAME='RENAME'`, etc.) et `RenameProposal.op_type: str` L131-144. **0 match** pour `RenameOpType|OpType` dans tout le repo.

**Decision R2 (option a)** : creation **ex nihilo** d'un `class OpType(StrEnum)` dans `probe_models.py` + migration ciblee des ~10-20 call-sites des constantes vers `OpType.RENAME/MOVE/...`. **Pas** d'audit `ruff UP042` repo-wide (4-5j, hors scope, deferre Vague P+).

**Backend**
- `cinesort/domain/probe_models.py` :
  - Nouveau `class OpType(StrEnum)` avec valeurs `RENAME`, `MOVE`, `NOOP` (decision VO-D execution : seules ces 3 valeurs canoniques, alignees sur l'implementation reelle de `probe_models.py` L22-33).
  - Conserver les constantes `OP_TYPE_RENAME = OpType.RENAME` (alias) pour retrocompat pendant la transition.
  - `RenameProposal.op_type: OpType` (typage renforce, retrocompat str preservee car `StrEnum` est `str`).

**Call-sites a migrer (perimetre cible)**
- Grep `OP_TYPE_RENAME|OP_TYPE_MOVE|OP_TYPE_NOOP` dans `cinesort/` -> inventaire ~10-20 sites (constantes alias retrocompat preservees dans `probe_models.py` L60-63).
- Migrer chaque site : `OP_TYPE_RENAME` -> `OpType.RENAME`.
- `cinesort/app/apply_audit.py` (281 LOC) : aucune ref `RenameOpType|OpType` a migrer aujourd'hui, **mais** verifier que la migration des constantes upstream propage bien (apply_audit consomme `RenameProposal.op_type` via comparaisons string).

**Synergie**
- `StrEnum` simplifie API JSON facade entre domain/app/ui (50 methodes facade), evite breaking change Python 3.13 (`str(Enum.FOO) == 'MyEnum.FOO'` pour Enum classique vs `'foo'` pour `StrEnum` - inchange en `StrEnum`).
- `isinstance(OpType.RENAME, str)` True -> serialisation JSON directe sans `.value`.

**Tests**
- `tests/test_optype_strenum_vo4.py` :
  - `isinstance(OpType.RENAME, str)` True.
  - `json.dumps({"op": OpType.RENAME}) == '{"op": "RENAME"}'` direct.
  - f-string `f"{OpType.RENAME}" == "RENAME"`.
  - Constantes alias retrocompat : `OP_TYPE_RENAME == OpType.RENAME == "RENAME"`.
- `tests/test_apply_audit_strenum_vo4.py` : apply_audit consomme `RenameProposal` typage `OpType`, comparaisons string preservees.
- Architecture import-linter respectee (domain isole).
- Pas de migration SQL.

**Acceptance criteria**
- [ ] `class OpType(StrEnum)` cree dans `probe_models.py`.
- [ ] Constantes `OP_TYPE_*` preservees comme alias retrocompat.
- [ ] Tous les call-sites des constantes migres vers `OpType.X` (grep clean apres migration).
- [ ] `apply_audit.py` non casse (tests existants verts).
- [ ] Tests `StrEnum` serialisation JSON / f-string verts.
- [ ] **PAS d'audit ruff UP042 repo-wide** (deferre).

---

## 4. Convergences Deep + Logic + Web Research

Les **4 convergences principales** qui justifient la Vague O (inchangees R2) :

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

4. **VO-4 + WEB strenum_migration** : `StrEnum` (Python 3.11+) elimine `.value`, `ruff UP042` detecte vieux patterns `class Foo(str, Enum)`. **R2** : decision ex nihilo (creer `OpType` dans `probe_models.py`), audit repo-wide deferre.

---

## 5. Memoires respectees / a verifier

| Memoire | Lot | Statut R2 |
|---------|-----|-----------|
| `feedback_sqlite_migration_test_existing_db` | VO-A | OK : `existing_db_fixture(target=27)` -> apply 028, ordre CREATE TABLE -> CREATE INDEX. |
| `feedback_cinesort_actions_dangereuses` | VO-A | OK : `dangerConfirmModal` + delai 3s + liste consequences pour bascule EXCLUSIVE. |
| `feedback_cinesort_v76_ui` (tier colors invariantes) | VO-C | OK : reutilisation `var(--tier-*)`, AUCUNE redefinition. |
| `feedback_js_release_checks` (pas de classe CSS partagee + node --check) | VO-C | OK : prefix `.score-waterfall-*` exclusif. `node --check` avant release. |
| `feedback_cinesort_design` (perceptual_reports != quality_reports) | VO-C | **RESOLU R2** : `perceptual-modal.js::_renderBreakdownSection` retire du perimetre. Waterfall `quality_score` integre UNIQUEMENT dans `lib-validation.js`, `lib-verification.js`, `score-v2.js` (composants exposant deja `quality_score`). PerceptualScore V2 reste isole dans `perceptual-modal`. |
| Subprocess direct ffprobe/mediainfo | Tous | OK : aucun wrapper Python introduit. |
| Bundle taille non prioritaire | Tous | OK : pas d'optimisation taille induite (PyInstaller onefile preserve). |
| Pas de modification titres films | Tous | OK : Vague O ne touche pas le renommage. |
| Architecture import-linter (domain isole) | Tous | OK : `pragma_profile.py` + `nas_validation.py` dans `infra/db`, VO-B place `scan_parallel` dans `plan_support.py` (app), VO-D `OpType` dans `domain/probe_models.py`. |

---

## 6. Pour toi

Vague O concerne la performance et l'infra : scans plus rapides sur SMB (gain x5-x8 sur la phase de lecture des fichiers, x2-x3 sur le scan total car TMDb reste sequentiel), affichage transparent des scores (waterfall additif inspire de Radarr) dans les inspecteurs qualite, database SQLite optimisee 2026 (WAL pragmas adaptes au stockage detecte), et typing moderne du pipeline probe avec `OpType StrEnum`.

---

## 7. Historique remediations R2

Cette section remplace l'ancien "Verdict NOGO" (R1) suite a application des remediations adversariales. Le tag `mini-recovery-o` reste **NON POSE** en attente de revue adversariale R2.

### 7.1 Remediations appliquees

| Motif NOGO R1 | Fix R2 | Section affectee |
|---------------|--------|------------------|
| **VO-C VIOLATION memoire `feedback_cinesort_design`** (waterfall quality_score dans perceptual-modal qui rend PerceptualScore V2) | Perimetre VO-C reduit : `perceptual-modal.js::_renderBreakdownSection` retire du perimetre. Waterfall integre uniquement dans `lib-validation.js`, `lib-verification.js`, `score-v2.js`. Tests verifient l'absence du waterfall dans `perceptual-modal`. | Section 3 VO-C, section 5 |
| **VO-C confusion `applied_rules` vs `applied_rule_ids`** (custom_rules retourne `applied_rule_ids`, explain_score ne retourne pas `applied_rules`) | Tranche : retenir **`applied_rule_ids`** cote backend. Lookup nom lisible cote frontend via `profile.custom_rules` joint par `id`. Aucun nouveau champ backend. | Section 3 VO-C |
| **VO-D `RenameOpType` inexistant** (op_type est str avec constantes, 0 match dans le repo) | Decision option (a) : creation **ex nihilo** de `class OpType(StrEnum)` dans `probe_models.py` + migration ~10-20 call-sites des constantes. Constantes `OP_TYPE_*` preservees comme alias retrocompat. Audit `ruff UP042` repo-wide **deferre** (hors scope, Vague P+). Effort 8h confirme. | Section 3 VO-D |
| **VO-B sous-estimation 22h** (`_filter_dossiers_phase` mute ctx, appelle TMDb HTTP, progress ordonne, wait_while_paused, persist_folder_cache) | Recadrage : extraire UNIQUEMENT la sous-phase paralelisable = **lecture FS locale + extraction metadata locale AVANT `tmdb.search()`** (Phase 1 parallele). Phase 2 (TMDb + progress + ctx mutation + wait_while_paused + persist) reste sequentielle. Gain x5-x8 sur Phase 1 seule, x2-x3 end-to-end realiste. Budget revise **22h -> 30h**. | Section 3 VO-B, section 2 |
| **Total arithmetique faux** (26+22+13+8=69h annonce 86.25h, ecart 17.25h non justifie) | Clarifie : sous-total reel = **77h** (26+30+13+8 apres revision VO-B). Buffer integration documente **+25% = 19.25h** (docs internes, tests d'integration croises, smoke E2E, regression visuelle). Ceiling officiel annonce = **96.25h**. | Section 1, section 2 |

### 7.2 Open questions remaining R2 (a trancher pendant execution)

1. **VO-A endpoint settings UI tri-etat** : exposer aussi `nas_smb_slow` (busy_timeout=30s) ou reserver auto-detect uniquement pour eviter mauvaise config user ? Recommande : auto-detect par defaut + override manuel masque derriere "Advanced" pour utilisateurs avertis.

2. **VO-B max_workers par defaut** : auto-detect via `detect_storage_type()` partage avec VO-A (synergie forte). NAS -> 32, NAS slow -> 16, local SSD -> 8, local HDD -> 4. A valider sur benchmark reel pendant execution.

3. **VO-D inventaire constantes `OP_TYPE_*`** : TRANCHE a l'execution VO-D-1 (2026-06-01). Liste finale = `OP_TYPE_RENAME`, `OP_TYPE_MOVE`, `OP_TYPE_NOOP` uniquement (StrEnum a 3 valeurs canoniques alignees sur `probe_models.py` L22-33). Pas de `KEEP`/`SKIP` dans l'implementation.

4. **Coordination migrations SQL Vague O** : 028 reservee VO-2 (`pragma_history`). 029/030 disponibles si necessaire (a priori non requis par VO-B/VO-C/VO-D).

### 7.3 Verdict R2 et next steps

**Verdict R2 propose** : **GO_WITH_FIXES** - les 5 motifs NOGO R1 sont resolus, les memoires user sont respectees explicitement, le total est arithmetiquement coherent, les sous-lots ont des acceptance criteria mesurables.

**Next steps** :
1. Soumettre ce doc R2 a la revue adversariale R2 (logic-deep + workflow find-verify-judge).
2. Si R2 confirme GO : poser tag `mini-recovery-o`, demarrer execution VO-A (depends_on rien) en parallele de VO-C et VO-D.
3. VO-B demarre apres merge VO-A (synergie `detect_storage_type`).
4. Si R2 identifie de nouveaux motifs : iterer en R3 (memoire `feedback_sereo_revue_adversaire_iterative` : 2-3 rounds avant tag).

---

*Document genere en remediation R2 post-NOGO R1 Vague O. Tag `mini-recovery-o` NON POSE. Sous-total reel 77h + buffer 25% = ceiling 96.25h. A re-soumettre a revue adversariale R2.*
