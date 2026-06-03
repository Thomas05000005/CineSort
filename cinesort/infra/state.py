from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "CineSort"
_DEBUG_ENV_VALUES = {"1", "true", "yes", "on", "debug"}


def _debug_enabled() -> bool:
    return str(os.environ.get("CINESORT_DEBUG", "")).strip().lower() in _DEBUG_ENV_VALUES


def _debug_log_state(state_dir: Path, message: str) -> None:
    if not _debug_enabled():
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        p = state_dir / "debug_state.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")
    except OSError:
        # Best-effort debug logging : mkdir / open / write peuvent lever OSError
        # (PermissionError, FileNotFoundError, etc., qui en derivent). Les
        # ImportError / KeyError / TypeError / ValueError historiques ici
        # n'avaient pas de cause plausible et masquaient des bugs reels.
        return


def default_state_dir() -> Path:
    """
    Local PC (evite ecritures reseau).
    """
    base = os.environ.get("LOCALAPPDATA", ".")
    return Path(base) / APP_NAME


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    run_dir: Path
    plan_jsonl: Path
    ui_log_txt: Path
    summary_txt: Path
    validation_json: Path


def new_run(state_dir: Path, run_id: str) -> RunPaths:
    runs = state_dir / "runs"
    run_dir = runs / f"tri_films_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    return RunPaths(
        run_id=run_id,
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )


def read_text_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, PermissionError):
        return ""


def write_text_safe(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def atomic_write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = f"{p.name}.tmp.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.{uuid.uuid4().hex[:8]}"
    tmp = p.with_name(tmp_name)
    try:
        # flush + fsync avant rename : sans cela, os.replace est atomique cote
        # VFS mais ne garantit PAS que les pages ecrites dans tmp sont durables.
        # Sur crash (BSOD, coupure courant), un fichier renomme mais avec
        # contenu tronque/0 byte est possible (ext4 sans data=ordered, NTFS,
        # ZFS). Critique pour validation.json et autres fichiers de reprise.
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, ensure_ascii=False, indent=2))
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                # fsync peut echouer sur certains montages reseau / fs en lecture
                # seule ; on n'echoue pas l'ecriture pour autant (best-effort).
                pass
        os.replace(tmp, p)
    finally:
        # Best-effort cleanup : tmp.exists() / tmp.unlink() ne peuvent lever
        # qu'OSError (PermissionError, FileNotFoundError en derivent). Les
        # KeyError / TypeError / ValueError / JSONDecodeError historiques ici
        # n'avaient pas de cause plausible sur ces 2 syscalls.
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def clean_old_runs(state_dir: Path, keep_last: int = 10) -> None:
    runs = state_dir / "runs"
    if not runs.exists():
        return
    items = sorted([d for d in runs.iterdir() if d.is_dir()], key=lambda x: x.name, reverse=True)
    for d in items[keep_last:]:
        try:
            shutil.rmtree(d)
        except OSError as exc:
            _debug_log_state(state_dir, f"clean_old_runs warning path={d} error={exc}")
