# Plan de Remédiation Exhaustif — CineSort v7.7.0 → v7.8.0

**Date** : 10 mai 2026
**Branche cible** : `polish_total_v7_7_0` (working tree clean au moment de la rédaction)
**Source** : audit exhaustif 6 agents parallèles (reuse, quality, efficiency, security, tests, architecture, frontend)
**Validation utilisateur** : approuvé tel quel, exécution dans l'ordre

---

## Mandat utilisateur

- Tout corriger, pas de raccourcis
- Recherche systématique AVANT modification (jamais d'edit à l'aveugle)
- Zéro régression tolérée
- Recherches web autorisées (CVE, best practices)
- **CLAUDE.md mis à jour EN PREMIER** (avec la vérité)
- Approche dev pro dans chaque domaine
- Validation utilisateur entre chaque phase

---

## Discrépances CLAUDE.md vs réalité (rappel)

CLAUDE.md revendique **9.9/10** et plusieurs métriques précises. Les agents ont **mesuré indépendamment** :

| Métrique CLAUDE.md | Revendiqué | Mesuré |
|---|---|---|
| Fonctions > 100L | "0 restantes" | **49 trouvées** (incl. `_execute_perceptual_analysis` 309L, `apply_rows` 271L, `quarantine_row` 278L) |
| Fonctions > 150L | "interdit sans justif" | **12 trouvées sans justif** |
| `except Exception` | "interdit" | **41 occurrences** dans 12 fichiers |
| Magic numbers | "0 dans scoring" | **277 occurrences** (Ruff PLR2004 désactivé) |
| Duplication identifiée | "0" | `video_exts` hardcodé 5× différemment, tier API dual, 22 composants JS dupliqués |
| Tests passants | "3893/3893 (100%)" | 3893 pass + **30 skip cachés**, dont **19 skips "V5C-03 deferred"** depuis ~6 mois |

**Note réaliste consensus 3 agents** : **7.2 à 7.5 / 10** (vs 9.9 revendiqué).

---

## Principes Directeurs (à respecter à chaque phase)

1. **Branche dédiée par phase** : `audit-cleanup/phase-N-<topic>` depuis `polish_total_v7_7_0`. Merge dans une branche d'intégration `v7.8.0-prep` après validation.

2. **Test baseline immuable** : avant TOUTE modification de `plan_library`, `apply_core`, `quality_score`, capturer un fingerprint SHA256 sur fixture synthétique. Re-vérifier après.

3. **Recherche obligatoire avant edit** :
   - `Grep` sur tous les call sites avant de modifier une signature
   - `Read` du fichier complet (pas excerpt) avant tout refactor structurel
   - `WebFetch` doc officielle si doute sur sémantique
   - `WebSearch` CVE/issues récents si touche aux dépendances
   - Vérifier les tests existants qui couvrent la zone

4. **Validation à 4 niveaux** après chaque phase :
   - Tests unitaires ciblés (zone touchée)
   - Suite complète (`python -m unittest discover -s tests`)
   - Ruff clean + format
   - Build EXE (`pyinstaller CineSort.spec --clean --noconfirm`) + smoke test launch

5. **Rollback prévu** : chaque commit doit être revertible.

6. **Pas de feature creep** : si un problème adjacent apparaît pendant une phase, l'ajouter au backlog, ne pas dévier.

7. **Documentation immédiate** : BILAN_CORRECTIONS.md mis à jour à la fin de chaque phase.

8. **Aucun fix purement cosmétique** dans une phase fonctionnelle. Polish séparé.

9. **Validation utilisateur entre phases** : présenter le résultat, attendre OK avant phase suivante.

---

## ORDRE D'EXÉCUTION

