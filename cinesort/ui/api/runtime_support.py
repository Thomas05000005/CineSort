"""Runtime and run-store helpers for the pywebview API facade.

CineSortApi remains the public bridge exposed to the stable UI. This module
owns the in-memory run registry, the state_dir-scoped infra cache, and the
lookup helpers that bind runtime runs back to persisted rows.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cinesort.infra.state as state
from cinesort.app import JobRunner
from cinesort.app.move_reconciliation import reconcile_at_boot
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir

_logger = logging.getLogger(__name__)

# CR-1 audit QA 20260429 : la reconciliation au boot ne doit s'executer qu'une
# seule fois par state_dir (la 1re creation de l'infra). Cache memoire pour
# la session courante, reset si la CineSortApi est recree (tests).
_RECONCILED_STATE_DIRS: set = set()


def reset_reconciliation_cache_for_tests() -> None:
    """Permet aux tests d'isoler la reconciliation entre runs."""
    _RECONCILED_STATE_DIRS.clear()


def state_dir_key(state_dir: Path) -> str:
    try:
        return str(state_dir.resolve()).lower()
    except (ImportError, OSError, TypeError, ValueError):
        return str(state_dir).lower()


def run_paths_for(state_dir: Path, run_id: str, *, ensure_exists: bool) -> state.RunPaths:
    run_dir = state_dir / "runs" / f"tri_films_{run_id}"
    if ensure_exists:
        run_dir.mkdir(parents=True, exist_ok=True)
    return state.RunPaths(
        run_id=run_id,
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )


def _publish_integrity_notification_if_any(api: Any, store: SQLiteStore) -> None:
    """V2-11 audit QA 20260504 : publie une notification UI persistante si
    l'integrity_check au boot a detecte une corruption.

    Trois cas distincts produisent un titre et un niveau differents :
    - "restored" : DB restauree avec succes (info, rassurant).
    - "restore_failed" : restore tente mais echoue (error, action requise).
    - "corrupt_no_backup" : aucun backup disponible (error, action requise).

    L'API `add_notification` du module notifications_support cree la
    notification dans le NotificationStore en memoire (cap 200), visible
    dans le notification center du dashboard au prochain refresh.

    Tolerant : toute erreur d'import ou de publication est ignoree pour ne
    pas bloquer le boot.
    """
    event = getattr(store, "integrity_event", None)
    if not event or not isinstance(event, dict):
        return
    status = str(event.get("status") or "")
    if not status:
        return
    try:
        from cinesort.ui.api.notifications_support import add_notification
    except ImportError as exc:
        _logger.warning("V2-11: import notifications_support echoue: %s", exc)
        return

    raw = str(event.get("raw") or "")
    backup_used = event.get("backup_used")
    if status == "restored":
        title = "Base de donnees restauree automatiquement"
        body = (
            "Une corruption a ete detectee au demarrage et la base a ete restauree "
            f"depuis le backup le plus recent. Detail : {raw[:200]}"
        )
        level = "warning"
    elif status == "restore_failed":
        title = "Echec restauration base de donnees"
        body = (
            "Corruption detectee au demarrage. La tentative de restauration "
            f"automatique depuis le backup a echoue. Detail : {raw[:200]}"
        )
        level = "error"
    elif status == "corrupt_no_backup":
        title = "Base de donnees corrompue"
        body = (
            "Une corruption a ete detectee au demarrage mais aucun backup n'est "
            "disponible. Verifiez vos sauvegardes manuelles ou contactez le support. "
            f"Detail : {raw[:200]}"
        )
        level = "error"
    else:
        return

    try:
        add_notification(
            api,
            event_type="db_integrity",
            title=title,
            body=body,
            level=level,
            category="system",
            data={
                "integrity_status": status,
                "raw": raw,
                "backup_used": backup_used,
                "ts": event.get("ts"),
            },
        )
        _logger.warning("V2-11: notification UI publiee (%s): %s", status, title)
    except Exception as exc:
        _logger.warning("V2-11: publication notification echouee: %s", exc)


