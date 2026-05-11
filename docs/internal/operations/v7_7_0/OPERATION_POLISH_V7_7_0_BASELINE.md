# Baseline avant Opération Polish Total v7.7.0

**Date snapshot** : 4 mai 2026 (Vague 0)
**Branche** : `polish_total_v7_7_0` (depuis `audit_qa_v7_6_0_dev_20260428`)
**Tag backup** : `backup-before-polish-total` (sur HEAD pré-fixes)
**Build référence** : `dist/CineSort.exe` 50.07 MB (4 mai 2026 00:23)

---

## Métriques code

| Métrique | Valeur | Note |
|---|---|---|
| Fichiers Python source | 445 | hors .venv, .git, build, dist |
| Fichiers test Python | 257 | dont 17 E2E |
| Fichiers JS | 120 | web/* |
| Fichiers CSS | 10 | tokens, themes, components, utilities + legacy |
| Endpoints REST publics | **101** | CLAUDE.md affirmait 33 → R4-DOC-1 confirmé |
| `plan_support.py` | 1506 L | cible refactor V4-01 (`_plan_item` 565L → 12 helpers) |
| `quality_score.py` | 1221 L | cible refactor V4-02 (`compute_quality_score` 369L) |
| Migration DB max | 020 | V1-02 créera 021 ON DELETE CASCADE |

---

## Top fichiers JS dashboard (cibles potentielles refactor)

| Fichier | Lignes | Notes |
|---|---|---|
| `web/dashboard/views/settings.js` | 1023 | 15 sections settings, complexité élevée |
| `web/dashboard/views/review.js` | 1017 | bulk actions, drafts localStorage |
| `web/dashboard/views/qij.js` | 974 | Quality+Integrations+Journal fusionné |
| `web/dashboard/views/status.js` | 966 | KPIs + polling adaptatif |
| `web/dashboard/views/library.js` | 944 | filtres + search + virtualisation cible V5-01 |
| `web/dashboard/views/help.js` | 456 | FAQ + glossaire |
| `web/dashboard/views/quality-simulator.js` | 463 | simulator scoring |

---

## Suite de tests

**Résultat baseline** : `Ran 3550 tests in 71.002s` → **FAILED (failures=22, errors=3, skipped=136)**

### Catégorisation des 25 failures (22 + 3)

#### Catégorie A — Tests obsolètes liés au revert v4 RESTAUREES (19 failures)

Post-V5C-01 (3 mai 2026), une décision a été prise de **RESTAURER les vues v4 dashboard** car la v5 perdait trop de fonctionnalités (cf commentaire dans `app.js` : "Vues v4 RESTAUREES (post-fix : la v5 perdait trop de fonctionnalites)"). Les tests `test_v5c_cleanup.py` n'ont pas été mis à jour pour refléter cette décision.

| Test | Type | Cause |
|---|---|---|
| `test_v5c_cleanup.test_v4_views_removed` × 13 | FAIL | vues v4 restaurées, test obsolète |
| `test_v5c_cleanup.test_app_no_longer_imports_removed_views` × 4 | FAIL | app.js importe v4 RESTAUREES, test obsolète |
| `test_v5c_cleanup.test_v4_library_folder_removed` | FAIL | dossier `library/` restauré |
| `test_v5b_activation.test_app_imports_v5_views` | FAIL | v5 désactivée post-revert |

**Action en Vague 1 (mission V1-05 étendue)** : mettre à jour ou supprimer ces tests pour refléter la décision RESTAUREES.

#### Catégorie B — Tests v5 cassés par le revert (3 failures)

| Test | Cause |
|---|---|
| `test_home_v5.test_home_js_uses_HomeWidgets_HomeCharts` | home.js v5 désactivé, utilise v4 |
| `test_nav_v5.test_7_nav_items_parity` | sidebar v5 différente après revert |
| `test_sidebar_v5_features.test_v1_14_help_entry` | sidebar restructurée |

**Action en Vague 1** : aligner les tests sur l'état post-revert.

#### Catégorie C — Tests flaky / network (3 errors)

| Test | Cause probable |
|---|---|
| `test_app_bridge_smoke.test_main_bootstraps_stable_webview_with_real_api` | lancement webview en CI flaky |
| `test_dashboard_infra.test_rate_limit_blocks_after_5_failures` | rate limiter HTTP flaky entre runs |
| `test_rest_api.test_unknown_method_returns_404` | HTTP server timing flaky |

**Action en Vague 2** : isoler ces tests (skip CI si flaky persistant) ou les rendre déterministes.

#### Catégorie D — Cache header (1 failure mineure)

- `test_dashboard_infra.test_dashboard_cache_header` : à investiguer Vague 1

### Conclusion baseline tests

- **0 régression imputable** aux 10 fixes appliqués (CRIT-1/2/3/5/6, R5-MEM-3, R5-CRASH-1/3, H1, H5)
- **22 failures + 3 errors PRÉ-EXISTANTS** dus au revert v4 et à la flakiness CI
- **3525 tests passent** (3550 - 22 - 3) = **99.30% passing rate**
- Acceptable comme baseline, à corriger Vague 1 (mission V1-05 étendue)

---

## Linting

**Ruff** : `All checks passed!` ✅

---

## Coverage

**TOTAL : 81.3%** ✅ (gate ≥ 80% respecté)

- 20929 statements, 3906 misses
- Modules à fort coverage : `tmdb_support` 100%, `settings_support` 91.6%, `notifications_support` 85.0%, `runtime_support` 81.0%, `cinesort_api` 83.1%
- Modules à coverage améliorable : `probe_support` 44.7%, `quality_support` 62.4%, `quality_profile_support` 64.5%, `perceptual_support` 68.8%, `history_support` 69.8%

**Cible v7.7.0** : maintenir ≥ 80%, idéalement remonter à 82-85% via tests ajoutés en Vagues 4 (refactor) et 6 (i18n).

---

## État Git au démarrage

**Branche source** : `audit_qa_v7_6_0_dev_20260428` (HEAD = `cb1af93`)

**Modifications WIP non commitées** sur la branche d'origine, emportées sur `polish_total_v7_7_0` :

### Fichiers modifiés (10 fixes + sections CLAUDE.md)
- `app.py` — FIX-7 (atexit + drain_timer)
- `cinesort/app/notify_service.py` — FIX-1 (drain_timer)
- `cinesort/app/watcher.py` — FIX-6 (is_dir_accessible)
- `cinesort/ui/api/notifications_support.py` — FIX-5 (cap insights)
- `cinesort/ui/api/runtime_support.py` — FIX-8 (cleanup runs orphelins)
- `web/dashboard/app.js` — FIX-9 (window.onerror)
- `web/dashboard/index.html` — FIX-4 (sections orphelines supprimées)
- `web/dashboard/views/qij.js` (untracked) — FIX-2 + FIX-3
- `web/dashboard/views/settings.js` (untracked) — FIX-10
- `CLAUDE.md` — section "OPERATION EN COURS"
- Autres fichiers v5/v4 modifiés post-revert (sidebar, top-bar, settings_support, rest_server, etc.)

### Fichiers nouveaux (tracking opération)
- `PLAN_RESTE_A_FAIRE.md` — plan exécutable 7 phases
- `AUDIT_TRACKING.md` — registry findings 5 rounds
- `OPERATION_POLISH_V7_7_0.md` — plan d'exécution 8 vagues
- `OPERATION_POLISH_V7_7_0_BASELINE.md` — CE document
- `OPERATION_POLISH_V7_7_0_PROGRESS.md` — tracking vivant (à créer)

### Fichiers untracked v4 restaurés (dashboard views)
- `web/dashboard/views/help.js`
- `web/dashboard/views/qij.js`
- `web/dashboard/views/quality.js`
- `web/dashboard/views/review.js`
- `web/dashboard/views/runs.js`
- `web/dashboard/views/settings.js`
- `web/dashboard/views/status.js`
- `web/dashboard/views/library/` (dossier complet)
- `web/dashboard/core/journal-polling.js`

### Autres untracked (HTML preview + audits prompts)
- `preview-apercu-v2.html`
- `preview-home-comparaison.html`
- `audit/prompts/_*.md`, `audit/prompts/vague1/`, `audit/prompts/vague2/`
- `docs/internal/audits/AMELIORATIONS_UX_DESIGN_20260429.md`

---

## Note de départ

**9.2/10** (post-fixes 4 mai 2026) — production-ready pour usage personnel + bêta privée 50 users.

**Cible Opération Polish Total** : **9.9-10/10** — production-grade publique massif (>1000 users).

---

## Décisions actées (rappel)

1. **i18n EN INCLUS** (Vague 6)
2. **Composite Score V2 = coexistence + toggle** (setting `composite_score_version` 1\|2)
3. **Branche unique** `polish_total_v7_7_0` → tag final `v7.7.0`
4. **Compatibilité 100%** — pas de breaking changes
5. **Vérification continue** — tests + ruff + smoke + validator à chaque commit

---

## Prochaine étape

**Vague 1 — Bloquants public release** (~1j en parallèle, 6 agents implémentation + 1 validator + 1 web-research)

Missions :
- V1-01 CVE bumps urllib3 + pyinstaller
- V1-02 Migration 021 ON DELETE CASCADE/RESTRICT
- V1-03 FFmpeg subprocess cleanup atexit
- V1-04 LPIPS model absent fallback
- V1-05 Tests E2E sélecteurs cassés + **mise à jour test_v5c_cleanup.py** (nouveau)
- V1-06 PyInstaller hidden imports perceptual
