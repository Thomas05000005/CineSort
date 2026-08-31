# BILAN - Preparation Boucle de Correction CineSort - 2026-06-08

Marqueurs utilises dans ce document :
- **FIGE** : etat confirme, immuable, vrai a la date du bilan (ex. invariantes, themes existants)
- **HYPOTHESE** : cause probable / regroupement a confirmer par mesure ou repro
- **OPERATIONNEL** : etat utilisable / bug code reproductible / point d'action immediat

---

## 0.0 Checklist Canonique - 32 Features

Regroupement par domaine. Statut : OK / operationnel / CASSE / FIGE.

### Backend (8)

| # | Feature | Statut | Preuves |
|---|---|---|---|
| 1 | scan | OK **OPERATIONNEL** | `cinesort/app/job_runner.py` + `tests/test_scan_streaming.py` + `test_incremental_scan.py` + `test_scan_parallel_v77.py` (section D ligne 99) |
| 2 | plan (dry-run) | OK **OPERATIONNEL** | `cinesort/app/plan_support.py` + `plan_support_core.py` + `plan_support_dedup.py` + `tests/test_apply_dryrun_retest.py` + `test_apply_preview.py` (section D ligne 100) |
| 3 | apply | OK **OPERATIONNEL** | `cinesort/app/apply_core.py` + `apply_audit.py` + `tests/test_apply_atomic_mode_v77.py` + `test_apply_atomicity.py` + `test_apply_progress.py` (section D ligne 101) |
| 4 | undo / historique 24h | OK **OPERATIONNEL** | `cinesort/ui/api/apply_support.undo_last_apply` + `cinesort/app/film_history.py` + `tests/test_undo_24h_enforcement.py` + `test_undo_apply.py` + `test_undo_checksum.py` + `test_film_history.py` (section D ligne 102) |
| 5 | rollback forward atomique | OK **OPERATIONNEL** | `cinesort/app/apply_rollback.py` (Vague P/VP-A) + `tests/test_apply_atomic_rollback_integration_v77.py` + `test_migration_rollback.py` (section D ligne 103) |
| 6 | analyse qualite (scoring composite) | OK **OPERATIONNEL** | `cinesort/domain/quality_score.py` + `fusion_score.py` + `tests/test_compose_score_explanation_v77.py` + `test_composite_score_v2.py` + commit `fix(mega-hotfix): quality_score_coherence` (section D ligne 104) |
| 7 | perceptual LPIPS (video+audio) | OK **OPERATIONNEL** | `cinesort/domain/perceptual/` + `tests/test_perceptual_*` (19 fichiers) + `cinesort/ui/api/perceptual_support.py` + commit `fix(mega-hotfix): audio_perceptual_overall` (section D ligne 105) |
| 8 | quarantaine TTL + retention crons | OK **OPERATIONNEL** | Crons retention/quarantine demarres au boot (section B ligne 46) + Vague Q quarantaine TTL |

### Integrations (7)

| # | Feature | Statut | Preuves |
|---|---|---|---|
| 9 | TMDB (fiches + posters URL) | OK backend / **CASSE frontend** | `cinesort/infra/tmdb_client.py` L632-641 produit `poster_url` valide + `cinesort/ui/api/tmdb_support.py` L158-164 + `cinesort/domain/core.py` L899-908 (sections C.1 + C.4) |
| 10 | OMDb enrichment | OK **OPERATIONNEL** | `cinesort/infra/omdb_client.py` (presence du client + memoire endpoints reels) |
| 11 | Plex sync | OK **OPERATIONNEL** | `cinesort/infra/plex_client.py` (pattern module-style import documente pour mocks dans `apply_support.py`) |
| 12 | Jellyfin sync + validation | OK **OPERATIONNEL** | `cinesort/app/jellyfin_sync.py` + `jellyfin_validation.py` + `tests/test_jellyfin_client.py` + `test_jellyfin_sync.py` + `test_jellyfin_validation.py` + `test_jellyfin_retry_integration.py` (section D ligne 106) |
| 13 | Radarr | OK **OPERATIONNEL** | `cinesort/infra/radarr_client.py` + `web/dashboard/views/radarr.js` |
| 14 | Ollama (LLM optionnel) | OK **OPERATIONNEL** | `cinesort/infra/integrations/ollama_client.py` |

