from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

PROBE_QUALITY_FULL = "FULL"
PROBE_QUALITY_PARTIAL = "PARTIAL"
PROBE_QUALITY_FAILED = "FAILED"


@dataclass
class NormalizedProbe:
    path: str
    container: Optional[str] = None
    container_title: Optional[str] = None
    duration_s: Optional[float] = None
    video: Dict[str, Any] = field(default_factory=dict)
    audio_tracks: List[Dict[str, Any]] = field(default_factory=list)
    subtitles: List[Dict[str, Any]] = field(default_factory=list)
    # Source par champ (mediainfo / ffprobe / mediainfo+ffprobe / none)
    sources: Dict[str, Any] = field(default_factory=dict)
    probe_quality: str = PROBE_QUALITY_FAILED
    probe_quality_reasons: List[str] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)

    # Fix audit 2026-05-25 (v1.5.5) Vague K : extension "NFO complet"
    # Champs additionnels extraits depuis ffprobe pour permettre la generation
    # d'un fichier NFO complet (containerextended, chapitres, encoder, bitrate
    # global, sample_rate audio, dispositions sous-titres, etc.).
    # Tous les champs ci-dessous sont OPTIONNELS et n'affectent pas la
    # retro-compat : les anciens consommateurs lisent toujours `video`,
    # `audio_tracks`, `subtitles` (formats inchanges, simplement enrichis).
    container_format_long: Optional[str] = None  # "matroska,webm" complet
    container_size_bytes: Optional[int] = None  # taille du fichier
    container_bit_rate: Optional[int] = None  # global, bits/s
    container_encoder: Optional[str] = None  # writing application
    container_creation_time: Optional[str] = None  # ISO8601 si dispo
    chapters: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
