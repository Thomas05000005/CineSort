from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional


class _ScanMixin:
    def _ensure_incremental_tables(self) -> None:
        self._ensure_schema_group("incremental")

    def clear_all_incremental_caches(self) -> Dict[str, int]:
        """Purge TOTALE des 3 tables de cache incremental, tous roots confondus.

        Utilise par l'endpoint reset_incremental_cache() pour forcer un rescan
        complet. La purge par root_path (prune_*) n'est pas fiable si les
        settings ne referencent plus le root ou si le chemin a ete normalise
        differemment. Cette methode supprime tout, sans filtre.

        Tolerance : chaque table est purgee dans son propre try/except. Si une
        table n'existe pas (migration partielle, install ancienne, DB foireuse),
        on enregistre 0 et on continue plutot que de bloquer toute la purge.

        Retourne le nombre de lignes supprimees par table.
        """

        def _safe_delete(conn: Any, table: str) -> int:
            try:
                return int(conn.execute(f"DELETE FROM {table}").rowcount or 0)
            except sqlite3.OperationalError:
                # Table manquante (ex: migration non encore passee sur cette DB).
                # On recree la table puis on retourne 0.
                return 0

        def op(conn: Any) -> Dict[str, int]:
            n_folder = _safe_delete(conn, "incremental_scan_cache")
            n_row = _safe_delete(conn, "incremental_row_cache")
            n_hash = _safe_delete(conn, "incremental_file_hashes")
            return {
                "folder_cache": n_folder,
                "row_cache": n_row,
                "file_hashes": n_hash,
            }

        # On passe par _managed_conn directement pour eviter _ensure_schema_group
        # qui ne connait pas incremental_row_cache (ajoutee par migration 008,
        # pas listee dans SCHEMA_GROUPS["incremental"]).
        with self._managed_conn() as conn:
            return op(conn)

    def get_incremental_file_hash(
        self,
        *,
        path: str,
        size: int,
        mtime_ns: int,
    ) -> Optional[str]:
        def op(conn: Any) -> Optional[str]:
            cur = conn.execute(
                """
                SELECT quick_hash
                FROM incremental_file_hashes
                WHERE path=? AND size=? AND mtime_ns=?
                LIMIT 1
                """,
                (str(path), int(size), int(mtime_ns)),
            )
            row = cur.fetchone()
            if not row:
                return None
            return str(row["quick_hash"] or "") or None

        return self._with_schema_group("incremental", op)

    def upsert_incremental_file_hash(
        self,
        *,
        path: str,
        size: int,
        mtime_ns: int,
        quick_hash: str,
        ts: Optional[float] = None,
    ) -> None:
        now = float(ts if ts is not None else time.time())

        def op(conn: Any) -> None:
            conn.execute(
                """
                INSERT INTO incremental_file_hashes(path, size, mtime_ns, quick_hash, updated_ts)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(path)
                DO UPDATE SET
                  size=excluded.size,
                  mtime_ns=excluded.mtime_ns,
                  quick_hash=excluded.quick_hash,
                  updated_ts=excluded.updated_ts
                """,
                (
                    str(path),
                    int(size),
                    int(mtime_ns),
                    str(quick_hash),
                    now,
                ),
            )

        self._with_schema_group("incremental", op)

    def get_incremental_folder_cache(
        self,
        *,
        root_path: str,
        folder_path: str,
        cfg_sig: str,
    ) -> Optional[Dict[str, Any]]:
        def op(conn: Any) -> Optional[Dict[str, Any]]:
            cur = conn.execute(
                """
                SELECT root_path, folder_path, cfg_sig, folder_sig, rows_json, stats_json, updated_ts, last_run_id
                FROM incremental_scan_cache
                WHERE root_path=? AND folder_path=? AND cfg_sig=?
                LIMIT 1
                """,
                (str(root_path), str(folder_path), str(cfg_sig)),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "root_path": str(row["root_path"]),
                "folder_path": str(row["folder_path"]),
                "cfg_sig": str(row["cfg_sig"]),
                "folder_sig": str(row["folder_sig"]),
                "rows_json": self._decode_row_json(row, "rows_json", default=[], expected_type=list),
                "stats_json": self._decode_row_json(row, "stats_json", default={}, expected_type=dict),
                "updated_ts": float(row["updated_ts"] or 0.0),
                "last_run_id": str(row["last_run_id"] or ""),
            }

        return self._with_schema_group("incremental", op)

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
        now = float(ts if ts is not None else time.time())
        rows_payload = json.dumps(list(rows_json or []), ensure_ascii=False, sort_keys=True)
        stats_payload = json.dumps(dict(stats_json or {}), ensure_ascii=False, sort_keys=True)

        def op(conn: Any) -> None:
            conn.execute(
                """
                INSERT INTO incremental_scan_cache(
                  root_path, folder_path, cfg_sig, folder_sig, rows_json, stats_json, updated_ts, last_run_id
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(root_path, folder_path)
                DO UPDATE SET
                  cfg_sig=excluded.cfg_sig,
                  folder_sig=excluded.folder_sig,
                  rows_json=excluded.rows_json,
                  stats_json=excluded.stats_json,
                  updated_ts=excluded.updated_ts,
                  last_run_id=excluded.last_run_id
                """,
                (
                    str(root_path),
                    str(folder_path),
                    str(cfg_sig),
                    str(folder_sig),
                    rows_payload,
                    stats_payload,
                    now,
                    str(run_id or ""),
                ),
            )

        self._with_schema_group("incremental", op)

    def prune_incremental_scan_cache(self, *, root_path: str, keep_folders: List[str]) -> int:
        """Purge les entrees cache dossier (v1) pour les dossiers absents de la liste a conserver."""
        root = str(root_path)
        keep = [str(x) for x in (keep_folders or []) if str(x).strip()]

        def op(conn: Any) -> int:
            if not keep:
                cur = conn.execute(
                    "DELETE FROM incremental_scan_cache WHERE root_path=?",
                    (root,),
                )
                return int(cur.rowcount or 0)

            placeholders = ",".join("?" for _ in keep)
            params = [root]
            params.extend(keep)
            cur = conn.execute(
                f"""
                DELETE FROM incremental_scan_cache
                WHERE root_path=?
                  AND folder_path NOT IN ({placeholders})
                """,
                tuple(params),
            )
            return int(cur.rowcount or 0)

        return self._with_schema_group("incremental", op)

    # --- Scan v2: per-video row cache ---

    def get_incremental_row_cache(
        self,
        *,
        root_path: str,
        video_path: str,
        cfg_sig: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a cached PlanRow for a specific video file."""

        def op(conn: Any) -> Optional[Dict[str, Any]]:
            cur = conn.execute(
                """
                SELECT root_path, video_path, video_size, video_mtime_ns, video_hash,
                       folder_path, nfo_sig, cfg_sig, kind, row_json, updated_ts, last_run_id
                FROM incremental_row_cache
                WHERE root_path=? AND video_path=? AND cfg_sig=?
                LIMIT 1
                """,
                (str(root_path), str(video_path), str(cfg_sig)),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "root_path": str(row["root_path"]),
                "video_path": str(row["video_path"]),
                "video_size": int(row["video_size"]),
                "video_mtime_ns": int(row["video_mtime_ns"]),
                "video_hash": str(row["video_hash"]),
                "folder_path": str(row["folder_path"]),
                "nfo_sig": str(row["nfo_sig"]) if row["nfo_sig"] is not None else None,
                "cfg_sig": str(row["cfg_sig"]),
                "kind": str(row["kind"] or "single"),
                "row_json": self._decode_row_json(row, "row_json", default={}, expected_type=dict),
                "updated_ts": float(row["updated_ts"] or 0.0),
                "last_run_id": str(row["last_run_id"] or ""),
            }

        return self._with_schema_group("incremental", op)

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
        """Store or update a cached PlanRow for a specific video file."""
        now = float(ts if ts is not None else time.time())
        payload = json.dumps(row_json, ensure_ascii=False, sort_keys=True)

        def op(conn: Any) -> None:
            conn.execute(
                """
                INSERT INTO incremental_row_cache(
                  root_path, video_path, video_size, video_mtime_ns, video_hash,
                  folder_path, nfo_sig, cfg_sig, kind, row_json, updated_ts, last_run_id
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(root_path, video_path)
                DO UPDATE SET
                  video_size=excluded.video_size,
                  video_mtime_ns=excluded.video_mtime_ns,
                  video_hash=excluded.video_hash,
                  folder_path=excluded.folder_path,
                  nfo_sig=excluded.nfo_sig,
                  cfg_sig=excluded.cfg_sig,
                  kind=excluded.kind,
                  row_json=excluded.row_json,
                  updated_ts=excluded.updated_ts,
                  last_run_id=excluded.last_run_id
                """,
                (
                    str(root_path),
                    str(video_path),
                    int(video_size),
                    int(video_mtime_ns),
                    str(video_hash),
                    str(folder_path),
                    str(nfo_sig) if nfo_sig is not None else None,
                    str(cfg_sig),
                    str(kind or "single"),
                    payload,
                    now,
                    str(run_id or ""),
                ),
            )

        self._with_schema_group("incremental", op)

    def prune_incremental_row_cache(self, *, root_path: str, keep_video_paths: List[str]) -> int:
        """Delete row cache entries for videos no longer in the library."""
        root = str(root_path)
        keep = [str(x) for x in (keep_video_paths or []) if str(x).strip()]

        def op(conn: Any) -> int:
            if not keep:
                cur = conn.execute(
                    "DELETE FROM incremental_row_cache WHERE root_path=?",
                    (root,),
                )
                return int(cur.rowcount or 0)

            placeholders = ",".join("?" for _ in keep)
            params = [root]
            params.extend(keep)
            cur = conn.execute(
                f"""
                DELETE FROM incremental_row_cache
                WHERE root_path=?
                  AND video_path NOT IN ({placeholders})
                """,
                tuple(params),
            )
            return int(cur.rowcount or 0)

        return self._with_schema_group("incremental", op)