```
Phase 0   — CLAUDE.md vérité ★ EN PREMIER
Phase 1   — Sécurité bloquante (SEC-H1, H2, BUG-1, DATA-2, BUG-3)
Phase 4   — Visual regression réel (pré-requis avant phases UI)
Phase 2   — Performance hot paths (gains 15-20 min/scan)
Phase 3   — Tests sécurité-critiques (move_journal, composite_score V1, DPAPI)
Phase 5   — Quality quick wins (noqa morts, console.log, var, etc.)
Phase 6   — Cohérence (tier API unifié, video_exts, codec taxonomy) — migration DB 022
Phase 7   — Dead code cleanup (DEMANDE CONFIRMATION pour frontend legacy)
Phase 8   — Refactor reuse backend (BaseRestClient, response factory)
Phase 9   — Frontend dedup (composants → shared)
Phase 11  — API REST HTTP codes corrects
Phase 13  — Tests manquants (cancel apply, upgrade DB, PyInstaller smoke)
Phase 15  — Settings : dataclass + validation
Phase 12  — Refactor fonctions > 150L
Phase 16  — Tests migrations DB systématiques
Phase 10  — Cycle domain↔app (GROS CHANTIER)
Phase 14  — Ruff strict
Phase 17  — Packaging + dépendances (CVE audit)
Phase 18  — Release v7.8.0
```

---

## PHASE 0 — CLAUDE.md (vérité d'abord)

**Objectif** : remplacer les revendications fausses par des faits mesurés.

### Recherche préalable

```bash
grep -rn "except Exception" cinesort/ | wc -l
python -c "import ast,os; ..."  # script AST pour fonctions > 100L
ruff check cinesort/ --select=PLR2004,BLE001,PLR0913,C901 --statistics
find cinesort web -name "*.py" -o -name "*.js" | xargs wc -l
python -m unittest discover -s tests 2>&1 | grep -E "Ran|skipped|OK|FAILED"
```

Stocker dans `audit/results/v7_7_0_real_metrics_20260510.md`.

### Plan d'action

1. **Créer `scripts/measure_codebase_health.py`** : script qui mesure toutes les métriques de manière reproductible
2. **Lancer script et créer `audit/results/v7_7_0_real_metrics_20260510.md`** avec les chiffres mesurés
3. **Réécrire section "État de santé" de CLAUDE.md** :
   - Note honnête (proposition : 7.5/10 avec décomposition par axe)
   - Chiffres réels remplaçant les revendications
   - Section "Dette technique connue" listant les 5 gros chantiers
   - Date de mise à jour
4. **Ajouter section "Vérification continue"** dans CLAUDE.md (comment recalculer)
5. **Mettre à jour `ROADMAP.md`** ou décider de le décommissionner
6. **Ajouter `tests/test_doc_consistency.py`** : asserte que CLAUDE.md correspond aux mesures (±10%)
7. **Archiver les revendications obsolètes** dans `docs/internal/historique_revendications_v7.md`

### Validation

- CLAUDE.md cohérent avec mesures
- Tests passent (doc only)
- BILAN_CORRECTIONS.md mis à jour

---

## PHASE 1 — Sécurité bloquante

### 1.1 — SEC-H1 : Scrubber SMTP password incomplet

**Fichier** : `cinesort/infra/log_scrubber.py:44`
**Problème** : regex actuelle ne couvre pas `email_smtp_password`
**Recherche** : grep tous les fields `password|token|key|secret` dans settings, recherche web "python logging filter best practices secrets scrubbing"
**Plan** : refondre `_SCRUB_PATTERNS` avec regex unique pour toute clé JSON `*_password|*_token|*_api_key|*_secret`
**Tests** : 15+ payloads contenant secrets, asserter aucune fuite

### 1.2 — SEC-H2 : `get_settings` expose clés TMDb + Jellyfin en clair

**Fichier** : `cinesort/ui/api/settings_support.py:883`
**Problème** : `_SECRET_FIELDS` manque `tmdb_api_key`, `jellyfin_api_key`, `omdb_api_key`, `osdb_api_key`
**Recherche** : grep call sites `api.get_settings()`, comprendre usage frontend
**Décision design à prendre** : Option A (ajouter à `_SECRET_FIELDS` + `_has_X_key: bool`) recommandée
**Plan** : ajouter les 4 clés, frontend adapté pour masque `••••••`
**Tests** : REST endpoint sans secret, save_settings préserve blobs

### 1.3 — DATA-2 : `data.db` tracké
`git rm --cached data.db` + vérifier `.gitignore`

### 1.4 — BUG-1 : `JellyfinError(Exception)`
**Plan** : créer `cinesort/infra/integration_errors.py` avec `IntegrationError` et hiérarchie `JellyfinError|PlexError|RadarrError|OmdbError|OpensubtitlesError`. Refactor `except Exception` annotés en `except IntegrationError`.

