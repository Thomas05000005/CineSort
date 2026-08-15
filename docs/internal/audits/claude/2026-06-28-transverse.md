# Audit Claude - 2026-06-28 - Couche transverse

**Modele** : Opus 4.8 (thinking max)
**Niveau** : modere (fixes safe/petits uniquement) — PRs activees
**Scope** : les 5 verifications transverses + les 3 themes templated du prompt
**Contrainte run** : sandbox sans interpreteur Python ni `awk` — analyse par
`grep`/`git`/`gh` + lecture de fichiers. Comptages de taille de fonction = *spans*
`def`->`def` (surestiment le corps reel), a confirmer via `radon`.

## Resume executif

Les **3 themes templated** du prompt d'audit transverse sont tous **perimes ou deja
traites** — l'audit-bot quotidien a fortement fait progresser la dette depuis mai :

1. **« 49 fonctions >100L »** : faux, ~14 documentees dans **#215 (OPEN)**. MAIS
   re-mesure exhaustive ce run -> **~22 fonctions** (l'inventaire avait double en
   silence). Enrichissement poste sur #215. Cause racine : refactor « extraire
   `_body` » qui recree des helpers >100L non suivis.
2. **« 22 composants JS dupliques desktop/dashboard »** : **RESOLU** via **#217**
   (~20 000 lignes legacy supprimees, PRs #257/#258/#259). `web/views/` et
   `web/components/` n'existent plus ; frontend = `web/dashboard/` ESM unifie. Aucune
   action.
3. **« 161 imports lazy + cycle domain<->app »** : **RESOLU** via **#83** (cycle
   domain->app casse + import-linter en CI, 3 contracts KEPT). Regressions stdlib
   residuelles deja trackees (#554/#557, #595). Aucune nouvelle issue.

**Invariants architecturaux : tous verts.** Aucune regression `domain->app`,
`domain->ui/infra` (sauf 1 `TYPE_CHECKING` legitime), `infra->app/ui`, `app->ui`.
Mixins `_XxxMixin` deja supprimes ; Repository pattern en place (10 repos).

### Top findings

| # | Finding | Action |
|---|---------|--------|
| 1 | Inventaire #215 ~2x sous-estime : `apply_rows` ~594L, `_execute_apply` ~329L, `_apply_changes_body` ~292L, `_plan_item` ~246L + ~8 autres non listees | Commentaire CAS B sur **#215** |
| 2 | Aucun garde-fou CI sur la taille des fonctions -> derive silencieuse | Nouvelle issue **#677** |

## Par categorie (couvertes ce run)

- **Cat 10 (dette technique)** : 2 findings. Ex: inventaire fonctions >100L derive
  (#215) ; refactor `_body` recree des helpers geants.
- **Cat 16 (tests)** : 1 finding. Ex: absence de test budget-taille (#677).
- **Cat 47 (invariants archi)** : 0 finding (tous verts — verifie par grep
  inter-couches, cf detail).
- **Cat 11 (code mort)** : 0 nouveau (JS legacy deja supprime #217).

## Par module

### cinesort/ui/api/apply_support.py
- **severite med** — cat 10 — `apply_support.py:1260` `_execute_apply` (~329 span)
  NOUVEAU helper >100L non inventorie. Fix: tracer dans #215, decoupe en phases.
- **severite med** — cat 10 — `apply_support.py:2097` `_apply_changes_body` (~292)
  corps extrait de `apply_changes` mais reste >100L.
- **severite med** — cat 10 — `apply_support.py:2522` `_build_apply_preview_body` (~193).
- **severite low** — cat 10 — `apply_support.py:1157` `_validate_apply` (~103).
- `_execute_undo_ops` (338) ~260 (grossi vs 209) ; `undo_selected_rows` (724) ~167.

### cinesort/app/apply_core.py
- **severite med** — cat 10 — `apply_core.py:1329` `apply_rows` (~594 span, contient
  nested `current_folder_path` L1474). **N°1 transverse**, decoupe en
  `preflight/resolve/execute/journal`.
- `apply_single` (1923) ~194 ; `apply_collection_item` (2117) ~192 ;
  `apply_tv_episode` (2309) ~185 NOUVEAU ; `move_file_with_collision_policy` (629)
  ~189 ; `move_duplicate_losers_to_user_decided` (952) ~182 NOUVEAU ;
  `move_marked_for_deletion_to_bucket` (1134) ~152 NOUVEAU ; `merge_dir_safe` (818) ~107.

### cinesort/app/plan_support_core.py (issu du split de plan_support.py)
- `_filter_dossiers_phase` (795) ~161 ; `_resolve_path_cached` (381) ~154 ;
  `_classify_and_plan_folder` (643) ~131. Toutes NOUVELLES (post-split), bien nommees.

### cinesort/app/plan_support_replan.py
- `_plan_item` (512) ~246 (grossi vs 181).

### cinesort/app/plan_support_dedup.py
- `plan_multi_roots` (779) ~94 : **retombe sous le seuil** (etait 178). A sortir de #215.

### Frontend web/
- `web/views/` et `web/components/` supprimes (#217). `web/dashboard/views/` (21 vues
  ESM) + `web/shared/` (0 JS). Aucune duplication desktop/dashboard residuelle.

### Imports
- 0 import inter-couches interdit. `domain/core.py:69` importe `infra.tmdb_client`
  sous `TYPE_CHECKING` (legitime). 90 lazy `cinesort.*` restants, majoritairement
  `ui/api` (top-down — dette, pas violation de cycle). Lazy stdlib residuels couverts
  par #595 (perceptual_support) et #554/#557 (cinesort_api), ou justifies (`# noqa
  PLC0415`, commentaires).

## Statistiques

- Modules/zones audites : apply_support, apply_core, plan_support_*, composite_score_v2,
  domain/infra/app/ui (imports), web/ (frontend), infra/db (mixins/repos).
- Findings totaux : 14 (high 0, med 6, low 3, info 5). 0 BLOCKER.
- Issues creees : 1 (#677).
- Issues enrichies (CAS B) : 1 (#215).
- PRs ouvertes : 1 (ce rapport).
- Findings deja connus (dedup) : themes JS (#217), lazy (#83/#554/#595/#557),
  fonctions>100L (#215) — aucun re-cree.

## Self-critique

Findings supprimes avant action :
- **3 dedup** : les 3 themes templated etaient deja trackes/resolus -> 0 issue recreee
  (respect strict de la regle anti-#217).
- **2 deja mitiges** : `domain->app` (casse + CI-locke), mixins (deja supprimes).
- **1 idiomatique** : lazy imports `ui/api` top-down (dette toleree, pas violation).
- **1 sans plan multi-PR** : decoupe des ~22 fonctions >100L -> pas d'issue critique,
  enrichissement du plan existant #215 uniquement (refactors hors scope « modere »).

Aucune PR de fix code ouverte : niveau « modere » + impossibilite de valider
pre-commit (ruff/unittest indisponibles ce run) -> les decoupes >100L sont des
refactors multi-PR risques, laisses en plan sur #215. Seule PR : ce rapport (docs).

## Tendance vs audits precedents

- 2026-05-17 : 14 fonctions >100L inventoriees.
- 2026-06-14/21 : confirmations + drift line-numbers + split plan_support.
- **2026-06-28 : ~22 fonctions** (la masse a migre dans des helpers `_body` non
  suivis) -> garde-fou CI propose (#677) pour stopper la derive.
