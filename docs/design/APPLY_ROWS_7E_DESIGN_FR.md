CineSort 7E - Cadrage de refactorisation progressive de `apply_rows`
==================================================================

Objectif
--------
Documenter un plan de refactorisation interne de `core.apply_rows(...)` sans changer:
- l'API publique,
- la politique medias,
- la semantique de `dry_run`,
- la gestion prudente des conflits, doublons, leftovers, quarantaine et undo.

Ce lot est volontairement un lot de conception.
Il ne doit pas modifier le comportement de production.

Pourquoi ce cadrage existe
--------------------------
`apply_rows(...)` concentre aujourd'hui trop de responsabilites dans un seul bloc:
- preparation du contexte apply,
- creation des racines `_review`,
- migration legacy collection,
- pre-pass des dossiers collection,
- resolution des dossiers courants,
- dispatch `single` / `collection` / `quarantine`,
- comptage applique / ignore,
- gestion d'erreurs par ligne,
- cleanup final des dossiers vides.

Ce n'est pas encore un bug en soi, mais c'est une dette de structure:
- chaque correction future coute plus cher,
- le risque de regression augmente,
- le code est plus difficile a tester et a relire.

Perimetre exact du lot 7E
-------------------------
Dans ce lot:
- on analyse `apply_rows(...)`,
- on fixe les invariants a ne jamais casser,
- on propose un ordre d'extraction progressif,
- on liste les tests obligatoires avant tout refactor.

Hors scope:
- aucun changement de logique metier,
- aucune extraction brutale de `_apply_single(...)`,
- aucune extraction brutale de `_apply_collection_item(...)`,
- aucune reecriture de `apply_rows(...)` en une seule passe.

Invariants non negociables
--------------------------
1. Compatibilite comportementale
- `apply_rows(...)` garde la meme signature publique.
- `ApplyResult` doit continuer a etre renseigne avec les memes compteurs utiles.

2. Securite medias
- jamais d'overwrite silencieux,
- conflits vers `_review/_conflicts*`,
- doublons identiques vers `_review/_duplicates_identical`,
- leftovers vers `_review/_leftovers`,
- quarantaine prudente des cas non valides si demandee.

3. Undo / journal apply
- les hooks `record_op(...)` doivent continuer a etre appeles sur les vraies operations,
- `dry_run=True` ne doit pas produire un journal reel incoherent.

4. Dry-run
- un `dry_run` doit rester un plan d'action, pas une execution partielle masquee.
- les compteurs et logs doivent rester coherents avec le mode simulation.

5. Gestion collections
- le pre-pass dossiers collection doit rester effectue une seule fois par dossier,
- les mappings de dossier doivent rester stables pendant tout l'apply,
- la dedup sidecars deja en place ne doit pas regresser.

6. Isolation des erreurs
- une erreur sur une ligne ne doit pas faire tomber tout le run,
- le compteur `errors` et les `skip_reasons` doivent rester coherents.

Responsabilites actuelles de `apply_rows(...)`
----------------------------------------------
Lecture actuelle du flux:

1. Normaliser la config et initialiser le resultat
- `cfg = cfg.normalized()`
- creation de `ApplyResult`
- preparation `decision_keys`, `hash_cache`

2. Construire les racines de review/conflicts
- `review_root`
- `conflicts_root`
- `conflicts_sidecars_root`
- `duplicates_identical_root`
- `leftovers_root`

3. Creer les dossiers necessaires hors dry-run
- `mkdir(...)` conditionnels

4. Lancer la migration legacy collection
- `_migrate_legacy_collection_root(...)`

5. Construire le mapping de dossiers collection
- `folder_map`
- `dedup_seen_ops`
- premiere passe sur `rows` collection

6. Resoudre le dossier courant reel
- helper local `current_folder_path(...)`

7. Iterer les rows et dispatcher
- ligne validee -> `_apply_single(...)` ou `_apply_collection_item(...)`
- ligne non validee -> `_quarantine_row(...)` ou skip explicite

8. Determiner si la ligne a reellement applique quelque chose
- comparaison `pre_actions` / `post_actions`
- fallback `_mark_skip(...)`

9. Isoler les erreurs ligne par ligne
- `try/except`
- compteur `errors`
- `SKIP_REASON_ERREUR_PRECEDENTE`

10. Cleanup final
- `_move_empty_top_level_dirs(...)`

Decoupage cible recommande
--------------------------
Le but n'est pas de "faire joli", mais d'isoler des blocs lisibles et testables sans casser le flux.

Etape cible A - Contexte apply
------------------------------
Extraire un helper interne de preparation, par exemple:

- `_build_apply_context(...)`

Contenu cible:
- config normalisee,
- `ApplyResult`,
- `decision_keys`,
- `hash_cache`,
- racines `_review`,
- creation conditionnelle des dossiers,
- set `touched_top_level_dirs`,
- `dedup_seen_ops`.

Interet:
- reduire le bruit de debut de fonction,
- figer les preconditions de l'apply dans un seul objet/context.

