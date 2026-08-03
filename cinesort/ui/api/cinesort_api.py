from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import cinesort.app.email_report as _email_report_mod
import cinesort.app.plugin_hooks as _plugin_hooks_mod
import cinesort.app.watchlist as _watchlist_mod
import cinesort.domain.core as core
import cinesort.infra.jellyfin_client as _jellyfin_mod
import cinesort.infra.network_utils as _network_utils_mod
import cinesort.infra.plex_client as _plex_mod
import cinesort.infra.radarr_client as _radarr_mod
import cinesort.infra.rest_server as _rest_server_mod
import cinesort.infra.state as state
from cinesort.app import JobRunner
from cinesort.app import updater as _updater
from cinesort.app.export_support import export_nfo_for_run
from cinesort.app.jellyfin_validation import build_sync_report
from cinesort.app.notify_service import NotifyService
from cinesort.app.plan_support import plan_row_from_jsonable
from cinesort.app.radarr_sync import build_radarr_report, get_upgrade_candidates
from cinesort.app.watcher import FolderWatcher
from cinesort.domain import i18n_messages as _i18n_messages_mod
from cinesort.domain.calibration import analyze_feedback_bias, compute_tier_delta, suggest_weight_adjustment
from cinesort.domain.conversions import to_bool as _to_bool
from cinesort.domain.custom_rules import ACTIONS, FIELD_PATHS, OPERATORS, validate_rules
from cinesort.domain.custom_rules_templates import list_templates
from cinesort.domain.film_history import _load_plan_rows_from_jsonl, _resolve_run_dir
from cinesort.domain.i18n_messages import SUPPORTED_LOCALES, get_locale, set_locale, t
from cinesort.domain.naming import (
    PRESETS,
    PREVIEW_MOCK_CONTEXT,
    build_naming_context,
    format_movie_folder,
    validate_template,
)
from cinesort.domain.profile_exchange import (
    extract_import_metadata,
    parse_and_validate_import,
    serialize_profile_export,
    wrap_profile_for_export,
)
from cinesort.domain.quality_score import default_quality_profile
from cinesort.infra.db import SQLiteStore
from cinesort.infra.fs_safety import safe_path_exists
from cinesort.infra.local_secret_store import protection_available as _protection_available
from cinesort.infra.log_context import is_remote_request
from cinesort.infra.omdb_client import OmdbClient
from cinesort.infra.probe import detect_probe_tools, manage_probe_tools, validate_tool_path
from cinesort.infra.tmdb_client import TmdbClient
from cinesort.ui.api import (
    apply_support,
    dashboard_cache_support,
    dashboard_support,
    demo_support,
    diagnostics_support,
    export_support,
    film_history_support,
    film_support,
    history_support,
    library_support,
    notifications_support,
    perceptual_support,
    probe_support,
    profiles_support,
    quality_internal_support,
    quality_profile_support,
    quality_report_support,
    quality_support,
    reset_support,
    run_control_support,
    run_data_support,
    run_flow_support,
    run_read_support,
    runtime_support,
    settings_support,
    tmdb_support,
)
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api._responses import safe_integration_error as _safe_integration_error
from cinesort.ui.api._validators import clamp_non_negative_int, clamp_timeout
from cinesort.ui.api.facades import (
    IntegrationsFacade,
    LibraryFacade,
    QualityFacade,
    RunFacade,
    RuntimeFacade,
    SettingsFacade,
)
from cinesort.ui.api.quality_simulator_support import (
    clear_cache as _sim_clear,
)
from cinesort.ui.api.quality_simulator_support import (
    run_simulation,
    save_custom_preset,
)
from cinesort.ui.api.settings_support import (
    _SECRET_MASK,
)
from cinesort.ui.api.settings_support import (
    build_cfg_from_run_row as _build_cfg_from_run_row,
)
from cinesort.ui.api.settings_support import (
    build_cfg_from_settings as _build_cfg_from_settings_payload,
)
from cinesort.ui.api.settings_support import (
    normalize_user_path as _normalize_user_path,
)
from cinesort.ui.api.settings_support import (
    read_settings as _read_settings,
)

logger = logging.getLogger(__name__)

# Compat module-level export kept for existing callers and tests.
protection_available = _protection_available


