"""Vector search infra (V3.3 sqlite-vec scaffold).

Bounded context : recherche de films similaires via embeddings (kNN).
- Backend : extension SQLite `sqlite-vec` (C extension, dll bundled).
- Storage : table `vec_films_hash` (film_id INTEGER PK, embedding BLOB).
- Lifecycle : load_extension lazy (au premier appel knn_search/add_embedding).

Feature flag : `similar_films` (desactive par defaut, cf
ui/api/similar_films_facade.py). Le scaffold n'est PAS branche au runtime
tant que la dll sqlite-vec n'est pas integree au bundle PyInstaller
(cf docs/internal/notes/sqlite_vec_setup.md).

Backward-compat ABSOLUE : aucune modification du schema existant, la
migration 032 ne cree qu'une nouvelle table (CREATE TABLE IF NOT EXISTS).
"""

from __future__ import annotations

from .sqlite_vec_adapter import SqliteVecAdapter

__all__ = ["SqliteVecAdapter"]
