from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional


class _ProbeMixin:
    def _ensure_probe_cache_table(self) -> None:
        self._ensure_schema_group("probe_cache")

    def get_probe_cache(
        self,
        *,
        path: str,
        size: int,
        mtime: float,
        tool: str,
    ) -> Optional[Dict[str, Any]]:
        def op(conn: Any) -> Optional[Dict[str, Any]]:
            cur = conn.execute(
                """
                SELECT path, size, mtime, tool, raw_json, normalized_json, ts
                FROM probe_cache
                WHERE path=? AND size=? AND mtime=? AND tool=?
                LIMIT 1
                """,
                (str(path), int(size), float(mtime), str(tool)),
            )
            row = cur.fetchone()
            if not row:
                return None

            return {
                "path": str(row["path"]),
                "size": int(row["size"]),
                "mtime": float(row["mtime"]),
                "tool": str(row["tool"]),
                "raw_json": self._decode_row_json(row, "raw_json", default=None, expected_type=(dict, list)),
                "normalized_json": self._decode_row_json(
                    row,
                    "normalized_json",
                    default=None,
                    expected_type=(dict, list),
                ),
                "ts": float(row["ts"]),
            }

        return self._with_schema_group("probe_cache", op)

    def upsert_probe_cache(
        self,
        *,
        path: str,
        size: int,
        mtime: float,
        tool: str,
        raw_json: Dict[str, Any],
        normalized_json: Dict[str, Any],
        ts: Optional[float] = None,
    ) -> None:
        now = float(ts if ts is not None else time.time())
        raw_payload = json.dumps(raw_json, ensure_ascii=False, sort_keys=True)
        norm_payload = json.dumps(normalized_json, ensure_ascii=False, sort_keys=True)

        def op(conn: Any) -> None:
            conn.execute(
                """
                INSERT INTO probe_cache(path, size, mtime, tool, raw_json, normalized_json, ts)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path, size, mtime, tool)
                DO UPDATE SET
                  raw_json=excluded.raw_json,
                  normalized_json=excluded.normalized_json,
                  ts=excluded.ts
                """,
                (
                    str(path),
                    int(size),
                    float(mtime),
                    str(tool),
                    raw_payload,
                    norm_payload,
                    now,
                ),
            )

        self._with_schema_group("probe_cache", op)

    def prune_probe_cache(self, *, retention_days: int = 90) -> int:
        """DB2 audit : supprime les entrees probe_cache non-touchees depuis `retention_days`.

        Utile pour eviter la croissance monotone sur une bibliotheque dynamique
        (fichiers supprimes cote disque laissent leur cache en DB indefiniment
        sans cet appel). A declencher soit au demarrage, soit depuis l'UI.
        Retourne le nombre d'entrees supprimees.
        """
        retention = max(1, int(retention_days))
        cutoff = time.time() - (retention * 24 * 3600)

        def op(conn: Any) -> int:
            cur = conn.execute("DELETE FROM probe_cache WHERE ts < ?", (float(cutoff),))
            return int(cur.rowcount or 0)

        return self._with_schema_group("probe_cache", op)
