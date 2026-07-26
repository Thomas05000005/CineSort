# Audit Claude - 2026-07-26 - Couche transverse

**Modèle** : Opus 4.8 (thinking max)
**Niveau** : modéré · **Ouverture PRs** : true
**Contrainte d'exécution** : dans ce run, l'exécution de `python`/`awk` n'était pas
autorisée (permissions restreintes). Toutes les mesures ci-dessous ont été obtenues
par `grep`/`git`/lecture de fichiers (heuristique écart-entre-`def`), pas par AST.
Les tailles de fonction sont donc des approximations (`≈`) ; un `radon cc`/AST
donnera les chiffres exacts. Aucune PR de code n'a été ouverte (impossible de faire
tourner `ruff`/`unittest` pour valider un pre-commit).

## Résumé exécutif

L'audit transverse a porté sur les 5 axes du prompt (fonctions >100L, doublons JS
desktop/dashboard, imports inter-couches, Repository pattern, module-style mocking)
+ les 3 livrables chiffrés (49 fonctions >100L, 22 composants JS, 161 lazy imports).

**3 des prémisses du prompt sont périmées** (le code a beaucoup évolué depuis
mai 2026) et **1 dette réelle a empiré** :

1. **[RÉEL — dette en hausse]** L'inventaire des fonctions >100L de #215
   (« 14 fonctions, en bonne voie ») est **périmé et sous-estimé**. Re-mesure du
   2026-07-26 : **≈20 fonctions >100L dans 3 fichiers seulement**
   (`apply_support.py`, `apply_core.py`, `plan_support_replan.py`), contre 14
   revendiquées pour tout le repo. De nouveaux géants sont apparus :
   `apply_rows` ≈600L, `_execute_apply` ≈352L, `_apply_changes_body` ≈292L,
   `_plan_item` ≈247L. → **enrichissement de #215** (re-baseline).
2. **[PÉRIMÉ]** « 22 composants JS dupliqués desktop/dashboard » : `web/views/` a
   été supprimé par PR #92 (migration vers `web/dashboard/views/`). Il n'existe
   plus qu'**un seul frontend** (`web/dashboard/` + `web/shared/`). Déjà documenté
   au rapport transverse du 2026-05-24. **Aucune issue créée.**
3. **[À JOUR]** « 161 lazy imports + cycle domain↔app » : le cycle `domain→app`
   est **brisé et verrouillé** (import-linter) ; **0** import `domain→app`. Le vrai
   reliquat (≈90 lazy imports intra-`ui/api`) est déjà couvert par #779 (2026-07-19).
   → **enrichissement léger de #779** (petite dérive couche `app` : 13 → ≈20).
