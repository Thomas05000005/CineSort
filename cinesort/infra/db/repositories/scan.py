"""ScanRepository : caches incremental scan (issue #85 phase B3).

Migration #85 phase B3 (2026-05-16) : meme pattern que B1/B2 :
- Code metier vit DANS ScanRepository
- B8 CLOSE (2026-05, commit 482f3e6) : _ScanMixin et l'heritage MRO supprimes
- SQLiteStore expose store.scan (heritage MRO supprime en B8)

Methodes exposees :
    clear_all_incremental_caches, get_incremental_file_hash,
    upsert_incremental_file_hash, get_incremental_folder_cache,
    upsert_incremental_folder_cache, prune_incremental_scan_cache,
    get_incremental_row_cache, upsert_incremental_row_cache,
    prune_incremental_row_cache
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from cinesort.infra.db.repositories._base import _BaseRepository

# Taille de lot pour les DELETE ... IN (...) de purge. Une clause `NOT IN` avec
# un placeholder par entrée conservée dépasse SQLITE_MAX_VARIABLE_NUMBER (999 sur
# SQLite < 3.32) dès qu'une racine contient plus d'entrées que la limite →
# sqlite3.OperationalError "too many SQL variables". On borne à 500 (< 999).
_PRUNE_CHUNK = 500


class ScanRepository(_BaseRepository):
    """Repository pour les caches incremental scan (file hashes, folder, row)."""

    def _ensure_incremental_tables(self) -> None:
        self._ensure_schema_group("incremental")

    def clear_all_incremental_caches(self) -> Dict[str, int]:
        """Purge TOTALE des 3 tables de cache incremental, tous roots confondus.

        Utilise par l'endpoint reset_incremental_cache() pour forcer un rescan
        complet. La purge par root_path (prune_*) n'est pas fiable si les
        settings ne referencent plus le root ou si le chemin a ete normalise
        differemment. Cette methode supprime tout, sans filtre.

        Tolerance : chaque table est purgee dans son propre try/except, et cette
        tolerance est BORNEE a « table absente » (migration partielle, install
        ancienne). On enregistre alors 0 et on continue plutot que de bloquer
        toute la purge. Toute autre `OperationalError` (base verrouillee, E/S,
        schema invalide) REMONTE : rendre 0 signifierait « rien a supprimer »
        alors que rien n'a ete supprime, et le rapport de purge mentirait.

        Retourne le nombre de lignes supprimees par table.
        """

        def _safe_delete(conn: Any, table: str) -> int:
            try:
                return int(conn.execute(f"DELETE FROM {table}").rowcount or 0)
            except sqlite3.OperationalError as exc:
                # UNIQUEMENT « table absente » (ex: migration pas encore passee
                # sur cette base) : elle ne contient alors rien a purger, 0 est
                # la verite.
                #
                # Un `except` large avalait aussi « database is locked », un
                # schema invalide ou une erreur d'E/S : la purge n'avait PAS eu
                # lieu et le rapport annoncait quand meme 0 ligne supprimee,
                # indiscernable d'une table deja vide. L'appelant
                # (`reset_incremental_cache`) en concluait un rescan complet
                # force, alors que le cache etait intact — le rescan suivant
                # repartait du cache perime.
                #
                # Meme discrimination que `run_id_est_utilise` / `delete_run`
                # (repositories/run.py) : on reutilise leur `_is_missing_table_error`
                # plutot que d'en reecrire une variante qui pourrait diverger.
                if not self._is_missing_table_error(exc, table):
                    raise
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

            # Chunké : on résout d'abord les dossiers obsolètes (existants moins
            # ceux à conserver) puis on supprime par lots de _PRUNE_CHUNK. Évite la
            # clause `NOT IN` non bornée (un placeholder par dossier conservé) qui
            # lève OperationalError "too many SQL variables" sur les grosses racines.
            keep_set = set(keep)
            existing = [
                str(r["folder_path"])
                for r in conn.execute(
                    "SELECT folder_path FROM incremental_scan_cache WHERE root_path=?",
                    (root,),
                )
            ]
            stale = [p for p in existing if p not in keep_set]
            deleted = 0
            for i in range(0, len(stale), _PRUNE_CHUNK):
                chunk = stale[i : i + _PRUNE_CHUNK]
                ph = ",".join("?" for _ in chunk)
                cur = conn.execute(
                    f"DELETE FROM incremental_scan_cache WHERE root_path=? AND folder_path IN ({ph})",
                    (root, *chunk),
                )
                deleted += int(cur.rowcount or 0)
            return deleted

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

            # Chunké : mêmes raisons que prune_incremental_scan_cache — on borne le
            # nombre de variables SQL en supprimant les vidéos obsolètes par lots.
            keep_set = set(keep)
            existing = [
                str(r["video_path"])
                for r in conn.execute(
                    "SELECT video_path FROM incremental_row_cache WHERE root_path=?",
                    (root,),
                )
            ]
            stale = [p for p in existing if p not in keep_set]
            deleted = 0
            for i in range(0, len(stale), _PRUNE_CHUNK):
                chunk = stale[i : i + _PRUNE_CHUNK]
                ph = ",".join("?" for _ in chunk)
                cur = conn.execute(
                    f"DELETE FROM incremental_row_cache WHERE root_path=? AND video_path IN ({ph})",
                    (root, *chunk),
                )
                deleted += int(cur.rowcount or 0)
            return deleted

        return self._with_schema_group("incremental", op)
