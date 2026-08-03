-- v27 : self-healing migration 023 (suite 026, Vague L 2026-05-26).
--
-- Fix audit 2026-05-26 (v1.5.6) Vague L (mig-2) : la migration 026 ne se
-- declenche QUE si user_version < 26. Les usagers passes par 026 mais qui
-- ont a nouveau perdu les tables (ou qui ont uv>=26 sans ces tables suite a
-- un cas non-investigue) ne sont pas guéris. Cette migration applique le
-- meme self-healing IF NOT EXISTS, garantissant que tout user_version a
-- jour rentre dans un etat ou les 3 tables existent.
--
-- Strictement idempotente : CREATE TABLE/INDEX IF NOT EXISTS partout.
-- Pas de point-virgule dans les commentaires (cf migration 026).

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

PRAGMA user_version = 27;