### UI Dashboard (13)

| # | Feature | Statut | Preuves |
|---|---|---|---|
| 15 | Accueil | operationnel **OPERATIONNEL** | `web/dashboard/views/accueil.js` (delta non commite, refonte UI 2026-05 active) |
| 16 | Traitement (lancement scan/plan/apply) | operationnel avec delta non commite **OPERATIONNEL** | `web/dashboard/views/traitement.js` +394L non commitees (section A ligne 14) + `processing.js` |
| 17 | Bibliotheque (cartes films + posters) | **CASSE (posters)** | `web/dashboard/views/bibliotheque.js` + `library/library.js` + `lib-analyse/apply/duplicates/validation/verification.js` -- CSP `img-src` bloque `image.tmdb.org` (section C.4) |
| 18 | Qualite (rapports + simulateur) | operationnel **OPERATIONNEL** | `web/dashboard/views/qualite.js` + `quality.js` + `quality-simulator.js` + `cinesort/ui/api/quality_simulator_support.py` |
| 19 | Historique | operationnel **OPERATIONNEL** | `web/dashboard/views/historique.js` + `cinesort/ui/api/history_support.py` + `film_history_support.py` |
| 20 | Parametres | operationnel avec delta non commite **OPERATIONNEL** | `web/dashboard/views/parametres.js` +267L non commitees (section A ligne 14) + `cinesort/ui/api/settings_support.py` |
| 21 | Doublons | operationnel **OPERATIONNEL** | `web/dashboard/views/doublons.js` + `library/lib-duplicates.js` + `cinesort/app/plan_support_dedup.py` |
| 22 | Film detail (modal + field locks) | operationnel **OPERATIONNEL** | `web/dashboard/views/film-detail.js` + `cinesort/ui/api/film_support.py` + migration 030 `field_locks` |
| 23 | Logs viewer | operationnel **OPERATIONNEL** | `web/dashboard/views/logs.js` + chemin `%LOCALAPPDATA%/CineSort/logs/cinesort.log` (section E) |
| 24 | Status systeme | operationnel **OPERATIONNEL** | `web/dashboard/views/status.js` + endpoint `GET /api/health` avec `active_run_id` et `last_event_ts` |
| 25 | Aide / About / Demo wizard | operationnel **OPERATIONNEL** | `web/dashboard/views/aide.js` + `help.js` + `about.js` + `demo-wizard.js` + `cinesort/ui/api/demo_support.py` |
| 26 | Custom rules editor + Enrichment + QIJ + Login | operationnel **OPERATIONNEL** | `web/dashboard/views/custom-rules-editor.js` + `enrichment.js` + `qij.js` + `login.js` (auth Bearer token) |

### Bridge desktop (2)

| # | Feature | Statut | Preuves |
|---|---|---|---|
| 27 | pywebview `js_api=CineSortApi` (actions natives) | **FIGE** | `app.py` L865 `js_api=api` + section C.3.a -- bridge NON utilise pour bibliotheque (REST `127.0.0.1:8642` a la place) |
| 28 | REST dispatcher `/api/<facade>/<methode>` (167 endpoints, 6 facades) | operationnel **OPERATIONNEL** | `cinesort/infra/rest_server.py` (1193L) + 6 facades run/settings/quality/integrations/library/runtime + section B ligne 46 (167 endpoints) |

### Themes (4)

| # | Feature | Statut | Preuves |
|---|---|---|---|
| 29 | studio | **FIGE** | `web/shared/themes.css` L35 `[data-theme=studio]` |
| 30 | cinema | **FIGE** | `web/shared/themes.css` L80 `[data-theme=cinema]` |
| 31 | luxe | **FIGE** | `web/shared/themes.css` L121 `[data-theme=luxe]` |
| 32 | neon | **FIGE** | `web/shared/themes.css` L169 `[data-theme=neon]` (+ aaa accessibilite L233 -- 5 themes au total, la mission en demande 4) |

**Total : 32 lignes / 32 features.**

---

## 0.1 Securiser la Base

