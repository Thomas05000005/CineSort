-- v26 : self-healing migration 023 (Vague H followup, 2026-05-25).
--
-- INCIDENT  sur la DB de l'utilisateur principal (et potentiellement d'autres),
-- la migration 023 est marquee comme appliquee dans schema_migrations MAIS
-- les 3 tables qu'elle cree (ignored_alerts, film_marked_for_deletion,
-- film_tmdb_overrides) sont absentes. Cause racine inconnue (les CREATE TABLE
-- sont IF NOT EXISTS dans 023, donc pas de fail visible possiblement un
-- ancien bug du migration_manager ou un bootstrap qui a echappe les
-- statements). Resultat library/get_film_full crashe en OperationalError
-- no such table ignored_alerts.
--
-- Cette migration est strictement idempotente (toutes les tables et index
-- utilisent IF NOT EXISTS). Elle est safe meme si les tables existent deja.
-- NB pas de point-virgule dans ce commentaire car _split_sql_statements
-- du migration_manager split naivement sur point-virgule sans skip les --

CREATE TABLE IF NOT EXISTS ignored_alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    row_id      TEXT    NOT NULL,
    alert_code  TEXT    NOT NULL,
    ignored_at  REAL    NOT NULL,
    UNIQUE(row_id, alert_code)
);

CREATE INDEX IF NOT EXISTS idx_ignored_alerts_row ON ignored_alerts(row_id);

CREATE TABLE IF NOT EXISTS film_marked_for_deletion (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL,
    row_id       TEXT    NOT NULL,
    marked_at    REAL    NOT NULL,
    source_path  TEXT    DEFAULT '',
    UNIQUE(run_id, row_id)
);

CREATE INDEX IF NOT EXISTS idx_marked_deletion_run ON film_marked_for_deletion(run_id);

CREATE TABLE IF NOT EXISTS film_tmdb_overrides (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL,
    row_id          TEXT    NOT NULL,
    tmdb_id         INTEGER NOT NULL,
    new_confidence  INTEGER NOT NULL,
    proposed_title  TEXT    DEFAULT '',
    proposed_year   INTEGER DEFAULT 0,
    chosen_at       REAL    NOT NULL,
    UNIQUE(run_id, row_id)
);

CREATE INDEX IF NOT EXISTS idx_tmdb_overrides_run ON film_tmdb_overrides(run_id);

PRAGMA user_version = 26;
