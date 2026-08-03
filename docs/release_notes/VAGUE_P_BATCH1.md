# Vague P batch 1 - VP-A Fondations transactionnelles & migration 029 - apply_atomic forward rollback

## Resume technique

Premier batch de la Vague P (Apply atomique & verrous) : implementation du sub-lot
**VP-A** (item `VP-1-APPLY-ATOMIC`) introduisant un mode atomique opt-in pour la
phase Apply. Quand `apply_atomic=True`, toute exception levee pendant l'execution
du batch declenche un **forward rollback** : replay du journal `apply_operations`
en sens inverse (LIFO) pour restaurer l'etat FS d'origine, suivi d'un marquage
final en DB. Backward compat ABSOLUE preservee (default OFF, signature `apply()`
retourne toujours `{ok: bool, ...}`). Migration 029 dediee, table separee
`apply_batch_modes` pour ne pas impacter le mecanisme undo classique.

## Changements par item

### VP-A : apply atomic forward rollback (opt-in)

- **VP-A-1** (`e76a41c`) - `feat(VP-A-1)`: implementation complete du mode
  atomique opt-in.

  Backend :
  - Migration `029_apply_atomic_mode.sql` : table `apply_batch_modes`
    (`batch_id` PK, `atomic_enabled`, `rollback_status`, `rolled_back_at`) +
    2 index. Ordre CREATE TABLE -> CREATE INDEX strict, pas d'ALTER, IF NOT
    EXISTS partout (memo `feedback_sqlite_migration_test_existing_db`).
  - `ApplyRepository` : nouvelles methodes `upsert_atomic_mode`,
    `mark_rollback_status`, `get_atomic_mode`, `list_atomic_modes_for_run`.
  - `cinesort/app/apply_rollback.py` : nouveau module `rollback_forward(store,
    batch_id)` qui replay le journal `apply_operations` en sens inverse (LIFO)
    avec audit log. AC-3 : si le mark final DB echoue alors que le FS a deja
    ete reverte, on degrade en `ROLLBACK_PARTIAL` (etat coherent et observable).
  - Coordination undo classique : `rollback_status` separe de `undo_status` via
    une table dediee `apply_batch_modes`, donc
    `get_last_reversible_apply_batch` reste non impacte (open question VP-A #5
    tranchee).
  - Cablage : `apply_support.apply_changes` / `_apply_changes_body` /
    `_execute_apply` / `cinesort_api._apply_impl` / `run_facade.apply` (4 points
    + 1 helper). En cas d'exception dans `_execute_apply` ET
    `apply_atomic=True`, `rollback_forward` est declenche puis le payload
    d'erreur enrichi avec `atomic_rollback`.
  - `list_apply_history` annote chaque batch avec `atomic_mode` pour badge UI.

  UI (`web/dashboard/views/traitement.js`) :
  - Toggle `apply_atomic` dans la section Apply (etape 5).
  - `dangerConfirmModal` a l'activation (consequences sans countdown, memo
    `feedback_cinesort_actions_dangereuses` : ici non-destructif) - AC-4.
  - Indicateur "Mode atomique" dans le recap pre-apply (modal confirmation).
  - Propagation `apply_atomic` dans les 2 `apiPost("run/apply", ...)`.
  - `node --check` OK.

## Tests

- `tests/test_apply_atomic_mode_v77.py` : 14 tests (SQL order strict, fresh DB,
  fixture v28 existante reelle, idempotence, methodes `ApplyRepository`).
  AC-2 verifie.
- `tests/test_apply_atomic_rollback_integration_v77.py` : 14 tests (rollback
  MOVE_FILE, skip irreversible / dst missing / src exists, partial 5/10, ordre
  LIFO, DB failure -> degradation `ROLLBACK_PARTIAL`, coordination undo,
  signatures). AC-1/3 verifies.
- `tests/test_existing_db_fixture_v77.py` : +1 test migration v28 -> v29 reelle.
- 0 regression sur tests undo existants (`test_undo_*`, 24 passed) - AC-5.

Acceptance criteria :

- AC-1 default OFF, signature `{ok: bool}` preservee.
- AC-2 migration 029 idempotente, fixture v28 reelle testee.
- AC-3 rollback FS+DB atomique avec degradation `ROLLBACK_PARTIAL` si DB fail.
- AC-4 `dangerConfirmModal` sans countdown (memo non-destructif).
- AC-5 0 regression undo (`test_undo_apply` / 24h / checksum / phase6 OK).

## 🎁 Pour toi

Tu peux maintenant activer un mode "Apply atomique" dans l'etape 5 du
traitement. Quand il est ON, si quelque chose se passe mal pendant le
deplacement des fichiers (un fichier bloque, le disque qui se deconnecte, une
erreur reseau...), CineSort fait machine arriere et remet tout en place comme
avant de lancer l'operation. C'est une securite en plus : par defaut le mode
est OFF (rien ne change pour toi), tu l'allumes seulement quand tu veux la
ceinture et les bretelles. Si jamais la restauration sur les fichiers reussit
mais que la trace en base de donnees echoue, tu vois un statut
"ROLLBACK_PARTIAL" : les fichiers sont bien revenus a leur place, juste le
journal qui n'a pas pu se mettre a jour.

## Notes

- Pas de bump VERSION (decision differee, coherent avec les batches Vague N/O).
- Tag local uniquement : `vague-p-batch1` (pas de push remote).
- Commits inclus : `e76a41c`.
- Suite Vague P : sub-lots VP-B+ (verrous, mini-recovery) a venir.
