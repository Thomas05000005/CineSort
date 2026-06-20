#!/usr/bin/env python3
"""Shim mediainfo LENT (harness panne synthetique - scenario a).

Pendant strict de slow_ffprobe.py: dort SLOW_PROBE_SLEEP_SECONDS avant exit 0.

Activation:
    set CINESORT_FAKE_PROBE=slow
    set PATH=%CD%\\scripts\\fake_probes;%PATH%
    mediainfo.exe foo.mkv -> dort 35s puis exit 0

NE PAS modifier code produit (cinesort/).
"""
from __future__ import annotations

import os
import sys
import time


def main() -> int:
    sleep_s = float(os.environ.get("SLOW_PROBE_SLEEP_SECONDS", "35"))
    sys.stderr.write(
        f"[fake_probe slow_mediainfo] sleeping {sleep_s}s "
        f"(args={sys.argv[1:]!r})\n"
    )
    sys.stderr.flush()
    time.sleep(sleep_s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
