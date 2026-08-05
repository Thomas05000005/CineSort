"""ApplyRepository : apply batches + operations + pending moves (issue #85 phase B7).

Migration #85 phase B7 (2026-05-16) : meme pattern que B1-B6 :
- Code metier vit DANS ApplyRepository
- B8 CLOSE (2026-05, commit 482f3e6) : _ApplyMixin et l'heritage MRO supprimes
- SQLiteStore expose store.apply (heritage MRO supprime en B8)

Note specifique B7 : `mark_apply_batch_undo_status` appelle `self.close_apply_batch`
en interne. Dans ApplyRepository, `self.close_apply_batch` est la methode locale
(meme classe) — pas d'indirection.

Methodes exposees :
    insert_apply_batch, append_apply_operation, close_apply_batch,
    get_last_reversible_apply_batch, list_apply_operations,
    mark_apply_operation_undo_status, mark_apply_batch_undo_status,
    list_apply_batches_for_run, get_batch_rows_summary,
    list_apply_operations_by_row, insert_pending_move, delete_pending_move,
    list_pending_moves, count_pending_moves
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from cinesort.infra.db.repositories._base import _BaseRepository


class ApplyBatchStateError(RuntimeError):
    """Levee quand `close_apply_batch` recoit une transition d'etat invalide.

    H14 hotfix2 : avant ce hotfix, `close_apply_batch` faisait un UPDATE
    inconditionnel et autorisait n'importe quelle transition (incluant
    ROLLED_BACK -> DONE), ce qui pouvait faire reapparaitre un batch deja
    annule comme "dernier reversible" via `get_last_reversible_apply_batch`
    et provoquer une perte silencieuse de l'integrite du journal undo.
    """


# H14 : whitelist des transitions autorisees. PENDING peut aller vers
# n'importe quel etat final ; DONE peut uniquement basculer vers les etats
# d'undo (UNDONE_DONE / UNDONE_PARTIAL) consommes par
# `mark_apply_batch_undo_status`. Toute autre transition (notamment
# ROLLED_BACK/FAILED/UNDONE_* -> DONE) est rejetee pour eviter la
# regression de reversibilite decrite par H14.
_ALLOWED_BATCH_TRANSITIONS: Dict[str, frozenset] = {
    "PENDING": frozenset(
        {
            "PENDING",
            "DONE",
            "FAILED",
            "ROLLED_BACK",
            "ROLLED_BACK_BY_ATOMIC",
            "UNDONE_DONE",
            "UNDONE_PARTIAL",
            "ABORTED",
            "ABORTED_HASH_MISMATCH",
        }
    ),
    # Premier undo full ou selectif depuis un batch acheve.
    "DONE": frozenset(
        {
            "UNDONE_DONE",
            "UNDONE_PARTIAL",
        }
    ),
    # Reprise d'un undo selectif partiel : on autorise a re-affiner le
    # statut tant qu'on reste dans la famille UNDONE_*. Tout retour vers
    # DONE/PENDING reste interdit (regression H14).
    "UNDONE_PARTIAL": frozenset(
        {
            "UNDONE_DONE",
            "UNDONE_PARTIAL",
        }
    ),
    # R8-015 (F2-c) : un apply qui a echoue est clos FAILED, PUIS rollback_forward
    # restaure le FS. Si le revert reussit completement, le statut du batch doit
    # refleter cet etat reel -> ROLLED_BACK_BY_ATOMIC (sinon il reste fige a FAILED,
    # impossible de savoir depuis apply_batches.status si le FS est restaure). On
    # n'autorise QUE cette transition depuis FAILED (pas de retour vers DONE/PENDING
    # = pas de reintroduction dans get_last_reversible_apply_batch).
    "FAILED": frozenset(
        {
            "ROLLED_BACK_BY_ATOMIC",
        }
    ),
    # Nuance N06 (ultra-audit 2026-08-03) : les deux statuts poses par le
    # boot-cleanup (cf cinesort/app/apply_batches_reconciliation.py:59-60)
    # n'avaient aucune entree ici. Consequence mesuree : apres un crash
    # mid-apply suivi d'un reboot, un undo selectif restaurait bien les fichiers
    # sur disque, puis `close_apply_batch` levait ApplyBatchStateError
    # ("transition invalide vers 'UNDONE_DONE'") — que
    # `apply_support._finalize_batch_undo_status` ne rattrape pas (il ne catche
    # que sqlite3.Error / OSError) -> HTTP 500 sur une operation REUSSIE, et le
    # statut du batch restait fige sur le libelle du boot-cleanup.
    # On n'ouvre que la famille UNDONE_* : aucun retour vers DONE/PENDING, donc
    # l'invariant H14 (pas de reintroduction dans
    # get_last_reversible_apply_batch) est preserve.
    "COMPLETED_BY_BOOT_CLEANUP": frozenset(
        {
            "UNDONE_DONE",
            "UNDONE_PARTIAL",
        }
    ),
    "ROLLED_BACK_BY_BOOT_CLEANUP": frozenset(
        {
            "UNDONE_DONE",
            "UNDONE_PARTIAL",
        }
    ),
}


class ApplyRepository(_BaseRepository):
    """Repository pour les operations apply (batches + operations + pending moves)."""

    def _ensure_apply_journal_tables(self) -> None:
        self._ensure_schema_group("apply_journal")

    def insert_apply_batch(
        self,
        *,
        run_id: str,
        dry_run: bool,
        quarantine_unapproved: bool,
        status: str = "PENDING",
        summary: Optional[Dict[str, Any]] = None,
        app_version: str = "unknown",
        started_ts: Optional[float] = None,
        batch_id: Optional[str] = None,
    ) -> str:
        self._ensure_apply_journal_tables()
        now = float(started_ts if started_ts is not None else time.time())
        bid = str(batch_id or f"{int(now * 1000)}_{uuid4().hex}")
        payload = json.dumps(summary or {}, ensure_ascii=False, sort_keys=True)
        with self._managed_conn() as conn:
            conn.execute(
                """
                INSERT INTO apply_batches(
                  batch_id, run_id, started_ts, ended_ts, dry_run,
                  quarantine_unapproved, status, summary_json, app_version
                )
                VALUES(?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    bid,
                    str(run_id),
                    now,
                    1 if bool(dry_run) else 0,
                    1 if bool(quarantine_unapproved) else 0,
                    str(status or "PENDING"),
                    payload,
                    str(app_version or "unknown"),
                ),
            )
        return bid

    def append_apply_operation(
        self,
        *,
        batch_id: str,
        op_index: int,
        op_type: str,
        src_path: str,
        dst_path: str,
        reversible: bool,
        ts: Optional[float] = None,
        row_id: Optional[str] = None,
        src_sha1: Optional[str] = None,
        src_size: Optional[int] = None,
    ) -> int:
        """Enregistre une operation apply.

        P1.2 : `src_sha1` et `src_size` sont le fingerprint du fichier deplace
        (calcule avant le move, donc equivalent au fichier present a `dst_path`
        apres apply). Utilises par l'undo pour refuser de deplacer un fichier
        que l'utilisateur aurait remplace manuellement entre apply et undo.
        """
        self._ensure_apply_journal_tables()
        now = float(ts if ts is not None else time.time())
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO apply_operations(
                  batch_id, op_index, op_type, src_path, dst_path, reversible,
                  undo_status, error_message, ts, row_id, src_sha1, src_size
                )
                VALUES(?, ?, ?, ?, ?, ?, 'PENDING', NULL, ?, ?, ?, ?)
                """,
                (
                    str(batch_id),
                    int(op_index),
                    str(op_type or "MOVE"),
                    str(src_path),
                    str(dst_path),
                    1 if bool(reversible) else 0,
                    now,
                    str(row_id) if row_id else None,
                    str(src_sha1) if src_sha1 else None,
                    int(src_size) if src_size is not None else None,
                ),
            )
            return int(cur.lastrowid)

    def close_apply_batch(
        self,
        *,
        batch_id: str,
        status: str,
        summary: Optional[Dict[str, Any]] = None,
        ended_ts: Optional[float] = None,
    ) -> None:
        """Met a jour le statut final + summary d'un batch.

        H14 hotfix2 : la transition d'etat est desormais validee par une
        whitelist (`_ALLOWED_BATCH_TRANSITIONS`). L'UPDATE filtre sur
        `status IN (...)` atomiquement (pas de TOCTOU) pour empecher la
        regression d'un batch deja cloture (ex: ROLLED_BACK -> DONE) qui
        ferait silencieusement reapparaitre un batch dans
        `get_last_reversible_apply_batch`. Si la transition n'est pas
        autorisee ou si le batch est introuvable, on leve
        `ApplyBatchStateError` apres avoir verifie l'etat reel en base
        (pour distinguer "batch absent" d'une "transition invalide").
        """
        self._ensure_apply_journal_tables()
        now = float(ended_ts if ended_ts is not None else time.time())
        payload = json.dumps(summary or {}, ensure_ascii=False, sort_keys=True)
        target_status = str(status)
        with self._managed_conn() as conn:
            # Construire la liste des statuts source autorises pour atteindre
            # `target_status`. Si la cible n'apparait dans AUCUN frozenset
            # autorise, on bloque immediatement.
            allowed_sources = [src for src, targets in _ALLOWED_BATCH_TRANSITIONS.items() if target_status in targets]
            if not allowed_sources:
                # Avant de lever, on lit l'etat reel pour message clair.
                cur = conn.execute(
                    "SELECT status FROM apply_batches WHERE batch_id=?",
                    (str(batch_id),),
                )
                row = cur.fetchone()
                current = row["status"] if row else None
                raise ApplyBatchStateError(
                    f"close_apply_batch: transition invalide vers '{target_status}' "
                    f"(batch_id={batch_id}, etat courant={current!r})"
                )
            placeholders = ",".join("?" for _ in allowed_sources)
            params = [target_status, now, payload, str(batch_id), *allowed_sources]
            cur = conn.execute(
                f"""
                UPDATE apply_batches
                SET status=?, ended_ts=?, summary_json=?
                WHERE batch_id=? AND status IN ({placeholders})
                """,
                params,
            )
            if cur.rowcount == 0:
                # Soit le batch n'existe pas, soit son etat actuel n'autorise
                # pas la transition demandee. On distingue les deux pour le
                # log via une lecture explicite.
                cur2 = conn.execute(
                    "SELECT status FROM apply_batches WHERE batch_id=?",
                    (str(batch_id),),
                )
                row2 = cur2.fetchone()
                current = row2["status"] if row2 else None
                raise ApplyBatchStateError(
                    f"close_apply_batch: transition refusee vers '{target_status}' "
                    f"(batch_id={batch_id}, etat courant={current!r}, "
                    f"sources autorisees={sorted(allowed_sources)})"
                )

    def get_last_reversible_apply_batch(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retourne le dernier batch apply reel (non dry-run) DONE pour ce run, sinon None."""
        self._ensure_apply_journal_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT batch_id, run_id, started_ts, ended_ts, dry_run, quarantine_unapproved, status, summary_json, app_version
                FROM apply_batches
                WHERE run_id=? AND dry_run=0 AND status='DONE'
                ORDER BY started_ts DESC
                LIMIT 1
                """,
                (str(run_id),),
            )
            row = cur.fetchone()
        if not row:
            return None
        summary = self._decode_row_json(row, "summary_json", default={}, expected_type=dict)
        return {
            "batch_id": str(row["batch_id"]),
            "run_id": str(row["run_id"]),
            "started_ts": float(row["started_ts"] or 0.0),
            "ended_ts": float(row["ended_ts"] or 0.0) if row["ended_ts"] is not None else None,
            "dry_run": int(row["dry_run"] or 0),
            "quarantine_unapproved": int(row["quarantine_unapproved"] or 0),
            "status": str(row["status"] or ""),
            "summary": summary,
            "app_version": str(row["app_version"] or ""),
        }

    def get_applied_counts_for_runs(self, run_ids: List[str]) -> Dict[str, int]:
        """{run_id: applied_count} depuis le DERNIER batch reel (non dry-run) DONE de chaque run.

        AUDIT 2026-07-13 (HIGH-7) : source de verite du nombre de films appliques =
        apply_batches.summary_json.applied_count (ecrit par apply_support). Les
        surfaces LECTURE (dashboard runs_history, inspecteur Historique) lisaient
        runs.stats_json.applied_count, une cle JAMAIS ecrite apres un apply ->
        "Appliques 0" partout malgre un apply reussi. Helper BULK (miroir de
        run.get_error_counts_for_runs) pour eviter un N+1 sur la liste des runs.
        """
        ids = [str(x) for x in (run_ids or []) if str(x).strip()]
        if not ids:
            return {}
        self._ensure_apply_journal_tables()
        placeholders = ",".join("?" for _ in ids)
        out: Dict[str, int] = {}
        with self._managed_conn() as conn:
            cur = conn.execute(
                f"""
                SELECT run_id, summary_json, started_ts
                FROM apply_batches
                WHERE run_id IN ({placeholders}) AND dry_run=0 AND status='DONE'
                ORDER BY started_ts DESC
                """,
                tuple(ids),
            )
            for row in cur.fetchall():
                rid = str(row["run_id"])
                if rid in out:
                    continue  # ORDER BY started_ts DESC -> 1er vu = dernier batch DONE
                summary = self._decode_row_json(row, "summary_json", default={}, expected_type=dict)
                out[rid] = int(summary.get("applied_count") or 0)
        return out

    def list_apply_operations(self, *, batch_id: str) -> List[Dict[str, Any]]:
        """Retourne les operations apply du batch dans l'ordre d'execution (op_index croissant)."""
        self._ensure_apply_journal_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT id, batch_id, op_index, op_type, src_path, dst_path, reversible,
                       undo_status, error_message, ts, row_id, src_sha1, src_size
                FROM apply_operations
                WHERE batch_id=?
                ORDER BY op_index ASC, id ASC
                """,
                (str(batch_id),),
            )
            rows = cur.fetchall()
        return [
            {
                "id": int(r["id"]),
                "batch_id": str(r["batch_id"]),
                "op_index": int(r["op_index"]),
                "op_type": str(r["op_type"]),
                "src_path": str(r["src_path"]),
                "dst_path": str(r["dst_path"]),
                "reversible": int(r["reversible"] or 0),
                "undo_status": str(r["undo_status"] or "PENDING"),
                "error_message": str(r["error_message"] or ""),
                "ts": float(r["ts"] or 0.0),
                "row_id": str(r["row_id"] or ""),
                "src_sha1": str(r["src_sha1"] or "") or None,
                "src_size": int(r["src_size"]) if r["src_size"] is not None else None,
            }
            for r in rows
        ]

    def mark_apply_operation_undo_status(
        self,
        *,
        op_id: int,
        undo_status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Met a jour le statut undo d'une operation (PENDING / DONE / FAILED / SKIPPED)."""
        self._ensure_apply_journal_tables()
        with self._managed_conn() as conn:
            conn.execute(
                """
                UPDATE apply_operations
                SET undo_status=?, error_message=?
                WHERE id=?
                """,
                (str(undo_status or "PENDING"), str(error_message or "") or None, int(op_id)),
            )

    def mark_apply_batch_undo_status(
        self,
        *,
        batch_id: str,
        status: str,
        summary: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Clot le batch cote undo en mettant a jour son statut + summary via `close_apply_batch`."""
        # self.close_apply_batch est la methode locale (meme classe)
        self.close_apply_batch(
            batch_id=batch_id,
            status=str(status),
            summary=summary or {},
            ended_ts=time.time(),
        )

    # --- Undo v5: per-row methods ---

    def list_apply_batches_for_run(self, *, run_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Return all batches for a run (not just the last DONE), most recent first.

        R2 (revue round 2) : `limit <= 0` = AUCUNE borne (tous les batches du run,
        deja fini). Utilise par le balayage d'integrite des MKDIR en undo, ou
        borner (ORDER BY started_ts DESC LIMIT 1000) jetait les PLUS ANCIENS
        batches -> un dossier saga cree par un vieux batch restait orphelin.
        """
        self._ensure_apply_journal_tables()
        lim = int(limit)
        base_sql = """
                SELECT batch_id, run_id, started_ts, ended_ts, dry_run,
                       quarantine_unapproved, status, summary_json, app_version
                FROM apply_batches
                WHERE run_id=?
                ORDER BY started_ts DESC
        """
        with self._managed_conn() as conn:
            if lim <= 0:
                cur = conn.execute(base_sql, (str(run_id),))
            else:
                cur = conn.execute(base_sql + " LIMIT ?", (str(run_id), lim))
            rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            summary = self._decode_row_json(row, "summary_json", default={}, expected_type=dict)
            out.append(
                {
                    "batch_id": str(row["batch_id"]),
                    "run_id": str(row["run_id"]),
                    "started_ts": float(row["started_ts"] or 0.0),
                    "ended_ts": float(row["ended_ts"] or 0.0) if row["ended_ts"] is not None else None,
                    "dry_run": int(row["dry_run"] or 0),
                    "quarantine_unapproved": int(row["quarantine_unapproved"] or 0),
                    "status": str(row["status"] or ""),
                    "summary": summary,
                    "app_version": str(row["app_version"] or ""),
                }
            )
        return out

    def get_batch_rows_summary(self, *, batch_id: str) -> List[Dict[str, Any]]:
        """Per-row summary of a batch: for each row_id, count total/reversible/undone/pending ops."""
        self._ensure_apply_journal_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT
                  COALESCE(row_id, '__legacy__') AS row_id,
                  COUNT(*) AS total_ops,
                  SUM(CASE WHEN reversible = 1 THEN 1 ELSE 0 END) AS reversible_ops,
                  SUM(CASE WHEN undo_status = 'DONE' THEN 1 ELSE 0 END) AS undone_ops,
                  SUM(CASE WHEN undo_status = 'PENDING' THEN 1 ELSE 0 END) AS pending_ops,
                  SUM(CASE WHEN undo_status = 'FAILED' THEN 1 ELSE 0 END) AS failed_ops,
                  SUM(CASE WHEN undo_status = 'SKIPPED' THEN 1 ELSE 0 END) AS skipped_ops
                FROM apply_operations
                WHERE batch_id = ?
                GROUP BY COALESCE(row_id, '__legacy__')
                ORDER BY MIN(op_index)
                """,
                (str(batch_id),),
            )
            return [
                {
                    "row_id": str(r["row_id"]),
                    "total_ops": int(r["total_ops"] or 0),
                    "reversible_ops": int(r["reversible_ops"] or 0),
                    "undone_ops": int(r["undone_ops"] or 0),
                    "pending_ops": int(r["pending_ops"] or 0),
                    "failed_ops": int(r["failed_ops"] or 0),
                    "skipped_ops": int(r["skipped_ops"] or 0),
                }
                for r in cur.fetchall()
            ]

    def list_apply_operations_by_row(self, *, batch_id: str, row_id: str) -> List[Dict[str, Any]]:
        """Operations for a specific row_id within a batch."""
        self._ensure_apply_journal_tables()
        effective_row_id = None if row_id == "__legacy__" else str(row_id)
        with self._managed_conn() as conn:
            if effective_row_id is None:
                cur = conn.execute(
                    """
                    SELECT id, batch_id, op_index, op_type, src_path, dst_path,
                           reversible, undo_status, error_message, ts, row_id,
                           src_sha1, src_size
                    FROM apply_operations
                    WHERE batch_id=? AND row_id IS NULL
                    ORDER BY op_index ASC, id ASC
                    """,
                    (str(batch_id),),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, batch_id, op_index, op_type, src_path, dst_path,
                           reversible, undo_status, error_message, ts, row_id,
                           src_sha1, src_size
                    FROM apply_operations
                    WHERE batch_id=? AND row_id=?
                    ORDER BY op_index ASC, id ASC
                    """,
                    (str(batch_id), effective_row_id),
                )
            rows = cur.fetchall()
        return [
            {
                "id": int(r["id"]),
                "batch_id": str(r["batch_id"]),
                "op_index": int(r["op_index"]),
                "op_type": str(r["op_type"]),
                "src_path": str(r["src_path"]),
                "dst_path": str(r["dst_path"]),
                "reversible": int(r["reversible"] or 0),
                "undo_status": str(r["undo_status"] or "PENDING"),
                "error_message": str(r["error_message"] or ""),
                "ts": float(r["ts"] or 0.0),
                "row_id": str(r["row_id"] or ""),
                "src_sha1": str(r["src_sha1"] or "") or None,
                "src_size": int(r["src_size"]) if r["src_size"] is not None else None,
            }
            for r in rows
        ]

    # =====================================================================
    # CR-1 audit QA 20260429 : journal write-ahead pour atomicite shutil.move
    # =====================================================================
    # Pattern : INSERT pending AVANT shutil.move, DELETE pending APRES move
    # reussi. Si l'app crashe entre les deux, l'entree reste pour
    # reconciliation au prochain boot (cf cinesort.app.move_reconciliation).

    def _ensure_apply_pending_tables(self) -> None:
        self._ensure_schema_group("apply_pending")

    def insert_pending_move(
        self,
        *,
        op_type: str,
        src_path: str,
        dst_path: str,
        batch_id: Optional[str] = None,
        src_sha1: Optional[str] = None,
        src_size: Optional[int] = None,
        row_id: Optional[str] = None,
        ts: Optional[float] = None,
    ) -> int:
        """Enregistre un move en attente. Retourne le pending_id (lastrowid)."""
        self._ensure_apply_pending_tables()
        now = float(ts if ts is not None else time.time())
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO apply_pending_moves(
                  batch_id, op_type, src_path, dst_path,
                  src_sha1, src_size, row_id, ts
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(batch_id) if batch_id else None,
                    str(op_type or "MOVE_FILE"),
                    str(src_path),
                    str(dst_path),
                    str(src_sha1) if src_sha1 else None,
                    int(src_size) if src_size is not None else None,
                    str(row_id) if row_id else None,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def delete_pending_move(self, pending_id: int) -> None:
        """Supprime une entree pending apres move reussi. Tolere id inconnu."""
        self._ensure_apply_pending_tables()
        with self._managed_conn() as conn:
            conn.execute(
                "DELETE FROM apply_pending_moves WHERE id=?",
                (int(pending_id),),
            )

    def list_pending_moves(self, *, batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retourne les pending moves orphelins.

        A appeler au boot pour reconciliation : tout ce qui est en table est
        considere comme orphelin (un move qui s'est commit ou rollback proprement
        a deja ete supprime via delete_pending_move).
        """
        self._ensure_apply_pending_tables()
        with self._managed_conn() as conn:
            if batch_id is None:
                cur = conn.execute(
                    """
                    SELECT id, batch_id, op_type, src_path, dst_path,
                           src_sha1, src_size, row_id, ts
                    FROM apply_pending_moves
                    ORDER BY ts ASC, id ASC
                    """
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, batch_id, op_type, src_path, dst_path,
                           src_sha1, src_size, row_id, ts
                    FROM apply_pending_moves
                    WHERE batch_id=?
                    ORDER BY ts ASC, id ASC
                    """,
                    (str(batch_id),),
                )
            rows = cur.fetchall()
        return [
            {
                "id": int(r["id"]),
                "batch_id": str(r["batch_id"] or "") or None,
                "op_type": str(r["op_type"]),
                "src_path": str(r["src_path"]),
                "dst_path": str(r["dst_path"]),
                "src_sha1": str(r["src_sha1"] or "") or None,
                "src_size": int(r["src_size"]) if r["src_size"] is not None else None,
                "row_id": str(r["row_id"] or "") or None,
                "ts": float(r["ts"] or 0.0),
            }
            for r in rows
        ]

    def count_pending_moves(self) -> int:
        """Nombre de pending moves orphelins (utile pour metrics et health)."""
        self._ensure_apply_pending_tables()
        with self._managed_conn() as conn:
            cur = conn.execute("SELECT COUNT(*) AS n FROM apply_pending_moves")
            row = cur.fetchone()
        return int(row["n"]) if row else 0

    # =====================================================================
    # Vague P / VP-A (migration 029) : apply atomique forward rollback (opt-in)
    # =====================================================================
    # Memo `feedback_cinesort_design` + plan VP-A : le mode atomique est OPT-IN
    # strict (flag default False). Le rollback_status est SEPARE de la chaine
    # undo classique (`undo_status` / `mark_apply_batch_undo_status`). Aucun
    # impact sur `get_last_reversible_apply_batch` qui reste autorite undo.
    #
    # Valeurs rollback_status :
    #   'NONE' (default), 'IN_PROGRESS', 'ROLLED_BACK_BY_ATOMIC',
    #   'ROLLBACK_FAILED', 'ROLLBACK_PARTIAL'

    def _ensure_apply_atomic_tables(self) -> None:
        self._ensure_schema_group("apply_atomic")

    def upsert_atomic_mode(self, batch_id: str, enabled: bool) -> None:
        """Enregistre le mode atomique pour un batch (insert ou update).

        Appele tres tot dans `_execute_apply` apres `insert_apply_batch` pour
        memoriser le flag opt-in. Idempotent : un re-appel met juste a jour
        `atomic_enabled` sans toucher au `rollback_status` deja stocke.
        """
        self._ensure_apply_atomic_tables()
        with self._managed_conn() as conn:
            conn.execute(
                """
                INSERT INTO apply_batch_modes(
                  batch_id, atomic_enabled, rollback_status, rolled_back_at
                )
                VALUES(?, ?, 'NONE', NULL)
                ON CONFLICT(batch_id) DO UPDATE SET
                    atomic_enabled = excluded.atomic_enabled
                """,
                (str(batch_id), 1 if bool(enabled) else 0),
            )

    def mark_rollback_status(
        self,
        batch_id: str,
        status: str,
        *,
        rolled_back_at: Optional[str] = None,
    ) -> None:
        """Met a jour `rollback_status` d'un batch (et eventuellement le ts).

        Tolerant si le batch n'existe pas dans `apply_batch_modes` (cas
        legitime : batch lance avant migration 029 ou mode atomique jamais
        active). Dans ce cas, on cree une ligne avec atomic_enabled=0 pour
        ne pas perdre la trace de l'echec de rollback (audit).
        """
        self._ensure_apply_atomic_tables()
        ts = str(rolled_back_at) if rolled_back_at is not None else None
        if ts is None and str(status) in (
            "IN_PROGRESS",
            "ROLLED_BACK_BY_ATOMIC",
            "ROLLBACK_FAILED",
            "ROLLBACK_PARTIAL",
        ):
            # auto-fill timestamp ISO-like pour audit
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._managed_conn() as conn:
            conn.execute(
                """
                INSERT INTO apply_batch_modes(
                  batch_id, atomic_enabled, rollback_status, rolled_back_at
                )
                VALUES(?, 0, ?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    rollback_status = excluded.rollback_status,
                    rolled_back_at  = COALESCE(excluded.rolled_back_at, apply_batch_modes.rolled_back_at)
                """,
                (str(batch_id), str(status or "NONE"), ts),
            )

    def get_atomic_mode(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Retourne {atomic_enabled, rollback_status, rolled_back_at} ou None."""
        self._ensure_apply_atomic_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT batch_id, atomic_enabled, rollback_status, rolled_back_at
                FROM apply_batch_modes
                WHERE batch_id=?
                """,
                (str(batch_id),),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "batch_id": str(row["batch_id"]),
            "atomic_enabled": int(row["atomic_enabled"] or 0),
            "rollback_status": str(row["rollback_status"] or "NONE"),
            "rolled_back_at": str(row["rolled_back_at"]) if row["rolled_back_at"] else None,
        }

    def list_atomic_modes_for_run(self, *, run_id: str) -> Dict[str, Dict[str, Any]]:
        """Liste tous les modes atomiques pour les batches d'un run (UI badge).

        Retourne un dict {batch_id: {atomic_enabled, rollback_status, rolled_back_at}}.
        Utilise par list_apply_history pour annoter chaque batch avec le mode.
        """
        self._ensure_apply_atomic_tables()
        self._ensure_apply_journal_tables()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT m.batch_id, m.atomic_enabled, m.rollback_status, m.rolled_back_at
                FROM apply_batch_modes m
                INNER JOIN apply_batches b ON b.batch_id = m.batch_id
                WHERE b.run_id = ?
                """,
                (str(run_id),),
            )
            rows = cur.fetchall()
        return {
            str(r["batch_id"]): {
                "atomic_enabled": int(r["atomic_enabled"] or 0),
                "rollback_status": str(r["rollback_status"] or "NONE"),
                "rolled_back_at": str(r["rolled_back_at"]) if r["rolled_back_at"] else None,
            }
            for r in rows
        }

    # =====================================================================
    # Phase 4 doublons (migration 023, cf docs/internal/design/refonte_2026_05_17/screens/01-doublons.md)
    # =====================================================================
    # Decisions utilisateur "garder ce winner" sur un groupe de doublons.
    # A l'apply, les loser_row_ids seront deplaces vers
    # <root>/_review/_duplicates_user_decided/.

    def _ensure_duplicate_decisions_table(self) -> None:
        self._ensure_schema_group("duplicate_decisions")

    def upsert_duplicate_decision(
        self,
        *,
        run_id: str,
        group_key: str,
        winner_row_id: str,
        loser_row_ids: List[str],
        decided_ts: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persiste la decision utilisateur pour un groupe de doublons.

        (run_id, group_key) est PK : upsert sur conflict pour permettre
        a l'utilisateur de changer d'avis.

        Retourne le dict serialise (winner + losers + ts).
        """
        self._ensure_duplicate_decisions_table()
        now = float(decided_ts if decided_ts is not None else time.time())
        losers_json = json.dumps([str(x) for x in (loser_row_ids or [])], ensure_ascii=False)
        with self._managed_conn() as conn:
            conn.execute(
                """
                INSERT INTO duplicate_decisions(
                  run_id, group_key, winner_row_id, loser_row_ids, decided_ts, notes
                )
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, group_key) DO UPDATE SET
                    winner_row_id = excluded.winner_row_id,
                    loser_row_ids = excluded.loser_row_ids,
                    decided_ts    = excluded.decided_ts,
                    notes         = excluded.notes
                """,
                (
                    str(run_id),
                    str(group_key),
                    str(winner_row_id),
                    losers_json,
                    now,
                    str(notes) if notes else None,
                ),
            )
        return {
            "run_id": str(run_id),
            "group_key": str(group_key),
            "winner_row_id": str(winner_row_id),
            "loser_row_ids": [str(x) for x in (loser_row_ids or [])],
            "decided_ts": now,
            "notes": notes,
        }

    def get_duplicate_decision(self, *, run_id: str, group_key: str) -> Optional[Dict[str, Any]]:
        """Retourne la decision persistee pour ce groupe, ou None si aucune."""
        self._ensure_duplicate_decisions_table()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT run_id, group_key, winner_row_id, loser_row_ids, decided_ts, notes
                FROM duplicate_decisions
                WHERE run_id=? AND group_key=?
                """,
                (str(run_id), str(group_key)),
            )
            row = cur.fetchone()
        if not row:
            return None
        try:
            losers = json.loads(row["loser_row_ids"]) if row["loser_row_ids"] else []
            if not isinstance(losers, list):
                losers = []
        except (TypeError, ValueError):
            losers = []
        return {
            "run_id": str(row["run_id"]),
            "group_key": str(row["group_key"]),
            "winner_row_id": str(row["winner_row_id"]),
            "loser_row_ids": [str(x) for x in losers],
            "decided_ts": float(row["decided_ts"] or 0.0),
            "notes": str(row["notes"]) if row["notes"] else None,
        }

    def list_duplicate_decisions(self, *, run_id: str) -> List[Dict[str, Any]]:
        """Liste toutes les decisions doublons d'un run (recent en premier)."""
        self._ensure_duplicate_decisions_table()
        with self._managed_conn() as conn:
            cur = conn.execute(
                """
                SELECT run_id, group_key, winner_row_id, loser_row_ids, decided_ts, notes
                FROM duplicate_decisions
                WHERE run_id=?
                ORDER BY decided_ts DESC
                """,
                (str(run_id),),
            )
            rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            try:
                losers = json.loads(row["loser_row_ids"]) if row["loser_row_ids"] else []
                if not isinstance(losers, list):
                    losers = []
            except (TypeError, ValueError):
                losers = []
            out.append(
                {
                    "run_id": str(row["run_id"]),
                    "group_key": str(row["group_key"]),
                    "winner_row_id": str(row["winner_row_id"]),
                    "loser_row_ids": [str(x) for x in losers],
                    "decided_ts": float(row["decided_ts"] or 0.0),
                    "notes": str(row["notes"]) if row["notes"] else None,
                }
            )
        return out