# M-07 (Vague M) : la classe ``RunState`` a ete extraite dans
# ``cinesort.ui.api._run_state``. Le re-export ci-dessous preserve les imports
# historiques ``from cinesort.ui.api.cinesort_api import RunState`` utilises par
# les tests (test_apply_progress, test_vague_h_concurrency, ...) et les facades
# (apply_support, run_flow_support, ...).
#
# Note de design : ``MAX_RUN_LOG_ITEMS`` reste aussi defini ci-dessous (cf
# L304) pour back-compat module-level. La constante dans ``_run_state.py`` est
# la reference, celle d'ici doit rester alignee.
from cinesort.ui.api._run_state import RunState  # noqa: F401  (back-compat re-export)


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
        # Lock pour proteger la sequence read-modify-write des settings (fix TOCTOU
        # dans _set_locale_impl : sans ce verrou, un save_settings concurrent
        # execute entre _get_settings_impl() et _save_settings_impl(current) est
        # ecrase par le payload 'current' lu avant la mutation parallele).
        self._settings_write_lock = threading.RLock()
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
        self.run = RunFacade(self)
        self.settings = SettingsFacade(self)
        self.quality = QualityFacade(self)
        self.integrations = IntegrationsFacade(self)
        self.library = LibraryFacade(self)
        # Spec 12-aide.md (Phase 4 — ecran Aide) : 4 endpoints diag/logs/docs.
        self.runtime = RuntimeFacade(self)

    def _touch_event(self) -> None:
        """Met a jour le timestamp du dernier evenement significatif (scan, apply, settings)."""
        self._last_event_ts = time.time()

    def _dispatch_plugin_hook(self, event: str, data: Dict[str, Any]) -> None:
        """Dispatch un hook plugin si plugins_enabled. Non-bloquant."""
        try:
            settings = self._get_settings_impl()
            if not settings.get("plugins_enabled"):
                return
            timeout = int(settings.get("plugins_timeout_s") or 30)
            # NB : module-style pour permettre patch("cinesort.app.plugin_hooks.dispatch_hook").
            _plugin_hooks_mod.dispatch_hook(event, data, timeout_s=timeout)
        except (ImportError, KeyError, OSError, TypeError, ValueError):
            pass  # Ne jamais bloquer pour un plugin

    def _dispatch_email(self, event: str, data: Dict[str, Any]) -> None:
        """Dispatch un rapport email si email_enabled. Non-bloquant."""
        try:
            # AUDIT 2026-06-10 : secrets en clair (email_smtp_password) pour SMTP.
            settings = self._internal_settings()
            # NB : module-style pour permettre patch("cinesort.app.email_report.dispatch_email").
            _email_report_mod.dispatch_email(settings, event, data)
        except (ImportError, KeyError, OSError, TypeError, ValueError):
            pass  # Ne jamais bloquer pour un email

    def _is_valid_run_id(self, run_id: Any) -> bool:
        rid = str(run_id or "").strip()
        return bool(RUN_ID_RE.fullmatch(rid))

    def _resolve_payload_state_dir(self, settings: Dict[str, Any]) -> Tuple[Path, bool]:
        return settings_support.resolve_payload_state_dir(settings, default_state_dir=self._get_state_dir())

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
            current_state_dir=self._get_state_dir(),
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
            current_state_dir=self._get_state_dir(),
            default_root=DEFAULT_ROOT,
            missing_message=missing_message,
        )

    def _get_state_dir(self) -> Path:
        """Fix audit 2026-05-25 (v1.5.3) Vague H : lecture atomique de _state_dir.

        Les mutations de ``self._state_dir`` (dans ``_save_settings_impl``) sont
        protegees par ``self._state_dir_lock``. Sans helper, les lectures
        directes ``self._state_dir`` pouvaient observer un Path mid-mutation
        (rare mais possible quand un endpoint REST parallele tourne pendant
        un ``save_settings``). On retourne une reference atomique sous le
        lock — Path etant immutable, le snapshot reste valide hors lock.
        """
        with self._state_dir_lock:
            return self._state_dir

    def _acquire_apply_slot(self, run_id: str) -> bool:
        with self._apply_guard_lock:
            if run_id in self._apply_inflight_run_ids:
                return False
            self._apply_inflight_run_ids.add(run_id)
            return True

    def _release_apply_slot(self, run_id: str) -> None:
        with self._apply_guard_lock:
            self._apply_inflight_run_ids.discard(run_id)

    @contextmanager
    def _apply_slot_guard(self, run_id: str):
        """Fix audit 2026-05-25 (v1.5.3) Vague H : libere le slot meme en cas d'exception.

        Remplace le pattern manuel ``_acquire_apply_slot`` / ``_release_apply_slot``
        eparpille (5 sites dans apply_support.py) ou un crash du caller laissait
        le slot occupe indefiniment. Les callers DOIVENT utiliser ce CM :

            with api._apply_slot_guard(run_id) as acquired:
                if not acquired:
                    return _err_response(t("errors.apply_already_in_progress"), ...)
                # ... reste de la logique apply ...

        Yield ``True`` si le slot a ete acquis (run_id pas deja in-flight),
        ``False`` sinon. Dans tous les cas le slot est libere a la sortie du
        ``with`` (succes, return early, exception).
        """
        acquired = self._acquire_apply_slot(run_id)
        try:
            yield acquired
        finally:
            if acquired:
                self._release_apply_slot(run_id)

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
        resolved_state_dir = state_dir if isinstance(state_dir, Path) else self._get_state_dir()
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
                resolved_store.run.insert_error(
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
        # PRAGMA-02 fix : passer state_dir pour que mode "auto" resolve la
        # valeur effective (4 NAS / 8 SSD) au lieu de retomber sur 1 sequentiel.
        return _build_cfg_from_settings_payload(
            settings,
            root=root,
            default_collection_folder_name=DEFAULT_COLLECTION_FOLDER_NAME,
            default_empty_folders_folder_name=DEFAULT_EMPTY_FOLDERS_FOLDER_NAME,
            default_residual_cleanup_folder_name=DEFAULT_RESIDUAL_CLEANUP_FOLDER_NAME,
            state_dir=self._get_state_dir(),
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
            state_dir=self._get_state_dir(),
            default_root=DEFAULT_ROOT,
            default_state_dir_example=DEFAULT_STATE_DIR_EXAMPLE,
            default_collection_folder_name=DEFAULT_COLLECTION_FOLDER_NAME,
            default_empty_folders_folder_name=DEFAULT_EMPTY_FOLDERS_FOLDER_NAME,
            default_residual_cleanup_folder_name=DEFAULT_RESIDUAL_CLEANUP_FOLDER_NAME,
            default_probe_backend=DEFAULT_PROBE_BACKEND,
            debug_enabled=_env_truthy("CINESORT_DEBUG"),
        )

    def _internal_settings(self) -> Dict[str, Any]:
        """Settings AVEC defaults mais secrets EN CLAIR — usage interne uniquement
        (jamais renvoye au frontend). Pour les consommateurs qui construisent un
        client Jellyfin/Plex/Radarr/SMTP : sans ca ils relisaient le masque
        "••••••••" et l'envoyaient comme credential (AUDIT 2026-06-10 -> 401).

        Implementation : on part du payload masque (_get_settings_impl, mockable
        en test) puis on dé-masque chaque secret depuis le disque — extension du
        pattern _unmask_or_stored a tout le payload. Un secret deja en clair
        (valeur != masque, ex cle de test injectee) est conserve tel quel."""
        settings = self._get_settings_impl()
        raw = _read_settings(self._get_state_dir())
        for field in settings_support._SECRET_FIELDS:
            if str(settings.get(field) or "").strip() == _SECRET_MASK:
                settings[field] = str(raw.get(field) or "").strip()
        return settings

    def _save_settings_impl(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        # Lock partage avec _set_locale_impl pour serialiser les sequences
        # read-modify-write des settings et fermer la fenetre TOCTOU.
        with self._settings_write_lock:
            return self._save_settings_impl_locked(settings)

    def _save_settings_impl_locked(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        # B05-401-INCOHERENT (Fix A) : capturer l'ancien token AVANT save pour
        # detecter le changement et hot-reloader le handler REST en memoire.
        # Sans ce hot-swap, settings.json a le NOUVEAU token mais le handler
        # valide encore avec l'ANCIEN -> 401 incoherents jusqu'au prochain
        # restart manuel. Lecture defensive : si _get_settings_impl echoue
        # pour une raison quelconque, on ne bloque pas la sauvegarde.
        try:
            old_settings = self._get_settings_impl()
        except (OSError, KeyError, TypeError, ValueError):
            old_settings = {}
        old_token = str((old_settings or {}).get("rest_api_token") or "").strip()

        state_dir, result = settings_support.save_settings_payload(
            settings,
            current_state_dir=self._get_state_dir(),
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
            # B05-401-INCOHERENT (Fix A) : hot-reload du token REST si change
            # sans redemarrer le serveur (evite la coupure des sessions
            # legitimes). Si le serveur n'expose pas update_auth_token
            # (versions anterieures), on no-op silencieusement -> backward compat.
            new_token = str(settings.get("rest_api_token") or "").strip()
            if new_token != old_token and self._rest_server is not None:
                updater_fn = getattr(self._rest_server, "update_auth_token", None)
                if callable(updater_fn):
                    try:
                        updater_fn(new_token)
                    except (AttributeError, RuntimeError, TypeError) as exc:
                        logger.warning(
                            "rest: hot-swap du token REST echoue (%s) — un restart manuel"
                            " du serveur sera necessaire pour appliquer le nouveau token.",
                            exc,
                        )
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
            _i18n_messages_mod.set_locale(str(locale))
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
        normalized = str(locale or "").strip().lower()
        if normalized not in SUPPORTED_LOCALES:
            return _err_response(
                t("errors.invalid_locale", locale=locale),
                category="validation",
                level="info",
                log_module=__name__,
                locale=get_locale(),
            )
        # 1) Activation immediate cote backend
        set_locale(normalized)
        # 2) Persistance dans settings.json (passe par save_settings_payload pour
        #    deduper toute la logique de validation/normalisation/backup).
        # Fix TOCTOU : la sequence get -> mutate -> save doit etre atomique pour
        # eviter qu'un save_settings concurrent execute entre les deux appels
        # soit integralement ecrase par le payload 'current' (qui contient les
        # valeurs lues avant la mutation parallele).
        with self._settings_write_lock:
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
    def _start_demo_mode_impl(self) -> Dict[str, Any]:
        """V3-05 : active le mode démo (15 films fictifs + run + plan.jsonl)."""
        result = demo_support.start_demo_mode(self)
        if result.get("ok"):
            self._touch_event()
        return result

    def _stop_demo_mode_impl(self) -> Dict[str, Any]:
        """V3-05 : désactive le mode démo (supprime runs + quality_reports + run_dir)."""
        result = demo_support.stop_demo_mode(self)
        if result.get("ok"):
            self._touch_event()
        return result

    def _is_demo_mode_active_impl(self) -> Dict[str, Any]:
        """V3-05 : True si au moins un run is_demo est présent en BDD."""
        return {"ok": True, "active": bool(demo_support.is_demo_active(self))}

    def _sync_watcher(self, settings: Dict[str, Any]) -> None:
        """Demarre ou arrete le watcher selon les settings."""
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
    def _get_event_ts_impl(self) -> Dict[str, Any]:
        """Retourne le timestamp du dernier evenement significatif (scan/apply/settings).

        Utilise par le desktop pour detecter les changements et rafraichir (parite dashboard).
        """
        return {
            "ok": True,
            "last_event_ts": float(self._last_event_ts),
            "last_settings_ts": float(self._last_settings_ts),
        }

    def _get_server_info_impl(self) -> Dict[str, Any]:
        """Retourne les infos du serveur REST (IP, port, URL dashboard)."""
        server = self._rest_server
        if server is None or not getattr(server, "is_running", False):
            return _err_response("Serveur REST non demarre.", category="state", level="info", log_module=__name__)
        # NB : module-style pour permettre patch("cinesort.infra.network_utils.X").
        ip = _network_utils_mod.get_local_ip()
        port = getattr(server, "_port", 8642)
        is_https = getattr(server, "_is_https", False)
        url = _network_utils_mod.build_dashboard_url(ip, port, is_https)
        return {"ok": True, "ip": ip, "port": port, "https": is_https, "dashboard_url": url}

    def _reveal_rest_token_impl(self) -> Dict[str, Any]:
        """AUDIT 2026-06-14 (R7-10) : revele le Bearer REST en CLAIR pour les
        boutons "Afficher/Copier la cle" (Statut Acces distant + Parametres).

        Le GET settings masque rest_api_token (-> '********'), donc afficher/
        copier exposait les puces -> 401 sur l'appareil distant. Cet endpoint
        retourne la vraie valeur, mais UNIQUEMENT en local (is_remote_request
        False) : un client distant ne peut jamais exfiltrer le token via l'API.
        """
        if is_remote_request():
            return _err_response(
                "Action disponible en local uniquement.",
                category="permission",
                level="info",
                log_module=__name__,
            )
        settings = self._internal_settings()
        token = str(settings.get("rest_api_token") or "")
        return {"ok": True, "rest_api_token": token}

    def _get_dashboard_qr_impl(self) -> Dict[str, Any]:
        """Retourne un QR code SVG inline pour l'URL du dashboard distant."""
        import io

        _log = logging.getLogger(__name__)

        info = self._get_server_info_impl()
        if not info.get("ok"):
            # Fallback : construire l'URL depuis les settings
            settings = self._get_settings_impl()
            ip = _network_utils_mod.get_local_ip()
            port = int(settings.get("rest_api_port") or 8642)
            is_https = bool(settings.get("rest_api_https_enabled"))
            url = _network_utils_mod.build_dashboard_url(ip, port, is_https)
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
            return _err_response(
                t("errors.qr_generation_failed", detail=str(exc)),
                category="runtime",
                level="error",
                log_module=__name__,
            )

        _log.info("api: QR code genere pour %s", url)
        return {"ok": True, "svg": svg_str, "url": url}

    def _check_for_updates_impl(self) -> Dict[str, Any]:
        """V3-12 — Force un check MAJ immediat (bouton "Verifier maintenant").

        Ignore le cache existant, interroge GitHub Releases et stocke le
        resultat dans le cache local pour les appels ``get_update_info``
        suivants. Retourne un dict toujours non vide avec le statut courant.
        """
        settings = self._get_settings_impl()
        repo = str(settings.get("update_github_repo") or "").strip()
        if not repo:
            return _err_response(
                "Aucun depot GitHub configure (update_github_repo).",
                category="config",
                level="info",
                log_module=__name__,
                data=_updater.info_to_dict(None, self._app_version),
            )
        cache_path = _updater.default_cache_path(self._get_state_dir())
        info = _updater.force_check(self._app_version, repo, cache_path=cache_path)
        try:
            settings["update_last_check_ts"] = time.time()
            self._save_settings_impl(settings)
        except (KeyError, OSError, TypeError, ValueError):
            pass  # ne pas bloquer le check si la persistence echoue
        return {"ok": True, "data": _updater.info_to_dict(info, self._app_version)}

    def _get_update_info_impl(self, force_refresh: bool = False) -> Dict[str, Any]:
        """V3-12 — Retourne le dernier resultat connu (cache).

        Sert l'info instantanement apres le check au boot. Si le cache est
        absent ou expire, ``data.update_available`` vaut False.

        Fix audit 2026-05-24 (v1.5.2) Vague E : si ``force_refresh=True``, on
        delegue a ``_check_for_updates_impl`` pour forcer un appel reseau
        immediat (ignore le cache TTL). Ainsi l'UI peut utiliser un seul
        endpoint ``runtime/get_update_info`` que ce soit pour servir le cache
        (boot) ou pour declencher un check manuel (bouton "Verifier maintenant").
        """
        if force_refresh:
            return self._check_for_updates_impl()
        cache_path = _updater.default_cache_path(self._get_state_dir())
        info = _updater.get_cached_info(self._app_version, cache_path=cache_path)
        return {"ok": True, "data": _updater.info_to_dict(info, self._app_version)}

    def _restart_api_server_impl(self) -> Dict[str, Any]:
        """Arrete et relance le serveur REST avec les settings actuels."""
        _log = logging.getLogger(__name__)

        old_server = self._rest_server
        if old_server and hasattr(old_server, "stop"):
            old_server.stop()
            self._rest_server = None

        # AUDIT 2026-06-10 : _internal_settings (token en clair) — _get_settings_impl
        # masquait rest_api_token, le serveur redemarrait avec Bearer "••••••••"
        # (constante publique) et tout client legitime recevait 401.
        settings = self._internal_settings()
        if not settings.get("rest_api_enabled"):
            return _err_response(
                "API REST desactivee dans les reglages.", category="runtime", level="warning", log_module=__name__
            )
        token = str(settings.get("rest_api_token") or "").strip()
        if not token:
            return _err_response("Aucun token configure.", category="state", level="info", log_module=__name__)

        port = int(settings.get("rest_api_port") or 8642)
        # AUDIT 2026-06-10 : repliquer host + cors_origin du boot (app.py:351-360).
        # Sans host, le serveur rebind silencieusement sur 127.0.0.1 -> perte de
        # l'exposition LAN/dashboard distant ; sans cors_origin, retour a "*".
        host = "0.0.0.0" if settings.get("rest_api_enabled") else "127.0.0.1"
        # NB : module-style pour permettre patch("cinesort.infra.rest_server.RestApiServer").
        server = _rest_server_mod.RestApiServer(
            self,
            port=port,
            token=token,
            cors_origin=str(settings.get("rest_api_cors_origin") or ""),
            https_enabled=bool(settings.get("rest_api_https_enabled")),
            cert_path=str(settings.get("rest_api_cert_path") or ""),
            key_path=str(settings.get("rest_api_key_path") or ""),
            host=host,
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
    def _reset_incremental_cache_impl(self) -> Dict[str, Any]:
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
        _log = logging.getLogger(__name__)

        # BUG : CineSortApi n'a PAS d'attribut self.store — le store est
        # stocke dans self._infra_by_state_dir et recupere via
        # _get_or_create_infra(). L'ancien code faisait `store = self.store`
        # → AttributeError non catchee → pywebview remontait l'exception au JS
        # → fallback "Purge du cache impossible".
        try:
            store, _runner = self._get_or_create_infra(self._get_state_dir())
        except Exception as exc:
            _log.exception("api: reset_incremental_cache echec init store")
            return _err_response(
                f"Store indisponible : {type(exc).__name__}: {exc}",
                category="state",
                level="error",
                log_module=__name__,
            )

        try:
            counts = store.scan.clear_all_incremental_caches()
        except Exception as exc:
            # Toutes les erreurs possibles (sqlite3.Error, OSError, AttributeError,
            # bug inattendu) sont remontees a l'utilisateur sous forme de message
            # clair plutot que de laisser pywebview transformer l'exception en
            # fallback JS generique "Purge du cache impossible".
            _log.exception("api: reset_incremental_cache echec purge")
            return _err_response(
                f"Purge echouee : {type(exc).__name__}: {exc}",
                category="runtime",
                level="error",
                log_module=__name__,
            )

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

    # ---------- VO-A-NAS : benchmark perf SQLite sur stockage cible ----------
    def _run_nas_benchmark_impl(
        self,
        n_writes: int = 1000,
        n_reads: int = 10000,
    ) -> Dict[str, Any]:
        """VO-A-NAS : declenche un benchmark perf SQLite sur le stockage cible.

        Cree une table dediee dans la DB CineSort active, mesure les
        percentiles p50/p95/p99 ecritures + lectures, puis DROP la table.
        Le rapport est sauvegarde sous
        ``<state_dir>/diagnostics/nas_benchmark_<ts>.json``.

        Args:
            n_writes: nombre d'INSERT a executer (clamp 1..100000).
            n_reads: nombre de SELECT a executer (clamp 1..1000000).

        Returns:
            dict de la forme {ok, result, report_path}. En cas d'erreur d'init
            DB : {ok: False, error: ...} via _err_response.
        """
        from cinesort.infra.db import db_path_for_state_dir
        from cinesort.infra.db.nas_validation import (
            run_nas_benchmark,
            write_benchmark_report,
        )

        _log = logging.getLogger(__name__)

        # Clamp pour eviter qu'un appel API distant ne lance un bench de 10M
        # lignes qui geleait la DB pendant 30 minutes.
        try:
            n_writes_clamped = clamp_non_negative_int(n_writes, default=1000)
        except (TypeError, ValueError):
            n_writes_clamped = 1000
        try:
            n_reads_clamped = clamp_non_negative_int(n_reads, default=10000)
        except (TypeError, ValueError):
            n_reads_clamped = 10000
        n_writes_clamped = max(1, min(n_writes_clamped, 100_000))
        n_reads_clamped = max(1, min(n_reads_clamped, 1_000_000))

        state_dir = self._get_state_dir()
        try:
            db_path = db_path_for_state_dir(state_dir)
        except Exception as exc:  # noqa: BLE001 -- chemin invalide / OSError
            _log.exception("api: run_nas_benchmark resolve db_path echec")
            return _err_response(
                f"Resolution chemin DB impossible : {type(exc).__name__}: {exc}",
                category="state",
                level="error",
                log_module=__name__,
            )

        # Best-effort : si la DB n'existe pas encore (cas test / 1er boot
        # tres precoce), on cree au moins le dossier parent pour que
        # sqlite3.connect puisse instancier le fichier.
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _log.warning("api: run_nas_benchmark mkdir parent echec : %s", exc)

        try:
            result = run_nas_benchmark(
                db_path,
                n_writes=n_writes_clamped,
                n_reads=n_reads_clamped,
            )
        except Exception as exc:  # noqa: BLE001 -- protection enveloppe
            _log.exception("api: run_nas_benchmark echec")
            return _err_response(
                f"Benchmark echec : {type(exc).__name__}: {exc}",
                category="runtime",
                level="error",
                log_module=__name__,
            )

        report_path: Optional[Path] = None
        try:
            report_path = write_benchmark_report(result, state_dir)
        except OSError as exc:
            _log.warning("api: run_nas_benchmark write_report echec : %s", exc)

        return {
            "ok": bool(result.get("ok", False)),
            "result": result,
            "report_path": str(report_path) if report_path else None,
        }

    # ---------- Helper masque -> cle stockee ----------
    def _unmask_or_stored(self, field: str, value: str) -> str:
        """UX fix : si le frontend renvoie le masque "••••••••" parce que la cle
        est deja chiffree DPAPI, on substitue par la cle stockee en interne.

        Cas typique : utilisateur clique "Tester la connexion" sans retaper la cle.
        Avant ce fix : test echouait avec 401 car la cle envoyee etait le masque.
        Apres : test utilise la vraie cle stockee dans settings.json (DPAPI).
        """

        if str(value or "").strip() == _SECRET_MASK:
            data = _read_settings(self._get_state_dir())
            return str(data.get(field) or "").strip()
        return str(value or "").strip()

    # ---------- TMDb ----------
    def _test_tmdb_key_impl(self, api_key: str, state_dir: str, timeout_s: float = 10.0) -> Dict[str, Any]:
        api_key = self._unmask_or_stored("tmdb_api_key", api_key)
        # Audit C7 P1 : borner timeout_s entre 1s et 60s pour eviter qu'un
        # caller (REST distant compromis) ne bloque le thread API ou ne crashe
        # le client HTTP avec timeout_s=0/NaN/None/str.
        timeout_s = clamp_timeout(timeout_s)
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
        # Audit C7 P1 : borner timeout_s entre 1s et 60s.
        timeout_s = clamp_timeout(timeout_s)
        return settings_support.test_jellyfin_connection(url, api_key, timeout_s)

    def _get_jellyfin_libraries_impl(self) -> Dict[str, Any]:
        """Retourne les bibliothèques Jellyfin configurées."""
        data = _read_settings(self._get_state_dir())
        url = str(data.get("jellyfin_url") or "").strip()
        api_key = str(data.get("jellyfin_api_key") or "").strip()
        user_id = str(data.get("jellyfin_user_id") or "").strip()
        timeout_s = float(data.get("jellyfin_timeout_s") or 10.0)
        if not url or not api_key:
            return _err_response("Jellyfin non configuré.", category="state", level="info", log_module=__name__)

        try:
            # NB : module-style pour permettre patch("cinesort.infra.jellyfin_client.JellyfinClient").
            client = _jellyfin_mod.JellyfinClient(url, api_key, timeout_s=timeout_s)
            if not user_id:
                info = client.validate_connection()
                if not info.get("ok"):
                    return _err_response(
                        info.get("error", "Connexion échouée."),
                        category="runtime",
                        level="warning",
                        log_module=__name__,
                    )
                user_id = info.get("user_id", "")
            libraries = client.get_libraries(user_id)
            movies_count = client.get_movies_count(user_id)
            return {"ok": True, "libraries": libraries, "movies_count": movies_count}
        except _jellyfin_mod.JellyfinError as exc:
            # Sprint 2 audit P0 #4 : ne pas leak exc string (peut contenir URL/token/path).
            return _safe_integration_error(exc, category="resource", log_module=__name__)

    # ---------- Email ----------
    def _test_email_report_impl(self) -> Dict[str, Any]:
        """Envoie un email test avec des donnees mock."""
        settings = self._internal_settings()  # secrets en clair pour SMTP (AUDIT 2026-06-10)
        if not settings.get("email_smtp_host") or not settings.get("email_to"):
            return _err_response(
                "Configurez d'abord le serveur SMTP et le destinataire.",
                category="validation",
                level="info",
                log_module=__name__,
            )
        mock_data = {
            "run_id": "test",
            "ts": time.time(),
            "data": {"rows": 42, "folders_scanned": 42, "roots": ["D:/Films"]},
        }
        # NB : module-style pour permettre patch("cinesort.app.email_report.send_email_report").
        ok = _email_report_mod.send_email_report(settings, "post_scan", mock_data)
        return {"ok": ok, "message": "Email test envoye." if ok else "Echec de l'envoi. Verifiez les parametres SMTP."}

    # ---------- Jellyfin validation croisee ----------
    def _get_jellyfin_sync_report_impl(self, run_id: str = "") -> Dict[str, Any]:
        """Compare la bibliotheque locale avec Jellyfin. Retourne le rapport de coherence."""
        settings = self._internal_settings()  # jellyfin_api_key en clair (AUDIT 2026-06-10)
        if not settings.get("jellyfin_enabled"):
            return _err_response("Jellyfin non configure.", category="state", level="info", log_module=__name__)
        jf_url = str(settings.get("jellyfin_url") or "").strip()
        jf_key = str(settings.get("jellyfin_api_key") or "").strip()
        jf_user_id = str(settings.get("jellyfin_user_id") or "").strip()
        if not jf_url or not jf_key:
            return _err_response(
                "URL ou cle API Jellyfin manquante.", category="validation", level="info", log_module=__name__
            )

        # Charger les PlanRows du dernier run
        state_dir = Path(self._get_state_dir())
        store, _runner = self._get_or_create_infra(state_dir)

        runs = store.run.get_runs_summary(limit=5)
        target_run_id = run_id.strip() if run_id else ""
        if not target_run_id:
            for r in runs:
                if str(r.get("status") or "") == "DONE":
                    target_run_id = str(r.get("run_id") or "")
                    break
        if not target_run_id:
            return _err_response("Aucun run termine disponible.", category="state", level="info", log_module=__name__)
        if not self._is_valid_run_id(target_run_id):
            return _err_response(
                "Identifiant de run invalide.",
                category="validation",
                level="warning",
                log_module=__name__,
            )

        # Audit 2026-06-02 : le vrai dossier de run est `runs/tri_films_{run_id}`
        # (cf state.new_run, runtime_support.run_paths_for, job_runner). Le chemin
        # etait construit sans le prefixe -> plan.jsonl jamais trouve -> "Aucun
        # film dans ce run" silencieux en prod. _resolve_run_dir applique la
        # convention canonique tout en tolerant les runs anterieurs (dossier nu).
        plan_path = _resolve_run_dir(state_dir, target_run_id) / "plan.jsonl"
        raw_rows = _load_plan_rows_from_jsonl(plan_path)
        local_rows = [plan_row_from_jsonable(d) for d in raw_rows]
        local_rows = [r for r in local_rows if r is not None]
        if not local_rows:
            return _err_response("Aucun film dans ce run.", category="state", level="info", log_module=__name__)

        try:
            timeout_s = float(settings.get("jellyfin_timeout_s") or 10)
            # NB : module-style pour permettre patch("cinesort.infra.jellyfin_client.JellyfinClient").
            client = _jellyfin_mod.JellyfinClient(jf_url, jf_key, timeout_s=timeout_s)
            if not jf_user_id:
                info = client.validate_connection()
                if not info.get("ok") or not info.get("user_id"):
                    err = str(info.get("error") or "user_id introuvable")
                    return _err_response(
                        f"Connexion Jellyfin echouee : {err}",
                        category="resource",
                        level="error",
                        log_module=__name__,
                    )
                jf_user_id = str(info.get("user_id") or "")
            # BUG 2 : utiliser le scan multi-library pour eviter les tronques
            jellyfin_movies = client.get_all_movies_from_all_libraries(jf_user_id)
        except _jellyfin_mod.JellyfinError as exc:
            return _safe_integration_error(exc, category="resource", log_module=__name__)

        report = build_sync_report(local_rows, jellyfin_movies)
        return {"ok": True, "run_id": target_run_id, **report}

    # ---------- Watchlist ----------
    def _import_watchlist_impl(self, csv_content: str, source: str) -> Dict[str, Any]:
        """Importe une watchlist CSV et compare avec la bibliotheque locale."""
        src = str(source or "").strip().lower()
        if src not in ("letterboxd", "imdb"):
            return _err_response(
                "Source inconnue. Utilisez 'letterboxd' ou 'imdb'.",
                category="runtime",
                level="warning",
                log_module=__name__,
            )
        content = str(csv_content or "")
        if not content.strip():
            return _err_response("Contenu CSV vide.", category="state", level="info", log_module=__name__)

        # NB : module-style pour permettre patch("cinesort.app.watchlist.X").
        if src == "letterboxd":
            films = _watchlist_mod.parse_letterboxd_csv(content)
        else:
            films = _watchlist_mod.parse_imdb_csv(content)
        if not films:
            return _err_response("Aucun film trouve dans le CSV.", category="state", level="info", log_module=__name__)

        # Charger les PlanRows du dernier run
        state_dir = Path(self._get_state_dir())
        store, _runner = self._get_or_create_infra(state_dir)

        runs = store.run.get_runs_summary(limit=5)
        target_run_id = ""
        for r in runs:
            if str(r.get("status") or "") == "DONE":
                target_run_id = str(r.get("run_id") or "")
                break
        if not target_run_id:
            return _err_response("Aucun run termine disponible.", category="state", level="info", log_module=__name__)
        if not self._is_valid_run_id(target_run_id):
            return _err_response(
                "Identifiant de run invalide.",
                category="validation",
                level="warning",
                log_module=__name__,
            )

        # Audit 2026-06-02 : meme bug que jellyfin_sync — cf commentaire la-bas.
        plan_path = _resolve_run_dir(state_dir, target_run_id) / "plan.jsonl"
        raw_rows = _load_plan_rows_from_jsonl(plan_path)
        local_rows = [plan_row_from_jsonable(d) for d in raw_rows]
        local_rows = [r for r in local_rows if r is not None]

        report = _watchlist_mod.compare_watchlist(films, local_rows)
        return {"ok": True, "source": src, **report}

    # ---------- Plex ----------
    def _test_plex_connection_impl(self, url: str = "", token: str = "", timeout_s: float = 10.0) -> Dict[str, Any]:
        """Teste la connexion au serveur Plex."""
        purl = (url or "").strip()
        ptok = self._unmask_or_stored("plex_token", token)
        if not purl or not ptok:
            return _err_response("URL et token requis.", category="validation", level="info", log_module=__name__)
        # Audit C7 P1 : remplace l'ancien max(1, min(30, timeout_s)) par le
        # helper centralise (range 1-60s + fallback robuste sur None/str).
        # NB : module-style pour permettre patch("cinesort.infra.plex_client.PlexClient").
        client = _plex_mod.PlexClient(purl, ptok, timeout_s=clamp_timeout(timeout_s))
        return client.validate_connection()

    def _get_plex_libraries_impl(self, url: str = "", token: str = "", timeout_s: float = 10.0) -> Dict[str, Any]:
        """Retourne les sections movie du serveur Plex."""
        purl = (url or "").strip()
        ptok = (token or "").strip()
        if not purl or not ptok:
            settings = self._internal_settings()  # plex_token en clair (AUDIT 2026-06-10)
            purl = purl or str(settings.get("plex_url") or "").strip()
            ptok = ptok or str(settings.get("plex_token") or "").strip()
        if not purl or not ptok:
            return _err_response("URL et token Plex requis.", category="validation", level="info", log_module=__name__)
        try:
            # Audit C7 P1 (suite) : symetrie avec _test_plex_connection_impl/_test_radarr_connection_impl
            # qui utilisent clamp_timeout (range 1-60s + fallback robuste sur None/str/NaN).
            client = _plex_mod.PlexClient(purl, ptok, timeout_s=clamp_timeout(timeout_s))
            libs = client.get_libraries("movie")
            return {"ok": True, "libraries": libs}
        except _plex_mod.PlexError as exc:
            # Sprint 2 audit P0 #4 : ne pas leak exc string (peut contenir URL/token/path).
            return _safe_integration_error(exc, category="resource", log_module=__name__)

    def _get_plex_sync_report_impl(self, run_id: str = "") -> Dict[str, Any]:
        """Compare la bibliotheque locale avec Plex."""
        settings = self._internal_settings()  # plex_token en clair (AUDIT 2026-06-10)
        if not settings.get("plex_enabled"):
            return _err_response("Plex non configure.", category="state", level="info", log_module=__name__)
        purl = str(settings.get("plex_url") or "").strip()
        ptok = str(settings.get("plex_token") or "").strip()
        plib = str(settings.get("plex_library_id") or "").strip()
        if not purl or not ptok or not plib:
            return _err_response(
                "URL, token ou library Plex manquant.", category="validation", level="info", log_module=__name__
            )

        state_dir = Path(self._get_state_dir())
        store, _runner = self._get_or_create_infra(state_dir)

        runs = store.run.get_runs_summary(limit=5)
        target_run_id = run_id.strip() if run_id else ""
        if not target_run_id:
            for r in runs:
                if str(r.get("status") or "") == "DONE":
                    target_run_id = str(r.get("run_id") or "")
                    break
        if not target_run_id:
            return _err_response("Aucun run termine disponible.", category="state", level="info", log_module=__name__)
        if not self._is_valid_run_id(target_run_id):
            return _err_response(
                "Identifiant de run invalide.",
                category="validation",
                level="warning",
                log_module=__name__,
            )

        # Audit 2026-06-02 : meme bug que jellyfin_sync — cf commentaire la-bas.
        plan_path = _resolve_run_dir(state_dir, target_run_id) / "plan.jsonl"
        raw_rows = _load_plan_rows_from_jsonl(plan_path)
        local_rows = [plan_row_from_jsonable(d) for d in raw_rows]
        local_rows = [r for r in local_rows if r is not None]
        if not local_rows:
            return _err_response("Aucun film dans ce run.", category="state", level="info", log_module=__name__)

        try:
            timeout_s = float(settings.get("plex_timeout_s") or 10)
            client = _plex_mod.PlexClient(purl, ptok, timeout_s=timeout_s)
            plex_movies = client.get_movies(plib)
        except _plex_mod.PlexError as exc:
            return _safe_integration_error(exc, category="resource", log_module=__name__)

        report = build_sync_report(local_rows, plex_movies)
        return {"ok": True, "run_id": target_run_id, **report}

    # ---------- Refresh manuel Jellyfin / Plex (#92 quick win #1) ----------
    def _refresh_jellyfin_library_now_impl(self) -> Dict[str, Any]:
        """Cf #92 quick win #1 : declenche un refresh Jellyfin a la demande.

        Endpoint accessible cote frontend pour offrir un bouton "Rafraichir
        Jellyfin maintenant" apres un apply, sans dependre du toggle
        `jellyfin_refresh_on_apply` (qui automatise post-apply mais ne
        permet pas un trigger explicite hors flow apply).
        """
        return apply_support.refresh_jellyfin_library_now(self)

    def _refresh_plex_library_now_impl(self) -> Dict[str, Any]:
        """Cf #92 quick win #1 : declenche un refresh Plex a la demande.

        Symetrique de `_refresh_jellyfin_library_now_impl`.
        """
        return apply_support.refresh_plex_library_now(self)

    # ---------- Radarr ----------
    def _test_radarr_connection_impl(self, url: str = "", api_key: str = "", timeout_s: float = 10.0) -> Dict[str, Any]:
        """Teste la connexion au serveur Radarr."""
        rurl = (url or "").strip()
        rkey = self._unmask_or_stored("radarr_api_key", api_key)
        if not rurl or not rkey:
            return _err_response("URL et cle API requis.", category="validation", level="info", log_module=__name__)
        # Audit C7 P1 : helper centralise (range 1-60s + fallback robuste).
        # NB : module-style pour permettre patch("cinesort.infra.radarr_client.RadarrClient").
        client = _radarr_mod.RadarrClient(rurl, rkey, timeout_s=clamp_timeout(timeout_s))
        return client.validate_connection()

    def _get_radarr_status_impl(self, run_id: str = "") -> Dict[str, Any]:
        """Rapport Radarr : matching, upgrade candidates."""
        settings = self._internal_settings()  # radarr_api_key en clair (AUDIT 2026-06-10)
        if not settings.get("radarr_enabled"):
            return _err_response("Radarr non configure.", category="state", level="info", log_module=__name__)
        rurl = str(settings.get("radarr_url") or "").strip()
        rkey = str(settings.get("radarr_api_key") or "").strip()
        if not rurl or not rkey:
            return _err_response(
                "URL ou cle API Radarr manquante.", category="validation", level="info", log_module=__name__
            )

        state_dir = Path(self._get_state_dir())
        store, _runner = self._get_or_create_infra(state_dir)

        runs = store.run.get_runs_summary(limit=5)
        target_run_id = run_id.strip() if run_id else ""
        if not target_run_id:
            for r in runs:
                if str(r.get("status") or "") == "DONE":
                    target_run_id = str(r.get("run_id") or "")
                    break
        if not target_run_id:
            return _err_response("Aucun run termine disponible.", category="state", level="info", log_module=__name__)
        if not self._is_valid_run_id(target_run_id):
            return _err_response(
                "Identifiant de run invalide.",
                category="validation",
                level="warning",
                log_module=__name__,
            )

        # Audit 2026-06-02 : meme bug que jellyfin_sync — cf commentaire la-bas.
        plan_path = _resolve_run_dir(state_dir, target_run_id) / "plan.jsonl"
        raw_rows = _load_plan_rows_from_jsonl(plan_path)
        local_rows = [plan_row_from_jsonable(d) for d in raw_rows]
        local_rows = [r for r in local_rows if r is not None]

        try:
            timeout_s = float(settings.get("radarr_timeout_s") or 10)
            client = _radarr_mod.RadarrClient(rurl, rkey, timeout_s=timeout_s)
            radarr_movies = client.get_movies()
            profiles = client.get_quality_profiles()
        except _radarr_mod.RadarrError as exc:
            return _safe_integration_error(exc, category="resource", log_module=__name__)

        # Collecter les quality reports pour les upgrade candidates
        qr_map: Dict[str, Dict[str, Any]] = {}
        for row in local_rows:
            rid = str(getattr(row, "row_id", "") or "")
            if rid:
                qr = store.quality.get_quality_report(run_id=target_run_id, row_id=rid)
                if qr:
                    qr_map[rid] = qr

        report = build_radarr_report(local_rows, radarr_movies, qr_map, profiles)
        candidates = get_upgrade_candidates(report, qr_map)
        return {"ok": True, "run_id": target_run_id, **report, "upgrade_candidates": candidates}

    def _request_radarr_upgrade_impl(self, radarr_movie_id: int) -> Dict[str, Any]:
        """Demande a Radarr de chercher une meilleure version d'un film."""
        settings = self._internal_settings()  # radarr_api_key en clair (AUDIT 2026-06-10)
        if not settings.get("radarr_enabled"):
            return _err_response("Radarr non configure.", category="state", level="info", log_module=__name__)
        rurl = str(settings.get("radarr_url") or "").strip()
        rkey = str(settings.get("radarr_api_key") or "").strip()
        mid = int(radarr_movie_id or 0)
        if mid <= 0:
            return _err_response("radarr_movie_id invalide.", category="validation", level="info", log_module=__name__)
        try:
            timeout_s = float(settings.get("radarr_timeout_s") or 10)
            client = _radarr_mod.RadarrClient(rurl, rkey, timeout_s=timeout_s)
            client.search_movie(mid)
            return {"ok": True, "message": f"Recherche lancee pour le film Radarr #{mid}."}
        except _radarr_mod.RadarrError as exc:
            # Sprint 2 audit P0 #4 : ne pas leak exc string (peut contenir URL/api_key/path).
            return _safe_integration_error(exc, category="resource", log_module=__name__)

    # ---------- OMDb (Phase 6.2 — cross-check IMDb) ----------
    def _test_omdb_connection_impl(self, api_key: str = "", timeout_s: float = 10.0) -> Dict[str, Any]:
        """Teste la cle OMDb avec un IMDb id connu (Shawshank Redemption).

        Retourne (cf spec 03-settings-omdb §2) :
          {ok, message, sample_title?, sample_year?, error_code?,
           quota_remaining?, quota_limit?, quota_reset_at?}
        """

        okey = self._unmask_or_stored("omdb_api_key", api_key)
        if not okey:
            return _err_response("Cle OMDb requise.", category="validation", level="info", log_module=__name__)
        # Cache temporaire pour le test : pas de pollution du cache prod
        cache_path = Path(self._get_state_dir()) / "omdb_cache_test.json"
        # Audit C7 P1 : helper centralise (range 1-60s + fallback robuste).
        try:
            client = OmdbClient(api_key=okey, cache_path=cache_path, timeout_s=clamp_timeout(timeout_s))
            return client.test_connection()
        except (OSError, ValueError, KeyError) as exc:
            # Sprint 2 audit P0 #4 : ne pas leak exc string (peut contenir cache_path/api_key).
            # Resolution conflit rebase i18n : on garde la version #332 (safe) qui ne
            # leak pas l'exception au client. La cle errors.omdb_test_failed reste
            # disponible dans locales/ pour usage futur.
            return _safe_integration_error(exc, category="resource", log_module=__name__)

    def _get_naming_presets_impl(self) -> Dict[str, Any]:
        """Retourne la liste des presets de renommage disponibles."""

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

    def _preview_naming_template_impl(self, template: str = "", sample_row_id: str = "") -> Dict[str, Any]:
        """Preview du resultat d'un template de renommage sur un film exemple."""

        tpl = str(template or "{title} ({year})").strip()
        ok, errors = validate_template(tpl)
        if not ok:
            return _err_response(
                "Template invalide.",
                category="validation",
                level="info",
                log_module=__name__,
                errors=errors,
            )

        # Essayer de charger un vrai film depuis la BDD
        context = None
        rid = str(sample_row_id or "").strip()
        if rid:
            try:
                state_dir = self._get_state_dir()
                settings = _read_settings(state_dir)
                store, _ = self._get_or_create_infra(state_dir, settings)
                # Chercher la probe en cache (NB: signature obsolete, fallback dans except)
                probe_data = store.probe.get_probe_cache(rid) if hasattr(store, "probe") else None
                quality_data = store.quality.get_quality_report(rid) if hasattr(store, "get_quality_report") else None
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

    def _validate_dropped_path_impl(self, path: str = "") -> Dict[str, Any]:
        r"""Valide qu'un chemin droppe est un dossier existant.

        M-7 audit QA 20260429 : refuse les symlinks et chemins UNC speciaux
        (\\?\ , \\.\ , etc.) qui peuvent contourner les guards path-traversal.
        Les UNC normaux \\server\share sont autorises (cas legitime NAS).
        """
        raw = str(path or "").strip()
        if not raw:
            return _err_response("Chemin vide.", category="state", level="info", log_module=__name__)

        # M-7 : reject UNC namespaces speciaux Windows (\\?\, \\.\)
        # Ces prefixes contournent la normalisation Win32 et permettent
        # d'acceder a des paths > 260 chars ou des devices systeme.
        norm = raw.replace("/", "\\")
        if norm.startswith("\\\\?\\") or norm.startswith("\\\\.\\"):
            return _err_response(
                "Chemin UNC special non autorise (\\\\?\\ ou \\\\.\\).",
                category="permission",
                level="info",
                log_module=__name__,
            )

        p = Path(raw)

        # M-7 : verifier accessibilite avec timeout (NAS debranche)

        exists = safe_path_exists(p, timeout_s=5.0)
        if exists is None:
            return _err_response(
                "Chemin inaccessible (NAS debranche ou timeout).",
                category="runtime",
                level="warning",
                log_module=__name__,
            )
        if not exists:
            return _err_response(f"Chemin introuvable : {p}", category="state", level="info", log_module=__name__)

        # M-7 : refuser les symlinks (peuvent pointer ailleurs apres validation)
        try:
            if p.is_symlink():
                return _err_response(
                    "Les liens symboliques ne sont pas autorises (resolvez la cible directement).",
                    category="permission",
                    level="info",
                    log_module=__name__,
                )
        except (OSError, PermissionError):
            return _err_response(
                "Impossible de lire l'attribut symlink du chemin.",
                category="runtime",
                level="error",
                log_module=__name__,
            )

        if not p.is_dir():
            return _err_response("Ce n'est pas un dossier.", category="state", level="info", log_module=__name__)

        # Resolution finale + verification que le resultat n'est pas un symlink
        # remontant ailleurs (defense en profondeur)
        try:
            resolved = p.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            return _err_response(
                f"Impossible de resoudre le chemin : {exc}", category="runtime", level="error", log_module=__name__
            )

        return {"ok": True, "path": str(resolved)}

    def _get_tools_status_impl(self) -> Dict[str, Any]:
        # Compat endpoint kept for v7.0/v7.1 callers.
        return self._get_probe_tools_status_impl()

    def _get_probe_tools_status_impl(self) -> Dict[str, Any]:
        """Retourne le statut de detection de ffprobe + MediaInfo (version, chemin, dispo)."""
        return probe_support.get_probe_tools_status(self, detect_probe_tools_fn=detect_probe_tools)

    def _recheck_probe_tools_impl(self) -> Dict[str, Any]:
        """Force une redetection des outils probe (utile apres installation manuelle)."""
        return probe_support.recheck_probe_tools(self, detect_probe_tools_fn=detect_probe_tools)

    def _set_probe_tool_paths_impl(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Enregistre des chemins manuels vers ffprobe / MediaInfo (si hors PATH)."""
        return probe_support.set_probe_tool_paths(
            self,
            payload,
            validate_tool_path_fn=validate_tool_path,
            detect_probe_tools_fn=detect_probe_tools,
        )

    def _install_probe_tools_impl(self, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Installe ffprobe + MediaInfo via winget (ou options fournies)."""
        return probe_support.install_probe_tools(
            self,
            options,
            manage_probe_tools_fn=manage_probe_tools,
            detect_probe_tools_fn=detect_probe_tools,
        )

    def _update_probe_tools_impl(self, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Met a jour ffprobe + MediaInfo via winget."""
        return probe_support.update_probe_tools(
            self,
            options,
            manage_probe_tools_fn=manage_probe_tools,
            detect_probe_tools_fn=detect_probe_tools,
        )

    def _auto_install_probe_tools_impl(self) -> Dict[str, Any]:
        """Telecharge et installe ffprobe + MediaInfo depuis les sources officielles."""
        return probe_support.auto_install_probe_tools(self, detect_probe_tools_fn=detect_probe_tools)

    def _purge_probe_cache_impl(self) -> Dict[str, Any]:
        """Fix audit 2026-05-25 (v1.5.5) Vague K (FIX 5) : purge totale du cache probe.

        Utile quand un settings.json obsolete a pollue le cache avec des
        resultats FAILED dus a un path ffprobe/mediainfo introuvable. Apres
        purge, le prochain scan relance toutes les probes proprement.
        """
        _log = logging.getLogger(__name__)
        try:
            store, _runner = self._get_or_create_infra(self._get_state_dir())
        except Exception as exc:  # noqa: BLE001 - boundary top-level
            _log.exception("api: purge_probe_cache echec init store")
            return _err_response(
                f"Store indisponible : {type(exc).__name__}: {exc}",
                category="state",
                level="error",
                log_module=__name__,
            )
        try:
            deleted = int(store.probe.clear_probe_cache())
        except Exception as exc:  # noqa: BLE001 - boundary top-level
            _log.exception("api: purge_probe_cache echec purge")
            return _err_response(
                f"Purge cache probe echouee : {type(exc).__name__}: {exc}",
                category="runtime",
                level="error",
                log_module=__name__,
            )
        _log.info("api: purge_probe_cache entries_deleted=%d", deleted)
        return {
            "ok": True,
            "entries_deleted": deleted,
            "message": (f"Cache probe purge : {deleted} entrees supprimees. Relance un scan pour re-probe les films."),
        }

    def _get_probe_impl(self, run_id: str, row_id: str) -> Dict[str, Any]:
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

        return run_simulation(self, run_id=run_id, preset_id=preset_id, overrides=overrides, scope=scope)

    def _save_custom_quality_preset_impl(self, name: str, profile_json: Dict[str, Any]) -> Dict[str, Any]:
        """Persiste un profil qualite custom et l'active (G5)."""

        return save_custom_preset(self, name, profile_json)

    def _get_custom_rules_templates_impl(self) -> Dict[str, Any]:
        """Retourne les 3 templates starter de regles custom (G6)."""

        return {"ok": True, "templates": list_templates()}

    def _get_custom_rules_catalog_impl(self) -> Dict[str, Any]:
        """Retourne les fields, operators et actions disponibles pour le builder UI (G6)."""

        return {
            "ok": True,
            "fields": list(FIELD_PATHS.keys()),
            "operators": list(OPERATORS.keys()),
            "actions": list(ACTIONS.keys()),
        }

    def _validate_custom_rules_impl(self, rules: Any) -> Dict[str, Any]:
        """Valide une liste de regles custom sans persister (G6)."""

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
            return _err_response(
                "E2E mode not active", category="permission", level="info", log_module=__name__, key="error"
            )
        # Audit C7 P1 : normaliser min_video_bytes -> int >= 0 (acceptait
        # n'importe quoi : str, float negatif, None, etc.).
        min_video_bytes = clamp_non_negative_int(min_video_bytes)
        try:
            # Reset du run courant
            with self._runs_lock:
                self._runs.clear()
            # Abaisser le seuil de taille video si demande (fichiers factices E2E)
            if min_video_bytes > 0:
                core.MIN_VIDEO_BYTES = min_video_bytes
            return {"ok": True, "message": "Reset E2E effectue."}
        except (OSError, KeyError, TypeError, ValueError) as exc:
            return _err_response(str(exc), category="runtime", level="error", log_module=__name__, key="error")

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

    def _get_perceptual_compare_frames_impl(
        self, run_id: str, row_id_a: str, row_id_b: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Cf #94 : N paires de frames cote-a-cote en PNG base64.

        Frames extraites pendant compare_perceptual mais jamais exposees au
        frontend ; cet endpoint les rend visibles pour validation visuelle
        des decisions destructrices (supprimer un doublon).
        """
        return perceptual_support.get_perceptual_compare_frames(self, run_id, row_id_a, row_id_b, options)

    def _get_perceptual_compare_audio_impl(
        self, run_id: str, row_id_a: str, row_id_b: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Phase 4 doublons : waveform PNG + clip MP3 cote-a-cote.

        Cf spec docs/internal/design/refonte_2026_05_17/screens/01-doublons.md
        section 3 "Comparaison audio".
        """
        return perceptual_support.get_perceptual_compare_audio(self, run_id, row_id_a, row_id_b, options)

    def _queue_perceptual_analyses_impl(self, pairs: Any, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Phase 4 doublons : queue d'analyses perceptuelles batch en background.

        Cf spec section 1 "Analyser perceptuel sur N groupes". Retourne un
        job_id pour polling via _get_perceptual_job_status_impl.
        """
        return perceptual_support.queue_perceptual_analyses(self, pairs, options)

    def _queue_perceptual_batch_impl(
        self, run_id: str, row_ids: Any, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """R5-C : analyse perceptuelle batch SINGLE-film en background (biblio).

        Variante async de analyze_perceptual_batch : retourne un job_id pollable
        via _get_perceptual_job_status_impl (meme registre que les paires).
        """
        return perceptual_support.queue_perceptual_batch(self, run_id, row_ids, options)

    def _get_perceptual_job_status_impl(self, job_id: str) -> Dict[str, Any]:
        """Phase 4 doublons : statut d'un batch perceptuel queue."""
        return perceptual_support.get_perceptual_job_status(self, job_id)

    def _mark_duplicate_winner_impl(
        self, run_id: str, group_key: str, winner_row_id: str, notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Phase 4 doublons : persiste la decision utilisateur.

        Cf spec section 3 "Workflow decision". Les loser_row_ids seront
        deplaces vers <root>/_review/_duplicates_user_decided/ a l'apply.
        """
        return run_flow_support.mark_duplicate_winner(self, run_id, group_key, winner_row_id, notes)

    def _get_dashboard_impl(self, run_id: str = "latest") -> Dict[str, Any]:
        """Dashboard d'un run (KPIs, distribution scores, anomalies, timeline)."""
        return dashboard_support.get_dashboard(self, run_id)

    def _get_global_stats_impl(self, limit_runs: int = 20) -> Dict[str, Any]:
        """Global dashboard: multi-run statistics for the library."""
        return dashboard_support.get_global_stats(self, limit_runs)

    def _get_sidebar_counters_impl(self) -> Dict[str, Any]:
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
    def _get_notifications_impl(
        self,
        unread_only: bool = False,
        limit: int = 100,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : liste les notifications en memoire (LIFO)."""
        return notifications_support.get_notifications(self, unread_only=unread_only, limit=limit, category=category)

    def _dismiss_notification_impl(self, notification_id: str) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : supprime une notification du centre."""
        return notifications_support.dismiss_notification(self, notification_id)

    def _mark_notification_read_impl(self, notification_id: str) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : marque une notification comme lue."""
        return notifications_support.mark_read(self, notification_id)

    def _mark_all_notifications_read_impl(self) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : marque toutes les notifications comme lues."""
        return notifications_support.mark_all_read(self)

    def _clear_notifications_impl(self) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : vide completement le centre de notifications."""
        return notifications_support.clear_all_notifications(self)

    def _get_notifications_unread_count_impl(self) -> Dict[str, Any]:
        """v7.6.0 Vague 9 : compteur pour le badge top bar."""
        return {"ok": True, "count": notifications_support.get_unread_count(self)}

    # ---------- v7.6.0 Vague 4 : Film standalone page ----------
    def _get_film_full_impl(self, row_id: str, run_id: Optional[str] = None) -> Dict[str, Any]:
        """v7.6.0 Vague 4 : toutes les infos d'un film pour la page standalone.

        Consolide : PlanRow, probe, perceptual V2, history, poster TMDb, runtime,
        director, overview (spec 06 §3.1).
        """
        return film_support.get_film_full(self, run_id, row_id)

    # ---------- Spec 06 Modal Film : 3 actions de modification ----------
    def _set_film_tmdb_candidate_impl(
        self,
        run_id: Optional[str],
        row_id: str,
        tmdb_id: int,
    ) -> Dict[str, Any]:
        """Spec 06 §3.4 : choisir un autre candidat TMDb pour un film.

        Recalcul confidence + nouveau renommage propose. Reversible tant que
        l'apply n'est pas faite.
        """
        return library_support.set_film_tmdb_candidate(self, run_id, row_id, tmdb_id)

    def _mark_for_deletion_impl(self, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
        """Spec 06 §3.7 : marque un film pour le bucket `_user_marked_for_deletion/`.

        Reversible via undo (clear). Le deplacement effectif sera applique
        au prochain apply.
        """
        return library_support.mark_for_deletion(self, run_id, row_id)

    def _clear_tmdb_override_impl(self, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
        """R7-12 : annule l'override TMDb manuel (revient au match auto)."""
        return library_support.clear_tmdb_override(self, run_id, row_id)

    def _unmark_for_deletion_impl(self, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
        """R7-12 : annule le marquage pour suppression d'un film."""
        return library_support.unmark_for_deletion(self, run_id, row_id)

    def _mark_alert_ignored_impl(self, row_id: str, alert_code: str) -> Dict[str, Any]:
        """Spec 06 §3.3 : persiste "j'ai vu cette alerte, on continue".

        L'alerte disparait visuellement pour ce film mais reste loggee en DB
        pour les stats globales.
        """
        return library_support.mark_alert_ignored(self, row_id, alert_code)

    def _rescan_row_impl(self, run_id: str, row_id: str) -> Dict[str, Any]:
        """Spec 06 §3.6 : relance probe + analyse perceptuelle pour 1 row.

        Retourne le nouveau plan_row + scores quality/perceptual updated.
        """
        return run_flow_support.rescan_row(self, run_id, row_id)

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

        return export_support.export_full_library(self)

    def _export_run_nfo_impl(self, run_id: str, overwrite: bool = False, dry_run: bool = True) -> Dict[str, Any]:
        """Génère des fichiers .nfo (Kodi/Jellyfin) pour chaque film du run."""
        if not self._is_valid_run_id(run_id):
            return _err_response("run_id invalide.", category="validation", level="info", log_module=__name__)
        built, _paths = dashboard_support.build_run_report_payload(self, run_id)
        if not built.get("ok"):
            return built
        report = built.get("report") if isinstance(built.get("report"), dict) else {}
        rows = report.get("rows") or []
        if not rows:
            return _err_response("Aucune ligne dans le run.", category="state", level="info", log_module=__name__)

        return export_nfo_for_run(rows, overwrite=bool(overwrite), dry_run=bool(dry_run))

    # ---------- validation persistence ----------
    def _load_validation_impl(self, run_id: str) -> Dict[str, Any]:
        """Recharge les decisions (approve/reject) persistees pour ce run."""
        return history_support.load_validation(self, run_id, normalize_user_path=_normalize_user_path)

    def _save_validation_impl(self, run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Persiste les decisions de validation dans validation.json (atomique).

        Vague P / VP-D : accepte aussi la cle optionnelle `decision`
        (`accepted`/`rejected`/`deferred`) en complement du legacy
        `ok: bool`. Backward compat ABSOLUE : shape retour `{ok, path}`
        preservee (helper `to_legacy_ok_bool` dans decisions.py).
        """
        return run_flow_support.save_validation(self, run_id, decisions)

    def _check_duplicates_impl(self, run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Detecte les collisions de destination entre rows approuvees avant apply."""
        return run_flow_support.check_duplicates(self, run_id, decisions)

    def _check_duplicates_fusion_impl(
        self,
        run_id: str,
        decisions: Dict[str, Dict[str, Any]],
        *,
        audio_weight: Optional[float] = None,
        video_weight: Optional[float] = None,
    ) -> Dict[str, Any]:
        """V2.4 — Detection fusion Chromaprint + videohash (feature flag opt-in).

        Backward compat ABSOLUE :
        - `_check_duplicates_impl` legacy ci-dessus reste l'unique chemin
          actif par defaut.
        - Cette implementation est gate par `CINESORT_FUSION_DOUBLONS` ; si
          le flag est off, retourne un stub `{ok, enabled: False, pairs: []}`.
        """
        return run_flow_support.check_duplicates_fusion(
            self,
            run_id,
            decisions,
            audio_weight=audio_weight,
            video_weight=video_weight,
        )

    def _get_cleanup_residual_preview_impl(self, run_id: str) -> Dict[str, Any]:
        """Preview du nettoyage de fin de run : dossiers vides + residuels identifies."""
        return run_read_support.get_cleanup_residual_preview(self, run_id)

    def _get_auto_approved_summary_impl(
        self,
        run_id: str,
        threshold: Optional[int] = None,
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

    def _get_tmdb_posters_impl(
        self, tmdb_ids: List[int], size: str = "w92", force_refresh: bool = False
    ) -> Dict[str, Any]:
        """Retourne les URLs de posters TMDb pour les IDs demandes (cache local).

        E4 : force_refresh=True purge l'entree cache de chaque ID avant lookup
        (bouton refresh jaquette de la fiche film).
        """
        return tmdb_support.get_tmdb_posters(self, tmdb_ids, size, force_refresh=force_refresh)

    def _enrich_tmdb_ids_by_title_impl(self, run_id: str, row_ids: Any) -> Dict[str, Any]:
        """R5-H2 : resout + persiste le tmdb_id de films identifies NFO/nom (sans
        tmdb_id) par recherche titre+annee, pour recuperer leurs jaquettes."""
        return tmdb_support.enrich_tmdb_ids_by_title(self, run_id, row_ids)

    def _search_tmdb_impl(self, query: str, year: Optional[int] = None) -> Dict[str, Any]:
        """Spec 06 3.4 : recherche manuelle TMDb depuis le Modal Film.

        Retourne jusqu'a 10 resultats (tmdb_id, title, year, poster_url,
        overview tronquee, votes). L'utilisateur peut ensuite appeler
        `set_film_tmdb_candidate(row_id, tmdb_id)` pour appliquer son choix.
        """
        return tmdb_support.search_tmdb(self, query, year)

    # ---------- apply ----------
    def _build_undo_preview_payload(
        self,
        run_id: str,
    ) -> Tuple[
        Dict[str, Any], Optional[SQLiteStore], Optional[state.RunPaths], Optional[Dict[str, Any]], List[Dict[str, Any]]
    ]:
        return apply_support.build_undo_preview_payload(self, run_id)

    def _undo_last_apply_preview_impl(self, run_id: str) -> Dict[str, Any]:
        """Preview (dry) de l'annulation du dernier batch apply reel (undo v1)."""
        return apply_support.undo_last_apply_preview(self, run_id)

    def _undo_last_apply_impl(self, run_id: str, dry_run: bool = True, atomic: bool = True) -> Dict[str, Any]:
        """Annule le dernier batch apply reel (undo v1). `dry_run=True` ne touche rien.

        P1.2 : atomic=True (defaut) refuse l'annulation si un fichier a ete
        remplace depuis l'apply (sha1 different). Rapport dans `preverify`.
        """
        return apply_support.undo_last_apply(self, run_id, dry_run, atomic=atomic)

    def _undo_by_row_preview_impl(self, run_id: str, batch_id: str = None) -> Dict[str, Any]:
        """Preview de l'annulation par film : resume par row_id du batch cible (undo v5)."""
        return apply_support.build_undo_by_row_preview(self, run_id, batch_id=batch_id)

    def _undo_selected_rows_impl(
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

    def _apply_impl(
        self,
        run_id: str,
        decisions: Dict[str, Dict[str, Any]],
        dry_run: bool,
        quarantine_unapproved: bool,
        apply_atomic: bool = False,
    ) -> Dict[str, Any]:
        """Vague P / VP-A : `apply_atomic` opt-in (default False, backward
        compat ABSOLUE — la signature retourne toujours `{ok: bool, ...}`)."""
        result = apply_support.apply_changes(
            self,
            run_id,
            decisions,
            dry_run,
            quarantine_unapproved,
            cleanup_scope_label=_cleanup_scope_label,
            cleanup_status_label=_cleanup_status_label,
            cleanup_reason_label=_cleanup_reason_label,
            apply_atomic=bool(apply_atomic),
        )
        if not dry_run:
            self._touch_event()
        return result

    def _export_shareable_profile_impl(
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

        try:
            store, _runner = self._get_or_create_infra(self._get_state_dir())
        except (OSError, TypeError, ValueError):
            store = None
        try:
            active = store.quality.get_active_quality_profile() if store else None
        except (OSError, TypeError, ValueError):
            active = None
        if active and isinstance(active.get("profile_json"), str):
            try:
                profile = json.loads(active["profile_json"])
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

    def _import_shareable_profile_impl(
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

        ok, profile, msg = parse_and_validate_import(content or "")
        meta = extract_import_metadata(content or "")
        if not ok:
            return _err_response(msg, category="validation", level="info", log_module=__name__, meta=meta)

        try:
            store, _runner = self._get_or_create_infra(self._get_state_dir())
        except (OSError, TypeError, ValueError) as exc:
            return _err_response(
                f"Store indisponible : {exc}", category="runtime", level="error", log_module=__name__, meta=meta
            )
        if not store:
            return _err_response("Store indisponible.", category="state", level="info", log_module=__name__, meta=meta)

        # save_quality_profile requiert profile_id + version. On les déduit
        # du profile importé, avec fallback sur l'app_version si absents.
        pid = str(profile.get("id") or "").strip()
        if not pid:
            # Générer un id depuis le name méta (ou timestamp)
            clean_name = (
                "".join(c for c in (meta.get("name") or "imported") if c.isalnum() or c in "_-")[:40] or "imported"
            )
            pid = f"{clean_name}_{int(time.time())}"
            profile["id"] = pid
        try:
            version = int(profile.get("version") or 1)
        except (TypeError, ValueError):
            version = 1

        try:
            store.quality.save_quality_profile(
                profile_id=pid,
                version=version,
                profile_json=profile,
                is_active=bool(activate),
            )
        except (OSError, TypeError, ValueError, AttributeError) as exc:
            self.log_api_exception("import_quality_profile", exc)
            return _err_response(
                f"Sauvegarde échouée : {exc}", category="runtime", level="error", log_module=__name__, meta=meta
            )
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

        if not self._is_valid_run_id(run_id):
            return _err_response("run_id invalide.", category="validation", level="info", log_module=__name__)
        if not row_id or not user_tier:
            return _err_response(
                "row_id et user_tier sont requis.", category="validation", level="info", log_module=__name__
            )

        found = self._find_run_row(run_id)
        if not found:
            return _err_response("Run introuvable.", category="state", level="info", log_module=__name__)
        _row, store = found

        try:
            qr = store.quality.get_quality_report(run_id=run_id, row_id=str(row_id))
        except (KeyError, TypeError, ValueError, OSError):
            qr = None
        if not qr:
            return _err_response(
                "Rapport qualité introuvable pour ce film.", category="state", level="info", log_module=__name__
            )

        computed_score = int(qr.get("score") or 0)
        computed_tier = str(qr.get("tier") or "")
        tier_delta = compute_tier_delta(computed_tier, str(user_tier))
        try:
            fb_id = store.quality.insert_user_quality_feedback(
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
            return _err_response(
                "Impossible d'enregistrer le feedback.", category="runtime", level="error", log_module=__name__
            )
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
            store, _runner = self._get_or_create_infra(self._get_state_dir())
        except (OSError, TypeError, ValueError) as exc:
            return _err_response(f"Store indisponible : {exc}", category="runtime", level="error", log_module=__name__)
        if not store:
            return _err_response("Store indisponible.", category="state", level="info", log_module=__name__)
        try:
            count = store.quality.delete_user_quality_feedback(feedback_id=int(feedback_id))
        except (OSError, TypeError, ValueError, AttributeError) as exc:
            self.log_api_exception("delete_score_feedback", exc)
            return _err_response("Suppression échouée.", category="runtime", level="error", log_module=__name__)
        return {"ok": True, "deleted_count": int(count)}

    def _get_calibration_report_impl(self) -> Dict[str, Any]:
        """P4.1 : agrège tous les feedbacks et propose un ajustement de poids.

        Retourne le rapport de biais + la suggestion de poids (ou None si
        pas de biais significatif).
        """

        try:
            store, _runner = self._get_or_create_infra(self._get_state_dir())
        except (OSError, TypeError, ValueError) as exc:
            return _err_response(f"Store indisponible : {exc}", category="runtime", level="error", log_module=__name__)
        if store is None:
            return _err_response("Store indisponible.", category="state", level="info", log_module=__name__)
        try:
            feedbacks = store.quality.list_user_quality_feedback(limit=10_000)
        except (OSError, TypeError, ValueError) as exc:
            self.log_api_exception("get_calibration_report", exc)
            return _err_response("Lecture feedbacks échouée.", category="runtime", level="error", log_module=__name__)

        bias = analyze_feedback_bias(feedbacks)
        # Profil actif pour calculer la suggestion
        try:
            prof = store.quality.get_active_quality_profile()
        except (OSError, TypeError, ValueError):
            prof = None
        if prof and isinstance(prof.get("profile_json"), str):
            try:
                payload = json.loads(prof["profile_json"])
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

    def _export_apply_audit_impl(
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

    # ---------- Run Control (V8-01 spec 08 Traitement) ----------
    def _pause_run_impl(self, run_id: str) -> Dict[str, Any]:
        """Suspend un run actif (signaling + DB PAUSED). Cf spec 08 §5."""
        return run_control_support.pause_run(self, run_id)

    def _resume_run_impl(self, run_id: str) -> Dict[str, Any]:
        """Reprend un run PAUSED ou SAVED (signaling + DB RUNNING). Cf spec 08 §5."""
        return run_control_support.resume_run(self, run_id)

    def _save_for_later_impl(self, run_id: str) -> Dict[str, Any]:
        """Sauvegarde un run pour plus tard (signaling + DB SAVED). Cf spec 08 §5."""
        return run_control_support.save_for_later(self, run_id)

    def _list_pending_runs_impl(self) -> Dict[str, Any]:
        """Liste les runs PAUSED / SAVED / AWAITING_VALIDATION. Cf spec 08 §5."""
        return run_control_support.list_pending_runs(self)

    # ---------- Historique (spec 09) ----------
    def _get_history_stats_impl(self, run_id: str) -> Dict[str, Any]:
        """Detail complet d'un run pour l'inspecteur Historique (spec 09)."""
        return history_support.get_history_stats(self, run_id)

    def _delete_run_impl(self, run_id: str) -> Dict[str, Any]:
        """Supprime un run de l'historique (DB seulement)."""
        return history_support.delete_run(self, run_id)

    def _cleanup_old_runs_impl(self, retention_days: int = 90) -> Dict[str, Any]:
        """Supprime les runs > N jours (defaut 90). Appele aussi par le cron retention."""
        return history_support.cleanup_old_runs(self, retention_days=retention_days)

    # ---------- VQ-2 QUARANTAINE-TTL (bucket _review filesystem) ----------
    def _build_quarantine_cfg(self) -> core.Config:
        """Construit la cfg pour les operations quarantaine (bucket root/_review).

        AUDIT 2026-06-10 (CRITICAL) : les 3 endpoints appelaient
        `_build_cfg_from_settings_payload(settings)` avec UN seul argument alors
        que build_cfg_from_settings exige root + 3 noms de dossiers keyword-only
        -> TypeError systematique avale -> {ok:False, build_cfg_failed} ->
        viewer + "Vider maintenant" morts ET le cron TTL ne purgeait JAMAIS le
        bucket (rendant le fix TTL inoperant). On passe par le helper correct
        _build_cfg_from_settings qui fournit les 4 kwargs.
        """
        settings = self._get_settings_impl()
        root = _normalize_user_path(settings.get("root"), Path(DEFAULT_ROOT))
        return self._build_cfg_from_settings(settings, root)

    def _purge_quarantine_bucket_impl(self, ttl_days: int = 30, dry_run: bool = False) -> Dict[str, Any]:
        """Purge le bucket FS `_review` des fichiers > TTL jours (defaut 30).

        Appele :
        - automatiquement au boot par le cron `quarantine_ttl.start_quarantine_ttl_cron`
        - via le bouton "Vider maintenant" (parametres > Quarantaine) en mode `purge_all=True`
        - manuellement depuis tests/REST.
        """
        from cinesort.app.quarantine_ttl import purge_review_bucket

        try:
            cfg = self._build_quarantine_cfg()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return {"ok": False, "error": f"build_cfg_failed: {exc}"}
        return purge_review_bucket(cfg, ttl_days=int(ttl_days), dry_run=bool(dry_run))

    def _purge_quarantine_bucket_all_impl(self, dry_run: bool = False) -> Dict[str, Any]:
        """Vider INTEGRALEMENT le bucket `_review` (sauf `_duplicates_user_decided`).

        Appele par l'UI bouton "Vider maintenant", protege cote front par
        dangerConfirmModal (countdown 3s si > 50 fichiers, memoire actions
        dangereuses).
        """
        from cinesort.app.quarantine_ttl import purge_review_bucket_all

        try:
            cfg = self._build_quarantine_cfg()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return {"ok": False, "error": f"build_cfg_failed: {exc}"}
        return purge_review_bucket_all(cfg, dry_run=bool(dry_run))

    def _list_quarantine_bucket_impl(self, limit: int = 500) -> Dict[str, Any]:
        """Inventaire du bucket `_review` pour le viewer UI (route /quarantine_viewer).

        Retourne files (tries mtime DESC), total, taille, ventilation par
        sous-dossier. Tronque a `limit` entrees (defaut 500).
        """
        from cinesort.app.quarantine_ttl import list_review_bucket_files

        try:
            cfg = self._build_quarantine_cfg()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return {"ok": False, "error": f"build_cfg_failed: {exc}"}
        return list_review_bucket_files(cfg, limit=int(limit))

    # ---------- Reset (V3-09) ----------
    def _reset_all_user_data_impl(self, confirmation: str = "") -> Dict[str, Any]:
        """V3-09 — Reset toutes les donnees user (avec backup ZIP automatique)."""

        return reset_support.reset_all_user_data(self, confirmation)

    def _get_user_data_size_impl(self) -> Dict[str, Any]:
        """V3-09 — Taille actuelle du user-data (pour affichage UI Danger Zone)."""

        return {"data": reset_support.get_user_data_size(self)}

    # ---------- Phase 4 backend-parametres-endpoints (spec 11 §5 + §2.9) ----------
    def _reset_settings_impl(self, scope: str = "all") -> Dict[str, Any]:
        """Reinitialise les settings par categorie (ou tout)."""

        return reset_support.reset_settings(self, scope)

    def _reset_database_impl(self) -> Dict[str, Any]:
        """Wipe complet de la DB SQLite (avec backup automatique)."""

        return reset_support.reset_database(self)

    def _get_profiles_impl(self) -> Dict[str, Any]:
        """Liste tous les profils qualite (presets predefinis + custom)."""

        return profiles_support.get_profiles(self)

    def _save_profile_impl(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Sauve un profil qualite custom dans settings (avec validation)."""

        return profiles_support.save_profile(self, profile)

    def _set_active_profile_impl(self, profile_id: str) -> Dict[str, Any]:
        """Active un profil qualite (preset ou custom)."""

        return profiles_support.set_active_profile(self, profile_id)

    # ---------- VO-A UI : Advanced PRAGMA settings (storage profile + EXCLUSIVE) ----------
    def _get_advanced_pragma_settings_impl(self) -> Dict[str, Any]:
        """VO-A : retourne l'etat des PRAGMA SQLite avances (profil + locking_mode).

        Retourne profil actif (auto/local_ssd/nas_smb), override user, profils
        disponibles et stockage detecte (heuristique drive type Windows).
        """
        return settings_support.get_advanced_pragma_settings_payload(
            state_dir=self._get_state_dir(),
        )

    def _set_advanced_pragma_settings_impl(
        self,
        profile_name: str,
        locking_mode_exclusive: bool = False,
    ) -> Dict[str, Any]:
        """VO-A : applique le profil PRAGMA et persiste dans settings.json.

        IMPORTANT : la bascule `locking_mode_exclusive=True` est destructive
        (empeche toute lecture DB en parallele). Le frontend DOIT confirmer
        via dangerConfirmModal avec countdown 3s avant d'envoyer True ici.
        """
        return settings_support.set_advanced_pragma_settings_payload(
            state_dir=self._get_state_dir(),
            profile_name=profile_name,
            locking_mode_exclusive=locking_mode_exclusive,
        )

    # ---------- VO-B-CONFIG : scan_max_workers (tri-etat auto/manuel) ----------
    def _get_scan_max_workers_impl(self) -> Dict[str, Any]:
        """VO-B-CONFIG : retourne l'etat actuel du setting scan_max_workers.

        Voir SettingsFacade.get_scan_max_workers pour la documentation
        complete et la synergie avec VO-A detect_storage.
        """
        return settings_support.get_scan_max_workers_payload(
            state_dir=self._get_state_dir(),
        )

    def _set_scan_max_workers_impl(
        self,
        mode: str,
        value: Any = None,
    ) -> Dict[str, Any]:
        """VO-B-CONFIG : persiste le setting scan_max_workers + retourne l'etat.

        Voir SettingsFacade.set_scan_max_workers pour la documentation.
        """
        return settings_support.set_scan_max_workers_payload(
            state_dir=self._get_state_dir(),
            mode=mode,
            value=value,
        )

    # ---------- misc ----------
    def open_path(self, path: str) -> Dict[str, Any]:
        return history_support.open_path(
            self,
            path,
            default_root=DEFAULT_ROOT,
            normalize_user_path=_normalize_user_path,
        )

    # ---------- support / logs (V3-13) ----------
    def _get_log_paths_impl(self) -> Dict[str, Any]:
        """V3-13 — Retourne les chemins des logs (pour affichage UI + copie)."""
        log_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CineSort", "logs")
        return {
            "data": {
                "log_dir": log_dir,
                "main_log": os.path.join(log_dir, "cinesort.log"),
                "exists": os.path.isdir(log_dir),
            }
        }

    def _open_logs_folder_impl(self) -> Dict[str, Any]:
        """V3-13 — Ouvre le dossier des logs dans l'explorateur Windows.

        Cf issue #72 (audit-2026-05-12:e3f5) : si la requete vient d'un client
        REST distant (LAN), on refuse l'ouverture pour eviter le DoS UX (un
        attaquant authentifie pouvait spammer cet endpoint et ouvrir des
        fenetres Explorer en chaine sur le PC server). Operation autorisee
        uniquement depuis le caller local (desktop natif ou 127.0.0.1).
        """

        if is_remote_request():
            return _err_response(
                "Operation locale uniquement (l'ouverture de l'explorateur n'est pas autorisee via REST distant).",
                category="permission",
                level="info",
                log_module=__name__,
                key="error",
            )
        log_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CineSort", "logs")
        if not os.path.isdir(log_dir):
            return _err_response(
                "Dossier logs introuvable",
                category="state",
                level="info",
                log_module=__name__,
                key="error",
                log_dir=log_dir,
            )
        try:
            os.startfile(log_dir)  # type: ignore[attr-defined]
            return {"ok": True, "opened": log_dir}
        except OSError as exc:
            return _err_response(
                str(exc), category="runtime", level="error", log_module=__name__, key="error", log_dir=log_dir
            )

    def _open_external_url_impl(self, url: str = "") -> Dict[str, Any]:
        """Fix audit 2026-05-24 : ouvre une URL externe dans le navigateur par defaut OS.

        WebView2 sans handler `on_new_window_request` bloque silencieusement
        `target="_blank"` et `window.open()` -> les boutons GitHub / TMDb /
        documentation dans aide.js / about.js / qualite.js ne faisaient rien.
        Ce endpoint permet au frontend de demander explicitement une ouverture
        externe via webbrowser.open() Python.

        Securite : autorise uniquement les schemes http(s) + bloque request
        REST distant pour eviter DoS UX (spam d'ouvertures sur le PC server).
        """
        if is_remote_request():
            return _err_response(
                "Operation locale uniquement.",
                category="permission",
                level="info",
                log_module=__name__,
            )
        u = str(url or "").strip()
        if not u:
            return _err_response("URL vide.", category="validation", level="info", log_module=__name__)
        # Whitelist scheme http(s) uniquement (evite file://, javascript:, data:, etc.)
        u_lower = u.lower()
        if not (u_lower.startswith("https://") or u_lower.startswith("http://")):
            return _err_response(
                "Schemes autorises : http, https.",
                category="validation",
                level="info",
                log_module=__name__,
            )
        try:
            import webbrowser as _webbrowser

            _webbrowser.open(u)
            return {"ok": True, "opened": u}
        except (OSError, RuntimeError) as exc:
            return _err_response(str(exc), category="runtime", level="warning", log_module=__name__)

    # ---------- Spec 12-aide.md (Phase 4 — ecran Aide) ----------
    # 4 endpoints exposes via la facade api.runtime.X(). Les methodes _impl
    # delegent au module runtime_support pour garder cinesort_api.py mince.

    def _get_diagnostic_impl(self) -> Dict[str, Any]:
        """Retourne le diagnostic complet pour le bouton "Copier diagnostic".

        Cf docs/internal/design/refonte_2026_05_17/screens/12-aide.md section 4.
        """
        return runtime_support.get_diagnostic(self)

    def _get_recent_logs_impl(self, limit: int = 100) -> Dict[str, Any]:
        """Lit les N dernieres lignes du log courant (cap a 1000)."""
        return runtime_support.get_recent_logs(self, limit)

    def _get_doc_impl(self, file: str) -> Dict[str, Any]:
        """Retourne le contenu markdown brut d'un document whiteliste.

        Securite : refuse tout chemin contenant `..` ou doc_id inconnu
        (category="validation").
        """
        return runtime_support.get_doc(self, file)

    def _search_docs_impl(self, query: str) -> Dict[str, Any]:
        """Recherche full-text dans tous les documents whitelistes."""
        return runtime_support.search_docs(self, query)

    def _get_app_version_impl(self) -> Dict[str, Any]:
        """Retourne la version applicative + metadonnees build pour l'ecran About.

        Source de verite : fichier `VERSION` a la racine (lu au demarrage dans
        `self._app_version`). Inclut aussi `build_date` (mtime du fichier
        VERSION), `git_sha` (best-effort via `git rev-parse`, vide si indispo
        ex. installation packagee sans .git), et `python_version`.

        Endpoint dedie pour about.js (cf web/dashboard/views/about.js).
        Cle "version" = ce que about.js consomme ; les autres champs enrichissent
        l'affichage sans casser la backward-compat si absents.

        Returns:
            {ok: True, version: str, build_date: str, git_sha: str, python_version: str}
        """
        # Imports locaux : evite de polluer le top-level pour un endpoint
        # ponctuel (subprocess lourd, sys/datetime non utilises au module-level).
        import datetime as _dt  # noqa: PLC0415
        import subprocess  # noqa: PLC0415
        import sys  # noqa: PLC0415

        version = str(getattr(self, "_app_version", "") or "unknown")

        # build_date : mtime du fichier VERSION (date ISO UTC). Best-effort.
        build_date = ""
        try:
            version_file = Path(__file__).resolve().parents[3] / "VERSION"
            if version_file.is_file():
                mtime = version_file.stat().st_mtime
                build_date = _dt.datetime.fromtimestamp(mtime, tz=_dt.timezone.utc).date().isoformat()
        except (OSError, ValueError):
            pass

        # git_sha : court (7 chars), best-effort. Vide si pas un repo git ou git absent.
        git_sha = ""
        try:
            repo_root = Path(__file__).resolve().parents[3]
            if (repo_root / ".git").exists():
                result = subprocess.run(  # noqa: S603 - args fixes, pas d'injection
                    ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],  # noqa: S607
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if result.returncode == 0:
                    git_sha = result.stdout.strip()
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

        python_version = ".".join(str(x) for x in sys.version_info[:3])

        return {
            "ok": True,
            "version": version,
            "build_date": build_date,
            "git_sha": git_sha,
            "python_version": python_version,
        }