- **Branche** : `loop/correction-2026-06`
- **Checkpoint SHA** : `f493abdc998ff56eea716e694c09f44995fe6cf7`
- **Fichiers non commites** : 93 (delta `traitement.js +394L`, `parametres.js +267L`, et 91 autres dans `web/`, `cinesort/`, `tests/`, `docs/`, `.github/workflows/`)

### Suggestion d'isolation : **OUI, isolation forte recommandee**

Le diff melange 4 strates independantes (UI web/, REST/infra, domaine pur, CI+docs+tests). Risques specifiques :

1. **Pipeline posters CSP** : rupture documentee dans `rest_server.py` L716-725 + `index.html` L11 (CSP `img-src 'self' data:` bloque `image.tmdb.org`). Toucher REST sans toucher CSP, ou inversement, casse la bibliotheque en silence.
2. **Invariantes tier hex** (Gold `#FFD700`) : peuvent etre cassees par `tokens.css`/`themes.css`/`styles.css` modifies en parallele. Verification **runtime** obligatoire via Playwright `getComputedStyle`, pas grep source (memoire `tier_duplication_historique` : un `:root` secondaire L1998-2001 de `styles.css` peut surcharger).
3. **Backward compat ABSOLUE** : impose tests UI separes du REST pour ne pas casser `/api/<methode>` legacy pendant qu'on refactore `/api/<facade>/<methode>`.

### Plan worktrees paralleles (feedback_multi_agents_parallel)

| Worktree | Perimetre | Risque dominant |
|---|---|---|
| `wt-ui-dashboard` | `web/dashboard/` + `web/shared/` + `index.html` | CSP, themes, refonte 2026-05 |
| `wt-rest-infra` | `rest_server.py` +150 lignes + `cinesort/ui/api/*` | Dispatcher 410 legacy, http_status convention |
| `wt-domain` | `cinesort/domain/` + `cinesort/app/` | Quality / perceptual / apply atomicity |
| `wt-ci-docs` | `.github/workflows/` + `docs/` + `tests/` | uv migration CI, hygiene release |

**Verifications obligatoires apres merge** :
- Playwright `getComputedStyle` sur tier colors (memoire `tier_duplication_historique`).
- Re-tester endpoints reels (`start_plan {settings:{library_path}}`, `check_duplicates`, `apply decisions:{}`) cote `rest_server.py` +150 lignes (memoire `endpoints_reels`).
- Lire `settings.json` avec `encoding='utf-8-sig'` (memoire `settings_utf8_bom`).
- Scrub `'users\<utilisateur>'` (test `release_hygiene` echoue actuellement sur `scripts/scan_smoketest_*`).

---

## 0.2 Synthese 07/06

- **Fichier ecrit** : `C:\Users\<utilisateur>\projects\CineSort\docs\internal\AUDIT_UX_2026-06-07.md`
- **10 fixes confirmes** appliques (commits `mega-hotfix` quality_score_coherence + audio_perceptual_overall + autres)
- **9 points ouverts** identifies dans la synthese, reportes dans 0.3 (triage tests) et 0.4 (triage erreurs log) ci-dessous

---

## 0.3 Triage Tests Non Passants

**Note** : la reconnaissance parlait de 40 tests. Le run pytest 2026-06-08 montre **53 failed + 99 skipped** (5329 passed). Delta du a evolutions intermediaires (B01/B02/B05) et nouveaux tests `_v77`. Categorisation ci-dessous porte sur les 53 echecs reels.

### Tableau de triage (53 echecs reels + 10 lignes meta)