### 1.5 — BUG-3 : Précédence and/or
**Fichier** : `quality_score.py:410`
**Plan** : parenthèses explicites + commentaire intention

### Validation Phase 1
- Suite complète + nouveau tests sécurité + Build EXE + smoke manuel

---

## PHASE 4 — Visual regression réel (avant phases UI)

**Recherche** : Playwright Python visual regression best practices 2026, vérifier baselines existantes
**Plan** :
1. Décider stratégie : Playwright natif `expect(page).to_have_screenshot()` vs pixelmatch
2. Générer baselines initiales (4 themes × 3 viewports × 7 vues = 84)
3. Modifier `tests/e2e/test_09_visual_regression.py` pour comparer vraiment
4. CI workflow dédié `visual-regression` bloquant sur PR
5. Documenter dans CONTRIBUTING.md la procédure baseline update

### Validation
- Test détecte une régression intentionnelle (mutation manuelle)
- Test passe sur code actuel

---

## PHASE 2 — Performance hot paths

### 2.0 — Mise en place benchmark reproductible
**Plan** : créer `bench/scan_5k_synthetic/` (5000 dossiers fictifs), `scripts/bench_scan.py`, capturer baseline AVANT optim (3 runs, médiane)

### 2.1 — PERF-1 : `get_tools_status` cache (gain ~500s/scan)
**Fichier** : `cinesort/infra/probe/service.py:145-150`
**Plan** : cache au niveau ProbeService, invalidation sur change path settings

### 2.2 — PERF-2 : `Path.resolve()` cache (gain 50-150s NAS)
**Fichier** : `plan_support.py:827-831` + `:548-550`
**Plan** : précomputer `cfg_root_resolved` une fois dans plan_library

### 2.3 — PERF-3 : `_nfo_signature` cache (gain ~200s)
**Plan** : refactor avec param `cache: dict` mémoïsant `(path, size, mtime_ns)`

### 2.4 — PERF-4 : `get_settings` cache + DPAPI (gain ~75s/batch perceptual)
**Plan** : cache `_settings_cache` avec invalidation mtime, `save_settings` reset cache

### 2.5 — PERF-5 : `apply_single` sans `find_main_video_in_folder` + `sha1_quick` (gain 100-250s NAS)
**DECISION REQUISE** : compromis perf vs sécurité atomicité — discuter avec utilisateur

### 2.6 — PERF-6 : TMDb cache drop `indent=2`
**Plan** : compact JSON, gain 50% taille file + 30% CPU

### Validation Phase 2
- Bench scan 5k : comparer avant/après
- Document `bench/results/comparison_phase2.md`

---

## PHASE 3 — Tests sécurité-critiques

### 3.1 — `move_journal.py` + `move_reconciliation.py` (372L combinés, 0 test direct)
**Plan** :
- `test_move_journal.py` : journaled_move success/exception, RecordOpWithJournal, atomic_move fallback
- `test_move_reconciliation.py` : 4 verdicts (completed/rolled_back/duplicated/lost), reconcile_at_boot idempotent

### 3.2 — `composite_score.py` V1 défaut (334L, 0 import direct dans tests)
**Plan** : tester `compute_visual_score`, `compute_audio_score`, `compute_global_score`, `detect_cross_verdicts` avec inputs synthétiques connus

### 3.3 — `local_secret_store.py` DPAPI (146L, 0 test)
**Plan** : tests Windows-only skipped sinon. Round-trip protect/unprotect avec entropy_purpose, edge cases (empty, unicode)

### Validation Phase 3
- Coverage nouveaux modules ≥ 90%

---

## PHASE 5 — Quality quick wins

1. Supprimer 19 `# noqa: BLE001` morts (Ruff RUF100 auto-fix)
2. Classifier les 41 `except Exception` restants (boundary légitime / typer / bug)
3. Décorateur `@boundary` jamais utilisé → supprimer ou appliquer
4. Args inutilisés (Ruff ARG001, 36 cas) → auto-fix
5. Variables loop inutilisées (Ruff B007) → auto-fix
6. `try/except/pass` → `contextlib.suppress` (14 cas)
7. `var` → `const`/`let` dans `web/core/format.js`
8. 22 `console.log` en prod → inventory + decide
9. `document.execCommand("copy")` → `navigator.clipboard.writeText()`
10. Commentaires "audit historique" pollution (`# V1-XX`, `# BUG N :`, `# Vague N`)

