-- Migration 031 : film_decisions_v2 tri-etat (Vague P / VP-D).
--
-- Pattern : decision tri-etat `accepted | rejected | deferred` (vs le
-- legacy binaire `ok: true | false`). Permet a l'utilisateur de mettre
-- un film "en suspens" (deferred) sans forcer un choix definitif.
--
-- Backward compat ABSOLUE : tous les endpoints existants qui retournent
-- `{ok: bool}` conservent leur shape via le helper `to_legacy_ok_bool`
-- (decisions.py). La nouvelle table coexiste avec la persistance JSON
-- (validation.json) — la table SQL est l'enrichissement long-terme,
-- le JSON reste la source primaire pour l'execution apply.
--
-- Memoire feedback_sqlite_migration_test_existing_db : ordre strict
-- CREATE TABLE -> CREATE INDEX, IF NOT EXISTS partout, PAS d'ALTER.
-- Idempotente : peut etre rejouee sans dommage si user_version regresse.
--
-- Coordination Vague P :
--   - VP-A `apply_atomic` : aucun conflit kwargs sur save_validation
--     (le parametre `apply_atomic` ne transite pas par cette table).
--   - VP-C `field_locks` : la transition `deferred -> accepted` doit
--     consulter les locks via `FieldLocksRepository.list_locks` AVANT
--     d'appliquer une mise a jour metadata (decisions.py respecte ce
--     contrat).
--
-- Schema :
--   film_id     : cle stable (tmdb:<id> ou path:<sha1>) cf VP-C.
--   run_id      : run d'origine (audit).
--   row_id      : row UI d'origine (audit) — peut etre vide.
--   decision    : 'accepted' | 'rejected' | 'deferred' (CHECK strict).
--   decided_at  : timestamp epoch.
--   decided_by  : 'user' | 'auto' | 'bulk' | ... (audit).
--   reason      : raison optionnelle (texte libre).
--
-- Unicite : (film_id, run_id). Une decision par film par run. Re-poser
-- une decision sur le meme (film_id, run_id) fait un upsert.

CREATE TABLE IF NOT EXISTS film_decisions_v2 (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    film_id     TEXT NOT NULL,
    run_id      TEXT NOT NULL DEFAULT '',
    row_id      TEXT NOT NULL DEFAULT '',
    decision    TEXT NOT NULL CHECK(decision IN ('accepted','rejected','deferred')),
    decided_at  REAL NOT NULL,
    decided_by  TEXT NOT NULL DEFAULT 'user',
    reason      TEXT NOT NULL DEFAULT '',
    UNIQUE(film_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_film_decisions_v2_film_decision
    ON film_decisions_v2(film_id, decision);

CREATE INDEX IF NOT EXISTS idx_film_decisions_v2_run_decision
    ON film_decisions_v2(run_id, decision);

PRAGMA user_version = 31;
