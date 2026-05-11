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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
