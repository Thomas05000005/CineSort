"""ApplyRepository : adapter composition du _ApplyMixin (issue #85).

Pattern :
- Heritage de _BaseRepository pour les helpers injectes (_managed_conn,
  _ensure_schema_group, _decode_row_json)
- Heritage de _ApplyMixin pour les methodes metier (insert_apply_batch,
  list_apply_operations, etc.)

L'ordre MRO (_BaseRepository, _ApplyMixin) garantit que les helpers
viennent de _BaseRepository (injection) plutot que d'attendre _StoreBase.
"""

from __future__ import annotations

from cinesort.infra.db._apply_mixin import _ApplyMixin
from cinesort.infra.db.repositories._base import _BaseRepository


class ApplyRepository(_BaseRepository, _ApplyMixin):
    """Repository pour les operations apply (batches + operations + pending moves).

    Methodes exposees (depuis _ApplyMixin) :
        insert_apply_batch, append_apply_operation, close_apply_batch,
        get_last_reversible_apply_batch, list_apply_operations,
        mark_apply_operation_undo_status, mark_apply_batch_undo_status,
        list_apply_batches_for_run, get_batch_rows_summary,
        list_apply_operations_by_row, insert_pending_move, delete_pending_move,
        list_pending_moves, count_pending_moves
    """

    pass
