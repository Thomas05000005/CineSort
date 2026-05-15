# CineSort (CineSort)

## Instructions pour Claude Code

Tu dois utiliser les MCP servers disponibles de maniere proactive et automatique, sans attendre qu'on te le demande :
- **context7** : consulte la doc a jour d'un framework ou lib avant de coder (pywebview, requests, Playwright, Ruff, PyInstaller).
- **memory** : stocke et recupere les decisions d'architecture et le contexte entre sessions.
- **sequential-thinking** : utilise pour tout raisonnement complexe (debug, refactoring, design d'archi).
- **filesystem** : lecture/ecriture de fichiers dans le workspace.
- **playwright** : teste et observe l'interface UI dans un vrai navigateur.
- N'attends jamais qu'on te demande d'utiliser un outil — anticipe.

Langue : reponds toujours en francais sauf si le code est en anglais.
Apres chaque lot de modifications, rapporte : ce qui a change, pourquoi, fichiers touches, tests lances, ce qui reste.
Prefere les refactors incrementaux. Preserve le comportement existant sauf demande explicite. Pas de travail GitHub/CI/release sauf demande.

---

## OPERATION TERMINEE — Logging structure API (#103) ✅ (15 mai 2026)

Issue #103 (audit-2026-05-13:logoff) **`return {"ok": False, ...}` sans logging** mergee en 7 PRs (#150 -> #156). 198 / 198 sites migres vers le helper `_err_response()` dans tout `cinesort/ui/api/`.

### Helper API standard

Toutes les reponses d'erreur API passent desormais par `cinesort/ui/api/_responses.py:err()` :

```python
from cinesort.ui.api._responses import err as _err_response

return _err_response(
    "Message FR montre a l'utilisateur",
    category="state",     # validation | state | resource | permission | config | runtime
    level="info",         # debug | info | warning | error
    log_module=__name__,  # logger contextuel
    key="message",        # defaut. Param `key="error"` pour endpoints historiques
    run_id=run_id,        # extra fields (**kwargs)
)
```

Chaque appel log automatiquement `api err [<category>]: <message>` au bon niveau, ce qui resout le probleme initial de **diagnostic impossible** des bugs utilisateur ("le bouton XYZ marche pas").

### Categories conventionnelles

| Category | Quand l'utiliser |
|---|---|
| `validation` | input vide / manquant / mauvais type |
| `state` | pre-condition metier echouee (feature off, aucun run, plan pas pret) |
| `resource` | ressource introuvable / network error (TMDb, Jellyfin, Plex) |
| `permission` | operation refusee (local-only, lock detenu) |
| `config` | configuration invalide (key/url/path manquant) |
| `runtime` | exception runtime (DB locked, FS error) |

### 7 PRs mergees (#150 -> #156)

| PR | Module(s) | Sites |
|---|---|---|
| #150 | run_flow_support | 18 |
| #151 | apply_support | 18 |
| #152 | perceptual_support + probe_support | 27 |
| #153 | history + quality + library + dashboard | 34 |
| #154 | 7 modules misc (export, film, tmdb, ...) | 25 |
| #155 | cinesort_api.py | 63 |
| #156 | err() param `key` + 13 sites "error" key | 13 |
| **Total** | | **198** |

### Tests

- `tests/test_responses_helper.py` : 10 tests sur le helper (categories, levels, **extra, custom key)
- 4020+ tests existants : 0 regression sur les 7 PRs

---

## OPERATION TERMINEE — Refactor god class CineSortApi + Quick UX (15 mai 2026) ✅

Issue #84 (ARCH-P1) **god class CineSortApi** mergee en 10 PRs Strangler Fig (pattern Adapter + Facade pattern). Surface publique reduite de 104 -> 50 methodes (-52%). 5 facades par bounded context. PR fixes UX bonus (#143) + Issue #83 etape 1 (#144, #145).

### Architecture facades

5 facades injectees comme attributs sur CineSortApi :

| Facade | Methodes | Acces |
|---|---|---|
| `api.run` | start_plan, get_status, get_plan, export_run_report, cancel_run, build_apply_preview, list_apply_history | **7** |
| `api.settings` | get_settings, save_settings, set_locale, restart_api_server, reset_all_user_data, get_user_data_size | **6** |
| `api.quality` | profil scoring + perceptual + feedback (21 methodes) | **21** |
| `api.integrations` | TMDb + Jellyfin + Plex + Radarr | **11** |
| `api.library` | get_library_filtered, smart playlists, scoring rollup, film history, export RGPD | **9** |
| **Total** | **5 contextes** | **54** |

### Pattern de delegation

- **Avant** : `api.start_plan(payload)` (god class, 1 fichier 2200 lignes 104 methodes)
- **Apres** : `api.run.start_plan(payload)` (facade, methode publique)
- **Methodes directes privatisees** : `api._start_plan_impl(payload)` (encore appelable mais souligne)
- **REST routes** : `POST /api/run/start_plan` (et plus `/api/start_plan` qui renvoie 404)

### 10 PRs mergees (#129 -> #142)

1. **#129 PR 1** : 5 facades squelette + 5 methodes pilote
2. **#130 PR 2** : RunFacade complete (7 methodes)
3. **#131 PR 3** : SettingsFacade complete (6 methodes)
4. **#132 PR 4** : QualityFacade complete (21 methodes)
5. **#133 PR 5** : IntegrationsFacade complete (11 methodes)
6. **#134 PR 6** : LibraryFacade complete (9 methodes)
7. **#135 PR 7** : Documentation finale REFACTOR_PLAN_84.md
8. **#136 PR 8** : REST dispatcher walk facades (additif backward-compat)
9. **#137 PR 9** : Frontend JS migre vers /api/<facade>/<method>
10. **#142 PR 10** : Suppression 54 methodes directes (privatisation `_X_impl`)

### PRs UX bonus (#143, #144, #145)

- **#143** : routes Actions rapides Accueil corrigees (/library#step-analyse mort → /processing, /quality → /qij), helper `_unmask_or_stored` pour Test connexion avec cle masquee (4 endpoints test_* Jellyfin/Plex/Radarr/TMDb)
- **#144** : Issue #83 etape 1 — 17 callers externes migres hors re-exports `domain.core` (preparation casser cycle domain↔app)
- **#145** : Documentation REFACTOR_PLAN_83.md (suite a faire : 3-5 jours)

### Tests + smoke test

- **Snapshot test** `tests/test_cinesort_api_snapshot.py` regenere : 104 -> 50 methodes publiques
- **Build EXE** : 50.78 MB (cohérent vs 49.84 MB baseline v7.7.0)
- **REST spec** : 102 endpoints exposes (50 directs + 52 facade routes)
- **Suite pytest** : 4020+ tests passent
- **Scripts one-shot commites** pour audit : `scripts/migrate_js_to_facades_84.py`, `migrate_py_to_facades_84.py`, `privatize_cinesort_api_84.py`, `fix_patch_object_84.py`, `fix_remaining_assertions_84.py`

### Reste sur #83 (4 etapes a faire en sessions futures, 3-5 jours)

- Etape 2 : bouger fonctions de `domain/core.py` (qui utilisent app.X) vers `app/`
- Etape 3 : convertir 179 lazy imports en top-level
- Etape 4 : installer import-linter en CI

Cf `docs/internal/REFACTOR_PLAN_83.md` pour le plan complet.

---

## OPERATION TERMINEE — Audit Claude v3 + Hardening security (12 mai 2026) ✅

Session intensive d'amelioration de l'audit automatique via GitHub Actions + 
hardening security + fixes issus du 1er run audit.

### Resultats

- **Audit Claude Code Action v3** : prompt 1406 lignes externalise dans
  `.github/audit-prompt.md` (cf #28 fix size limit GitHub Actions 21000).
  46 categories d'audit (vs 16 initiales), 6 personas multi-agent
  (Security/Performance/UX/DB/Reliability/Compliance), JSON output schema
  + dedup via hash, self-critique 6 filtres, 1500 turns / 6h timeout.
- **Workflow audit-module.yml** : limites supprimees (15 PRs max -> illimite,
  300 turns -> 1500, 180 min -> 360 min). Cron quotidien 04h UTC.
- **OpenSSF Scorecard** : 42 actions externes pinned par SHA + permissions
  scopees par job (PR #27). Dependabot security updates ACTIVE via API.
- **1er run audit (14 min, 130 modules)** : 4 PRs auto fixes (plugin_hooks
  tracked_run, urlretrieve timeout, dead code, rapport docs) + 6 issues
  detaillees. Self-critique a supprime 31 faux positifs.
- **6 issues issues du run resolues** : DPAPI docs (#34), _op_between
  bornes inversees (#30), float comparisons HDR+spectral (#31), executescript
  transaction-safe (#33), O(n^2) fuzzy matching x3 modules (#29 perf x100-x1000),
  plan commente pour feature UI orphan data (#32).
- **CVE-2025-71176 pytest** bumpe a 9.0.3 (PR #44).
- **Bugs perceptuels precoces** : audio_score=0 conflate fixed,
  interpolation continue _score_val_inv/_score_bits (vs escalier 4 valeurs),
  magic numbers blur -> constantes nommees, __all__ ajoute composite_score.

### 16 PRs mergees

#22 fix(perceptual): 4 bugs composite_score + 8 tests + __all__
#23 refactor(perceptual): nommer seuils blur des verdicts croises
#24 feat(perceptual): scoring continu par interpolation lineaire
#25 chore(ci): prompt audit v2 (21 categories + ETAPE 2.5 techniques cross-couche)
#26 feat(ci): prompt audit v3 ultra-complet (46 categories + multi-agent + JSON)
#27 chore(security): pin SHAs + scope permissions par job (Scorecard fixes)
#28 fix(ci): URGENT - prompt > 21000 chars bloque les runs (externalisation .md)
#35 fix(plugins): plugin_hooks tracked_run pour cleanup garanti
#36 fix(probe): timeout socket sur urlretrieve dans auto_install
#37 refactor(audit): nettoyer 2 dead-code mineurs (tautologie + typo .upper)
#38 docs(audit): rapport Claude audit 2026-05-12 couche all (130 modules)
#39 docs(security): scope DPAPI CURRENT_USER documente
#40 fix(domain): _op_between normalise les bornes inversees (POLS)
#41 fix(perceptual): comparaisons flottantes robustes (HDR + spectral)
#42 fix(db): bootstrap schema dans transaction BEGIN/COMMIT (rollback-safe)
#43 perf(app): vectoriser fuzzy matching titres x3 modules

### 14 issues fermees

#13 #15 #16 #17 #18 #19 #20 #21 (audits perceptual + cleanup doublons)
#29 #30 #31 #32 (commente) #33 #34 (audit Claude run 1)

### Restant

- Issue #14 : meta-tracker audit (permanent, OK)
- Issue #32 : feature UI exposure (decision produit a prendre : modale /
  inline / page dediee pour exposer audio_fingerprint, ssim_self_ref,
  upscale_verdict, voir commentaire detaille)
- Cron audit auto 04h UTC quotidien : continuera a livrer findings sur
  les categories non encore epuisees

---

## OPERATION TERMINEE — Polish Total v7.7.0 (4 mai 2026) ✅

**7 vagues completees** sur la branche `polish_total_v7_7_0` (depuis `audit_qa_v7_6_0_dev_20260428`).
Tag final : `v7.7.0`. Plan d'execution : `OPERATION_POLISH_V7_7_0.md`. Tracking : `OPERATION_POLISH_V7_7_0_PROGRESS.md`.

### Resultats

- **3893/3893 tests** (100% pass), +343 vs baseline
- **Note 9.2/10 → ~9.9/10** (production-grade publique)
- **47+ findings resolus** (CRIT-4, R5-DB, R5-CRASH, R5-PERC, R5-STRESS-1/2/4/5, R4-MEM, R4-DOC-1/7, R4-CC-1/3/6, R4-LOG-1/4, R4-I18N-1/5, R4-PERC-7, H1-H18, etc.)
- **Build .exe** : 50.07 MB → 49.84 MB (-0.23 MB) ✅ < 60 MB
- **Coverage 81.3%** stable
- **i18n FR + EN** (locale switch live)
- **Stress 10k+ films** supporte (UI virtualisation, perceptual+probe parallelism)
- **Documentation utilisateur** : 6 docs (MANUAL, TROUBLESHOOTING, API ENDPOINTS, architecture.mmd, RELEASE, i18n)

### 7 vagues (cumul)

| Vague | Theme | Commits | Tests delta |
|---|---|---|---|
| 0 | Preparation (branche, baseline, tag) | 3 | baseline 3550 |
| 1 | Bloquants public release (CVE, FK CASCADE, ffmpeg, LPIPS, E2E, hidden imports) | 8 | +39 |
| 2 | UX/A11y polish (race UI, XSS, WCAG 2.2 AA, font-display, CSP, PRAGMA) | 6 | +42 |
| 3 | Polish micro + Documentation | 12 | +29 |
| 4 | Refactor code (3 fonctions monstres → 26 helpers) | 5 | +30 |
| 5 | Stress / scale (UI virtualisation, parallelism perceptual+probe, TMDb TTL) | 6 | +100 |
| 6 | i18n EN (infrastructure + 282 strings + formatters + EN trans + tests) | 6 | +103 |
| 7 | Validation finale + release v7.7.0 | 3-4 | — |

**Tags backup** : `backup-before-polish-total`, `end-vague-1` à `end-vague-6`, **`v7.7.0`** (final).

Pour le detail historique, voir `BILAN_CORRECTIONS.md` section "Phase Polish Total v7.7.0" et `CHANGELOG.md`.

---

## Nom du projet

**CineSort** (nom interne : CineSort) — Application desktop Windows de tri, renommage et organisation automatique de bibliotheques de films video.

## Stack technique

| Composant | Technologie | Version |
|-----------|------------|---------|
| Langage | Python | 3.13 (target) |
| GUI | pywebview | >= 5.0 |
| HTTP | requests | >= 2.31 |
| QR Code | segno | >= 1.6 (pure Python, MIT) |
| Fuzzy matching | rapidfuzz | >= 3.0 (C++, MIT, wheels Windows) |
| Base de donnees | SQLite3 (stdlib) | WAL mode, FK, busy_timeout 5000ms |
| Linter/Formatter | Ruff | >= 0.15 (regles E9, F) |
| Tests | unittest + coverage | coverage >= 7.6 |
| Build | PyInstaller | >= 6.0 |
| UI Testing | Playwright | >= 1.40 |
| Git hooks | pre-commit | >= 4.0 |
| OS cible | Windows 11 | onefile EXE (release) + onedir (QA) |

## Architecture

```
CineSort/
├── app.py                          # Point d'entree (pywebview, dev mode, UI variant)
│
├── cinesort/                       # Architecture moderne en couches
│   ├── domain/                     # Couche domaine (modeles purs, scoring)
│   │   ├── core.py                 #   Config, Stats, Candidate, PlanRow, NFO, scoring, constantes
│   │   ├── conversions.py          #   to_int/to_float/to_bool partages (source unique)
│   │   ├── title_helpers.py        #   Extraction titre/annee, constantes de scoring nommes
│   │   ├── scan_helpers.py         #   Scan fichiers et filtrage
│   │   ├── subtitle_helpers.py     #   Detection sous-titres, langues, inventaire
│   │   ├── duplicate_support.py    #   Detection doublons, _check_file_collisions
│   │   ├── duplicate_compare.py   #   Comparaison qualite doublons (7 criteres ponderes)
│   │   ├── integrity_check.py    #   Verification integrite header (magic bytes MKV/MP4/AVI/TS/WMV)
│   │   ├── encode_analysis.py   #   Detection upscale, 4K light, re-encode degrade
│   │   ├── audio_analysis.py   #   Analyse audio (format, canaux, commentaire, doublons, badge)
│   │   ├── librarian.py       #   Mode bibliothecaire (suggestions proactives, health score)
│   │   ├── run_models.py           #   RunStatus, RunSnapshot
│   │   ├── probe_models.py         #   NormalizedProbe
│   │   ├── quality_score.py        #   Scoring CinemaLux : _score_video, _score_audio,
│   │   ├── naming.py              #   Profils de renommage : templates, presets, validation
│   │   │                               #   _score_extras, _apply_weights, _determine_tier,
│   │   │                               #   compute_quality_score (orchestrateur)
│   │   └── perceptual/            #   Analyse qualite perceptuelle (signal reel)
│   │       ├── constants.py        #     Seuils, poids, tiers, studios (PERCEPTUAL_ENGINE_VERSION)
│   │       ├── models.py           #     FrameMetrics, VideoPerceptual, GrainAnalysis, AudioPerceptual, PerceptualResult
│   │       ├── ffmpeg_runner.py    #     resolve_ffmpeg_path, run_ffmpeg_binary/text
│   │       ├── frame_extraction.py #     compute_timestamps, extract_representative_frames
│   │       ├── video_analysis.py   #     run_filter_graph, luminance_histogram, block_variance, detect_banding
│   │       ├── grain_analysis.py   #     estimate_grain, classify_film_era, analyze_grain (verdict TMDb)
│   │       ├── audio_perceptual.py #     analyze_loudnorm, analyze_astats, analyze_clipping_segments
│   │       ├── composite_score.py  #     compute_visual/audio/global_score, detect_cross_verdicts
│   │       └── comparison.py       #     extract_aligned_frames, compare_per_frame, build_comparison_report
│   │
│   ├── infra/                      # Couche infrastructure
│   │   ├── db/
│   │   │   ├── connection.py       #   connect_sqlite() — factory connexion unique (WAL, FK)
│   │   │   ├── sqlite_store.py     #   _StoreBase (245L) + SQLiteStore (composition mixins)
│   │   │   ├── _run_mixin.py       #   Persistence runs et erreurs (13 methodes)
│   │   │   ├── _probe_mixin.py     #   Cache probe (3 methodes)
│   │   │   ├── _scan_mixin.py      #   Scan incremental (6 methodes)
│   │   │   ├── _quality_mixin.py   #   Quality profiles et reports (8 methodes)
│   │   │   ├── _anomaly_mixin.py   #   Anomalies (4 methodes)
│   │   │   ├── _apply_mixin.py     #   Journal apply/undo (7 methodes)
│   │   │   ├── migration_manager.py#   Orchestration migrations SQL
│   │   │   └── migrations/         #   001 a 006 (runs, probe, quality, anomalies, undo, scan)
│   │   ├── probe/
│   │   │   ├── constants.py        #   Timeouts centralises (VERSION_PROBE_TIMEOUT_S, etc.)
│   │   │   ├── service.py          #   ProbeService (ffprobe/mediainfo, cache)
│   │   │   ├── normalize.py        #   _extract_tracks, _merge_probes, _determine_quality,
│   │   │   │                       #   normalize_probe (orchestrateur), _ffprobe_video_dict
│   │   │   ├── ffprobe_backend.py  #   Runner ffprobe JSON
│   │   │   ├── mediainfo_backend.py#   Runner mediainfo JSON
│   │   │   ├── tools_manager.py    #   Detection/installation outils probe
│   │   │   └── tooling.py          #   ToolStatus, detection rapide
│   │   ├── state.py                #   RunPaths, ecriture JSON atomique
│   │   ├── tmdb_client.py          #   Client TMDb avec cache local JSON
│   │   ├── jellyfin_client.py      #   Client Jellyfin REST API (connexion, refresh, libraries)
│   │   ├── local_secret_store.py   #   Protection cle TMDb/Jellyfin via DPAPI (Windows)
│   │   └── run_id.py               #   Normalisation run_id
│   │
│   ├── app/                        # Couche application (orchestration)
│   │   ├── job_runner.py           #   JobRunner (threading, cancel, RunSnapshot)
│   │   ├── plan_support.py         #   _plan_item, plan_library, plan_multi_roots (scan/plan)
│   │   ├── apply_core.py           #   apply_rows, sha1_quick (orchestration apply)
│   │   ├── cleanup.py              #   _move_dirs_to_bucket, nettoyage vides/residuels
│   │   ├── export_support.py       #   Export HTML, .nfo Kodi/Jellyfin, CSV enrichi
│   │   └── jellyfin_sync.py        #   Sync watched Jellyfin (snapshot/restore Phase 2)
│   │
│   └── ui/                         # Couche UI (API bridge pywebview <-> JS)
│       └── api/
│           ├── cinesort_api.py     #   API principale (RunState, orchestration)
│           ├── run_flow_support.py  #   _build_analysis_summary, _init_tmdb_client,
│           │                       #   start_plan, _compute_speed_and_eta, get_status
│           ├── apply_support.py     #   _validate_apply, _execute_apply, _cleanup_apply,
│           │                       #   _summarize_apply, apply_changes, _execute_undo_ops,
│           │                       #   _write_undo_summary, undo_last_apply
│           ├── dashboard_support.py #   _load_report_context, build_run_report_payload
│           ├── quality_report_support.py # _probe_and_score, get_quality_report
│           ├── settings_support.py  #   Validation/normalisation settings
│           ├── quality_support.py   #   Analyse qualite batch
│           ├── perceptual_support.py #  Orchestration analyse perceptuelle + comparaison
│           └── (13 autres modules support)
│
├── web/                            # Frontend HTML/CSS/JS — Architecture v2 modulaire
│   ├── index.html                  #   Structure HTML (6 vues, sidebar, modals)
│   ├── styles.css                  #   Design system CineSort DS (tokens, composants)
│   ├── app.js                      #   Bootstrap (~100L) : init, bridge, theme
│   ├── core/
│   │   ├── dom.js                  #   Helpers DOM ($, qsa, esc, escapeHtml, clipboard)
│   │   ├── state.js                #   Etat global + persistence localStorage
│   │   ├── api.js                  #   Wrapper pywebview API (apiCall, persistValidation)
│   │   ├── router.js               #   Navigation vues (showView, navigateTo, table wrap)
│   │   ├── keyboard.js             #   Dispatcher raccourcis clavier (Alt+N, Ctrl+S, validation)
│   │   └── drop.js                 #   Drag & drop dossiers avec overlay visuel
│   ├── components/
│   │   ├── badge.js                #   setBadge, badgeForConfidence, severityBadge
│   │   ├── empty-state.js          #   buildEmptyStateHtml, buildTableEmptyRow
│   │   ├── modal.js                #   openModal, closeModal, trapFocus, uiConfirm
│   │   ├── status.js               #   setStatusMessage, flashActionButton
│   │   └── table.js                #   renderGenericTable (factory)
│   ├── views/
│   │   ├── home.js                 #   Accueil + lanceur scan (startPlan, pollStatus)
│   │   ├── validation.js           #   Fusion review + decisions (renderTable, filtres)
│   │   ├── execution.js            #   Apply + undo v1/v5 + conflits
│   │   ├── quality.js              #   Scoring, distribution, anomalies
│   │   ├── history.js              #   Runs table + exports (JSON, CSV, HTML, .nfo)
│   │   └── settings.js             #   Config + wizard onboarding
│   ├── preview/                    #   Mode preview (10 scenarios, mock API)
│   └── dashboard/                  #   Dashboard distant (SPA reseau local)
│       ├── index.html              #     Shell SPA (login + sidebar + vues)
│       ├── styles.css              #     Design system CinemaLux responsive
│       ├── app.js                  #     Bootstrap, routes, navigation
│       ├── core/
│       │   ├── dom.js              #     Helpers DOM ($, escapeHtml, el)
│       │   ├── state.js            #     Token (session/localStorage), polling timers
│       │   ├── api.js              #     Client fetch (Bearer auto, 401→login, 429)
│       │   └── router.js           #     Hash router, guards auth, transitions
│       ├── components/
│       │   ├── kpi-card.js         #     Carte KPI (icone SVG, valeur, tendance)
│       │   ├── badge.js            #     Badges tier/confiance/statut
│       │   ├── table.js            #     Table generique sortable (colonnes declaratives)
│       │   └── modal.js            #     Modale (detail + confirmation, Escape, overlay)
│       ├── views/
│       │   ├── login.js            #     Formulaire token + test connexion
│       │   ├── status.js           #     Etat global (KPIs, run en cours, sante, actions)
│       │   ├── logs.js             #     Logs live (polling 2s, auto-scroll, progress bar)
│       │   ├── library.js          #     Bibliotheque films (table, search, filtres, chart SVG, detail modale)
│       │   ├── runs.js             #     Historique runs (table, timeline SVG, export CSV/HTML/JSON)
│       │   ├── review.js           #     Review triage distant (approve/reject, bulk, dry-run, apply)
│       │   └── jellyfin.js         #     Statut Jellyfin (KPIs, libraries, test connexion)
│       └── fonts/
│           └── Manrope-Variable.ttf #    Police embarquee (pas de CDN)
│
├── tests/                          # 29 fichiers, 300 tests
│   ├── test_error_resilience.py    #   Tests resilience erreurs (16 tests, ajoutes pendant audit)
│   ├── test_*.py                   #   28 autres fichiers de tests
│   ├── e2e/                        #   Tests E2E Playwright (dashboard distant, 121 tests)
│   │   ├── conftest.py             #     Fixtures : serveur REST, auth, console errors
│   │   ├── create_test_data.py     #     Generateur 15 films mock + 2 runs + reports
│   │   ├── run_e2e.py              #     Script helper CLI
│   │   ├── pages/                  #     Page Object Model (base, login, status, library, runs, review, jellyfin)
│   │   ├── test_01_login.py        #     10 tests login
│   │   ├── test_02_navigation.py   #     10 tests navigation
│   │   ├── test_03_status.py       #     10 tests status
│   │   ├── test_04_library.py      #     12 tests library
│   │   ├── test_05_runs.py         #     8 tests runs
│   │   ├── test_06_review.py       #     12 tests review
│   │   ├── test_07_jellyfin.py     #     8 tests jellyfin
│   │   ├── test_08_responsive.py   #     10 tests 3 viewports
│   │   ├── test_09_visual_regression.py # 9 tests screenshots
│   │   ├── test_10_performance.py  #     8 tests perf
│   │   ├── test_11_accessibility.py #    10 tests a11y
│   │   ├── test_12_errors.py       #     8 tests erreurs
│   │   ├── test_13_console_errors.py #   7 tests console
│   │   ├── test_14_ui_report.py    #   5 tests rapport UI (debordements, boutons, textes)
│   │   ├── test_15_visual_catalog.py # 5 tests catalogue visuel (screenshots + rapport HTML)
│   │   ├── visual_catalog.py       #     Capture 45+ screenshots (7 vues × 3 viewports + modales)
│   │   ├── generate_visual_report.py #   Rapport HTML navigable (images base64, lightbox)
│   │   ├── ui_report.md            #     Rapport UI auto-genere (problemes mobile)
│   │   ├── visual_report.html      #     Catalogue visuel HTML single-file (~6 Mo)
│   │   └── corrections_log.md      #     Journal des bugs trouves et corriges
│   ├── live/                       #   Tests optionnels (TMDb, probe, pywebview)
│   └── stress/                     #   Tests charge (1000-5000 dossiers)
│
├── scripts/                        # Outils build et maintenance
│   ├── generate_icon.py            #   Generation ICO multi-resolution depuis JPEG source
│   └── ...                         #   capture_ui_preview, package_zip, etc.
├── runtime_hooks/                  # PyInstaller runtime hooks
│   └── splash_hook.py              #   Splash Win32 ctypes + AllocConsole --api
├── assets/
│   ├── cinesort.ico                #   Icone multi-resolution (16-256px, vrai ICO)
│   └── splash.png                  #   Image splash CineSort
├── docs/                           # Documentation (vision, design, releases, audits)
├── pyproject.toml                  # Config Ruff (py313, line-length 120)
├── CineSort.spec                   # Spec PyInstaller (QA onedir + release onefile)
├── CineSort.exe.manifest           # Manifest Windows (DPI, UAC, visual styles)
├── version_info.txt                # Template version info Windows (lu depuis VERSION)
├── check_project.bat               # CI locale (compile, lint, format, tests, coverage)
├── build_windows.bat               # Build PyInstaller (QA + release)
├── AGENTS.md                       # Regles de travail pour Claude
├── CHANGELOG.md                    # Historique des versions
├── AUDIT_COMPLET.md                # Audit du 2 avril 2026
└── BILAN_CORRECTIONS.md            # Bilan des 6 phases de corrections
```

## Conventions de code

### Langue et nommage
- **Langue** : francais pour l'UI, messages, commentaires, documentation ; anglais pour les noms de fonctions/variables
- **Classes** : `PascalCase` (`Config`, `PlanRow`, `RunState`)
- **Fonctions / variables** : `snake_case` (`extract_year`, `build_candidates_from_nfo`)
- **Constantes** : `UPPER_SNAKE_CASE` (`VIDEO_EXTS_DEFAULT`, `_TMDB_SCORE_BASE`)
- **Prive** : `_leading_underscore` (`_strip_accents`, `_RunMixin`)
- **Formatage** : 120 caracteres par ligne (Ruff), `from __future__ import annotations`
- **Dataclasses** : `frozen=True` pour l'immutabilite quand approprie
- **Commits** : prefixes (feat, fix, test, docs, ux, refactor)

### Regles de qualite (post-audit)
- **Docstrings** : obligatoires sur toutes les fonctions publiques. Format une ligne pour les simples, multi-lignes pour les complexes.
- **Constantes nommees** : pas de magic numbers dans le scoring ou les seuils. Utiliser des constantes `_UPPER_SNAKE` avec commentaire.
- **Try/except cibles** : ne jamais ecrire `except Exception`. Toujours specifier les types (`except (ET.ParseError, FileNotFoundError, PermissionError, OSError)`).
- **Regex compilees** : compiler a module level avec `re.compile()` quand utilise dans des boucles.
- **Timeouts** : centralises dans `cinesort/infra/probe/constants.py`.
- **Pas de duplication** : toute logique partagee doit etre dans un module commun (`conversions.py`, `connection.py`, `_check_file_collisions`, etc.).
- **Taille des fonctions** : viser < 100 lignes. Justification requise au-dela de 150 lignes.

## Contexte metier

### Extraction titre/annee
1. **NFO** (`.nfo` XML) : `<title>`, `<originaltitle>`, `<year>`, `<tmdbid>` — source la plus fiable, validee par `nfo_consistent()` (couverture >=0.75, sequence >=0.78)
2. **Dossier / Filename** : `infer_name_year()` avec regex de nettoyage — annees parenthesees `(YYYY)` prioritaires
3. **TMDb fallback** : recherche API, cache JSON local, cle API protegee DPAPI

### Scoring de confiance
- **High** (>=80) | **Med** (>=60) | **Low** (<60)
- Facteurs : similarite titre (constantes `_SEQ_WEIGHT`, `_TOK_WEIGHT`), delta annee, credibilite source, consensus multi-sources, popularite TMDb (constantes `_TMDB_SCORE_*`)

### Validation UI et review triage
- Preset "A relire (risque)" base sur score de risque (confiance, source, warnings, type changement, qualite)
- **Review triage** : actions rapides approuver/rejeter directement depuis "Cas a revoir", boutons bulk "Approuver tous / Rejeter tous", masquage des cas traites, compteur inbox zero
- **Mode batch automatique** : reglage `auto_approve_enabled` + `auto_approve_threshold` (70-100%, defaut 85%). Apres le scan, les films avec confiance >= seuil ET sans warning critique sont auto-approuves. Les autres passent en review manuelle. Endpoint : `get_auto_approved_summary(run_id, threshold, enabled)`

### Onboarding
- **Wizard premier lancement** : modal 5 etapes (Bienvenue → Dossier racine → Cle TMDb → Test rapide → Termine). Detection automatique : aucun root configure + `onboarding_completed=false`. Flag persiste dans settings.json. Validation dossier en temps reel, test TMDb live, dry-run sur 5 films avec apercu des resultats.

### Dry-run, quarantine, undo
- **Dry-run** : `dry_run=True`, aucune modification filesystem
- **Quarantine** : rows non approuvees vers `_review/`
- **Undo v1 (batch)** : journal SQLite (`apply_batches` + `apply_operations`), preview avant rollback, conflits vers `_review/_undo_conflicts`
- **Undo v5 (par film)** : annulation selective film par film via `row_id` dans `apply_operations` (migration 007). Endpoints : `undo_by_row_preview(run_id, batch_id?)`, `undo_selected_rows(run_id, row_ids, dry_run?, batch_id?)`, `list_apply_history(run_id)`. Vue frontend avec table de films, checkboxes, preview dry-run, confirmation modale, badges de statut par film. Backward-compatible (batches legacy sans row_id affiches comme "__legacy__").

### Quality scoring (CinemaLux)
- Scinde en sous-fonctions : `_score_video()`, `_score_audio()`, `_score_extras()`, `_apply_weights()`, `_determine_tier()`
- Tiers : Premium >=85, Bon 68-84, Moyen 54-67, Mauvais <54
- Presets caches : `_get_presets_catalog()` (lazy init, calcul unique par processus)
- Backends probe : ffprobe ou mediainfo, timeouts dans `constants.py`

### Profils de renommage
- **Module** : `cinesort/domain/naming.py` — `NamingProfile`, `PRESETS`, `format_movie_folder`, `format_tv_series_folder`, `build_naming_context`, `validate_template`, `check_path_length`
- **Syntaxe** : variables `{title}`, `{year}`, `{resolution}`, `{video_codec}`, `{hdr}`, `{audio_codec}`, `{channels}`, `{quality}`, `{score}`, `{tmdb_id}`, `{tmdb_tag}`, `{original_title}`, `{source}`, `{bitrate}`, `{container}`, `{series}`, `{season}`, `{episode}`, `{ep_title}` (20 variables)
- **Presets** : `default` (`{title} ({year})`), `plex` (`{title} ({year}) {tmdb_tag}`), `jellyfin` (`{title} ({year}) [{resolution}]`), `quality` (`{title} ({year}) [{resolution} {video_codec}]`), `custom` (libre)
- **{tmdb_tag}** : produit `{tmdb-27205}` (accolades literales dans le resultat) si tmdb_id disponible, sinon chaine vide
- **Variables manquantes** : remplacees par chaine vide, separateurs orphelins nettoyes automatiquement (`[]`, `()`, espaces doubles, tirets)
- **Validation** : `validate_template()` verifie variables connues, accolades equilibrees, presence de `{title}` ou `{series}`
- **Settings** : `naming_preset`, `naming_movie_template`, `naming_tv_template` dans settings.json
- **Config** : `naming_movie_template` et `naming_tv_template` dans Config dataclass, propages via `build_cfg_from_settings`
- **Injection** : `apply_single()`, `apply_collection_item()`, `apply_tv_episode()` dans apply_core.py utilisent `format_movie_folder()`/`format_tv_series_folder()` au lieu du f-string hardcode
- **Defaut** : `{title} ({year})` → comportement identique a l'historique, zero regression
- **Preview mock** : `PREVIEW_MOCK_CONTEXT` (Inception, 2010, 1080p, hevc, tmdb 27205, truehd 7.1) toujours disponible
- **Path length** : `check_path_length()` warning si > 240 chars, pas de troncature

### Scan incremental v2 (double couche)
- **Couche 1 (dossier, v1)** : cache `incremental_scan_cache` (folder_sig + cfg_sig). Hit total = 0 overhead.
- **Couche 2 (video, v2)** : cache `incremental_row_cache` (video_path + video_sig + nfo_sig + cfg_sig). Hit partiel = seules les videos modifiees sont rescannees. Migration 008.
- **Invalidation granulaire** : fichier video modifie → miss cette video uniquement. NFO modifie → miss les rows liees. Config changee → miss total.
- **Metriques** : `cache_folder_hits`, `cache_row_hits`, `cache_row_misses` visibles dans le resume d'analyse.

### Detection series TV
- **Reglage** : `enable_tv_detection` (bool, defaut false). Active → les series sont detectees et organisees au lieu d'etre ignorees.
- **Parsing** : `parse_tv_info()` dans `cinesort/domain/tv_helpers.py`. Patterns S01E01, 1x01, Episode N. Extraction serie/saison/episode depuis les noms de fichiers et dossiers.
- **TMDb TV** : `search_tv()`, `get_tv_episode_title()` dans `cinesort/infra/tmdb_client.py`. Cache JSON local.
- **PlanRow etendu** : champs optionnels `tv_series_name`, `tv_season`, `tv_episode`, `tv_episode_title`, `tv_tmdb_series_id`. Kind `"tv_episode"`.
- **Apply** : `apply_tv_episode()` cree la structure `Serie (annee)/Saison NN/S01E01 - Titre.ext` avec sidecars.
- **UI** : badge "Serie" (violet) dans la table de validation. Toggle dans les reglages.

### Export enrichi
- **CSV enrichi** : 30 colonnes (vs 17) — ajout confidence, resolution, video_codec, bitrate, audio_codec, channels, hdr, subscores, explanation, warning_flags, nfo_present
- **Rapport HTML** : single-file autonome, CSS/SVG inline, zéro dépendance. Sections : stats cards, distribution qualité (bar chart SVG), table complète. Ouvrable dans tout navigateur, imprimable PDF via Ctrl+P. `export_html_report()` dans `cinesort/app/export_support.py`.
- **Export .nfo** : format XML Kodi/Jellyfin/Emby (`<movie><title>...<year>...<uniqueid type="tmdb">...`). Un .nfo par film, skip si existant (option overwrite), dry-run disponible. `export_nfo_for_run()`.
- **Endpoints** : `export_run_report(run_id, "html")`, `export_run_nfo(run_id, overwrite, dry_run)`
- **UI** : boutons "Exporter HTML" et "Générer .nfo" dans le dashboard. Le .nfo utilise dry-run preview + confirmation.

### Integration Jellyfin
- **Client** : `cinesort/infra/jellyfin_client.py` — `JellyfinClient` avec `validate_connection()`, `get_libraries()`, `get_movies_count()`, `refresh_library()`, `get_all_movies()`, `mark_played()`, `mark_unplayed()`
- **Auth** : header `Authorization: MediaBrowser Token="API_KEY"`. Cle API protegee DPAPI comme TMDb.
- **Settings** : `jellyfin_enabled`, `jellyfin_url`, `jellyfin_api_key` (DPAPI), `jellyfin_user_id` (auto-detecte), `jellyfin_refresh_on_apply`, `jellyfin_sync_watched`, `jellyfin_timeout_s`
- **Hook post-apply** : `_trigger_jellyfin_refresh()` dans `apply_support.py`. Declenche `POST /Library/Refresh` apres chaque apply reel (pas dry-run). Non-bloquant, log warning si echec.
- **Phase 2 (sync watched)** : `cinesort/app/jellyfin_sync.py`. Snapshot des statuts vu/pas vu AVANT apply (`snapshot_watched`), restauration APRES refresh (`restore_watched`). Polling re-indexation avec retry. Match par chemin normalise. Injection dans `apply_support.py` : `_snapshot_jellyfin_watched` / `_restore_jellyfin_watched`.
- **UI** : section Jellyfin dans les reglages (toggle, URL, cle API, test connexion, toggle refresh auto)
- **Endpoints API** : `test_jellyfin_connection(url, key, timeout)`, `get_jellyfin_libraries()`

### Multi-root
- **Concept** : scanner plusieurs dossiers racine (SSD + NAS + disque externe) en un seul run
- **Settings** : `roots: list[str]` en plus de `root: str` (backward compat). Migration automatique `root` → `roots` dans `_migrate_root_to_roots()`. Validation : deduplication, detection imbrication, detection roots inaccessibles.
- **PlanRow** : champ `source_root: Optional[str] = None` indiquant le root d'origine
- **Scan** : `plan_multi_roots()` dans `plan_support.py` itere sur chaque root, appelle `plan_library()` avec un Config dedie, merge Stats, detecte doublons cross-root (`duplicate_cross_root` warning_flag)
- **Apply** : `_execute_apply()` dans `apply_support.py` regroupe les rows par `source_root`, cree un Config par root, appelle `apply_rows()` par groupe. Chaque root a ses propres buckets (_review, _Collection, _Vide).
- **Cache incremental** : deja indexe par `(root_path, folder_path)` — aucune modification necessaire
- **Base de donnees** : `runs.root = roots[0]`, liste complete dans `config_json`. Pas de migration SQL.
- **UI Reglages** : liste editable de roots (ajouter/supprimer), remplace le champ texte unique
- **UI Accueil** : affichage de chaque root avec indicateur de statut
- **Cas limites** : root deconnecte → skip + warning ; root en double → deduplique ; root imbrique → warning ; aucun root accessible → erreur

### Gestion sous-titres
- **Concept** : detection et inventaire des sous-titres externes (.srt, .ass, .sub, .sup, .idx). Pas de renommage — les sous-titres suivent le dossier lors du move/rename.
- **Module** : `cinesort/domain/subtitle_helpers.py` — `SubtitleInfo`, `SubtitleReport`, `detect_language_from_suffix()`, `find_subtitles_in_folder()`, `match_subtitles_to_video()`, `build_subtitle_report()`
- **Detection langue** : par suffixe de nom de fichier (`.fr.srt`, `.eng.srt`, `.french.srt`). Mapping `_LANG_MAP` (~50 entrees ISO 639-1/2, noms courants, tags speciaux). Pas de lecture de metadonnees internes.
- **PlanRow** : 5 champs — `subtitle_count`, `subtitle_languages`, `subtitle_formats`, `subtitle_missing_langs`, `subtitle_orphans`
- **Warning flags** : `subtitle_missing_{lang}` (langue attendue absente), `subtitle_orphan` (sous-titre sans video), `subtitle_duplicate_lang` (doublon de langue)
- **Scoring qualite** : bonus/malus dans `_score_extras()` — toutes langues presentes +6, partielles +3, absentes -4, orphelins -2. Toggle `include_subtitles` dans le profil.
- **Settings** : `subtitle_detection_enabled` (bool, defaut True), `subtitle_expected_languages` (list, defaut ["fr"])
- **UI** : colonne "ST" dans la table de validation (badge vert/orange/rouge), detail dans l'inspecteur (langues, manquants, orphelins), toggle + langues dans les reglages

### Raccourcis clavier + Drag & drop
- **Module** : `web/core/keyboard.js` — dispatcher central raccourcis clavier. Un seul listener `keydown` sur document, routes par priorite : modal → modifiers (Alt+N, Ctrl+S, F5) → input focus guard → vue specifique → global.
- **Navigation** : Alt+1 a Alt+6 pour les 6 vues (meme dans un input). Ctrl+S sauvegarde les decisions. F5 rafraichit. ? ou F1 ouvre la modale raccourcis.
- **Validation** : fleches/jk pour naviguer, Espace/a pour approuver, r pour rejeter, i pour inspecteur, Ctrl+A tout approuver, Escape deselectionner.
- **Modale raccourcis** : `modalShortcuts` avec tableau structure (kbd tags, sections Navigation + Validation + Drag & drop).
- **Drag & drop** : `web/core/drop.js` — overlay visuel global quand un dossier est glisse. Drop ajoute le dossier aux roots. Sur Home, propose de lancer un scan. Fallback si file.path indisponible (limitation pywebview).
- **Backend** : `validate_dropped_path(path)` dans cinesort_api.py — valide que le chemin est un dossier existant.
- **Accessibilite** : overlay avec aria-hidden, modale avec role=dialog + aria-modal, kbd semantique, focus trap.

### Anomalies et conflits
- Table `anomalies` en SQLite ; doublons SHA1 vers `_duplicates_identical/` ; conflits vers `_review/_conflicts`

### Dashboard stats global (Bibliotheque)
- **Positionnement** : toggle dans la vue Qualite ("Run courant" / "Bibliotheque"), pas de 7e onglet
- **KPIs globaux** : total runs, total films, score moyen pondere, premium %, tendance (↑↓→), films sans analyse
- **Tendance** : compare la moyenne des 5 derniers runs vs les 5 precedents. Seuil ±2 points pour ↑↓
- **Timeline SVG** : barres verticales colorees par tier (success/accent/warning/danger), tooltip par run
- **Distribution** : tiers (Premium/Bon/Moyen/Mauvais) agreges sur N derniers runs
- **Top anomalies** : codes les plus frequents avec compteur et dernier run ou vu
- **Activite** : table des runs recents avec score, statut, alertes
- **Backend** : `get_global_stats(limit_runs=20)` dans `dashboard_support.py`. 3 methodes DB : `get_global_tier_distribution()`, `get_top_anomaly_codes()`, `get_runs_summary()`
- **Films sans analyse** : `total_rows` du dernier run - `scored_movies` = films jamais passes par le module probe

### Notifications desktop
- **Technologie** : Win32 `Shell_NotifyIconW` via ctypes — zero dependance externe
- **Module** : `cinesort/infra/notifications.py` (wrapper balloon) + `cinesort/app/notify_service.py` (service avec queue)
- **Evenements** : scan_done, apply_done, undo_done, error — chacun avec toggle individuel
- **Settings** : `notifications_enabled` (global), `notifications_scan_done`, `notifications_apply_done`, `notifications_undo_done`, `notifications_errors`
- **Focus** : notifie uniquement si `document.hasFocus()` retourne false (fenetre pywebview non active)
- **Thread-safety** : les scans tournent en thread background → queue + `drain_queue()` depuis le main thread
- **Points d'injection** : `run_flow_support.py` (scan), `apply_support.py` (apply + undo), `cinesort_api.py` (erreurs critiques)
- **Lifecycle** : `api._notify.set_window(window)` dans `app.py`, `api._notify.shutdown()` a la fermeture

### API REST
- **Module** : `cinesort/infra/rest_server.py` (~390L) — `RestApiServer` + `_CineSortHandler` + `_RateLimiter` + `generate_openapi_spec`
- **Technologie** : stdlib `http.server.ThreadingHTTPServer` — zero dependance externe
- **Convention** : `POST /api/{method_name}` avec body JSON. Dispatch generique via `getattr(api, method)(**params)`
- **Endpoints publics** : `GET /api/health` (statut + `active_run_id` optionnel), `GET /api/spec` (OpenAPI 3.0.3)
- **Dashboard distant** : `GET /dashboard/*` sert les fichiers statiques depuis `web/dashboard/`. Garde anti path-traversal (resolution + verification prefix). Fallback `/dashboard/` → `index.html`. MIME types etendus (woff2, svg, etc.). Cache-Control 5 min.
- **Rate limiting** : `_RateLimiter` — 5 echecs 401 par IP en 60s → 429. Dict `{ip: [timestamps]}` avec purge auto a chaque requete. Thread-safe.
- **Auth** : token Bearer dans header `Authorization`. Configurable via `rest_api_token`. Fail-closed si token vide
- **CORS** : `Access-Control-Allow-Origin: *` par defaut, preflight OPTIONS
- **Methodes exclues** : `open_path` (local uniquement), `log_api_exception` (interne)
- **Settings** : `rest_api_enabled` (bool), `rest_api_port` (int, 1024-65535), `rest_api_token` (str), `rest_api_https_enabled` (bool), `rest_api_cert_path` (str), `rest_api_key_path` (str)
- **HTTPS** : si `rest_api_https_enabled=true` + cert/key valides → TLS via `ssl.SSLContext`. Sinon fallback HTTP. Commande : `openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=CineSort"`
- **Modes** : GUI+API (thread daemon a cote de pywebview) ou standalone (`python app.py --api --port 8642`)
- **Thread-safety** : les guard locks existants de CineSortApi protegent les operations concurrentes
- **OpenAPI** : spec generee par introspection (`inspect.signature`) sur les methodes publiques

### Dashboard web distant
- **Acces** : `http://<ip>:8642/dashboard/` depuis n'importe quel navigateur du reseau local
- **Architecture** : SPA vanilla JS (ES modules), 19 fichiers dans `web/dashboard/`, zero dependance externe
- **Core** : `dom.js` (helpers $, escapeHtml), `state.js` (token session/localStorage, polling timers), `api.js` (client fetch, Bearer auto, 401→login, 429→retry), `router.js` (hash router, guards auth, setNavVisible)
- **Composants** : `kpi-card.js` (icones SVG Lucide, tendance, suffix), `badge.js` (tier/confiance/statut), `table.js` (sortable, colonnes declaratives, clickable), `modal.js` (overlay, Escape, confirmation)
- **Vues** : `login.js` (token + persist checkbox), `status.js` (KPIs + run progress + sante + actions, polling 2s/15s), `logs.js` (auto-scroll, polling incremental 2s), `library.js` (table 8 colonnes, search debounce, filtres tier, chart SVG, detail modale), `runs.js` (table, timeline SVG, export CSV/HTML/JSON via Blob), `review.js` (approve/reject toggle, bulk, preview, save, apply dry-run + confirm), `jellyfin.js` (guard enabled, KPIs, libraries, test connexion)
- **Design** : CinemaLux tokens complets, glass morphism, responsive 3 breakpoints (sidebar >=1024, collapse 768-1023, bottom tab <768), police Manrope embarquee, hover glow desktop, reduced motion, touch targets 44px
- **Securite** : fichiers statiques publics (pas d'auth), API protegee Bearer, rate limiting 5/IP/60s→429, path traversal guard, XSS escapeHtml, CORS
- **Endpoints utilises** : health, get_settings, get_global_stats, get_status, get_probe_tools_status, get_dashboard, get_plan, load_validation, save_validation, check_duplicates, apply, cancel_run, start_plan, export_run_report, test_jellyfin_connection, get_jellyfin_libraries (16 endpoints sur 33+)
- **Nav dynamique** : onglet Jellyfin masque si jellyfin_enabled=false
- **Vues integrations en v4 (choix architectural V5C-02)** : `jellyfin.js`, `plex.js`, `radarr.js`, `logs.js` restent en v4 par decision V5C-02 (mai 2026). Elles utilisent deja le pattern ESM moderne (`apiPost`/`apiGet`) avec tout le polish V1-V4 (skeletons, allSettled, KPIs colores, sync reports). Pas de port v5 prevu — vues simples qui ne beneficient pas d'une refonte. Cf `audit/results/v5c-02-decision.md`.

### Packaging PyInstaller
- **Spec** : `CineSort.spec` — un seul fichier spec pour les 2 modes (QA onedir + release onefile)
- **Icone** : `assets/cinesort.ico` — vrai ICO multi-resolution (16, 32, 48, 64, 128, 256 px), genere par `scripts/generate_icon.py` depuis le JPEG source
- **Splash screen** : `runtime_hooks/splash_hook.py` — fenetre Win32 ctypes (fond CinemaLux #06090F, texte accent bleu, barre decorative). Se ferme automatiquement quand pywebview affiche la fenetre principale (event `shown`)
- **AllocConsole** : le meme runtime hook detecte `--api` dans argv et attache/alloue une console Win32 pour que le mode standalone REST affiche ses logs
- **Version info** : `version_info.txt` template, rempli au build depuis `VERSION`. Visible dans Proprietes du .exe Windows (FileDescription, ProductName, version)
- **Manifest** : `CineSort.exe.manifest` — DPI awareness Per-Monitor V2, visual styles ComCtl32 v6, UAC asInvoker, long path support
- **Exclusions** : tkinter, unittest, test, pip, setuptools, PIL, protocoles reseau inutilises, lib2to3, etc. (~15-25 MB economises)
- **Filtrage web/** : `web/preview/` exclu du bundle (dev-only), fichiers `.bak`/`.tmp` exclus
- **Build** : `build_windows.bat` → genere l'icone, lance `pyinstaller CineSort.spec`, package ZIP
- **Sortie** : `dist/CineSort_QA/` (onedir) + `dist/CineSort.exe` (onefile ~14 MB)

## Priorites de developpement

1. **Fiabilite produit** — Aucun rename/move incorrect, dry-run obligatoire, undo fonctionnel
2. **Structure app** — Separation domaine/infra/UI, pas de raccourcis d'architecture
3. **Comprehension** — Code lisible, docstrings, constantes nommees, wording FR clair
4. **Vitesse d'usage** — Scan incremental, caches, polling reactif
5. **Nouvelles features** — Seulement apres stabilisation des 4 priorites precedentes

## Regles a ne pas enfreindre

- **Pas de modification BDD sans dry-run** — Toute operation apply doit pouvoir etre previsualisee
- **Pas de melange UI/domain** — La logique metier reste dans `cinesort/domain/` et `cinesort/app/`, jamais dans `web/` ou `cinesort/ui/`
- **Pas de dependance externe sans discussion** — Le projet a volontairement tres peu de dependances (pywebview + requests)
- **Pas de suppression de fichier utilisateur sans journal** — Toute operation destructive enregistree dans `apply_operations`
- **Pas de `except Exception`** — Toujours specifier les types d'exception attendus
- **Pas de magic numbers** — Toute valeur numerique de scoring/seuil doit etre une constante nommee
- **Pas de duplication de code** — Logique partagee dans un module commun
- **Pas de fonction > 150 lignes sans justification** — Scinder en sous-fonctions privees
- **Pas de big-bang rewrite** — Refactors incrementaux uniquement
- **Pas de travail GitHub/CI/release sauf demande explicite**

## Commandes utiles

### Lancement
```bash
python app.py                     # UI normale
python app.py --dev               # Mode developpeur (console)
python app.py --ui preview        # UI preview (dev uniquement)
python app.py --api               # API REST standalone (sans UI)
python app.py --api --port 9000   # API REST sur port custom
```

### Tests
```bash
check_project.bat                 # CI complet (compile, lint, format, tests, coverage)
python -m unittest discover -s tests -p "test_*.py" -v
python -m coverage run -m unittest discover -s tests -p "test_*.py" -v
python -m coverage report
```

### Lint et formatage
```bash
python -m ruff check .
python -m ruff format .
pre-commit run --all-files
```

### Tests optionnels
```bash
CINESORT_LIVE_TMDB=1 python -m unittest discover -s tests/live -p "test_tmdb_live.py" -v
CINESORT_LIVE_PROBE=1 python -m unittest discover -s tests/live -p "test_probe_tools_live.py" -v
CINESORT_STRESS=1 python -m unittest tests.stress.large_volume_flow -v
```

### Build et preview
```bash
build_windows.bat
python scripts/package_zip.py --all
python scripts/run_ui_preview.py --dev --no-browser
python scripts/capture_ui_preview.py --dev --recommended
python scripts/visual_check_ui_preview.py --dev
```

## Outils MCP disponibles

### context7
Consulter la documentation a jour d'un framework ou lib avant de coder. Utiliser systematiquement pour pywebview, requests, Playwright, PyInstaller, Ruff.

### memory
Stocker et recuperer les decisions d'architecture, conventions et contexte entre sessions. Persister les choix de design valides et les preferences utilisateur.

### sequential-thinking
Utiliser pour tout probleme complexe : debug multi-etapes, refactoring d'architecture, design de features, analyse de cas limites.

### filesystem
Lire et ecrire des fichiers dans le workspace. Complementaire des outils natifs pour l'exploration d'arborescence.

### playwright
Tester et observer l'interface UI dans un vrai navigateur. Indispensable pour les taches UI/UX : audit visuel, verification de regression, capture screenshots.

### sqlite
**Non connecte.** Pour interroger la base de donnees du projet, utiliser Python directement (`import sqlite3`).

## Base de donnees SQLite

Schema **v21** (21 migrations 001 a 021, historique dans `schema_migrations`), gere par `SQLiteStore` compose de 6 mixins :
- `_RunMixin` : `runs`, `errors`
- `_ProbeMixin` : `probe_cache`
- `_QualityMixin` : `quality_profiles`, `quality_reports`, `perceptual_reports` (009), `audio_fingerprints` (015), `audio_spectral` (016), `ssim_self_ref` (017), `composite_score_v2` (018)
- `_AnomalyMixin` : `anomalies`
- `_ApplyMixin` : `apply_batches`, `apply_operations` (007 row_id, 013 checksum), `apply_pending_moves` (019 WAL move journal), `user_quality_feedback` (014)
- `_ScanMixin` : `incremental_file_hashes`, `incremental_scan_cache`, `incremental_row_cache` (008)

**Migrations critiques recentes** :
- **020** : indexes performance sur `quality_reports(run_id, tier)` + autres
- **021** : `ON DELETE CASCADE` sur 4 FK (errors, quality_reports, anomalies, apply_operations) — V1-02 Polish Total v7.7.0

Pragmas : `foreign_keys = ON`, `journal_mode = WAL`, `busy_timeout = 5000`, `mmap_size = 256MB`, `PRAGMA optimize` au shutdown (V2-G), `PRAGMA integrity_check` au boot avec auto-restore depuis backup (V2-G). Backup auto rotatif 5 par defaut dans `<db_dir>/backups/` (CR-2). Factory connexion unique dans `connection.py`.

## Etat de sante du projet

> **Note 10 mai 2026** : section reecrite a partir des mesures objectives produites par
> `scripts/measure_codebase_health.py`. Toutes les valeurs ci-dessous sont **mesurables et
> reproductibles** (cf. `audit/results/v7_7_0_real_metrics_20260510.md` pour le snapshot
> integral). Les revendications anterieures (note 9.9/10, "0 fonction > 100L", "0 duplication
> identifiee") n'etaient **pas alignees avec la realite** : elles ont ete remplacees ci-dessous
> et archivees dans `docs/internal/historique_revendications_v7.md`.

### Note globale honnete : **7.5 / 10** (post Polish Total v7.7.0)

Decomposition par axe (notation justifiable, pas marketing) :

| Axe | Note | Justification courte |
|-----|------|----------------------|
| **Fonctionnalite** | 9.5 / 10 | Couverture features tres large (multi-source identification, dedup quality, perceptual, Jellyfin/Plex/Radarr, watchlist, REST, i18n FR+EN) |
| **Packaging** | 9.0 / 10 | PyInstaller solide, signing CI, splash, manifest DPI, ICO multi-res, bundle 49.84 MB |
| **Securite** | 8.0 / 10 | DPAPI 5 secrets, scrubber, REST hardening, mais 2 HIGH connus (cf section "Dette technique connue") |
| **Tests** | 7.0 / 10 | 4187 fonctions test, coverage 81 %, mais 31 skip caches dont 26 "V5C-01/V5C-03" deferred ; modules securite-critiques (move_journal, move_reconciliation, composite_score V1, local_secret_store) sans test direct ; visual regression e2e est une coquille vide |
| **Architecture** | 7.5 / 10 | God class CineSortApi -> 5 facades par bounded context (issue #84 mergee 15 mai). Cycle `domain → app` partiellement reduit (issue #83 etape 1 mergee, reste 3-5 j). Frontend triple-systeme toujours present. |
| **Performance** | 7.0 / 10 | Parallelisme perceptual + probe livre ; 6 optims triviales identifiees non faites (gain ~15-20 min sur scan 5k NAS) |
| **Qualite code** | 6.5 / 10 | 49 fonctions > 100L (vs "0" revendique), 17 fonctions > 150L, 276 magic numbers, 120 fonctions ≥ 6 params, Ruff config trop laxiste pour appliquer les regles ecrites dans CLAUDE.md |
| **Documentation** | 6.0 / 10 | CLAUDE.md desaligne (corrige par ce commit), ROADMAP.md s'arrete a v4 (mai 2026 = v7.7.0 livree), absence de SETTINGS.md exhaustif |

### Metriques objectives (snapshot 10 mai 2026)

| Metrique | Valeur mesuree | Commande |
|----------|----------------|----------|
| **Version** | v7.7.0 (tag `v7.7.0`, branche `polish_total_v7_7_0`) | `git describe --tags` |
| **Tests passants** | 3893 + 31 skip (V5C-01 deferred majoritaires) | `python -m unittest discover -s tests` |
| **Tests skip caches** | 31 (la plupart deferred V5C-01) | `grep -rn @unittest.skip tests/` |
| **Coverage** | 81 % (gate CI >= 80%) | `python -m coverage report` |
| **LOC Python** (cinesort/) | 47 049 dans 139 fichiers | `scripts/measure_codebase_health.py` |
| **LOC JS** (web/) | 32 372 dans 124 fichiers | idem |
| **Fichiers Python > 500L** | 23 | idem |
| **Fonctions > 100L** | **49** (CLAUDE.md anterieur revendiquait 20) | idem |
| **Fonctions > 150L** | **17** | idem |
| **Fonctions ≥ 10 params** | 30 (dont `_build_resolved_row` a 20 params) | idem |
| **except Exception / bare** | 28 sites AST (BLE001 Ruff en flag 11) | idem |
| **Magic numbers** (PLR2004) | 276 | `ruff check --select PLR2004` |
| **Imports lazy** (`import cinesort.X` indente) | 161 | symptome cycle domain↔app |
| **`console.log` actifs** | 22 dans `web/` hors preview | idem |
| **`# noqa` morts** (RUF100) | 23 | `ruff check --select RUF100` |
| **Composants JS dupliques** (desktop ↔ dashboard) | **22** | `comm -12 <(ls web/components) <(ls web/dashboard/components)` |
| **Migrations SQL** | 21 (jusqu'a 021 ON DELETE CASCADE) | `ls cinesort/infra/db/migrations/` |
| **Endpoints REST publics** | **102** (50 directs + 52 facade routes, depuis #84) | introspection `cinesort_api.py` |
| **Packaging** | 49.84 MB onefile (incluant LPIPS ONNX + onnxruntime) | `dist/CineSort.exe` |

### Verification continue

```bash
# Recalculer les metriques (a faire avant chaque release)
python scripts/measure_codebase_health.py \
    --output audit/results/v7_X_Y_real_metrics.md

# Test de coherence doc<->code (echoue si CLAUDE.md derive)
python -m unittest tests.test_doc_consistency
```

Ajouter `python scripts/measure_codebase_health.py --output ...` au workflow CI avant tag release.

## Dette technique connue (a traiter par phases — voir `audit/REMEDIATION_PLAN_v7_8_0.md`)

> **Plan de remediation complet** : [audit/REMEDIATION_PLAN_v7_8_0.md](audit/REMEDIATION_PLAN_v7_8_0.md)
> **Tracking d'execution** : [audit/TRACKING_v7_8_0.md](audit/TRACKING_v7_8_0.md)

### Bloquants prochaine release (Phase 1)

1. **SEC-H1** — `cinesort/infra/log_scrubber.py:44` : pattern regex SMTP password incomplet, `email_smtp_password` peut fuiter en clair dans `cinesort.log` si dump settings logge
2. **SEC-H2** — `cinesort/ui/api/settings_support.py:883` : `POST /api/get_settings` retourne `tmdb_api_key` et `jellyfin_api_key` en clair (les autres clefs Plex/Radarr/SMTP sont masquees). Pivot vers Jellyfin admin possible si token REST capture
3. **BUG-1** — `JellyfinError` herite directement d'`Exception` (`jellyfin_client.py:21`), force le code a `except Exception` dans 4 sites annotes "intentional"
4. **BUG-3** — Precedence and/or ambigue `quality_score.py:410`
5. **BUG-4** — `tests/e2e/test_09_visual_regression.py` : sauvegarde un screenshot puis assert `.exists()` mais **ne compare jamais** a une baseline (coquille vide)
6. **DATA-2** — `data.db` (0 octets) trackee par Git malgre `.gitignore`

### Performance hot paths (gain estime 15-20 min sur scan 5000 films NAS — Phase 2)

1. **PERF-1** — `ProbeService.get_tools_status` lance `mediainfo --version` + `ffprobe -version` (2 subprocess) **par film** ; cache miss coute 500 s sur premier scan 5k
2. **PERF-2** — `folder.resolve() == cfg.root.resolve()` execute 2x par film dans `plan_support.py:827-831` — 50-150 s sur SMB
3. **PERF-3** — `_nfo_signature` lit le NFO 2x par film en cache miss (lookup + store) — 200 s NAS
4. **PERF-4** — `get_settings` re-dechiffre DPAPI a chaque appel (~10 calls par scan + ~5000 par batch perceptual) — 75 s sur batch perceptual
5. **PERF-5** — `apply_single` execute `find_main_video_in_folder` + `sha1_quick` 16 MB par MOVE_DIR meme si `row.video` connu — 100-250 s NAS (decision compromis perf/securite atomicite a prendre)
6. **PERF-6** — TMDb cache JSON re-ecrit complet avec `indent=2` toutes les 2 s (~20 MB × 750 writes par scan) — 15 GB I/O inutile + 112 s CPU

### Dette structurelle (Phases 6, 8, 9, 10, 12)

- ✅ **God class CineSortApi (issue #84)** : RESOLU le 15 mai 2026 via 10 PRs Strangler Fig. 104 -> 50 methodes publiques sur CineSortApi, 5 facades par bounded context (api.run, api.settings, api.quality, api.integrations, api.library). REST routes prefixees `/api/<facade>/<method>`.
- **49 fonctions > 100L** dont 17 > 150L (top : `_execute_perceptual_analysis` 309L, `apply_rows` 271L, `_build_dashboard_section` 241L)
- **Cycle d'imports `domain/core.py → app/` (issue #83)** : EN COURS. PR #144 (etape 1, 17 callers migres) mergee. 4 imports top-level + 38 re-exports + 179 lazy imports a finir en 3-5 jours. Cf `docs/internal/REFACTOR_PLAN_83.md`.
- **22 composants JS dupliques** entre `web/components/` (IIFE) et `web/dashboard/components/` (ESM) — bugs corriges deux fois
- **Frontend triple-systeme** : `web/styles.css` (87 KB) + `web/dashboard/styles.css` (82 KB) + `web/shared/components.css` (94 KB) — CLAUDE.md note "reporte v7.7.0+" non resolu
- **`web/index.html` + `web/views/*.js` (~9000 LOC)** potentiellement dead code (le dashboard charge `web/dashboard/index.html` ; le legacy desktop n'apparait pas dans `app.py` cote pywebview)
- **Tier API dual** : `Platinum/Gold/Silver/Bronze/Reject` (nouveau) cohabite avec `Premium/Bon/Moyen/Mauvais` (legacy) dans 5 endroits avec fallbacks
- **`video_exts`** hardcode 5 fois differemment (parfois sans `.wmv`, parfois oui)
- **3 systemes de codec rank** (`duplicate_compare.py`, `audio_analysis.py`, `quality_score.py`) avec valeurs divergentes
- **212 occurrences** `return {"ok": False, "message": ...}` sans factory, **18 sites** boilerplate validation run_id
- **`_save_cache_atomic` TMDb** : 7 sites callers refont `try/except` autour, pourrait etre interne au save

### Qualite tests (Phase 3, 13, 16)

- **Modules sans test direct** : `move_journal.py` (192 L), `move_reconciliation.py` (180 L), `composite_score.py` V1 par defaut (334 L), `local_secret_store.py` DPAPI (146 L), 24/26 modules `ui/api/`
- **20/21 migrations SQL** sans test dedie (seul `test_migration_021.py` suit le pattern recommande Fresh/Cascade/Existing/Idempotence)
- **Tests manquants** : cancel pendant `apply()` (uniquement scan testes), upgrade DB v1 → v21, smoke test PyInstaller (`dist/CineSort.exe` jamais demarre dans la suite), upgrade `settings.json` ancien
- **31 tests skip** dont 26 deferred V5C-01 / V5C-03 — `dashboard/views/review.js` et associes supprimes mais tests pas re-portes vers `processing.js`
- **`test_09_visual_regression.py`** est une coquille vide (assert juste `.exists()`)
- **Pas de property-based** (hypothesis), pas de mutation testing

### Outillage (Phase 14)

- Ruff config `pyproject.toml:34` : `select = ["E", "F", "W", "UP024", "UP032", "UP034"]` — **les regles que CLAUDE.md edicte ne sont pas appliquees** par le linter. Activations recommandees a faire progressivement : `B`, `BLE001`, `PLR2004`, `PLR0913`, `C901`, `SIM`, `RUF`, `I`, `S`
- 23 `# noqa: BLE001` morts (RUF100) — directives inutiles puisque BLE001 n'est pas dans le select
- ROADMAP.md s'arrete a v4 (avril 2026) — vagues V5-V7.7 absentes

### Sections inchangees (cf historique audits)

- Design system v5 : 4 themes Studio/Cinema/Luxe/Neon avec tier colors invariantes, 5 fichiers `web/shared/`
- Navigation v5 : sidebar 7 entrees Alt+1-7, top-bar Cmd+K + notification center
- Schema SQLite v21, pragmas WAL + FK + busy_timeout + mmap_size + PRAGMA optimize au shutdown
- Mode preview : 6 vues v2, 10 scenarios, mock API complet
- Locale FR + EN (491 cles FR + 295 cles EN)
- Moteur perceptuel : 20+ modules, grain intelligence v2, LPIPS ONNX, score composite V2 toggle
- Securite acquise : DPAPI 5 secrets, scrubber (8 patterns sauf bug SEC-H1), CSP Report-Only, atomicite shutil.move via journal (CR-1), backup DB auto rotatif (CR-2)

## Historique des audits

**4 mai 2026 — Polish Total v7.7.0 (7 vagues, ~50 commits, 47+ findings)** : opération marathon de validation production-grade publique.
- Vague 0 : préparation (branche `polish_total_v7_7_0` depuis `audit_qa_v7_6_0_dev_20260428`)
- Vague 1 : bloquants public release (CVE urllib3+pyinstaller, migration 021 ON DELETE CASCADE, ffmpeg subprocess cleanup atexit, LPIPS fallback graceful, tests E2E + v5c_cleanup mise à jour, PyInstaller hidden imports). 8 commits, tag `end-vague-1`.
- Vague 2 : UX/A11y polish (qij race+XSS+tri Journal, cache get_settings boot, memory leaks 5 fixes, WCAG 2.2 AA focus trap+aria-busy+arrow keys, CSP Report-Only, PRAGMA optimize+integrity_check). 6 commits.
- Vague 3 : polish micro + documentation (CSS legacy -603 KB, Manrope dédup, .clickable-row, logging run_id+request_id, CLAUDE.md mise à jour, ENDPOINTS.md auto-gen 99 endpoints, MANUAL.md 538L, TROUBLESHOOTING.md 357L, architecture.mmd 6 diagrammes, env.example, BILAN cleanup R1+R2 archives, RELEASE.md). 12 commits.
- Vague 4 : refactor code séquentiel (`_plan_item` 565L → 14 helpers, `compute_quality_score` 369L → 7 helpers, `plan_library` 347L → 5 helpers, ~50 docstrings, Composite Score V2 toggle V1 défaut). 5 commits, score IDENTIQUE vérifié.
- Vague 5 : stress/scale (UI virtualisation library, perceptual ThreadPool, TMDb TTL+purge, probe ThreadPool). 6 commits, scale 10k+ films, 100% pass.
- Vague 6 : i18n EN (infrastructure complète, 282 strings extraites, formatters Intl.*, en.json 295 clés, 31 tests round-trip, docs/i18n.md). 6 commits, FR+EN locale switch live.
- Vague 7 : validation finale + release v7.7.0 (build .exe 49.84 MB, CHANGELOG.md, CLAUDE.md statut final).
- **Bilan** : 3550 → 3893 tests (100% pass), 9.2/10 → 9.9/10, 0 régression imputable.

**2 avril 2026** — Audit complet (AUDIT_COMPLET.md) : exploration structurelle, audit de chaque fichier Python, reconstitution du flux fonctionnel, 11 captures UI Playwright. Note initiale 7.1/10. 28 findings identifies (0 critique, 12 importants, 10 mineurs, 6 cosmetiques).

**2 avril 2026** — Corrections en 6 phases (BILAN_CORRECTIONS.md) : 859 lignes nettes supprimees, 528 lignes de duplication eliminees (100%), fonctions geantes scindees (12 → 3 > 100L), SQLiteStore 1200L → 245L + 6 mixins, 16 tests de resilience ajoutes. Note finale 8.0/10.

**2 avril 2026** — Migration legacy → cinesort/ : 9 modules racine migres vers cinesort/domain/, cinesort/app/, cinesort/infra/. Shims de compatibilite sys.modules. 0 regression.

**2 avril 2026** — Undo v5 (annulation par film) : migration 007 (row_id), 3 endpoints API, 3 methodes DB, frontend avec table de films + selection + preview + confirmation. 4 tests ajoutes. Schema v7. Note 8.2/10.

**3 avril 2026** — Review triage + Mode batch automatique : actions rapides approuver/rejeter dans "Cas a revoir", bulk actions, inbox zero. Reglage auto-approbation (seuil configurable), endpoint get_auto_approved_summary, slider UI. Note 8.4/10.

**3 avril 2026** — Scan incremental v2 : cache double couche (dossier v1 + video v2). Migration 008 (incremental_row_cache). Invalidation granulaire par video/NFO. 3 methodes DB, metriques enrichies, 3 tests ajoutes. Schema v8. Note 8.5/10.

**3 avril 2026** — Onboarding ameliore : wizard 5 etapes (bienvenue, dossier, TMDb, test rapide, termine). Detection premier lancement automatique. Validation en temps reel, test TMDb live, dry-run apercu. Flag onboarding_completed en settings. Note 8.6/10.

**3 avril 2026** — Detection series TV : parsing S01E01/1x01/Episode N, TMDb TV API (search_tv, get_tv_episode_title), PlanRow etendu (tv_series_name, tv_season, tv_episode), apply vers Serie/Saison/S01E01.ext, badge "Serie" violet, toggle reglage. 9 tests ajoutes. Note 8.8/10.

**3 avril 2026** — Integration Jellyfin Phase 1 : JellyfinClient (connexion, validate, refresh, get_libraries, get_movies_count), 7 settings (url, api_key DPAPI, user_id, refresh_on_apply, sync_watched, timeout_s, enabled), hook post-apply _trigger_jellyfin_refresh (fire-and-forget, dry-run safe), section UI dans reglages (test connexion, toggle refresh), 2 endpoints API. 27 tests ajoutes. Note 8.9/10.

**3 avril 2026** — Export enrichi : CSV 30 colonnes (+15 qualite/probe), rapport HTML single-file (CSS/SVG inline, stats cards, bar chart distribution, table complete, zero dependance), export .nfo XML Kodi/Jellyfin/Emby (dry-run, skip existing, overwrite). Module export_support.py, 2 endpoints API, boutons UI dashboard. 24 tests ajoutes. Note 9.0/10.

**4 avril 2026** — Refonte UI v2 : reecriture complete du frontend. Design system CineSort DS (25 tokens couleur, 1 police Manrope, 5 tailles, grille 4px, 3 variantes de boutons). Architecture JS modulaire : core/ (dom, state, api, router) + components/ (table, badge, modal, status, empty-state) + views/ (home, validation, execution, quality, history, settings) + app.js bootstrap (~100L). Reduction de 10 vues a 6 (fusion Review+Decisions, suppression Vue du run + Analyse + Conflits). CSS de 9211 a ~560 lignes. JS de 7800 a ~2800 lignes. Tests adaptes : 370 OK, 0 regression. Note 9.2/10.

**4 avril 2026** — Dashboard stats global : vue Bibliotheque dans Qualite. Toggle Run courant / Bibliotheque. 3 methodes DB (_quality_mixin, _anomaly_mixin, _run_mixin), 1 endpoint API get_global_stats, chart SVG timeline (barres colorees par tier), KPIs globaux (runs, films, score, premium, tendance ↑↓→, films sans analyse), distribution tiers, top anomalies, activite recente. Indicateur de tendance calcule sur 5 derniers vs 5 precedents. 21 tests ajoutes (DB + API + UI). Note 9.3/10.

**4 avril 2026** — Notifications desktop : toasts Win32 via Shell_NotifyIconW (ctypes, zero dependance). NotifyService avec queue thread-safe, detection focus via document.hasFocus(). 5 evenements (scan_done, apply_done, undo_done, error, scan_error), 5 settings (global + 4 par type). Points d'injection : run_flow_support (scan), apply_support (apply + undo), cinesort_api (erreurs). Section Notifications dans Reglages. 21 tests ajoutes (service + delivery + queue + UI + persistence). Note 9.4/10.

**4 avril 2026** — API REST : serveur HTTP stdlib (ThreadingHTTPServer, zero dependance). Dispatch generique POST /api/{method} vers CineSortApi. Auth Bearer token, CORS, spec OpenAPI 3.0.3 auto-generee. 33 endpoints exposes, 2 exclus (open_path, log_api_exception). 3 settings (enabled, port, token). Mode standalone `--api` ou coexistence avec pywebview en thread daemon. 25 tests ajoutes (lifecycle, HTTP, auth, CORS, dispatch, OpenAPI, settings, UI). Note 9.5/10.

**4 avril 2026** — Adaptation preview UI v2 : migration des 10 scenarios vers les 6 vues v2 (validate→validation, apply→execution, logs→history). preview_boot.js adapte pour CineSortBridge.navigateTo au lieu de openNavigationView. preview_toolbar.js avec SUPPORTED_VIEWS v2 et aliases legacy. Mock API enrichi (get_global_stats). Scripts capture_ui_preview.py et visual_check mis a jour (DEFAULT_VIEWS, CRITICAL_VIEWS, check active au lieu de hidden). Emission cinesortready dans app.js. Scripts preview charges dans index.html. Baselines regenerees.

**4 avril 2026** — Jellyfin Phase 2 (sync watched) : 3 methodes client (get_all_movies, mark_played, mark_unplayed), module jellyfin_sync.py (snapshot_watched, restore_watched, _normalize_path, _build_path_mapping), injection pre/post apply (snapshot AVANT, restore APRES refresh). Dataclasses WatchedInfo + RestoreResult. Polling re-indexation avec retry. 29 tests Jellyfin. Note 9.5/10.

**4 avril 2026** — Refactoring 3 fonctions > 100L : start_plan 227L→54L (extraction _validate_and_init_plan_context + _build_plan_job_fn + _save_plan_artifacts), undo_last_apply 131L→45L (extraction _extract_undo_context + _execute_and_finalize_undo), build_run_report_payload 126L→76L (extraction _build_row_payload + _read_report_meta). 0 fonction > 100L restante. 0 regression.

**4 avril 2026** — Multi-root : support de N dossiers racine dans un seul run. PlanRow.source_root, plan_multi_roots() avec merge Stats + detection doublons cross-root. Settings migration root→roots (backward compat). Apply regroupe par source_root. UI settings editeur multi-root (liste ajouter/supprimer). UI home affichage multi-root avec statut. Validation roots (dedup, imbrication, accessibilite). 25 tests multi-root. 493 tests total, 0 regression. Note 9.6/10.

**4 avril 2026** — Gestion sous-titres : detection .srt/.ass/.sub/.sup/.idx, association par stem video, detection langue par suffixe (mapping 50+ entrees ISO 639-1/2 + noms courants). Module subtitle_helpers.py (SubtitleInfo, SubtitleReport). PlanRow +5 champs (subtitle_count, subtitle_languages, subtitle_formats, subtitle_missing_langs, subtitle_orphans). Warning flags (subtitle_missing_{lang}, subtitle_orphan, subtitle_duplicate_lang). Scoring qualite dans _score_extras (+6/-4). Settings (subtitle_detection_enabled, subtitle_expected_languages). UI colonne ST dans validation + detail inspecteur + section reglages. 31 tests sous-titres. 524 tests total, 0 regression. Note 9.7/10.

**4 avril 2026** — Raccourcis clavier + Drag & drop : module keyboard.js (dispatcher central, priorite modal → modifiers → input guard → vue → global). Alt+1-6 navigation, Ctrl+S sauvegarde, F5 refresh, ?/F1 aide. Validation : fleches/jk, Espace/a approuver, r rejeter, i inspecteur, Ctrl+A tout approuver, Escape deselectionner. Module drop.js (overlay visuel, drop → ajoute root, proposition scan sur Home, fallback si file.path indisponible). Backend validate_dropped_path. Modale modalShortcuts (kbd tags, sections). Migration handleValidationKeydown → keyboard.js. 6 tests ajoutes. 530 tests total, 0 regression. Note 9.8/10.

**4 avril 2026** — Refonte esthetique CinemaLux : design system v3.0. Direction artistique "salle de projection privee". Palette sombre profonde (#06090F), glass morphism (backdrop-filter blur 12px), bordures lumineuses accent-border (bleu 25% opacite), gradient accents sur boutons/toggles/presets. Icones sidebar SVG Lucide coherentes (6 icones inline). Cards avec inset shadow et border accent hover. KPI avec border-left coloree par categorie + animation fadeIn decalee. Tables avec row hover barre laterale bleue + alternance subtile. Badges avec micro-glow colore et border fine. Bouton primary gradient bleu + shadow + hover translateY. Distribution bars gradient + glow par tier. Toggles gradient track + knob shadow. Modales glass card + animation modalEnter. Env bar avec dot indicators glow. Presets avec gradient actif + glow. Animations viewEnter sur les vues, kpiFadeIn decale. Theme clair adapte (ombres au lieu de glass, glow reduit). Retrait pill "Bureau 1250px+". 530 tests, 0 regression. Baselines regenerees. Note 9.9/10.

**4 avril 2026** — Packaging PyInstaller optimise : vrai ICO multi-resolution (7 tailles 16-256px, 141 KB) genere par scripts/generate_icon.py depuis le JPEG source. Splash screen Win32 ctypes (fond CinemaLux, texte accent, fermeture sur event shown). AllocConsole pour --api standalone. Version info Windows (FileDescription, ProductName, version lue depuis VERSION). Manifest Windows (DPI Per-Monitor V2, visual styles ComCtl32 v6, UAC asInvoker, long path). Exclusions stdlib (~15-25 MB : tkinter, unittest, pip, PIL, protocoles reseau). Filtrage web/preview/ et .bak du bundle. Renommage CineSortApp.spec → CineSort.spec. Build : QA onedir 27 MB, release onefile 14 MB. 530 tests, 0 regression. Note 9.9/10.

**4 avril 2026** — Dashboard distant Phase 1 (infra) : handler fichiers statiques `GET /dashboard/*` dans `rest_server.py` avec garde anti path-traversal (resolution + verification prefix), fallback `/dashboard/` → `index.html`, MIME types etendus (woff2, svg, ttf, ico). Rate limiting 401 : `_RateLimiter` (5 echecs/IP/60s → 429, dict avec purge auto, thread-safe). Health enrichi avec `active_run_id` optionnel via `_find_active_run_id()`. Placeholder `web/dashboard/index.html` (CinemaLux tokens). CineSort.spec deja inclusif. 18 tests ajoutes (rate limiter unit, active_run_id, static files 200/404/traversal, rate limit HTTP, health enrichi). 548 tests total, 0 regression.

**4 avril 2026** — Dashboard distant Phase 2 (shell SPA + login) : SPA vanilla JS avec ES modules, hash router declaratif, guards auth. 9 fichiers crees dans `web/dashboard/` : `index.html` (shell avec login plein ecran + sidebar 6 vues + bottom tab bar mobile), `styles.css` (~300L, tokens CinemaLux complets, glass morphism, responsive 3 breakpoints : sidebar >=1024, collapse 768-1023, bottom tab <768, reduced motion, touch targets 44px), `app.js` (bootstrap, 7 routes), `core/dom.js` (helpers $, $$, escapeHtml, el), `core/state.js` (token session/localStorage avec checkbox persist, polling timers avec pause document.hidden), `core/api.js` (client fetch, Bearer auto, 401→redirect login, 429→message retry, testConnection), `core/router.js` (hash router, registerRoute, requireAuth guard, shell/login toggle), `views/login.js` (formulaire token password, checkbox "Rester connecte", spinner, validation via POST get_settings + GET health). Police Manrope-Variable.ttf embarquee (pas de CDN). 26 tests ajoutes (HTTP: CSS/JS/font MIME, structure HTML, login flow; structure: fichiers, tokens CSS, responsive, ES modules, XSS escaping, auth guard, polling, routes). 574 tests total, 0 regression.

**4 avril 2026** — Dashboard distant Phase 3 (Status + Logs) : 2 composants reutilisables + 2 vues. `components/kpi-card.js` (carte KPI avec icone SVG Lucide, label, valeur, tendance fleche up/down/stable, couleur conditionnelle, suffix). `components/badge.js` (badges tier Premium/Bon/Moyen/Mauvais, confiance High/Med/Low, statut ok/running/error/cancelled, fallback neutre, scoreBadgeHtml avec seuils 85/68/54). `views/status.js` (page d'accueil : KPIs via Promise.all(health + get_global_stats + get_settings + get_probe_tools_status), run en cours avec barre de progression + ETA + speed, sante (probe, jellyfin, roots), actions rapides start_plan/cancel_run, polling adaptatif 2s run actif / 15s idle). `views/logs.js` (logs live : zone scrollable monospace avec auto-scroll, polling get_status(run_id, last_log_index) 2s, barre de progression, bouton annuler, detection fin de run, classes log-error/log-warn/log-end). CSS enrichi : progress-bar, logs-box, kpi-suffix/kpi-header/kpi-icon/kpi-trend, status-health-list. index.html + app.js mis a jour (conteneurs statusContent/logsContent, imports initStatus/initLogs). 52 tests ajoutes (structure KPI/badge/status/logs, CSS phase 3, HTTP fichiers + endpoints). 626 tests total, 0 regression.

**4 avril 2026** — Dashboard distant Phase 4 (Library + Runs) : 2 composants reutilisables + 2 vues. `components/table.js` (table generique sortable : colonnes declaratives [{key, label, sortable, render}], tri client asc/desc/none avec localeCompare + numerique, lignes cliquables data-row-idx, scroll horizontal mobile, escapeHtml). `components/modal.js` (modale : overlay backdrop blur, fermeture clic exterieur + Escape, aria-modal, mode confirmation 2 boutons + mode detail contenu libre, mobile plein ecran). `views/library.js` (bibliotheque films : table 8 colonnes avec badges tier/confiance, recherche texte debounce 300ms, filtres toggle par tier, bar chart SVG distribution tiers, modale detail film avec probe/score/sous-titres/warnings, donnees via get_dashboard). `views/runs.js` (historique runs : table 6 colonnes sortable, timeline SVG barres colorees par tier, export CSV/HTML/JSON via export_run_report + download Blob/createObjectURL, donnees via get_global_stats). CSS enrichi : modal-overlay/card/header/body/actions avec animations, th-sortable/sort-asc/sort-desc, btn-filter/active, search-input, tier-chart, runs-timeline, detail-grid/row/label, modal plein ecran mobile. 61 tests ajoutes. 687 tests total, 0 regression.

**5 avril 2026** — Dashboard distant Phase 5 (Review triage distant) : vue `views/review.js` (~310L). Table triage 7 colonnes (titre, annee, ancien/nouveau chemin, confiance badge, alertes, actions approve/reject). Boutons approve/reject avec icones SVG inline, toggle 3 etats (approved/rejected/null), lignes colorees (.row-approved vert, .row-rejected rouge). Compteurs live (approuve/rejete/en attente). Actions bulk : approuver les surs (confiance >= seuil auto_approve_threshold), tout rejeter, reinitialiser. Preview impact via check_duplicates → modale avec conflits. Sauvegarder via save_validation. Apply en 2 etapes : dry-run obligatoire → modale confirmation avec resume → apply reel. Chargement decisions existantes via load_validation au mount. Detection run via /api/health active_run_id avec fallback get_global_stats. CSS enrichi (~50L) : review-bulk-bar, review-action-bar, review-counters, btn-review (36px desktop, 44px mobile), btn-approve/reject avec hover/active, row-approved/rejected avec border-left coloree, action-bar sticky bottom mobile. 46 tests ajoutes. 733 tests total, 0 regression.

**5 avril 2026** — Dashboard distant Phase 6 (Jellyfin + Polish final) : vue `views/jellyfin.js` (~160L). Guard jellyfin_enabled → message "non configure" si desactive. KPIs (statut connecte/deconnecte, films, serveur, version). Infos connexion (URL, utilisateur, admin, refresh auto, sync watched). Liste bibliotheques Jellyfin (nom, type, items). Boutons test connexion + rafraichir. Nav dynamique : onglet Jellyfin masque si desactive (setNavVisible dans router.js, _checkJellyfinNav dans app.js). CSS enrichi : jellyfin-lib-list, hover glow desktop only (hover:hover media query). Plus aucun placeholder "en construction" dans le HTML. 19 fichiers dashboard, 4 composants, 7 vues. 41 tests ajoutes. 774 tests total, 0 regression. **Dashboard distant complet.**

**5 avril 2026** — Profils de renommage Phases A+B : module `cinesort/domain/naming.py` (~240L). 5 presets (default, plex, jellyfin, quality, custom). 20 variables template ({title}, {year}, {resolution}, {video_codec}, {hdr}, {audio_codec}, {channels}, {quality}, {score}, {tmdb_id}, {tmdb_tag}, {original_title}, {source}, {bitrate}, {container}, {series}, {season}, {episode}, {ep_title}). `{tmdb_tag}` produit `{tmdb-27205}` (accolades literales). Variables manquantes → chaine vide + nettoyage separateurs orphelins ([], (), espaces doubles). `validate_template()` verifie variables connues, accolades equilibrees, presence title/series. `check_path_length()` warning si > 240 chars. `PREVIEW_MOCK_CONTEXT` hardcode (Inception). Config enrichi : `naming_movie_template` + `naming_tv_template` avec defauts `{title} ({year})` / `{series} ({year})`. Injection dans `apply_core.py` : 3 f-strings remplaces par `format_movie_folder()`/`format_tv_series_folder()` (apply_single, apply_collection_item, apply_tv_episode). Propagation via `build_cfg_from_settings`. 44 tests ajoutes (presets, variables manquantes, Windows safe, validation, fallback, tmdb_tag, path length, contexte, preview mock). 818 tests total, 0 regression.

**5 avril 2026** — Profils de renommage Phases C+D+F : conformance check `folder_matches_template()` dans naming.py (comparaison normalisee template vs dossier), `single_folder_is_conform()` enrichi avec `naming_template` kwarg (check template actif + fallback regex historique), `_single_folder_is_conform` dans core.py propage le template, `apply_single` passe `cfg.naming_movie_template`. Settings : `naming_preset` dans defaults (5 valeurs), `_apply_naming_preset()` ecrase templates si preset != custom, valide templates custom via `validate_template()`, fallback si invalide. Endpoints : `preview_naming_template(template, sample_row_id?)` avec mock Inception par defaut, `get_naming_presets()` retourne les 5 profils. 23 tests ajoutes (conformance 12, settings 5, preview 6). 841 tests total, 0 regression.

**5 avril 2026** — Profils de renommage Phases G+H+I (fin 9.1) : UI desktop settings section "Profil de renommage" dans index.html (dropdown 5 presets, inputs template film/serie, zone preview live, liste variables). JS settings.js : `_NAMING_PRESETS` local, `_loadNamingPreset`, `_onPresetChange` (ecrase templates sauf custom), `_hookNamingEvents`, `_fetchNamingPreview` (debounce 300ms via `preview_naming_template`), inputs readOnly sauf custom, `gatherSettingsFromForm` inclut naming. CSS naming-preview. Dashboard status.js : profil actif affiche dans sante (label + template si custom). 24 tests ajoutes (HTML structure 7, JS structure 10, CSS 2, dashboard 3, HTTP 3). 865 tests total, 0 regression. **Item 9.1 complet.**

**5 avril 2026** — Comparaison qualite doublons Phases A+B+C (item 9.2) : module `cinesort/domain/duplicate_compare.py` (~240L). 7 criteres ponderes (resolution 30pts, HDR 20pts, codec video 15pts, audio codec 15pts, canaux audio 10pts, bitrate 5pts si meme codec, taille 0pts informatif). Dataclasses `CriterionResult` et `ComparisonResult`. `compare_duplicates(probe_a, probe_b)` retourne winner/tie + criteres detailles + recommendation + size_savings. `rank_duplicates(files[])` pour 3+ fichiers. `determine_winner()` avec seuil tie ±5pts. Injection dans `check_duplicates()` via `_enrich_groups_with_quality_comparison()` dans run_flow_support.py — charge les quality_reports depuis la BDD, reconstitue les probes, enrichit chaque group avec un champ `comparison` optionnel. 29 tests ajoutes (resolution, HDR, codec, audio, bitrate, egalite, probes manquantes, ranking 3 fichiers, ponderations, structure, edge cases). 894 tests total, 0 regression.

**5 avril 2026** — Comparaison qualite doublons Phases D+E+F (fin 9.2) : UI desktop `execution.js` enrichie avec vue cote-a-cote dans modale (`_buildComparisonHtml`, `_criterionBadge`, `_formatFileSize`). Table 3 colonnes (Critere / Fichier A / Fichier B), badges winner vert, score et recommendation affiches, economie potentielle en Ko/Mo/Go, modale `modalCompare` dans index.html. Fallback sans comparison (ancienne vue preservee). Dashboard `review.js` : `_buildDashComparisonHtml` + `_fmtSize` dans `_onPreview()`, meme vue cote-a-cote dans la modale, badges badge-success. CSS : `.compare-table`, `.compare-score`, `.compare-winner` dans app + dashboard. 30 tests ajoutes (desktop structure 12, HTML 3, CSS 3, dashboard 10, dashboard CSS 2). 924 tests total, 0 regression. **Item 9.2 complet.**

**5 avril 2026** — Detection contenu non-film (item 9.3) : fonction `not_a_movie_score()` dans `scan_helpers.py` (~60L). 6 heuristiques avec scoring par points (seuil 60) : nom suspect +40 (12 mots-cles : sample, trailer, bonus, making, featurette, interview, deleted, extra, behind, teaser, demo, promo), taille < 100Mo +30, taille 100-300Mo +15, pas de match TMDb +25, titre ≤ 3 mots +10, extension .m2ts/.ts/.vob +10. Constantes nommees. Injection dans `plan_support.py` : appel apres PlanRow creation, flag `not_a_movie` dans warning_flags si score ≥ 60. UI desktop `validation.js` : badge orange "Non-film ?" avec tooltip. Dashboard `review.js` : badge "Non-film" dans colonne alertes. CSS badge `.badge--not-a-movie` / `.badge-not-a-movie` (orange #FB923C). 33 tests ajoutes (6 heuristiques isolees, 5 combinaisons, 3 seuils, 3 edge cases, 5 UI + CSS, 11 fonctionnels). 957 tests total, 0 regression. **Item 9.3 complet.**

**5 avril 2026** — Verification integrite fichiers (item 9.4) : module `cinesort/domain/integrity_check.py` (~80L). Verification magic bytes pour 5 formats : MKV (EBML 1A 45 DF A3), MP4/MOV (ftyp offset 4), AVI (RIFF + AVI offset 8), MPEG-TS (3 sync bytes 0x47 a intervalles 188), WMV/ASF (30 26 B2 75...). `check_header(path)` → (is_valid, detail). Extensions inconnues → skip silencieux. Injection dans `plan_support.py` : flag `integrity_header_invalid` au scan. Enrichissement probe : `quality_report_support.py` ajoute `integrity_probe_failed` si probe_quality == FAILED. UI desktop `validation.js` : badge rouge "Corrompu ?" + tooltip. Dashboard `review.js` : badge "Corrompu". CSS `.badge--integrity` / `.badge-integrity` (rouge #EF4444). 23 tests ajoutes (5 formats valides, 3 invalides, 6 edge cases, 5 UI). 980 tests total, 0 regression. **Item 9.4 complet.**

**5 avril 2026** — Collections automatiques TMDb (item 9.5) : TMDb client enrichi `_get_movie_detail_cached()` dans `tmdb_client.py` (refactoring poster + extraction `belongs_to_collection` depuis `/movie/{id}`, cache unifie). `get_movie_collection(movie_id)` retourne `(collection_id, collection_name)`. Candidate + PlanRow enrichis avec `tmdb_collection_id` + `tmdb_collection_name`. Propagation dans `plan_support.py` : appel `tmdb.get_movie_collection(chosen.tmdb_id)` apres selection candidat. Deserialization enrichie (`plan_row_from_jsonable`). Apply enrichi dans `apply_single()` : si `tmdb_collection_name` + `collection_folder_enabled` → destination `root/_Collection/SagaName/Film (Annee)/`. UI desktop `validation.js` : badge violet "Saga" avec tooltip nom collection. Dashboard `review.js` : badge violet "Saga" dans colonne titre. CSS `.badge--saga` / `.badge-saga` (violet #A855F7). 22 tests ajoutes (TMDb client 6, Candidate 2, PlanRow 2, deserialization 4, apply 4, UI 4). 1002 tests total, 0 regression. **Item 9.5 complet.**

**5 avril 2026** — Detection re-encode / upgrade suspect (item 9.6) : module `cinesort/domain/encode_analysis.py` (~60L). Fonction `analyze_encode_quality(detected)` retourne les flags `upscale_suspect` (bitrate trop bas pour la resolution : 4K HEVC < 3500 kbps, 4K H264 tout bitrate, 1080p HEVC < 1500 kbps, 1080p H264 < 2000 kbps, 720p < 1000 kbps), `4k_light` (4K HEVC/AV1 entre 3500-25000 kbps, mutuellement exclusif avec upscale), `reencode_degraded` (bitrate extremement bas : 1080p HEVC < 800 kbps, 1080p H264 < 1000 kbps, 720p < 500 kbps, SD < 300 kbps). Injection dans `quality_report_support.py` : champ `encode_warnings` dans le resultat. UI desktop `validation.js` : badges rouge "Upscale ?", orange "4K light", rouge "Re-encode". Dashboard `review.js` : memes badges. CSS `.badge--upscale`, `.badge--4k-light`, `.badge--reencode`. 33 tests ajoutes (upscale 6, pas upscale 4, 4K light 4, re-encode 5, guards 6, UI 8). 1035 tests total, 0 regression. **Item 9.6 complet.**

**5 avril 2026** — Analyse audio approfondie (item 9.7) : probe enrichie dans `normalize.py` (+champs `title` et `is_commentary` sur les pistes audio, extraction tags.title ffprobe + disposition.comment + Title mediainfo). Module `cinesort/domain/audio_analysis.py` (~120L). `analyze_audio(audio_tracks)` retourne best_format, best_channels, badge_label, badge_tier (premium/bon/standard/basique), tracks_count, has_commentary, duplicate_tracks, languages. Hierarchie : Atmos(6) > TrueHD(5) > DTS-HD MA(4) > EAC3/FLAC(3) > DTS/AC3(2) > AAC/MP3(1). Detection Atmos : truehd + title contient "atmos". Detection commentaire : disposition.comment OU title "commentary/commentaire". Detection doublons : ignore paires compat (TrueHD+AC3), flagge 2×meme codec meme langue. Injection `quality_report_support.py` : champ `audio_analysis` + flag `audio_duplicate_track`. UI desktop `validation.js` : badge audio colore (or/vert/bleu/gris par tier). Dashboard `review.js` : meme badge. CSS 4 tiers `.badge--audio-premium/bon/standard/basique`. 37 tests ajoutes (format 10, canaux 4, commentaire 3, doublons 4, badge 4, edge 4, probe 1, UI 7). 1072 tests total, 0 regression. **Item 9.7 complet.**

**5 avril 2026** — Espace disque intelligent (item 9.8) : metrics quality enrichies avec `duration_s` et `file_size_bytes` (calcul `_estimate_file_size` depuis duration × bitrate). `_compute_space_analysis()` dans `dashboard_support.py` (~50L) : agregation depuis quality reports (total_bytes, avg_bytes, by_tier, by_resolution, by_codec, archivable). Top 10 gaspilleurs avec formule `waste_score = size_gb × (100 - score) / 100`. Enrichissement `get_global_stats()` avec bloc `space_analysis`. Dashboard `status.js` : section "Espace disque" avec KPIs (total/moyenne/recuperable), bar chart SVG par tier, table top 5 gaspilleurs. Desktop `quality.js` : section espace dans panel Bibliotheque avec bar chart par tier. CSS space-bars (track/fill/label/value) dans app + dashboard. HTML conteneur `globalSpaceSection`. 21 tests ajoutes (file_size 4, space analysis 8, UI 8, waste formula 1). 1093 tests total, 0 regression. **Item 9.8 complet.**

**5 avril 2026** — Mode bibliothecaire (item 9.9) : module `cinesort/domain/librarian.py` (~100L). `generate_suggestions(rows, quality_reports, settings)` retourne 6 suggestions triees par priorite : codec_obsolete (haute, mpeg4/xvid/divx/wmv/mpeg2), duplicates (haute, warning flags duplicate), missing_subtitles (moyenne, subtitle_missing_langs × langue cible), unidentified (moyenne, proposed_source unknown OU confidence 0), low_resolution (basse, SD height < 680), collections_info (basse, informatif TMDb sagas). Health score = 100 × (films sans probleme / total). Injection `_compute_librarian_suggestions()` dans `dashboard_support.py` → bloc `librarian` dans `get_global_stats()`. Dashboard `status.js` : section Suggestions avec health score colore + liste cartes suggestion (badge priorite, message, details). Desktop `quality.js` : meme section dans panel Bibliotheque. HTML conteneur `globalLibrarianSection`. CSS `.suggestions-list`, `.suggestion-card`. 21 tests ajoutes (codec 2, doublons 2, sous-titres 2, non identifies 2, resolution 2, collections 1, priorite 1, health 3, edge 1, UI 6). 1114 tests total, 0 regression. **Item 9.9 complet.**

**5 avril 2026** — Sante bibliotheque continue (item 9.10) : snapshot sante persiste dans `stats_json.health_snapshot` a la fin de chaque run (health_score + subtitle_coverage_pct + resolution_4k_pct + codec_modern_pct). `_compute_subtitle_coverage()` dans `run_flow_support.py`. Timeline enrichi dans `get_global_stats()` : chaque point inclut health_score si snapshot disponible (null sinon). `_compute_health_trend()` dans `dashboard_support.py` : delta entre les 2 derniers runs avec snapshot (fleche ↑/↓/→ + message). `get_runs_summary()` enrichi avec `health_snapshot`. Dashboard `status.js` : section "Tendance sante" avec line chart SVG (polyline + fill accent semi-transparent), delta colore. Desktop `quality.js` : meme graphe dans panel Bibliotheque. HTML conteneur `globalHealthTrend`. CSS `.health-chart`. 18 tests ajoutes (trend 7, subtitle coverage 3, snapshot 1, UI 7). 1132 tests total, 0 regression. **Item 9.10 complet. Tier B complet (5/5 items).**

**5 avril 2026** — Suppression shims legacy Lot 1 (item 9.17 partiel) : 6 shims racine supprimes (`core_title_helpers.py`, `core_duplicate_support.py`, `core_plan_support.py`, `core_apply_support.py`, `core_cleanup.py`, `core_scan_helpers.py`). Tous les importeurs migres vers imports directs `cinesort.*` (8 fichiers modifies : `cinesort/domain/core.py`, `cinesort/app/apply_core.py`, `tests/test_error_resilience.py`, `tests/test_core_heuristics.py`, `tests/test_scan_streaming.py`). 1132 tests, 0 regression.

**5 avril 2026** — Suppression shims legacy Lot 2 (item 9.17 suite) : 2 shims racine supprimes (`tmdb_client.py`, `state.py`). 20 importeurs migres vers imports directs (9 fichiers pour tmdb_client : `cinesort/domain/core.py`, `cinesort/app/plan_support.py`, 4 modules `cinesort/ui/api/`, 3 tests ; 11 modules `cinesort/ui/api/` pour state). Mocks `test_tmdb_client.py` mis a jour (`"tmdb_client.requests.get"` → `"cinesort.infra.tmdb_client.requests.get"`). 1132 tests, 0 regression.

**5 avril 2026** — Suppression shims legacy Lot 3 (item 9.17 fin) : 2 derniers shims supprimes (`backend.py`, `core.py`). `backend.py` : 23 importeurs migres (app.py + 22 tests) via `from cinesort.ui.api.cinesort_api import CineSortApi` ou alias `as backend`. `core.py` : ~40 references migrees (7 modules cinesort/app/, 7 modules cinesort/ui/api/, 14 tests, 3 imports locaux test_tmdb_collections) via `import cinesort.domain.core as core` ou `as core_mod`. **Plus aucun shim racine. Item 9.17 complet.** 1132 tests, 0 regression.

**5 avril 2026** — Coverage HTML dans la CI (item 9.19) : 2 steps ajoutes dans `.github/workflows/ci.yml` apres le seuil coverage 80%. Step 9 : `python -m coverage html -d coverage_html`. Step 10 : `actions/upload-artifact@v4` (name `coverage-report`, retention 14 jours). Pas de Codecov (zero dependance externe). Le rapport HTML est telechargeable depuis la page Actions de chaque run. **Item 9.19 complet.**

**5 avril 2026** — Refresh auto dashboard apres apply (item 9.21) : `CineSortApi._last_event_ts` (float) mis a jour dans `save_settings`, `apply` (non dry-run) et fin de scan (thread job_fn). Expose dans `GET /api/health` comme `last_event_ts`. Dashboard `state.js` : `checkEventChanged(serverTs)` compare avec `_lastEventTs` local. `status.js` : le polling idle (15s) utilise `_pollIdleWithEventCheck` qui appelle health et declenche `_loadAll()` si l'evenement a change. Pas de WebSocket/SSE — simple check sur le health existant. 8 tests ajoutes. 1140 tests total, 0 regression. **Item 9.21 complet.**

**5 avril 2026** — HTTPS dashboard (item 9.20) : `RestApiServer` accepte `https_enabled`, `cert_path`, `key_path`. Si active + cert/key valides → `ssl.SSLContext(PROTOCOL_TLS_SERVER)` wrappe le socket. Si cert manquant → fallback HTTP + log warning. 3 settings ajoutes (`rest_api_https_enabled`, `rest_api_cert_path`, `rest_api_key_path`) avec defaults + normalisation. `app.py` propage les params dans les 2 modes (GUI + standalone). L'utilisateur genere son cert avec `openssl req -x509 ...`. 6 tests ajoutes (fallback 3, HTTPS reel 1, settings 2). 1146 tests total, 0 regression. **Item 9.20 complet.**

**5 avril 2026** — Detection langue audio incoherente (item 9.27) : `_check_language_coherence()` dans `audio_analysis.py` detecte les pistes sans tag langue (vide, null, "und", "unk") et l'incompletude (certaines taguees, d'autres non). Pistes commentaire ignorees. 2 champs ajoutes dans `analyze_audio()` : `missing_language_count` (int), `incomplete_languages` (bool). 2 warnings injectes via `quality_report_support.py` : `audio_language_missing`, `audio_language_incomplete`. Badge jaune "Langue ?" dans validation.js + review.js. CSS `.badge--audio-lang` / `.badge-audio-lang` (#FBBF24). 11 tests ajoutes (coherence 7, UI 4). 1157 tests total, 0 regression. **Item 9.27 complet.**

**5 avril 2026** — Conflit metadonnees MKV (item 9.23) : extraction du titre conteneur MKV/MP4 via probe (`container_title` dans NormalizedProbe). Sources : `format.tags.title` (ffprobe), `general.Title` ou `general.Movie` (mediainfo). Module `cinesort/domain/mkv_title_check.py` : `check_container_title()` compare le titre conteneur avec `proposed_title` (case-insensitive). `_is_scene_title()` detecte les titres scene (6 patterns regex, seuil 2). Warning `mkv_title_mismatch` injecte dans `quality_report_support.py`. Badge jaune "MKV titre" dans validation.js + review.js. 21 tests ajoutes (detection 8, scene 4, extraction 5, UI 4). 1178 tests total, 0 regression. **Item 9.23 complet (Phase 1 detection). Nettoyage mkvpropedit prevu Phase 2.**

**5 avril 2026** — Editions multiples / Multi-version (item 9.22) : module `cinesort/domain/edition_helpers.py` — `extract_edition()` (12 groupes d'editions, regex compile), `strip_edition()` (retrait avant matching TMDb). `PlanRow.edition: Optional[str]`. Injection au scan dans `plan_support.py` (extract edition, strip avant queries TMDb, propagation dans PlanRow). Naming : variables `{edition}` (label simple) et `{edition-tag}` (format Plex `{edition-Director's Cut}`), `_VAR_RE` accepte les tirets. Dedup edition-aware : `movie_key()` inclut l'edition dans la cle → meme film + editions differentes = pas un doublon. Badge violet dans validation.js + review.js (`.badge--edition` / `.badge-edition` #A78BFA). 29 tests ajoutes (detection 8, stockage 4, naming 5, doublons 4, UI 4, integration 4). 1207 tests total, 0 regression. **Item 9.22 complet.**

**5 avril 2026** — Historique par film (item 9.13) : module `cinesort/domain/film_history.py` — `film_identity_key(row)` (priorite tmdb_id puis titre+annee, avec edition), `get_film_timeline(film_id, state_dir, store)` reconstruit les events (scan/score/apply) depuis plan.jsonl + quality_reports + apply_operations. Zero nouvelle table SQL — reconstruction a la volee. `list_films_overview()` pour la liste des films du dernier run. Endpoints `get_film_history` + `list_films_with_history` dans cinesort_api.py via `film_history_support.py`. UI desktop : bouton "Historique" dans l'inspecteur, timeline verticale avec icones/delta score. UI dashboard : bouton dans la modale detail film, meme timeline. CSS timeline (`.timeline-container`, `.timeline-event`, delta colore). 21 tests ajoutes (identite 5, timeline 6, API 4, UI 4, edge 2). 1228 tests total, 0 regression. **Item 9.13 complet.**

**5 avril 2026** — Mode planifie / Watch folder (item 9.11) : module `cinesort/app/watcher.py` — `FolderWatcher(threading.Thread, daemon=True)`. Poll `os.scandir` niveau 1 toutes les N minutes. Snapshot initial sans scan (snapshot de reference). Detection changements par comparaison `name|mtime_ns`. Si change ET pas de scan en cours → `api.start_plan(settings)` automatique. Skip si scan deja actif. Arret propre via `Event.set()`. Settings : `watch_enabled` (bool, False), `watch_interval_minutes` (int, 1-60, defaut 5). Toggle dynamique dans `save_settings` (`_sync_watcher`). Integration `app.py` : start apres REST, stop au shutdown. UI desktop : toggle + intervalle dans settings. Dashboard : indicateur "Veille active (5 min)" dans la section sante. CSS `.watcher-status` / `.watcher-status--active`. 15 tests ajoutes (snapshot 4, changed 3, lifecycle 3, settings 2, UI 3). 1243 tests total, 0 regression. **Item 9.11 complet.**

**5 avril 2026** — Plugin hooks post-action (item 9.15) : module `cinesort/app/plugin_hooks.py` — `discover_plugins()` (scan dossier `plugins/`, extensions .py/.bat/.ps1), `dispatch_hook()` (thread daemon, non-bloquant), `_run_plugin()` (subprocess.run, stdin JSON, env vars CINESORT_EVENT/CINESORT_RUN_ID, timeout). Convention nommage : `post_scan_xxx.py` → post_scan seul, `any_xxx.py` → tous, `xxx.py` → tous. 4 evenements : post_scan, post_apply, post_undo (si done>0), post_error. Injection dans `run_flow_support.py`, `apply_support.py`, `cinesort_api.py`. `_dispatch_plugin_hook()` helper dans CineSortApi avec guard `plugins_enabled`. Settings `plugins_enabled` (False), `plugins_timeout_s` (30, 5-120). UI section Plugins dans settings. 15 tests ajoutes (decouverte 3, convention 5, execution 4, settings 2, UI 1). 1258 tests total, 0 regression. **Item 9.15 complet.**

**5 avril 2026** — Rapport par email (item 9.16) : module `cinesort/app/email_report.py` — `send_email_report()` (smtplib stdlib, MIME texte brut), `dispatch_email()` (thread daemon non-bloquant). Support SMTP (port 587 + STARTTLS) et SMTP_SSL (port 465). 9 settings email (host, port, user, password, tls, to, on_scan, on_apply, enabled). `_dispatch_email()` helper dans CineSortApi. Injection post_scan + post_apply (memes points que plugin hooks). Endpoint `test_email_report()` avec donnees mock. UI section "Rapport par email" dans settings (tous les champs SMTP + checkboxes triggers). 14 tests ajoutes (construction 4, SMTP mock 4, guards 2, settings 2, endpoint+UI 2). 1272 tests total, 0 regression. **Item 9.16 complet.**

**5 avril 2026** — Validation croisee Jellyfin (item 9.26) : `get_all_movies()` enrichi avec `ProductionYear` + `ProviderIds` (year, tmdb_id). Module `cinesort/app/jellyfin_validation.py` — `build_sync_report()` matching 3 niveaux (chemin normalise → tmdb_id → titre+annee). Rapport : matched, missing_in_jellyfin, ghost_in_jellyfin, metadata_mismatch. Endpoint `get_jellyfin_sync_report(run_id)` dans cinesort_api.py. Dashboard `jellyfin.js` : bouton "Verifier la coherence" + section resultats (KPI sync-ok/warn/error + tables manquants/fantomes/divergents). CSS `.sync-ok`/`.sync-warn`/`.sync-error`. 13 tests ajoutes (enrichi 2, matching 5, rapport 3, endpoint+UI 3). 1285 tests total, 0 regression. **Item 9.26 complet.**

**5 avril 2026** — Watchlist Letterboxd/IMDb (item 9.12) : module `cinesort/app/watchlist.py` — `parse_letterboxd_csv()`, `parse_imdb_csv()` (parsing CSV stdlib), `_normalize_title()` (lowercase, strip accents unicodedata, retrait articles initiaux The/Le/La/Les/A/An/L'), `compare_watchlist()` (matching titre+annee normalise). Rapport : owned, missing, coverage_pct. Endpoint `import_watchlist(csv_content, source)` dans cinesort_api.py — charge PlanRows du dernier run, compare. UI desktop : section Watchlist dans settings (boutons file picker Letterboxd/IMDb via FileReader, resultats KPI + table manquants). UI dashboard : section dans library.js (meme logique). 18 tests ajoutes (parsing 4, normalisation 3, matching 9, endpoint+UI 2). 1303 tests total, 0 regression. **Item 9.12 complet.**

**5 avril 2026** — Integration Plex (item 9.14) : module `cinesort/infra/plex_client.py` — `PlexClient` HTTP direct avec `X-Plex-Token`. `validate_connection()` via GET /identity. `get_libraries("movie")` via GET /library/sections. `get_movies(library_id)` via GET /library/sections/{id}/all (extraction Guid→tmdb_id, Media.Part.file→path). `refresh_library(library_id)` via GET /library/sections/{id}/refresh. 6 settings (plex_enabled, plex_url, plex_token, plex_library_id, plex_refresh_on_apply, plex_timeout_s). `_trigger_plex_refresh()` dans apply_support (symetrique Jellyfin). Endpoints `test_plex_connection`, `get_plex_libraries`, `get_plex_sync_report` (reutilise `build_sync_report`). UI desktop : section Plex dans settings (toggle, URL, token, dropdown libraries dynamique, refresh toggle). Dashboard : indicateur Plex dans status.js. Coexistence Jellyfin+Plex supportee. 16 tests ajoutes (client 4, refresh 2, sync 2, endpoints 3, settings 2, UI 3). 1319 tests total, 0 regression. **Item 9.14 complet. Tier C complet (6/6 items).**

**5 avril 2026** — Integration Radarr bidirectionnelle (item 9.25) : module `cinesort/infra/radarr_client.py` — `RadarrClient` API v3 (X-Api-Key). `validate_connection()` via GET /api/v3/system/status. `get_movies()` avec tmdb_id, path, quality_name, monitored, has_file. `get_quality_profiles()`. `search_movie(movie_id)` via POST /api/v3/command MoviesSearch. Module `cinesort/app/radarr_sync.py` — `build_radarr_report()` matching 3 niveaux (tmdb_id, chemin, titre+annee), `should_propose_upgrade()` (score<54 OU upscale_suspect/reencode_degraded OU codec obsolete xvid/divx/wmv, ET monitored), `get_upgrade_candidates()`. Endpoints `test_radarr_connection`, `get_radarr_status`, `request_radarr_upgrade`. 4 settings (radarr_enabled, radarr_url, radarr_api_key, radarr_timeout_s). UI desktop section Radarr dans settings + test connexion. Dashboard indicateur Radarr. 20 tests ajoutes. 1339 tests total, 0 regression. **Item 9.25 complet.**

**5 avril 2026** — Audit post-V3 + corrections : note 9.7/10. 5 findings corriges : M1 — `log()` et `progress()` ajoutes dans `_EXCLUDED_METHODS` (rest_server.py). M2 — 13 modules V3 lazy-importes ajoutes dans `hiddenimports` (CineSort.spec). M3 — `_normalize_path()` extraite dans `cinesort/app/_path_utils.py`, 3 copies remplacees (jellyfin_validation, radarr_sync, jellyfin_sync). C2 — commentaire HTML documente dans dashboard modal.js. 1339 tests, 0 regression.

**6 avril 2026** — Tests Playwright E2E dashboard (item 9.18) : 121 tests dans `tests/e2e/` (13 fichiers). 4 phases : login+infra (10), navigation+status+library+runs (40), review+jellyfin (20), cross-cutting responsive+visual+perf+a11y+errors+console (51). Page Object Model : 7 pages (base, login, status, library, runs, review, jellyfin). 3 viewports testes (desktop 1280, tablet 768, mobile 375). 15 films mock deterministes + 2 runs + quality reports + perceptual reports. Serveur REST auto-contenu (session-scoped, polling health). 5 bugs app corriges : dashboard library sans rows (C1), runs_summary alias manquant (C2), review.js `row` non defini (C4), row_from_json sans champs V3 (C5), rate limiter bloquant entre tests (C7). Screenshots baselines generes dans 3 viewports × 3 vues. 1518 unitaires + 121 E2E, 0 regression. **Item 9.18 complet.**

**6 avril 2026** — Analyse qualite perceptuelle (item 9.24) : 9 phases, package `cinesort/domain/perceptual/` (7 modules, ~1500L). Phase I : infrastructure (constants, models, ffmpeg_runner, DB migration 009, _PerceptualMixin, 11 settings). Phase II-A : frame_extraction (timestamps deterministes, extraction raw Y, validation, diversite, downscale 4K). Phase II-B : video_analysis (signalstats+blockdetect+blurdetect single-pass, histogramme, variance blocs, banding, bit depth effectif, consistance temporelle). Phase III : grain_analysis (estimation grain zones plates, classification ere TMDb, verdicts contextualises : grain_naturel/dnr_suspect/bruit_numerique/image_propre/artificiel). Phase IV : audio_perceptual (EBU R128 loudnorm, astats, clipping segments, selection meilleure piste par hierarchie). Phase V : composite_score (score visuel 6 metriques ponderees, score audio 5 metriques, global 60/40, 5 tiers, 10 verdicts croises inter-metriques). Phase VI : perceptual_support (orchestration single+batch, cache DB, enrichissement quality_report, 3 endpoints API). Phase VII : comparison (frames alignees, diff pixel, histogrammes, 8 criteres, rapport justifie FR). Phase VIII : UI desktop+dashboard (section settings 11 params, bouton analyse inspecteur, badges 5 tiers, verdicts croises, indicateur status). Phase IX : edge cases (film court, audio-only, video-only, probe FAILED, ffmpeg absent), stub calibration. Schema v9. 179 tests perceptuels ajoutes. 1518 tests total, 0 regression. **Item 9.24 complet.**

**6 avril 2026** — Logging V4 structure : audit complet des 5 couches (133 fichiers, 68% sans logging). 5 phases d'implementation : (1) Infra critique — REST server request/response logging avec timing, 4 clients HTTP (TMDb, Jellyfin, Plex, Radarr) avec log request/response, migrations DB avec trace. (2) App critique — apply_core audit trail (debut/fin/erreurs), plan_support trace scan, job_runner thread lifecycle, cleanup/export. (3) Domain — scoring quality_score debug, duplicate_compare, audio_analysis, encode_analysis, integrity_check, mkv_title_check, scan_helpers not_a_movie, perceptual pipeline (ffmpeg_runner, video_analysis, grain_analysis, audio_perceptual, composite_score). (4) UI/API — start_plan, apply, undo logs, dead imports corrigés (naming.py, history_support.py). (5) JS Frontend — router navigation logging, api.js timing succès, dashboard api.js logging complet, review/validation/settings/login actions utilisateur. ~39 fichiers modifiés, ~300L ajoutées. Format uniforme : logging stdlib, DEBUG pour details, INFO pour actions, WARNING pour anomalies. 1518 tests, 0 regression.

**6 avril 2026** — Quality of Life V4 (4 items) : (1) Auto-detection IP locale via UDP socket (`network_utils.py`), URL dashboard affichee dans les reglages + endpoint `get_server_info()`, log au demarrage REST. (2) Redemarrage serveur REST a chaud : `restart_api_server()` sans fermer l'EXE, bouton dans les reglages. (3) Bouton refresh dashboard : SVG dans la sidebar, animation rotation CSS, interception F5. (4) Bouton copier le lien dashboard : clipboard API, hint mobile. QR code non implemente (trop lourd en 0-dep). 2 fichiers crees, 8 modifies, 12 tests ajoutes. 1530 tests, 0 regression.

**6 avril 2026** — Splash screen HTML pywebview (V4.6) : remplacement complet du splash Win32 ctypes (qui ne se fermait pas toujours, fallback 8s) par un splash HTML via pywebview. Nouveau fichier `web/splash.html` (design CinemaLux, gradient, logo glow, barre de progression animee CSS, 7 etapes). Flow app.py reecrit : 2 fenetres pywebview (splash frameless 520x320 on_top + main hidden), fonction `_startup()` passee a `webview.start()`, progression via `evaluate_js("updateProgress(...)")`, `main_window.show()` + `splash.destroy()` a la fin. Runtime hook simplifie de 257L a 30L (suppression complete Win32 splash, conservation AllocConsole). ~220L Win32 supprimees, ~160L ajoutees, 8 tests. 1538 tests, 0 regression.

**6 avril 2026** — Dependances V4 (segno + rapidfuzz, 4 items) : (1) segno QR code — endpoint `get_dashboard_qr()` retourne SVG inline CinemaLux, QR affiche dans les reglages desktop. Pure Python, MIT, 0 sous-dep. (2) rapidfuzz core — remplacement `difflib.SequenceMatcher` par `rapidfuzz.fuzz.ratio()` dans `title_helpers.py:seq_ratio()`. 5-100x plus rapide, compatibilite 0.0-1.0 preservee, toute la chaine scan/TMDb en profite automatiquement. (3) Fuzzy sync Jellyfin/Radarr — nouveau module `_fuzzy_utils.py` (normalize_for_fuzzy, fuzzy_title_match). Level 3 des sync reports enrichi avec fallback fuzzy (seuil 85). Gere accents, ponctuation, titres traduits. (4) Watchlist fuzzy — pass 2 `fuzz.token_sort_ratio()` pour rattraper les non-matches exact (ordre mots inverse, accents). Filtre annee strict. CineSort.spec + requirements.txt mis a jour. 5 fichiers crees, 6 modifies, 31 tests ajoutes. 1569 tests, 0 regression.

**6 avril 2026** — Ameliorations logiques metier V4 (6 items) : (A) TMDb lookup IMDb ID — `find_by_imdb_id()` dans tmdb_client.py via /find endpoint, .nfo avec IMDb ID cree un candidat score=0.95, fallback FR→EN si 0 resultat. (B) Scoring contextualise — bonus ere (patrimoine pre-1970 +8, classique pre-1995 +4), malus film recent post-2020 -4 (sauf AV1), penalites encode (upscale -8, reencode -6, 4k_light -3), penalite commentary-only -15. (C) Detection non-film — heuristique duree (<5min +35, <20min +25), 4 mots-cles (blooper, outtake, recap, gag reel). (D) Patterns TV — S01.E01 (point optionnel), "Season/Saison N Episode N" (texte FR/EN). (E) Integrite tail check — verification fin de fichier MP4 (moov atom) et MKV (fin non-nulle). (F) Doublons enrichis — critere perceptuel (poids 10) + critere sous-titres FR (poids 5). 5 fichiers crees, 8 modifies, 43 tests ajoutes. 1612 tests, 0 regression.

**6 avril 2026** — Systeme de themes V4 : 4 palettes atmospheriques (Studio bleu technique, Cinema rouge/or velours, Luxe noir mat/or, Neon violet/cyan cyberpunk). 3 niveaux animation (subtle/moderate/intense). 3 curseurs temps reel (vitesse effets, intensite glow, luminosite effets) via CSS custom properties. Fichier `web/themes.css` partage (~280L) avec palettes, effets atmospheriques par theme (grain pellicule Cinema, scan line Studio, shimmer dore Luxe, bordure neon rotative Neon), profondeur cards, reduced motion. 5 settings Python (theme, animation_level, effect_speed, glow_intensity, light_intensity) avec validation/clamp. Section "Apparence" dans les reglages desktop (dropdowns + sliders avec preview instantane). Dashboard charge le theme au login. 1628 tests, 0 regression.

**6 avril 2026** — Dashboard parite complete V4 (8 phases) : le dashboard distant passe de 6 a 10 vues avec parite fonctionnelle quasi-totale avec le desktop. (1) Page Reglages complete — 15 sections identiques au desktop (essentiel, TMDb, analyse video, renommage, Jellyfin, nettoyage, notifications, Plex, Radarr, surveillance, email, plugins, API REST, apparence, perceptuel). Boutons test connexion, preview renommage, curseurs apparence temps reel. (2) Sync temps reel settings — `last_settings_ts` dans health endpoint, detection changements via polling, theme synchronise desktop↔dashboard en < 5s. (3) Vue Qualite — KPIs, distribution tiers, timeline score, anomalies, activite recente. (4) Undo + Export NFO — bouton annulation dans review, export .nfo dans runs. (5) Inspecteur film enrichi — candidats TMDb, sous-titres detailles, edition, collection dans la modale. (6) Vues Plex + Radarr — guard enabled, KPIs connexion, test, validation croisee, candidats upgrade Radarr. (7) Raccourcis clavier — 1-8 navigation, Escape ferme modale, ? aide. (8) 26 tests parite. 7 fichiers crees, 8 modifies. 1654 tests, 0 regression.

**23 avril 2026** — v7.6.0 Refonte UI/UX totale (10 vagues, Design System v5) : session marathon suivant directement v7.5.0. Refonte complete de l'interface apres la consolidation du moteur perceptuel v7.5.0. Nouvelle architecture "data-first" — 1 palette unique + 4 themes atmospheriques (**Studio** bleu technique, **Cinema** rouge/or velours, **Luxe** noir mat/or, **Neon** violet/cyan cyberpunk) dont les couleurs de tier restent **invariantes** (test `test_themes_do_not_redefine_tiers`). **Vague 0 (Fondations)** : 5 fichiers `web/shared/` (tokens.css 280L, themes.css 180L, animations.css 180L avec 15 keyframes + `.stagger-item`, components.css 3550L avec v5-btn/card/badge/table/modal/toast, utilities.css 370L). Handler REST `/shared/*` pour supervision web. **Vague 1 (Navigation)** : `sidebar-v5.js` 7 entrees Alt+1-7 + collapse localStorage, `top-bar-v5.js` Cmd+K + notifications + theme switch, `breadcrumb.js`, wrapper `window.CommandPalette`. Router `parseRoute` + `buildBreadcrumb` + route `/film/:id`. **Vague 2 (Home)** : `home-widgets.js` + `home-charts.js` (donut SVG, line SVG), `_compute_v2_tier_distribution` + `_compute_trend_30days` + `_compute_active_insights` dans `dashboard_support.py`, +4 methodes `_perceptual_mixin.py`. **Vague 3 (Library)** : `library-v5.js` 260L, `library_support.py` avec `get_library_filtered` (10 filtres + 10 tri), smart playlists CRUD. **Vague 4 (Film)** : `film-detail.js` 440L, 4 tabs, `get_film_full` dans `film_support.py` consolidant PlanRow + probe + perceptual + history + TMDb poster. **Vague 5 (Processing F1)** : `processing.js` 500L, stepper 3 etapes scan->review->apply dans une seule vue continue. **Vague 6 (Settings 9 groupes)** : `settings-v5.js` 580L, schema declaratif `SETTINGS_GROUPS` avec 9 groupes par intention, 7 field types, auto-save debounce 500 ms, live preview. **Vague 7 (QIJ)** : `qij-v5.js` 450L consolidant Quality+Integrations+Journal, `get_scoring_rollup(by, limit, run_id)` 5 dimensions (franchise/decade/codec/era_grain/resolution), `ROUTE_ALIASES = {}`. **Vague 8 (Fusion desktop/supervision)** : reportee a v7.7.0 strategie "finir feature set d'abord". **Vague 9 (Notification Center)** : `notifications_support.py` avec `NotificationStore` thread-safe cap 200, 6 endpoints (`get_notifications`, `dismiss_notification`, `mark_notification_read`, `mark_all_notifications_read`, `clear_notifications`, `get_notifications_unread_count`), `NotifyService.set_center_hook()` mirror inconditionnel des toasts OS vers le centre, `emit_from_insights()` dedupe par `(code, source)`. `notification-center.js` (desktop IIFE + supervision web ES module) drawer side-panel, filtres all/unread/insight/event, polling 30 s, focus management, ESC close. Badge compteur cloche top-bar. **Vague 10 (Tests + polish)** : `tests/e2e/test_16_v76_api.py` 18 tests E2E API REST, `tests/test_accessibility_v5.py` 28 tests ARIA/roles statique, `tests/test_polish_v5.py` 22 tests coherence (file sizes, no TODOs, tokens invariants, prefix `v5-*`, routes canoniques, overlays mutuellement exclusifs). **Principes v7.6.0** (5 regles en memoire) : overlay pattern (mutuellement exclusifs, creation dynamique), coexistence v5+legacy via prefix `v5-*`, separation backend (endpoints dans `*_support.py` dedies), tier colors invariantes cross-themes, notifications independantes du toast OS. **Reporte v7.7.0+** : Vague 8 fusion desktop/supervision, cleanup CSS legacy (styles.css 83 KB + themes.css 32 KB encore utilises par legacy views). **Tests 2723 -> 3028+** (+305). 0 regression imputable (1 echec preexistant `test_no_personal_strings_in_repo` depuis v7.5.0 sur "bruit blanc" dans tests audio). Note 9.9/10 maintenue.

**23 avril 2026** — v7.5.0 Analyse perceptuelle avancee v2 (14 sections, session marathon) : version majeure consolidant le moteur d'analyse perceptuelle. 14 sections livrees dans l'ordre §3 §4 §9 §13 §14 §5 §6 §7 §8 §15 §12 §11 §16a §16b. Package `cinesort/domain/perceptual/` etendu de 7 a 20+ modules. **Audio** : §3 Chromaprint fingerprint (fpcalc.exe + colonne dediee + migration 015), §9 spectral cutoff FFT numpy + rolloff 85% (migration 016), §14 DRC classification cinema/standard/broadcast via crest_factor+LRA, §12 Mel spectrogram (4 detecteurs : soft clipping, MP3 shelf, AAC holes, spectral flatness). **Video** : §4 scene detection via ffmpeg showinfo + merge hybride, §5 HDR10+ Pass 2 multi-frame (SMPTE ST 2094-40), §6 Dolby Vision profils 5/7/8.1/8.2/8.4 via DOVI record (mutualise avec §5), §7 fake 4K FFT 2D numpy HF/LF ratio combinee avec §13, §8 filtres metadonnees paralleles (idet+cropdetect+mpdecimate+IMAX 4 methodes), §13 SSIM self-ref via split+scale 1080p+scale 4K+ssim (migration 017). **Grain Intelligence v2 (phare §15)** : 6 bandes d'ere (16mm->UHD DV), exceptions Nolan/A24/Pixar, AV1 AFGS1 detection via ITU-T T.35 markers, classifier signature temporal+spatial 8dir+cross-color, detection DNR partiel, contexte historique FR. **ML §11** : LPIPS AlexNet ONNX (onnxruntime + assets/models/lpips_alexnet.onnx 9.4MB self-contained, script convert_lpips_to_onnx.py one-shot). **Score composite V2 §16** : `composite_score_v2.py` avec 3 categories ponderees (Video 60% / Audio 35% / Coherence 5%), 9 regles d'ajustement contextuel, confidence-weighted scoring, 5 tiers Platinum/Gold/Silver/Bronze/Reject, 7 warnings auto-collectes. Migration 018, coexistence totale avec v1. **Frontend §16b** : composants `score-v2.js` desktop IIFE + dashboard ES module (cercle SVG anime, 3 jauges horizontales, accordeon cliquable, tooltips FR educatifs, encarts warnings jaunes) integres dans inspecteur validation.js + modale compare execution.js + library.js + lib-duplicates.js. 185L CSS desktop + 95L dashboard. **Principes v7.5.0** (4 regles codifiees en memoire) : subprocess direct > wrappers Python, stockage perceptual_reports (pas quality_reports), code robuste aux binaires absents, migrations sequentielles, taille bundle non prioritaire (tout inclure dans le bundle). **Packaging** : dependances `onnxruntime>=1.24`, `numpy>=2.0`. Bundle release : ~16 MB -> ~48 MB (fpcalc 1 MB + LPIPS 9 MB + onnxruntime + embedding). Build EXE valide avec Python 3.13 (.venv313). **Schema v14 -> v18**. **Tests 2098 -> 2723** (+625). 0 regression imputable v7.5.0 (flakes REST + test "blanc" dans docs FR prexistants). **Reporte v7.6.0+** : §10 NR-VMAF (modele custom training), radar chart §16 optionnel. Note 9.9/10 maintenue.

**28 avril 2026** — Audit QA v7.6.0-dev Vague 1 reduite (branche `audit_qa_v7_6_0_dev_20260428`) : audit produit / launch readiness complementaire a `AUDIT_20260422.md` (audit code 8.6/10). Score launch readiness 78/100. 2 critiques identifiees mais REPORTEES car refactor profond (CR-1 atomicite shutil.move, CR-2 backup auto DB) — cf `docs/internal/audits/AUDIT_QA_20260428.md`. 4 high corriges : H-1 SAVEPOINT garde idempotence des migrations ALTER TABLE (catch "duplicate column" / "already exists"), H-2 pre-check espace disque avant apply (`cinesort/app/disk_space_check.py`, refus si free < max(somme*1.10, 100MB)), H-3+S-4/S-5 scrubber des secrets dans logs (`cinesort/infra/log_scrubber.py`, 8 patterns scrubbes : api_key=, Bearer, MediaBrowser Token, X-Plex-Token, X-Api-Key, JSON keys, smtp_password ; installe globalement dans `app.main()` et `app.main_api()`), H-4 durcissement REST LAN (constante `MIN_LAN_TOKEN_LENGTH=32`, retrogradation transparente vers 127.0.0.1 si bind 0.0.0.0 demande avec token court ; properties `lan_demoted` / `lan_demotion_reason` exposees a l'appelant). 5 commits, +34 tests unitaires, 3124 passes 0 regression introduite. 2 echecs preexistants (test "blanc", flake REST WinError 10053 en suite full). Cf `BILAN_CORRECTIONS.md` section "Phase Audit QA — 28 avril 2026" pour le detail.

**29 avril 2026** — Audit QA v7.6.0-dev — CR-1 atomicite shutil.move resolu (branche `audit_qa_v7_6_0_dev_20260428`, commit `f34d240`). Pattern WAL (write-ahead log) : migration 019 cree `apply_pending_moves` (table 8 colonnes + 2 indexes), mixin `_apply_mixin` etendu avec insert/delete/list/count_pending_moves. Nouveau module `cinesort/app/move_journal.py` (188L) expose : `journaled_move()` context manager (INSERT pending avant yield, DELETE apres sortie sans exception), `RecordOpWithJournal` wrapper (porte `journal_store` + `batch_id` en attributs sur le callable record_op), `atomic_move()` drop-in helper. Nouveau module `cinesort/app/move_reconciliation.py` (176L) avec 4 verdicts (`completed` / `rolled_back` / `duplicated` / `lost`) + cleanup automatique + notification UI sur conflits. Hook `reconcile_at_boot()` dans `runtime_support.get_or_create_infra` une seule fois par state_dir (cache `_RECONCILED_STATE_DIRS`). 9 sites de `shutil.move` wrappes via `atomic_move(record_op, ...)` (apply_core 8 sites: move_to_review_bucket, move_file_with_collision_policy, move_collection_folder, apply_tv_episode video+sidecar, quarantine_row dir+sidecar+video ; cleanup 1 site) + 2 undos via `journaled_move` direct (apply_support _execute_undo_ops). **Aucune signature de fonction interne touchee** — retro-compat tests legacy car `getattr(record_op, 'journal_store', None)` tombe sur `None` si record_op est un callable simple, et `atomic_move` fait alors `shutil.move` direct. +22 tests dans `test_apply_atomicity.py`. 2 tests existants mis a jour pour version DB 18->19. 3146 tests passent, 0 regression introduite. Score launch readiness 78/100 -> 86/100. Reste **CR-2 (backup auto DB)** non corrige avant launch "vrais clients". Cf `BILAN_CORRECTIONS.md` section "Phase Audit QA — 29 avril 2026" pour le detail complet.

**3 mai 2026 (suite)** — Migration v5 COMPLETE (Vagues 5B + 5C + V6, ~13 commits supplementaires). **V5B-01** : activation v5 dans le dashboard — refonte `index.html` (shell v5 minimal), refonte `app.js` (composants v5 + 7 vues v5 ESM + 4 vues v4 conservees), router enrichi `/film/:id`, handler REST `/views/*`, notification center polling 30s, FAB Aide V3-08, V3-04 sidebar counters + V3-01 + V1-13. Decouverte critique : vues v5 referencent globals legacy via references libres → creation `_legacy_globals.js` (shim CSP-safe) court-terme. Smoke test Playwright valide. **V5C** (3 missions) : V5C-01 supprime 9 vues v4 obsoletes (-7257 lignes), V5C-02 conserve Jellyfin/Plex/Radarr/Logs en v4 (decision documentee), V5C-03 adapte 26 tests legacy + audit du shim revele 400+ refs (conservation court-terme). **V6** : audit fin revele que home.js est le SEUL vrai consommateur du shim (~91 refs reelles ; les 200+ refs ailleurs etaient des faux positifs grep dans `empty state`/`skeleton state`). Solution : creation `web/views/_legacy_compat.js` (module ESM exposant les 14 helpers en imports propres), migration home.js, suppression du shim global + retrait `<script>` tag. Architecture finale **100% ESM**, plus aucune pollution window.X. **Tests** : 3784 → **3550** (-234 = tests v4 supprimes/skipes, +2 V6 ESM compat). Coverage 82.5% → **82.2%** (stable, normal apres -7257 lignes v4). Ruff clean. Smoke test app launch sans shim OK (REST 200). **Hygiene** : tags `backup-before-v[5b,5c,6]-merge`, fast-forward 3 phases, cleanup auto branches+worktrees. **Migration v5 = COMPLETE** : dashboard 100% v5 (sidebar moderne + topbar Cmd+K + notification center + breadcrumb), 7 vues v5 ESM actives, 4 vues v4 conservees temporaire (decision V5C-02), toutes V1-V4 features preservees, 0 shim global. Cf `BILAN_CORRECTIONS.md` section "Phase Migration v5 — 3 mai 2026 (Vagues 5B + 5C + V6)".

**3 mai 2026** — Migration v5 phase B (Vague 5-bis) : port 7 vues v5 IIFE → ES modules + REST apiPost (branche `audit_qa_v7_6_0_dev_20260428`, ~17 commits supplementaires). Audit pre-modification de l'instance V5B-01 a detecte un **bug architectural majeur** dans le plan initial : les vues v5 (`web/views/*.js`) etaient des IIFE appelant `window.pywebview.api.X()` directement, incompatibles avec le SPA dashboard qui utilise ES modules + REST `apiPost`. Cause racine : vues concues pour le webview legacy `web/index.html` jamais charge en mode normal. **Pivot strategique** : V5-bis = port complet vers ESM avant d'activer v5. **V5bis-00 (sequentiel)** : module shared `web/views/_v5_helpers.js` (192L, 17 tests) avec `apiPost(method, params)` (REST first, fallback pywebview natif), format normalise `{ok, data, status, error?}`, re-export `escapeHtml`/`$`/`$$`/`el`, `renderSkeleton` (4 types), `renderError`, `initView` pattern, `isNativeMode`, `formatSize`, `formatDuration`. **V5bis-01 a 07 (paralleles, 0 conflit)** : port 7 vues vers ES modules — `home.js` (138L), `library-v5.js` (599L), `qij-v5.js` (1095L, 3 IIFE → 4 exports), `processing.js` (1567L, 11 sites API), `settings-v5.js` (1665L, schema 9 groupes preserve + autosave + V3-02/03/09/12), `film-detail.js` (1065L, 4 tabs + drawer mobile), `help.js` (769L, FAQ + glossaire + V3-08 raccourcis + V3-13 Support). **Total** : ~6900 lignes refactorees, 0 IIFE restant, 0 `window.pywebview.api` restant, 100% des features V5A (V1-V4) preservees. **Tests** : 3705 → **3784** (+79). Coverage 82.5% stable. Ruff clean. JS syntax OK 8 fichiers. **Hygiene** : tags `backup-before-v5bis-00` + `backup-before-v5bis-merge`, fast-forward, cleanup auto 7 worktrees + 8 branches. **Reste** : Vague 5B activation v5 dans `app.js` (maintenant techniquement possible), Vague 5C cleanup vues v4 + IIFE legacy. Cf `BILAN_CORRECTIONS.md` section "Phase Migration v5 — 3 mai 2026".

**2 mai 2026 (suite)** — Migration v5 phase A : port V1-V4 vers v5 dormante (branche `audit_qa_v7_6_0_dev_20260428`, ~10 commits supplementaires). Audit ultra-complet (4 agents en parallele) a revele que 79% des features V1-V4 (19 sur 24) etaient absentes des fichiers v5 dormants. Decision : migration v5 en 3 phases (A port → B activation → C cleanup). **Vague 5A** (8 missions paralleles, 0 conflit) enrichit les fichiers v5 sans encore activer (dashboard continue en v4) : V5A-01 sidebar-v5 (badges V3-04 + integrations V3-01 + About V1-12 + update V1-13 + Aide V1-14 + V4-09 aria-current), V5A-02 top-bar-v5 (FAB ? V3-08 + updateNotificationBadge dynamic), V5A-03 settings-v5 (mode expert V3-02 + glossaire V3-03), V5A-04 home v5 (V2-04 allSettled + V2-08 skeleton + V1-07 banner + V1-06 CTA + V3-05 demo wizard), V5A-05 processing v5 (V2-04 + V2-08 + V2-07 EmptyState + V2-03 draft localStorage + V3-06 drawer mobile), V5A-06 qij-v5 (V1-05 EmptyState + V3-03 + V2-08), V5A-07 library-v5 + film-detail (V2-04 + V2-08 + V3-06), V5A-08 help v5 (V3-08 raccourcis enrichis). **Tests** : 3665 → **3705** (+40). Coverage 82.3% → **82.5%**. Ruff clean. Fix mineur post-merge sur `test_nav_v5.py` (adapter exports top-bar attendus). **Hygiene Git** : tag `backup-before-v5a-merge`, branche test `v5a_merge_test`, fast-forward, cleanup auto 8 worktrees + 9 branches. **Reste** : Vague 5B activation v5 dans `app.js` (~1 jour), Vague 5C cleanup vues v4 obsoletes (~0.5 jour). Cf `BILAN_CORRECTIONS.md` section "Phase Migration v5 — 2 mai 2026 (Vague 5A : port V1-V4 vers v5 dormante)".

**2 mai 2026** — Audit QA v7.6.0-dev — Vague 4 validation finale + V4-09 quick-wins a11y/BP livres et merges (branche `audit_qa_v7_6_0_dev_20260428`, ~10 commits supplementaires sur la session). Score launch readiness : 95/100 -> **96/100** ✅. **Vague 4** (7/8 missions, V4-08 beta privee differee) : V4-01 stress test 10000 films (generateur SQLite mock + test perf+RAM+DB skip par defaut opt-in `CINESORT_STRESS=1`), V4-02 contraste WCAG 2.2 AA pour 4 themes (calcul ratio chiffre sur tokens CSS, fail si < 4.5:1 texte normal), V4-03 templates GitHub Community (4 ISSUE templates + PR template + CONTRIBUTING.md FR + CODE_OF_CONDUCT.md Contributor Covenant 2.1 FR + SECURITY.md politique disclosure), V4-04 README enrichi (hero + 6 sections + FAQ + badges, script Playwright bootstrap propre serveur REST mock auto-genere 6 vues + 4 themes + grille), V4-05 Lighthouse score (wrapper npx lighthouse, baseline initiale perf 62 / a11y 90 / BP 96, test garde-fou anti-regression), V4-06 test devices multi-viewports (script Playwright capture 10 viewports x 6 routes + detection debordement horizontal + checklist humaine A→E pour Win10/11/4K/petit ecran/mobile/tablette), V4-07 audit a11y NVDA (test axe-core via Playwright WCAG 2.0/2.1/2.2 A+AA + guide pas-a-pas NVDA + clavier seul pour validation humaine). **V4-09 quick-wins a11y/BP** (5 fixes, 1h post-V4-05) : aria-selected → aria-current=page (12 nav-btn statiques + router.js dynamique, ARIA correct pour navigation), topbarAvatar mismatch split `<span aria-hidden>CS</span><span class=v5u-sr-only>Profil utilisateur</span>`, nav-badge spans (Validation/Application/Qualite) ajout `role=status` + `aria-live=polite` pour compteurs dynamiques, favicon SVG inline data URI 🎬 (evite 404 sans fichier separe), CSP frame-ancestors retire du meta (ignore par browsers, deja present en HTTP header `rest_server.py:380`). **Resultats Lighthouse post-V4-09** : a11y 90 → **96** (+6), BP 96 → **100** (+4), perf 62 inchange (minification CSS/JS = chantier V5). Test `test_lighthouse_baseline` thresholds tightened : a11y 85→90, BP 90→95. **Hygiene Git** : tag `backup-before-v4-merge`, branche test `v4_merge_test`, fast-forward sur audit, 0 conflit (missions V4 vraiment independantes), cleanup auto 7 worktrees + 8 branches. **Tests session** : 3643 → **3665** (+22). Coverage 82.2% → **82.3%** (stable, > seuil CI 80%). Ruff clean. 2 failures pre-existantes confirmees inchangees (radarr/plex via `git stash + checkout base`). **Reste avant public release** : lancer V4-08 (templates beta privee) quand pret a recruter 20-50 early adopters, tester soi-meme sur appareils physiques (V4-06 checklist) + avec NVDA (V4-07 guide), remplacer placeholders URL/email apres creation repo public, build `.exe` final + tag `v7.6.0` + creation GitHub Release. **Reportes V5+** : minification CSS/JS pour perf Lighthouse 80+, cleanup `web/views/*.js` legacy, UI fluidite tableaux 10000 films via Playwright. Cf `BILAN_CORRECTIONS.md` section "Phase Audit QA — 2 mai 2026 (Vague 4 validation finale + V4-09 quick-wins)" pour le detail complet.

**1er mai 2026** — Audit QA v7.6.0-dev — Vagues 1+2+3 polish public-launch livrees et mergees (branche `audit_qa_v7_6_0_dev_20260428`, 40 commits cumules sur la session). Score launch readiness : 93/100 -> **95/100** ✅. Orchestration parallele via worktrees Git (1 instance Claude Code par mission, prompts auto-suffisants dans `audit/prompts/vague[1-3]/`). **Vague 1** (15 missions, fondations launch) : LICENSE MIT, CI bundle 60MB, requirements CVE bumps, accents fix, EmptyState CTA quality, integrations links, banner outils manquants, migration 020 indexes perf, DB integrity check boot, settings.json auto-backup rotation 5, helper `make_session_with_retry` urllib3, footer About + modale, updater GitHub Releases (rate-limit 60/h), vue Aide complete (15 FAQ + 16 termes glossaire FR), test_release_hygiene skip_dirs="audit". **Vague 2** (12 missions, qualite + perf + tests) : refactor `save_settings_payload` F=81→B=6 (16 helpers), refactor 4 fonctions complexite E≥30 (analyze_quality_batch, _build_analysis_summary, _enrich_groups, row_from_json), draft auto validation localStorage (debounce 500ms, restore intelligent, TTL 30j), Promise.allSettled 9 vues, tests cinesort_api 52→84.2%, tests tmdb_support 14.7→100%, composant `<EmptyState>` reutilisable + 4 ecrans, skeleton states 7 vues dashboard, migration 4 clients HTTP retry (TMDb/Jellyfin/Plex/Radarr). **Vague 3** (13 missions, UX final) : sidebar integrations toujours visible (avant masquee = feature morte), mode `expert_mode` toggle settings, 18 termes metier glossaire tooltip ⓘ, badges sidebar (Validation/Application/Qualite avec polling 30s), demo wizard premier-run (15 films fictifs), drawer mobile inspector validation < 768px, focus visible WCAG 2.4.7 par theme (`--focus-ring`), kbd hints + FAB "?" aide raccourcis, reset all data UI (Danger Zone + backup ZIP), 30 hardcodes hex → tokens CSS, PRAGMA mmap_size 256MB, hook updater au boot + UI Settings + badge "•" sidebar si MAJ, vue Aide section Support (ouvrir logs / copier chemin / signaler bug). **Post-fix critique V3-09+V3-12** : prompts mentionnaient `web/dashboard/views/settings-v5.js` qui n'existe pas, instances ont modifie `web/views/settings-v5.js` (legacy webview, jamais affiche en mode normal — pywebview charge `web/dashboard/index.html` via `localhost:8642/dashboard/?native=1` cf `app.py:400`). Sections Danger Zone + Mises a jour portees manuellement vers `web/dashboard/views/settings.js` (le vrai). **Hygiene Git** : tags `backup-before-v[2,3]-merge`, branches test merge `v[2,3]_merge_test` pour pre-detection conflits, fast-forward sur audit, cleanup auto worktrees+branches apres merge. **Tests session** : 3174 → **3643** (+469 tests cumules). Coverage 79.7% → **82.2%** (au-dessus seuil CI 80%). Ruff clean, 0 regression imputable. **Reste Vague 4** (validation finale ~8 missions) : test devices Win10/11/4K/petit ecran/mobile, audit a11y NVDA reel, stress 10 000 films, Lighthouse score, contraste 4 themes, templates GitHub Issues + CONTRIBUTING + CODE_OF_CONDUCT, README enrichi + screenshots + demo GIF, beta privee 20-50 early adopters. Placeholder GitHub URL V3-13 + `update_github_repo` V3-12 a configurer apres creation repo public. Cf `BILAN_CORRECTIONS.md` section "Phase Audit QA — 1er mai 2026 (Vagues 1+2+3 polish public-launch)" pour le detail complet.

**29 avril 2026 (suite)** — Audit QA v7.6.0-dev — CR-2 backup auto + Vague 2 livres (branche `audit_qa_v7_6_0_dev_20260428`, 7 commits supplementaires apres CR-1). Score launch readiness : 86/100 -> **93/100** ✅. **CR-2** (`ed1886f`) : nouveau module `cinesort/infra/db/backup.py` (180L) avec `backup_db()` natif (sqlite3.Connection.backup), `list_backups`, `rotate_backups`, `restore_backup` + garde-fou. Hook `_backup_before_migrations()` dans `SQLiteStore.initialize()` (skip fresh install). Hook `store.backup_now(trigger="post_apply")` dans `apply_support.apply_changes()` apres apply reel. API publique `backup_now()` + `list_db_backups()` pretes pour UI Settings. Default rotation : 5 backups dans `<db_dir>/backups/`. +19 tests. **H-6** (`80ca098`) : `install_rotating_log(log_dir)` cree RotatingFileHandler 50 MB × 5 backups dans `%LOCALAPPDATA%/CineSort/logs/cinesort.log`. Le scrubber est attache au handler (defense en profondeur). +3 tests. **H-7** (`ca53cda`) : message d'erreur "ffmpeg introuvable" enrichi avec suggestion d'action ("Installez depuis Reglages > Outils video") + champ `missing_tool: "ffmpeg"`. **H-8 + H-9** (`236d643`) : "Preview selection" -> "Aperçu de la sélection" + accents restaures sur "Annuler la sélection" ; suppression de l'onclick inline `#btnQualitySimulate` (race condition au boot) -> event listener via DOMContentLoaded dans `quality-simulator.js`. **H-10** : DEJA RESOLU sur 7.6.0-dev (`_persist_protected_secret(legacy_field="email_smtp_password", ...)` dans settings_support.py:409). Le finding antérieur (22 avril v7.2.0-dev) etait obsolete. **H-11** (`9a2d125`) : Jellyfin watched-state restore passe de 2 a 5 retries avec backoff exponentiel `_compute_retry_delay()` cap `_MAX_RETRY_DELAY_S = 60s` (total max wait 15s -> 135s pour absorber les Jellyfin lents). +5 tests. **M-3** (`dae94f0`) : nouvelle classe CSS `.btn--loading` (spinner CSS pur, respect prefers-reduced-motion). Pas de modif JS dans ce commit — infrastructure dispo pour adoption progressive. **Reportes Vague 3** : H-5 virtualisation tables, M-1 timeout scan FS, M-5 console.* en prod, D-5/D-6 caches, P-1/P-2 parallelisation, P-4 PRAGMA SQLite, L-* polish. 3174 tests passent (+119 cumules sur la session 29/04), 0 regression introduite. 2 failures preexistants inchanges. **Recommendation finale : Ready to launch ✅** — toutes les Critical resolues, toutes les High Vague 1+2 traitees. Cf `BILAN_CORRECTIONS.md` section "Phase Audit QA — 29 avril 2026 (Vague 2 + CR-2 + score final 93/100)" pour le detail complet.

**4 mai 2026** — Operation Polish Total v7.7.0 — Vague 0 + Vague 1 livrees (branche `polish_total_v7_7_0` depuis `audit_qa_v7_6_0_dev_20260428`). Cible : v7.7.0 production-grade publique, note 9.2/10 -> 9.9-10/10 en 8 vagues d'execution multi-agents. **Vague 0 (preparation)** : creation branche, tag `backup-before-polish-total`, baseline (3550 tests dont 22 fail + 3 err preexistants, ruff clean, .exe 50.07 MB, coverage 81.3%, **101 endpoints REST mesures** vs CLAUDE.md "33"), creation `OPERATION_POLISH_V7_7_0.md` + `BASELINE.md` + `PROGRESS.md`. **Vague 1 (bloquants public release, 7 agents paralleles + 1 web-research)** : V1-01 CVE bumps `urllib3>=2.6.0` (CVE-2024-37891 fuite Proxy-Auth + CVE-2025-66418 zip bomb) + `pyinstaller>=6.10.0` (CVE-2025-59042 elevation privileges) dans `requirements.txt` + `requirements-build.txt` (commit `3dc8421`). V1-02 Migration **021 ON DELETE CASCADE** sur 4 FK (`errors.run_id`, `quality_reports.run_id`, `anomalies.run_id`, `apply_operations.batch_id`) +17 tests (commit `9200320`, schema v20 -> **v21**). V1-03 FFmpeg subprocess cleanup atexit : nouveau module `subprocess_safety.py` + 9 tests + 8 sites refactores dans `ffmpeg_runner.py` (commit `8bb3473`). V1-04 LPIPS model absent fallback graceful degrade dans `lpips_compare.py` +12 tests (commit `ce0f995`). V1-05 + V1-05bis + V1-05ter Tests E2E + `test_v5c_cleanup` corriges (`450b434` + `1b447fe` + `dc53894`) : sélecteurs cassés + `_startup_error` MessageBox skip pendant tests (mock `fake_start`) + `test_dashboard_cache_header` accepte `no-cache` ou `max-age` -> taux pass 99.30% -> **100%** (3589/3589). V1-06 PyInstaller hidden imports perceptual via `collect_submodules` dans `CineSort.spec` (commit `adda0ae`), .exe 50.08 MB. **Findings resolus** : CRIT-4 (CVE), R5-DB-1 (FK CASCADE), R5-CRASH-2/R4-PERC-4 (ffmpeg zombies), R5-PERC-3/R4-PERC-3 (LPIPS fallback), H7 (tests E2E), H9 (hidden imports), pollution ecran tests (V1-05bis). 11 commits sur la branche, tag `end-vague-1` sur `1b447fe`. Tests : 3550 -> 3589 (+39), 100% pass, ruff clean, .exe < 60 MB. Note 9.2/10 -> ~9.4/10. Cf `OPERATION_POLISH_V7_7_0_PROGRESS.md` pour le detail.

**4 mai 2026 (suite)** — Operation Polish Total v7.7.0 — Vague 2 livree (UX/A11y polish, 8 agents paralleles : 7 implementation + 1 web-research). **V2-A** (`f82bd8f`) : qij.js race UI 3 fixes (setTimeout 100ms remplace par binding direct H2, AbortController sur `_qijMountActive` H4, guard `parentElement` polling H8) + XSS hardening 14 patterns escape (`m.year`, autres champs dynamiques) + tri Journal (selecteur 6 options date/score/statut asc/desc remplace boutons cards). **V2-B** (`c676572`+`38bf0fd`) : cache `get_settings` boot — 4 sites concurrents `app.js:161,295,344,361` reduits a 1 wrapper `_cachedSettings` avec invalidation sur `last_settings_ts`. Latence boot reduite ~200ms. **V2-C** (`c676572`) : memory leaks 5 fixes — `closeNotifications()` retire overlay+drawer du DOM (notification-center.js), `journal-polling.js` AbortSignal.timeout(5000), pattern `unmount()` exporte par chaque vue appele par router au switch, `localStorage drafts` TTL 30j + nettoyage periodique au boot, `Promise.allSettled` AbortController au navigate hashchange. 14 fichiers modifies, +431/-63. **V2-D** (`e93c341`) : WCAG 2.2 AA — `trapFocus(overlay)` capture Tab/Shift+Tab dans modal.js (H10), `aria-atomic="true"` + queue d'annonces aria-live, `aria-busy` toggle dynamique avant/apres fetch, `aria-expanded` sur toggle dropdown theme top-bar-v5.js, Arrow keys (Up/Down/Home/End) sur menu theme ouvert, keydown Space/Enter sur `.th-sortable` table.js, `aria-required` + `*` rouge sur champs settings obligatoires. +27 tests a11y. **V2-E** font-display:swap : NO-OP, deja resolu anterieurement (H11). **V2-F** (`2f3fb9e`) : `open_logs_folder` retire de `_EXCLUDED_METHODS` -> expose en REST (H18) ; CSP — `'unsafe-inline'` style **conserve** (refactor 391 styles inline disproportionne pour Vague 2, cf decision dans `OPERATION_POLISH_V7_7_0_PROGRESS.md`), header `Content-Security-Policy-Report-Only` strict ajoute en parallele pour observation des violations (mitigation : V2-A escape XSS systematique). Reporte Vague 3+ : refactor 391 styles inline -> classes CSS, suppression `'unsafe-inline'` enforced. **V2-G** (`09e5af4`) : `PRAGMA optimize` au shutdown dans `sqlite_store.close()` (R5-DB-2, reduit fragmentation DB long-terme), `PRAGMA integrity_check` au boot dans `sqlite_store.initialize()` avec auto-restore depuis backup si corrompu (R5-DB-3) + UI notification au prochain boot. +13 tests. **Findings resolus Vague 2** : H2/H4/H8 (race UI), H3 (XSS), H6 (tri Journal), H10 (a11y WCAG 2.2 AA), H11 (font-display deja OK), H13 (cache boot), H17 partiel (CSP Report-Only), H18 (open_logs_folder), R4-MEM-2/3/4/5/6 (memory leaks), R5-DB-2/3 (PRAGMA). Tests : 3589 -> **3631** (+42), **100% pass rate maintenu** (0 fail / 0 err), ruff clean, coverage stable, .exe **50.10 MB** (< 60 MB). 6 commits, tag `end-vague-2` sur `e93c341`. Note ~9.4/10 -> **~9.6/10** (estim). Reste Vagues 3-7 : Polish + Documentation (CLAUDE/MANUAL/API/TROUBLESHOOTING + CSS legacy + logging), Refactor (`_plan_item` 565L + `compute_quality_score` 369L + Composite Score V2 toggle), Stress/scale, i18n EN, validation finale + tag `v7.7.0`.
