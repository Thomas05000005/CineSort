-- Migration 030 : field_locks Jellyfin-style (Vague P / VP-C).
--
-- Reproduit le pattern Jellyfin `LockedFields` : verrous champ-par-champ
-- pour resister au rescan/refresh OMDb/TMDb. Lecon bug Jellyfin #15549 :
-- les locks doivent etre persistes en DB (pas juste en memoire) et
-- consultes avant toute ecriture d'un enrichissement automatique.
--
-- Memoire feedback_sqlite_migration_test_existing_db : ordre strict
-- CREATE TABLE -> CREATE INDEX, IF NOT EXISTS partout, PAS d'ALTER.
-- Idempotente : peut etre rejouee sans dommage si user_version regresse.
--
-- Cle stable film_id (`cinesort/domain/film_identity.py:compute_film_id`) :
--   - "tmdb:<id>" quand on connait l'id TMDb canonique
--   - "path:<sha1(folder+video)>" sinon (fallback avant Identify manuel)
--
-- Fix #5 : lors de la transition path: -> tmdb: (Identify manuel ou
-- rematch automatique reussi), TOUS les locks de l'ancien film_id sont
-- migres vers le nouveau via `migrate_locks` du repository. L'index
-- `idx_film_id` est dedie a cette operation.
--
-- Coexistence : `film_tmdb_overrides` (migration 023) reste intacte. Les
-- deux tables vivent en parallele — la nouvelle table verrouille au
-- niveau du *champ*, l'ancienne au niveau du *match TMDb*. Backward
-- compat absolue : aucune migration de donnees, aucun ALTER.
--
-- Schema :
--   film_id        : cle stable (tmdb:<id> ou path:<sha1>).
--   run_id         : run d'origine du lock (audit, peut etre vide).
--   row_id         : row UI au moment du lock (audit, peut etre vide).
--   field_name     : nom du champ verrouille (ex. "title", "year",
--                    "tmdb_id", "imdb_id", "overview", "genres"...).
--   locked_value   : valeur verrouillee serialisee en JSON (str/int/dict).
--   locked_at      : timestamp epoch.
--   source         : "manual_identify" | "user_edit" | "ui_lock"...

CREATE TABLE IF NOT EXISTS film_field_locks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    film_id       TEXT NOT NULL,
    run_id        TEXT NOT NULL DEFAULT '',
    row_id        TEXT NOT NULL DEFAULT '',
    field_name    TEXT NOT NULL,
    locked_value  TEXT NOT NULL DEFAULT '',
    locked_at     REAL NOT NULL,
    source        TEXT NOT NULL DEFAULT 'ui_lock',
    UNIQUE(film_id, field_name)
);

CREATE INDEX IF NOT EXISTS idx_film_field_locks_film
    ON film_field_locks(film_id);

CREATE INDEX IF NOT EXISTS idx_film_field_locks_field
    ON film_field_locks(field_name);

-- Fix #5 : index dedie a la migration des locks lors de la transition
-- path: -> tmdb:. `migrate_locks(old_film_id, new_film_id)` fait un
-- UPDATE WHERE film_id=? — index obligatoire pour la perf sur grosses
-- bibliotheques.
CREATE INDEX IF NOT EXISTS idx_film_field_locks_film_id
    ON film_field_locks(film_id, field_name);

PRAGMA user_version = 30;
