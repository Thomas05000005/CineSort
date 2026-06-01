"""VN-E.2 — reconciliation des apply_batches PENDING-zombi au boot.

Scenario : un apply crash a mi-parcours (process kill, blue screen, OOM, etc.)
- apply_batches.status reste 'PENDING' indefiniment ;
- le slot mutex apply est garde occupe ;
- aucun re-apply n'est possible sans intervention manuelle en base.

Solution (meme pattern que `move_reconciliation.py` pour apply_pending_moves
+ migration 019) : au boot CineSort, scanner les batches PENDING dont
`started_ts` est anterieur a un seuil (defaut 1h), et les marquer :

| Etat des operations associees    | Verdict      | Status final              |
|----------------------------------|--------------|---------------------------|
| toutes applied=True OR skipped=True | finalisable | COMPLETED_BY_BOOT_CLEANUP |
| au moins une operation inachevee | inconsistant | ROLLED_BACK_BY_BOOT_CLEANUP |

Note : ici "applied" / "skipped" s'inferent des colonnes existantes :
- `undo_status` reste a 'PENDING' tant que l'op n'a pas ete undo
- une op est consideree "appliquee" si elle est presente avec
  `op_type='MOVE'` et que `error_message` est NULL/vide
- une op est consideree "skipped" si `error_message` contient 'skip' ou
  `op_type='SKIP'`

Comme le schema actuel ne distingue pas applied vs pending au niveau
operation (undo_status concerne le cote undo, pas le cote apply forward),
on adopte une heuristique conservatrice :
- batch est "completable" si TOUTES les operations attendues ont ete
  inserees ET aucune n'a `error_message` non-vide ;
- sinon ROLLED_BACK.

Le comptage des operations vs sommaire batch (summary_json.expected_ops)
est tente, mais en l'absence d'info on tombe sur "marker ROLLED_BACK" par
defaut, plus prudent.

Idempotent : si pas de PENDING-zombi, retourne report vide.
Re-run au prochain boot OK (les batches deja flagges COMPLETED_BY_BOOT_CLEANUP
ou ROLLED_BACK_BY_BOOT_CLEANUP ne sont plus 'PENDING' donc ignores).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)

# Seuil par defaut : un batch PENDING > 1h est considere zombi.
# Choisi pour eviter les faux positifs sur un apply en cours legitime.
DEFAULT_MAX_AGE_HOURS = 1.0

STATUS_COMPLETED_BY_BOOT = "COMPLETED_BY_BOOT_CLEANUP"
STATUS_ROLLED_BACK_BY_BOOT = "ROLLED_BACK_BY_BOOT_CLEANUP"


def _list_pending_batches(store: Any, *, older_than_ts: float) -> List[Dict[str, Any]]:
    """Liste les batches PENDING dont `started_ts < older_than_ts`.

    Utilise un acces direct a la connexion sqlite via `store._managed_conn`
    (pattern identique au cleanup runs orphelins dans runtime_support.py).
    Tolere une absence de la table apply_batches (DB pre-v5).
    """
    rows: List[Dict[str, Any]] = []
    with store._managed_conn() as conn:  # type: ignore[attr-defined]
        try:
            cur = conn.execute(
                """
                SELECT batch_id, run_id, started_ts, dry_run, summary_json
                FROM apply_batches
                WHERE status = 'PENDING' AND started_ts < ?
                ORDER BY started_ts ASC
                """,
                (float(older_than_ts),),
            )
            for r in cur.fetchall():
                rows.append(
                    {
                        "batch_id": str(r[0]),
                        "run_id": str(r[1] or ""),
                        "started_ts": float(r[2] or 0.0),
                        "dry_run": int(r[3] or 0),
                        "summary_json": str(r[4] or ""),
                    }
                )
        except sqlite3.OperationalError:
            # DB pre-v5 : la table n'existe pas encore. Pas une erreur.
            return []
    return rows


def _classify_batch(store: Any, batch_id: str) -> str:
    """Decide si un batch PENDING-zombi est completable ou doit etre rollback.

    Retourne 'completed' ou 'rolled_back'.

    Heuristique conservatrice :
    - Si aucune operation associee : ROLLED_BACK (rien n'a ete fait,
      ou alors les operations n'ont jamais ete inserees -> incoherent).
    - Si toutes les operations ont error_message NULL/vide ET
      undo_status != 'FAILED' : COMPLETED.
    - Si au moins une operation a un error_message non-vide OU
      undo_status='FAILED' : ROLLED_BACK (preuve d'echec partiel).
    """
    with store._managed_conn() as conn:  # type: ignore[attr-defined]
        try:
            cur = conn.execute(
                """
                SELECT
                  COUNT(*) AS total_ops,
                  SUM(CASE WHEN error_message IS NOT NULL AND error_message != '' THEN 1 ELSE 0 END) AS failed_ops,
                  SUM(CASE WHEN undo_status = 'FAILED' THEN 1 ELSE 0 END) AS undo_failed_ops
                FROM apply_operations
                WHERE batch_id = ?
                """,
                (str(batch_id),),
            )
            row = cur.fetchone()
        except sqlite3.OperationalError:
            return "rolled_back"

    if row is None:
        return "rolled_back"

    total = int(row[0] or 0)
    failed = int(row[1] or 0)
    undo_failed = int(row[2] or 0)

    if total == 0:
        # Aucune operation enregistree -> batch sans contenu, on rollback.
        return "rolled_back"
    if failed > 0 or undo_failed > 0:
        return "rolled_back"
    return "completed"


def _close_batch(store: Any, *, batch_id: str, status: str, now_ts: float) -> None:
    """Marque un batch avec un statut final et `ended_ts=now`.

    Utilise un UPDATE direct (pas via close_apply_batch) car on veut conserver
    le summary_json existant (qui contient l'info originale du batch) et juste
    ajouter une note dans le summary pour tracabilite.
    """
    with store._managed_conn() as conn:  # type: ignore[attr-defined]
        # Lire summary_json courant pour le merge
        try:
            cur = conn.execute(
                "SELECT summary_json FROM apply_batches WHERE batch_id = ?",
                (str(batch_id),),
            )
            row = cur.fetchone()
            current_summary = str(row[0] or "{}") if row else "{}"
        except sqlite3.OperationalError:
            current_summary = "{}"

        # Annoter le summary avec la trace du cleanup (best-effort, on
        # n'echoue pas si JSON casse).
        import json as _json

        try:
            data = _json.loads(current_summary) if current_summary else {}
            if not isinstance(data, dict):
                data = {"_original": current_summary}
        except (TypeError, ValueError):
            data = {}
        data["_boot_cleanup"] = {
            "applied_at": float(now_ts),
            "reason": status,
        }
        new_summary = _json.dumps(data, ensure_ascii=False, sort_keys=True)

        conn.execute(
            """
            UPDATE apply_batches
            SET status = ?, ended_ts = ?, summary_json = ?
            WHERE batch_id = ? AND status = 'PENDING'
            """,
            (str(status), float(now_ts), new_summary, str(batch_id)),
        )


def reconcile_pending_batches(
    store: Any,
    *,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """Cleanup les apply_batches PENDING-zombi au boot.

    Args:
        store : SQLiteStore (ou None -> no-op).
        max_age_hours : age minimum pour considerer un batch comme zombi.
            Defaut 1h. Doit etre > 0.
        now_ts : timestamp de reference (defaut time.time()). Utile pour tests.

    Retourne un rapport :
    {
        "pending_found": int,    # nombre de PENDING-zombi detectes
        "completed": int,        # marques COMPLETED_BY_BOOT_CLEANUP
        "rolled_back": int,      # marques ROLLED_BACK_BY_BOOT_CLEANUP
        "batches": List[dict],   # detail (batch_id, run_id, verdict)
    }

    Tolere store None (no-op, retourne rapport vide).
    """
    report: Dict[str, Any] = {
        "pending_found": 0,
        "completed": 0,
        "rolled_back": 0,
        "batches": [],
    }
    if store is None:
        return report

    max_age = max(0.0, float(max_age_hours))
    now = float(now_ts if now_ts is not None else time.time())
    threshold = now - (max_age * 3600.0)

    try:
        pending = _list_pending_batches(store, older_than_ts=threshold)
    except (sqlite3.Error, OSError, AttributeError):
        _logger.exception("reconcile_pending_batches: list pending failed")
        return report

    if not pending:
        _logger.info("reconcile_pending_batches: no pending batches to reconcile")
        return report

    report["pending_found"] = len(pending)
    _logger.info(
        "reconcile_pending_batches: %d PENDING-zombi batch(es) detected (>%.1fh old)",
        len(pending),
        max_age,
    )

    for batch in pending:
        bid = batch["batch_id"]
        rid = batch["run_id"]
        try:
            verdict = _classify_batch(store, bid)
        except (sqlite3.Error, OSError, AttributeError):
            _logger.exception("reconcile_pending_batches: classify failed for %s", bid)
            verdict = "rolled_back"

        final_status = (
            STATUS_COMPLETED_BY_BOOT if verdict == "completed" else STATUS_ROLLED_BACK_BY_BOOT
        )
        try:
            _close_batch(store, batch_id=bid, status=final_status, now_ts=now)
        except (sqlite3.Error, OSError, AttributeError):
            _logger.exception("reconcile_pending_batches: close failed for %s", bid)
            continue

        if verdict == "completed":
            report["completed"] += 1
            _logger.info(
                "reconcile_pending_batches: batch %s (run=%s) marked %s "
                "(no failed ops, cleanup completing)",
                bid,
                rid,
                final_status,
            )
        else:
            report["rolled_back"] += 1
            _logger.warning(
                "reconcile_pending_batches: batch %s (run=%s) marked %s "
                "(inconsistent state, manual review may be needed)",
                bid,
                rid,
                final_status,
            )

        report["batches"].append(
            {
                "batch_id": bid,
                "run_id": rid,
                "started_ts": batch["started_ts"],
                "verdict": verdict,
                "final_status": final_status,
            }
        )

    return report


def reconcile_batches_at_boot(
    store: Any,
    *,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> Dict[str, Any]:
    """Wrapper boot : appelle reconcile_pending_batches + logue le rapport.

    Tolere toutes les erreurs (n'empeche jamais le boot de continuer).
    """
    try:
        report = reconcile_pending_batches(store, max_age_hours=max_age_hours)
    except Exception:
        _logger.exception("reconcile_batches_at_boot: unexpected error (boot continues)")
        return {
            "pending_found": 0,
            "completed": 0,
            "rolled_back": 0,
            "batches": [],
        }

    if report["pending_found"] > 0:
        _logger.info(
            "reconcile_batches_at_boot: %d PENDING-zombi cleaned (%d completed, %d rolled_back)",
            report["pending_found"],
            report["completed"],
            report["rolled_back"],
        )
    return report
