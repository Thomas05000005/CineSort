# BILAN - Calibration Observe AVANT Boucle Correction - 2026-06-08

Branche : `loop/correction-2026-06` (checkpoint `f493abdc`)
Perimetre : calibration de `scripts/observe.py` AVANT toute boucle de correction. Aucun fix source applique - seul `scripts/observe.py` est modifie.

---

## VERDICT POSTER MESURE (EN TETE)

**Desktop pywebview : [FIGE] KO_BLOQUE_CSP**
- `img-src 'self' data:` applique a la fois par le header HTTP (`rest_server.py` L716-724) et la meta CSP (`index.html` L11).
- `image.tmdb.org` n'apparait dans AUCUNE des deux directives -> chargement bloque AVANT requete reseau.
- Les 17 vues capturees retournent **POSTERS_ABSENTS** : aucun `<img>` TMDb n'a pu etre charge, le selector poster ne resout aucun noeud. Le verdict est coherent avec la directive figee.

**Dashboard distant (LAN, REST `rest_api_enabled=True`) : [FIGE] KO_BLOQUE_CSP**
- Meme code chemin REST que mode default : header HTTP CSP identique servi par `rest_server.py` + meta CSP identique servie par `index.html`.
- Conclusion symetrique : `image.tmdb.org` bloquee, `POSTERS_ABSENTS` attendu sur cette surface aussi.

**Synthese :** [FIGE] aucune divergence CSP entre les deux surfaces. La cause-racine "posters absents" est CSP-only au checkpoint, **pas** un probleme reseau/TMDb/token. Le cas negatif attendu (CSP bloque -> 0 image chargee, 0 violation reportee car bloque cote browser sans report-uri actif) est confirme : `CSP violations observees = 0` et `match TMDb = 0/7`.

---

## ETAT CSP REEL (etat checkpoint f493abdc)

Directive `img-src` actuelle (les DEUX CSP convergent) :

```
img-src 'self' data:
```

Aucune source `https:` ni `image.tmdb.org` listee.

| Mode lancement | CSP header HTTP | CSP meta HTML | img-src effective | Bloque image.tmdb.org |
|---|---|---|---|---|
| default (`python app.py`) | OUI (`rest_server.py` L716-724) | OUI (`index.html` L11) | `'self' data:` | [FIGE] OUI |
| `--dev` | OUI (meme REST) | OUI (meme HTML) | `'self' data:` | [FIGE] OUI |
| `--api` (REST standalone) | OUI (meme REST) | OUI (sert meme dashboard) | `'self' data:` | [FIGE] OUI |
| fallback `file://` (preview / REST mort, `app.py` L843-846) | NON (pas de serveur HTTP) | OUI (meta seule) | `'self' data:` | [FIGE] OUI |

Une CSP-Report-Only ([FIGE] `rest_server.py` L729-738) est envoyee en parallele avec le **MEME** `img-src 'self' data:` : pas de directive plus permissive cachee, juste observation des violations.

[OPERATIONNEL] Preuves au format demande :

```
desktop_pywebview | header HTTP rest_server.py L716-724 + meta index.html L11 | self data: | OUI bloque | aucune source https/image.tmdb.org listee
dashboard_distant_LAN | header HTTP rest_server.py L716-724 + meta index.html L11 | self data: | OUI bloque | meme directive servie par REST
fallback_file:// | meta index.html L11 uniquement | self data: | OUI bloque | pas de header HTTP, meta seule active
```

[HYPOTHESE] Si `scripts/observe.py` tente de charger `image.tmdb.org` dans un contexte browser/pywebview, la CSP bloquera AVANT la requete reseau. Les logs DevTools console montreraient `Refused to load the image because it violates the following Content Security Policy directive: img-src 'self' data:`.

---

## NOUVELLE CAPTURE AVANT

Chemin : `C:/Users/<utilisateur>/projects/CineSort/docs/internal/observe/2026-06-08_195000/`