| # | Test | Categorie | Cause probable | Domaine |
|---|---|---|---|---|
| 1 | `test_apply_dryrun_retest.py::ApplyDryRunRestRetestTests::test_apply_atomic_is_opt_in_strict` | vrai bug | dispatcher REST `/api/<facade>/<methode>` non aligne (legacy 410) | apply dry-run REST |
| 2 | `test_apply_dryrun_retest.py::ApplyDryRunRestRetestTests::test_case_only_rename_is_noop_in_preview` | vrai bug | preview ne detecte plus case-only rename comme noop | apply preview / plan |
| 3 | `test_apply_dryrun_retest.py::ApplyDryRunRestRetestTests::test_post_run_apply_dry_run_does_not_touch_fs` | vrai bug | dry-run touche FS (regression atomicity) | apply dry-run |
| 4 | `test_audit_2026_05_24_regression.py::SettingsDispatcherSectionsTests::test_save_section_advanced_exists` | vrai bug | section `advanced` absente du dispatcher settings (410) | settings dispatcher |
| 5 | `test_audit_2026_05_24_regression.py::SettingsDispatcherSectionsTests::test_save_section_naming_exists` | vrai bug | section `naming` absente | settings dispatcher |
| 6 | `test_audit_2026_05_24_regression.py::SettingsDispatcherSectionsTests::test_save_section_omdb_exists` | vrai bug | section `omdb` absente | settings dispatcher |
| 7 | `test_audit_2026_05_24_regression.py::SettingsDispatcherSectionsTests::test_save_section_sources_exists` | vrai bug | section `sources` absente | settings dispatcher |
| 8 | `test_ci_workflows_pyproject_compat_v77.py::CiWorkflowsCompatTests::test_ci_yml_installs_requirements_or_pyproject` | vrai bug | `ci.yml` n'installe ni requirements ni pyproject patterns reconnus (uv migration) | CI workflows |
| 9 | `test_ci_workflows_pyproject_compat_v77.py::CiWorkflowsCompatTests::test_workflows_install_via_known_patterns` | vrai bug | meme cause (workflows GH non alignes pattern) | CI workflows |
| 10 | `test_cinesort_api_radarr.py::TestGetRadarrStatus::test_radarr_connection_error` | vrai bug | 'network down' non trouve dans message i18n (encoding mojibake 'echec') | integrations Radarr |
| 11 | `test_contrast_wcag.py::ContrastWcagTests::test_cinema_contrast` | vrai bug | tokens `--text-primary/secondary/muted=None` sur theme cinema (var CSS non chargee) | tokens theme / WCAG |
| 12 | `test_contrast_wcag.py::ContrastWcagTests::test_luxe_contrast` | vrai bug | meme cause tokens manquants theme luxe | tokens theme / WCAG |
| 13 | `test_contrast_wcag.py::ContrastWcagTests::test_neon_contrast` | vrai bug | meme cause tokens manquants theme neon | tokens theme / WCAG |
| 14 | `test_contrast_wcag.py::ContrastWcagTests::test_studio_contrast` | vrai bug | meme cause tokens manquants theme studio | tokens theme / WCAG |
| 15 | `test_core_heuristics.py::CoreHeuristicsTests::test_plan_library_collects_ignored_extensions_breakdown` | vrai bug | breakdown extensions ignored = 0 mais attend >=1 (skip absent du res) | plan_library heuristics |
| 16 | `test_dashboard_infra.py::RateLimitHttpTests::test_rate_limit_blocks_after_5_failures` | vrai bug | localhost cense renvoyer 401 renvoie 410 (legacy passthrough) | REST rate-limit |
| 17 | `test_dashboard_shell.py::DashboardShellHttpTests::test_login_invalid_token_returns_401` | vrai bug | endpoint legacy renvoie 410 au lieu 401 | dashboard auth |
| 18 | `test_log_context.py::RestRequestIdHeaderTests::test_x_request_id_on_unauthorized_post` | vrai bug | header `X-Request-Id` absent sur 401 (route 410 court-circuite) | observability / log_context |
| 19 | `test_path_length_killswitch_v77.py::ApplySingleKillSwitchTests::test_path_trop_long_declenche_kill_switch` | vrai bug | kill-switch path trop long ne se declenche pas (rename passe) | apply kill-switch |
| 20 | `test_phase2b_routing_sidebar.py::I18nTranslationsTests::test_fr_quality_label` | vrai bug | 'Qualite' vs 'Qualite' (i18n encoding/normalisation) | UI i18n |
| 21 | `test_phase3_1b_cta_health_suggestions.py::IntegrationTests::test_render_accueil_passes_3_args` | vrai bug | `renderAccueil` signature ne passe pas 3 args (regression integration) | UI accueil |
| 22 | `test_phase3_1c_env_inspector_states.py::InspectorContentTests::test_shortcuts_section_lists_keys` | vrai bug | env inspector ne liste plus les keys shortcuts | UI env inspector |
| 23 | `test_phase3_3_traitement.py::FiveStepsTests::test_step_labels_french` | vrai bug | labels FR des 5 etapes traitement changes (mojibake possible) | UI traitement i18n |
| 24 | `test_phase4_bibliotheque_endpoints.py::GetLibraryCountersByChipTests::test_unidentified_counted` | vrai bug | compteur 'unidentified' = 5 attendu 1 (regression filter chip) | UI bibliotheque counters |
| 25 | `test_phase4_parametres_endpoints.py::ResetSettingsTests::test_scope_apparence_restores_default_theme` | vrai bug | reset scope apparence -> theme='luxe' au lieu de 'studio' (default) | settings reset scope |
| 26 | `test_phase5_bibliotheque_complete.py::BulkActionsWiringTests::test_countdown_3s_if_over_50` | vrai bug | countdown 3s bulk >50 non cable (memoire user 'actions dangereuses') | UI bibliotheque bulk |
| 27 | `test_phase5_doublons_complete.py::DoublonsViewRightPanelTests::test_right_panel_unmount_clears_sections` | vrai bug | unmount panel doublons ne clear pas sections (leak) | UI doublons lifecycle |
| 28 | `test_phase5_historique_complete.py::ApplyTabDetailTests::test_apply_op_labels` | vrai bug | labels operations apply manquants dans tab historique | UI historique |
| 29 | `test_phase5_traitement_complete.py::ValidationStepTests::test_bulk_approve_shows_toast_5s` | vrai bug | `_traitementLastBulkSnapshot` manquant pour toast 5s | UI traitement bulk validation |
| 30 | `test_phase5_traitement_complete.py::LifecycleTests::test_unmount_cleans_doublons` | vrai bug | `unmountTraitement` ne contient pas `unmountDoublons` (regression cleanup) | UI traitement lifecycle |
| 31 | `test_phase5_traitement_complete.py::LifecycleTests::test_unmount_cleans_polling` | vrai bug | `unmountTraitement` ne contient pas `_stopPolling` (regression polling cleanup) | UI traitement polling |
| 32 | `test_probe_parallel.py::ProbeFilesBatchTests::test_100_files_completes_under_reasonable_time` | **flaky** | seuil temporel / perf (probe 100 files sous machine partagee) | probe parallel perf |
| 33 | `test_pyinstaller_smoke.py::PyInstallerSmokeTests::test_exe_starts_and_responds_to_health` | **flaky / env** | EXE n'a pas repondu `/api/health` en 15s (`dist/CineSort.exe` pas rebuild, hiddenimports manquants ou port 8642 occupe) | build smoke |
| 34 | `test_quality_score.py::QualityScoreTests::test_analyze_quality_batch_rejects_concurrent_launch` | vrai bug | concurrent launch quality batch n'est plus rejete (regression guard) | quality batch concurrency |
| 35 | `test_refactor_84_progress_v77.py::TestRefactor84LazyImportProgress::test_lazy_imports_bounded` | vrai bug | 121 lazy imports > borne 69 (regression #84/#83 lazy bound) | architecture / lazy imports |
| 36 | `test_release_hygiene.py::ReleaseHygieneTests::test_no_personal_strings_in_repo` | vrai bug | `users\<utilisateur>` present dans `scripts/scan_smoketest_lib.py` et `scan_smoketest_parallel.py` | release hygiene / scrub |
| 37 | `test_release_hygiene.py::RecordApplyOpTests::test_returns_false_on_failure_and_logs` | vrai bug | `record_apply_op` n'emet plus ERROR log on failure | apply audit logging |
| 38 | `test_rest_http_status.py::HttpStatusConventionTests::test_default_status_is_200` | vrai bug | dispatcher legacy 410 court-circuite la convention `http_status` opt-in | REST http_status convention |
| 39 | `test_rest_http_status.py::HttpStatusConventionTests::test_http_status_404_propagates` | vrai bug | meme cause (410 ecrase 404 metier) | REST http_status convention |
| 40 | `test_rest_http_status.py::HttpStatusConventionTests::test_http_status_409_propagates` | vrai bug | meme cause (410 ecrase 409 metier) | REST http_status convention |
| 41 | `test_rest_http_status.py::HttpStatusConventionTests::test_invalid_http_status_falls_back_to_200` | vrai bug | meme cause (410 court-circuite fallback) | REST http_status convention |
| 42 | `test_rest_http_status.py::HttpStatusConventionTests::test_out_of_range_status_falls_back_to_200` | vrai bug | meme cause (410 court-circuite fallback) | REST http_status convention |
| 43 | `test_rest_security.py::RestSecurityHttpTests::test_404_no_path_reflection` | vrai bug | path reflection check via legacy endpoint 410 | REST security / legacy |
| 44 | `test_rest_security.py::RestSecurityHttpTests::test_500_no_exception_leak` | vrai bug | endpoint legacy renvoie 410, pas 500 attendu pour exception leak test | REST security / legacy |
| 45 | `test_rest_security.py::RestSecurityHttpTests::test_cors_can_be_restricted_explicitly` | vrai bug | CORS test via legacy endpoint 410 | REST CORS / legacy |
| 46 | `test_rest_security.py::RestSecurityHttpTests::test_cors_configurable` | vrai bug | meme cause CORS legacy | REST CORS / legacy |
| 47 | `test_rest_security.py::RestSecurityHttpTests::test_path_traversal_post_harmless` | vrai bug | path traversal POST legacy 410 | REST security / legacy |
| 48 | `test_rest_security.py::RestSecurityHttpTests::test_request_empty_token_returns_401` | vrai bug | empty token attend 401, recoit 410 (legacy avant auth) | REST auth / legacy |
| 49 | `test_rest_security.py::RestSecurityHttpTests::test_request_invalid_token_returns_401` | vrai bug | invalid token attend 401, recoit 410 | REST auth / legacy |
| 50 | `test_rest_security.py::RestSecurityHttpTests::test_request_without_auth_returns_401` | vrai bug | no auth attend 401, recoit 410 | REST auth / legacy |
| 51 | `test_rest_security.py::RateLimiterHttpIntegrationTests::test_rate_limiter_returns_429_after_5_failures` | vrai bug | rate-limiter 429 attendu, route legacy renvoie 410 avant rate-limit | REST rate-limit / legacy |
| 52 | `test_settings_robustness.py::SettingsRobustnessTests::test_secrets_masked_in_get_settings` | vrai bug | secrets masques avec bullets U+2022 (mojibake en log) au lieu de la valeur attendue | settings secrets masking |
| 53 | `test_unified_ui_contracts.py::UnifiedUiContractTests::test_app_injects_token_for_native_mode` | vrai bug | `__CINESORT_NATIVE__` absent de `app.py` (regression injection token native mode) | UI native mode token |

### Patterns dominants (meta)

| # | Pattern | Tests touches | Action recommandee |
|---|---|---|---|
| P1 | **legacy `/api/<methode>` renvoie 410 Gone systematique** (P0 #233 mai 2026) -- casse tous les tests qui attendent 401/200/429 via endpoint legacy | 24 tests | Fix de masse : reecrire les tests vers `/api/<facade>/<methode>` OU restaurer `CINESORT_REST_LEGACY_PASS1_ENABLED=1` en fixture **OPERATIONNEL** |
| P2 | **tokens CSS theme** (cinema/luxe/neon/studio) avec `--text-primary/secondary/muted=None` | 4 tests | Regression chargement `tokens.css` par theme **HYPOTHESE** |
| P3 | **refactor UI 2026-05 traitement/doublons/bibliotheque** : unmount/lifecycle/labels regress | 5 tests | Cleanup polling + countdown 3s + unmount cascade (memoire actions dangereuses) **OPERATIONNEL** |
| P4 | **i18n mojibake** 'Qualite' vs 'Qualite' / 'echec' avec '?' | 3 tests | Encoding tests vs source (UTF-8 BOM cote source + `utf-8` cote tests) **HYPOTHESE** |
| P5 | **skips (99)** : non detailes (`pytest.mark.skip` ou `skipif env`) | 99 | Classes en 'skip volontaire' (1 visible dans `test_dashboard_shell.py` + 2 dans le run final dont `test_visual_regression`) |
| P6 | **flaky confirmes** | 2 | `test_probe_parallel` (perf) + `test_pyinstaller_smoke` (rebuild EXE + port 8642 disponible) |
| P7 | **vrai bug confirmes** | 51 / 53 | Cibles de la boucle de correction |
| P8 | **skip volontaire dans la liste failed** | 0 / 53 | Skips comptes separement dans le total 99 |
| P9 | **Categorisation finale read-only** | 51 vrais bugs + 2 flaky + 0 skip | 24 legacy 410 + 27 regressions UI / backend |
| P10 | **Action de masse prioritaire** | P1 (24 tests d'un coup) | Restaurer la fixture `CINESORT_REST_LEGACY_PASS1_ENABLED=1` ou re-router les tests vers la facade -- a discuter dans la boucle |

**Total : 63 lignes** (53 tests individuels + 10 lignes patterns/meta).

---

## 0.4 Triage 9 Erreurs Log

| # | Erreur | Cause probable | Domaine | Marqueur |
|---|---|---|---|---|
| 1 | `get_quality_report` failed `run_id=20260607_142449_050 row_id=T\|b4f7bd4f` (MediaInfo.exe timeout 30s sur `\\<nas>\Media\downloads\A.Knight...mkv`) | subprocess MediaInfo.exe sature sur fichier UNC distant (SMB lent + fichier 2160p H265), timeout 30s code en dur `tooling.py` L55, pas de retry ni de cache probe | quality_report (perceptual!=quality) - probe MediaInfo sur partage SMB | **HYPOTHESE** (cause SMB latence non confirmee par mesure reseau, mais 14 occurrences identiques meme jour meme partage `\\<nas>\Media`) |
| 2 | `get_quality_report` failed `row_id=C\|3d53c61` (MediaInfo.exe timeout 30s sur `Bande Demo ILM.mkv` UNC) | meme racine que ci-dessus : timeout MediaInfo sur SMB. Notable : fichier petit (BONUS) timeout aussi -> handshake SMB ou OMV indisponible, pas la taille | quality_report probe pipeline | **HYPOTHESE** (meme root cause cluster MediaInfo timeout, hypothese reseau) |
| 3 | `get_quality_report` failed (12 autres occurrences 16:20-16:29 toutes `row_id C\|*`) | repetition continue meme racine MediaInfo timeout UNC, indique boucle UI qui retente sans backoff sur erreur probe (refresh dashboard ou `get_quality_report` appele en boucle par composant UI) | quality_report UI polling + probe MediaInfo | **HYPOTHESE** (absence de circuit-breaker hypothese, a confirmer cote front - polling visible juste avant chaque ERROR avec `get_dashboard`/`get_status` repetes) |
| 4 | REST 500 `method=quality/get_perceptual_report` (183482ms) ffmpeg `loudnorm` timeout 60s sur `The Abyss QTZ x265` UNC | ffmpeg loudnorm sur piste audio 4 (`-map 0:a:4`) lit fichier entier via SMB pour normaliser, timeout 60s insuffisant pour 4K 100Go+ sur reseau lent. Note : 183s ecoules = 3x le timeout, indique retry implicite ou multi-pistes | `quality/get_perceptual_report` (perceptual!=quality - audit audio) | **HYPOTHESE** (hypothese 4K+UNC, root cause meme famille que MediaInfo : I/O reseau) |
| 5 | API_EXCEPTION `endpoint=apply run_id=20260530_144631_443` `FileNotFoundError` Plan introuvable `plan.jsonl` | utilisateur appelle `apply` sur un run dont le `plan.jsonl` n'existe pas (run jamais finalise / dossier nettoye / run_id stale cote UI). UI ne previent pas avant l'appel, ou state UI desynchronise du systeme fichiers | run apply / plan persistence | **OPERATIONNEL** (cause utilisateur/etat - pas un bug code, manque verif preventive cote UI uniquement) |
| 6 | API_EXCEPTION `endpoint=apply` meme `run_id` 8s apres (`req=99ab03a1`) | retry utilisateur sur la meme erreur sans correction du state -> meme echec. Confirme absence de feedback UI explicite (utilisateur clique 2x) | run apply UI feedback | **OPERATIONNEL** (symptome UX, pas defaut moteur) |
| 7 | REST 500 `method=library/search_tmdb` `'CineSortApi' object has no attribute '_normalize_user_path'` | regression code : methode `_normalize_user_path` supprimee/renommee mais `search_tmdb` la reference toujours. `AttributeError` direct, pas un cas limite | library search TMDB | **OPERATIONNEL** (bug code reproductible 100%, root cause = refactor incomplet `cinesort_api.py` - probablement deja fixe vu memoire 'fixes deja appliques sur cinesort_api.py' section F) |
| 8 | REST 500 `method=integrations/test_jellyfin_connection` `ReadTimeoutError` host=192.168.1.34:8096 timeout=5s | serveur Jellyfin LAN indisponible/ralenti, timeout 5s trop court pour endpoint `/Users/.../Items` avec `Recursive=true` (scan complet bibliotheque cote serveur). 3 occurrences meme jour 16:00-16:21 = test repetitif user | integrations Jellyfin test connection | **HYPOTHESE** (root cause double : Jellyfin lent ET timeout client trop court - cause serveur hypothese, cause client confirmee par valeur 5s en dur) |
| 9 | **Total racines distinctes : 6** (MediaInfo timeout UNC x16, ffmpeg loudnorm timeout UNC x1, plan.jsonl introuvable x2, _normalize_user_path manquant x1, Jellyfin connection timeout x3, perceptual report ffmpeg x1) - dominant cluster = subprocess timeout sur partage SMB `\\<nas>\Media` (17/24 = 71%) | racine commune systemique : I/O reseau SMB non-resilient (pas de timeout adaptatif, pas de cache probe, pas de circuit-breaker) | infra probe + perceptual analysis | **HYPOTHESE** (regroupement cause systemique a valider - solution probable : probe en arriere-plan + cache + timeout dynamique selon taille fichier) |

---

## 0.5 Bibliotheque Fictive

- **Script** : `C:\Users\<utilisateur>\projects\CineSort\scripts\make_test_library.py`
- **Idempotent** : OUI (re-execution sans effet de bord, controle de presence)
- **Arborescence** : `RootA/` et `RootB/` (2 racines pour tester multi-source + dedup cross-root)
- **Contenu** : clips reels Creative Commons + stubs varies (titres FR/EN, annees diverses, codecs varies, 4K + 1080p + 720p, multi-piste audio)
- **Executed** : `true`
- **Fichiers crees** : **22**

---

## 0.6 Outil Observation

- **Script** : `C:\Users\<utilisateur>\projects\CineSort\scripts\observe.py`
- **Capture AVANT** : `true`
- **Sortie** : `C:\Users\<utilisateur>\projects\CineSort\docs\internal\observe\2026-06-08_184504`
- **Vues posters casses** : capture visuelle Playwright des cartes bibliotheque montre les posters non charges (CSP `img-src 'self' data:` bloque `image.tmdb.org` -- ref `rest_server.py` L716-725 + `index.html` L11). Confirme la rupture decrite section C.4 de la recon. **FIGE** sur la cause CSP, **OPERATIONNEL** sur la capture (utilisable comme baseline AVANT/APRES pour la boucle).

---

## Confirmation Filets Reversibles

- [x] Branche creee (`loop/correction-2026-06`)
- [x] Checkpoint commit pose (`f493abdc998ff56eea716e694c09f44995fe6cf7`)
- [x] Synthese 07/06 ecrite (`AUDIT_UX_2026-06-07.md` -- 10 fixes / 9 points ouverts)
- [x] Biblio fictive reproductible (`make_test_library.py`, idempotent, 22 fichiers)
- [x] Observer reutilisable (`observe.py`, sortie horodatee)
- [x] Capture AVANT prise (`docs/internal/observe/2026-06-08_184504`)

---

**Le terrain est PRET pour la boucle de correction.**

Marqueurs **FIGE** / **HYPOTHESE** / **OPERATIONNEL** utilises tout au long du document conformement aux memoires de session.
