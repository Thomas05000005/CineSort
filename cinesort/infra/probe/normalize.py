from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cinesort.domain.perceptual.hdr_analysis import (
    analyze_dv_from_frame_data,
    analyze_hdr_from_frame_data,
)
from cinesort.domain.probe_models import (
    PROBE_QUALITY_FAILED,
    PROBE_QUALITY_FULL,
    PROBE_QUALITY_PARTIAL,
    NormalizedProbe,
)

# Pre-compiled regex patterns for _to_int number parsing (used in hot loops).
_GROUPED_NUMBER_RE = re.compile(r"(\d{1,3}(?:[ \t,\.]\d{3})+)")
_GROUP_SEP_RE = re.compile(r"[ \t,\.]")
_FIRST_DIGITS_RE = re.compile(r"\d+")


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        try:
            return int(round(value))
        except (TypeError, ValueError):
            return None
    s = str(value)
    s_clean = s.replace("\u00a0", " ").strip()
    if not s_clean:
        return None
    # Grouped numbers like "3 840", "12,500,000", "12.500.000".
    grouped = _GROUPED_NUMBER_RE.search(s_clean)
    if grouped:
        try:
            joined = _GROUP_SEP_RE.sub("", grouped.group(1))
            return int(joined)
        except (TypeError, ValueError):
            pass
    m = _FIRST_DIGITS_RE.search(s_clean)
    if not m:
        return None
    try:
        return int(m.group(0))
    except (TypeError, ValueError):
        return None


def _to_bitrate_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    s = str(value or "").strip().lower().replace("\u00a0", " ")
    if not s:
        return None
    unit_m = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*(gb/s|gbit/s|gib/s|mb/s|mbit/s|mib/s|kb/s|kbit/s|kib/s)", s)
    if unit_m:
        num_txt = unit_m.group(1).replace(",", ".")
        try:
            base = float(num_txt)
        except (TypeError, ValueError):
            base = 0.0
        unit = unit_m.group(2)
        if unit.startswith("gb") or unit.startswith("gi"):
            return int(round(base * 1_000_000_000))
        if unit.startswith("mb") or unit.startswith("mi"):
            return int(round(base * 1_000_000))
        return int(round(base * 1_000))
    return _to_int(s)


def _ratio_to_fps(value: Any) -> Optional[float]:
    s = str(value or "").strip()
    if not s:
        return None
    if "/" in s:
        try:
            n, d = s.split("/", 1)
            n_f = float(n)
            d_f = float(d)
            if d_f == 0:
                return None
            return round(n_f / d_f, 3)
        except (TypeError, ValueError):
            return None
    return _to_float(s)


def _duration_seconds_from_mediainfo(value: Any) -> Optional[float]:
    v = _to_float(value)
    if v is None:
        return None
    # MediaInfo JSON peut renvoyer des ms selon formats.
    if v > 100000.0:
        return round(v / 1000.0, 3)
    return round(v, 3)


def _bool_from_text(value: Any) -> Optional[bool]:
    s = str(value or "").strip().lower()
    if not s:
        return None
    if s in {"1", "true", "yes", "oui"}:
        return True
    if s in {"0", "false", "no", "non"}:
        return False
    return None


def _pick_value(
    *,
    ffprobe_value: Any,
    mediainfo_value: Any,
    prefer_ffprobe: bool = True,
) -> Tuple[Any, str]:
    def _has(v: Any) -> bool:
        if v is None:
            return False
        if isinstance(v, str):
            return bool(v.strip())
        if isinstance(v, (list, dict, tuple, set)):
            return len(v) > 0
        return True

    ff_has = _has(ffprobe_value)
    mi_has = _has(mediainfo_value)
    if prefer_ffprobe:
        if ff_has:
            return ffprobe_value, "ffprobe"
        if mi_has:
            return mediainfo_value, "mediainfo"
    else:
        if mi_has:
            return mediainfo_value, "mediainfo"
        if ff_has:
            return ffprobe_value, "ffprobe"
    return None, "none"


def _merge_flag(mi: bool, ff: bool, mi_has: bool, ff_has: bool) -> Tuple[bool, str]:
    value = bool(mi or ff)
    if mi and ff:
        return value, "mediainfo+ffprobe"
    if ff:
        return value, "ffprobe"
    if mi:
        return value, "mediainfo"
    if ff_has:
        return value, "ffprobe"
    if mi_has:
        return value, "mediainfo"
    return value, "none"


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


# Fix audit 2026-05-25 (v1.5.5) Vague K : extraction bit_depth robuste depuis pix_fmt
def _extract_bit_depth(pix_fmt: str, bits_per_raw_sample: Any) -> Optional[int]:
    """Retourne la profondeur de bits du flux video.

    Prefere `bits_per_raw_sample` (champ explicite ffprobe). Sinon parse le
    `pix_fmt` (yuv420p10le -> 10, yuv420p12le -> 12, yuv420p -> 8).
    """
    explicit = _to_int(bits_per_raw_sample)
    if explicit and explicit > 0:
        return explicit
    pf = str(pix_fmt or "").lower()
    if not pf:
        return None
    # Patterns ffmpeg : p10/p12/p16 (planar) ou 10le/12le/16le
    for depth in (16, 12, 10):
        if f"p{depth}" in pf or f"{depth}le" in pf or f"{depth}be" in pf:
            return depth
    # Fallback : tout pix_fmt yuv/rgb sans suffixe = 8 bits
    if "yuv" in pf or "rgb" in pf or "gray" in pf or "nv" in pf:
        return 8
    return None


# Fix audit 2026-05-25 (v1.5.5) Vague K : detection Atmos / DTS:X
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


def normalize_probe(
    *,
    media_path: Path,
    raw_mediainfo: Optional[Dict[str, Any]],
    raw_ffprobe: Optional[Dict[str, Any]],
    backend: str,
    messages: List[str],
) -> NormalizedProbe:
    mi, ff = _extract_tracks(raw_mediainfo, raw_ffprobe)

    normalized = NormalizedProbe(path=str(media_path))
    normalized.messages = list(messages or [])

    _merge_probes(mi, ff, normalized)
    _determine_quality(normalized, raw_mediainfo=raw_mediainfo, raw_ffprobe=raw_ffprobe, backend=backend)

    return normalized
