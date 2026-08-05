"""AnomalyRepository : anomalies detectees pendant scan/quality (issue #85 phase B2).

Migration #85 phase B2 (2026-05-16) : meme pattern que phase B1 ProbeRepository :
- Code metier vit DANS AnomalyRepository
- B8 CLOSE (2026-05, commit 482f3e6) : _AnomalyMixin et l'heritage MRO supprimes
- SQLiteStore expose store.anomaly (plus d'heritage _AnomalyMixin)

Methodes exposees :
    get_anomaly_counts_for_runs, get_anomaly_stats, get_top_anomaly_codes,
    list_anomalies_for_run

ETAT AU 2026-08-03 (nuance N10 de l'ultra-audit) — A LIRE AVANT DE CODER CONTRE
CE REPOSITORY : la table `anomalies` n'a AUCUN producteur. Les 4 methodes
ci-dessus sont en lecture seule, et le depot ne contient pas un seul INSERT vers
cette table hors des tests et de la recopie interne de `021_fk_cascade.sql`.
Constate sur une base de production reelle : `sqlite_sequence` porte la ligne
('anomalies', 0), donc le compteur AUTOINCREMENT n'a jamais avance — la table
n'a pas ete videe, elle n'a jamais recu une insertion. Ces methodes renvoient
donc toujours [] / {} / 0, et le consommateur `dashboard_support` prend
systematiquement sa branche de repli en memoire.
Ce n'est PAS un bug a corriger ici : c'est un arbitrage produit (brancher un
producteur, ou supprimer la table avec ses 3 index, sa migration 021 dediee, ce
repository et ses lecteurs) qui depasse la couche infra. Ne pas "reparer" une
lecture qui n'a rien a lire.
"""

from __future__ import annotations

from typing import Any, Dict, List

from cinesort.infra.db.repositories._base import _BaseRepository
from cinesort.infra.db.repositories._sql import SQL_CHUNK, chunked


class AnomalyRepository(_BaseRepository):
    """Repository pour la table anomalies."""

    def _ensure_anomalies_table(self) -> None:
        self._ensure_schema_group("anomalies")

    def get_anomaly_counts_for_runs(self, run_ids: List[str]) -> Dict[str, int]:
        """Retourne {run_id: nb_anomalies} pour la liste de runs donnee (agregation bulk).

        Issue #448 : decoupe en paquets. Le `GROUP BY run_id` rend une ligne par
        run, donc l'union des paquets redonne exactement le meme dictionnaire.
        """
        self._ensure_anomalies_table()
        ids = [str(x) for x in (run_ids or []) if str(x).strip()]
        if not ids:
            return {}
        out: Dict[str, int] = {}
        with self._managed_conn() as conn:
            for chunk in chunked(ids, SQL_CHUNK):
                placeholders = ",".join("?" for _ in chunk)
                cur = conn.execute(
                    f"""
                    SELECT run_id, COUNT(*) AS cnt
                    FROM anomalies
                    WHERE run_id IN ({placeholders})
                    GROUP BY run_id
                    """,
                    tuple(chunk),
                )
                out.update({str(r["run_id"]): int(r["cnt"]) for r in cur.fetchall()})
        return out

    def get_anomaly_stats(self, *, run_id: str) -> Dict[str, Any]:
        """Retourne {count, max_ts} pour les anomalies de ce run."""
        self._ensure_anomalies_table()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT COUNT(*) AS cnt, MAX(ts) AS max_ts
                FROM anomalies
                WHERE run_id=?
                """,
                (str(run_id),),
            )
            row = cur.fetchone()
        return {
            "count": int((row["cnt"] if row else 0) or 0),
            "max_ts": float((row["max_ts"] if row else 0.0) or 0.0),
        }

    def get_top_anomaly_codes(self, *, limit_runs: int = 20, limit_codes: int = 10) -> List[Dict[str, Any]]:
        """Return most frequent anomaly codes across the last N runs."""
        self._ensure_anomalies_table()
        lr = max(1, int(limit_runs))
        lc = max(1, int(limit_codes))
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT code, COUNT(*) AS cnt, MAX(run_id) AS last_run_id
                FROM anomalies
                WHERE run_id IN (
                    SELECT run_id FROM runs ORDER BY COALESCE(started_ts, created_ts) DESC LIMIT ?
                )
                GROUP BY code
                ORDER BY cnt DESC
                LIMIT ?
                """,
                (lr, lc),
            )
            return [
                {"code": str(r["code"]), "count": int(r["cnt"]), "last_run_id": str(r["last_run_id"])}
                for r in cur.fetchall()
            ]

    def list_anomalies_for_run(self, *, run_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Retourne les anomalies d'un run, triees par severite (ERROR > WARN > INFO) puis ts."""
        self._ensure_anomalies_table()
        lim = max(1, int(limit))
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT id, run_id, row_id, severity, code, message, path, recommended_action, context_json, ts
                FROM anomalies
                WHERE run_id=?
                ORDER BY
                  CASE severity WHEN 'ERROR' THEN 3 WHEN 'WARN' THEN 2 ELSE 1 END DESC,
                  ts DESC
                LIMIT ?
                """,
                (str(run_id), lim),
            )
            rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            # Phase 8 v7.8.0 : utilise helper _decode_row_json existant
            ctx = self._decode_row_json(row, "context_json", default={}, expected_type=dict)
            out.append(
                {
                    "id": int(row["id"]),
                    "run_id": str(row["run_id"]),
                    "row_id": str(row["row_id"]) if row["row_id"] is not None else None,
                    "severity": str(row["severity"]),
                    "code": str(row["code"]),
                    "message": str(row["message"]),
                    "path": str(row["path"]) if row["path"] is not None else "",
                    "recommended_action": (
                        str(row["recommended_action"]) if row["recommended_action"] is not None else ""
                    ),
                    "context": ctx,
                    "ts": float(row["ts"]),
                }
            )
        return out