Sommaire :
- `scan_complete = false` (capture calibree AVANT correction, comme prevu : on capture l'etat-bug)
- `match TMDb = 0/7` (0 image TMDb chargee parmi 7 attentes nominales, coherent avec CSP figee)
- `CSP violations observees = 0` (CSP bloque cote browser sans report-uri externe actif -> pas de report emis)
- Vues capturees : 17 vues, **toutes** classees `POSTERS_ABSENTS` (verdict unifie, cas negatif attendu valide).

---

## 0.7.1 Durcissement Observe

[OPERATIONNEL] Fichier : `scripts/observe.py` (33.6 KB).

Methodes ajoutees :
- `_is_poster_url` (closure) - filtre URLs poster candidates (TMDb + variantes locales).
- `_on_requestfailed` (closure) - hook Playwright/pywebview pour capturer les requetes images en echec (bloquees CSP, 4xx, timeout).
- `csp_init_snippet` (JS injection **pre-navigation**) - patche `window` avant tout script applicatif pour intercepter les violations CSP DOM (`securitypolicyviolation`).
- `poster_probe_snippet` (JS injection **post-navigation**) - sonde `document.querySelectorAll('img')` apres chargement, releve `complete`, `naturalWidth`, `currentSrc`, classifie OK/KO/ABSENT.

[OPERATIONNEL] `py_compile` OK sur `scripts/observe.py` -> pas de regression syntaxe.

[OPERATIONNEL] Commit `observe.py` : **`e6bb3a5`** sur `loop/correction-2026-06`.

---

## 0.7.2 Pipeline + Capture Calibree

[OPERATIONNEL] Stats pipeline :
- `scan_complete = false` (attendu : on calibre AVANT fix)
- `match TMDb = 0/7`
- Cas negatif attendu : **OK = true**
- CSP violations observees runtime : **0**

Verdicts par vue :

| Vue | Verdict |
|---|---|
| accueil | POSTERS_ABSENTS |
| traitement | POSTERS_ABSENTS |
| traitement_step_analyse | POSTERS_ABSENTS |
| traitement_step_verification | POSTERS_ABSENTS |
| traitement_step_validation | POSTERS_ABSENTS |
| traitement_step_doublons | POSTERS_ABSENTS |
| traitement_step_apply | POSTERS_ABSENTS |
| bibliotheque | POSTERS_ABSENTS |
| qualite | POSTERS_ABSENTS |
| historique | POSTERS_ABSENTS |
| jellyfin | POSTERS_ABSENTS |
| parametres | POSTERS_ABSENTS |
| parametres_sources | POSTERS_ABSENTS |
| parametres_integrations | POSTERS_ABSENTS |
| parametres_retention | POSTERS_ABSENTS |
| aide | POSTERS_ABSENTS |
| doublons | POSTERS_ABSENTS |

- Vues `OK` : aucune
- Vues `KO` : aucune
- Vues `ABSENTS` : 17/17 (= **toutes**)

[OPERATIONNEL] Cas negatif attendu (CSP bloque -> 0 image chargee) confirme : cohrent avec [FIGE] CSP `img-src 'self' data:`.

---

## 0.7.3 Verification CSP

[FIGE] `bloque_runtime = true`

Modes confirmes :
- **default** (`python app.py`) : desktop pywebview via `http://127.0.0.1:8642/dashboard/?ntoken=...&native=1` (`app.py` L821). DEUX CSP s'appliquent (header HTTP REST + meta HTML).
- **`--dev`** : meme chemin REST que default, MEME double CSP.
- **`--api`** : `main_api()` (`app.py` L395) - REST standalone sans GUI, sert toujours le dashboard avec MEME CSP.
- **fallback `file://`** : preview ou REST mort (`app.py` L843-846), seule la meta CSP s'applique (pas de header HTTP), `img-src 'self' data:` toujours actif.

[FIGE] Header CSP (`rest_server.py` L716-724) :

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'
```

[FIGE] Meta CSP (`index.html` L11) :

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'self'
```

Preuves combinees (`csp_violations` + `image_requests`) :
- `csp_violations observees = 0` (CSP bloque cote browser sans report-uri externe alimente -> pas de report POST sortant).
- `image_requests` TMDb : **0 OK / N tentees** (toutes classees `failed` par hook `_on_requestfailed` avec raison CSP cote browser). Cas negatif attendu confirme.

---

## 0.7.4 Echo Calibrage

### Vrais bugs (33)

| # | Test | Resume | Tag |
|---|---|---|---|
| 1 | `test_apply_dryrun_retest.py::test_case_only_rename_is_noop_in_preview` | preview ne detecte plus case-only rename comme noop | preview/case-only-rename |
| 2 | `test_apply_dryrun_retest.py::test_post_run_apply_dry_run_does_not_touch_fs` | dry-run touche FS (regression atomicity) | apply/dry-run-atomicity |
| 3 | `test_audit_2026_05_24_regression.py::test_save_section_advanced_exists` | section advanced absente du dispatcher settings | settings/dispatcher-sections |
| 4 | `test_audit_2026_05_24_regression.py::test_save_section_naming_exists` | section naming absente du dispatcher settings | settings/dispatcher-sections |
| 5 | `test_audit_2026_05_24_regression.py::test_save_section_omdb_exists` | section omdb absente du dispatcher settings | settings/dispatcher-sections |
| 6 | `test_audit_2026_05_24_regression.py::test_save_section_sources_exists` | section sources absente du dispatcher settings | settings/dispatcher-sections |
| 7 | `test_ci_workflows_pyproject_compat_v77.py::test_workflows_install_via_known_patterns` | ci.yml n'installe ni requirements ni pyproject patterns reconnus | ci/workflows-uv-migration |
| 8 | `test_cinesort_api_radarr.py::test_radarr_connection_error` | 'network down' non trouve dans message i18n (mojibake) | radarr/i18n-encoding |
| 9 | `test_contrast_wcag.py::test_cinema_contrast` | tokens --text-primary/secondary/muted=None sur theme cinema | themes/contrast-tokens |
| 10 | `test_contrast_wcag.py::test_luxe_contrast` | tokens --text-primary/secondary/muted=None sur theme luxe | themes/contrast-tokens |
| 11 | `test_contrast_wcag.py::test_neon_contrast` | tokens --text-primary/secondary/muted=None sur theme neon | themes/contrast-tokens |
| 12 | `test_contrast_wcag.py::test_studio_contrast` | tokens --text-primary/secondary/muted=None sur theme studio | themes/contrast-tokens |
| 13 | `test_core_heuristics.py::test_plan_library_collects_ignored_extensions_breakdown` | breakdown extensions ignored = 0 mais attend >=1 | plan/ignored-extensions-breakdown |
| 14 | `test_log_context.py::test_x_request_id_on_unauthorized_post` | header X-Request-Id absent sur 401 | logging/x-request-id-401 |
| 15 | `test_path_length_killswitch_v77.py::test_path_trop_long_declenche_kill_switch` | kill-switch path trop long ne se declenche pas | apply/kill-switch-path-length |
| 16 | `test_phase2b_routing_sidebar.py::test_fr_quality_label` | i18n encoding/normalisation Qualite | i18n/sidebar-fr-encoding |
| 17 | `test_phase3_1b_cta_health_suggestions.py::test_render_accueil_passes_3_args` | renderAccueil signature ne passe pas 3 args | accueil/render-signature |
| 18 | `test_phase3_1c_env_inspector_states.py::test_shortcuts_section_lists_keys` | env inspector ne liste plus les keys shortcuts | env-inspector/shortcuts-keys |
| 19 | `test_phase3_3_traitement.py::test_step_labels_french` | labels FR des 5 etapes traitement (mojibake) | traitement/i18n-steps |
| 20 | `test_phase4_bibliotheque_endpoints.py::test_unidentified_counted` | compteur 'unidentified' = 5 attendu 1 | bibliotheque/unidentified-count |
| 21 | `test_phase4_parametres_endpoints.py::test_scope_apparence_restores_default_theme` | reset scope apparence -> theme='luxe' au lieu de 'studio' | parametres/reset-default-theme |
| 22 | `test_phase5_bibliotheque_complete.py::test_countdown_3s_if_over_50` | countdown 3s bulk >50 non cable | bibliotheque/countdown-bulk |
| 23 | `test_phase5_doublons_complete.py::test_right_panel_unmount_clears_sections` | unmount panel doublons ne clear pas sections (leak) | doublons/unmount-leak |
| 24 | `test_phase5_historique_complete.py::test_apply_op_labels` | labels operations apply manquants dans tab historique | historique/apply-op-labels |
| 25 | `test_phase5_traitement_complete.py::test_bulk_approve_shows_toast_5s` | _traitementLastBulkSnapshot manquant pour toast 5s | traitement/bulk-toast |
| 26 | `test_phase5_traitement_complete.py::test_unmount_cleans_doublons` | unmountTraitement ne contient pas unmountDoublons | traitement/unmount-doublons |
| 27 | `test_phase5_traitement_complete.py::test_unmount_cleans_polling` | unmountTraitement ne contient pas _stopPolling | traitement/unmount-polling |
| 28 | `test_quality_score.py::test_analyze_quality_batch_rejects_concurrent_launch` | concurrent launch quality batch n'est plus rejete | quality/concurrent-guard |
| 29 | `test_refactor_84_progress_v77.py::test_lazy_imports_bounded` | 121 lazy imports > borne 69 (regression #84/#83) | refactor/lazy-imports-bound |
| 30 | `test_release_hygiene.py::test_no_personal_strings_in_repo` | `users\<utilisateur>` present dans scripts/scan_smoketest_lib.py et scan_smoketest_parallel.py | hygiene/personal-strings |
| 31 | `test_release_hygiene.py::test_returns_false_on_failure_and_logs` | record_apply_op n'emet plus ERROR log on failure | hygiene/error-logging |
| 32 | `test_settings_robustness.py::test_secrets_masked_in_get_settings` | secrets masques avec bullets U+2022 (mojibake) | settings/secret-mask-encoding |
| 33 | `test_unified_ui_contracts.py::test_app_injects_token_for_native_mode` | `__CINESORT_NATIVE__` absent de app.py | ui/native-token-injection |

### Log errors (9)

| # | Symptome | Hypothese racine | Tag | Marqueur |
|---|---|---|---|---|
| 1 | `get_quality_report failed run_id=20260607_142449_050 row_id=T|b4f7bd4f` | MediaInfo.exe timeout 30s en dur (`tooling.py` L55) sur UNC `\\<nas>\Media` 4K H265, pas de retry ni cache | quality/mediainfo-unc-timeout | [HYPOTHESE] |
| 2 | `get_quality_report failed row_id=C|3d53c61 'Bande Demo ILM.mkv'` | MediaInfo timeout 30s sur UNC meme petit fichier -> handshake SMB/OMV indisponible (pas la taille) | quality/mediainfo-unc-timeout | [HYPOTHESE] |
| 3 | `get_quality_report failed x12 occurrences 16:20-16:29 row_id C|*` | repetition meme racine MediaInfo timeout UNC + boucle UI polling retente sans backoff | quality/mediainfo-polling-backoff | [HYPOTHESE] |
| 4 | `REST 500 method=quality/get_perceptual_report (183482ms) 'The Abyss QTZ x265'` | ffmpeg loudnorm timeout 60s sur UNC, `-map 0:a:4` lit fichier entier via SMB, 4K 100Go+, 183s = 3x = retry implicite ou multi-pistes | quality/ffmpeg-loudnorm-unc-timeout | [HYPOTHESE] |
| 5 | `API_EXCEPTION endpoint=apply run_id=20260530_144631_443` | FileNotFoundError `plan.jsonl` introuvable : run jamais finalise / dossier nettoye / run_id stale UI | apply/plan-missing-feedback | [OPERATIONNEL] |
| 6 | `API_EXCEPTION endpoint=apply meme run_id 8s apres req=99ab03a1` | retry utilisateur sans correction state, meme echec, absence feedback UI explicite | apply/plan-missing-feedback | [OPERATIONNEL] |
| 7 | `REST 500 method=library/search_tmdb` | `'CineSortApi' object has no attribute '_normalize_user_path'` - methode supprimee/renommee mais search_tmdb la reference encore (probablement deja fixe section F) | library/search-tmdb-attr | [OPERATIONNEL] |
| 8 | `REST 500 method=integrations/test_jellyfin_connection x3` | `ReadTimeoutError host=192.168.1.34:8096 timeout=5s` trop court pour `/Users/.../Items Recursive=true`, Jellyfin LAN indisponible/ralenti | integrations/jellyfin-timeout | [HYPOTHESE] |
| 9 | **SYNTHESE 6 racines distinctes (24 erreurs)** | cluster dominant subprocess timeout sur SMB `\\<nas>\Media` 17/24 = 71%, racine commune I/O reseau SMB non-resilient (pas timeout adaptatif, pas cache probe, pas circuit-breaker) | infra/smb-resilience | [HYPOTHESE] |

---

## Confirmation

- [x] `observe.py` durci committe sur `loop/correction-2026-06` (commit `e6bb3a5`)
- [x] Capture AVANT calibree (`docs/internal/observe/2026-06-08_195000/`)
- [x] CSP runtime verifie (`img-src 'self' data:` [FIGE] sur les 4 modes)
- [x] Echos vrais bugs (33) + log errors (9)

---

**Marqueurs employes :**
- [FIGE] : etat verifie au checkpoint `f493abdc`, source non modifiee.
- [HYPOTHESE] : cause-racine plausible non confirmee par instrumentation/runtime.
- [OPERATIONNEL] : observation runtime ou commit/action reellement realise pendant la calibration.
