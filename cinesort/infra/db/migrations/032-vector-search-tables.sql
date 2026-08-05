-- Migration 032 : vector search tables (V3.3 sqlite-vec scaffold).
--
-- Pattern : table plate pour stocker les embeddings de films (BLOB
-- float32 little-endian, dim 256 par defaut). La table virtuelle vec0
-- (HNSW) sera creee a RUNTIME par SqliteVecAdapter.create_vec_table()
-- via l'extension sqlite-vec, PAS dans cette migration (l'extension
-- n'est pas garantie chargee au moment de la migration).
--
-- Backward compat ABSOLUE : table CREATE IF NOT EXISTS, aucun schema
-- existant modifie. Si la feature flag `similar_films` reste OFF, la
-- table reste vide -- cout zero pour les utilisateurs existants.
--
-- Memoire feedback_sqlite_migration_test_existing_db : ordre strict
-- CREATE TABLE -> CREATE INDEX, IF NOT EXISTS partout, PAS d'ALTER.
-- Idempotente : peut etre rejouee sans dommage si user_version regresse.
--
-- Coordination V3.3 :
--   - Cinesort/infra/vector_search/sqlite_vec_adapter.py : adapter qui
--     consomme cette table + cree la virtual table vec0 a runtime.
--   - cinesort/ui/api/similar_films_facade.py : facade endpoint
--     (feature_flag=disabled par defaut).
--   - docs/internal/notes/sqlite_vec_setup.md : procedure dl/integration
--     vec0.dll dans le bundle PyInstaller.
--
-- Schema vec_films_hash :
--   film_id   : INTEGER PRIMARY KEY, refere films.id (FK logique, pas
--               de contrainte FK pour eviter cascade involontaire si
--               la migration est rejouee sur une base ancienne).
--   embedding : BLOB, vecteur float32 little-endian (256 floats = 1024
--               bytes par defaut). La dimension est validee a runtime
--               par SqliteVecAdapter (PAS de CHECK SQL : la dim peut
--               evoluer en V3.4+ sans nouvelle migration).
--
-- Note importante : PAS d'index HNSW dans cette migration. La virtual
-- table vec0(embedding float[256]) sera creee par create_vec_table() a
-- l'init de la feature flag.

CREATE TABLE IF NOT EXISTS vec_films_hash (
    film_id   INTEGER PRIMARY KEY,
    embedding BLOB NOT NULL
);

PRAGMA user_version = 32;
