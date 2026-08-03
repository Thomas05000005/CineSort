# Vague P batch 5 - VP-E Refactor plan_support.py decoupe haute LOC (canonical SUPPRIME apres fix #1)

## Resume technique

Cinquieme batch de la Vague P : sub-lot **VP-E** (`VP-E-6` /
`VP-6-PLAN-SUPPORT-DECOUPE`) **refactor pur** sans changement
fonctionnel. Decoupe du monolithe `cinesort/app/plan_support.py`
(**2715 LOC** historiques) en **3 sous-modules thematiques** + une
**facade re-export** pour preserver une **backward compat ABSOLUE** des
imports legacy (UI api, `run_flow_support`, 12 tests `import
cinesort.app.plan_support as plan_support`, patching attribute-level
`plan_support.plan_library = mock`). Aucune fonction renommee
"canonical" introduite : la branche canonical a ete **SUPPRIMEE apres
fix #1** (AC-5), pour eviter une seconde surface d'API a maintenir.
Tests source-inspection (`test_tmdb_scoring_strict`) mis a jour pour
pointer sur les sous-modules cibles au lieu du facade.

## Changements par item

### VP-E : decoupe plan_support.py en sous-modules thematiques

- **VP-E-6** (`207e219`) - `refactor(VP-E-6)` : decoupe `plan_support`
  en 3 sous-modules + facade re-export. **Refactor pur, zero
  changement fonctionnel.**

  **Sous-modules crees** :
  - `cinesort/app/plan_support_core.py` (**999 LOC**) : orchestrateur
    `plan_library` + 3 phases privees + `_PlanLibraryContext` + helpers
    de (de)serialisation et signatures.
  - `cinesort/app/plan_support_replan.py` (**925 LOC**) : pipeline
    single-row `_plan_item` + variantes (`_plan_single`,
    `_plan_collection_item`, `replan_single_row`, `_plan_tv_episode`)
    + row builders + enrichments + cache lookup/store.
  - `cinesort/app/plan_support_dedup.py` (**769 LOC**) : scoring
    NFO/IMDb/TMDb des candidats, runtime HARD filter, multi-roots
    (`plan_multi_roots`), detection des doublons
    (`find_duplicate_targets`, `_detect_cross_root_duplicates`).

  **Facade** :
  - `cinesort/app/plan_support.py` reduit de **2715 -> 133 LOC**
    (~95% de reduction). Re-exporte **100% des symboles publics
    historiques** (`plan_library`, `replan_single_row`,
    `plan_multi_roots`, `find_duplicate_targets`, ...) + les helpers
    prives effectivement utilises par les call-sites
    (`_PlanLibraryContext`, `_apply_runtime_hard_filter_to_tmdb_cands`,
    etc).
  - Logger module-level `_log` conserve sous le nom
    `cinesort.app.plan_support` (preserve les filtres de log
    existants).

  **Patterns historiques preserves** :
  - `from cinesort.app.plan_support import X` (UI api,
    `run_flow_support`, tests).
  - `import cinesort.app.plan_support as plan_support` (12 tests
    legacy).
  - Patching attribute-level `plan_support.plan_library = mock`
    (`test_api_bridge_lot3`).

  **Decision architecture (fix #1)** :
  - Aucune fonction renommee "canonical" introduite. La branche
    canonical (qui aurait double l'API publique avec des noms
    `*_canonical`) a ete **SUPPRIMEE** pour eviter une seconde
    surface d'API a maintenir + de la confusion call-sites (AC-5).

## Tests

- `tests/test_plan_support_modules.py` (smoke fixture) : valide
  `plan_library` + `replan_single_row` + `plan_multi_roots` cross-root
  dedup directement contre les sous-modules.
- `tests/test_plan_support_facade_reexports.py` (**8 tests**) :
  verifie que le facade re-exporte bien tous les symboles publics +
  les helpers prives consommes par les call-sites
  (`_PlanLibraryContext`, `_apply_runtime_hard_filter_to_tmdb_cands`,
  `replan_single_row`, ...).
- `tests/test_tmdb_scoring_strict.py` (source-inspection) : pointe
  desormais sur `plan_support_dedup.py` (IMDb lookup) et
  `plan_support_replan.py` (collection token check) au lieu du facade.
- **Total : 263 tests passes, 1 echec pre-existant non-lie au
  refactor** (AC-2 zero regression).

Acceptance criteria (5/5) :

- AC-1 OK : `plan_support_core.py` **< 1000 LOC** (999). `replan` et
  `dedup` au-dessus des cibles optimistes (700/600) mais inevitable
  etant donne la masse de code reelle (2266 LOC effectives, budget
  agrege etait 2300).
- AC-2 OK : **0 regression** sur les tests deja verts (263 passes, 1
  echec pre-existant non-lie).
- AC-3 OK : `import-linter` inchange (1 contrat broken **pre-existant**
  non lie a ce refactor).
- AC-4 OK : facade re-export complet + tests dedies
  (`test_plan_support_facade_reexports.py`, 8 passes) qui verifient
  tous les helpers prives utilises par les call-sites.
- AC-5 OK : **aucune fonction renommee "canonical" introduite** (fix
  #1 applique, branche canonical **SUPPRIMEE**).

## 🎁 Pour toi

Ce batch est invisible cote utilisateur : **rien ne change** dans ce
que tu vois ou cliques. C'est du **nettoyage interne** pur, mais qui
prepare la suite.

Avant : un seul gros fichier `plan_support.py` de **2715 lignes**
contenait absolument tout ce qui sert a planifier le rangement de ta
biblio (l'orchestration des phases, le scoring des metadonnees, la
detection des doublons, le replan d'un film individuel). Quand on
voulait ajouter une fonctionnalite a une seule de ces 4 logiques, il
fallait fouiller le monolithe entier en risquant de casser les 3
autres.

Maintenant : ce gros fichier est decoupe en **3 modules specialises**
(orchestrateur / replan single-row / scoring & doublons) + une petite
facade de **133 lignes** qui garde **exactement les memes points
d'entree** que avant. Resultat concret pour toi :

- **Aucune regression** : tous les tests deja verts restent verts (263
  passes), donc le rangement de tes films se comporte **strictement
  comme avant**.
- **Demarrage et planification identiques** : le scan et le plan vont
  exactement aussi vite (refactor pur, pas de code execute en plus ni
  en moins).
- **Futur plus rapide** : les prochaines features (suite Vague P) vont
  pouvoir cibler le bon sous-module sans risquer d'effets de bord sur
  les 3 autres. Concretement : moins de bugs collateraux, des
  iterations plus serieuses.

Petit detail honnete : on avait envisage de creer une **seconde
surface d'API** avec des fonctions `*_canonical` (pour signaler le
"vrai" point d'entree). Cette idee a ete **abandonnee et supprimee**
(fix #1) : ca aurait double les chemins d'import et cree de la
confusion pour rien. On garde **un seul nom par fonction**, celui que
le code existant utilisait deja.

## Notes

- Pas de bump VERSION (decision differee, coherent avec les batches
  Vague N/O/P-1/P-2/P-3/P-4).
- Tag local uniquement : `vague-p-batch5` (pas de push remote).
- Commits inclus : `207e219`.
- **Refactor pur** : zero changement fonctionnel, zero migration SQL,
  zero modification de l'UI. Seul le decoupage interne des modules
  change.
- **Backward compat ABSOLUE** : tous les patterns d'import historiques
  preserves (`from cinesort.app.plan_support import X`,
  `import cinesort.app.plan_support as plan_support`, patching
  attribute-level). Le logger `cinesort.app.plan_support` est
  conserve sous le meme nom.
- **Fix #1 applique** : branche canonical **SUPPRIMEE**, aucune
  fonction renommee `*_canonical`.
- Suite Vague P : sub-lots VP-F+ a venir.
