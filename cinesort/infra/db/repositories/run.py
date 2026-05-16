"""RunRepository : runs + errors (issue #85 phase B6).

Migration #85 phase B6 (2026-05-16) : meme pattern que B1-B5 :
- Code metier vit DANS RunRepository
- _RunMixin devient thin wrapper backward-compat
- SQLiteStore conserve son inheritance

Note specifique B6 : `insert_run_pending` appelle `initialize()` en fallback
si la table runs n'existe pas. Dans RunRepository (_BaseRepository compose),
on appelle `self._store.initialize()` pour deleguer au SQLiteStore parent.

Methodes exposees :
    insert_run_pending, mark_run_running, update_run_progress,
    mark_cancel_requested, mark_run_done, mark_run_cancelled,
    mark_run_failed, insert_error, get_run, list_errors, get_latest_run,
    list_runs, get_runs_summary, get_error_counts_for_runs
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from cinesort.infra.db.repositories._base import _BaseRepository


class RunRepository(_BaseRepository):
    """Repository pour les tables runs + errors."""

    def _insert_pending_run_row(
        self,
        conn: Any,
        *,
        run_id: str,
        created_ts: float,
        root: str,
        state_dir: str,
        config_json: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO runs (
              run_id, status, created_ts, root, state_dir, config_json,
              stats_json, idx, total, current_folder, cancel_requested, error_message
            )
            VALUES (?, 'PENDING', ?, ?, ?, ?, NULL, 0, 0, '', 0, NULL)
            """,
            (run_id, created_ts, str(root), str(state_dir), config_json),
        )

    def _ensure_runs_table(self) -> None:
        self._ensure_schema_group("runs", min_user_version=1)

    def insert_run_pending(
        self,
        *,
        run_id: str,
        root: str,
        state_dir: str,
        config: Dict[str, Any],
        created_ts: Optional[float] = None,
    ) -> None:
        payload = json.dumps(config, ensure_ascii=False, sort_keys=True)
        now = float(created_ts if created_ts is not None else time.time())
        self._ensure_runs_table()

        try:
            with self._managed_conn() as conn:
                self._insert_pending_run_row(
                    conn,
                    run_id=run_id,
                    created_ts=now,
                    root=str(root),
                    state_dir=str(state_dir),
                    config_json=payload,
                )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, sqlite3.OperationalError) as exc:
            if not (isinstance(exc, sqlite3.OperationalError) and self._is_missing_table_error(exc, "runs")):
                raise
            # Fallback : table absente, delegue a SQLiteStore.initialize() qui
            # cree tous les schemas depuis migrations. Dans _BaseRepository,
            # self._store est le SQLiteStore.
            self._store.initialize()
            with self._managed_conn() as conn:
                self._insert_pending_run_row(
                    conn,
                    run_id=run_id,
                    created_ts=now,
                    root=str(root),
                    state_dir=str(state_dir),
                    config_json=payload,
                )

    def mark_run_running(self, run_id: str, *, started_ts: Optional[float] = None) -> None:
        """Bascule le run en statut RUNNING et enregistre `started_ts`."""
        ts = float(started_ts if started_ts is not None else time.time())
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status='RUNNING', started_ts=?, error_message=NULL
                WHERE run_id=?
                """,
                (ts, run_id),
            )

    def update_run_progress(self, run_id: str, *, idx: int, total: int, current_folder: str) -> None:
        """Met a jour la progression du run (indice courant, total, dossier en cours)."""
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET idx=?, total=?, current_folder=?
                WHERE run_id=?
                """,
                (int(idx), int(total), str(current_folder or ""), run_id),
            )

    def mark_cancel_requested(self, run_id: str) -> None:
        """Pose le flag `cancel_requested=1` ; la boucle de scan verifiera ce flag."""
        with self._managed_conn() as conn:
            conn.execute(
                "UPDATE runs SET cancel_requested=1 WHERE run_id=?",
                (run_id,),
            )

    def mark_run_done(
        self, run_id: str, *, stats: Optional[Dict[str, Any]] = None, ended_ts: Optional[float] = None
    ) -> None:
        """Bascule le run en statut DONE avec les stats finales serialisees en JSON."""
        ts = float(ended_ts if ended_ts is not None else time.time())
        stats_json = json.dumps(stats, ensure_ascii=False, sort_keys=True) if stats is not None else None
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status='DONE', ended_ts=?, stats_json=?, error_message=NULL
                WHERE run_id=?
                """,
                (ts, stats_json, run_id),
            )

    def mark_run_cancelled(
        self, run_id: str, *, stats: Optional[Dict[str, Any]] = None, ended_ts: Optional[float] = None
    ) -> None:
        """Bascule le run en statut CANCELLED (annule a la demande operateur)."""
        ts = float(ended_ts if ended_ts is not None else time.time())
        stats_json = json.dumps(stats, ensure_ascii=False, sort_keys=True) if stats is not None else None
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status='CANCELLED', ended_ts=?, stats_json=?, error_message=NULL
                WHERE run_id=?
                """,
                (ts, stats_json, run_id),
            )

    def mark_run_failed(self, run_id: str, *, error_message: str, ended_ts: Optional[float] = None) -> None:
        """Bascule le run en statut FAILED et enregistre le message d'erreur."""
        ts = float(ended_ts if ended_ts is not None else time.time())
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status='FAILED', ended_ts=?, error_message=?
                WHERE run_id=?
                """,
                (ts, str(error_message or ""), run_id),
            )

    def insert_error(
        self,
        *,
        run_id: str,
        step: str,
        code: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        ts: Optional[float] = None,
    ) -> None:
        """Insere une erreur associee au run (step, code, message + contexte JSON optionnel)."""
        now = float(ts if ts is not None else time.time())
        context_json = json.dumps(context, ensure_ascii=False, sort_keys=True) if context is not None else None

        with self._managed_conn() as conn:
            conn.execute(
                """
                INSERT INTO errors (run_id, ts, step, code, message, context_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, now, str(step), str(code), str(message), context_json),
            )

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retourne la ligne `runs` correspondant a `run_id`, ou None si absente."""

        def op(conn: Any) -> Optional[Dict[str, Any]]:
            cur = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,))
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

        return self._with_schema_group("runs", op, min_user_version=1)

    def list_errors(self, run_id: str) -> List[Dict[str, Any]]:
        """Retourne la liste chronologique des erreurs enregistrees pour ce run."""
        with self._managed_conn() as conn:
            cur = conn.execute(
                "SELECT * FROM errors WHERE run_id=? ORDER BY id ASC",
                (run_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_latest_run(self) -> Optional[Dict[str, Any]]:
        """Retourne le run le plus recent (par started_ts/created_ts), ou None."""
        self._ensure_runs_table()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT *
                FROM runs
                ORDER BY COALESCE(started_ts, created_ts) DESC, created_ts DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

    def list_runs(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        """Retourne les N derniers runs (metadonnees completes), ordre chronologique inverse."""
        self._ensure_runs_table()
        lim = max(1, int(limit))
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT *
                FROM runs
                ORDER BY COALESCE(started_ts, created_ts) DESC, created_ts DESC
                LIMIT ?
                """,
                (lim,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_runs_summary(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        """Return last N runs with basic metadata for timeline display."""
        self._ensure_runs_table()
        lim = max(1, int(limit))
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT run_id, status, created_ts, started_ts, ended_ts,
                       root, stats_json, total
                FROM runs
                ORDER BY COALESCE(started_ts, created_ts) DESC, created_ts DESC
                LIMIT ?
                """,
                (lim,),
            )
            out: List[Dict[str, Any]] = []
            for row in cur.fetchall():
                started = float(row["started_ts"] or 0)
                ended = float(row["ended_ts"] or 0)
                duration = (ended - started) if started and ended else 0.0
                stats = self._decode_row_json(row, "stats_json", default={}, expected_type=dict)
                health_snap = stats.get("health_snapshot") if isinstance(stats.get("health_snapshot"), dict) else None
                out.append(
                    {
                        "run_id": str(row["run_id"]),
                        "status": str(row["status"] or "PENDING"),
                        "start_ts": started,
                        "duration_s": round(duration, 1),
                        "total_rows": int(row["total"] or stats.get("planned_rows", 0) or 0),
                        "applied": bool(stats.get("applied_count", 0)),
                        "health_snapshot": health_snap,
                    }
                )
            return out

    def get_error_counts_for_runs(self, run_ids: List[str]) -> Dict[str, int]:
        """Retourne {run_id: nb_erreurs} pour la liste de runs donnee (agregation bulk)."""
        ids = [str(x) for x in (run_ids or []) if str(x).strip()]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._managed_conn() as conn:
            cur = conn.execute(
                f"""
                SELECT run_id, COUNT(*) AS cnt
                FROM errors
                WHERE run_id IN ({placeholders})
                GROUP BY run_id
                """,
                tuple(ids),
            )
            return {str(r["run_id"]): int(r["cnt"]) for r in cur.fetchall()}
