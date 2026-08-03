#!/usr/bin/env python3
"""Shim ffprobe INTERMITTENT (harness panne synthetique - scenario c).

Echoue les FLAKY_PROBE_FAIL_FIRST_N premieres tentatives, puis reussit.
Sert a tester le retry+backoff cote CineSort.

Compteur persistant dans %TEMP%/cinesort_fake_probe_count.txt pour traverser
les invocations subprocess separees. Reset: supprimer le fichier OU
set FLAKY_PROBE_RESET=1.

Activation:
    set CINESORT_FAKE_PROBE=flaky
    set FLAKY_PROBE_FAIL_FIRST_N=2   (defaut 2)
    set PATH=%CD%\\scripts\\fake_probes;%PATH%

NE PAS modifier code produit (cinesort/).
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from pathlib import Path

COUNTER_FILE = Path(tempfile.gettempdir()) / "cinesort_fake_probe_count.txt"


def _read_counter() -> int:
    try:
        return int(COUNTER_FILE.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def _write_counter(n: int) -> None:
    try:
        COUNTER_FILE.write_text(str(n), encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"[fake_probe flaky_ffprobe] counter write failed: {exc}\n")


def main() -> int:
    fail_n = int(os.environ.get("FLAKY_PROBE_FAIL_FIRST_N", "2"))
    if os.environ.get("FLAKY_PROBE_RESET") == "1":
        with contextlib.suppress(OSError):
            COUNTER_FILE.unlink(missing_ok=True)

    count = _read_counter() + 1
    _write_counter(count)

    if count <= fail_n:
        sys.stderr.write(f"[fake_probe flaky_ffprobe] attempt {count}/{fail_n} -> FAIL (args={sys.argv[1:]!r})\n")
        sys.stderr.write("ffprobe: simulated I/O error (SMB timeout)\n")
        return 1

    sys.stderr.write(f"[fake_probe flaky_ffprobe] attempt {count} -> OK (args={sys.argv[1:]!r})\n")
    # Minimal JSON exploitable cote parse (vide format/streams = degradation visible)
    sys.stdout.write('{"streams": [], "format": {}}\n')
    return 0


if __name__ == "__main__":
    sys.exit(main())
