"""Point d'entree public pour la normalisation des probes mediainfo / ffprobe.

Vague M, M-04 : module decoupe en sous-modules privees pour faciliter la
maintenance (739 LOC -> facade + 4 sous-modules ~200 LOC chacun).

Sous-modules :
- _normalize_helpers : conversions atomiques (_to_int / _to_float / _to_bitrate_int / _bool_from_text /
                       _ratio_to_fps / _duration_seconds_from_mediainfo / _pick_value / _merge_flag /
                       _extract_bit_depth).
- _normalize_mediainfo : extraction MediaInfo (_extract_mediainfo).
- _normalize_ffprobe : extraction ffprobe (_extract_ffprobe, _ffprobe_video_dict, _detect_atmos_dtsx).
- _normalize_merge : fusion + qualite (_extract_tracks, _merge_probes, _determine_quality).

Le re-export via __all__ + imports relatifs preserve la compatibilite stricte avec
les tests existants (tests/test_probe_normalize_complete.py, test_dolby_vision.py,
test_mkv_title.py, test_quality_score_accepts_normalizedprobe.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.domain.probe_models import NormalizedProbe
from cinesort.infra.probe._normalize_ffprobe import (
    _detect_atmos_dtsx,
    _extract_ffprobe,
    _ffprobe_video_dict,
)
from cinesort.infra.probe._normalize_helpers import (
    _bool_from_text,
    _duration_seconds_from_mediainfo,
    _extract_bit_depth,
    _merge_flag,
    _pick_value,
    _ratio_to_fps,
    _to_bitrate_int,
    _to_float,
    _to_int,
)
from cinesort.infra.probe._normalize_mediainfo import _extract_mediainfo
from cinesort.infra.probe._normalize_merge import (
    _determine_quality,
    _extract_tracks,
    _merge_probes,
)

__all__ = [
    "normalize_probe",
    # Helpers prives re-exportes pour les tests
    "_bool_from_text",
    "_detect_atmos_dtsx",
    "_determine_quality",
    "_duration_seconds_from_mediainfo",
    "_extract_bit_depth",
    "_extract_ffprobe",
    "_extract_mediainfo",
    "_extract_tracks",
    "_ffprobe_video_dict",
    "_merge_flag",
    "_merge_probes",
    "_pick_value",
    "_ratio_to_fps",
    "_to_bitrate_int",
    "_to_float",
    "_to_int",
]


def normalize_probe(
    *,
    media_path: Path,
    raw_mediainfo: Optional[Dict[str, Any]],
    raw_ffprobe: Optional[Dict[str, Any]],
    backend: str,
    messages: List[str],
) -> NormalizedProbe:
    """Fusionne les payloads mediainfo + ffprobe en un NormalizedProbe canonique.

    Signature publique inchangee depuis Vague K (NFO complet). Les helpers
    prives sont accessibles via les sous-modules ou re-exportes depuis ce
    module pour la retro-compat des tests.
    """
    mi, ff = _extract_tracks(raw_mediainfo, raw_ffprobe)

    normalized = NormalizedProbe(path=str(media_path))
    normalized.messages = list(messages or [])

    _merge_probes(mi, ff, normalized)
    _determine_quality(normalized, raw_mediainfo=raw_mediainfo, raw_ffprobe=raw_ffprobe, backend=backend)

    return normalized