---

## PHASE 6 — Cohérence

### 6.1 — Unifier tiers (Premium/Bon/... ↔ Platinum/Gold/...)
**Plan** : créer `cinesort/domain/tiers.py`, migration DB 022 `UPDATE quality_reports SET tier = ...`, supprimer dual fallbacks

### 6.2 — Unifier `video_exts` (5 sets différents)
**Plan** : une constante `VIDEO_EXTS_ALL` dans `core.py`

### 6.3 — Unifier audio mappings langue
**Plan** : étendre `_LANG_MAP` dans `subtitle_helpers.py`

### 6.4 — Unifier `_OBSOLETE_CODECS`
**Plan** : déplacer dans `encode_analysis.py`, importer ailleurs

### 6.5 — Créer `cinesort/domain/codec_taxonomy.py`
**Plan** : `audio_codec_rank()`, `video_codec_rank()`, familles codec — source unique

---

## PHASE 7 — Dead code cleanup

### 7.1 — Vérifier puis supprimer legacy frontend
**ATTENTION** : DEMANDE CONFIRMATION utilisateur explicite avant action
**Recherche EXHAUSTIVE** :
- `grep -rn "web/index.html" .`
- Lancer EXE en mode dev, tester `--ui preview`
- Vérifier `package_zip.py`
**Plan** (si confirmé dead) :
1. Déplacer dans `archive/legacy_frontend_v4_v5/` (pas supprimer)
2. Modifier `CineSort.spec` exclusions
3. Mesurer bundle reduction

### 7.2 — 14 endpoints API jamais appelés
**Plan** : double-check grep, déprécier ou supprimer

### 7.3 — 19 tests skip "V5C-03 deferred"
**Plan** : porter vers processing.js OU supprimer définitivement

### 7.4 — Fichiers `.md` opération en racine
**Plan** : déplacer dans `docs/internal/operations/v7_7_0/`

---

## PHASE 8 — Refactor reuse backend

### 8.1 — `BaseRestClient` + 3 clients
**Plan** : créer `cinesort/infra/_http_utils.py` avec `BaseRestClient` (Session, rate limiter, _get/_post/_delete, _normalize_url, clamp_timeout). Refactor Jellyfin/Plex/Radarr.

### 8.2 — `_decode_row_json` utilisé partout (8 sites)
### 8.3 — Helper `_canonical_json()` dans `_StoreBase` (16 occurrences)
### 8.4 — Helper `_load_run_or_error()` (18 sites boilerplate)
### 8.5 — Response factory `error_response()`/`success_response()` (212 sites)
### 8.6 — `_runner_platform_kwargs` unifié dans `subprocess_safety.py`
### 8.7 — `strip_accents` unifié dans `text_normalization.py`
### 8.8 — `_FakeResponse` dans `tests/_fixtures.py`
### 8.9 — `conftest.py` racine

---

## PHASE 9 — Frontend dedup

### 9.1 — Composants partagés `web/shared/components/`
**Plan** : pour chaque des 22 composants dupliqués :
- Déplacer vers `web/shared/components/<name>.js` au format ESM
- Wrapper `web/components/<name>.js` IIFE expose sur `window`
- Mettre à jour dashboard pour importer depuis `web/shared/`
- Tester visual regression après migration

### 9.2 — Tokens CSS uniques `web/shared/tokens.css`
**Plan** : vérifier imports, supprimer copies legacy

---

## PHASE 11 — API REST HTTP codes

**Plan** :
- 400 validation errors
- 404 not found
- 409 conflict
- 429 quota
- 401/403 auth
- 500 exceptions
**Refactor via helpers Phase 8.5**

---

## PHASE 13 — Tests manquants

13.1 — Cancel pendant apply (pas seulement scan)
13.2 — Upgrade DB v1 → v21
13.3 — Smoke test PyInstaller (`dist/CineSort.exe` démarre)
13.4 — Upgrade settings.json ancien
13.5 — Property-based tests (hypothesis)
13.6 — Tests d'idempotence apply

---