def get_or_create_infra(
    api: Any,
    state_dir: Path,
    *,
    env_truthy_fn: Callable[[str], bool],
) -> Tuple[SQLiteStore, JobRunner]:
    key = state_dir_key(state_dir)

    def _sqlite_debug(msg: str) -> None:
        if not env_truthy_fn("CINESORT_DEBUG"):
            return
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            api._append_text(state_dir / "debug_sqlite.log", f"[{ts}] {msg}\n")
        except (OSError, TypeError, ValueError):
            return

    with api._runs_lock:
        existing = api._infra_by_state_dir.get(key)
        if existing:
            store_existing, _runner_existing = existing
            version = store_existing.initialize()
            _sqlite_debug(f"SQLite initialized at {store_existing.db_path}, schema version={version}")
            return existing

    store = SQLiteStore(
        db_path_for_state_dir(state_dir),
        busy_timeout_ms=8000,
        debug_logger=_sqlite_debug,
    )
    version = store.initialize()
    _sqlite_debug(f"SQLite initialized at {store.db_path}, schema version={version}")

    # V2-11 audit QA 20260504 : si l'integrity_check a detecte une corruption,
    # publier une notification UI persistante (consommee par le notification
    # center au prochain affichage). Independant de la reconciliation, car
    # peut arriver meme sans pending_moves.
    _publish_integrity_notification_if_any(api, store)

    # CR-1 audit QA 20260429 : reconciliation des moves orphelins au 1er boot
    # de chaque state_dir. Si un crash a interrompu un apply precedent, on
    # examine apply_pending_moves et on classifie/cleanup chaque entree.
    if key not in _RECONCILED_STATE_DIRS:
        try:
            notify = getattr(api, "_notify", None)
            report = reconcile_at_boot(store, notify=notify)
            if report.get("examined", 0) > 0:
                _logger.info(
                    "reconcile_at_boot: %d entree(s) examinee(s), %d completed, %d rolled_back, %d duplicated, %d lost",
                    report["examined"],
                    report.get("completed", 0),
                    report.get("rolled_back", 0),
                    len(report.get("duplicated", [])),
                    len(report.get("lost", [])),
                )
        except Exception as exc:
            _logger.warning("reconcile_at_boot: erreur ignoree (boot continue): %s", exc)
        # R5-CRASH-1 fix : nettoyer les runs orphelins (status='RUNNING' sans
        # processus actif). Si l'app a crash mid-scan, le run reste RUNNING
        # en BDD pour toujours. On les marque FAILED avec message de crash.
        try:
            with store._managed_conn() as conn:  # type: ignore[attr-defined]
                cursor = conn.execute(
                    "SELECT run_id FROM runs WHERE status = ?",
                    ("RUNNING",),
                )
                orphan_run_ids = [row[0] for row in cursor.fetchall()]
                if orphan_run_ids:
                    conn.execute(
                        "UPDATE runs SET status = ?, error_message = COALESCE(error_message, ?) WHERE status = ?",
                        ("FAILED", "Crash detecte au boot (run orphelin)", "RUNNING"),
                    )
                    _logger.warning(
                        "Boot cleanup: %d run(s) orphelin(s) marques FAILED: %s",
                        len(orphan_run_ids),
                        ", ".join(orphan_run_ids[:5]),
                    )
        except Exception as exc:
            _logger.warning("orphan runs cleanup: ignored (%s)", exc)
        _RECONCILED_STATE_DIRS.add(key)

    def _jobrunner_debug(msg: str) -> None:
        if not env_truthy_fn("CINESORT_DEBUG"):
            return
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            api._append_text(state_dir / "debug_jobrunner.log", f"[{ts}] {msg}\n")
        except (OSError, TypeError, ValueError):
            return

    runner = JobRunner(store, debug_logger=_jobrunner_debug)

    with api._runs_lock:
        already = api._infra_by_state_dir.get(key)
        if already:
            return already
        api._infra_by_state_dir[key] = (store, runner)
        return store, runner


def get_run(api: Any, run_id: str) -> Optional[Any]:
    with api._runs_lock:
        purge_terminal_runs_locked(api, max_keep=getattr(api, "_max_terminal_runs_in_memory", 50))
        return api._runs.get(run_id)


def purge_terminal_runs_locked(api: Any, *, max_keep: int) -> None:
    terminal: List[Tuple[float, str]] = []
    for rid, rs in api._runs.items():
        if rs.running:
            continue
        snap = rs.runner.get_status(rid)
        if snap and not snap.done:
            continue
        ts = float((snap.ended_ts if snap else None) or rs.started_ts or 0.0)
        terminal.append((ts, rid))

    safe_max_keep = max(1, int(max_keep or 1))
    if len(terminal) <= safe_max_keep:
        return

    terminal.sort(key=lambda item: item[0], reverse=True)
    keep = {rid for _, rid in terminal[:safe_max_keep]}
    for _, rid in terminal[safe_max_keep:]:
        if rid not in keep:
            api._runs.pop(rid, None)


def generate_run_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"


def generate_unique_run_id(api: Any, store: SQLiteStore) -> str:
    while True:
        run_id = generate_run_id()
        with api._runs_lock:
            if run_id in api._runs:
                continue
        if store.get_run(run_id) is not None:
            continue
        return run_id


def find_run_row(api: Any, run_id: str) -> Optional[Tuple[Dict[str, Any], SQLiteStore]]:
    with api._runs_lock:
        stores = [store for store, _runner in api._infra_by_state_dir.values()]
    for store in stores:
        row = store.get_run(run_id)
        if row:
            return row, store

    default_store, _runner = api._get_or_create_infra(api._state_dir)
    row = default_store.get_run(run_id)
    if row:
        return row, default_store
    return None
