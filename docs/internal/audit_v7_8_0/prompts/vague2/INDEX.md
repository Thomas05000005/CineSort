# Index Vague 2 — 12 missions à lancer en parallèle

**Date** : 1er mai 2026 (après merge V1 réussi)
**Pré-requis** : Vague 1 mergée sur `audit_qa_v7_6_0_dev_20260428` ✅

---

## ⚠️ LIRE EN PREMIER

- `audit/prompts/_WORKTREE_SETUP.md` — procédure worktree (chaque instance crée son worktree)
- `audit/report.md` — contexte audit complet
- `audit/lot2_security_robustness_code.md` + `audit/lot4_perf_data_tests.md` — détails findings

---

## 📁 Comment utiliser

1. Ouvre **12 instances** Claude Code (1 par mission)
2. Dans chaque instance : **"Lis et exécute le fichier `audit/prompts/vague2/<NUM>-XXX.md`"**
3. Chaque instance crée son worktree (étape 0 obligatoire)
4. Quand toutes mergées → demande la Vague 3

---

## 🌊 12 missions Vague 2

| # | Fichier | Branche | Worktree | Effort |
|---|---|---|---|---|
| V2-01 | [01-REFACTOR-SAVE-SETTINGS-PAYLOAD.md](01-REFACTOR-SAVE-SETTINGS-PAYLOAD.md) | `refactor/save-settings-payload-split` | `refactor-save-settings-payload-split` | 2 jours |
| V2-02 | [02-REFACTOR-4-FONCTIONS-COMPLEXITE-E.md](02-REFACTOR-4-FONCTIONS-COMPLEXITE-E.md) | `refactor/cyclomatic-e-functions` | `refactor-cyclomatic-e-functions` | 2-3 jours |
| V2-03 | [03-DRAFT-AUTO-VALIDATION.md](03-DRAFT-AUTO-VALIDATION.md) | `feat/validation-auto-draft` | `feat-validation-auto-draft` | 1 jour |
| V2-04 | [04-PROMISE-ALLSETTLED.md](04-PROMISE-ALLSETTLED.md) | `refactor/promise-allsettled` | `refactor-promise-allsettled` | 1 jour |
| V2-05 | [05-TESTS-CINESORT-API.md](05-TESTS-CINESORT-API.md) | `test/cinesort-api-coverage` | `test-cinesort-api-coverage` | 2-3 jours |
| V2-06 | [06-TESTS-TMDB-SUPPORT.md](06-TESTS-TMDB-SUPPORT.md) | `test/tmdb-support-coverage` | `test-tmdb-support-coverage` | 1 jour |
| V2-07 | [07-EMPTY-STATE-COMPONENT.md](07-EMPTY-STATE-COMPONENT.md) | `feat/empty-state-component` | `feat-empty-state-component` | 1-2 jours |
| V2-08 | [08-SKELETON-STATES.md](08-SKELETON-STATES.md) | `feat/skeleton-states-everywhere` | `feat-skeleton-states-everywhere` | 1-2 jours |
| V2-09 | [09-MIGRATE-TMDB-CLIENT-RETRY.md](09-MIGRATE-TMDB-CLIENT-RETRY.md) | `feat/tmdb-client-retry-migration` | `feat-tmdb-client-retry-migration` | 2-3h |
| V2-10 | [10-MIGRATE-JELLYFIN-CLIENT-RETRY.md](10-MIGRATE-JELLYFIN-CLIENT-RETRY.md) | `feat/jellyfin-client-retry-migration` | `feat-jellyfin-client-retry-migration` | 2-3h |
| V2-11 | [11-MIGRATE-PLEX-CLIENT-RETRY.md](11-MIGRATE-PLEX-CLIENT-RETRY.md) | `feat/plex-client-retry-migration` | `feat-plex-client-retry-migration` | 2-3h |
| V2-12 | [12-MIGRATE-RADARR-CLIENT-RETRY.md](12-MIGRATE-RADARR-CLIENT-RETRY.md) | `feat/radarr-client-retry-migration` | `feat-radarr-client-retry-migration` | 2-3h |

**Estimation parallèle (12 instances)** : ~3 jours (la plus longue est V2-01 ou V2-02 ou V2-05)
**Estimation séquentielle** : ~12-15 jours

---

## ⚠ Coordinations à connaître

| Fichier touché par plusieurs missions | Missions | Risque |
|---|---|---|
| `web/dashboard/views/review.js` | V2-03 (draft) + V2-04 (allSettled) | Sections différentes — auto-merge OK |
| Vues dashboard (quality.js, jellyfin.js, etc.) | V2-04 + V2-07 + V2-08 | V2-04 modifie le `Promise.all`, V2-07 le markup empty state, V2-08 le skeleton — sections différentes |
| Tests existants des 4 clients HTTP | V2-09/10/11/12 | Chaque mission ne touche QUE son propre client — pas de collision |

---

## 🎯 Statut V2

```
V2-01  [ ] Refactor save_settings_payload (F=81 → C)
V2-02  [ ] Refactor 4 fonctions complexité E (≥30 → C)
V2-03  [ ] Draft auto validation (localStorage)
V2-04  [ ] Promise.all → Promise.allSettled (9 vues)
V2-05  [ ] Tests cinesort_api 52% → 75%
V2-06  [ ] Tests tmdb_support 14.7% → 80%
V2-07  [ ] Composant <EmptyState> + 4 vues
V2-08  [ ] Skeleton states 7 vues
V2-09  [ ] Migrate TmdbClient retry
V2-10  [ ] Migrate JellyfinClient retry
V2-11  [ ] Migrate PlexClient retry
V2-12  [ ] Migrate RadarrClient retry
```

---

## 🚀 Quand toutes les V2 sont mergées

Reviens vers l'orchestrateur avec : **"Vague 2 mergée, génère V3"**.

Vague 3 contiendra (~10 missions polish) :
- Mode débutant `expert_mode`
- Tooltips ⓘ glossaire métier
- Compteurs sidebar
- Drawer mobile inspector Validation
- Fix focus visible thème Studio
- Reset all data UI
- Tooltips raccourcis clavier
- 30 hardcodes couleurs → tokens CSS
- PRAGMA mmap_size optim perf
- Mode démo wizard
- Hook updater au boot + UI Settings updater
- Vue Aide : bouton "Ouvrir logs"