## PHASE 15 — Settings dataclass

**Plan** : créer `SettingsSchema` dataclass, remplacer `apply_settings_defaults` (180L de setdefault), validation centralisée, docs auto-générées

---

## PHASE 12 — Refactor fonctions > 150L

**Cibles** (12 fonctions) :
- `_execute_perceptual_analysis` (309L)
- `apply_rows` (271L)
- `_build_dashboard_section` (241L)
- `_execute_apply` (227L)
- `_execute_undo_ops` (207L)
- `_plan_item` (182L)
- `compute_quality_score` (181L)
- `apply_settings_defaults` (180L)
- `_score_video` (178L)
- `generate_suggestions` (178L)
- `analyze_audio_perceptual` (169L)
- `get_quality_report` (162L)

**Pattern par fonction** : tests de caractérisation → extract method → validation → cible <80L sous-fns, <100L orchestrateur

---

## PHASE 16 — Tests migrations DB systématiques

**Plan** : pour chaque migration 001-021, créer `test_migration_NNN.py` (modèle de `test_migration_021.py` avec 4 classes : Fresh, Cascade, Existing, Idempotence)

---

## PHASE 10 — Cycle domain↔app (GROS CHANTIER)

**Recherche** : Python break circular import dependency injection refactor patterns
**Plan** :
1. Recenser re-exports `domain/core.py` → `app/`
2. Migrer call sites externes
3. Supprimer re-exports
4. Remonter 161 imports lazy en tête de module
5. Supprimer hiddenimports manuels devenus inutiles
6. `pylint --enable=cyclic-import` retourne 0

---

## PHASE 14 — Ruff strict

**Activer progressivement** (1 règle = 1 commit + fixes) :
- `B` (bugbear)
- `BLE001` (blind except)
- `PLR2004` (magic values) — gros chantier
- `PLR0913` (too many args)
- `C901` (complexity > 10)
- `SIM` (simplify)
- `RUF` (Ruff-specific)
- `I` (isort)
- `S` (security)

---

## PHASE 17 — Packaging + dépendances

**Plan** :
- `pip-audit` pour CVE
- Mettre à jour majeures non breaking
- Mesurer bundle après cleanup
- Optimiser exclusions PyInstaller
- Vérifier signing executable

---

## PHASE 18 — Release v7.8.0

**Plan** :
- CHANGELOG.md complet
- Bumper VERSION
- Tag git
- Release notes utilisateur friendly
- CLAUDE.md final avec note réaliste (probable 8.5-9/10 post-cleanup)

---

## Stratégie Anti-Régression Globale

À chaque phase :
1. **Test baseline immuable** vérifié avant et après
2. **Suite complète** doit passer (0 régression imputable)
3. **Build EXE** + smoke test launch obligatoire
4. **Bench scan 5k** si phase touche hot path (2, 6, 10, 12)
5. **Visual regression** activée dès Phase 4 → bloque tout changement UI non intentionnel

---

## Recherches Web Prévues

| Phase | Recherche |
|-------|-----------|
| 1.1 | Best practices Python log filter pour secrets, 2026 |
| 1.2 | REST API expose API keys pattern |
| 2.0 | Python benchmarking pattern stable (pytest-benchmark) |
| 2.1 | Subprocess CreationFlags Windows headless cache |
| 2.2 | `pathlib.Path.resolve` performance SMB Windows |
| 2.4 | DPAPI performance / caching guidelines |
| 4   | Playwright Python visual regression baseline 2026 |
| 6   | SQLite migration patterns for data transformation |
| 8.1 | requests Session sharing thread-safety details |
| 9   | ES modules + IIFE coexistence patterns 2026 |
| 10  | Python break circular import dependency injection |
| 11  | REST API HTTP status codes for business errors |
| 13.5| hypothesis property-based testing Python |
| 14  | Ruff config strict production Python 2026 |
| 17  | pip-audit / safety CVE scanning workflow |

---

## Dashboard de Suivi

Créer `audit/TRACKING_v7_8_0.md` mis à jour à chaque phase avec :
- Statut (TODO / WIP / DONE)
- Branche
- Findings adressés
- Tests ajoutés
- Suite ok ?
- Bench si applicable
- Date completion
- Commit hash

---

**FIN DU PLAN**
