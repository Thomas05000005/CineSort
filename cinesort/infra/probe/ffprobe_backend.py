from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .constants import FILE_PROBE_TIMEOUT_S
from .tooling import RunnerFn


def run_ffprobe_json(
    *,
    tool_path: str,
    media_path: Path,
    runner: RunnerFn,
    timeout_s: float = FILE_PROBE_TIMEOUT_S,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    messages: List[str] = []
    # §5 v7.5.0 : ajout de show_frames + read_intervals pour extraire le
    # side_data_list HDR (mastering display, content light level, DV, HDR10+).
    # Cout: ~300-500ms par fichier au scan initial. Acceptable.
    # On ne restreint PAS avec -show_entries : le JSON gagne un champ "frames"
    # mais conserve streams + format complets (retro-compat totale).
    cmd = [
        str(tool_path),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-show_frames",
        "-read_intervals",
        "%+#1",
        str(media_path),
    ]
    try:
        rc, out, err = runner(cmd, timeout_s)
    except subprocess.TimeoutExpired as exc:
        # ITER13 RETRY_BACKOFF : apres epuisement des retries dans
        # `default_runner`, TimeoutExpired peut surfacer ici. Auparavant cette
        # exception n'etait PAS dans le tuple except -> elle remontait jusqu'au
        # REST handler en HTTP 500 + payload incomplet (cf BILAN_ITER13 §2).
        # Maintenant: degradation VISIBLE (message clair), pas silencieuse.
        messages.append(
            f"ffprobe timeout apres {getattr(exc, 'timeout', timeout_s):.0f}s "
            f"(retries epuises): {exc}"
        )
        return None, messages
    except (OSError, TimeoutError, TypeError, ValueError) as exc:
        messages.append(f"ffprobe echec execution: {exc}")
        return None, messages

    if rc != 0:
        details = (err or out or "").strip()
        if details:
            messages.append(f"ffprobe echec (code {rc}): {details[:300]}")
        else:
            messages.append(f"ffprobe echec (code {rc}).")
        return None, messages

    text = (out or "").strip()
    if not text:
        messages.append("ffprobe n'a retourne aucune sortie.")
        return None, messages

    try:
        parsed = json.loads(text)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        messages.append(f"ffprobe JSON invalide: {exc}")
        return None, messages

    if not isinstance(parsed, dict):
        messages.append("ffprobe JSON non exploitable (objet attendu).")
        return None, messages
    return parsed, messages
