from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import cinesort.domain.core as core
import cinesort.infra.state as state
from cinesort.domain.i18n_messages import t
from cinesort.infra.tmdb_client import TmdbClient
from cinesort.app import JobRunner
from cinesort.infra.db import SQLiteStore
from cinesort.infra.local_secret_store import protection_available as _protection_available
from cinesort.infra.probe import detect_probe_tools, manage_probe_tools, validate_tool_path
from cinesort.app.notify_service import NotifyService
from cinesort.ui.api import (
    apply_support,
    diagnostics_support,
    dashboard_cache_support,
    dashboard_support,
    demo_support,
    film_history_support,
    film_support,
    history_support,
    library_support,
    notifications_support,
    perceptual_support,
    probe_support,
    run_data_support,
    quality_internal_support,
    quality_profile_support,
    quality_report_support,
    quality_support,
    run_flow_support,
    runtime_support,
    run_read_support,
    settings_support,
    tmdb_support,
)
from cinesort.domain.conversions import to_bool as _to_bool
from cinesort.ui.api.settings_support import (
    build_cfg_from_run_row as _build_cfg_from_run_row,
    build_cfg_from_settings as _build_cfg_from_settings_payload,
    normalize_user_path as _normalize_user_path,
    read_settings as _read_settings,
)

logger = logging.getLogger(__name__)

# Compat module-level export kept for existing callers and tests.
protection_available = _protection_available


