# Vague P batch 4 - VP-D Decisions tri-etat & save_validation (migration 031)

## Resume technique

Quatrieme batch de la Vague P : implementation du sub-lot **VP-D**
(`VP-D-5`) introduisant des **decisions tri-etat** persistentes
(`accepted` / `rejected` / `deferred`) en remplacement du booleen binaire
`ok:bool`. Objectif : permettre a l'utilisateur de **reporter** un choix
sans dire ni "oui" ni "non", tout en preservant une **backward compat
ABSOLUE** sur la signature legacy `save_validation({ok:bool, ...})` qui
reste consommee par le frontend existant. Migration **031** stricte
`CREATE TABLE -> CREATE INDEX` (memo `feedback_sqlite_migration_test_existing_db`
respecte) testee sur fixture v30 reelle (post-VP-C). Repository
`DecisionsRepository` cable sur `SQLiteStore` + transition
`deferred -> accepted` qui consulte les **field locks VP-C** pour ne pas
ecraser les champs verrouilles. UI 3 boutons (Accepter / Reporter /
Rejeter) + `dangerConfirmModal` countdown 3s si > 50 items sur "Rejeter
Tout" (memo `feedback_cinesort_actions_dangereuses` respecte).

## Changements par item

### VP-D : decisions tri-etat & save_validation backward compat ABSOLUE

- **VP-D-5** (`a1795e4`) - `feat(VP-D-5)` : tri-etat decisions
  `accepted/rejected/deferred` + cablage `save_validation` backward compat
  ABSOLUE + UI tri-etat.

  Backend SQL (`cinesort/infra/db/migrations/031_tri_etat_decisions.sql`) :
  - `CREATE TABLE film_decisions_v2 (id PK, film_id TEXT, run_id TEXT,
    row_id TEXT, decision TEXT CHECK(decision IN
    ('accepted','rejected','deferred')), decided_at, source TEXT)`.
  - 2 `CREATE INDEX IF NOT EXISTS` (idx film_id, idx run_id).
  - `PRAGMA user_version=31`.
  - Ordre strict `CREATE TABLE -> CREATE INDEX`, **AUCUN ALTER** (memo
    `feedback_sqlite_migration_test_existing_db`).

  Backend infra (`cinesort/infra/db/repositories/decisions.py`) :
  - `DecisionsRepository` : CRUD (`set_decision`, `get_decision`,
    `list_for_run`, `list_for_film`, `clear_decision`).
  - `upgrade_deferred_to_accepted(film_id)` : transition tri-etat qui
    **consulte les `field_locks` VP-C** et retourne `respected_locks`
    (AC-3).
  - Helpers backward compat ABSOLUE : `to_legacy_ok_bool(decision)` et
    `from_legacy_ok_bool(ok)` pour mapper l'ancien shape `{ok:bool}`
    vers/depuis le tri-etat.

  Backend integration :
  - `cinesort/infra/db/sqlite_store.py` : enregistre `store.decisions` +
    `SCHEMA_GROUPS['tri_etat_decisions']`.
  - `cinesort/ui/api/run_flow_support.py::save_validation` : mirror
    tri-etat -> SQL **best-effort non bloquant** + accepte cle optionnelle
    `decision` en complement de `ok:bool`. Shape retour
    `{ok:bool, path:str}` **PRESERVEE** (AC-2).
  - `cinesort/ui/api/facades/run_facade.py::save_validation` +
    `cinesort/ui/api/cinesort_api.py::_save_validation_impl` : docstrings
    VP-D ajoutees.

  UI (`web/dashboard/views/library/lib-validation.js`) :
  - **3 boutons par row** : Accepter / Reporter / Rejeter (lecture tri-etat).
  - Bouton bulk **"Rejeter Tout"** -> `dangerConfirmModal` avec
    **countdown 3s SI > 50 items** (AC-4, memo
    `feedback_cinesort_actions_dangereuses` respecte).
  - Compteurs UI 3 etats (accepte / reporte / rejete) + classes CSS
    `row-deferred`.
  - `buildDecisionsPayload` emet **`decision` ET `ok`** (backward compat
    ABSOLUE).
  - `filterByDecisionState` exporte (filtre par etat).
  - `node --check lib-validation.js` OK.

