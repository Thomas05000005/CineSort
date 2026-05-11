"""Mixin DB pour les rapports d'analyse perceptuelle."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional


_PERCEPTUAL_TABLES = ("perceptual_reports",)


class _PerceptualMixin:
    """Persistence des rapports perceptuels dans SQLite."""

    def _ensure_perceptual_tables(self) -> None:
        self._ensure_tables(*_PERCEPTUAL_TABLES)

    def upsert_perceptual_report(
        self,
        *,
        run_id: str,
        row_id: str,
        visual_score: int,
        audio_score: int,
        global_score: int,
        global_tier: str,
        metrics: Dict[str, Any],
        settings_used: Dict[str, Any],
        audio_fingerprint: Optional[str] = None,
        spectral_cutoff_hz: Optional[float] = None,
        lossy_verdict: Optional[str] = None,
        ssim_self_ref: Optional[float] = None,
        upscale_verdict: Optional[str] = None,
        global_score_v2: Optional[float] = None,
        global_tier_v2: Optional[str] = None,
        global_score_v2_payload: Optional[Dict[str, Any]] = None,
        ts: Optional[float] = None,
    ) -> None:
        """Insere ou met a jour un rapport perceptuel.

        §3 v7.5.0 : `audio_fingerprint` (base64) persiste dans la colonne dediee.
        §9 v7.5.0 : `spectral_cutoff_hz` + `lossy_verdict` (detection lossy).
        §13 v7.5.0 : `ssim_self_ref` + `upscale_verdict` (detection fake 4K).
        §16 v7.5.0 : `global_score_v2` + `global_tier_v2` + `global_score_v2_json`
                     (score composite V2 avec sous-scores, ajustements, warnings).
        """
        now = float(ts if ts is not None else time.time())
        metrics_payload = json.dumps(dict(metrics or {}), ensure_ascii=False, sort_keys=True)
        settings_payload = json.dumps(dict(settings_used or {}), ensure_ascii=False, sort_keys=True)
        fp_value = str(audio_fingerprint) if audio_fingerprint else None
        cutoff_value = float(spectral_cutoff_hz) if spectral_cutoff_hz is not None else None
        verdict_value = str(lossy_verdict) if lossy_verdict else None
        ssim_value = float(ssim_self_ref) if ssim_self_ref is not None else None
        upscale_value = str(upscale_verdict) if upscale_verdict else None
        gv2_score = float(global_score_v2) if global_score_v2 is not None else None
        gv2_tier = str(global_tier_v2) if global_tier_v2 else None
        gv2_json = (
            json.dumps(dict(global_score_v2_payload), ensure_ascii=False, sort_keys=True)
            if global_score_v2_payload
            else None
        )

        def op(conn: Any) -> None:
            conn.execute(
                """
                INSERT INTO perceptual_reports(
                  run_id, row_id, visual_score, audio_score, global_score,
                  global_tier, metrics_json, settings_json, ts,
                  audio_fingerprint, spectral_cutoff_hz, lossy_verdict,
                  ssim_self_ref, upscale_verdict,
                  global_score_v2, global_tier_v2, global_score_v2_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, row_id)
                DO UPDATE SET
                  visual_score=excluded.visual_score,
                  audio_score=excluded.audio_score,
                  global_score=excluded.global_score,
                  global_tier=excluded.global_tier,
                  metrics_json=excluded.metrics_json,
                  settings_json=excluded.settings_json,
                  ts=excluded.ts,
                  audio_fingerprint=excluded.audio_fingerprint,
                  spectral_cutoff_hz=excluded.spectral_cutoff_hz,
                  lossy_verdict=excluded.lossy_verdict,
                  ssim_self_ref=excluded.ssim_self_ref,
                  upscale_verdict=excluded.upscale_verdict,
                  global_score_v2=excluded.global_score_v2,
                  global_tier_v2=excluded.global_tier_v2,
                  global_score_v2_json=excluded.global_score_v2_json
                """,
                (
                    str(run_id),
                    str(row_id),
                    int(visual_score),
                    int(audio_score),
                    int(global_score),
                    str(global_tier),
                    metrics_payload,
                    settings_payload,
                    now,
                    fp_value,
                    cutoff_value,
                    verdict_value,
                    ssim_value,
                    upscale_value,
                    gv2_score,
                    gv2_tier,
                    gv2_json,
                ),
            )

        self._ensure_perceptual_tables()
        with self._managed_conn() as conn, conn:
            op(conn)

    def get_perceptual_report(self, *, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        """Recupere un rapport perceptuel pour un film."""
        self._ensure_perceptual_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT run_id, row_id, visual_score, audio_score, global_score,
                       global_tier, metrics_json, settings_json, ts, audio_fingerprint,
                       spectral_cutoff_hz, lossy_verdict, ssim_self_ref, upscale_verdict,
                       global_score_v2, global_tier_v2, global_score_v2_json
                FROM perceptual_reports
                WHERE run_id=? AND row_id=?
                LIMIT 1
                """,
                (str(run_id), str(row_id)),
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._parse_perceptual_row(row)

    def list_perceptual_reports(self, *, run_id: str) -> List[Dict[str, Any]]:
        """Liste tous les rapports perceptuels d'un run."""
        self._ensure_perceptual_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT run_id, row_id, visual_score, audio_score, global_score,
                       global_tier, metrics_json, settings_json, ts, audio_fingerprint,
                       spectral_cutoff_hz, lossy_verdict, ssim_self_ref, upscale_verdict,
                       global_score_v2, global_tier_v2, global_score_v2_json
                FROM perceptual_reports
                WHERE run_id=?
                ORDER BY global_score ASC, ts ASC
                """,
                (str(run_id),),
            )
            return [self._parse_perceptual_row(row) for row in cur.fetchall()]

    # §16 v7.6.0 Vague 2 : agregats V2 pour la Home overview-first ----------

    def get_global_tier_v2_distribution(self, *, run_ids: List[str]) -> Dict[str, int]:
        """Compte les films par tier V2 sur la liste de run_ids.

        Renvoie {"platinum": N, "gold": N, ..., "reject": N, "unknown": N_non_scored}.
        Les rows sans global_tier_v2 (pre-v7.5) sont comptees comme "unknown".
        """
        if not run_ids:
            return {}
        self._ensure_perceptual_tables()
        placeholders = ",".join("?" * len(run_ids))
        result: Dict[str, int] = {
            "platinum": 0,
            "gold": 0,
            "silver": 0,
            "bronze": 0,
            "reject": 0,
            "unknown": 0,
        }
        with self._managed_conn() as conn:
            cur = conn.execute(
                f"""
                SELECT global_tier_v2, COUNT(*) as n
                FROM perceptual_reports
                WHERE run_id IN ({placeholders})
                GROUP BY global_tier_v2
                """,
                tuple(run_ids),
            )
            for row in cur.fetchall():
                tier = str(row[0] or "").strip().lower() or "unknown"
                if tier in result:
                    result[tier] += int(row[1])
                else:
                    result["unknown"] += int(row[1])
        return result

    def get_global_score_v2_trend(self, *, since_ts: float, until_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        """Aggregation du score V2 moyen par jour entre since_ts et until_ts (inclus).

        Renvoie [{"date": "YYYY-MM-DD", "avg_score": float, "count": int}, ...]
        trie par date croissante. Jours sans donnee absents du resultat.
        """
        self._ensure_perceptual_tables()
        until_value = float(until_ts) if until_ts is not None else time.time() + 86400.0
        since_value = float(since_ts)

        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT date(ts, 'unixepoch', 'localtime') as d,
                       AVG(global_score_v2) as avg_score,
                       COUNT(*) as n
                FROM perceptual_reports
                WHERE global_score_v2 IS NOT NULL
                  AND ts >= ? AND ts <= ?
                GROUP BY d
                ORDER BY d ASC
                """,
                (since_value, until_value),
            )
            out: List[Dict[str, Any]] = []
            for row in cur.fetchall():
                d = row[0]
                if d is None:
                    continue
                out.append(
                    {
                        "date": str(d),
                        "avg_score": round(float(row[1] or 0), 1),
                        "count": int(row[2] or 0),
                    }
                )
            return out

    def count_v2_tier_since(self, *, tier: str, since_ts: float) -> int:
        """Compte les films d'un tier V2 donne ajoutes depuis since_ts.

        Utilise pour les insights actifs ("N nouveaux Reject ce mois", etc.).
        """
        self._ensure_perceptual_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT COUNT(*) FROM perceptual_reports
                WHERE global_tier_v2 = ? AND ts >= ?
                """,
                (str(tier).lower(), float(since_ts)),
            )
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0

    def count_v2_warnings_flag(self, *, flag: str, run_ids: List[str]) -> int:
        """Compte les rows dont le global_score_v2_json contient un warning matching `flag`.

        Scan naif via LIKE sur le JSON ; suffit pour 1000-10000 rows.
        """
        if not run_ids:
            return 0
        self._ensure_perceptual_tables()
        placeholders = ",".join("?" * len(run_ids))
        pattern = f"%{flag}%"
        with self._managed_conn() as conn:
            cur = conn.execute(
                f"""
                SELECT COUNT(*) FROM perceptual_reports
                WHERE run_id IN ({placeholders})
                  AND global_score_v2_json LIKE ?
                """,
                (*run_ids, pattern),
            )
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0

    def _parse_perceptual_row(self, row: Any) -> Dict[str, Any]:
        """Parse une ligne de perceptual_reports."""
        # Phase 8 v7.8.0 : utilise helper _decode_row_json (centralise gestion JSON corrompu)
        metrics = self._decode_row_json(row, "metrics_json", default={}, expected_type=dict)
        settings_used = self._decode_row_json(row, "settings_json", default={}, expected_type=dict)
        # Colonnes optionnelles pour retro-compat (migrations 015/016)
        try:
            fp_raw = row["audio_fingerprint"]
        except (IndexError, KeyError):
            fp_raw = None
        try:
            cutoff_raw = row["spectral_cutoff_hz"]
        except (IndexError, KeyError):
            cutoff_raw = None
        try:
            verdict_raw = row["lossy_verdict"]
        except (IndexError, KeyError):
            verdict_raw = None
        try:
            ssim_raw = row["ssim_self_ref"]
        except (IndexError, KeyError):
            ssim_raw = None
        try:
            upscale_raw = row["upscale_verdict"]
        except (IndexError, KeyError):
            upscale_raw = None
        try:
            gv2_score_raw = row["global_score_v2"]
        except (IndexError, KeyError):
            gv2_score_raw = None
        try:
            gv2_tier_raw = row["global_tier_v2"]
        except (IndexError, KeyError):
            gv2_tier_raw = None
        try:
            gv2_json_raw = row["global_score_v2_json"]
        except (IndexError, KeyError):
            gv2_json_raw = None
        gv2_payload: Optional[Dict[str, Any]] = None
        if gv2_json_raw:
            try:
                parsed_v2 = json.loads(str(gv2_json_raw))
                gv2_payload = parsed_v2 if isinstance(parsed_v2, dict) else None
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        return {
            "run_id": str(row["run_id"]),
            "row_id": str(row["row_id"]),
            "visual_score": int(row["visual_score"]),
            "audio_score": int(row["audio_score"]),
            "global_score": int(row["global_score"]),
            "global_tier": str(row["global_tier"]),
            "metrics": metrics,
            "settings_used": settings_used,
            "ts": float(row["ts"]),
            "audio_fingerprint": str(fp_raw) if fp_raw else None,
            "spectral_cutoff_hz": float(cutoff_raw) if cutoff_raw is not None else None,
            "lossy_verdict": str(verdict_raw) if verdict_raw else None,
            "ssim_self_ref": float(ssim_raw) if ssim_raw is not None else None,
            "upscale_verdict": str(upscale_raw) if upscale_raw else None,
            "global_score_v2": float(gv2_score_raw) if gv2_score_raw is not None else None,
            "global_tier_v2": str(gv2_tier_raw) if gv2_tier_raw else None,
            "global_score_v2_payload": gv2_payload,
        }
