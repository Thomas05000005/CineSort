from __future__ import annotations

# Timeouts (seconds) for external tool invocations.
VERSION_PROBE_TIMEOUT_S = 6.0
VERSION_PROBE_DETAILED_TIMEOUT_S = 8.0
FILE_PROBE_TIMEOUT_S = 30.0
WINGET_INSTALL_TIMEOUT_S = 1800.0

# V5-04 (Polish Total v7.7.0, R5-STRESS-1) : parallelisation probe batch.
# ffprobe / mediainfo sont I/O-bound (attente subprocess), ThreadPoolExecutor
# est ideal — pas de besoin multiprocessing. Le cap a 16 evite de saturer
# le file system / les NAS lents avec trop de subprocess concurrents.
PROBE_WORKERS_MAX = 16
PROBE_WORKERS_AUTO_CAP = 8  # `min(cpu_count(), 8)` quand probe_workers=0 (auto)
