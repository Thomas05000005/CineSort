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

# ITER13 mecanisme TIMEOUT_ADAPTATIF (2026-06-10) :
# Le timeout file probe etait un couperet unique (30s defaut, 5-300s clampe)
# sans tenir compte de la taille du fichier. Resultat : un petit MP4 1080p
# acceptait jusqu'a 300s (ridicule), un gros 4K HEVC 80 GB sur NAS lent
# coupait a 30s (faux negatif). Le timeout adaptatif corrige les 2 cas :
# timeout = base + multiplier * (file_size / size_unit), borne [floor, ceiling].
#
# Defauts choisis :
# - base 30s = ancien defaut, retro-compat fichier de taille moyenne (~5 GB).
# - +5s par GB = empirique, ffprobe doit lire l'index moov + sidx,
#   sur NAS SMB lent (5-10 MB/s) un fichier 20 GB peut demander 30-60s
#   de transfert avant meme de commencer le parse.
# - floor 10s = ne descend jamais en-dessous (evite scintillement reseau).
# - ceiling 300s = ne monte jamais au-dessus (evite hang infini sur fichier
#   geant injoignable, deja le clamp historique probe_timeout_s).
PROBE_TIMEOUT_BASE_S = 30.0
PROBE_TIMEOUT_PER_GB_S = 5.0
PROBE_TIMEOUT_FLOOR_S = 10.0
PROBE_TIMEOUT_CEILING_S = 300.0
_PROBE_TIMEOUT_GB_UNIT_BYTES = 1024 * 1024 * 1024  # 1 GiB en octets