## Tests

- `tests/test_tri_etat_decisions.py` (**30 tests**) : helpers backward
  compat `to_legacy_ok_bool` / `from_legacy_ok_bool`, CRUD repo, AC-3
  transition `deferred -> accepted` respecte field_locks VP-C, AC-5
  signatures kwargs distinctes (`apply_atomic` sur `apply()` uniquement,
  pas `save_validation()`), persistance close/reopen.
- `tests/test_save_validation_backward_compat.py` (**14 tests**) : AC-2
  shape `{ok:bool}` preservee sur payload legacy, payload mixte tri-etat
  sans rupture, best-effort mirror SQL non bloquant, helper
  `_mirror_decisions_to_sql`.
- `tests/test_existing_db_fixture_v77.py` (**+2 tests**) : AC-1 migration
  031 testee sur fixture v30 reelle (post-VP-C) + idempotence rejouable.
- **Total : 54 nouveaux tests verts.** 0 regression sur VP-A/VP-C (33/33
  verts).

Acceptance criteria (5/5) :

- AC-1 OK : migration 031 testee sur fixture v30 reelle
  (`test_existing_db_fixture_v77`).
- AC-2 OK : `save_validation` retourne `{ok:bool, path:str}` sur appel
  legacy.
- AC-3 OK : `upgrade_deferred_to_accepted` retourne `respected_locks`
  (consulte field_locks VP-C).
- AC-4 OK : `dangerConfirmModal` "Rejeter Tout > 50" countdown 3s.
- AC-5 OK : kwarg `apply_atomic` sur `apply()` uniquement, pas sur
  `save_validation()`.

## 🎁 Pour toi

Avant ce batch, CineSort te forcait a un choix binaire devant chaque film
proposition : **oui** (j'accepte) ou **non** (je refuse). Pas de
"j'hesite", pas de "je verrai plus tard". A partir de maintenant, tu as
**trois boutons** par film dans l'ecran de validation :

- **Accepter** : le film est valide, ses metadonnees sont appliquees.
- **Reporter** : tu n'es pas sur, tu y reviendras plus tard, le film
  reste dans une zone d'attente (decision `deferred`).
- **Rejeter** : non merci, on n'en parle plus.

Tes decisions sont maintenant **persistentes** : elles survivent a la
fermeture de l'app et aux redemarrages. Et quand tu reviens sur un film
"reporte" pour finalement l'accepter, CineSort **respecte les cadenas
que tu avais poses sur certains champs** (memo VP-C) : si tu avais
verrouille le titre ou le poster, ils restent intacts meme apres
acceptation.

Petit detail rassurant : si tu cliques sur **"Rejeter Tout"** sur plus de
**50 films**, CineSort affiche une **confirmation avec compte a rebours
de 3 secondes** avant de te laisser valider (memo des actions
dangereuses : pas de clic accidentel sur une grosse biblio).

Et cote interne : l'ancien format `{ok: true/false}` que l'UI envoyait
continue de fonctionner **exactement comme avant**. Aucune rupture, juste
plus de possibilites.

## Notes

- Pas de bump VERSION (decision differee, coherent avec les batches
  Vague N/O/P-1/P-2/P-3).
- Tag local uniquement : `vague-p-batch4` (pas de push remote).
- Commits inclus : `a1795e4`.
- **Backward compat ABSOLUE** : signature `save_validation({ok:bool, ...})`
  preservee, shape retour `{ok, path}` preservee, frontend legacy non
  casse. Le mirror SQL tri-etat est **best-effort non bloquant** : si
  l'ecriture SQL echoue, `save_validation` retourne quand meme `{ok:True}`.
- Suite Vague P : sub-lots VP-E+ (mini-recovery) a venir.
