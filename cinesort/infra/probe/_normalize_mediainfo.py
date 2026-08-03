"""Extraction MediaInfo (Vague M, M-04 split).

Convertit le JSON MediaInfo brut en dict normalize {container, video, audio_tracks,
subtitles, ...} consomme par _normalize_merge.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from cinesort.infra.probe._normalize_helpers import (
    _bool_from_text,
    _duration_seconds_from_mediainfo,
    _to_bitrate_int,
    _to_float,
    _to_int,
)


def _extract_mediainfo(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    media = raw.get("media")
    if not isinstance(media, dict):
        return {}
    tracks = media.get("track")
    if not isinstance(tracks, list):
        return {}

    general = None
    video = None
    audios: List[Dict[str, Any]] = []
    subs: List[Dict[str, Any]] = []
    for t in tracks:
        if not isinstance(t, dict):
            continue
        t_type = str(t.get("@type") or t.get("Type") or "").strip().lower()
        if t_type == "general" and general is None:
            general = t
        elif t_type == "video" and video is None:
            video = t
        elif t_type == "audio":
            audios.append(t)
        elif t_type in {"text", "subtitle"}:
            subs.append(t)

    out: Dict[str, Any] = {
        "container": None,
        "container_title": None,
        "duration_s": None,
        "video": {},
        "audio_tracks": [],
        "subtitles": [],
    }

    if general:
        out["container"] = str(general.get("Format") or "").strip() or None
        out["duration_s"] = _duration_seconds_from_mediainfo(general.get("Duration"))
        # Titre du conteneur (champ Title ou Movie dans MediaInfo)
        out["container_title"] = str(general.get("Title") or general.get("Movie") or "").strip() or None

    if video:
        video_bitrate_value = video.get("BitRate")
        if not video_bitrate_value and general:
            video_bitrate_value = general.get("OverallBitRate")
        hdr_text = " ".join(
            str(video.get(k) or "")
            for k in (
                "HDR_Format",
                "HDR_Format_String",
                "HDR_Format_Compatibility",
                "HDR_Format_Commercial",
                "HDR_Format_Version",
                "Transfer_Characteristics",
            )
        ).lower()
        out["video"] = {
            "codec": str(video.get("Format") or video.get("CodecID") or "").strip() or None,
            "width": _to_int(video.get("Width")),
            "height": _to_int(video.get("Height")),
            "fps": _to_float(video.get("FrameRate")),
            "bit_depth": _to_int(video.get("BitDepth")),
            "pixel_format": str(video.get("ChromaSubsampling") or video.get("ColorSpace") or "").strip() or None,
            "bitrate": _to_bitrate_int(video_bitrate_value),
            "hdr_dolby_vision": ("dolby vision" in hdr_text) or ("dovi" in hdr_text),
            "hdr10": ("hdr10" in hdr_text) or ("smpte st 2084" in hdr_text) or ("pq" in hdr_text),
            "hdr10_plus": "hdr10+" in hdr_text,
            "_hdr_text_present": bool(hdr_text.strip()),
        }

    for idx, a in enumerate(audios):
        _mi_title = str(a.get("Title") or "").strip()
        _mi_commentary = "commentary" in _mi_title.lower() or "commentaire" in _mi_title.lower()
        out["audio_tracks"].append(
            {
                "index": idx,
                "codec": str(a.get("Format") or a.get("CodecID") or "").strip() or None,
                "channels": _to_int(a.get("Channel(s)")) or _to_int(a.get("Channels")),
                "language": str(a.get("Language_String3") or a.get("Language") or "").strip() or None,
                "bitrate": _to_bitrate_int(a.get("BitRate")),
                "title": _mi_title,
                "is_commentary": _mi_commentary,
            }
        )

    for idx, s in enumerate(subs):
        forced_v = _bool_from_text(s.get("Forced"))
        out["subtitles"].append(
            {
                "index": idx,
                "language": str(s.get("Language_String3") or s.get("Language") or "").strip() or None,
                "forced": bool(forced_v) if forced_v is not None else False,
            }
        )

    return out
