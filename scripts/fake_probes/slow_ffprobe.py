#!/usr/bin/env python3
"""Shim ffprobe LENT (harness panne synthetique - scenario a).

Dort SLOW_PROBE_SLEEP_SECONDS (defaut 35s) avant de retourner stdout vide.
Simule un SMB/NAS hyper-lent qui repond mais au-dela du timeout raisonnable.

Activation:
    set CINESORT_FAKE_PROBE=slow
    set PATH=%CD%\\scripts\\fake_probes;%PATH%
    ffprobe.exe foo.mkv   -> dort 35s puis exit 0 stdout vide

Override duree:
    set SLOW_PROBE_SLEEP_SECONDS=5   (pour tests rapides)

NE PAS modifier code produit (cinesort/) - ceci est outillage scripts/.
"""
from __future__ import annotations

import os
import sys
import time


def main() -> int:
    sleep_s = float(os.environ.get("SLOW_PROBE_SLEEP_SECONDS", "35"))
    # Log discret stderr pour debug harness (ne pollue pas stdout que le caller parse)
    sys.stderr.write(
        f"[fake_probe slow_ffprobe] sleeping {sleep_s}s "
        f"(args={sys.argv[1:]!r})\n"
    )
    sys.stderr.flush()
    time.sleep(sleep_s)
    # stdout vide = probe sans donnees exploitables
    return 0


if __name__ == "__main__":
    sys.exit(main())
