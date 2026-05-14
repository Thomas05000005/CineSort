"""Base class pour les Repository SQLite (issue #85).

Strategie : composition au lieu d'heritage MRO. Chaque Repository recoit
le SQLiteStore parent en injection au constructeur et delegue les helpers
(_managed_conn, _ensure_schema_group, etc.) au store.

Vs l'ancien pattern mixin :
- Plus de couplage MRO fragile (Python resolu d'office l'heritage multiple)
- Repository instanciable en isolation pour les tests (juste mocker `store`)
- L'API publique de SQLiteStore reste backward-compat via wrappers

Pour les tests unitaires d'un Repository :
    class FakeStore:
        def _managed_conn(self): ...
        def _ensure_schema_group(self, name): ...
        def _decode_row_json(self, ...): ...

    repo = ApplyRepository(FakeStore())
    repo.insert_apply_batch(...)
"""

from __future__ import annotations

from typing import Any


class _BaseRepository:
    """Composition wrapper qui delegue les helpers au SQLiteStore parent.

    Args:
        store: Instance SQLiteStore (ou compatible avec les helpers requis :
            _connect, _managed_conn, _ensure_schema_group, _ensure_tables,
            _with_schema_group, _decode_row_json, _is_missing_table_error).
            Pour les tests, peut etre une stub class qui implemente ces
            methodes.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    # --- Delegation des helpers vers le store ---

    def _connect(self):
        return self._store._connect()

    def _managed_conn(self):
        return self._store._managed_conn()

    def _ensure_schema_group(self, group_name: str, **kwargs: Any) -> None:
        return self._store._ensure_schema_group(group_name, **kwargs)

    def _ensure_tables(self, *table_names: str, **kwargs: Any) -> None:
        return self._store._ensure_tables(*table_names, **kwargs)

    def _with_schema_group(self, group_name: str, operation: Any, **kwargs: Any) -> Any:
        return self._store._with_schema_group(group_name, operation, **kwargs)

    def _decode_row_json(self, *args: Any, **kwargs: Any) -> Any:
        return self._store._decode_row_json(*args, **kwargs)

    def _is_missing_table_error(self, exc: Any, table_name: str) -> bool:
        return self._store._is_missing_table_error(exc, table_name)