4. **[OK]** Invariants architecture : **0 violation inter-couche**, mixins SQLite
   entièrement supprimés (#85 CLOSED, plus aucune classe `_XxxMixin`), pattern
   module-style intact. RAS.

**Décision dedup (ETAPE 4)** : les 2 sujets réels correspondent à des issues
ouvertes récentes (#215, #779). Conformément à la règle CRITIQUE anti-doublon
(incident #91→#217), **aucune issue n'est recréée** : #215 et #779 sont enrichies
(CAS B). Le sujet JS est résolu (#92), pas d'issue.

## Par axe du prompt transverse

### 1) Fonctions > 100L par ROI de refactor — #215 PÉRIMÉ, dette en hausse

`plan_support.py` (2100+L en mai) a été scindé en `plan_support_replan.py`,
`plan_support_dedup.py`, … → **toutes les lignes de #215 sont invalides**.
Les fonctions listées existent encore mais ont bougé et souvent **grossi**.

Re-mesure (écart-entre-`def`, `≈`) — sous-ensemble vérifié sur les 3 fichiers chauds :

| ≈LOC | Fichier:Ligne | Symbole | Couche | Tier ROI |
|----:|---------------|---------|--------|:--------:|
| 600 | `cinesort/app/apply_core.py:1469` | `apply_rows` | app | T2 (risqué, hot-path) |
| 352 | `cinesort/ui/api/apply_support.py:1411` | `_execute_apply` | ui/api | **T1** |
| 292 | `cinesort/ui/api/apply_support.py:2299` | `_apply_changes_body` | ui/api | **T1** |
| 260 | `cinesort/ui/api/apply_support.py:338` | `_execute_undo_ops` | ui/api | **T1** |
| 247 | `cinesort/app/plan_support_replan.py:543` | `_plan_item` | app | T2 |
| 210 | `cinesort/app/apply_core.py:1033` | `move_duplicate_losers_to_user_decided` | app | **T1** |
| 206 | `cinesort/app/apply_core.py:2069` | `apply_single` | app | T2 |
| 193 | `cinesort/ui/api/apply_support.py:2724` | `_build_apply_preview_body` | ui/api | **T1** |
| 192 | `cinesort/app/apply_core.py:2275` | `apply_collection_item` | app | T2 |
| 189 | `cinesort/app/apply_core.py:629` | `move_file_with_collision_policy` | app | T2 (Strategy) |
| 186 | `cinesort/ui/api/apply_support.py:1872` | `_summarize_apply` | ui/api | **T1** |
| 185 | `cinesort/app/apply_core.py:2467` | `apply_tv_episode` | app | T2 |
| 183 | `cinesort/app/apply_core.py:1243` | `move_marked_for_deletion_to_bucket` | app | **T1** |
| 174 | `cinesort/ui/api/apply_support.py:835` | `undo_selected_rows` | ui/api | T1 |
| 128 | `cinesort/ui/api/apply_support.py:1283` | `_validate_apply` | ui/api | T1 |
| 128 | `cinesort/app/plan_support_replan.py:298` | `_build_resolved_row` | app | T1 |
| 124 | `cinesort/ui/api/apply_support.py:205` | `build_undo_preview_payload` | ui/api | T2 |
| 114 | `cinesort/ui/api/apply_support.py:1079` | `_execute_and_finalize_undo` | ui/api | T1 |
| 109 | `cinesort/ui/api/apply_support.py:1763` | `_cleanup_apply` | ui/api | T1 |
| 107 | `cinesort/app/apply_core.py:818` | `merge_dir_safe` | app | T2 |

**Constat clé** : le refactor « split en `_xxx_body` » (ex. `apply_changes`→48L qui
délègue à `_apply_changes_body`≈292L, `build_apply_preview`→75L qui délègue à
`_build_apply_preview_body`≈193L) a **déplacé la masse dans le helper sans la
découper** — la dette a été renommée, pas résorbée. `apply_rows` (≈600L, hot-path
central) est le plus gros point de complexité du repo.

**ROI** :
- **T1 (haut ROI, orchestration séquentielle, extraction triviale)** :
  `_execute_apply`, `_apply_changes_body`, `_execute_undo_ops`, `_summarize_apply`,
  `_build_apply_preview_body`, `move_duplicate_losers_to_user_decided`,
  `move_marked_for_deletion_to_bucket`. Étapes claires (validation → dry-run → exec
  → journal → résumé), extraction en helpers privés sans changement de valeurs.
- **T2 (ROI moyen, refactor délicat, hot-path)** : `apply_rows` (le plus gros gain
  mais le plus risqué → multi-PR obligatoire), `apply_single`, `apply_collection_item`,
  `_plan_item`, `move_file_with_collision_policy` (candidat pattern Strategy).

**Garde-fou** : issue #677 / PR #778 proposent un test CI anti-régression sur la
taille des fonctions. Vu la re-croissance constatée, ce garde-fou est **prioritaire**
(sinon la dette re-double en silence, comme entre mai et juillet). `radon cc -a -nb`
et `radon mi` pour les chiffres exacts.

### 2) Composants JS dupliqués desktop/dashboard — PRÉMISSE PÉRIMÉE

`find web -name '*.js'` : un seul arbre de vues, `web/dashboard/`
(+ `web/shared/`). **Aucun `web/views/`, `web/ui/`, ni `web/components/`** au niveau
racine. `web/views/` a été supprimé par PR #92 (migration → `web/dashboard/views/`),
ce qui a clôturé indirectement #217. Confirmé par le rapport transverse du
2026-05-24 (« Doublons JS components : 22 → 0 »). **Rien à mutualiser côté
desktop/dashboard** : il n'y a plus de dualité. (Une dette de duplication
*intra*-dashboard reste possible mais est hors périmètre de la prémisse et n'a pas
été relevée comme bloquante ici.)

### 3) Imports inter-couches interdits — 0 VIOLATION

`.importlinter` définit 3 contrats : `domain_pure`, `infra_bounded`, `app_bounded`.
- `domain → app` : **0** (seuls 2 hits grep sont un commentaire `# Cf #83` et une
  docstring — pas des imports).
- `domain → infra` : 1 sous `if TYPE_CHECKING:` (`core.py:55`, whitelisté dans
  `ignore_imports`) + 1 en docstring (`_runners.py:84`). Pas de dépendance runtime.
- `infra → app/ui` : 0. `app → ui` : 0.

Note mineure (doc) : le CONTEXTE du prompt cite les contrats `infra_no_upstream` /
`app_no_ui` ; les vrais noms sont `infra_bounded` / `app_bounded`. Sans impact.

### 4) Repository pattern — MIXINS SUPPRIMÉS (#85 CLOSED)

`SQLiteStore` compose désormais 10 repositories (`self.probe`, `self.scan`,
`self.quality`, `self.run`, `self.apply`, `self.perceptual`, `self.anomaly`,
`self.film_modal`, `self.field_locks`, `self.decisions`). **Aucune classe
`_XxxMixin`** ne subsiste (`grep -rn 'class _[A-Za-z]*Mixin' cinesort/` → 0) et
aucun appel legacy `store.probe_xxx` résiduel. La phase B8 de #85 est terminée
(#85 CLOSED). La prémisse « mixins coexistent » du prompt est périmée.

### 5) Module-style imports pour modules mockés — INTACT

74 cibles distinctes `patch("cinesort.…")` dans `tests/`. Échantillon : elles
patchent le symbole dans son module de définition (ex.
`patch("cinesort.app.watchlist.parse_imdb_csv")`), pattern compatible module-style.
Les 4277 tests passent (CONTEXTE) → aucune régression de patch détectée ; toute
rupture apparaîtrait en CI rouge.

## Par catégorie (46)

- **Cat 10 (dette technique)** : 1 finding réel enrichissant #215 (fonctions >100L,
  dette en hausse). Exemples : `apply_rows`≈600L, `_execute_apply`≈352L.
- **Cat 47 (invariants architecture)** : 0 violation. Exemples vérifiés : cycle
  `domain→app`=0 ; contrats import-linter présents et respectés.
- **Cat 10 (lazy imports)** : enrichissement #779 (ui/api≈90, app 13→≈20).
- **Cat 20 (parity desktop/dashboard)** : prémisse périmée (frontend unique).
- Autres catégories : non ré-auditées ce run (périmètre transverse ciblé).

## Statistiques

- Modules audités (axes transverses) : 5 axes + 3 fichiers chauds ré-mesurés
- Findings retenus (confiance ≥0.70) : 2 réels (fonctions>100L, dérive lazy `app`)
- Prémisses périmées documentées : 3 (JS dup, cycle domain→app, mixins)
- Issues créées : **0** (dedup — #215 et #779 enrichies)
- Issues enrichies (CAS B) : **2** (#215, #779)
- PRs de code : **0** (niveau modéré + `ruff`/`unittest` non exécutables ce run)
- PR docs : 1 (ce rapport + JSONL)
- Findings déjà connus (dedup) : #215, #779, #92 (JS), #85 (mixins), #677/#778 (garde-fou)

## Self-critique (ETAPE 2.6)

Findings supprimés : **5**.
- 3 prémisses « imaginées par le prompt » écartées après vérification code réel
  (JS dup, cycle domain→app, mixins) — FILTRE 1 + FILTRE 7 (mitigation déjà en place).
- 1 finding « contrats renommés » dégradé en note mineure (FILTRE 5 sévérité).
- 1 doublon potentiel « nouvelle issue fonctions>100L » supprimé au profit de
  l'enrichissement de #215 (FILTRE 4 dedup + règle CRITIQUE anti-recréation).
