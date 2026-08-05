"""QualityRepository : profils + rapports + feedback (issue #85 phase B5).

Migration #85 phase B5 (2026-05-16) : meme pattern que B1-B4 :
- Code metier vit DANS QualityRepository
- B8 CLOSE (2026-05, commit 482f3e6) : _QualityMixin et l'heritage MRO supprimes
- SQLiteStore expose store.quality (heritage MRO supprime en B8)

Methodes exposees :
    get_active_quality_profile, save_quality_profile, get_quality_report,
    get_quality_reports_for_pairs, upsert_quality_report, list_quality_reports,
    insert_user_quality_feedback, list_user_quality_feedback,
    delete_user_quality_feedback, get_quality_report_stats,
    get_global_tier_distribution, get_unscored_film_count,
    get_quality_counts_for_runs
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from cinesort.domain.tiers_helpers import LOW_TIERS_LOWER, PREMIUM_TIERS_LOWER
from cinesort.infra.db.repositories._base import _BaseRepository
from cinesort.infra.db.repositories._sql import SQL_CHUNK, chunked

# Nombre de couples (run_id, row_id) par requete de `get_quality_reports_for_pairs`.
# Chaque couple pese 2 parametres lies et un niveau d'imbrication `OR` : 200 tient
# tres en dessous de SQLITE_MAX_VARIABLE_NUMBER comme de SQLITE_MAX_EXPR_DEPTH.
_SQL_PAIR_CHUNK = 200

# AUDIT 2026-07-13 (HIGH-8) : exclut les runs utilitaires de bulk re-scan
# (config_json {"rescan_run_id": ...}) de la resolution du "dernier run". Ces
# runs de tracking n'ont ni plan.jsonl ni quality_reports -> sans ce filtre,
# get_global_tier_distribution(limit_runs=1) resolvait le parasite apres un
# re-scan groupe et renvoyait une distribution VIDE sur la page Qualite.
# MEME predicat que run.py:_NOT_RESCAN_TRACKING_SQL (duplique volontairement
# pour eviter un import inter-repository ; garder les deux synchronises).
_NOT_RESCAN_TRACKING_SQL = "COALESCE(config_json, '') NOT LIKE '%\"rescan_run_id\"%'"


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

    def get_quality_reports_for_pairs(
        self,
        *,
        pairs: Sequence[Tuple[str, str]],
    ) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """Version groupee de `get_quality_report` : {(run_id, row_id): rapport}.

        Issue #577 : la timeline d'un film appelait `get_quality_report` une fois
        par run (jusqu'a 100), et `list_films_overview` une fois par film (50).
        Chaque appel ouvre sa propre connexion SQLite.

        Les couples sans rapport sont ABSENTS du dict (l'appelant teste la
        presence, comme il testait `None` avant).
        """
        wanted: List[Tuple[str, str]] = []
        seen: set[Tuple[str, str]] = set()
        for run_id, row_id in pairs or []:
            key = (str(run_id), str(row_id))
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            wanted.append(key)
        if not wanted:
            return {}

        def op(conn: Any) -> Dict[Tuple[str, str], Dict[str, Any]]:
            out: Dict[Tuple[str, str], Dict[str, Any]] = {}
            for start in range(0, len(wanted), _SQL_PAIR_CHUNK):
                chunk = wanted[start : start + _SQL_PAIR_CHUNK]
                predicate = " OR ".join("(run_id=? AND row_id=?)" for _ in chunk)
                params: List[str] = []
                for run_id, row_id in chunk:
                    params.extend((run_id, row_id))
                cur = conn.execute(
                    f"""
                    SELECT run_id, row_id, score, tier, reasons_json, metrics_json,
                           profile_id, profile_version, ts
                    FROM quality_reports
                    WHERE {predicate}
                    """,
                    tuple(params),
                )
                for row in cur.fetchall():
                    out[(str(row["run_id"]), str(row["row_id"]))] = {
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
            return out

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
        # Fix audit 2026-05-30 (v1.5.8) tier_v2 fallback dashboard :
        # Memes pattern que library_support._build_library_rows:373-377 :
        # privilegier perceptual.global_tier_v2 si dispo, sinon retomber sur
        # quality_reports.tier (V1, calcule en post-scan auto). Sans ce fallback,
        # le dashboard affiche 0 Platinum quand le run n'a pas eu d'analyse
        # perceptuelle, alors meme que quality_reports contient des tiers V1
        # valides. On utilise LEFT JOIN + COALESCE pour la cle d'agregation.
        # Note: on garde tout en lowercase pour eviter les doublons "Gold"/"gold".
        with self._managed_conn() as conn:
            # _ensure tables perceptual_reports peut ne pas exister sur vieilles bases,
            # on tente d'assurer leur creation via le store si dispo.
            try:  # noqa: SIM105 - contextlib.suppress ferait perdre la justification du catch
                self._ensure_tables("perceptual_reports")  # type: ignore[attr-defined]
            except Exception:
                pass
            cur = conn.execute(
                f"""
                SELECT COALESCE(LOWER(p.global_tier_v2), LOWER(q.tier)) AS tier_key,
                       COUNT(*) AS cnt
                FROM quality_reports q
                LEFT JOIN perceptual_reports p
                    ON p.run_id = q.run_id AND p.row_id = q.row_id
                WHERE q.run_id IN (
                    SELECT run_id FROM runs
                    WHERE {_NOT_RESCAN_TRACKING_SQL}
                    ORDER BY COALESCE(started_ts, created_ts) DESC LIMIT ?
                )
                GROUP BY tier_key
                """,
                (lim,),
            )
            dist: Dict[str, int] = {}
            for row in cur.fetchall():
                key = row["tier_key"]
                if key is None:
                    key = "unknown"
                dist[str(key)] = int(row["cnt"] or 0)

            total_cur = conn.execute(
                f"""
                SELECT COUNT(*) AS cnt FROM quality_reports
                WHERE run_id IN (
                    SELECT run_id FROM runs
                    WHERE {_NOT_RESCAN_TRACKING_SQL}
                    ORDER BY COALESCE(started_ts, created_ts) DESC LIMIT ?
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
        """Agregats qualite par run (bulk).

        Retourne ``{run_id: {"scored_movies", "score_avg", "premium_count",
        "low_count"}}``. Les runs sans aucun rapport qualite sont ABSENTS du
        dict (``GROUP BY`` ne produit pas de ligne vide) — l'appelant doit donc
        utiliser ``.get(run_id, {})``.

        La docstring precedente annoncait ``{run_id: {tier: count, ...}}``,
        c'est-a-dire une distribution PAR TIER : cette forme n'a JAMAIS ete
        produite ici (c'est ``get_global_tier_distribution`` qui la rend).

        #472 — `premium_count` et `low_count` se calculaient en re-seuillant le
        `score` brut avec 85 et 55 ecrits dans le SQL. Or le tier d'un film n'est
        PAS decide par ces deux nombres : il l'est par les seuils du profil
        qualite actif, que l'utilisateur peut reconfigurer, et le resultat est
        DEJA persiste dans la colonne `tier` au moment du scan. Les deux
        surfaces divergeaient donc dans le meme payload `get_global_stats` :
        `tier_distribution` (qui agrege `LOWER(q.tier)`, cf.
        `get_global_tier_distribution` plus haut) et `summary.premium_pct` (qui
        agregeait le score) ne parlaient pas du meme decoupage.

        Le 85 n'etait meme plus le seuil d'aucun tier : c'etait le seuil
        Platinum d'AVANT la recalibration v1.5.7, qui a aligne tous les profils
        sur 70/66/55/40 (cf. `domain/tiers_helpers.DEFAULT_TIER_THRESHOLDS`).
        Un film Platinum a 78/100 n'etait pas compte comme premium alors que la
        page Qualite l'affichait Platinum.

        On agrege donc sur le tier persiste, sans redefinir ce que « premium »
        veut dire : c'est toujours le tier le PLUS HAUT (Platinum, et son alias
        historique Premium d'avant la migration 011), pas Platinum+Gold. De
        meme `low_count` reste « sous Silver » = Bronze + Reject, ce qui, avec
        le profil par defaut (silver=55), redonne exactement l'ancien
        `score < 55` — le comptage ne bouge que pour les profils personnalises,
        c'est-a-dire exactement les cas ou il etait faux.
        """
        self._ensure_quality_tables()
        ids = [str(x) for x in (run_ids or []) if str(x).strip()]
        if not ids:
            return {}
        # Ordre des parametres = ordre d'APPARITION des `?` dans le SQL.
        premium_bands = sorted(PREMIUM_TIERS_LOWER)
        low_bands = sorted(LOW_TIERS_LOWER)
        premium_ph = ",".join("?" for _ in premium_bands)
        low_ph = ",".join("?" for _ in low_bands)
        # Issue #448 : la liste de runs est decoupee en paquets (les bandes de
        # tiers, elles, sont bornees par les constantes du domaine). Le
        # `GROUP BY run_id` rend une ligne par run : l'union des paquets redonne
        # exactement le meme dictionnaire.
        out: Dict[str, Dict[str, Any]] = {}
        with self._managed_conn() as conn:
            for chunk in chunked(ids, SQL_CHUNK):
                placeholders = ",".join("?" for _ in chunk)
                cur = conn.execute(
                    f"""
                    SELECT
                      run_id,
                      COUNT(*) AS scored_movies,
                      AVG(score) AS score_avg,
                      SUM(CASE WHEN LOWER(TRIM(tier)) IN ({premium_ph}) THEN 1 ELSE 0 END) AS premium_count,
                      SUM(CASE WHEN LOWER(TRIM(tier)) IN ({low_ph}) THEN 1 ELSE 0 END) AS low_count
                    FROM quality_reports
                    WHERE run_id IN ({placeholders})
                    GROUP BY run_id
                    """,
                    (*premium_bands, *low_bands, *chunk),
                )
                for row in cur.fetchall():
                    out[str(row["run_id"])] = {
                        "scored_movies": int(row["scored_movies"] or 0),
                        "score_avg": float(row["score_avg"] or 0.0),
                        "premium_count": int(row["premium_count"] or 0),
                        "low_count": int(row["low_count"] or 0),
                    }
        return out
