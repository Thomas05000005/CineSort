"""ScanRepository : adapter composition du _ScanMixin (issue #85)."""

from __future__ import annotations

from cinesort.infra.db._scan_mixin import _ScanMixin
from cinesort.infra.db.repositories._base import _BaseRepository


class ScanRepository(_BaseRepository, _ScanMixin):
    """Repository pour les caches incremental scan (file hashes, folder, row).

    Methodes exposees (depuis _ScanMixin) :
        clear_all_incremental_caches, get_incremental_file_hash,
        upsert_incremental_file_hash, get_incremental_folder_cache,
        upsert_incremental_folder_cache, prune_incremental_scan_cache,
        get_incremental_row_cache, upsert_incremental_row_cache,
        prune_incremental_row_cache
    """

    pass
