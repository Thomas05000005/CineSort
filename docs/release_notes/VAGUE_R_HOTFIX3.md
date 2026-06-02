# Hotfix3 - completion migration+naming (post-a141f75)

## Pour toi

Le commit `a141f75` (hotfix2 BUG-015 migration_manager) embarquait, en
plus du fix declare, un changement non documente du calcul de resolution
pour les renommages : les films cinema en 1920x800 (ratio 2.35:1) etaient
classes en `720p` sous l ancienne logique (height-only), ils sont
desormais classes en `1080p` sous la nouvelle logique (width-based,
alignee sur `quality_score._resolution_label`). C est le bon
comportement (1920px = 1080p natif peu importe l aspect ratio
cinema), mais il aurait du etre annonce. Cet hotfix3 complete
la traçabilite : tests unitaires de la nouvelle semantique, note
de backward compat, ajout optionnel de `sqlparse` en dev pour
activer la couverture complete du splitter SQL dans les tests.

## Aucun fichier deja renomme n est modifie

**Backward compat ABSOLUE**. Les fichiers que vous avez deja renommes
avec l ancienne logique (par ex. `Film (2020) [720p].mkv` pour un
1920x800) ne sont PAS renommes automatiquement par cet hotfix. Seuls
les nouveaux scans (ou un re-scan manuel via "Re-analyser cette
bibliotheque") appliqueront la nouvelle classification width-based.

Si vous tenez a re-aligner votre bibliotheque existante :
1. Lancer un re-scan complet sur la racine concernee
2. Verifier le preview avant Apply (les tags `[720p]` -> `[1080p]`
   apparaitront pour vos films cinema 2.35:1)
3. Apply : les vieux noms partent en historique undo, comme tout
   renommage

## Build

Pas de rebuild EXE necessaire (modification de tests + pyproject.toml
dev-extra + release notes uniquement, aucun changement de code prod).

## Changements par fichier

### `tests/test_naming_resolution_label.py` (nouveau)

Fige la semantique width-based de `_resolution_label` post-SCAN-1
(introduite silencieusement par `a141f75`). Couvre :

- `1920x800` -> `1080p` (cinema 2.35:1, regression cible)
- `1920x816` -> `1080p` (cinema 2.35:1 variante)
- `3840x1600` -> `2160p` (4K cinema 2.40:1 Mad Max / Dune)
- `1280x720`, `1280x540` -> `720p`
- Fallback height-only (width manquant) : `>=1000` -> `1080p`,
  `>=680` -> `720p`, `>=2100` -> `2160p`
- Edges : dict vide, dimensions nulles, valeurs negatives clampees,
  valeurs str (ffprobe peut renvoyer str) coercees via `int()`
- `576p` (DVD PAL) tombe dans le fallback custom `{height}p`

Empeche tout retour en arriere accidentel vers l ancien
comportement height-only.

### `pyproject.toml` (dev-extra)

Ajout `sqlparse>=0.5,<1` dans `[project.optional-dependencies].dev`.

Permet de couvrir le chemin complet du splitter SQL de
`migration_manager._split_sql_statements` dans les tests (literals
contenant `/*`, blocs imbriques) sans imposer la dependance en prod.
En prod l absence reste geree par le fallback regex + WARNING log
mis en place en hotfix2 (BUG-015). Aucun changement runtime.

### `docs/release_notes/VAGUE_R_HOTFIX3.md` (ce fichier)

Documentation explicite du changement de comportement SCAN-1 qui
manquait dans `VAGUE_R_HOTFIX2.md` : la modification de
`cinesort/domain/naming.py:_resolution_label` (width-based)
embarquee dans `a141f75` n etait pas decrite, seul le fix
migration_manager (BUG-015) etait documente.

## Pourquoi hotfix3 et pas amend de a141f75

Le commit `a141f75` est suivi de 7 commits hotfix2 et un commit
release notes, tous deja stables. Reecrire l historique
casserait les references croisees (VAGUE_R_HOTFIX2.md liste
`a141f75` par SHA). Un commit additionnel de completion preserve
le journal lineaire et la SHA historique.

## Commits inclus

- `<HOTFIX3_SHA>` fix(hotfix3): completion migration+naming (post-a141f75)

## Tag

Pas de tag dedie - completion de `vague-r-hotfix2`.
