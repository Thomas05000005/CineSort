"""FilmModalRepository : etat persistant du Modal Film (spec 06).

Cf migration 023_film_modal_state.sql.

Trois tables :
    - ignored_alerts          : "j'ai vu cette alerte, on continue"
    - film_marked_for_deletion : marque pour bucket `_user_marked_for_deletion/`
    - film_tmdb_overrides     : choix manuel d'un candidat TMDb different

Les tables sont reversibles tant que l'apply n'est pas faite : un simple
DELETE remet l'etat initial.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from cinesort.infra.db.repositories._base import _BaseRepository


class FilmModalRepository(_BaseRepository):
    """Repository pour les tables d'etat du Modal Film."""

    def _ensure_tables(self) -> None:
        self._store._ensure_schema_group("film_modal_state")

    # ------------------------------------------------------------------
    # ignored_alerts
    # ------------------------------------------------------------------

    def insert_ignored_alert(self, row_id: str, alert_code: str) -> Dict[str, Any]:
        """Marque une alerte comme ignoree pour ce film. Idempotent via UNIQUE."""
        self._ensure_tables()
        ts = time.time()
        rid = str(row_id or "").strip()
        code = str(alert_code or "").strip()
        if not rid or not code:
            return {"ok": False, "inserted": False}
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO ignored_alerts(row_id, alert_code, ignored_at)
                VALUES (?, ?, ?)
                """,
                (rid, code, ts),
            )
            inserted = bool(cur.rowcount)
        return {"ok": True, "inserted": inserted, "ignored_at": ts}

    def list_ignored_alerts(self, row_id: str) -> List[str]:
        """Liste les alert_code ignores pour un row_id."""
        self._ensure_tables()
        rid = str(row_id or "").strip()
        if not rid:
            return []
        with self._managed_conn() as conn:
            cur = conn.execute(
                "SELECT alert_code FROM ignored_alerts WHERE row_id=? ORDER BY ignored_at ASC",
                (rid,),
            )
            return [str(r["alert_code"]) for r in cur.fetchall()]

    def is_alert_ignored(self, row_id: str, alert_code: str) -> bool:
        self._ensure_tables()
        rid = str(row_id or "").strip()
        code = str(alert_code or "").strip()
        if not rid or not code:
            return False
        with self._managed_conn() as conn:
            cur = conn.execute(
                "SELECT 1 FROM ignored_alerts WHERE row_id=? AND alert_code=? LIMIT 1",
                (rid, code),
            )
            return cur.fetchone() is not None

    # ------------------------------------------------------------------
    # film_marked_for_deletion
    # ------------------------------------------------------------------

    def mark_for_deletion(
        self,
        *,
        run_id: str,
        row_id: str,
        source_path: str = "",
    ) -> Dict[str, Any]:
        """Marque un film pour le bucket `_user_marked_for_deletion/`. Idempotent."""
        self._ensure_tables()
        ts = time.time()
        with self._managed_conn() as conn:
            conn.execute(
                """
                INSERT INTO film_marked_for_deletion(run_id, row_id, marked_at, source_path)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, row_id) DO UPDATE SET
                    marked_at=excluded.marked_at,
                    source_path=excluded.source_path
                """,
                (str(run_id), str(row_id), ts, str(source_path or "")),
            )
        return {"ok": True, "marked_at": ts}

    def unmark_for_deletion(self, *, run_id: str, row_id: str) -> Dict[str, Any]:
        """Annule le marquage (undo). Retourne {ok, removed} (removed = bool)."""
        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                "DELETE FROM film_marked_for_deletion WHERE run_id=? AND row_id=?",
                (str(run_id), str(row_id)),
            )
            removed = bool(cur.rowcount)
        return {"ok": True, "removed": removed}

    def is_marked_for_deletion(self, *, run_id: str, row_id: str) -> bool:
        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                "SELECT 1 FROM film_marked_for_deletion WHERE run_id=? AND row_id=? LIMIT 1",
                (str(run_id), str(row_id)),
            )
            return cur.fetchone() is not None

    def list_marked_for_deletion(self, *, run_id: str) -> List[Dict[str, Any]]:
        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT row_id, source_path, marked_at
                FROM film_marked_for_deletion
                WHERE run_id=?
                ORDER BY marked_at DESC
                """,
                (str(run_id),),
            )
            return [
                {
                    "row_id": str(r["row_id"]),
                    "source_path": str(r["source_path"] or ""),
                    "marked_at": float(r["marked_at"]),
                }
                for r in cur.fetchall()
            ]

    # ------------------------------------------------------------------
    # film_tmdb_overrides
    # ------------------------------------------------------------------

    def upsert_tmdb_override(
        self,
        *,
        run_id: str,
        row_id: str,
        tmdb_id: int,
        new_confidence: int,
        proposed_title: str = "",
        proposed_year: int = 0,
    ) -> Dict[str, Any]:
        """Enregistre le choix manuel d'un candidat TMDb. Reversible."""
        self._ensure_tables()
        ts = time.time()
        with self._managed_conn() as conn:
            conn.execute(
                """
                INSERT INTO film_tmdb_overrides(
                    run_id, row_id, tmdb_id, new_confidence,
                    proposed_title, proposed_year, chosen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, row_id) DO UPDATE SET
                    tmdb_id=excluded.tmdb_id,
                    new_confidence=excluded.new_confidence,
                    proposed_title=excluded.proposed_title,
                    proposed_year=excluded.proposed_year,
                    chosen_at=excluded.chosen_at
                """,
                (
                    str(run_id),
                    str(row_id),
                    int(tmdb_id),
                    int(new_confidence),
                    str(proposed_title or ""),
                    int(proposed_year or 0),
                    ts,
                ),
            )
        return {"ok": True, "chosen_at": ts}

    def get_tmdb_override(self, *, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT tmdb_id, new_confidence, proposed_title, proposed_year, chosen_at
                FROM film_tmdb_overrides
                WHERE run_id=? AND row_id=?
                LIMIT 1
                """,
                (str(run_id), str(row_id)),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "tmdb_id": int(row["tmdb_id"]),
            "new_confidence": int(row["new_confidence"]),
            "proposed_title": str(row["proposed_title"] or ""),
            "proposed_year": int(row["proposed_year"] or 0),
            "chosen_at": float(row["chosen_at"]),
        }

    def clear_tmdb_override(self, *, run_id: str, row_id: str) -> Dict[str, Any]:
        """Annule un override TMDb (undo)."""
        self._ensure_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                "DELETE FROM film_tmdb_overrides WHERE run_id=? AND row_id=?",
                (str(run_id), str(row_id)),
            )
            removed = bool(cur.rowcount)
        return {"ok": True, "removed": removed}
