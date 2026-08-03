-- Migration 028: pragma_history (Vague O / VO-A)
-- Trace les bascules de profil pragma SQLite (audit + debug NAS).
--
-- Memoire feedback_sqlite_migration_test_existing_db : ordre strict
-- CREATE TABLE -> CREATE INDEX, IF NOT EXISTS partout, pas d'ALTER.
-- Idempotente : peut etre rejouee sans dommage si user_version regresse.

CREATE TABLE IF NOT EXISTS pragma_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    applied_at INTEGER NOT NULL,
    profile_name TEXT NOT NULL,
    db_path TEXT NOT NULL,
    storage_type_detected TEXT,
    pragmas_json TEXT,
    source TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pragma_history_applied_at
    ON pragma_history(applied_at);

CREATE INDEX IF NOT EXISTS idx_pragma_history_db_path
    ON pragma_history(db_path);

PRAGMA user_version = 28;
