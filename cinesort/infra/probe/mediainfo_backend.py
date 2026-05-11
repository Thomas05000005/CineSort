from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .constants import FILE_PROBE_TIMEOUT_S
from .tooling import RunnerFn


def run_mediainfo_json(
    *,
    tool_path: str,
    media_path: Path,
    runner: RunnerFn,
    timeout_s: float = FILE_PROBE_TIMEOUT_S,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    messages: List[str] = []
    cmd = [str(tool_path), "--Output=JSON", str(media_path)]
    try:
        rc, out, err = runner(cmd, timeout_s)
    except (ImportError, OSError, TypeError, ValueError) as exc:
        messages.append(f"MediaInfo echec execution: {exc}")
        return None, messages

    if rc != 0:
        details = (err or out or "").strip()
        if details:
            messages.append(f"MediaInfo echec (code {rc}): {details[:300]}")
        else:
            messages.append(f"MediaInfo echec (code {rc}).")
        return None, messages

    text = (out or "").strip()
    if not text:
        messages.append("MediaInfo n'a retourne aucune sortie.")
        return None, messages

    try:
        parsed = json.loads(text)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        messages.append(f"MediaInfo JSON invalide: {exc}")
        return None, messages

    if not isinstance(parsed, dict):
        messages.append("MediaInfo JSON non exploitable (objet attendu).")
        return None, messages
    return parsed, messages