Etape cible B - Pre-pass collection
-----------------------------------
Extraire un helper interne, par exemple:

- `_prepare_collection_folder_map(...)`

Contenu cible:
- migration legacy collection,
- premiere passe sur `rows`,
- calcul de `folder_map`,
- increments `collection_moves`,
- logs associes.

Interet:
- c'est un bloc conceptuellement distinct du vrai apply par ligne,
- faible risque si les tests collection restent verts.

Etape cible C - Resolution et dispatch ligne
--------------------------------------------
Extraire un helper interne, par exemple:

- `_apply_row_decision(...)`

Contenu cible:
- lecture `decisions[row_id]`,
- choix `single` / `collection` / `quarantine` / `skip`,
- isolation du `try/except` par ligne.

Interet:
- clarifie le coeur de la boucle,
- permet de tester plus finement les transitions de statut.

Etape cible D - Comptage applique / ignore
------------------------------------------
Extraire un helper, par exemple:

- `_update_apply_result_after_row(...)`

Contenu cible:
- `pre_actions` / `post_actions`,
- logique `applied_count`,
- fallback `_mark_skip(...)`,
- conservation des `skip_reasons`.

Interet:
- aujourd'hui cette logique est fragile car enfouie dans la boucle,
- c'est un bon candidat a test pur ou semi-pur.

Etape cible E - Cleanup final
-----------------------------
Extraire un helper, par exemple:

- `_finalize_apply_cleanup(...)`

Contenu cible:
- `_move_empty_top_level_dirs(...)`
- tout futur cleanup post-apply

Interet:
- sortie de fonction plus claire,
- preparation d'extensions futures sans allonger la boucle principale.

Ordre d'extraction recommande
-----------------------------
Ordre faible risque:

1. Extraire le contexte apply
- risque faible,
- pas de changement du coeur metier,
- forte reduction de bruit.

2. Extraire le pre-pass collection
- risque faible a moyen,
- structure deja naturellement separee.

3. Extraire le cleanup final
- risque faible,
- bloc tres local.

4. Extraire le dispatch ligne
- risque moyen,
- a faire uniquement apres les garde-fous.

5. Extraire le comptage applique/ignore
- risque moyen,
- a faire une fois les tests bien stabilises.

Ce qu'il ne faut pas faire
--------------------------
Ne pas:
- fusionner dans le meme lot extraction structurelle + changement de politique,
- reecrire `apply_rows(...)` completement en une fois,
- commencer par `_apply_single(...)` ou `_apply_collection_item(...)`,
- toucher `record_op(...)` sans test undo associe,
- changer les `skip_reasons` pendant le refactor structurel.

Matrice de non-regression obligatoire
-------------------------------------
Avant chaque sous-lot 7E codant un refactor:

1. Tests apply / merge / conflits
- `tests/test_merge_duplicates.py`

2. Tests flow backend
- `tests/test_backend_flow.py`

3. Tests undo
- `tests/test_undo_apply.py`

4. Tests scan/heuristiques utilises indirectement par apply
- `tests/test_core_heuristics.py`

5. Si le lot touche le bridge API
- `tests/test_api_bridge_lot3.py`

Cas concrets a verrouiller
--------------------------
Au minimum, conserver explicitement:

1. Single -> rename simple
2. Single -> merge dossier existant sans ecrasement
3. Collection -> move/merge avec sidecars
4. Doublon identique -> `_duplicates_identical`
5. Conflit sidecar -> keep-both / review conflict
6. Leftovers -> `_leftovers`
7. Quarantaine row non validee
8. Dry-run sans mutation destructive
9. Undo journal present sur apply reel seulement
10. Cleanup dossiers vides sans supprimer un dossier utile

Structure cible raisonnable
---------------------------
Sans renommer l'API publique, on peut viser:

- `apply_rows(...)`
  - `_build_apply_context(...)`
  - `_prepare_collection_folder_map(...)`
  - boucle:
    - `_resolve_row_runtime_folder(...)`
    - `_apply_row_decision(...)`
    - `_update_apply_result_after_row(...)`
  - `_finalize_apply_cleanup(...)`

Cette structure garde la meme orchestration tout en reduisant le volume cognitif.

Risque principal
----------------
Le risque n'est pas l'extraction elle-meme.
Le vrai risque est de casser un invariant discret:
- ordre des operations,
- comptage applique/ignore,
- journal undo,
- target folder reel en collection,
- difference entre `dry_run` et apply reel.

Strategie de rollout
--------------------
1. Un sous-lot = une extraction logique.
2. Tests obligatoires apres chaque sous-lot.
3. Pas de melange avec nouvelles features.
4. Si une extraction force trop de changements de tests, elle est trop grosse.

Verdict 7E
----------
Le refactor de `apply_rows(...)` est souhaitable, mais doit rester progressif.
Le meilleur prochain sous-lot code est:

1. `_build_apply_context(...)`
2. `_prepare_collection_folder_map(...)`
3. `_finalize_apply_cleanup(...)`

Le dispatch par ligne et le comptage doivent venir apres, pas avant.
