-- v23 : tables d'etat pour la spec 06 (Modal Film).
--
-- Trois besoins persistants exposes par le modal :
--   1. `ignored_alerts` : "j'ai vu cette alerte, on continue".
--      L'alerte disparait visuellement pour le film mais reste loggee en DB
--      pour les stats globales.
--   2. `film_marked_for_deletion` : marque un fichier pour deplacement vers
--      `<root>/_user_marked_for_deletion/` au prochain apply. Reversible
--      tant que l'apply n'est pas faite (DELETE FROM la table).
--   3. `film_tmdb_overrides` : enregistre le choix manuel d'un candidat TMDb
--      different par l'utilisateur (set_film_tmdb_candidate). Reversible tant
--      que l'apply n'est pas faite.
--
-- Pattern identique aux migrations precedentes : pas de BEGIN/COMMIT explicite
-- (migration_manager.apply() encapsule deja). Les CREATE TABLE/INDEX sont
-- idempotents via IF NOT EXISTS.

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

PRAGMA user_version = 23;
