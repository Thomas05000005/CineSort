"""_ScanMixin : thin wrapper backward-compat (issue #85 phase B3).

Migration #85 phase B3 (2026-05-16) : code metier deplace dans
`cinesort.infra.db.repositories.scan.ScanRepository`. Ce mixin delegue
a `self.scan.X()`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class _ScanMixin:
    """Backward-compat wrappers : delegue a self.scan (ScanRepository)."""

    def _ensure_incremental_tables(self) -> None:
        self.scan._ensure_incremental_tables()

    def clear_all_incremental_caches(self) -> Dict[str, int]:
        return self.scan.clear_all_incremental_caches()

    def get_incremental_file_hash(
        self,
        *,
        path: str,
        size: int,
        mtime_ns: int,
    ) -> Optional[str]:
        return self.scan.get_incremental_file_hash(path=path, size=size, mtime_ns=mtime_ns)

    def upsert_incremental_file_hash(
        self,
        *,
        path: str,
        size: int,
        mtime_ns: int,
        quick_hash: str,
        ts: Optional[float] = None,
    ) -> None:
        self.scan.upsert_incremental_file_hash(
            path=path, size=size, mtime_ns=mtime_ns, quick_hash=quick_hash, ts=ts
        )

    def get_incremental_folder_cache(
        self,
        *,
        root_path: str,
        folder_path: str,
        cfg_sig: str,
    ) -> Optional[Dict[str, Any]]:
        return self.scan.get_incremental_folder_cache(
            root_path=root_path, folder_path=folder_path, cfg_sig=cfg_sig
        )

    def upsert_incremental_folder_cache(
        self,
        *,
        root_path: str,
        folder_path: str,
        cfg_sig: str,
        folder_sig: str,
        rows_json: List[Dict[str, Any]],
        stats_json: Dict[str, Any],
        run_id: str,
        ts: Optional[float] = None,
    ) -> None:
        self.scan.upsert_incremental_folder_cache(
            root_path=root_path,
            folder_path=folder_path,
            cfg_sig=cfg_sig,
            folder_sig=folder_sig,
            rows_json=rows_json,
            stats_json=stats_json,
            run_id=run_id,
            ts=ts,
        )

    def prune_incremental_scan_cache(self, *, root_path: str, keep_folders: List[str]) -> int:
        return self.scan.prune_incremental_scan_cache(root_path=root_path, keep_folders=keep_folders)

    def get_incremental_row_cache(
        self,
        *,
        root_path: str,
        video_path: str,
        cfg_sig: str,
    ) -> Optional[Dict[str, Any]]:
        return self.scan.get_incremental_row_cache(
            root_path=root_path, video_path=video_path, cfg_sig=cfg_sig
        )

    def upsert_incremental_row_cache(
        self,
        *,
        root_path: str,
        video_path: str,
        video_size: int,
        video_mtime_ns: int,
        video_hash: str,
        folder_path: str,
        nfo_sig: Optional[str],
        cfg_sig: str,
        kind: str,
        row_json: Dict[str, Any],
        run_id: str,
        ts: Optional[float] = None,
    ) -> None:
        self.scan.upsert_incremental_row_cache(
            root_path=root_path,
            video_path=video_path,
            video_size=video_size,
            video_mtime_ns=video_mtime_ns,
            video_hash=video_hash,
            folder_path=folder_path,
            nfo_sig=nfo_sig,
            cfg_sig=cfg_sig,
            kind=kind,
            row_json=row_json,
            run_id=run_id,
            ts=ts,
        )

    def prune_incremental_row_cache(self, *, root_path: str, keep_video_paths: List[str]) -> int:
        return self.scan.prune_incremental_row_cache(
            root_path=root_path, keep_video_paths=keep_video_paths
        )
