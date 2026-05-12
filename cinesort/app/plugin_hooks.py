"""Plugin hooks post-action — execute des scripts utilisateur apres certains evenements.

Les scripts sont decouverts dans le dossier plugins/ (a cote de app.py ou de l'exe).
Convention de nommage : post_scan_xxx.py → declenche sur post_scan uniquement,
any_xxx.py → declenche sur tous les evenements, xxx.py → idem.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.infra.subprocess_safety import tracked_run

logger = logging.getLogger("cinesort.plugins")

# Evenements supportes
HOOK_EVENTS = frozenset({"post_scan", "post_apply", "post_undo", "post_error"})

# Extensions de scripts supportees
_SCRIPT_EXTS = frozenset({".py", ".bat", ".ps1"})


def _resolve_plugins_dir() -> Path:
    """Localise le dossier plugins/ a cote du code source ou de l'exe PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "plugins"
    return Path(__file__).resolve().parents[2] / "plugins"


def discover_plugins(plugins_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Scan le dossier plugins/ et retourne la liste des plugins avec leurs evenements cibles."""
    pdir = plugins_dir or _resolve_plugins_dir()
    if not pdir.is_dir():
        return []
    plugins: List[Dict[str, Any]] = []
    try:
        entries = sorted(pdir.iterdir(), key=lambda p: p.name.lower())
    except (OSError, PermissionError):
        return []
    for entry in entries:
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in _SCRIPT_EXTS:
            continue
        stem = entry.stem.lower()
        # Deduire les evenements depuis le nom
        events = _events_from_name(stem)
        plugins.append(
            {
                "name": entry.name,
                "path": str(entry),
                "events": events,
            }
        )
    return plugins


def _events_from_name(stem: str) -> List[str]:
    """Deduit les evenements cibles depuis le nom du fichier (sans extension)."""
    for event in HOOK_EVENTS:
        if stem.startswith(event + "_") or stem == event:
            return [event]
    if stem.startswith("any_") or stem == "any":
        return sorted(HOOK_EVENTS)
    # Pas de prefixe reconnu → tous les evenements
    return sorted(HOOK_EVENTS)


def dispatch_hook(
    event: str,
    data: Dict[str, Any],
    *,
    plugins_dir: Optional[Path] = None,
    timeout_s: int = 30,
) -> None:
    """Dispatch un evenement aux plugins concernes. Execute dans un thread daemon."""
    if event not in HOOK_EVENTS:
        return
    plugins = discover_plugins(plugins_dir)
    matching = [p for p in plugins if event in p["events"]]
    if not matching:
        return
    # Execution dans un thread daemon pour ne pas bloquer le flow principal
    t = threading.Thread(
        target=_dispatch_sync,
        args=(event, data, matching, timeout_s),
        daemon=True,
        name=f"plugin-hook-{event}",
    )
    t.start()


def _dispatch_sync(
    event: str,
    data: Dict[str, Any],
    plugins: List[Dict[str, Any]],
    timeout_s: int,
) -> None:
    """Execute sequentiellement les plugins concernes (dans un thread)."""
    for plugin in plugins:
        try:
            _run_plugin(Path(plugin["path"]), event, data, timeout_s)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            logger.warning("[plugins] exception dispatch %s %s: %s", event, plugin["name"], exc)


def _run_plugin(
    plugin_path: Path,
    event: str,
    data: Dict[str, Any],
    timeout_s: int,
) -> None:
    """Execute un script plugin avec JSON sur stdin et env vars."""
    payload = json.dumps({"event": event, **data}, ensure_ascii=False, default=str)
    env = dict(os.environ)
    env["CINESORT_EVENT"] = event
    env["CINESORT_RUN_ID"] = str(data.get("run_id") or "")

    # Determiner la commande selon l'extension
    ext = plugin_path.suffix.lower()
    if ext == ".py":
        cmd = [sys.executable, str(plugin_path)]
    elif ext == ".bat":
        cmd = ["cmd.exe", "/c", str(plugin_path)]
    elif ext == ".ps1":
        cmd = ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(plugin_path)]
    else:
        logger.warning("[plugins] extension non supportee: %s", plugin_path)
        return

    logger.info("[plugins] exec %s for %s", plugin_path.name, event)
    try:
        # tracked_run garantit kill+wait du child meme sur KeyboardInterrupt
        # ou MemoryError (subprocess.run brut le fait uniquement sur
        # TimeoutExpired). Drop-in compatible avec subprocess.run.
        result = tracked_run(
            cmd,
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()[:200]
            logger.warning(
                "[plugins] %s exit=%d stderr=%s",
                plugin_path.name,
                result.returncode,
                stderr,
            )
        else:
            logger.debug("[plugins] %s OK", plugin_path.name)
    except subprocess.TimeoutExpired:
        logger.warning("[plugins] %s timeout (%ds)", plugin_path.name, timeout_s)
    except (OSError, FileNotFoundError) as exc:
        logger.warning("[plugins] %s exec error: %s", plugin_path.name, exc)
