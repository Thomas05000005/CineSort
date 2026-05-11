"""Internal diagnostics helpers for the pywebview API facade."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from cinesort.infra.log_scrubber import scrub_secrets


def debug_enabled(
    settings: Optional[Dict[str, Any]],
    *,
    env_truthy_fn: Callable[[str], bool],
    to_bool_fn: Callable[[Any, bool], bool],
) -> bool:
    if settings is not None and "debug_enabled" in settings:
        return to_bool_fn(settings.get("debug_enabled"), False)
    return env_truthy_fn("CINESORT_DEBUG")


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as file_obj:
        file_obj.write(text)


def debug_log(
    api: Any,
    *,
    state_dir: Path,
    run_id: Optional[str],
    enabled: bool,
    message: str,
) -> None:
    if not enabled:
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    # CodeQL py/clear-text-storage-sensitive-data : on applique le scrubber
    # AVANT d'ecrire en disque, par symetrie avec le logging stdlib (qui
    # passe par log_scrubber via SecretsScrubFilter). Si l'appelant passe
    # accidentellement un message contenant un secret (api_key, token,
    # password, etc.), il sera masque dans le fichier.
    safe_message = scrub_secrets(message)
    line = f"[{ts}] {safe_message}\n"
    try:
        append_text(state_dir / "debug_api.log", line)
    except (OSError, PermissionError):
        return
    if run_id:
        try:
            run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=True)
            append_text(run_paths.run_dir / "debug.log", line)
        except (KeyError, OSError, TypeError, ValueError):
            return


def sanitize_log_extra(extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(extra, dict):
        return {}

    def _one(value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for idx, (key, nested_value) in enumerate(value.items()):
                if idx >= 10:
                    break
                out[str(key)] = _one(nested_value)
            return out
        if isinstance(value, (list, tuple, set)):
            return [_one(item) for item in list(value)[:10]]
        return str(value)

    return {str(key): _one(value) for key, value in extra.items()}


def write_crash_file(
    api: Any,
    run_paths: Any,
    header: str,
    tb_text: str,
    *,
    env_truthy_fn: Callable[[str], bool],
) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    content = f"[{ts}] {header}\n\n{tb_text.rstrip()}\n"
    try:
        run_paths.run_dir.mkdir(parents=True, exist_ok=True)
        run_paths.run_dir.joinpath("crash.txt").write_text(content, encoding="utf-8")
    except (OSError, PermissionError, TypeError, ValueError) as exc:
        debug_log(
            api,
            state_dir=api._state_dir,
            run_id=run_paths.run_id,
            enabled=env_truthy_fn("CINESORT_DEBUG"),
            message=f"_write_crash_file warning: {exc}",
        )


def unique_path(base: Path) -> Path:
    if not base.exists():
        return base
    stem = base.stem
    suffix = base.suffix
    idx = 1
    while True:
        candidate = base.with_name(f"{stem}_{idx}{suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def write_summary_section(run_paths: Any, marker: str, section_body: str) -> None:
    marker_line = f"\n{marker}\n"
    existing_text = ""
    if run_paths.summary_txt.exists():
        existing_text = run_paths.summary_txt.read_text(encoding="utf-8")
    marker_idx = existing_text.find(marker_line)
    if marker_idx >= 0:
        existing_text = existing_text[:marker_idx].rstrip() + "\n"

    final_text = existing_text.rstrip("\n")
    if final_text:
        final_text += "\n"
    final_text += marker_line.lstrip("\n")
    final_text += section_body.strip("\n") + "\n"
    run_paths.summary_txt.write_text(final_text, encoding="utf-8")


def file_logger(api: Any, run_paths: Any, *, env_truthy_fn: Callable[[str], bool]) -> Callable[[str, str], None]:
    def _log(level: str, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        try:
            run_paths.ui_log_txt.parent.mkdir(parents=True, exist_ok=True)
            with open(run_paths.ui_log_txt, "a", encoding="utf-8") as file_obj:
                file_obj.write(f"[{ts}] {level}: {msg}\n")
        except (OSError, PermissionError) as exc:
            state_dir_guess = api._state_dir
            try:
                state_dir_guess = run_paths.run_dir.parent.parent
            except (OSError, PermissionError):
                state_dir_guess = api._state_dir
            debug_log(
                api,
                state_dir=state_dir_guess,
                run_id=run_paths.run_id,
                enabled=env_truthy_fn("CINESORT_DEBUG"),
                message=f"_file_logger warning ui_log write failed: {exc}",
            )

    return _log
