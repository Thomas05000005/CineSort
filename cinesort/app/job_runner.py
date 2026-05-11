from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
import os
import threading
import time
import traceback
from typing import Any, Callable, Dict, Optional

from cinesort.domain.run_models import RunSnapshot, RunStatus
from cinesort.infra.db import SQLiteStore
from cinesort.infra.log_context import clear_run_id, set_run_id
from cinesort.infra.run_id import normalize_or_generate_run_id

_logger = logging.getLogger(__name__)


JobFn = Callable[[Callable[[], bool]], Optional[Dict[str, Any]]]
_TERMINAL = {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED}
_ACTIVE = {RunStatus.PENDING, RunStatus.RUNNING}


@dataclass
class _RuntimeRun:
    run_id: str
    cancel_event: threading.Event
    thread: Optional[threading.Thread]
    snapshot: RunSnapshot
    debug_log: Optional[Callable[[str], None]]


class JobRunner:
    """Orchestrateur de jobs (scan/apply) en thread, avec persistance d'état.

    Gère un seul run actif à la fois, expose `start_job`, `request_cancel` et
    `get_status`. Les snapshots sont persistés dans `SQLiteStore` et exposés via
    `RunSnapshot` pour l'UI.
    """

    def __init__(self, store: SQLiteStore, debug_logger: Optional[Callable[[str], None]] = None):
        self._store = store
        self._lock = threading.RLock()
        self._runs: Dict[str, _RuntimeRun] = {}
        self._active_run_id: Optional[str] = None
        self._debug_logger = debug_logger

    def _debug(self, message: str, run_debug: Optional[Callable[[str], None]] = None) -> None:
        logger = run_debug or self._debug_logger
        if not logger:
            return
        try:
            logger(message)
        # except Exception intentionnel : boundary top-level
        except Exception as exc:
            if str(os.environ.get("CINESORT_DEBUG", "")).strip().lower() in {"1", "true", "yes", "on", "debug"}:
                try:
                    print(f"[JobRunner] debug logger failure: {exc}", flush=True)
                except (KeyError, TypeError, ValueError):
                    return

    def _write_crash_for_run(self, run_id: str, header: str, tb_text: str) -> None:
        try:
            row = self._store.get_run(run_id)
            if not row:
                return
            state_dir = Path(str(row.get("state_dir") or ""))
            if not state_dir:
                return
            run_dir = state_dir / "runs" / f"tri_films_{run_id}"
            run_dir.mkdir(parents=True, exist_ok=True)
            content = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {header}\n\n{tb_text.rstrip()}\n"
            run_dir.joinpath("crash.txt").write_text(content, encoding="utf-8")
        # except Exception intentionnel : boundary top-level
        except Exception as exc:
            self._debug(f"_write_crash_for_run warning run_id={run_id}: {exc}")

    def _generate_current_format_run_id(self) -> str:
        return time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"

    def _safe_stats(self, stats: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return stats if isinstance(stats, dict) else None

    def _set_snapshot(self, run_id: str, **changes: Any) -> None:
        rt = self._runs.get(run_id)
        if not rt:
            return
        rt.snapshot = replace(rt.snapshot, **changes)

    def _should_cancel_factory(self, run_id: str) -> Callable[[], bool]:
        def _should_cancel() -> bool:
            with self._lock:
                rt = self._runs.get(run_id)
                if not rt:
                    return True
                return rt.cancel_event.is_set()

        return _should_cancel

    def _active_run_locked(self) -> Optional[_RuntimeRun]:
        if not self._active_run_id:
            return None
        rt = self._runs.get(self._active_run_id)
        if not rt:
            self._active_run_id = None
            return None
        if rt.snapshot.status in _ACTIVE:
            return rt
        self._active_run_id = None
        return None

    def start_job(
        self,
        *,
        job_fn: JobFn,
        root: str,
        state_dir: str,
        config: Dict[str, Any],
        run_id_hint: Optional[str] = None,
        debug_log: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Démarre un nouveau job en thread daemon et renvoie son `run_id`.

        Lève `RuntimeError` si un run est déjà actif. Génère un `run_id` unique
        si `run_id_hint` est absent ou en collision avec un run existant.
        """
        created_ts = time.time()
        candidate = run_id_hint or self._generate_current_format_run_id()
        run_id = normalize_or_generate_run_id(candidate)
        run_debug = debug_log or self._debug_logger
        self._debug(
            f"start_job called candidate={candidate} normalized_run_id={run_id} root={root} state_dir={state_dir}",
            run_debug,
        )

        with self._lock:
            active = self._active_run_locked()
            if active:
                self._debug("start_job refused: active run already in progress", run_debug)
                raise RuntimeError("Un run est deja en cours")

            # If same run_id already exists in DB or memory, fallback to uuid-style id.
            if run_id in self._runs or self._store.get_run(run_id) is not None:
                self._debug(f"start_job run_id collision for {run_id}, generating fallback id", run_debug)
                run_id = normalize_or_generate_run_id(None)

            self._store.insert_run_pending(
                run_id=run_id,
                root=str(root),
                state_dir=str(state_dir),
                config=dict(config or {}),
                created_ts=created_ts,
            )
            self._debug(f"start_job insert_run_pending OK run_id={run_id}", run_debug)

            snapshot = RunSnapshot(
                run_id=run_id,
                status=RunStatus.PENDING,
                created_ts=created_ts,
                started_ts=None,
                ended_ts=None,
                cancel_requested=False,
                running=True,
                done=False,
                error=None,
            )
            rt = _RuntimeRun(
                run_id=run_id,
                cancel_event=threading.Event(),
                thread=None,
                snapshot=snapshot,
                debug_log=run_debug,
            )
            self._runs[run_id] = rt
            self._active_run_id = run_id

            t = threading.Thread(target=self._run_worker, args=(run_id, job_fn), daemon=True)
            rt.thread = t
            t.start()
            _logger.info("job: demarrage thread run_id=%s", run_id)
            self._debug(f"start_job thread start OK run_id={run_id} thread_ident={t.ident}", run_debug)

        return run_id

    def _run_worker(self, run_id: str, job_fn: JobFn) -> None:
        """Boucle de vie complète d'un run : RUNNING -> DONE/CANCELLED/FAILED.

        Position le `run_id` dans le ContextVar de log, exécute `job_fn`, persiste
        le statut final, écrit un crash report en cas d'exception, puis nettoie.
        """
        started_ts = time.time()
        stats: Optional[Dict[str, Any]] = None
        error_message: Optional[str] = None
        run_debug: Optional[Callable[[str], None]] = None

        # V3-04 polish v7.7.0 (R4-LOG-1) : positionner le run_id dans le
        # ContextVar pour que TOUS les logs emis depuis ce thread (et ses
        # appels descendants) soient enrichis avec [run=...]. Le clear est
        # garanti par le finally en bas du try.
        set_run_id(run_id)

        try:
            with self._lock:
                rt = self._runs.get(run_id)
                if not rt:
                    return
                run_debug = rt.debug_log
                self._debug(f"worker entered run_id={run_id}", run_debug)
                cancelled_before_run = rt.cancel_event.is_set()

            if cancelled_before_run:
                self._debug(f"worker cancel before run run_id={run_id}", run_debug)
                ended_ts = time.time()
                self._store.mark_run_cancelled(run_id, ended_ts=ended_ts)
                with self._lock:
                    self._set_snapshot(
                        run_id,
                        status=RunStatus.CANCELLED,
                        started_ts=None,
                        ended_ts=ended_ts,
                        cancel_requested=True,
                        running=False,
                        done=True,
                        error=None,
                    )
                return

            self._store.mark_run_running(run_id, started_ts=started_ts)
            self._debug(f"worker mark_run_running OK run_id={run_id}", run_debug)
            with self._lock:
                self._set_snapshot(
                    run_id,
                    status=RunStatus.RUNNING,
                    started_ts=started_ts,
                    running=True,
                    done=False,
                    error=None,
                )

            should_cancel = self._should_cancel_factory(run_id)
            self._debug(f"worker calling job_fn run_id={run_id}", run_debug)
            stats = self._safe_stats(job_fn(should_cancel))
            self._debug(f"worker job_fn returned run_id={run_id} stats_keys={list((stats or {}).keys())}", run_debug)

            ended_ts = time.time()
            if should_cancel():
                self._store.mark_run_cancelled(run_id, stats=stats, ended_ts=ended_ts)
                self._debug(f"worker mark_run_cancelled OK run_id={run_id}", run_debug)
                with self._lock:
                    self._set_snapshot(
                        run_id,
                        status=RunStatus.CANCELLED,
                        ended_ts=ended_ts,
                        cancel_requested=True,
                        running=False,
                        done=True,
                        error=None,
                    )
            else:
                self._store.mark_run_done(run_id, stats=stats, ended_ts=ended_ts)
                _logger.info("job: termine run_id=%s en %.1fs", run_id, ended_ts - started_ts)
                self._debug(f"worker mark_run_done OK run_id={run_id}", run_debug)
                with self._lock:
                    self._set_snapshot(
                        run_id,
                        status=RunStatus.DONE,
                        ended_ts=ended_ts,
                        running=False,
                        done=True,
                        error=None,
                    )

        # except Exception intentionnel : boundary top-level
        except Exception as exc:
            error_message = str(exc)
            tb_text = traceback.format_exc()
            _logger.error("job: echec run_id=%s: %s", run_id, error_message)
            self._debug(f"worker exception run_id={run_id}: {error_message}\n{tb_text}", run_debug)
            ended_ts = time.time()
            self._write_crash_for_run(run_id, "job_runner worker failed", tb_text)
            self._store.mark_run_failed(run_id, error_message=error_message, ended_ts=ended_ts)
            self._store.insert_error(
                run_id=run_id,
                step="job_runner",
                code=exc.__class__.__name__,
                message=error_message,
                context={"run_id": run_id, "traceback": tb_text},
            )
            with self._lock:
                self._set_snapshot(
                    run_id,
                    status=RunStatus.FAILED,
                    ended_ts=ended_ts,
                    running=False,
                    done=True,
                    error=error_message,
                )
        finally:
            with self._lock:
                rt = self._runs.get(run_id)
                if rt and self._active_run_id == run_id:
                    self._active_run_id = None

                rt_after = self._runs.get(run_id)
                if rt_after and rt_after.snapshot.status in _TERMINAL and rt_after.snapshot.ended_ts is None:
                    self._set_snapshot(
                        run_id,
                        ended_ts=time.time(),
                        running=False,
                        done=True,
                        error=error_message
                        if rt_after.snapshot.status == RunStatus.FAILED
                        else rt_after.snapshot.error,
                    )

                # Nettoyer les runs termines anciens pour eviter la fuite memoire (H6)
                # On garde les 5 derniers runs termines pour consultation.
                if len(self._runs) > 5:
                    finished = [(k, v) for k, v in self._runs.items() if v.snapshot.status in _TERMINAL]
                    finished.sort(key=lambda kv: kv[1].snapshot.started_ts or 0.0)
                    # On supprime les plus anciens, en gardant les 5 derniers termines
                    to_drop = finished[:-5] if len(finished) > 5 else []
                    for key, _rt in to_drop:
                        self._runs.pop(key, None)
            self._debug(f"worker finally released active_run run_id={run_id}", run_debug)
            # V3-04 polish v7.7.0 : effacer le run_id du ContextVar pour que les
            # logs emis hors-job (timers daemon) ne portent pas un run_id obsolete.
            clear_run_id()

    def request_cancel(self, run_id: str) -> bool:
        """Demande l'annulation d'un run actif. Renvoie False si inconnu/déjà terminé."""
        run_debug: Optional[Callable[[str], None]] = None
        with self._lock:
            rt = self._runs.get(run_id)
            if not rt:
                self._debug(f"request_cancel ignored: unknown run_id={run_id}", run_debug)
                return False
            run_debug = rt.debug_log
            if rt.snapshot.status in _TERMINAL:
                self._debug(
                    f"request_cancel ignored: run_id={run_id} already terminal={rt.snapshot.status.value}", run_debug
                )
                return False
            rt.cancel_event.set()
            self._set_snapshot(run_id, cancel_requested=True)
            self._debug(f"request_cancel set cancel flag run_id={run_id}", run_debug)

        self._store.mark_cancel_requested(run_id)
        self._debug(f"request_cancel persisted cancel_requested run_id={run_id}", run_debug)
        return True

    def get_status(self, run_id: str) -> Optional[RunSnapshot]:
        """Renvoie le `RunSnapshot` courant pour ce `run_id` (mémoire puis BDD)."""
        with self._lock:
            rt = self._runs.get(run_id)
            if rt:
                return rt.snapshot

        row = self._store.get_run(run_id)
        if not row:
            return None

        try:
            status = RunStatus(str(row.get("status") or "FAILED"))
        except (KeyError, OSError, TypeError, ValueError):
            status = RunStatus.FAILED

        return RunSnapshot(
            run_id=str(row.get("run_id") or run_id),
            status=status,
            created_ts=float(row.get("created_ts") or 0.0),
            started_ts=float(row["started_ts"]) if row.get("started_ts") is not None else None,
            ended_ts=float(row["ended_ts"]) if row.get("ended_ts") is not None else None,
            cancel_requested=bool(row.get("cancel_requested") or 0),
            running=status in _ACTIVE,
            done=status in _TERMINAL,
            error=str(row.get("error_message")) if row.get("error_message") else None,
        )
