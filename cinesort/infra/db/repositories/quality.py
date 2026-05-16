"""QualityRepository : profils + rapports + feedback (issue #85 phase B5).

Migration #85 phase B5 (2026-05-16) : meme pattern que B1-B4 :
- Code metier vit DANS QualityRepository
- _QualityMixin devient thin wrapper backward-compat
- SQLiteStore conserve son inheritance

Methodes exposees :
    get_active_quality_profile, save_quality_profile, get_quality_report,
    upsert_quality_report, list_quality_reports,
    insert_user_quality_feedback, list_user_quality_feedback,
    delete_user_quality_feedback, get_quality_report_stats,
    get_global_tier_distribution, get_unscored_film_count,
    get_quality_counts_for_runs
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from cinesort.infra.db.repositories._base import _BaseRepository


class QualityRepository(_BaseRepository):
    """Repository pour les profils qualite + rapports + feedback user."""

    def _ensure_quality_tables(self) -> None:
        self._ensure_schema_group("quality")

    def get_active_quality_profile(self) -> Optional[Dict[str, Any]]:
        """Retourne le profil de scoring qualite actuellement actif, ou None si aucun."""

        def op(conn: Any) -> Optional[Dict[str, Any]]:
            cur = conn.execute(
                """
                SELECT id, version, profile_json, created_ts, updated_ts, is_active
                FROM quality_profiles
                WHERE is_active=1
                ORDER BY updated_ts DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": str(row["id"]),
                "version": int(row["version"]),
                "profile_json": self._decode_row_json(row, "profile_json", default={}, expected_type=dict),
                "created_ts": float(row["created_ts"]),
                "updated_ts": float(row["updated_ts"]),
                "is_active": int(row["is_active"]),
            }

        return self._with_schema_group("quality", op)

    def save_quality_profile(
        self,
        *,
        profile_id: str,
        version: int,
        profile_json: Dict[str, Any],
        is_active: bool = True,
        ts: Optional[float] = None,
    ) -> None:
        """Persiste un profil de scoring ; si `is_active`, desactive les autres profils."""
        now = float(ts if ts is not None else time.time())
        payload = json.dumps(profile_json, ensure_ascii=False, sort_keys=True)
        pid = str(profile_id or "").strip()
        if not pid:
            raise ValueError("profile_id manquant")

        def op(conn: Any) -> None:
            if is_active:
                conn.execute("UPDATE quality_profiles SET is_active=0 WHERE is_active=1")
            conn.execute(
                """
                INSERT INTO quality_profiles(id, version, profile_json, created_ts, updated_ts, is_active)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(id)
                DO UPDATE SET
                  version=excluded.version,
                  profile_json=excluded.profile_json,
                  updated_ts=excluded.updated_ts,
                  is_active=excluded.is_active
                """,
                (
                    pid,
                    int(version),
                    payload,
                    now,
                    now,
                    1 if is_active else 0,
                ),
            )

        self._with_schema_group("quality", op)

    def get_quality_report(self, *, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        """Retourne le rapport qualite persiste pour (run_id, row_id), ou None."""

        def op(conn: Any) -> Optional[Dict[str, Any]]:
            cur = conn.execute(
                """
                SELECT run_id, row_id, score, tier, reasons_json, metrics_json, profile_id, profile_version, ts
                FROM quality_reports
                WHERE run_id=? AND row_id=?
                LIMIT 1
                """,
                (str(run_id), str(row_id)),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "run_id": str(row["run_id"]),
                "row_id": str(row["row_id"]),
                "score": int(row["score"]),
                "tier": str(row["tier"]),
                "reasons": self._decode_row_json(row, "reasons_json", default=[], expected_type=list),
                "metrics": self._decode_row_json(row, "metrics_json", default={}, expected_type=dict),
                "profile_id": str(row["profile_id"]),
                "profile_version": int(row["profile_version"]),
                "ts": float(row["ts"]),
            }

        return self._with_schema_group("quality", op)

    def upsert_quality_report(
        self,
        *,
        run_id: str,
        row_id: str,
        score: int,
        tier: str,
        reasons: List[str],
        metrics: Dict[str, Any],
        profile_id: str,
        profile_version: int,
        ts: Optional[float] = None,
    ) -> None:
        now = float(ts if ts is not None else time.time())
        reasons_payload = json.dumps(list(reasons or []), ensure_ascii=False, sort_keys=False)
        metrics_payload = json.dumps(dict(metrics or {}), ensure_ascii=False, sort_keys=True)

        def op(conn: Any) -> None:
            conn.execute(
                """
                INSERT INTO quality_reports(
                  run_id, row_id, score, tier, reasons_json, metrics_json, profile_id, profile_version, ts
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, row_id)
                DO UPDATE SET
                  score=excluded.score,
                  tier=excluded.tier,
                  reasons_json=excluded.reasons_json,
                  metrics_json=excluded.metrics_json,
                  profile_id=excluded.profile_id,
                  profile_version=excluded.profile_version,
                  ts=excluded.ts
                """,
                (
                    str(run_id),
                    str(row_id),
                    int(score),
                    str(tier),
                    reasons_payload,
                    metrics_payload,
                    str(profile_id),
                    int(profile_version),
                    now,
                ),
            )

        self._with_schema_group("quality", op)

    def list_quality_reports(self, *, run_id: str) -> List[Dict[str, Any]]:
        """Retourne tous les rapports qualite d'un run, tries par score croissant."""
        self._ensure_quality_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT run_id, row_id, score, tier, reasons_json, metrics_json, profile_id, profile_version, ts
                FROM quality_reports
                WHERE run_id=?
                ORDER BY score ASC, ts ASC
                """,
                (str(run_id),),
            )
            rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            reasons = self._decode_row_json(row, "reasons_json", default=[], expected_type=list)
            metrics = self._decode_row_json(row, "metrics_json", default={}, expected_type=dict)
            out.append(
                {
                    "run_id": str(row["run_id"]),
                    "row_id": str(row["row_id"]),
                    "score": int(row["score"]),
                    "tier": str(row["tier"]),
                    "reasons": reasons,
                    "metrics": metrics,
                    "profile_id": str(row["profile_id"]),
                    "profile_version": int(row["profile_version"]),
                    "ts": float(row["ts"]),
                }
            )
        return out

    # ---------------------------------------------------------------
    # P4.1 : user_quality_feedback (calibration perceptuelle)
    # ---------------------------------------------------------------

    def insert_user_quality_feedback(
        self,
        *,
        run_id: str,
        row_id: str,
        computed_score: int,
        computed_tier: str,
        user_tier: str,
        tier_delta: int,
        category_focus: Optional[str] = None,
        comment: Optional[str] = None,
        app_version: str = "",
    ) -> int:
        """Enregistre un feedback utilisateur sur un scoring film."""
        self._ensure_schema_group("user_feedback")
        now = time.time()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO user_quality_feedback(
                    run_id, row_id, computed_score, computed_tier,
                    user_tier, tier_delta, category_focus, comment, created_ts, app_version
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run_id),
                    str(row_id),
                    int(computed_score),
                    str(computed_tier),
                    str(user_tier),
                    int(tier_delta),
                    (str(category_focus) if category_focus else None),
                    (str(comment) if comment else None),
                    float(now),
                    str(app_version or ""),
                ),
            )
            return int(cur.lastrowid)

    def list_user_quality_feedback(
        self,
        *,
        run_id: Optional[str] = None,
        row_id: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Retourne les feedbacks utilisateurs, ordonnés du plus récent au plus ancien."""
        self._ensure_schema_group("user_feedback")
        clauses = []
        params: List[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(str(run_id))
        if row_id:
            clauses.append("row_id = ?")
            params.append(str(row_id))
        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, int(limit)))
        with self._managed_conn() as conn:
            cur = conn.execute(
                f"""
                SELECT id, run_id, row_id, computed_score, computed_tier,
                       user_tier, tier_delta, category_focus, comment, created_ts, app_version
                FROM user_quality_feedback
                {where_sql}
                ORDER BY created_ts DESC
                LIMIT ?
                """,
                tuple(params),
            )
            return [
                {
                    "id": int(r["id"]),
                    "run_id": str(r["run_id"]),
                    "row_id": str(r["row_id"]),
                    "computed_score": int(r["computed_score"] or 0),
                    "computed_tier": str(r["computed_tier"] or ""),
                    "user_tier": str(r["user_tier"] or ""),
                    "tier_delta": int(r["tier_delta"] or 0),
                    "category_focus": (str(r["category_focus"]) if r["category_focus"] else None),
                    "comment": (str(r["comment"]) if r["comment"] else None),
                    "created_ts": float(r["created_ts"] or 0.0),
                    "app_version": str(r["app_version"] or ""),
                }
                for r in cur.fetchall()
            ]

    def delete_user_quality_feedback(self, *, feedback_id: int) -> int:
        """Supprime un feedback par id. Retourne le nb de lignes affectées."""
        self._ensure_schema_group("user_feedback")
        with self._managed_conn() as conn:
            cur = conn.execute("DELETE FROM user_quality_feedback WHERE id = ?", (int(feedback_id),))
            return int(cur.rowcount or 0)

    def get_quality_report_stats(self, *, run_id: str) -> Dict[str, Any]:
        """Retourne {count, max_ts} pour les rapports qualite de ce run."""
        self._ensure_quality_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT COUNT(*) AS cnt, MAX(ts) AS max_ts
                FROM quality_reports
                WHERE run_id=?
                """,
                (str(run_id),),
            )
            row = cur.fetchone()
        return {
            "count": int((row["cnt"] if row else 0) or 0),
            "max_ts": float((row["max_ts"] if row else 0.0) or 0.0),
        }

    def get_global_tier_distribution(self, *, limit_runs: int = 20) -> Dict[str, Any]:
        """Aggregate tier distribution across the last N runs."""
        self._ensure_quality_tables()
        lim = max(1, int(limit_runs))
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT tier, COUNT(*) AS cnt
                FROM quality_reports
                WHERE run_id IN (
                    SELECT run_id FROM runs ORDER BY COALESCE(started_ts, created_ts) DESC LIMIT ?
                )
                GROUP BY tier
                """,
                (lim,),
            )
            dist: Dict[str, int] = {}
            for row in cur.fetchall():
                dist[str(row["tier"])] = int(row["cnt"] or 0)

            total_cur = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM quality_reports
                WHERE run_id IN (
                    SELECT run_id FROM runs ORDER BY COALESCE(started_ts, created_ts) DESC LIMIT ?
                )
                """,
                (lim,),
            )
            total_row = total_cur.fetchone()
            total = int((total_row["cnt"] if total_row else 0) or 0)

        return {"tiers": dist, "total_scored": total}

    def get_unscored_film_count(self, *, run_id: str, total_rows: int) -> int:
        """Count films in a run that have no quality report (never probed).

        On soustrait les films ayant un quality_report du total fourni par l'appelant
        (qui connait le total via le plan.jsonl ou la DB des runs).
        """
        self._ensure_quality_tables()
        rid = str(run_id).strip()
        if not rid or total_rows <= 0:
            return 0
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM (
                    SELECT DISTINCT row_id FROM quality_reports WHERE run_id = ?
                ) AS scored
                """,
                (rid,),
            )
            scored_row = cur.fetchone()
            scored = int((scored_row["cnt"] if scored_row else 0) or 0)
        return max(0, int(total_rows) - scored)

    def get_quality_counts_for_runs(self, run_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Retourne {run_id: {tier: count, ...}} pour la liste de runs donnee (agregation bulk)."""
        self._ensure_quality_tables()
        ids = [str(x) for x in (run_ids or []) if str(x).strip()]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._managed_conn() as conn:
            cur = conn.execute(
                f"""
                SELECT
                  run_id,
                  COUNT(*) AS scored_movies,
                  AVG(score) AS score_avg,
                  SUM(CASE WHEN score >= 85 THEN 1 ELSE 0 END) AS premium_count,
                  SUM(CASE WHEN score < 55 THEN 1 ELSE 0 END) AS low_count
                FROM quality_reports
                WHERE run_id IN ({placeholders})
                GROUP BY run_id
                """,
                tuple(ids),
            )
            out: Dict[str, Dict[str, Any]] = {}
            for row in cur.fetchall():
                out[str(row["run_id"])] = {
                    "scored_movies": int(row["scored_movies"] or 0),
                    "score_avg": float(row["score_avg"] or 0.0),
                    "premium_count": int(row["premium_count"] or 0),
                    "low_count": int(row["low_count"] or 0),
                }
            return out
