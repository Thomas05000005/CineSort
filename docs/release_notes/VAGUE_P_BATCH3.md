# Vague P batch 3 - VP-C Field locks Jellyfin-style & merge_metadata (migration 030)

## Resume technique

Troisieme batch de la Vague P : implementation du sub-lot **VP-C**
(`VP-C-FIELD-LOCKING`) introduisant des **verrous champ-par-champ persistents**
inspires du pattern **Jellyfin `LockedFields`** (lecon bug Jellyfin #15549).
Objectif : qu'un champ verrouille par l'utilisateur (titre, annee, plot,
poster, etc.) **resiste aux rescans OMDb/TMDb et au refresh automatique**, y
compris en mode "Tout reconstruire". Migration **030** stricte
`CREATE TABLE -> CREATE INDEX` (memo `feedback_sqlite_migration_test_existing_db`
respecte) testee sur fixture v29 reelle. Barriere `merge_metadata` pure (zero
IO), insensible a la casse, avec deux modes : `replace_data=False` (completer
les manques) et `True` (tout reconstruire, locks toujours preserves).
Transition d'identite `path:<sha1>` -> `tmdb:<id>` migre **TOUS** les locks
existants (fix #5).

## Changements par item

### VP-C : field locks Jellyfin-style + merge_metadata

- **VP-C-FIELD-LOCKING** (`defe745`) - `feat(VP-C-FIELD-LOCKING)`:
  implementation complete des verrous champ-par-champ persistents.

  Backend SQL (`cinesort/infra/db/migrations/030_field_locks.sql`) :
  - `CREATE TABLE film_field_locks (id PK, film_id TEXT, run_id TEXT,
    row_id TEXT, field_name TEXT, locked_value TEXT, locked_at,
    source TEXT, UNIQUE(film_id, field_name))`.
  - 3 `CREATE INDEX IF NOT EXISTS` : `idx_film` (film_id), `idx_field`
    (field_name), `idx_film_id` (film_id seul, pour fix #5).
  - Ordre strict `CREATE TABLE -> CREATE INDEX`, **AUCUN ALTER** (memo
    `feedback_sqlite_migration_test_existing_db`).

  Backend domain (`cinesort/domain/film_identity.py`) :
  - `compute_film_id(row)` -> `"tmdb:<id>"` si TMDb id connu, sinon
    `"path:<sha1(folder+video)>"`. Module **domain pur** (stdlib only,
    aucune dependance app/infra).

  Backend infra (`cinesort/infra/db/repositories/field_locks.py`) :
  - `FieldLocksRepository` : `set_lock`, `clear_lock`, `get_lock`,
    `is_locked`, `list_locks`.
  - `migrate_locks(old_id, new_id)` : transition `path:` -> `tmdb:` (fix #5).
  - Registre `SQLiteStore.field_locks` + `schema_group`.

  Backend app (`cinesort/app/merge_metadata.py`) :
  - Barriere `MergeData` Jellyfin-style **pure** (zero IO).
  - `replace_data=False` = "completer les manques" (override sources non
    verrouillees uniquement).
  - `replace_data=True` = "tout reconstruire" (locks toujours preserves).
  - **Insensible a la casse** sur `locked_fields`.

  Backend integration (`cinesort/ui/api/library_actions_support.py`) :
  - `_rematch_tmdb_and_update_plan` :
    1. `compute_film_id` ancien + nouveau
    2. `migrate_locks` si transition `path:` -> `tmdb:`
    3. `merge_metadata` pour preserver les champs verrouilles.

  UI (`web/dashboard/views/library/lib-validation.js`) :
  - `dangerConfirmModal` mode "Tout reconstruire" avec **countdown 3s si
    > 50 items** (memo `feedback_cinesort_actions_dangereuses` respecte).
  - Helpers exportes : `confirmRebuildAll`, `setFieldLock`, `loadFieldLocks`,
    `fieldLockToggleHtml`.
  - `node --check lib-validation.js` OK.

## Tests

- `tests/test_field_locks_persistence.py` (12 tests) : lock survit
  close/reopen (lecon Jellyfin #15549), AC-1 migration 030 sur fixture v29
  reelle, idempotence.
- `tests/test_merge_metadata_resistance_rescan.py` (7 tests) : barriere
  preserve les locks en modes `fill` et `replace`, scenarios OMDb/TMDb
  refresh.
- `tests/test_field_locks_migration_path_to_tmdb.py` (12 tests) : fix #5
  `migrate_locks` + `compute_film_id` (path/tmdb forms, idempotence).
- `tests/test_existing_db_fixture_v77.py` (8 tests etendus) : cas v29 -> v30
  + coexistence `film_tmdb_overrides` + `apply_batch_modes` (AC-4 zero
  regression).
- **Total : 39 tests verts** (migration_chain OK, library_support OK).

Acceptance criteria (5/5) :

- AC-1 OK : migration 030 testee sur fixture v29 reelle
  (`existing_db_fixture`).
- AC-2 OK : champ verrouille resiste a `merge_metadata` en mode
  `replace_data=True` (tout reconstruire).
- AC-3 OK : transition `path:` -> `tmdb:` migre **TOUS** les locks
  (`migrate_locks`).
- AC-4 OK : `film_tmdb_overrides` (migration 023) coexiste sans regression.
- AC-5 OK : `dangerConfirmModal` countdown 3s si > 50 items.

## 🎁 Pour toi

CineSort sait maintenant **verrouiller chaque champ individuellement**, comme
le fait **Jellyfin** avec ses "Locked Fields". Tu as corrige a la main le
titre d'un film ? Tu as choisi un poster precis ? Tu as reecrit le resume ? Tu
peux maintenant poser un petit cadenas dessus, et **plus aucun rescan OMDb ou
TMDb ne pourra ecraser ta modification**, meme si tu cliques sur "Tout
reconstruire les metadonnees". Tes choix sont **persistents** : ils survivent
a la fermeture de l'app, aux redemarrages, et meme au changement d'identite
quand un film passe d'une identification par chemin a une identification TMDb.

C'est exactement la lecon retenue d'un **vrai bug Jellyfin** (le #15549) ou
des utilisateurs perdaient leurs corrections manuelles a chaque refresh
automatique. Ici, ca n'arrivera plus.

Petit detail rassurant : si tu lances "Tout reconstruire" sur **plus de 50
films**, CineSort affiche une **confirmation avec compte a rebours de 3
secondes** avant de te laisser cliquer (memo des actions dangereuses : on ne
risque pas le clic accidentel sur une grosse biblio).

## Notes

- Pas de bump VERSION (decision differee, coherent avec les batches Vague
  N/O/P-1/P-2).
- Tag local uniquement : `vague-p-batch3` (pas de push remote).
- Commits inclus : `defe745`.
- Backward compat ABSOLUE : `film_tmdb_overrides` (migration 023) intact,
  aucune modification de titres au-dela du renommage configure.
- Suite Vague P : sub-lots VP-D+ (mini-recovery) a venir.
