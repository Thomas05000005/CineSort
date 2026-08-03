-- Migration 029 : apply_batch_modes (Vague P / VP-A — Apply atomique forward rollback).
--
-- Permet le mode apply atomique opt-in : si une operation echoue au milieu
-- du batch, toutes les operations precedentes sont annulees (rollback forward
-- via le journal `move_journal` existant), laissant le FS dans l'etat
-- exact d'avant l'apply.
--
-- Memoire feedback_sqlite_migration_test_existing_db : ordre strict
-- CREATE TABLE -> CREATE INDEX, IF NOT EXISTS partout, PAS d'ALTER.
-- Idempotente : peut etre rejouee sans dommage si user_version regresse.
--
-- Schema :
--   batch_id          : FK logique vers apply_batches.batch_id (pas de FK
--                       declaree SQLite pour eviter les cascades cross-table
--                       au cas ou un test purge apply_batches manuellement —
--                       meme convention que duplicate_decisions).
--   atomic_enabled    : 1 si le batch a ete lance en mode atomique opt-in.
--   rollback_status   : etat du rollback forward post-failure.
--                       Valeurs : 'NONE' (jamais declenche, default),
--                                 'IN_PROGRESS' (rollback en cours),
--                                 'ROLLED_BACK_BY_ATOMIC' (succes),
--                                 'ROLLBACK_FAILED' (DB rollback OK, FS
--                                 revert ko ou inverse — audit log requis),
--                                 'ROLLBACK_PARTIAL' (certains revert ok).
--   rolled_back_at    : timestamp ISO 8601 du moment ou rollback declenche.
--
-- Coordination undo classique : `rollback_status` est volontairement separe
-- de `apply_batches.status` + `apply_operations.undo_status`. Le rollback
-- atomique ne touche pas a la chaine undo manuelle (`UNDONE_DONE`/`PARTIAL`)
-- — un batch peut etre ROLLED_BACK_BY_ATOMIC ET ensuite ne pas etre undo-able.
-- `get_last_reversible_apply_batch` reste base sur status='DONE', donc
-- un batch rollback-atomique (status='FAILED') n'apparait pas dans l'undo
-- — comportement attendu (rien a defaire, deja revert).

CREATE TABLE IF NOT EXISTS apply_batch_modes (
    batch_id         TEXT PRIMARY KEY,
    atomic_enabled   INTEGER NOT NULL DEFAULT 0,
    rollback_status  TEXT NOT NULL DEFAULT 'NONE',
    rolled_back_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_apply_batch_modes_status
    ON apply_batch_modes(rollback_status);

CREATE INDEX IF NOT EXISTS idx_apply_batch_modes_atomic
    ON apply_batch_modes(atomic_enabled);

PRAGMA user_version = 29;
