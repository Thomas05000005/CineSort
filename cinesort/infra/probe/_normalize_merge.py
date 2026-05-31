"""Merge ffprobe / mediainfo et determination de la qualite de la probe.

Vague M, M-04 split : extrait depuis normalize.py la logique de fusion des
dictionnaires intermediaires en NormalizedProbe et l'evaluation FULL / PARTIAL /
FAILED.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from cinesort.domain.probe_models import (
    PROBE_QUALITY_FAILED,
    PROBE_QUALITY_FULL,
    PROBE_QUALITY_PARTIAL,
    NormalizedProbe,
)
from cinesort.infra.probe._normalize_ffprobe import _extract_ffprobe
from cinesort.infra.probe._normalize_helpers import (
    _merge_flag,
    _pick_value,
    _to_int,
)
from cinesort.infra.probe._normalize_mediainfo import _extract_mediainfo


def _extract_tracks(
    raw_mediainfo: Optional[Dict[str, Any]],
    raw_ffprobe: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return _extract_mediainfo(raw_mediainfo), _extract_ffprobe(raw_ffprobe)


def _merge_probes(
    mi: Dict[str, Any],
    ff: Dict[str, Any],
    normalized: NormalizedProbe,
) -> None:
    container, container_src = _pick_value(
        ffprobe_value=ff.get("container"),
        mediainfo_value=mi.get("container"),
        prefer_ffprobe=False,
    )
    duration_s, duration_src = _pick_value(
        ffprobe_value=ff.get("duration_s"),
        mediainfo_value=mi.get("duration_s"),
        prefer_ffprobe=True,
    )
    normalized.container = str(container) if container else None
    normalized.duration_s = round(float(duration_s), 3) if duration_s is not None else None

    container_title, container_title_src = _pick_value(
        ffprobe_value=ff.get("container_title"),
        mediainfo_value=mi.get("container_title"),
        prefer_ffprobe=True,
    )
    normalized.container_title = str(container_title).strip() if container_title else None

    # Fix audit 2026-05-25 (v1.5.5) Vague K : propagation champs container additionnels
    # ffprobe est la source unique pour ces champs (pas de symetrie mediainfo).
    container_format_long = ff.get("container_format_long")
    normalized.container_format_long = str(container_format_long).strip() if container_format_long else None
    normalized.container_size_bytes = _to_int(ff.get("container_size_bytes"))
    normalized.container_bit_rate = _to_int(ff.get("container_bit_rate"))
    container_encoder = ff.get("container_encoder")
    normalized.container_encoder = str(container_encoder).strip() if container_encoder else None
    container_creation_time = ff.get("container_creation_time")
    normalized.container_creation_time = str(container_creation_time).strip() if container_creation_time else None
    ff_chapters = ff.get("chapters") if isinstance(ff.get("chapters"), list) else []
    normalized.chapters = list(ff_chapters)

    mi_video = mi.get("video") if isinstance(mi.get("video"), dict) else {}
    ff_video = ff.get("video") if isinstance(ff.get("video"), dict) else {}
    video: Dict[str, Any] = {}
    video_sources: Dict[str, str] = {}

    for key in ("codec", "width", "height", "fps", "bit_depth", "pixel_format", "bitrate"):
        val, src = _pick_value(
            ffprobe_value=ff_video.get(key),
            mediainfo_value=mi_video.get(key),
            prefer_ffprobe=True,
        )
        video[key] = val
        video_sources[key] = src

    hdr_dv, hdr_dv_src = _merge_flag(
        bool(mi_video.get("hdr_dolby_vision")),
        bool(ff_video.get("hdr_dolby_vision")),
        bool(mi_video.get("_hdr_text_present")),
        bool(ff_video.get("_hdr_text_present")),
    )
    hdr10, hdr10_src = _merge_flag(
        bool(mi_video.get("hdr10")),
        bool(ff_video.get("hdr10")),
        bool(mi_video.get("_hdr_text_present")),
        bool(ff_video.get("_hdr_text_present")),
    )
    hdr10_plus, hdr10_plus_src = _merge_flag(
        bool(mi_video.get("hdr10_plus")),
        bool(ff_video.get("hdr10_plus")),
        bool(mi_video.get("_hdr_text_present")),
        bool(ff_video.get("_hdr_text_present")),
    )
    video["hdr_dolby_vision"] = hdr_dv
    video["hdr10"] = hdr10
    video["hdr10_plus"] = hdr10_plus
    video_sources["hdr_dolby_vision"] = hdr_dv_src
    video_sources["hdr10"] = hdr10_src
    video_sources["hdr10_plus"] = hdr10_plus_src

    # Fix audit 2026-05-25 (v1.5.5) Vague K : propagation des champs ffprobe-only
    # restants (hdr_type, color_primaries, dv_profile, profile, level, ...).
    # Tous les enrichissements §5/§6 v7.5.0 + Vague K NFO complet sont
    # passes en clair depuis ff_video. Ne pas ecraser les keys deja merged.
    _already_merged = {
        "codec", "width", "height", "fps", "bit_depth", "pixel_format", "bitrate",
        "hdr_dolby_vision", "hdr10", "hdr10_plus", "_hdr_text_present",
    }
    for k, v in ff_video.items():
        if k in _already_merged:
            continue
        video[k] = v
        video_sources[k] = "ffprobe"

    normalized.video = video

    ff_audio = ff.get("audio_tracks") if isinstance(ff.get("audio_tracks"), list) else []
    mi_audio = mi.get("audio_tracks") if isinstance(mi.get("audio_tracks"), list) else []
    if ff_audio:
        normalized.audio_tracks = ff_audio
        audio_sources = [
            {"index": "ffprobe", "codec": "ffprobe", "channels": "ffprobe", "language": "ffprobe", "bitrate": "ffprobe"}
            for _ in ff_audio
        ]
    elif mi_audio:
        normalized.audio_tracks = mi_audio
        audio_sources = [
            {
                "index": "mediainfo",
                "codec": "mediainfo",
                "channels": "mediainfo",
                "language": "mediainfo",
                "bitrate": "mediainfo",
            }
            for _ in mi_audio
        ]
    else:
        normalized.audio_tracks = []
        audio_sources = []

    ff_sub = ff.get("subtitles") if isinstance(ff.get("subtitles"), list) else []
    mi_sub = mi.get("subtitles") if isinstance(mi.get("subtitles"), list) else []
    if ff_sub:
        normalized.subtitles = ff_sub
        sub_sources = [{"index": "ffprobe", "language": "ffprobe", "forced": "ffprobe"} for _ in ff_sub]
    elif mi_sub:
        normalized.subtitles = mi_sub
        sub_sources = [{"index": "mediainfo", "language": "mediainfo", "forced": "mediainfo"} for _ in mi_sub]
    else:
        normalized.subtitles = []
        sub_sources = []

    normalized.sources = {
        "container": container_src,
        "container_title": container_title_src,
        "duration_s": duration_src,
        "video": video_sources,
        "audio_tracks": audio_sources,
        "subtitles": sub_sources,
    }


def _determine_quality(
    normalized: NormalizedProbe,
    *,
    raw_mediainfo: Optional[Dict[str, Any]],
    raw_ffprobe: Optional[Dict[str, Any]],
    backend: str,
) -> None:
    reasons: List[str] = []
    any_raw = isinstance(raw_mediainfo, dict) or isinstance(raw_ffprobe, dict)
    if not any_raw:
        if any("manquant" in str(m).lower() for m in normalized.messages):
            reasons.append("Analyse partielle: outil manquant.")
            normalized.probe_quality = PROBE_QUALITY_PARTIAL
        else:
            reasons.append("Analyse technique impossible.")
            normalized.probe_quality = PROBE_QUALITY_FAILED
    else:
        if not normalized.video.get("codec"):
            reasons.append("Codec video non detecte.")
        if not normalized.video.get("width") or not normalized.video.get("height"):
            reasons.append("Resolution video incomplete.")
        if normalized.duration_s is None:
            reasons.append("Duree non detectee.")
        if reasons:
            normalized.probe_quality = PROBE_QUALITY_PARTIAL
        else:
            normalized.probe_quality = PROBE_QUALITY_FULL
            reasons.append("Analyse technique complete.")

    if str(backend).strip().lower() == "none":
        normalized.probe_quality = PROBE_QUALITY_FAILED
        reasons = ["Probe desactivee (probe_backend=none)."]

    normalized.probe_quality_reasons = reasons
