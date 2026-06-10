"""Adaptive timeout for ffprobe / mediainfo file probes.

ITER13 mecanisme TIMEOUT_ADAPTATIF (2026-06-10).

Probleme adresse
----------------
Avant ce module, `cinesort/infra/probe/service.py` utilisait un timeout unique
(probe_timeout_s, defaut 30s, clampe 5-300s) pour tous les fichiers. Resultat :

- petit MP4 1080p (200 MB) : 30s c'etait beaucoup trop genereux (probe < 1s),
  permettait a un fichier corrompu de bloquer le scan trop longtemps.
- gros 4K HEVC 80 GB sur NAS SMB lent (5-10 MB/s) : 30s coupait avant meme que
  ffprobe ait pu lire l'index moov + sidx (faux negatif systematique).

Logique du fix
--------------
Le timeout est calcule en fonction de la taille du fichier :

    timeout = base + multiplier * (file_size_bytes / GB), borne [floor, ceiling]

Defauts :
- base    : 30s (retro-compat fichier ~5 GB)
- per_gb  : 5s   (empirique NAS SMB lent)
- floor   : 10s  (jamais en-dessous, evite scintillement reseau)
- ceiling : 300s (jamais au-dessus, evite hang infini)

Configuration
-------------
1. Settings (UI) : `probe_timeout_base_s`, `probe_timeout_per_gb_s`,
   `probe_timeout_floor_s`, `probe_timeout_ceiling_s` (tous floats).
2. Env vars (override settings) :
   - `CINESORT_PROBE_TIMEOUT_BASE` (float, secondes)
   - `CINESORT_PROBE_TIMEOUT_PER_GB` (float, secondes par GB)
   - `CINESORT_PROBE_TIMEOUT_FLOOR` (float, secondes)
   - `CINESORT_PROBE_TIMEOUT_CEILING` (float, secondes)
3. Fallback : constantes `PROBE_TIMEOUT_*` dans constants.py.

Le legacy `probe_timeout_s` (UI settings) reste respecte si present : dans ce
cas il sert de `base`, et l'adaptatif n'est applique que si les autres champs
adaptatifs sont absents (retro-compat ABSOLUE).

Architecture
------------
Module pur infra (pas d'import app/ui), helpers stateless, deterministe.
Couvre uniquement le mecanisme TIMEOUT_ADAPTATIF. Le RETRY_BACKOFF, le
CIRCUIT_BREAKER, le CACHE_PROBE et le POLLING_UI_BACKOFF sont traites
separement (un seul mecanisme par fix, contrainte ITER13).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from cinesort.infra.probe.constants import (
    PROBE_TIMEOUT_BASE_S,
    PROBE_TIMEOUT_CEILING_S,
    PROBE_TIMEOUT_FLOOR_S,
    PROBE_TIMEOUT_PER_GB_S,
    _PROBE_TIMEOUT_GB_UNIT_BYTES,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdaptiveTimeoutConfig:
    """Config immuable pour le calcul du timeout adaptatif."""

    base_s: float
    per_gb_s: float
    floor_s: float
    ceiling_s: float

    def __post_init__(self) -> None:
        # Garanties d'invariants : floor <= ceiling, base >= 0, per_gb >= 0.
        # On ne raise PAS — on log et clamp pour rester resilient :
        # une config corrompue ne doit pas casser le scan, juste retomber
        # sur les defauts.
        if self.floor_s > self.ceiling_s:
            logger.warning(
                "AdaptiveTimeoutConfig: floor (%.1fs) > ceiling (%.1fs), "
                "config probablement invalide — calcul retombe sur defauts.",
                self.floor_s,
                self.ceiling_s,
            )


def _read_float_env(name: str) -> Optional[float]:
    """Lit une env var et retourne float ou None si absente/invalide.

    Helper stateless, NE leve PAS — env corrompu = fallback silencieux defaut.
    """
    raw = os.environ.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Env %s=%r invalide (float attendu), valeur ignoree.", name, raw
        )
        return None


def _read_float_setting(settings: Optional[Dict[str, Any]], key: str) -> Optional[float]:
    """Lit un float depuis un dict settings ou None si absent/invalide."""
    if not isinstance(settings, dict):
        return None
    val = settings.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def resolve_adaptive_timeout_config(
    settings: Optional[Dict[str, Any]] = None,
) -> AdaptiveTimeoutConfig:
    """Calcule la config adaptive : env > settings > defauts.

    Ordre de precedence (la 1ere valeur non-None gagne) :
    1. Env var (CINESORT_PROBE_TIMEOUT_*)
    2. Settings UI (probe_timeout_*_s)
    3. Constantes PROBE_TIMEOUT_*

    Le legacy `probe_timeout_s` est utilise comme base si `probe_timeout_base_s`
    n'est pas defini (retro-compat).
    """
    # base : env > settings.probe_timeout_base_s > settings.probe_timeout_s (legacy) > const
    base = _read_float_env("CINESORT_PROBE_TIMEOUT_BASE")
    if base is None:
        base = _read_float_setting(settings, "probe_timeout_base_s")
    if base is None:
        base = _read_float_setting(settings, "probe_timeout_s")
    if base is None:
        base = float(PROBE_TIMEOUT_BASE_S)

    per_gb = _read_float_env("CINESORT_PROBE_TIMEOUT_PER_GB")
    if per_gb is None:
        per_gb = _read_float_setting(settings, "probe_timeout_per_gb_s")
    if per_gb is None:
        per_gb = float(PROBE_TIMEOUT_PER_GB_S)

    floor = _read_float_env("CINESORT_PROBE_TIMEOUT_FLOOR")
    if floor is None:
        floor = _read_float_setting(settings, "probe_timeout_floor_s")
    if floor is None:
        floor = float(PROBE_TIMEOUT_FLOOR_S)

    ceiling = _read_float_env("CINESORT_PROBE_TIMEOUT_CEILING")
    if ceiling is None:
        ceiling = _read_float_setting(settings, "probe_timeout_ceiling_s")
    if ceiling is None:
        ceiling = float(PROBE_TIMEOUT_CEILING_S)

    # Clamp defensif : valeurs negatives ou aberrantes retombent sur defaut.
    if base < 0:
        base = float(PROBE_TIMEOUT_BASE_S)
    if per_gb < 0:
        per_gb = float(PROBE_TIMEOUT_PER_GB_S)
    if floor < 0:
        floor = float(PROBE_TIMEOUT_FLOOR_S)
    if ceiling <= 0:
        ceiling = float(PROBE_TIMEOUT_CEILING_S)

    return AdaptiveTimeoutConfig(
        base_s=base, per_gb_s=per_gb, floor_s=floor, ceiling_s=ceiling
    )


def _safe_file_size_bytes(media_path: Path) -> int:
    """Retourne la taille du fichier en octets ou 0 si stat impossible.

    NE leve PAS — fichier injoignable = on retourne 0, ce qui donne le base
    timeout (sans bonus taille). Cela laisse la chance au probe de tenter
    sans le penaliser pre-emptivement (l'indisponibilite sera detectee par
    le probe lui-meme).
    """
    try:
        return int(media_path.stat().st_size)
    except (OSError, ValueError, AttributeError):
        return 0


def compute_adaptive_timeout(
    media_path: Path,
    *,
    config: Optional[AdaptiveTimeoutConfig] = None,
    settings: Optional[Dict[str, Any]] = None,
) -> float:
    """Calcule un timeout subprocess adaptatif pour un fichier donne.

    Args:
        media_path: chemin du fichier (sert au stat pour taille).
        config: config pre-resolue (evite re-lecture env/settings dans une boucle).
        settings: settings UI (utilise si config est None).

    Returns:
        Timeout en secondes, clampe [floor, ceiling].

    Formule : `base + per_gb * (size_bytes / 1 GiB)`, puis clamp.

    Exemples (defauts : base=30, per_gb=5, floor=10, ceiling=300) :
    - 200 MB : 30 + 5 * 0.195 = 30.98s    (~ base, petit fichier)
    - 5 GB   : 30 + 5 * 5     = 55s        (taille moyenne)
    - 20 GB  : 30 + 5 * 20    = 130s       (gros 4K HEVC)
    - 80 GB  : 30 + 5 * 80    = 300s clampe ceiling (limite haute)
    - fichier injoignable (size=0) : 30s = base (pas de bonus, pas de penalite)
    """
    if config is None:
        config = resolve_adaptive_timeout_config(settings)

    size_bytes = _safe_file_size_bytes(media_path)
    size_gb = float(size_bytes) / float(_PROBE_TIMEOUT_GB_UNIT_BYTES)

    raw_timeout = config.base_s + config.per_gb_s * size_gb

    # Clamp [floor, ceiling]. Si floor > ceiling (config invalide deja loggee),
    # on retombe sur ceiling pour rester safe.
    floor = config.floor_s
    ceiling = config.ceiling_s
    if floor > ceiling:
        return ceiling
    return max(floor, min(ceiling, raw_timeout))
