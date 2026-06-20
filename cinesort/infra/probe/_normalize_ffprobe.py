"""Extraction ffprobe (Vague M, M-04 split).

Convertit le JSON ffprobe brut en dict normalize {container, video, audio_tracks,
subtitles, chapters, ...} consomme par _normalize_merge. Inclut la classification
HDR/DV via cinesort.domain.perceptual.hdr_analysis (§5/§6 v7.5.0) et la detection
Atmos / DTS:X audio (Vague K).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from cinesort.domain.perceptual.hdr_analysis import (
    analyze_dv_from_frame_data,
    analyze_hdr_from_frame_data,
)
from cinesort.infra.probe._normalize_helpers import (
    _bool_from_text,
    _extract_bit_depth,
    _ratio_to_fps,
    _to_bitrate_int,
    _to_float,
    _to_int,
)


def _detect_atmos_dtsx(codec_name: str, profile: str, title: str, tags: Dict[str, Any]) -> Tuple[bool, bool]:
    """Detecte les containers immersifs (Atmos / DTS:X).

    - Atmos : flux TrueHD ou E-AC3 avec "Atmos" dans le titre/tags, ou profile JOC.
    - DTS:X : flux DTS / DTS-HD avec "DTS:X" ou "DTS X" ou "IMAX Enhanced" dans le titre.
    """
    codec = (codec_name or "").lower()
    prof = (profile or "").lower()
    title_l = (title or "").lower()
    # Tags MKV : peuvent contenir JOC, MOBJECT, etc.
    tags_blob = " ".join(str(v) for v in (tags or {}).values()).lower()

    is_atmos = False
    if codec in {"truehd", "eac3", "ac3"}:
        if "atmos" in title_l or "atmos" in tags_blob or "atmos" in prof:
            is_atmos = True
        elif "joc" in prof or "joc" in tags_blob:
            # JOC = Joint Object Coding (Atmos on E-AC3)
            is_atmos = True

    is_dts_x = False
    if codec in {"dts", "dts-hd"} or "dts" in codec:
        if "dts:x" in title_l or "dts x" in title_l or "dtsx" in title_l:
            is_dts_x = True
        elif "imax enhanced" in title_l or "imax" in tags_blob:
            is_dts_x = True

    return is_atmos, is_dts_x


def _ffprobe_video_dict(
    video_stream: Dict[str, Any],
    fmt: Dict[str, Any],
    first_frame: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    tags = video_stream.get("tags") if isinstance(video_stream.get("tags"), dict) else {}
    side_data = video_stream.get("side_data_list") if isinstance(video_stream.get("side_data_list"), list) else []
    hdr_text = " ".join(
        [
            str(video_stream.get("color_transfer") or ""),
            str(video_stream.get("color_space") or ""),
            str(video_stream.get("color_primaries") or ""),
            str(tags.get("HDR_Format") or ""),
            str(tags.get("DOVI") or ""),
            " ".join(str(it) for it in side_data),
        ]
    ).lower()

    # Fix audit 2026-05-25 (v1.5.5) Vague K : extraction bit_depth robuste
    bit_depth = _extract_bit_depth(
        str(video_stream.get("pix_fmt") or ""),
        video_stream.get("bits_per_raw_sample"),
    )

    # §5 v7.5.0 : HDR metadata classification + validation (Pass 1)
    # §6 v7.5.0 : Dolby Vision profile classification (meme side_data_list)
    hdr_info = analyze_hdr_from_frame_data(video_stream, first_frame)
    dv_info = analyze_dv_from_frame_data(video_stream, first_frame)

    return {
        "codec": str(video_stream.get("codec_name") or "").strip() or None,
        "width": _to_int(video_stream.get("width")),
        "height": _to_int(video_stream.get("height")),
        "fps": _ratio_to_fps(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")),
        "bit_depth": bit_depth,
        "pixel_format": str(video_stream.get("pix_fmt") or "").strip() or None,
        "bitrate": _to_bitrate_int(video_stream.get("bit_rate") or fmt.get("bit_rate")),
        # Champs historiques (booleens) preserves pour retro-compat
        "hdr_dolby_vision": ("dolby vision" in hdr_text) or ("dovi" in hdr_text),
        "hdr10": ("hdr10" in hdr_text) or ("smpte2084" in hdr_text) or ("mastering display metadata" in hdr_text),
        "hdr10_plus": ("hdr10+" in hdr_text) or ("dynamic_hdr_plus" in hdr_text),
        "_hdr_text_present": bool(hdr_text.strip()),
        # §5 v7.5.0 : enrichissement HDR structure
        "color_primaries": hdr_info.color_primaries,
        "color_transfer": hdr_info.color_transfer,
        "color_space": hdr_info.color_space,
        "hdr_type": hdr_info.hdr_type,
        "max_cll": hdr_info.max_cll,
        "max_fall": hdr_info.max_fall,
        "min_luminance": hdr_info.min_luminance,
        "max_luminance": hdr_info.max_luminance,
        "hdr_is_valid": hdr_info.is_valid,
        "hdr_validation_flag": hdr_info.validation_flag,
        "hdr_quality_score": hdr_info.quality_score,
        # §6 v7.5.0 : enrichissement Dolby Vision
        "dv_present": dv_info.present,
        "dv_profile": dv_info.profile,
        "dv_compatibility": dv_info.compatibility,
        "dv_el_present": dv_info.el_present,
        "dv_rpu_present": dv_info.rpu_present,
        "dv_warning": dv_info.warning,
        "dv_quality_score": dv_info.quality_score,
        # Fix audit 2026-05-25 (v1.5.5) Vague K : "NFO complet" — champs additionnels
        "profile": str(video_stream.get("profile") or "").strip() or None,
        "level": _to_int(video_stream.get("level")),
        "display_aspect_ratio": str(video_stream.get("display_aspect_ratio") or "").strip() or None,
        "sample_aspect_ratio": str(video_stream.get("sample_aspect_ratio") or "").strip() or None,
        "color_range": str(video_stream.get("color_range") or "").strip() or None,
        "chroma_location": str(video_stream.get("chroma_location") or "").strip() or None,
        "r_frame_rate": _ratio_to_fps(video_stream.get("r_frame_rate")),
        "language": str(tags.get("language") or tags.get("LANGUAGE") or "").strip() or None,
        "title": str(tags.get("title") or tags.get("TITLE") or "").strip() or None,
    }


def _extract_ffprobe(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    streams = raw.get("streams")
    if not isinstance(streams, list):
        streams = []
    fmt = raw.get("format")
    if not isinstance(fmt, dict):
        fmt = {}
    # §5 v7.5.0 : frames[0] est fourni par -show_frames -read_intervals "%+#1"
    # Contient les side_data_list HDR (mastering display, HDR10+, DV).
    frames = raw.get("frames") if isinstance(raw.get("frames"), list) else []
    first_frame = frames[0] if frames and isinstance(frames[0], dict) else None

    video_stream = None
    audio_streams: List[Dict[str, Any]] = []
    sub_streams: List[Dict[str, Any]] = []
    for s in streams:
        if not isinstance(s, dict):
            continue
        typ = str(s.get("codec_type") or "").strip().lower()
        if typ == "video" and video_stream is None:
            video_stream = s
        elif typ == "audio":
            audio_streams.append(s)
        elif typ == "subtitle":
            sub_streams.append(s)

    container = None
    fmt_name = str(fmt.get("format_name") or "").strip()
    if fmt_name:
        container = fmt_name.split(",", 1)[0].strip() or None

    # Titre du conteneur (format.tags.title dans ffprobe)
    fmt_tags = fmt.get("tags") if isinstance(fmt.get("tags"), dict) else {}
    container_title = str(fmt_tags.get("title") or "").strip() or None

    # Fix audit 2026-05-25 (v1.5.5) Vague K : enrichissement container "NFO complet"
    container_size_bytes = _to_int(fmt.get("size"))
    container_bit_rate = _to_bitrate_int(fmt.get("bit_rate"))
    container_encoder = (
        str(fmt_tags.get("encoder") or fmt_tags.get("ENCODER") or fmt_tags.get("writing_application") or "").strip()
        or None
    )
    container_creation_time = (
        str(fmt_tags.get("creation_time") or fmt_tags.get("CREATION_TIME") or "").strip() or None
    )

    out: Dict[str, Any] = {
        "container": container,
        "container_title": container_title,
        "duration_s": _to_float(fmt.get("duration")),
        "video": {},
        "audio_tracks": [],
        "subtitles": [],
        # Fix audit 2026-05-25 (v1.5.5) Vague K : champs container additionnels
        "container_format_long": fmt_name or None,
        "container_size_bytes": container_size_bytes,
        "container_bit_rate": container_bit_rate,
        "container_encoder": container_encoder,
        "container_creation_time": container_creation_time,
        "chapters": [],
    }

    if video_stream:
        out["video"] = _ffprobe_video_dict(video_stream, fmt, first_frame)

    for s in audio_streams:
        tags = s.get("tags") if isinstance(s.get("tags"), dict) else {}
        disp_a = s.get("disposition") if isinstance(s.get("disposition"), dict) else {}
        _ff_title = str(tags.get("title") or "").strip()
        _ff_commentary = (
            bool(disp_a.get("comment")) or "commentary" in _ff_title.lower() or "commentaire" in _ff_title.lower()
        )
        # Fix audit 2026-05-25 (v1.5.5) Vague K : enrichissement audio "NFO complet"
        codec_name = str(s.get("codec_name") or "").strip() or None
        profile = str(s.get("profile") or "").strip() or None
        is_atmos, is_dts_x = _detect_atmos_dtsx(codec_name or "", profile or "", _ff_title, tags)
        out["audio_tracks"].append(
            {
                "index": _to_int(s.get("index")),
                "codec": codec_name,
                "channels": _to_int(s.get("channels")),
                "language": str(tags.get("language") or "").strip() or None,
                "bitrate": _to_bitrate_int(s.get("bit_rate")),
                "title": _ff_title,
                "is_commentary": _ff_commentary,
                # Champs additionnels
                "profile": profile,
                "channel_layout": str(s.get("channel_layout") or "").strip() or None,
                "sample_rate": _to_int(s.get("sample_rate")),
                "bit_depth": _to_int(s.get("bits_per_raw_sample") or s.get("bits_per_sample")),
                "is_default": bool(int(disp_a.get("default") or 0)),
                "is_forced": bool(int(disp_a.get("forced") or 0)),
                "is_atmos": is_atmos,
                "is_dts_x": is_dts_x,
            }
        )

    for s in sub_streams:
        tags = s.get("tags") if isinstance(s.get("tags"), dict) else {}
        disp = s.get("disposition") if isinstance(s.get("disposition"), dict) else {}
        forced_tag = _bool_from_text(tags.get("forced"))
        forced_disp = bool(int(disp.get("forced") or 0))
        out["subtitles"].append(
            {
                "index": _to_int(s.get("index")),
                "language": str(tags.get("language") or "").strip() or None,
                "forced": bool(forced_tag) if forced_tag is not None else forced_disp,
                # Fix audit 2026-05-25 (v1.5.5) Vague K : enrichissement sub "NFO complet"
                "codec": str(s.get("codec_name") or "").strip() or None,
                "title": str(tags.get("title") or "").strip() or None,
                "is_default": bool(int(disp.get("default") or 0)),
                "is_hearing_impaired": bool(int(disp.get("hearing_impaired") or 0)),
            }
        )

    # Fix audit 2026-05-25 (v1.5.5) Vague K : extraction chapitres
    raw_chapters = raw.get("chapters") if isinstance(raw.get("chapters"), list) else []
    for ch in raw_chapters:
        if not isinstance(ch, dict):
            continue
        ch_tags = ch.get("tags") if isinstance(ch.get("tags"), dict) else {}
        out["chapters"].append(
            {
                "id": _to_int(ch.get("id")),
                "start_time": _to_float(ch.get("start_time")),
                "end_time": _to_float(ch.get("end_time")),
                "title": str(ch_tags.get("title") or "").strip() or None,
            }
        )

    return out