class RunState:
    def __init__(
        self,
        run_paths: state.RunPaths,
        cfg: core.Config,
        *,
        runner: JobRunner,
        store: SQLiteStore,
    ):
        self.paths = run_paths
        self.cfg = cfg
        self.runner = runner
        self.store = store
        self.lock = threading.Lock()
        self.running = False
        self.done = False
        self.error: Optional[str] = None

        self.idx = 0
        self.total = 0
        self.current_folder = ""
        self.started_ts = time.time()
        self.progress_samples: List[Tuple[float, int]] = []
        self.speed_ewma = 0.0

        self.logs: List[Dict[str, str]] = []  # {ts, level, msg}
        self.rows: List[core.PlanRow] = []
        self.stats: Optional[core.Stats] = None

    def log(self, level: str, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        item = {"ts": ts, "level": level, "msg": msg}
        with self.lock:
            self.logs.append(item)
            if len(self.logs) > MAX_RUN_LOG_ITEMS:
                self.logs = self.logs[-MAX_RUN_LOG_ITEMS:]
        # best-effort UI log persistence
        try:
            self.paths.ui_log_txt.parent.mkdir(parents=True, exist_ok=True)
            with open(self.paths.ui_log_txt, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {level}: {msg}\n")
        # except Exception intentionnel : boundary top-level
        except Exception as exc:
            if _env_truthy("CINESORT_DEBUG"):
                try:
                    with open(self.paths.run_dir / "debug_runstate.log", "a", encoding="utf-8") as f:
                        f.write(f"[{ts}] WARN ui_log write failed: {exc}\n")
                except (OSError, PermissionError):
                    return

    def progress(self, idx: int, total: int, current: str) -> None:
        now = time.time()
        with self.lock:
            prev_idx = self.idx
            prev_ts = self.progress_samples[-1][0] if self.progress_samples else self.started_ts

            self.idx = idx
            self.total = total
            self.current_folder = current

            if idx > prev_idx:
                dt = max(0.001, now - prev_ts)
                inst_speed = (idx - prev_idx) / dt
                # Exponential smoothing to avoid a noisy ETA.
                alpha = 0.28
                self.speed_ewma = (
                    inst_speed if self.speed_ewma <= 0.0 else (alpha * inst_speed + (1.0 - alpha) * self.speed_ewma)
                )
            elif self.speed_ewma <= 0.0 and idx > 0:
                elapsed = max(0.001, now - self.started_ts)
                self.speed_ewma = idx / elapsed

            self.progress_samples.append((now, idx))
            if len(self.progress_samples) > 400:
                self.progress_samples = self.progress_samples[-400:]


def _read_app_version() -> str:
    try:
        version_file = Path(__file__).resolve().parents[3] / "VERSION"
        return version_file.read_text(encoding="utf-8").strip() or "unknown"
    except (OSError, PermissionError, ValueError):
        return "unknown"


def _env_truthy(name: str) -> bool:
    v = str(os.environ.get(name, "")).strip().lower()
    return v in {"1", "true", "yes", "on", "debug"}


DEFAULT_ROOT = r"D:\Films"
DEFAULT_STATE_DIR_EXAMPLE = r"%LOCALAPPDATA%\CineSort"
DEFAULT_COLLECTION_FOLDER_NAME = "_Collection"
DEFAULT_EMPTY_FOLDERS_FOLDER_NAME = "_Vide"
DEFAULT_RESIDUAL_CLEANUP_FOLDER_NAME = "_Dossier Nettoyage"
DEFAULT_PROBE_BACKEND = "auto"
MAX_RUN_LOG_ITEMS = 5000
MAX_TERMINAL_RUNS_IN_MEMORY = 50
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,80}$")


def _cleanup_scope_label(scope: str) -> str:
    return "Toute la racine ROOT" if str(scope or "").strip() == "root_all" else "Dossiers touchés par ce run"


def _cleanup_status_label(status: str, *, dry_run: bool = False) -> str:
    raw = str(status or "").strip()
    if raw == "disabled":
        return "désactivé"
    if raw == "ready":
        return "prêt"
    if raw == "no_action_likely":
        return "aucune action probable"
    if raw == "executed":
        return "exécuté"
    if raw == "executed_no_move":
        return "exécuté sans déplacement"
    if raw == "not_executed":
        return "simulation uniquement" if dry_run else "non exécuté"
    return raw or "inconnu"


def _cleanup_reason_label(reason: str) -> str:
    raw = str(reason or "").strip()
    return {
        "disabled": "fonction désactivée",
        "eligible": "des dossiers semblent éligibles",
        "scope_touched_only_none": "aucun dossier touché correspondant avec le scope actuel",
        "videos_present": "des vidéos sont encore présentes dans les dossiers inspectés",
        "ambiguous_extensions": "des extensions ambiguës ont bloqué le nettoyage",
        "empty_only": "seuls des dossiers vides relèvent de _Vide",
        "none_eligible": "aucun dossier sidecar-only éligible trouvé",
        "no_families_enabled": "aucune famille résiduelle n'est activée",
    }.get(raw, raw or "inconnue")


class CineSortApi:
    """
    API exposee a JavaScript via pywebview.
    """

    def __init__(self):
        self._runs: Dict[str, RunState] = {}
        self._runs_lock = threading.Lock()
        self._state_dir: Path = state.default_state_dir()
        # Lock pour proteger les mutations concurrentes de _state_dir (H7)
        self._state_dir_lock = threading.Lock()
        self._app_version: str = _read_app_version()
        self._infra_by_state_dir: Dict[str, Tuple[SQLiteStore, JobRunner]] = {}
        self._apply_guard_lock = threading.Lock()
        self._apply_inflight_run_ids: set[str] = set()
        self._quality_batch_guard_lock = threading.Lock()
        self._quality_batch_inflight_run_ids: set[str] = set()
        self._max_terminal_runs_in_memory = MAX_TERMINAL_RUNS_IN_MEMORY
        self._last_event_ts: float = time.time()
        self._last_settings_ts: float = time.time()
        self._probe_tools_cache: Dict[str, Any] = {"key": "", "ts": 0.0, "payload": None}
        self._notify = NotifyService()
        self._watcher: Any = None
        self._window: Any = None
        self._rest_server: Any = None
        # v7.6.0 Vague 9 : notification center store (lazy init)
        self._notification_store: Any = None
        self._emitted_insight_codes: set[tuple[str, str]] = set()
        self._notify.set_center_hook(
            lambda event_type, title, body, level: notifications_support.add_notification(
                self,
                event_type=event_type,
                title=title,
                body=body,
                level=level,
                category="event",
            )
        )

        # Cf issue #84 PR 1 (pilote) : facades par bounded context.
        # Strategie Strangler Fig - les anciennes methodes directes coexistent
        # avec les facades pendant la migration (backward-compat 100%).
        # Cf docs/internal/REFACTOR_PLAN_84.md.
        # Import tardif pour eviter cycle (facades importent CineSortApi en TYPE_CHECKING).
        from cinesort.ui.api.facades import (
            IntegrationsFacade,
            LibraryFacade,
            QualityFacade,
            RunFacade,
            SettingsFacade,
        )

        self.run = RunFacade(self)
        self.settings = SettingsFacade(self)
        self.quality = QualityFacade(self)
        self.integrations = IntegrationsFacade(self)
        self.library = LibraryFacade(self)

    def _touch_event(self) -> None:
        """Met a jour le timestamp du dernier evenement significatif (scan, apply, settings)."""
        self._last_event_ts = time.time()

    def _dispatch_plugin_hook(self, event: str, data: Dict[str, Any]) -> None:
        """Dispatch un hook plugin si plugins_enabled. Non-bloquant."""
        try:
            settings = self._get_settings_impl()
            if not settings.get("plugins_enabled"):
                return
            from cinesort.app.plugin_hooks import dispatch_hook

            timeout = int(settings.get("plugins_timeout_s") or 30)
            dispatch_hook(event, data, timeout_s=timeout)
        except (ImportError, KeyError, OSError, TypeError, ValueError):
            pass  # Ne jamais bloquer pour un plugin

    def _dispatch_email(self, event: str, data: Dict[str, Any]) -> None:
        """Dispatch un rapport email si email_enabled. Non-bloquant."""
        try:
            settings = self._get_settings_impl()
            from cinesort.app.email_report import dispatch_email

            dispatch_email(settings, event, data)
        except (ImportError, KeyError, OSError, TypeError, ValueError):
            pass  # Ne jamais bloquer pour un email

    def _is_valid_run_id(self, run_id: Any) -> bool:
        rid = str(run_id or "").strip()
        return bool(RUN_ID_RE.fullmatch(rid))

    def _resolve_payload_state_dir(self, settings: Dict[str, Any]) -> Tuple[Path, bool]:
        return settings_support.resolve_payload_state_dir(settings, default_state_dir=self._state_dir)

    def _resolve_root_from_payload(
        self,
        settings: Dict[str, Any],
        *,
        state_dir: Path,
        state_dir_present: bool,
        missing_message: str,
    ) -> Tuple[Optional[Path], Optional[str]]:
        return settings_support.resolve_root_from_payload(
            settings,
            state_dir=state_dir,
            state_dir_present=state_dir_present,
            current_state_dir=self._state_dir,
            default_root=DEFAULT_ROOT,
            missing_message=missing_message,
        )

    def _resolve_roots_from_payload(
        self,
        settings: Dict[str, Any],
        *,
        state_dir: Path,
        state_dir_present: bool,
        missing_message: str,
    ) -> Tuple[Optional[list], Optional[str]]:
        """Resout la liste des roots depuis le payload settings."""
        return settings_support.resolve_roots_from_payload(
            settings,
            state_dir=state_dir,
            state_dir_present=state_dir_present,
            current_state_dir=self._state_dir,
            default_root=DEFAULT_ROOT,
            missing_message=missing_message,
        )

    def _acquire_apply_slot(self, run_id: str) -> bool:
        with self._apply_guard_lock:
            if run_id in self._apply_inflight_run_ids:
                return False
            self._apply_inflight_run_ids.add(run_id)
            return True

    def _release_apply_slot(self, run_id: str) -> None:
        with self._apply_guard_lock:
            self._apply_inflight_run_ids.discard(run_id)

    def _acquire_quality_batch_slot(self, run_id: str) -> bool:
        with self._quality_batch_guard_lock:
            if run_id in self._quality_batch_inflight_run_ids:
                return False
            self._quality_batch_inflight_run_ids.add(run_id)
            return True

    def _release_quality_batch_slot(self, run_id: str) -> None:
        with self._quality_batch_guard_lock:
            self._quality_batch_inflight_run_ids.discard(run_id)

    def _quality_store(self) -> Tuple[Path, SQLiteStore]:
        return quality_internal_support.quality_store(self)

    def _active_quality_profile_payload(self) -> Dict[str, Any]:
        return quality_internal_support.active_quality_profile_payload(self)

    def _save_active_quality_profile(self, profile_json: Dict[str, Any]) -> Dict[str, Any]:
        return quality_internal_support.save_active_quality_profile(self, profile_json)

    def _write_run_report_file(
        self,
        *,
        run_paths: state.RunPaths,
        run_id: str,
        export_format: str,
        report: Dict[str, Any],
    ) -> Path:
        return dashboard_support.write_run_report_file(
            self,
            run_paths=run_paths,
            run_id=run_id,
            export_format=export_format,
            report=report,
        )

    def _debug_enabled(self, settings: Optional[Dict[str, Any]] = None) -> bool:
        return diagnostics_support.debug_enabled(
            settings,
            env_truthy_fn=_env_truthy,
            to_bool_fn=_to_bool,
        )

    def _append_text(self, path: Path, text: str) -> None:
        diagnostics_support.append_text(path, text)

    def _debug_log(self, *, state_dir: Path, run_id: Optional[str], enabled: bool, message: str) -> None:
        diagnostics_support.debug_log(
            self,
            state_dir=state_dir,
            run_id=run_id,
            enabled=enabled,
            message=message,
        )

    def _sanitize_log_extra(self, extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return diagnostics_support.sanitize_log_extra(extra)

    def log_api_exception(
        self,
        context: str,
        exc: Exception,
        run_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        *,
        store: Optional[SQLiteStore] = None,
        state_dir: Optional[Path] = None,
        level: str = "error",
    ) -> None:
        endpoint = str(context or "unknown")
        rid = str(run_id or "").strip()
        safe_extra = self._sanitize_log_extra(extra)
        resolved_state_dir = state_dir if isinstance(state_dir, Path) else self._state_dir
        resolved_store = store

        if rid and self._is_valid_run_id(rid):
            try:
                found = self._find_run_row(rid)
            except (OSError, TypeError, ValueError):
                found = None
            if found:
                row, found_store = found
                resolved_store = resolved_store or found_store
                resolved_state_dir = _normalize_user_path(row.get("state_dir"), resolved_state_dir)

        debug_settings = _read_settings(resolved_state_dir) if isinstance(resolved_state_dir, Path) else {}
        debug_enabled = self._debug_enabled(debug_settings)
        trace_text = ""
        if debug_enabled:
            trace_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=6)).strip()

        logger_method = logger.warning if str(level).lower() == "warning" else logger.error
        logger_method(
            "API_EXCEPTION endpoint=%s run_id=%s error_type=%s error=%s extra=%s",
            endpoint,
            rid or "-",
            type(exc).__name__,
            exc,
            json.dumps(safe_extra, ensure_ascii=False, sort_keys=True),
        )
        if trace_text:
            self._debug_log(
                state_dir=resolved_state_dir,
                run_id=rid or None,
                enabled=True,
                message=(
                    f"API_EXCEPTION endpoint={endpoint} run_id={rid or '-'} "
                    f"error_type={type(exc).__name__} error={exc}\n{trace_text}"
                ),
            )

        if resolved_store is not None and rid:
            context_payload: Dict[str, Any] = {
                "endpoint": endpoint,
                "run_id": rid,
                "error_type": type(exc).__name__,
                "extra": safe_extra,
            }
            if trace_text:
                context_payload["traceback"] = trace_text
            try:
                resolved_store.insert_error(
                    run_id=rid,
                    step=endpoint,
                    code=type(exc).__name__,
                    message=str(exc),
                    context=context_payload,
                )
            except (KeyError, OSError, TypeError, ValueError) as insert_exc:
                logger.warning(
                    "API_EXCEPTION_PERSIST_FAILED endpoint=%s run_id=%s err=%s",
                    endpoint,
                    rid or "-",
                    insert_exc,
                )
        self._notify.notify(
            "error",
            t("notifications.title_critical_error"),
            f"{endpoint}: {exc}",
            level="error",
        )
        self._dispatch_plugin_hook(
            "post_error",
            {
                "run_id": rid or "",
                "ts": time.time(),
                "data": {"error": str(exc), "step": endpoint},
            },
        )

    def _write_crash_file(self, run_paths: state.RunPaths, header: str, tb_text: str) -> None:
        diagnostics_support.write_crash_file(self, run_paths, header, tb_text, env_truthy_fn=_env_truthy)

    def _unique_path(self, base: Path) -> Path:
        return diagnostics_support.unique_path(base)

    def _write_summary_section(self, run_paths: state.RunPaths, marker: str, section_body: str) -> None:
        diagnostics_support.write_summary_section(run_paths, marker, section_body)

    def _dashboard_cache_path(self, run_paths: state.RunPaths) -> Path:
        return dashboard_cache_support.dashboard_cache_path(run_paths)

    def _path_cache_signature(self, path: Path) -> Dict[str, Any]:
        return dashboard_cache_support.path_cache_signature(path)

    def _dashboard_cache_signature(
        self,
        *,
        run_row: Dict[str, Any],
        run_paths: state.RunPaths,
        store: SQLiteStore,
    ) -> Dict[str, Any]:
        return dashboard_cache_support.dashboard_cache_signature(
            self,
            run_row=run_row,
            run_paths=run_paths,
            store=store,
        )

    def _load_dashboard_cache(
        self,
        *,
        run_row: Dict[str, Any],
        run_paths: state.RunPaths,
        store: SQLiteStore,
    ) -> Optional[Dict[str, Any]]:
        return dashboard_cache_support.load_dashboard_cache(
            self,
            run_row=run_row,
            run_paths=run_paths,
            store=store,
        )

    def _write_dashboard_cache(
        self,
        *,
        run_row: Dict[str, Any],
        run_paths: state.RunPaths,
        store: SQLiteStore,
        payload: Dict[str, Any],
    ) -> None:
        dashboard_cache_support.write_dashboard_cache(
            self,
            run_row=run_row,
            run_paths=run_paths,
            store=store,
            payload=payload,
        )

    def _state_dir_key(self, state_dir: Path) -> str:
        return runtime_support.state_dir_key(state_dir)

    def _run_paths_for(self, state_dir: Path, run_id: str, *, ensure_exists: bool) -> state.RunPaths:
        return runtime_support.run_paths_for(state_dir, run_id, ensure_exists=ensure_exists)

    def _get_or_create_infra(self, state_dir: Path) -> Tuple[SQLiteStore, JobRunner]:
        return runtime_support.get_or_create_infra(self, state_dir, env_truthy_fn=_env_truthy)

    def _get_run(self, run_id: str) -> Optional[RunState]:
        return runtime_support.get_run(self, run_id)

    def _purge_terminal_runs_locked(self) -> None:
        runtime_support.purge_terminal_runs_locked(self, max_keep=MAX_TERMINAL_RUNS_IN_MEMORY)

    def _generate_run_id(self) -> str:
        return runtime_support.generate_run_id()

    def _generate_unique_run_id(self, store: SQLiteStore) -> str:
        return runtime_support.generate_unique_run_id(self, store)

    def _build_cfg_from_settings(self, settings: Dict[str, Any], root: Path) -> core.Config:
        return _build_cfg_from_settings_payload(
            settings,
            root=root,
            default_collection_folder_name=DEFAULT_COLLECTION_FOLDER_NAME,
            default_empty_folders_folder_name=DEFAULT_EMPTY_FOLDERS_FOLDER_NAME,
            default_residual_cleanup_folder_name=DEFAULT_RESIDUAL_CLEANUP_FOLDER_NAME,
        )

    def _cfg_from_run_row(self, row: Dict[str, Any]) -> core.Config:
        return _build_cfg_from_run_row(
            row,
            default_root=DEFAULT_ROOT,
            default_collection_folder_name=DEFAULT_COLLECTION_FOLDER_NAME,
            default_empty_folders_folder_name=DEFAULT_EMPTY_FOLDERS_FOLDER_NAME,
            default_residual_cleanup_folder_name=DEFAULT_RESIDUAL_CLEANUP_FOLDER_NAME,
        )

    def _serialize_rows_for_payload(self, rows: List[core.PlanRow]) -> List[Dict[str, Any]]:
        return run_data_support.serialize_rows_for_payload(rows)

    def _candidate_from_json(self, data: Dict[str, Any]) -> core.Candidate:
        return run_data_support.candidate_from_json(data)

    def _row_from_json(self, data: Dict[str, Any]) -> core.PlanRow:
        return run_data_support.row_from_json(data)

    def _load_rows_from_plan_jsonl(self, run_paths: state.RunPaths) -> List[core.PlanRow]:
        return run_data_support.load_rows_from_plan_jsonl(run_paths)

    def _load_decisions_from_validation(self, run_paths: state.RunPaths) -> Dict[str, Dict[str, Any]]:
        return run_data_support.load_decisions_from_validation(self, run_paths, env_truthy_fn=_env_truthy)

    def _merge_decisions(
        self,
        primary: Dict[str, Dict[str, Any]],
        fallback: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        return run_data_support.merge_decisions(primary, fallback)

    def _file_logger(self, run_paths: state.RunPaths) -> Callable[[str, str], None]:
        return diagnostics_support.file_logger(self, run_paths, env_truthy_fn=_env_truthy)

    def _normalize_decisions_for_rows(
        self,
        rows: List[core.PlanRow],
        decisions: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        return run_data_support.normalize_decisions_for_rows(rows, decisions)

    def _normalize_decisions(self, rs: RunState, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return self._normalize_decisions_for_rows(rs.rows, decisions)

    def _probe_settings_from_dict(self, cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return probe_support.probe_settings_from_dict(cfg)

    def _probe_settings_from_run_row(self, run_row: Dict[str, Any]) -> Dict[str, Any]:
        return probe_support.probe_settings_from_run_row(run_row)

    def _probe_tools_status_payload(
        self,
        *,
        settings: Dict[str, Any],
        state_dir: Path,
        force: bool = False,
        check_versions: bool = True,
        scan_winget_packages: bool = True,
    ) -> Dict[str, Any]:
        return probe_support.probe_tools_status_payload(
            self,
            settings=settings,
            state_dir=state_dir,
            detect_probe_tools_fn=detect_probe_tools,
            force=force,
            check_versions=check_versions,
            scan_winget_packages=scan_winget_packages,
        )

    def _effective_probe_settings_for_runtime(self, run_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return probe_support.effective_probe_settings_for_runtime(
            self,
            run_row,
            detect_probe_tools_fn=detect_probe_tools,
        )

    def _ensure_quality_profile(self, store: SQLiteStore) -> Dict[str, Any]:
        return quality_internal_support.ensure_quality_profile(self, store)

    def _parse_profile_payload(self, payload: Any) -> Tuple[bool, List[str], Dict[str, Any]]:
        return quality_internal_support.parse_profile_payload(payload)

    def _resolve_media_path_for_row(self, cfg: core.Config, row: core.PlanRow) -> Optional[Path]:
        return run_read_support.resolve_media_path_for_row(self, cfg, row, env_truthy_fn=_env_truthy)

    def _find_run_row(self, run_id: str) -> Optional[Tuple[Dict[str, Any], SQLiteStore]]:
        return runtime_support.find_run_row(self, run_id)

    def _run_context_for_apply(
        self,
        run_id: str,
    ) -> Optional[Tuple[core.Config, state.RunPaths, List[core.PlanRow], Callable[[str, str], None], SQLiteStore]]:
        return apply_support.run_context_for_apply(self, run_id)

    def _touched_top_level_dirs_for_rows(
        self,
        cfg: core.Config,
        rows: List[core.PlanRow],
    ) -> Set[Path]:
        return run_read_support.touched_top_level_dirs_for_rows(cfg, rows)

    def _build_run_report_payload(self, run_id: str) -> Tuple[Dict[str, Any], Optional[state.RunPaths]]:
        return dashboard_support.build_run_report_payload(self, run_id)

    def _report_to_csv_text(self, report: Dict[str, Any]) -> str:
        return dashboard_support.report_to_csv_text(report)

    # ---------- settings ----------
    def _get_settings_impl(self) -> Dict[str, Any]:
        return settings_support.get_settings_payload(
            state_dir=self._state_dir,
            default_root=DEFAULT_ROOT,
            default_state_dir_example=DEFAULT_STATE_DIR_EXAMPLE,
            default_collection_folder_name=DEFAULT_COLLECTION_FOLDER_NAME,
            default_empty_folders_folder_name=DEFAULT_EMPTY_FOLDERS_FOLDER_NAME,
            default_residual_cleanup_folder_name=DEFAULT_RESIDUAL_CLEANUP_FOLDER_NAME,
            default_probe_backend=DEFAULT_PROBE_BACKEND,
            debug_enabled=_env_truthy("CINESORT_DEBUG"),
        )

    def _save_settings_impl(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        state_dir, result = settings_support.save_settings_payload(
            settings,
            current_state_dir=self._state_dir,
            default_root=DEFAULT_ROOT,
            default_collection_folder_name=DEFAULT_COLLECTION_FOLDER_NAME,
            default_empty_folders_folder_name=DEFAULT_EMPTY_FOLDERS_FOLDER_NAME,
            default_residual_cleanup_folder_name=DEFAULT_RESIDUAL_CLEANUP_FOLDER_NAME,
            default_probe_backend=DEFAULT_PROBE_BACKEND,
            debug_enabled=_env_truthy("CINESORT_DEBUG"),
        )
        if result.get("ok"):
            # H7 : mutation de _state_dir protegee par lock
            with self._state_dir_lock:
                self._state_dir = state_dir
            self._notify.update_settings(settings)
            self._touch_event()
            self._last_settings_ts = time.time()
            # Toggle watcher dynamique
            self._sync_watcher(settings)
            # V6-01 Polish Total v7.7.0 : appliquer la locale au backend des
            # qu'elle est sauvegardee (i18n_messages.set_locale est tolerant aux
            # valeurs invalides — le clamp a deja eu lieu cote settings).
            self._apply_locale_setting(settings.get("locale"))
        return result

    # ---------- locale (V6-01 Polish Total v7.7.0) ----------
    def _apply_locale_setting(self, locale: Any) -> None:
        """Synchronise i18n_messages.set_locale avec le setting persiste.

        - Tolerant : import lazy pour eviter les cycles, fail silencieux si
          le module i18n n'est pas dispo (ex. tests qui mock partiellement
          le bundle).
        - No-op si ``locale`` est None ou vide (evite des warnings parasites
          dans les tests qui n'envoient pas de locale).
        """
        # Pas de locale fournie -> on ne touche pas la locale active
        if locale is None or (isinstance(locale, str) and not locale.strip()):
            return
        try:
            from cinesort.domain import i18n_messages

            i18n_messages.set_locale(str(locale))
        except (ImportError, AttributeError) as exc:
            logger.debug("i18n: backend locale sync skipped: %s", exc)

    def _set_locale_impl(self, locale: str) -> Dict[str, Any]:
        """Endpoint REST V6-01 : change la locale active (fr|en).

        Met a jour le setting `locale` ET appelle `i18n_messages.set_locale()`
        pour activation immediate cote backend (formatters, messages d'erreur,
        notifications). Le frontend a son propre `setLocale` (cf core/i18n.js)
        qui doit etre appele en parallele pour synchroniser l'UI.

        Returns:
            { "ok": True, "locale": "fr" } en cas de succes
            { "ok": False, "message": "...", "locale": <current> } sinon
        """
        from cinesort.domain.i18n_messages import (
            SUPPORTED_LOCALES as _I18N_SUPPORTED,
            get_locale as _i18n_get_locale,
            set_locale as _i18n_set_locale,
            t as _i18n_t,
        )

        normalized = str(locale or "").strip().lower()
        if normalized not in _I18N_SUPPORTED:
            return {
                "ok": False,
                "message": _i18n_t("errors.invalid_locale", locale=locale),
                "locale": _i18n_get_locale(),
            }
        # 1) Activation immediate cote backend
        _i18n_set_locale(normalized)
        # 2) Persistance dans settings.json (passe par save_settings_payload pour
        #    deduper toute la logique de validation/normalisation/backup).
        try:
            current = self._get_settings_impl()
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("set_locale: cannot load settings to persist locale: %s", exc)
            return {"ok": True, "locale": normalized, "persisted": False}
        current["locale"] = normalized
        try:
            self._save_settings_impl(current)
            persisted = True
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("set_locale: persistence failed: %s", exc)
            persisted = False
        return {"ok": True, "locale": normalized, "persisted": persisted}

    # ---------- V3-05 — Mode démo wizard (premier-run) ----------
    def start_demo_mode(self) -> Dict[str, Any]:
        """V3-05 : active le mode démo (15 films fictifs + run + plan.jsonl)."""
        result = demo_support.start_demo_mode(self)
        if result.get("ok"):
            self._touch_event()
        return result

    def stop_demo_mode(self) -> Dict[str, Any]:
        """V3-05 : désactive le mode démo (supprime runs + quality_reports + run_dir)."""
        result = demo_support.stop_demo_mode(self)
        if result.get("ok"):
            self._touch_event()
        return result

    def is_demo_mode_active(self) -> Dict[str, Any]:
        """V3-05 : True si au moins un run is_demo est présent en BDD."""
        return {"ok": True, "active": bool(demo_support.is_demo_active(self))}

    def _sync_watcher(self, settings: Dict[str, Any]) -> None:
        """Demarre ou arrete le watcher selon les settings."""
        from cinesort.app.watcher import FolderWatcher

        want = bool(settings.get("watch_enabled"))
        if want and (self._watcher is None or not self._watcher.is_alive()):
            # Demarrer
            roots_raw = settings.get("roots") or ([settings.get("root")] if settings.get("root") else [])
            roots = [Path(r) for r in roots_raw if r and Path(r).is_dir()]
            if roots:
                interval_min = max(1, min(60, int(settings.get("watch_interval_minutes") or 5)))
                self._watcher = FolderWatcher(self, interval_s=interval_min * 60, roots=roots)
                self._watcher.start()
        elif not want and self._watcher and self._watcher.is_alive():
            # Arreter
            self._watcher.stop()
            self._watcher = None

    # ---------- Server info ----------
    def get_event_ts(self) -> Dict[str, Any]:
        """Retourne le timestamp du dernier evenement significatif (scan/apply/settings).

        Utilise par le desktop pour detecter les changements et rafraichir (parite dashboard).
        """
        return {
            "ok": True,
            "last_event_ts": float(self._last_event_ts),
            "last_settings_ts": float(self._last_settings_ts),
        }

    def get_server_info(self) -> Dict[str, Any]:
        """Retourne les infos du serveur REST (IP, port, URL dashboard)."""
        from cinesort.infra.network_utils import build_dashboard_url, get_local_ip

        server = self._rest_server
        if server is None or not getattr(server, "is_running", False):
            return {"ok": False, "message": "Serveur REST non demarre."}
        ip = get_local_ip()
        port = getattr(server, "_port", 8642)
        is_https = getattr(server, "_is_https", False)
        url = build_dashboard_url(ip, port, is_https)
        return {"ok": True, "ip": ip, "port": port, "https": is_https, "dashboard_url": url}

    def get_dashboard_qr(self) -> Dict[str, Any]:
        """Retourne un QR code SVG inline pour l'URL du dashboard distant."""
        import io
        import logging as _logging

        _log = _logging.getLogger(__name__)

        info = self.get_server_info()
        if not info.get("ok"):
            # Fallback : construire l'URL depuis les settings
            from cinesort.infra.network_utils import build_dashboard_url, get_local_ip

            settings = self._get_settings_impl()
            ip = get_local_ip()
            port = int(settings.get("rest_api_port") or 8642)
            is_https = bool(settings.get("rest_api_https_enabled"))
            url = build_dashboard_url(ip, port, is_https)
        else:
            url = info["dashboard_url"]

        try:
            import segno

            qr = segno.make(url)
            buf = io.BytesIO()
            qr.save(buf, kind="svg", scale=5, dark="#e0e0e8", light="#0a0a0f", border=2, xmldecl=False, svgns=False)
            svg_str = buf.getvalue().decode("utf-8")
        except (ImportError, KeyError, OSError, TypeError, ValueError) as exc:
            _log.warning("api: echec generation QR — %s", exc)
            return {"ok": False, "message": f"Erreur generation QR: {exc}"}

        _log.info("api: QR code genere pour %s", url)
        return {"ok": True, "svg": svg_str, "url": url}

    def check_for_updates(self) -> Dict[str, Any]:
        """V3-12 — Force un check MAJ immediat (bouton "Verifier maintenant").

        Ignore le cache existant, interroge GitHub Releases et stocke le
        resultat dans le cache local pour les appels ``get_update_info``
        suivants. Retourne un dict toujours non vide avec le statut courant.
        """
        from cinesort.app import updater as _updater

        settings = self._get_settings_impl()
        repo = str(settings.get("update_github_repo") or "").strip()
        if not repo:
            return {
                "ok": False,
                "message": "Aucun depot GitHub configure (update_github_repo).",
                "data": _updater.info_to_dict(None, self._app_version),
            }
        cache_path = _updater.default_cache_path(self._state_dir)
        info = _updater.force_check(self._app_version, repo, cache_path=cache_path)
        try:
            settings["update_last_check_ts"] = time.time()
            self._save_settings_impl(settings)
        except (KeyError, OSError, TypeError, ValueError):
            pass  # ne pas bloquer le check si la persistence echoue
        return {"ok": True, "data": _updater.info_to_dict(info, self._app_version)}

    def get_update_info(self) -> Dict[str, Any]:
        """V3-12 — Retourne le dernier resultat connu (cache).

        Sert l'info instantanement apres le check au boot. Si le cache est
        absent ou expire, ``data.update_available`` vaut False.
        """
        from cinesort.app import updater as _updater

        cache_path = _updater.default_cache_path(self._state_dir)
        info = _updater.get_cached_info(self._app_version, cache_path=cache_path)
        return {"ok": True, "data": _updater.info_to_dict(info, self._app_version)}

    def _restart_api_server_impl(self) -> Dict[str, Any]:
        """Arrete et relance le serveur REST avec les settings actuels."""
        import logging as _logging

        _log = _logging.getLogger(__name__)

        old_server = self._rest_server
        if old_server and hasattr(old_server, "stop"):
            old_server.stop()
            self._rest_server = None

        settings = self._get_settings_impl()
        if not settings.get("rest_api_enabled"):
            return {"ok": False, "message": "API REST desactivee dans les reglages."}
        token = str(settings.get("rest_api_token") or "").strip()
        if not token:
            return {"ok": False, "message": "Aucun token configure."}

        from cinesort.infra.rest_server import RestApiServer

        port = int(settings.get("rest_api_port") or 8642)
        server = RestApiServer(
            self,
            port=port,
            token=token,
            https_enabled=bool(settings.get("rest_api_https_enabled")),
            cert_path=str(settings.get("rest_api_cert_path") or ""),
            key_path=str(settings.get("rest_api_key_path") or ""),
        )
        server.start()
        self._rest_server = server

        _log.info("api: redemarrage serveur REST port=%d https=%s", port, server._is_https)
        return {
            "ok": True,
            "message": "Serveur REST redemarre.",
            "dashboard_url": server.dashboard_url,
        }

    # ---------- Cache incremental ----------
    def reset_incremental_cache(self) -> Dict[str, Any]:
        """Purge TOTALE du cache incremental (3 tables, tous roots confondus).

        Utilise par le bouton "Forcer le rescan complet". Purge sans filtre :
        - incremental_scan_cache (cache folder v1)
        - incremental_row_cache (cache video v2)
        - incremental_file_hashes (hashes quick v1)

        Bug historique : l'ancienne version iterait sur les roots des settings,
        mais si les settings n'avaient pas de root OU si le root_path en BDD
        differait (normalisation de chemin), rien n'etait purge. La nouvelle
        version supprime TOUT le contenu des 3 tables en un seul DELETE.
        """
        import logging as _logging

        _log = _logging.getLogger(__name__)

        # BUG : CineSortApi n'a PAS d'attribut self.store — le store est
        # stocke dans self._infra_by_state_dir et recupere via
        # _get_or_create_infra(). L'ancien code faisait `store = self.store`
        # → AttributeError non catchee → pywebview remontait l'exception au JS
        # → fallback "Purge du cache impossible".
        try:
            store, _runner = self._get_or_create_infra(self._state_dir)
        except Exception as exc:
            _log.exception("api: reset_incremental_cache echec init store")
            return {
                "ok": False,
                "message": f"Store indisponible : {type(exc).__name__}: {exc}",
            }

        try:
            counts = store.clear_all_incremental_caches()
        except Exception as exc:
            # Toutes les erreurs possibles (sqlite3.Error, OSError, AttributeError,
            # bug inattendu) sont remontees a l'utilisateur sous forme de message
            # clair plutot que de laisser pywebview transformer l'exception en
            # fallback JS generique "Purge du cache impossible".
            _log.exception("api: reset_incremental_cache echec purge")
            return {
                "ok": False,
                "message": f"Purge echouee : {type(exc).__name__}: {exc}",
            }

        n_folder = int(counts.get("folder_cache", 0))
        n_row = int(counts.get("row_cache", 0))
        n_hash = int(counts.get("file_hashes", 0))
        total = n_folder + n_row + n_hash
        _log.info(
            "api: reset_incremental_cache folder=%d row=%d hash=%d total=%d",
            n_folder,
            n_row,
            n_hash,
            total,
        )
        return {
            "ok": True,
            "folder_entries_deleted": n_folder,
            "row_entries_deleted": n_row,
            "file_hash_entries_deleted": n_hash,
            "total_deleted": total,
            "message": (
                f"Cache purge : {n_folder} dossiers, {n_row} videos, {n_hash} hashes. Le prochain scan sera complet."
            ),
        }

    # ---------- Helper masque -> cle stockee ----------
    def _unmask_or_stored(self, field: str, value: str) -> str:
        """UX fix : si le frontend renvoie le masque "••••••••" parce que la cle
        est deja chiffree DPAPI, on substitue par la cle stockee en interne.

        Cas typique : utilisateur clique "Tester la connexion" sans retaper la cle.
        Avant ce fix : test echouait avec 401 car la cle envoyee etait le masque.
        Apres : test utilise la vraie cle stockee dans settings.json (DPAPI).
        """
        from cinesort.ui.api.settings_support import _SECRET_MASK

        if str(value or "").strip() == _SECRET_MASK:
            data = _read_settings(self._state_dir)
            return str(data.get(field) or "").strip()
        return str(value or "").strip()

    # ---------- TMDb ----------
    def _test_tmdb_key_impl(self, api_key: str, state_dir: str, timeout_s: float = 10.0) -> Dict[str, Any]:
        api_key = self._unmask_or_stored("tmdb_api_key", api_key)
        return settings_support.test_tmdb_key(
            api_key,
            state_dir,
            timeout_s,
            default_state_dir=state.default_state_dir(),
            tmdb_client_cls=TmdbClient,
        )

    # ---------- Jellyfin ----------
    def _test_jellyfin_connection_impl(
        self, url: str = "", api_key: str = "", timeout_s: float = 10.0
    ) -> Dict[str, Any]:
        """Teste la connexion au serveur Jellyfin."""
        api_key = self._unmask_or_stored("jellyfin_api_key", api_key)
        return settings_support.test_jellyfin_connection(url, api_key, timeout_s)

    def _get_jellyfin_libraries_impl(self) -> Dict[str, Any]:
        """Retourne les bibliothèques Jellyfin configurées."""
        data = _read_settings(self._state_dir)
        url = str(data.get("jellyfin_url") or "").strip()
        api_key = str(data.get("jellyfin_api_key") or "").strip()
        user_id = str(data.get("jellyfin_user_id") or "").strip()
        timeout_s = float(data.get("jellyfin_timeout_s") or 10.0)
        if not url or not api_key:
            return {"ok": False, "message": "Jellyfin non configuré."}

        from cinesort.infra.jellyfin_client import JellyfinClient, JellyfinError

        try:
            client = JellyfinClient(url, api_key, timeout_s=timeout_s)
            if not user_id:
                info = client.validate_connection()
                if not info.get("ok"):
                    return {"ok": False, "message": info.get("error", "Connexion échouée.")}
                user_id = info.get("user_id", "")
            libraries = client.get_libraries(user_id)
            movies_count = client.get_movies_count(user_id)
            return {"ok": True, "libraries": libraries, "movies_count": movies_count}
        except JellyfinError as exc:
            return {"ok": False, "message": str(exc)}

    # ---------- Email ----------
    def test_email_report(self) -> Dict[str, Any]:
        """Envoie un email test avec des donnees mock."""
        from cinesort.app.email_report import send_email_report

        settings = self._get_settings_impl()
        if not settings.get("email_smtp_host") or not settings.get("email_to"):
            return {"ok": False, "message": "Configurez d'abord le serveur SMTP et le destinataire."}
        mock_data = {
            "run_id": "test",
            "ts": time.time(),
            "data": {"rows": 42, "folders_scanned": 42, "roots": ["D:/Films"]},
        }
        ok = send_email_report(settings, "post_scan", mock_data)
        return {"ok": ok, "message": "Email test envoye." if ok else "Echec de l'envoi. Verifiez les parametres SMTP."}

    # ---------- Jellyfin validation croisee ----------
    def _get_jellyfin_sync_report_impl(self, run_id: str = "") -> Dict[str, Any]:
        """Compare la bibliotheque locale avec Jellyfin. Retourne le rapport de coherence."""
        settings = self._get_settings_impl()
        if not settings.get("jellyfin_enabled"):
            return {"ok": False, "message": "Jellyfin non configure."}
        jf_url = str(settings.get("jellyfin_url") or "").strip()
        jf_key = str(settings.get("jellyfin_api_key") or "").strip()
        jf_user_id = str(settings.get("jellyfin_user_id") or "").strip()
        if not jf_url or not jf_key:
            return {"ok": False, "message": "URL ou cle API Jellyfin manquante."}

        # Charger les PlanRows du dernier run
        state_dir = Path(self._state_dir)
        store, _runner = self._get_or_create_infra(state_dir)
        from cinesort.domain.film_history import _load_plan_rows_from_jsonl
        from cinesort.app.plan_support import plan_row_from_jsonable

        runs = store.get_runs_summary(limit=5)
        target_run_id = run_id.strip() if run_id else ""
        if not target_run_id:
            for r in runs:
                if str(r.get("status") or "") == "DONE":
                    target_run_id = str(r.get("run_id") or "")
                    break
        if not target_run_id:
            return {"ok": False, "message": "Aucun run termine disponible."}

        plan_path = state_dir / "runs" / target_run_id / "plan.jsonl"
        raw_rows = _load_plan_rows_from_jsonl(plan_path)
        local_rows = [plan_row_from_jsonable(d) for d in raw_rows]
        local_rows = [r for r in local_rows if r is not None]
        if not local_rows:
            return {"ok": False, "message": "Aucun film dans ce run."}

        # Appeler Jellyfin
        from cinesort.infra.jellyfin_client import JellyfinClient, JellyfinError

        try:
            timeout_s = float(settings.get("jellyfin_timeout_s") or 10)
            client = JellyfinClient(jf_url, jf_key, timeout_s=timeout_s)
            if not jf_user_id:
                info = client.validate_connection()
                jf_user_id = info.get("user_id", "")
            # BUG 2 : utiliser le scan multi-library pour eviter les tronques
            jellyfin_movies = client.get_all_movies_from_all_libraries(jf_user_id)
        except JellyfinError as exc:
            return {"ok": False, "message": f"Connexion Jellyfin echouee : {exc}"}

        from cinesort.app.jellyfin_validation import build_sync_report

        report = build_sync_report(local_rows, jellyfin_movies)
        return {"ok": True, "run_id": target_run_id, **report}

    # ---------- Watchlist ----------
    def import_watchlist(self, csv_content: str, source: str) -> Dict[str, Any]:
        """Importe une watchlist CSV et compare avec la bibliotheque locale."""
        src = str(source or "").strip().lower()
        if src not in ("letterboxd", "imdb"):
            return {"ok": False, "message": "Source inconnue. Utilisez 'letterboxd' ou 'imdb'."}
        content = str(csv_content or "")
        if not content.strip():
            return {"ok": False, "message": "Contenu CSV vide."}

        from cinesort.app.watchlist import parse_letterboxd_csv, parse_imdb_csv, compare_watchlist

        if src == "letterboxd":
            films = parse_letterboxd_csv(content)
        else:
            films = parse_imdb_csv(content)
        if not films:
            return {"ok": False, "message": "Aucun film trouve dans le CSV."}

        # Charger les PlanRows du dernier run
        state_dir = Path(self._state_dir)
        store, _runner = self._get_or_create_infra(state_dir)
        from cinesort.domain.film_history import _load_plan_rows_from_jsonl
        from cinesort.app.plan_support import plan_row_from_jsonable

        runs = store.get_runs_summary(limit=5)
        target_run_id = ""
        for r in runs:
            if str(r.get("status") or "") == "DONE":
                target_run_id = str(r.get("run_id") or "")
                break
        if not target_run_id:
            return {"ok": False, "message": "Aucun run termine disponible."}

        plan_path = state_dir / "runs" / target_run_id / "plan.jsonl"
        raw_rows = _load_plan_rows_from_jsonl(plan_path)
        local_rows = [plan_row_from_jsonable(d) for d in raw_rows]
        local_rows = [r for r in local_rows if r is not None]

        report = compare_watchlist(films, local_rows)
        return {"ok": True, "source": src, **report}

    # ---------- Plex ----------
    def _test_plex_connection_impl(self, url: str = "", token: str = "", timeout_s: float = 10.0) -> Dict[str, Any]:
        """Teste la connexion au serveur Plex."""
        from cinesort.infra.plex_client import PlexClient

        purl = (url or "").strip()
        ptok = self._unmask_or_stored("plex_token", token)
        if not purl or not ptok:
            return {"ok": False, "message": "URL et token requis."}
        client = PlexClient(purl, ptok, timeout_s=max(1, min(30, timeout_s)))
        return client.validate_connection()

    def _get_plex_libraries_impl(self, url: str = "", token: str = "", timeout_s: float = 10.0) -> Dict[str, Any]:
        """Retourne les sections movie du serveur Plex."""
        from cinesort.infra.plex_client import PlexClient, PlexError

        purl = (url or "").strip()
        ptok = (token or "").strip()
        if not purl or not ptok:
            settings = self._get_settings_impl()
            purl = purl or str(settings.get("plex_url") or "").strip()
            ptok = ptok or str(settings.get("plex_token") or "").strip()
        if not purl or not ptok:
            return {"ok": False, "message": "URL et token Plex requis."}
        try:
            client = PlexClient(purl, ptok, timeout_s=max(1, min(30, timeout_s)))
            libs = client.get_libraries("movie")
            return {"ok": True, "libraries": libs}
        except PlexError as exc:
            return {"ok": False, "message": str(exc)}

    def _get_plex_sync_report_impl(self, run_id: str = "") -> Dict[str, Any]:
        """Compare la bibliotheque locale avec Plex."""
        settings = self._get_settings_impl()
        if not settings.get("plex_enabled"):
            return {"ok": False, "message": "Plex non configure."}
        purl = str(settings.get("plex_url") or "").strip()
        ptok = str(settings.get("plex_token") or "").strip()
        plib = str(settings.get("plex_library_id") or "").strip()
        if not purl or not ptok or not plib:
            return {"ok": False, "message": "URL, token ou library Plex manquant."}

        state_dir = Path(self._state_dir)
        store, _runner = self._get_or_create_infra(state_dir)
        from cinesort.domain.film_history import _load_plan_rows_from_jsonl
        from cinesort.app.plan_support import plan_row_from_jsonable

        runs = store.get_runs_summary(limit=5)
        target_run_id = run_id.strip() if run_id else ""
        if not target_run_id:
            for r in runs:
                if str(r.get("status") or "") == "DONE":
                    target_run_id = str(r.get("run_id") or "")
                    break
        if not target_run_id:
            return {"ok": False, "message": "Aucun run termine disponible."}

        plan_path = state_dir / "runs" / target_run_id / "plan.jsonl"
        raw_rows = _load_plan_rows_from_jsonl(plan_path)
        local_rows = [plan_row_from_jsonable(d) for d in raw_rows]
        local_rows = [r for r in local_rows if r is not None]
        if not local_rows:
            return {"ok": False, "message": "Aucun film dans ce run."}

        from cinesort.infra.plex_client import PlexClient, PlexError

        try:
            timeout_s = float(settings.get("plex_timeout_s") or 10)
            client = PlexClient(purl, ptok, timeout_s=timeout_s)
            plex_movies = client.get_movies(plib)
        except PlexError as exc:
            return {"ok": False, "message": f"Connexion Plex echouee : {exc}"}

        from cinesort.app.jellyfin_validation import build_sync_report

        report = build_sync_report(local_rows, plex_movies)
        return {"ok": True, "run_id": target_run_id, **report}

    # ---------- Radarr ----------
    def _test_radarr_connection_impl(self, url: str = "", api_key: str = "", timeout_s: float = 10.0) -> Dict[str, Any]:
        """Teste la connexion au serveur Radarr."""
        from cinesort.infra.radarr_client import RadarrClient

        rurl = (url or "").strip()
        rkey = self._unmask_or_stored("radarr_api_key", api_key)
        if not rurl or not rkey:
            return {"ok": False, "message": "URL et cle API requis."}
        client = RadarrClient(rurl, rkey, timeout_s=max(1, min(30, timeout_s)))
        return client.validate_connection()

    def _get_radarr_status_impl(self, run_id: str = "") -> Dict[str, Any]:
        """Rapport Radarr : matching, upgrade candidates."""
        settings = self._get_settings_impl()
        if not settings.get("radarr_enabled"):
            return {"ok": False, "message": "Radarr non configure."}
        rurl = str(settings.get("radarr_url") or "").strip()
        rkey = str(settings.get("radarr_api_key") or "").strip()
        if not rurl or not rkey:
            return {"ok": False, "message": "URL ou cle API Radarr manquante."}

        state_dir = Path(self._state_dir)
        store, _runner = self._get_or_create_infra(state_dir)
        from cinesort.domain.film_history import _load_plan_rows_from_jsonl
        from cinesort.app.plan_support import plan_row_from_jsonable

        runs = store.get_runs_summary(limit=5)
        target_run_id = run_id.strip() if run_id else ""
        if not target_run_id:
            for r in runs:
                if str(r.get("status") or "") == "DONE":
                    target_run_id = str(r.get("run_id") or "")
                    break
        if not target_run_id:
            return {"ok": False, "message": "Aucun run termine disponible."}

        plan_path = state_dir / "runs" / target_run_id / "plan.jsonl"
        raw_rows = _load_plan_rows_from_jsonl(plan_path)
        local_rows = [plan_row_from_jsonable(d) for d in raw_rows]
        local_rows = [r for r in local_rows if r is not None]

        from cinesort.infra.radarr_client import RadarrClient, RadarrError

        try:
            timeout_s = float(settings.get("radarr_timeout_s") or 10)
            client = RadarrClient(rurl, rkey, timeout_s=timeout_s)
            radarr_movies = client.get_movies()
            profiles = client.get_quality_profiles()
        except RadarrError as exc:
            return {"ok": False, "message": f"Connexion Radarr echouee : {exc}"}

        # Collecter les quality reports pour les upgrade candidates
        qr_map: Dict[str, Dict[str, Any]] = {}
        for row in local_rows:
            rid = str(getattr(row, "row_id", "") or "")
            if rid:
                qr = store.get_quality_report(run_id=target_run_id, row_id=rid)
                if qr:
                    qr_map[rid] = qr

        from cinesort.app.radarr_sync import build_radarr_report, get_upgrade_candidates

        report = build_radarr_report(local_rows, radarr_movies, qr_map, profiles)
        candidates = get_upgrade_candidates(report, qr_map)
        return {"ok": True, "run_id": target_run_id, **report, "upgrade_candidates": candidates}

    def _request_radarr_upgrade_impl(self, radarr_movie_id: int) -> Dict[str, Any]:
        """Demande a Radarr de chercher une meilleure version d'un film."""
        settings = self._get_settings_impl()
        if not settings.get("radarr_enabled"):
            return {"ok": False, "message": "Radarr non configure."}
        rurl = str(settings.get("radarr_url") or "").strip()
        rkey = str(settings.get("radarr_api_key") or "").strip()
        mid = int(radarr_movie_id or 0)
        if mid <= 0:
            return {"ok": False, "message": "radarr_movie_id invalide."}
        from cinesort.infra.radarr_client import RadarrClient, RadarrError

        try:
            timeout_s = float(settings.get("radarr_timeout_s") or 10)
            client = RadarrClient(rurl, rkey, timeout_s=timeout_s)
            client.search_movie(mid)
            return {"ok": True, "message": f"Recherche lancee pour le film Radarr #{mid}."}
        except RadarrError as exc:
            return {"ok": False, "message": str(exc)}

    def get_naming_presets(self) -> Dict[str, Any]:
        """Retourne la liste des presets de renommage disponibles."""
        from cinesort.domain.naming import PRESETS

        presets = []
        for _pid, p in PRESETS.items():
            presets.append(
                {
                    "id": p.id,
                    "label": p.label,
                    "movie_template": p.movie_template,
                    "tv_template": p.tv_template,
                }
            )
        return {"ok": True, "presets": presets}

    def preview_naming_template(self, template: str = "", sample_row_id: str = "") -> Dict[str, Any]:
        """Preview du resultat d'un template de renommage sur un film exemple."""
        from cinesort.domain.naming import (
            PREVIEW_MOCK_CONTEXT,
            build_naming_context,
            format_movie_folder,
            validate_template,
        )

        tpl = str(template or "{title} ({year})").strip()
        ok, errors = validate_template(tpl)
        if not ok:
            return {"ok": False, "errors": errors, "message": "Template invalide."}

        # Essayer de charger un vrai film depuis la BDD
        context = None
        rid = str(sample_row_id or "").strip()
        if rid:
            try:
                settings = _read_settings(self._state_dir)
                state_dir = self._state_dir
                store, _ = self._get_or_create_infra(state_dir, settings)
                # Chercher la probe en cache
                probe_data = store.get_probe_cache(rid) if hasattr(store, "get_probe_cache") else None
                quality_data = store.get_quality_report(rid) if hasattr(store, "get_quality_report") else None
                context = build_naming_context(
                    title="Film",
                    year=2020,
                    probe_data=probe_data,
                    quality_data=quality_data,
                )
            except (OSError, PermissionError, TypeError, ValueError):
                context = None

        # Fallback : mock hardcode (Inception)
        if context is None:
            context = dict(PREVIEW_MOCK_CONTEXT)

        result = format_movie_folder(tpl, context)
        return {"ok": True, "result": result, "variables": context}

    def validate_dropped_path(self, path: str = "") -> Dict[str, Any]:
        r"""Valide qu'un chemin droppe est un dossier existant.

        M-7 audit QA 20260429 : refuse les symlinks et chemins UNC speciaux
        (\\?\ , \\.\ , etc.) qui peuvent contourner les guards path-traversal.
        Les UNC normaux \\server\share sont autorises (cas legitime NAS).
        """
        raw = str(path or "").strip()
        if not raw:
            return {"ok": False, "message": "Chemin vide."}

        # M-7 : reject UNC namespaces speciaux Windows (\\?\, \\.\)
        # Ces prefixes contournent la normalisation Win32 et permettent
        # d'acceder a des paths > 260 chars ou des devices systeme.
        norm = raw.replace("/", "\\")
        if norm.startswith("\\\\?\\") or norm.startswith("\\\\.\\"):
            return {"ok": False, "message": "Chemin UNC special non autorise (\\\\?\\ ou \\\\.\\)."}

        p = Path(raw)

        # M-7 : verifier accessibilite avec timeout (NAS debranche)
        from cinesort.infra.fs_safety import safe_path_exists

        exists = safe_path_exists(p, timeout_s=5.0)
        if exists is None:
            return {"ok": False, "message": "Chemin inaccessible (NAS debranche ou timeout)."}
        if not exists:
            return {"ok": False, "message": f"Chemin introuvable : {p}"}

        # M-7 : refuser les symlinks (peuvent pointer ailleurs apres validation)
        try:
            if p.is_symlink():
                return {
                    "ok": False,
                    "message": "Les liens symboliques ne sont pas autorises (resolvez la cible directement).",
                }
        except (OSError, PermissionError):
            return {"ok": False, "message": "Impossible de lire l'attribut symlink du chemin."}

        if not p.is_dir():
            return {"ok": False, "message": "Ce n'est pas un dossier."}

        # Resolution finale + verification que le resultat n'est pas un symlink
        # remontant ailleurs (defense en profondeur)
        try:
            resolved = p.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            return {"ok": False, "message": f"Impossible de resoudre le chemin : {exc}"}

        return {"ok": True, "path": str(resolved)}

    def get_tools_status(self) -> Dict[str, Any]:
        # Compat endpoint kept for v7.0/v7.1 callers.
        return self.get_probe_tools_status()

    def get_probe_tools_status(self) -> Dict[str, Any]:
        """Retourne le statut de detection de ffprobe + MediaInfo (version, chemin, dispo)."""
        return probe_support.get_probe_tools_status(self, detect_probe_tools_fn=detect_probe_tools)

    def recheck_probe_tools(self) -> Dict[str, Any]:
        """Force une redetection des outils probe (utile apres installation manuelle)."""
        return probe_support.recheck_probe_tools(self, detect_probe_tools_fn=detect_probe_tools)

    def set_probe_tool_paths(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Enregistre des chemins manuels vers ffprobe / MediaInfo (si hors PATH)."""
        return probe_support.set_probe_tool_paths(
            self,
            payload,
            validate_tool_path_fn=validate_tool_path,
            detect_probe_tools_fn=detect_probe_tools,
        )

    def install_probe_tools(self, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Installe ffprobe + MediaInfo via winget (ou options fournies)."""
        return probe_support.install_probe_tools(
            self,
            options,
            manage_probe_tools_fn=manage_probe_tools,
            detect_probe_tools_fn=detect_probe_tools,
        )

    def update_probe_tools(self, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Met a jour ffprobe + MediaInfo via winget."""
        return probe_support.update_probe_tools(
            self,
            options,
            manage_probe_tools_fn=manage_probe_tools,
            detect_probe_tools_fn=detect_probe_tools,
        )

    def auto_install_probe_tools(self) -> Dict[str, Any]:
        """Telecharge et installe ffprobe + MediaInfo depuis les sources officielles."""
        return probe_support.auto_install_probe_tools(self, detect_probe_tools_fn=detect_probe_tools)

    def get_probe(self, run_id: str, row_id: str) -> Dict[str, Any]:
        """Retourne la probe normalisee (video/audio/sous-titres) d'un film du run."""
        return probe_support.get_probe(self, run_id, row_id, detect_probe_tools_fn=detect_probe_tools)

    def _get_quality_profile_impl(self) -> Dict[str, Any]:
        """Retourne le profil de scoring qualite actif (poids, seuils, toggles)."""
        return quality_profile_support.get_quality_profile(self)

    def _get_quality_presets_impl(self) -> Dict[str, Any]:
        """Retourne le catalogue des presets de scoring (Remux strict / Equilibre / Light)."""
        return quality_profile_support.get_quality_presets(self)

    def _apply_quality_preset_impl(self, preset_id: str) -> Dict[str, Any]:
        """Applique un preset du catalogue comme profil de scoring actif."""
        from cinesort.ui.api.quality_simulator_support import clear_cache as _sim_clear

        _sim_clear()
        return quality_profile_support.apply_quality_preset(self, preset_id)

    def _simulate_quality_preset_impl(
        self,
        run_id: str = "latest",
        preset_id: str = "equilibre",
        overrides: Optional[Dict[str, Any]] = None,
        scope: str = "run",
    ) -> Dict[str, Any]:
        """Simule l'application d'un preset qualite sans persister (G5)."""
        from cinesort.ui.api.quality_simulator_support import run_simulation

        return run_simulation(self, run_id=run_id, preset_id=preset_id, overrides=overrides, scope=scope)

    def _save_custom_quality_preset_impl(self, name: str, profile_json: Dict[str, Any]) -> Dict[str, Any]:
        """Persiste un profil qualite custom et l'active (G5)."""
        from cinesort.ui.api.quality_simulator_support import save_custom_preset

        return save_custom_preset(self, name, profile_json)

    def _get_custom_rules_templates_impl(self) -> Dict[str, Any]:
        """Retourne les 3 templates starter de regles custom (G6)."""
        from cinesort.domain.custom_rules_templates import list_templates

        return {"ok": True, "templates": list_templates()}

    def _get_custom_rules_catalog_impl(self) -> Dict[str, Any]:
        """Retourne les fields, operators et actions disponibles pour le builder UI (G6)."""
        from cinesort.domain.custom_rules import ACTIONS, FIELD_PATHS, OPERATORS

        return {
            "ok": True,
            "fields": list(FIELD_PATHS.keys()),
            "operators": list(OPERATORS.keys()),
            "actions": list(ACTIONS.keys()),
        }

    def _validate_custom_rules_impl(self, rules: Any) -> Dict[str, Any]:
        """Valide une liste de regles custom sans persister (G6)."""
        from cinesort.domain.custom_rules import validate_rules

        ok, errs, norm = validate_rules(rules or [])
        return {"ok": ok, "errors": errs, "normalized": norm}

    def _save_quality_profile_impl(self, profile_json: Any) -> Dict[str, Any]:
        """Enregistre un profil de scoring custom (valide, persiste, active)."""
        return quality_profile_support.save_quality_profile(self, profile_json)

    def test_reset(self, min_video_bytes: int = 0) -> Dict[str, Any]:
        """Remet l'app dans un etat propre pour les tests E2E. Desactive en production.

        Args:
            min_video_bytes: si > 0, abaisse le seuil de taille video pour les
                fichiers factices. Defaut 0 = pas de changement.
        """
        if os.environ.get("CINESORT_E2E") != "1":
            return {"ok": False, "error": "E2E mode not active"}
        try:
            # Reset du run courant
            with self._runs_lock:
                self._runs.clear()
            # Abaisser le seuil de taille video si demande (fichiers factices E2E)
            if min_video_bytes > 0:
                import cinesort.domain.core as _core

                _core.MIN_VIDEO_BYTES = int(min_video_bytes)
            return {"ok": True, "message": "Reset E2E effectue."}
        except (OSError, KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def _reset_quality_profile_impl(self) -> Dict[str, Any]:
        """Reinitialise le profil de scoring aux valeurs par defaut."""
        return quality_profile_support.reset_quality_profile(self)

    def _export_quality_profile_impl(self) -> Dict[str, Any]:
        """Exporte le profil de scoring actif en JSON (pour partage / backup)."""
        return quality_profile_support.export_quality_profile(self)

    def _import_quality_profile_impl(self, profile_json: Any) -> Dict[str, Any]:
        """Importe un profil de scoring depuis JSON (valide, persiste, active)."""
        return quality_profile_support.import_quality_profile(self, profile_json)

    def _get_quality_report_impl(
        self, run_id: str, row_id: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Retourne le rapport de scoring qualite d'un film (score, tier, reasons, metrics)."""
        return quality_report_support.get_quality_report(self, run_id, row_id, options)

    def _analyze_quality_batch_impl(
        self, run_id: str, row_ids: Any, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Analyse qualite batch sur plusieurs films (probe + scoring)."""
        return quality_support.analyze_quality_batch(self, run_id, row_ids, options)

    # ---------- analyse perceptuelle ----------

    def _get_perceptual_report_impl(
        self, run_id: str, row_id: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Analyse perceptuelle d'un film (a la demande)."""
        return perceptual_support.get_perceptual_report(self, run_id, row_id, options)

    def _get_perceptual_details_impl(self, run_id: str, row_id: str) -> Dict[str, Any]:
        """Retourne toutes les metriques perceptuelles persistees (lecture DB).

        Cf issue #32 : expose audio_fingerprint, ssim_self_ref,
        upscale_verdict, spectral_cutoff_hz, global_score_v2 + breakdown.
        Ne declenche AUCUNE analyse, lecture pure. Pour declencher une
        analyse, utiliser get_perceptual_report().
        """
        return perceptual_support.get_perceptual_details(self, run_id, row_id)

    def _analyze_perceptual_batch_impl(
        self, run_id: str, row_ids: Any, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Analyse perceptuelle batch sur plusieurs films."""
        return perceptual_support.analyze_perceptual_batch(self, run_id, row_ids, options)

    def _compare_perceptual_impl(
        self, run_id: str, row_id_a: str, row_id_b: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Comparaison perceptuelle profonde entre 2 fichiers."""
        return perceptual_support.compare_perceptual(self, run_id, row_id_a, row_id_b, options)

    def get_dashboard(self, run_id: str = "latest") -> Dict[str, Any]:
        """Dashboard d'un run (KPIs, distribution scores, anomalies, timeline)."""
        return dashboard_support.get_dashboard(self, run_id)

    def get_global_stats(self, limit_runs: int = 20) -> Dict[str, Any]:
        """Global dashboard: multi-run statistics for the library."""
        return dashboard_support.get_global_stats(self, limit_runs)

    def get_sidebar_counters(self) -> Dict[str, Any]:
        """V3-04 — Compteurs sidebar pour badges UI (validation/application/quality)."""
        return {"data": dashboard_support.get_sidebar_counters(self)}

    # ---------- v7.6.0 Vague 3 : Library / Explorer ----------
    def _get_library_filtered_impl(
        self,
        run_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        sort: str = "title",
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """v7.6.0 Vague 3 : Library filtree, triee, paginee.

        Filtres supportes : search, tier_v2, codec, resolution, hdr,
        warnings, grain_era_v2, grain_nature, year_min/max, duration_min/max.
        """
        return library_support.get_library_filtered(self, run_id, filters, sort, page, page_size)

    def _get_smart_playlists_impl(self) -> Dict[str, Any]:
        """v7.6.0 Vague 3 : liste des smart playlists (presets + custom)."""
        return library_support.get_smart_playlists(self)

    def _save_smart_playlist_impl(
        self,
        name: str,
        filters: Dict[str, Any],
        playlist_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """v7.6.0 Vague 3 : cree ou met a jour une smart playlist custom."""
        return library_support.save_smart_playlist(self, name, filters, playlist_id)

    def _delete_smart_playlist_impl(self, playlist_id: str) -> Dict[str, Any]:
        """v7.6.0 Vague 3 : supprime une smart playlist custom."""
        return library_support.delete_smart_playlist(self, playlist_id)

    def _get_scoring_rollup_impl(
        self,
        by: str = "franchise",
        limit: int = 20,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """v7.6.0 Vague 7 : scoring agrege par dimension (franchise / decade / codec / era_grain)."""
        return library_support.get_scoring_rollup(self, by=by, limit=limit, run_id=run_id)

    # ---------- v7.6.0 Vague 9 : Notification Center ----------
    def get_notifications(
        self,
        unread_only: bool = False,
        limit: int = 100,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : liste les notifications en memoire (LIFO)."""
        return notifications_support.get_notifications(self, unread_only=unread_only, limit=limit, category=category)

    def dismiss_notification(self, notification_id: str) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : supprime une notification du centre."""
        return notifications_support.dismiss_notification(self, notification_id)

    def mark_notification_read(self, notification_id: str) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : marque une notification comme lue."""
        return notifications_support.mark_read(self, notification_id)

    def mark_all_notifications_read(self) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : marque toutes les notifications comme lues."""
        return notifications_support.mark_all_read(self)

    def clear_notifications(self) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : vide completement le centre de notifications."""
        return notifications_support.clear_all_notifications(self)

    def get_notifications_unread_count(self) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : compteur pour le badge top bar."""
        return {"ok": True, "count": notifications_support.get_unread_count(self)}

    # ---------- v7.6.0 Vague 4 : Film standalone page ----------
    def _get_film_full_impl(self, row_id: str, run_id: Optional[str] = None) -> Dict[str, Any]:
        """v7.6.0 Vague 4 : toutes les infos d'un film pour la page standalone.

        Consolide : PlanRow, probe, perceptual V2, history, poster TMDb.
        """
        return film_support.get_film_full(self, run_id, row_id)

    # ---------- film history ----------
    def _get_film_history_impl(self, film_id: str) -> Dict[str, Any]:
        """Timeline complete d'un film a travers tous les runs."""
        return film_history_support.get_film_history(self, film_id)

    def _list_films_with_history_impl(self, limit: int = 50) -> Dict[str, Any]:
        """Liste des films du dernier run avec resume d'historique."""
        return film_history_support.list_films_with_history(self, limit)

    # ---------- planning ----------
    def _start_plan_impl(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Demarre un scan+plan en thread background. Retourne {run_id, ok}."""
        return run_flow_support.start_plan(self, settings, run_state_cls=RunState)

    def _get_status_impl(self, run_id: str, last_log_index: int = 0) -> Dict[str, Any]:
        """Retourne l'etat courant d'un run : progression, logs incrementaux, sante."""
        return run_flow_support.get_status(self, run_id, last_log_index)

    def _get_plan_impl(self, run_id: str) -> Dict[str, Any]:
        """Retourne la liste des PlanRow persistees dans plan.jsonl pour ce run."""
        return history_support.get_plan(self, run_id, normalize_user_path=_normalize_user_path)

    def _export_run_report_impl(self, run_id: str, fmt: str = "json") -> Dict[str, Any]:
        """Exporte le rapport du run au format json / csv / html."""
        return dashboard_support.export_run_report(self, run_id, fmt)

    def _export_full_library_impl(self) -> Dict[str, Any]:
        """RGPD Art. 20 — export portable de toute la bibliotheque (films +
        decisions + scores + settings sanitises) en JSON v1.0.

        Cf issue #95. Format documente dans docs/EXPORT_FORMAT.md.
        Le caller frontend serialise la reponse en JSON et offre le download.
        """
        from cinesort.ui.api import export_support

        return export_support.export_full_library(self)

    def export_run_nfo(self, run_id: str, overwrite: bool = False, dry_run: bool = True) -> Dict[str, Any]:
        """Génère des fichiers .nfo (Kodi/Jellyfin) pour chaque film du run."""
        if not self._is_valid_run_id(run_id):
            return {"ok": False, "message": "run_id invalide."}
        built, _paths = dashboard_support.build_run_report_payload(self, run_id)
        if not built.get("ok"):
            return built
        report = built.get("report") if isinstance(built.get("report"), dict) else {}
        rows = report.get("rows") or []
        if not rows:
            return {"ok": False, "message": "Aucune ligne dans le run."}

        from cinesort.app.export_support import export_nfo_for_run

        return export_nfo_for_run(rows, overwrite=bool(overwrite), dry_run=bool(dry_run))

    # ---------- validation persistence ----------
    def load_validation(self, run_id: str) -> Dict[str, Any]:
        """Recharge les decisions (approve/reject) persistees pour ce run."""
        return history_support.load_validation(self, run_id, normalize_user_path=_normalize_user_path)

    def save_validation(self, run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Persiste les decisions de validation dans validation.json (atomique)."""
        return run_flow_support.save_validation(self, run_id, decisions)

    def check_duplicates(self, run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Detecte les collisions de destination entre rows approuvees avant apply."""
        return run_flow_support.check_duplicates(self, run_id, decisions)

    def get_cleanup_residual_preview(self, run_id: str) -> Dict[str, Any]:
        """Preview du nettoyage de fin de run : dossiers vides + residuels identifies."""
        return run_read_support.get_cleanup_residual_preview(self, run_id)

    def get_auto_approved_summary(
        self,
        run_id: str,
        threshold: int = 85,
        enabled: bool = False,
        quarantine_corrupted: bool = False,
    ) -> Dict[str, Any]:
        """Resume des rows auto-approuvees selon le seuil de confiance (mode batch).

        M-2 audit QA 20260429 : `quarantine_corrupted` (defaut False) si True,
        les rows avec warnings d'integrite (integrity_header_invalid /
        integrity_probe_failed) sont auto-marquees pour quarantine et exclues
        de l'auto-approbation. Le frontend peut lire `auto_quarantine_row_ids`
        pour pre-rejeter ces films.
        """
        return run_read_support.get_auto_approved_summary(
            self,
            run_id,
            threshold=threshold,
            enabled=enabled,
            quarantine_corrupted=quarantine_corrupted,
        )

    def _get_tmdb_posters_impl(self, tmdb_ids: List[int], size: str = "w92") -> Dict[str, Any]:
        """Retourne les URLs de posters TMDb pour les IDs demandes (cache local)."""
        return tmdb_support.get_tmdb_posters(self, tmdb_ids, size)

    # ---------- apply ----------
    def _build_undo_preview_payload(
        self,
        run_id: str,
    ) -> Tuple[
        Dict[str, Any], Optional[SQLiteStore], Optional[state.RunPaths], Optional[Dict[str, Any]], List[Dict[str, Any]]
    ]:
        return apply_support.build_undo_preview_payload(self, run_id)

    def undo_last_apply_preview(self, run_id: str) -> Dict[str, Any]:
        """Preview (dry) de l'annulation du dernier batch apply reel (undo v1)."""
        return apply_support.undo_last_apply_preview(self, run_id)

    def undo_last_apply(self, run_id: str, dry_run: bool = True, atomic: bool = True) -> Dict[str, Any]:
        """Annule le dernier batch apply reel (undo v1). `dry_run=True` ne touche rien.

        P1.2 : atomic=True (defaut) refuse l'annulation si un fichier a ete
        remplace depuis l'apply (sha1 different). Rapport dans `preverify`.
        """
        return apply_support.undo_last_apply(self, run_id, dry_run, atomic=atomic)

    def undo_by_row_preview(self, run_id: str, batch_id: str = None) -> Dict[str, Any]:
        """Preview de l'annulation par film : resume par row_id du batch cible (undo v5)."""
        return apply_support.build_undo_by_row_preview(self, run_id, batch_id=batch_id)

    def undo_selected_rows(
        self,
        run_id: str,
        row_ids: list = None,
        dry_run: bool = True,
        batch_id: str = None,
        atomic: bool = True,
    ) -> Dict[str, Any]:
        """Annule selectivement les rows choisies (undo v5). `dry_run=True` ne touche rien.

        P1.2 : atomic=True refuse l'annulation si fichiers modifies depuis apply.
        """
        return apply_support.undo_selected_rows(
            self,
            run_id,
            row_ids or [],
            dry_run=dry_run,
            batch_id=batch_id,
            atomic=atomic,
        )

    def _list_apply_history_impl(self, run_id: str) -> Dict[str, Any]:
        """Liste les batches apply (reels + dry-run) d'un run, plus recent en premier."""
        return apply_support.list_apply_history(self, run_id)

    def apply(
        self,
        run_id: str,
        decisions: Dict[str, Dict[str, Any]],
        dry_run: bool,
        quarantine_unapproved: bool,
    ) -> Dict[str, Any]:
        result = apply_support.apply_changes(
            self,
            run_id,
            decisions,
            dry_run,
            quarantine_unapproved,
            cleanup_scope_label=_cleanup_scope_label,
            cleanup_status_label=_cleanup_status_label,
            cleanup_reason_label=_cleanup_reason_label,
        )
        if not dry_run:
            self._touch_event()
        return result

    def export_shareable_profile(
        self,
        name: str = "",
        author: str = "",
        description: str = "",
    ) -> Dict[str, Any]:
        """P4.3 : exporte le profil qualité actif au format communautaire.

        Format JSON structuré avec schema + metadata (name, author, description,
        exported_at) pour partage inter-utilisateurs. Retourne
        `{ok, content: str (JSON), filename_suggestion: str}`.

        Distinct de `export_quality_profile` (historique) qui renvoie le JSON
        brut du profil sans wrap.
        """
        from cinesort.domain.profile_exchange import (
            serialize_profile_export,
            wrap_profile_for_export,
        )
        from cinesort.domain.quality_score import default_quality_profile

        try:
            store, _runner = self._get_or_create_infra(self._state_dir)
        except (OSError, TypeError, ValueError):
            store = None
        try:
            active = store.get_active_quality_profile() if store else None
        except (OSError, TypeError, ValueError):
            active = None
        if active and isinstance(active.get("profile_json"), str):
            try:
                import json as _json

                profile = _json.loads(active["profile_json"])
            except (ValueError, TypeError):
                profile = default_quality_profile()
        else:
            profile = default_quality_profile()

        wrapped = wrap_profile_for_export(
            profile,
            name=str(name or ""),
            author=str(author or ""),
            description=str(description or ""),
            exporter=f"CineSort {self._app_version}",
        )
        content = serialize_profile_export(wrapped)
        safe_name = (name or "cinesort_profile").replace(" ", "_").replace("/", "_")[:80]
        filename = f"{safe_name}.cinesort.json"
        return {"ok": True, "content": content, "filename_suggestion": filename}

    def import_shareable_profile(
        self,
        content: str,
        activate: bool = True,
    ) -> Dict[str, Any]:
        """P4.3 : importe un profil depuis un JSON communautaire (avec metadata).

        Par défaut, active le profil importé (activate=True). Retourne les
        métadonnées extraites + le résultat de sauvegarde.

        Distinct de `import_quality_profile` (historique) qui accepte un profil
        brut sans wrapping schema.
        """
        from cinesort.domain.profile_exchange import (
            extract_import_metadata,
            parse_and_validate_import,
        )

        ok, profile, msg = parse_and_validate_import(content or "")
        meta = extract_import_metadata(content or "")
        if not ok:
            return {"ok": False, "message": msg, "meta": meta}

        try:
            store, _runner = self._get_or_create_infra(self._state_dir)
        except (OSError, TypeError, ValueError) as exc:
            return {"ok": False, "message": f"Store indisponible : {exc}", "meta": meta}
        if not store:
            return {"ok": False, "message": "Store indisponible.", "meta": meta}

        # save_quality_profile requiert profile_id + version. On les déduit
        # du profile importé, avec fallback sur l'app_version si absents.
        pid = str(profile.get("id") or "").strip()
        if not pid:
            # Générer un id depuis le name méta (ou timestamp)
            clean_name = (
                "".join(c for c in (meta.get("name") or "imported") if c.isalnum() or c in "_-")[:40] or "imported"
            )
            import time as _time

            pid = f"{clean_name}_{int(_time.time())}"
            profile["id"] = pid
        try:
            version = int(profile.get("version") or 1)
        except (TypeError, ValueError):
            version = 1

        try:
            store.save_quality_profile(
                profile_id=pid,
                version=version,
                profile_json=profile,
                is_active=bool(activate),
            )
        except (OSError, TypeError, ValueError, AttributeError) as exc:
            self.log_api_exception("import_quality_profile", exc)
            return {"ok": False, "message": f"Sauvegarde échouée : {exc}", "meta": meta}
        return {
            "ok": True,
            "meta": meta,
            "activated": bool(activate),
            "saved_profile_id": pid,
        }

    def _submit_score_feedback_impl(
        self,
        run_id: str,
        row_id: str,
        user_tier: str,
        category_focus: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """P4.1 : enregistrer un feedback utilisateur sur le scoring d'un film.

        user_tier : Platinum|Gold|Silver|Bronze|Reject (ou alias legacy).
        category_focus : 'video'|'audio'|'extras' si l'utilisateur pointe une catégorie.
        comment : texte libre optionnel.
        """
        from cinesort.domain.calibration import compute_tier_delta

        if not self._is_valid_run_id(run_id):
            return {"ok": False, "message": "run_id invalide."}
        if not row_id or not user_tier:
            return {"ok": False, "message": "row_id et user_tier sont requis."}

        found = self._find_run_row(run_id)
        if not found:
            return {"ok": False, "message": "Run introuvable."}
        _row, store = found

        try:
            qr = store.get_quality_report(run_id=run_id, row_id=str(row_id))
        except (KeyError, TypeError, ValueError, OSError):
            qr = None
        if not qr:
            return {"ok": False, "message": "Rapport qualité introuvable pour ce film."}

        computed_score = int(qr.get("score") or 0)
        computed_tier = str(qr.get("tier") or "")
        tier_delta = compute_tier_delta(computed_tier, str(user_tier))
        try:
            fb_id = store.insert_user_quality_feedback(
                run_id=str(run_id),
                row_id=str(row_id),
                computed_score=computed_score,
                computed_tier=computed_tier,
                user_tier=str(user_tier),
                tier_delta=tier_delta,
                category_focus=category_focus,
                comment=comment,
                app_version=self._app_version,
            )
        except (OSError, TypeError, ValueError) as exc:
            self.log_api_exception("submit_score_feedback", exc, run_id=run_id)
            return {"ok": False, "message": "Impossible d'enregistrer le feedback."}
        return {
            "ok": True,
            "feedback_id": fb_id,
            "computed_score": computed_score,
            "computed_tier": computed_tier,
            "user_tier": str(user_tier),
            "tier_delta": tier_delta,
        }

    def _delete_score_feedback_impl(self, feedback_id: int) -> Dict[str, Any]:
        """P4.1 : supprime un feedback utilisateur (cleanup / correction).

        Retourne `{ok, deleted_count}`.
        """
        try:
            store, _runner = self._get_or_create_infra(self._state_dir)
        except (OSError, TypeError, ValueError) as exc:
            return {"ok": False, "message": f"Store indisponible : {exc}"}
        if not store:
            return {"ok": False, "message": "Store indisponible."}
        try:
            count = store.delete_user_quality_feedback(feedback_id=int(feedback_id))
        except (OSError, TypeError, ValueError, AttributeError) as exc:
            self.log_api_exception("delete_score_feedback", exc)
            return {"ok": False, "message": "Suppression échouée."}
        return {"ok": True, "deleted_count": int(count)}

    def _get_calibration_report_impl(self) -> Dict[str, Any]:
        """P4.1 : agrège tous les feedbacks et propose un ajustement de poids.

        Retourne le rapport de biais + la suggestion de poids (ou None si
        pas de biais significatif).
        """
        from cinesort.domain.calibration import analyze_feedback_bias, suggest_weight_adjustment
        from cinesort.domain.quality_score import default_quality_profile

        try:
            store, _runner = self._get_or_create_infra(self._state_dir)
        except (OSError, TypeError, ValueError) as exc:
            return {"ok": False, "message": f"Store indisponible : {exc}"}
        if store is None:
            return {"ok": False, "message": "Store indisponible."}
        try:
            feedbacks = store.list_user_quality_feedback(limit=10_000)
        except (OSError, TypeError, ValueError) as exc:
            self.log_api_exception("get_calibration_report", exc)
            return {"ok": False, "message": "Lecture feedbacks échouée."}

        bias = analyze_feedback_bias(feedbacks)
        # Profil actif pour calculer la suggestion
        try:
            prof = store.get_active_quality_profile()
        except (OSError, TypeError, ValueError):
            prof = None
        if prof and isinstance(prof.get("profile_json"), str):
            try:
                import json as _json

                payload = _json.loads(prof["profile_json"])
                current_weights = payload.get("weights") or {}
            except (ValueError, TypeError):
                current_weights = {}
        else:
            current_weights = default_quality_profile().get("weights", {})

        suggestion = suggest_weight_adjustment(bias, current_weights) if current_weights else None
        return {
            "ok": True,
            "bias": bias,
            "current_weights": current_weights,
            "suggestion": suggestion,
            "sample_feedbacks": feedbacks[:20],
        }

    def export_apply_audit(
        self,
        run_id: str,
        batch_id: Optional[str] = None,
        as_format: str = "json",
    ) -> Dict[str, Any]:
        """P2.3 : journal d'audit JSONL d'un apply (complémentaire à apply_operations).

        as_format : "json" (liste d'événements), "jsonl" (texte brut), "csv".
        """
        return apply_support.export_apply_audit(self, run_id, batch_id, as_format=as_format)

    def _build_apply_preview_impl(
        self,
        run_id: str,
        decisions: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """P1.3 : plan structuré "avant/après" des déplacements, par film.

        Pure : ne touche ni filesystem ni BDD. Enrichit chaque film avec
        tier/confidence/warnings pour affichage visuel par l'UI.
        """
        return apply_support.build_apply_preview(
            self,
            run_id,
            decisions,
            cleanup_scope_label=_cleanup_scope_label,
            cleanup_status_label=_cleanup_status_label,
            cleanup_reason_label=_cleanup_reason_label,
        )

    def _cancel_run_impl(self, run_id: str) -> Dict[str, Any]:
        """Demande l'annulation d'un run en cours (pose cancel_requested=1)."""
        return history_support.cancel_run(self, run_id)

    # ---------- Reset (V3-09) ----------
    def _reset_all_user_data_impl(self, confirmation: str = "") -> Dict[str, Any]:
        """V3-09 — Reset toutes les donnees user (avec backup ZIP automatique)."""
        from cinesort.ui.api import reset_support

        return reset_support.reset_all_user_data(self, confirmation)

    def _get_user_data_size_impl(self) -> Dict[str, Any]:
        """V3-09 — Taille actuelle du user-data (pour affichage UI Danger Zone)."""
        from cinesort.ui.api import reset_support

        return {"data": reset_support.get_user_data_size(self)}

    # ---------- misc ----------
    def open_path(self, path: str) -> Dict[str, Any]:
        return history_support.open_path(
            self,
            path,
            default_root=DEFAULT_ROOT,
            normalize_user_path=_normalize_user_path,
        )

    # ---------- support / logs (V3-13) ----------
    def get_log_paths(self) -> Dict[str, Any]:
        """V3-13 — Retourne les chemins des logs (pour affichage UI + copie)."""
        log_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CineSort", "logs")
        return {
            "data": {
                "log_dir": log_dir,
                "main_log": os.path.join(log_dir, "cinesort.log"),
                "exists": os.path.isdir(log_dir),
            }
        }

    def open_logs_folder(self) -> Dict[str, Any]:
        """V3-13 — Ouvre le dossier des logs dans l'explorateur Windows.

        Cf issue #72 (audit-2026-05-12:e3f5) : si la requete vient d'un client
        REST distant (LAN), on refuse l'ouverture pour eviter le DoS UX (un
        attaquant authentifie pouvait spammer cet endpoint et ouvrir des
        fenetres Explorer en chaine sur le PC server). Operation autorisee
        uniquement depuis le caller local (desktop natif ou 127.0.0.1).
        """
        from cinesort.infra.log_context import is_remote_request

        if is_remote_request():
            return {
                "ok": False,
                "error": "Operation locale uniquement (l'ouverture de l'explorateur n'est pas autorisee via REST distant).",
            }
        log_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CineSort", "logs")
        if not os.path.isdir(log_dir):
            return {"ok": False, "error": "Dossier logs introuvable", "log_dir": log_dir}
        try:
            os.startfile(log_dir)  # type: ignore[attr-defined]
            return {"ok": True, "opened": log_dir}
        except OSError as exc:
            return {"ok": False, "error": str(exc), "log_dir": log_dir}
