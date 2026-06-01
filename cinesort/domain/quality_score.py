from __future__ import annotations

import copy
import logging
import re
# Fix audit 2026-05-26 (v1.5.7) hotfix dataclass : import top-level
# pour permettre aux helpers (_estimate_file_size, _build_invalid_profile_result,
# _apply_custom_rules_helper, _build_quality_metrics_helper, _merge_probe_with_name_hints)
# d'accepter aussi un NormalizedProbe @dataclass passe directement. Le mutation
# testing patche dataclasses.is_dataclass -> les tests cassent (preuve).
from dataclasses import asdict as _asdict, is_dataclass as _is_dc
from typing import Any, Dict, List, Optional, Tuple

from cinesort.domain.conversions import to_bool as _to_bool, to_float as _to_float, to_int as _to_int
from cinesort.domain.custom_rules import apply_custom_rules as _apply_rules
from cinesort.domain.explain_score import build_rich_explanation
from cinesort.domain.genre_rules import (
    adjust_bitrate_threshold as _adj_th,
    compute_genre_adjustments,
    detect_primary_genre as _detect_pg,
)
# Fix audit 2026-05-25 (v1.5.5) Vague K : parser nom de release pour fallback
# quand le probe est PARTIAL/FAILED (ex: SMB obsolete, fichier corrompu).
from cinesort.domain.release_name_parser import ReleaseNameInfo, parse_release_name
# SCORE-02 (Vague M, M-06) : helpers tiers centralises (dedup retro-compat
# legacy premium/bon/moyen -> platinum/gold/silver). Pure delegation sans
# changement de comportement attendu sur les tiers.
from cinesort.domain.tiers_helpers import normalize_tiers as _normalize_tiers_central

logger = logging.getLogger(__name__)


DEFAULT_PROFILE_ID = "CinemaLux_v1"
DEFAULT_PROFILE_VERSION = 1
QUALITY_PRESET_REMUX_STRICT = "remux_strict"
QUALITY_PRESET_EQUILIBRE = "equilibre"
QUALITY_PRESET_LIGHT = "light"
# Spec 11 §2.9 (Phase 4 backend-parametres-endpoints) :
# 2 nouveaux presets pour completer le catalogue (streaming + compact)
# en miroir des 2 existants (remux_strict + equilibre/CinemaLux).
QUALITY_PRESET_STREAMING_OPTIMAL = "streaming_optimal"
QUALITY_PRESET_COMPACT = "compact"


def default_quality_profile() -> Dict[str, Any]:
    return {
        "id": DEFAULT_PROFILE_ID,
        "version": DEFAULT_PROFILE_VERSION,
        "engine_version": "CinemaLux_v1",
        "weights": {
            "video": 60,
            "audio": 30,
            "extras": 10,
        },
        "toggles": {
            "include_metadata": False,
            "include_naming": False,
            "enable_4k_light": True,
            # VN-F.2 : toggle ajoute explicitement aux profils 2026-06-01.
            # Active la branche subtitle scoring (_score_extras) qui restait
            # inatteignable. Defaut False pour preserver les scores existants ;
            # un profil utilisateur (custom) peut le passer a True pour
            # activer le bonus/penalty langues sous-titres.
            "include_subtitles": False,
        },
        "video_thresholds": {
            "bitrate_min_kbps_2160p": 18000,
            "bitrate_min_kbps_1080p": 8000,
            "penalty_low_bitrate": 14,
            "penalty_4k_light": 7,
            "penalty_hdr_8bit": 8,
        },
        "hdr_bonuses": {
            "dv_bonus": 12,
            "hdr10p_bonus": 10,
            "hdr10_bonus": 8,
        },
        "codec_bonuses": {
            "hevc_bonus": 8,
            "av1_bonus": 9,
            "avc_bonus": 5,
        },
        "audio_bonuses": {
            "truehd_atmos_bonus": 12,
            "dts_hd_ma_bonus": 10,
            "dts_bonus": 6,
            "aac_bonus": 3,
            "channels_bonus_map": {
                "2.0": 2,
                "5.1": 6,
                "7.1": 8,
            },
        },
        "languages": {
            "bonus_vo_present": 4,
            "bonus_vf_present": 2,
        },
        "tiers": {
            # Nouveaux noms (v7.2.0-dev, audit AUDIT_20260422 U1).
            # Anciens alias acceptes pour retro-compat lecture :
            #   Premium->Platinum, Bon->Gold, Moyen->Silver, Faible->Bronze/Reject.
            # Fix audit 2026-05-25 (v1.5.5) Vague J : recalibrage des seuils.
            # Avant : 85/68/54/30 -> sur une bibliotheque reelle (853 films),
            # la moyenne ponderee tournait autour de 22-40 (probe partielle,
            # bitrates 5-8 Mbps frequents, 1080p AVC majoritaire), ce qui
            # placait 100% des films en Reject (< 30). Les nouveaux seuils
            # sont calibres pour une distribution realiste :
            #   Platinum 75+ : UHD HDR Remux haut debit
            #   Gold 56+     : 1080p BluRay propre ou UHD light
            #   Silver 42+   : 1080p web/DVD HD standard
            #   Bronze 25+   : 720p, encodes leger, probe partielle
            #   Reject < 25  : echec probe ou tres faible qualite reelle
            # Fix audit 2026-05-26 (v1.5.6) Vague L (scoring-5) : Gold 58 -> 56.
            # Sur un panel reel, ~80% des 1080p HEVC HDR propres (10 Mbps + DTS-HD MA)
            # stagnent en Silver a 55 alors qu'ils meritent Gold (HEVC + HDR + audio
            # lossless multicanal). Abaisser Gold de 2 points (au lieu de gonfler
            # massivement les bonus video/audio qui debalancerait le UHD) permet
            # a ces 1080p qualitatifs d'atteindre Gold. Combinée avec le bump de
            # base audio (10 -> 12, voir _score_audio).
            # Fix audit 2026-05-30 (v1.5.7) calibration biblio reelle : sur la
            # distribution observee 853 films (run 20260530_144631_443) -
            # 20-29:1, 30-39:69, 40-49:181, 50-59:321 (peak), 60-69:277, 70-79:4 -
            # les seuils 75/56/42/25 placaient 100% des films en Silver+Bronze
            # (aucun Platinum car max=79, et Bronze 25 trop genereux : 100% > 25).
            # Recalibrage cible decision senior (distribution observee) :
            #   Platinum 70+ : 0.5% (4 films exceptionnels)
            #   Gold     66+ : ~13% (UHD light ou 1080p HDR premium)
            #   Silver   55+ : ~38% (peak, BluRay 1080p propre)
            #   Bronze   40+ : ~40% (1080p web/encodes legers)
            #   Reject  <40  : ~8% (probe FAILED, qualite tres faible)
            "platinum": 70,
            "gold": 66,
            "silver": 55,
            "bronze": 40,
        },
    }


def _build_quality_presets_catalog() -> Dict[str, Dict[str, Any]]:
    base = default_quality_profile()

    remux_strict = copy.deepcopy(base)
    remux_strict["id"] = "CinemaLux_RemuxStrict_v1"
    remux_strict["weights"].update({"video": 66, "audio": 30, "extras": 4})
    remux_strict["toggles"].update({"enable_4k_light": False, "include_metadata": False, "include_naming": False})
    remux_strict["video_thresholds"].update(
        {
            "bitrate_min_kbps_2160p": 26000,
            "bitrate_min_kbps_1080p": 10500,
            "penalty_low_bitrate": 18,
            "penalty_4k_light": 14,
            "penalty_hdr_8bit": 10,
        }
    )
    remux_strict["hdr_bonuses"].update({"dv_bonus": 13, "hdr10p_bonus": 11, "hdr10_bonus": 9})
    remux_strict["codec_bonuses"].update({"hevc_bonus": 10, "av1_bonus": 11, "avc_bonus": 4})
    remux_strict["audio_bonuses"].update(
        {
            "truehd_atmos_bonus": 14,
            "dts_hd_ma_bonus": 12,
            "dts_bonus": 5,
            "aac_bonus": 1,
            "channels_bonus_map": {"2.0": 1, "5.1": 7, "7.1": 10},
        }
    )
    remux_strict["languages"].update({"bonus_vo_present": 3, "bonus_vf_present": 1})
    remux_strict["tiers"].update({"premium": 90, "bon": 76, "moyen": 60})

    equilibre = copy.deepcopy(base)
    equilibre["id"] = "CinemaLux_Equilibre_v1"
    equilibre["weights"].update({"video": 60, "audio": 30, "extras": 10})
    equilibre["toggles"].update({"enable_4k_light": True, "include_metadata": False, "include_naming": False})
    # Fix audit 2026-05-25 (v1.5.5) Vague J : equilibre suit le default recalibre.
    # Fix audit 2026-05-30 (v1.5.7) calibration biblio reelle : aligne sur default.
    equilibre["tiers"].update({"platinum": 70, "gold": 66, "silver": 55, "bronze": 40})

    light = copy.deepcopy(base)
    light["id"] = "CinemaLux_Light_v1"
    light["weights"].update({"video": 52, "audio": 30, "extras": 18})
    light["toggles"].update({"enable_4k_light": True, "include_metadata": True, "include_naming": True})
    light["video_thresholds"].update(
        {
            "bitrate_min_kbps_2160p": 12000,
            "bitrate_min_kbps_1080p": 5200,
            "penalty_low_bitrate": 8,
            "penalty_4k_light": 4,
            "penalty_hdr_8bit": 5,
        }
    )
    light["hdr_bonuses"].update({"dv_bonus": 10, "hdr10p_bonus": 8, "hdr10_bonus": 6})
    light["codec_bonuses"].update({"hevc_bonus": 7, "av1_bonus": 8, "avc_bonus": 6})
    light["audio_bonuses"].update(
        {
            "truehd_atmos_bonus": 10,
            "dts_hd_ma_bonus": 8,
            "dts_bonus": 5,
            "aac_bonus": 4,
            "channels_bonus_map": {"2.0": 2, "5.1": 5, "7.1": 7},
        }
    )
    light["languages"].update({"bonus_vo_present": 5, "bonus_vf_present": 3})
    # Fix audit 2026-05-30 (v1.5.8) align CinemaLux_Light_v1 sur calibration biblio reelle :
    # Avant : premium=80, bon=64, moyen=50 (legacy) -> normalisation produisait Platinum 85
    # ce qui placait 0 film en Platinum sur la distribution observee (max=79).
    # Apres : aligne sur les seuils default recalibres 70/66/55/40.
    light["tiers"].update({"platinum": 70, "gold": 66, "silver": 55, "bronze": 40})

    # Streaming optimal : profil pour bibliotheques destinees au streaming
    # (Plex/Jellyfin). Tolerant sur l'audio (peu de pertes a 5.1), severe sur
    # le debit video (les players de salon n'apprecient pas le low bitrate).
    streaming_optimal = copy.deepcopy(base)
    streaming_optimal["id"] = "StreamingOptimal_v1"
    streaming_optimal["weights"].update({"video": 55, "audio": 25, "extras": 20})
    streaming_optimal["toggles"].update({"enable_4k_light": True, "include_metadata": True, "include_naming": True})
    streaming_optimal["video_thresholds"].update(
        {
            "bitrate_min_kbps_2160p": 15000,
            "bitrate_min_kbps_1080p": 6500,
            "penalty_low_bitrate": 12,
            "penalty_4k_light": 6,
            "penalty_hdr_8bit": 7,
        }
    )
    streaming_optimal["codec_bonuses"].update({"hevc_bonus": 10, "av1_bonus": 12, "avc_bonus": 4})
    streaming_optimal["audio_bonuses"].update(
        {
            "truehd_atmos_bonus": 10,
            "dts_hd_ma_bonus": 9,
            "dts_bonus": 6,
            "aac_bonus": 5,
            "channels_bonus_map": {"2.0": 3, "5.1": 7, "7.1": 8},
        }
    )
    streaming_optimal["languages"].update({"bonus_vo_present": 5, "bonus_vf_present": 4})
    streaming_optimal["tiers"].update({"platinum": 82, "gold": 66, "silver": 52, "bronze": 32})

    # Compact : profil pour bibliotheques portables (NAS petite capacite,
    # serveur ARM). Accepte H.264/HEVC compact 5-6 GB pour 1080p, valorise
    # AV1, peu severe sur les bitrate bas.
    compact = copy.deepcopy(base)
    compact["id"] = "Compact_v1"
    compact["weights"].update({"video": 50, "audio": 30, "extras": 20})
    compact["toggles"].update({"enable_4k_light": True, "include_metadata": True, "include_naming": True})
    compact["video_thresholds"].update(
        {
            "bitrate_min_kbps_2160p": 10000,
            "bitrate_min_kbps_1080p": 4200,
            "penalty_low_bitrate": 6,
            "penalty_4k_light": 3,
            "penalty_hdr_8bit": 4,
        }
    )
    compact["codec_bonuses"].update({"hevc_bonus": 9, "av1_bonus": 12, "avc_bonus": 5})
    compact["audio_bonuses"].update(
        {
            "truehd_atmos_bonus": 8,
            "dts_hd_ma_bonus": 7,
            "dts_bonus": 5,
            "aac_bonus": 5,
            "channels_bonus_map": {"2.0": 3, "5.1": 5, "7.1": 6},
        }
    )
    compact["languages"].update({"bonus_vo_present": 5, "bonus_vf_present": 4})
    compact["tiers"].update({"platinum": 78, "gold": 60, "silver": 46, "bronze": 28})

    return {
        QUALITY_PRESET_REMUX_STRICT: {
            "preset_id": QUALITY_PRESET_REMUX_STRICT,
            "label": "Remux strict",
            "description": "Exigeant sur le debit et les formats premium, ideal home-cinema.",
            "profile_json": remux_strict,
        },
        QUALITY_PRESET_EQUILIBRE: {
            "preset_id": QUALITY_PRESET_EQUILIBRE,
            "label": "CinemaLux (equilibre)",
            "description": "Profil par defaut recommande pour un usage mixte sans biais remux ou light.",
            "profile_json": equilibre,
        },
        QUALITY_PRESET_LIGHT: {
            "preset_id": QUALITY_PRESET_LIGHT,
            "label": "Light",
            "description": "Tolerance plus large pour encodes compacts et bibliotheques heterogenes.",
            "profile_json": light,
        },
        QUALITY_PRESET_STREAMING_OPTIMAL: {
            "preset_id": QUALITY_PRESET_STREAMING_OPTIMAL,
            "label": "Streaming optimal",
            "description": "Optimise pour Plex/Jellyfin : bonus codec moderne, audio 5.1 valorise.",
            "profile_json": streaming_optimal,
        },
        QUALITY_PRESET_COMPACT: {
            "preset_id": QUALITY_PRESET_COMPACT,
            "label": "Compact",
            "description": "Bibliotheques portables : tolerant aux faibles bitrates, valorise AV1/HEVC.",
            "profile_json": compact,
        },
    }


_PRESETS_CATALOG: Optional[Dict[str, Dict[str, Any]]] = None


def _get_presets_catalog() -> Dict[str, Dict[str, Any]]:
    global _PRESETS_CATALOG
    if _PRESETS_CATALOG is None:
        _PRESETS_CATALOG = _build_quality_presets_catalog()
    return _PRESETS_CATALOG


def list_quality_presets(*, include_profiles: bool = False) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    catalog = _get_presets_catalog()
    for preset_id in (
        QUALITY_PRESET_REMUX_STRICT,
        QUALITY_PRESET_EQUILIBRE,
        QUALITY_PRESET_LIGHT,
        QUALITY_PRESET_STREAMING_OPTIMAL,
        QUALITY_PRESET_COMPACT,
    ):
        item = catalog[preset_id]
        profile_json = copy.deepcopy(item["profile_json"])
        row: Dict[str, Any] = {
            "preset_id": preset_id,
            "label": str(item["label"]),
            "description": str(item["description"]),
            "profile_id": str(profile_json.get("id") or ""),
            "profile_version": int(profile_json.get("version") or 1),
        }
        if include_profiles:
            row["profile_json"] = profile_json
        out.append(row)
    return out


def quality_profile_from_preset(preset_id: Any) -> Optional[Dict[str, Any]]:
    wanted = str(preset_id or "").strip().lower()
    if not wanted:
        return None
    for row in list_quality_presets(include_profiles=True):
        if str(row.get("preset_id") or "") == wanted:
            profile = row.get("profile_json")
            if isinstance(profile, dict):
                return copy.deepcopy(profile)
    return None


# _to_int, _to_float, _to_bool imported from cinesort.domain.conversions


def validate_quality_profile(raw_profile: Any) -> Tuple[bool, List[str], Dict[str, Any]]:
    errs: List[str] = []
    base = default_quality_profile()
    if not isinstance(raw_profile, dict):
        return False, ["Profil invalide: format JSON attendu (objet)."], base

    profile = copy.deepcopy(base)
    for key in ("id", "version", "engine_version"):
        if key in raw_profile:
            profile[key] = raw_profile[key]

    for section in (
        "weights",
        "toggles",
        "video_thresholds",
        "hdr_bonuses",
        "codec_bonuses",
        "audio_bonuses",
        "languages",
        "tiers",
    ):
        src = raw_profile.get(section)
        if isinstance(src, dict):
            profile[section].update(src)

    profile["id"] = str(profile.get("id") or DEFAULT_PROFILE_ID).strip() or DEFAULT_PROFILE_ID
    profile["version"] = max(1, _to_int(profile.get("version"), DEFAULT_PROFILE_VERSION))
    profile["engine_version"] = str(profile.get("engine_version") or "CinemaLux_v1").strip() or "CinemaLux_v1"

    weights = profile["weights"]
    for key in ("video", "audio", "extras"):
        weights[key] = max(0, _to_int(weights.get(key), base["weights"][key]))
    if (weights["video"] + weights["audio"] + weights["extras"]) <= 0:
        errs.append("Poids invalides: au moins un poids doit etre > 0.")

    toggles = profile["toggles"]
    toggles["include_metadata"] = _to_bool(toggles.get("include_metadata"), False)
    toggles["include_naming"] = _to_bool(toggles.get("include_naming"), False)
    toggles["enable_4k_light"] = _to_bool(toggles.get("enable_4k_light"), True)
    # VN-F.2 : include_subtitles ajoute aux profils 2026-06-01 (defaut False
    # pour preserver les scores existants ; activable via profil custom).
    toggles["include_subtitles"] = _to_bool(toggles.get("include_subtitles"), False)

    vt = profile["video_thresholds"]
    for key in ("bitrate_min_kbps_2160p", "bitrate_min_kbps_1080p"):
        vt[key] = max(500, _to_int(vt.get(key), base["video_thresholds"][key]))
    for key in ("penalty_low_bitrate", "penalty_4k_light", "penalty_hdr_8bit"):
        vt[key] = max(0, _to_int(vt.get(key), base["video_thresholds"][key]))

    for section in ("hdr_bonuses", "codec_bonuses", "languages"):
        sec = profile[section]
        for k, v in list(sec.items()):
            sec[k] = max(0, _to_int(v, base[section].get(k, 0)))

    ab = profile["audio_bonuses"]
    for key in ("truehd_atmos_bonus", "dts_hd_ma_bonus", "dts_bonus", "aac_bonus"):
        ab[key] = max(0, _to_int(ab.get(key), base["audio_bonuses"][key]))
    channels_raw = ab.get("channels_bonus_map")
    channels = base["audio_bonuses"]["channels_bonus_map"].copy()
    if isinstance(channels_raw, dict):
        for k, v in channels_raw.items():
            channels[str(k)] = max(0, _to_int(v, 0))
    ab["channels_bonus_map"] = channels

    tiers = profile["tiers"]
    # SCORE-02 (Vague M, M-06) : delegation a tiers_helpers.normalize_tiers
    # pour centraliser la retro-compat legacy (premium/bon/moyen). Comportement
    # preserve : meme defaults v1.5.7 70/66/55/40, meme clamp [0,100], meme
    # suppression des cles legacy apres normalisation.
    normalized = _normalize_tiers_central(tiers)
    tiers["platinum"] = normalized["platinum"]
    tiers["gold"] = normalized["gold"]
    tiers["silver"] = normalized["silver"]
    tiers["bronze"] = normalized["bronze"]
    for _legacy in ("premium", "bon", "moyen", "faible"):
        tiers.pop(_legacy, None)
    if not (tiers["platinum"] >= tiers["gold"] >= tiers["silver"] >= tiers["bronze"]):
        errs.append("Seuils invalides: Platinum >= Gold >= Silver >= Bronze requis.")

    # Custom rules (G6) : passer a travers si present, validation deleguee a custom_rules.validate_rules
    raw_rules = raw_profile.get("custom_rules")
    if isinstance(raw_rules, list):
        profile["custom_rules"] = raw_rules

    return (len(errs) == 0), errs, profile


def _clamp_0_100(value: float) -> int:
    return int(round(max(0.0, min(100.0, float(value)))))


def _confidence_label(value: int) -> str:
    if value >= 75:
        return "Elevee"
    if value >= 50:
        return "Moyenne"
    return "Faible"


def _codec_bonus(codec: str, profile: Dict[str, Any]) -> int:
    c = str(codec or "").strip().lower()
    bonuses = profile["codec_bonuses"]
    if "av1" in c:
        return int(bonuses["av1_bonus"])
    if c in {"hevc", "h265", "h.265", "x265"}:
        return int(bonuses["hevc_bonus"])
    if c in {"avc", "h264", "h.264", "x264"}:
        return int(bonuses["avc_bonus"])
    return 0


def _normalize_bitrate_kbps(raw_bitrate: Any) -> Optional[int]:
    if raw_bitrate is None:
        return None
    n = _to_float(raw_bitrate, -1.0)
    if n <= 0:
        return None
    if n > 100000.0:
        return int(round(n / 1000.0))
    return int(round(n))


_RELEASE_2160_RE = re.compile(r"\b(2160p|4k|uhd)\b", re.IGNORECASE)
_RELEASE_1080_RE = re.compile(r"\b1080p\b", re.IGNORECASE)
_RELEASE_720_RE = re.compile(r"\b720p\b", re.IGNORECASE)
_RELEASE_4K_LIGHT_RE = re.compile(r"\b(4klight|hdlight|uhdrip)\b", re.IGNORECASE)


def _resolution_label(*, width: int, height: int, release_name: str = "") -> Tuple[str, str]:
    # Prefer measured probe dimensions when available.
    w = max(0, int(width or 0))
    h = max(0, int(height or 0))
    # Fix audit 2026-05-30 (v1.5.7) bug 178 faux 720p : utiliser short_edge=min(w,h)
    # classait les films cinema 1920x800 (ratio 2.35:1) en 720p car 800<1000. Or
    # ce sont des 1080p natifs croppes ou matted (les bandes noires retirees).
    # Tous les films 21:9 / 2.39:1 ont une height ~800-900 avec width 1920.
    # Solution : utiliser le pattern (w>=X or h>=Y) coherent avec library_support
    # ._classify_resolution. Width est le critere principal (1920 = 1080p
    # toujours, peu importe l aspect ratio). VERIFIE par ffprobe direct sur 15
    # echantillons de la biblio utilisateur : 15/15 = 1920x[784-818] etaient
    # tous des vrais 1080p mal classes en 720p avec l ancienne logique.
    if w >= 3800 or h >= 2100:
        return "2160p", "probe"
    if w >= 1900 or h >= 1000:
        return "1080p", "probe"
    if w >= 1280 or h >= 680:
        return "720p", "probe"

    rel = str(release_name or "").strip().lower()
    if rel:
        if _RELEASE_2160_RE.search(rel):
            return "2160p", "name_fallback"
        if _RELEASE_1080_RE.search(rel):
            return "1080p", "name_fallback"
        if _RELEASE_720_RE.search(rel):
            return "720p", "name_fallback"
    return "SD", "unknown"


def _resolution_rank(label: str) -> int:
    if label == "2160p":
        return 2160
    if label == "1080p":
        return 1080
    if label == "720p":
        return 720
    return 480


def _extract_languages(audio_tracks: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for track in audio_tracks:
        lang = str(track.get("language") or "").strip().lower()
        if lang:
            out.append(lang)
    return sorted(set(out))


def _has_vo(langs: List[str]) -> bool:
    return any(lang in {"en", "eng", "english", "vo", "vost"} for lang in langs)


def _has_vf(langs: List[str]) -> bool:
    return any(lang in {"fr", "fra", "fre", "french", "vf", "vff", "vfi"} for lang in langs)


def _best_audio_track(audio_tracks: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not audio_tracks:
        return {}
    return max(
        audio_tracks,
        key=lambda t: (
            _to_int(t.get("channels"), 0),
            _to_int(t.get("bitrate"), 0),
        ),
    )


def _audio_codec_bonus(codec: str, profile: Dict[str, Any]) -> Tuple[int, str]:
    c = str(codec or "").strip().lower()
    bonuses = profile["audio_bonuses"]
    if ("truehd" in c) or ("atmos" in c):
        return int(bonuses["truehd_atmos_bonus"]), "Audio TrueHD/Atmos"
    # BUG-3 (v7.8.0) : parentheses explicites. Avant : `... or "ma" in c and "dts" in c`
    # se lisait comme `or ("ma" in c and "dts" in c)` (precedence Python : and > or).
    # Comportement preserve, juste rendu lisible et resistant au refactor.
    if ("dts-hd" in c) or ("dtshd" in c) or ("ma" in c and "dts" in c):
        return int(bonuses["dts_hd_ma_bonus"]), "Audio DTS-HD MA"
    if "dts" in c:
        return int(bonuses["dts_bonus"]), "Audio DTS"
    if "aac" in c:
        return int(bonuses["aac_bonus"]), "Audio AAC"
    return 0, ""


def _channels_bonus(channels: int, profile: Dict[str, Any]) -> Tuple[int, str]:
    cmap = profile["audio_bonuses"]["channels_bonus_map"]
    if channels >= 8:
        return _to_int(cmap.get("7.1"), 0), "Canaux 7.1"
    if channels >= 6:
        return _to_int(cmap.get("5.1"), 0), "Canaux 5.1"
    if channels >= 2:
        return _to_int(cmap.get("2.0"), 0), "Canaux stereo/2.0"
    return 0, ""


def _folder_has_year(folder_name: str, year: int) -> bool:
    if not folder_name or not year:
        return False
    return re.search(rf"\(\s*{int(year)}\s*\)", folder_name) is not None


def _title_in_folder(folder_name: str, title: str) -> bool:
    if not folder_name or not title:
        return False
    nf = re.sub(r"[^a-z0-9]+", " ", folder_name.lower()).strip()
    nt = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return bool(nt) and (nt in nf)


def _score_video(
    video: Dict[str, Any],
    prof: Dict[str, Any],
    *,
    folder_name: str,
    release_name: str,
    reasons: List[str],
    factors: List[Dict[str, Any]],
    primary_genre: Optional[str] = None,
) -> Dict[str, Any]:
    def add_reason(delta: int, label: str) -> None:
        factors.append({"category": "video", "delta": int(delta), "label": str(label)})
        sign = "+" if delta >= 0 else ""
        reasons.append(f"{sign}{delta} {label}")

    vt = prof["video_thresholds"]
    toggles = prof["toggles"]

    width = _to_int(video.get("width"), 0)
    height = _to_int(video.get("height"), 0)
    bitrate_kbps = _normalize_bitrate_kbps(video.get("bitrate"))
    bit_depth = _to_int(video.get("bit_depth"), 0)
    video_codec = str(video.get("codec") or "").lower()
    has_dv = bool(video.get("hdr_dolby_vision"))
    has_hdr10p = bool(video.get("hdr10_plus"))
    has_hdr10 = bool(video.get("hdr10"))
    release_ctx = " ".join([str(folder_name or ""), str(release_name or "")]).strip()
    resolution_label, resolution_source = _resolution_label(
        width=width,
        height=height,
        release_name=release_ctx,
    )
    resolution_rank = _resolution_rank(resolution_label)

    video_sub = 8.0
    if resolution_label == "2160p":
        video_sub += 34
        if resolution_source == "probe":
            add_reason(+16, "Resolution 2160p mesuree")
        else:
            add_reason(+11, "Resolution 2160p deduite du nom")
    elif resolution_label == "1080p":
        video_sub += 24
        if resolution_source == "probe":
            add_reason(+10, "Resolution 1080p mesuree")
        else:
            add_reason(+7, "Resolution 1080p deduite du nom")
    elif resolution_label == "720p":
        video_sub += 14
        add_reason(+5, "Resolution 720p")
    else:
        video_sub += 4
        add_reason(-6, "Resolution faible")

    c_bonus = _codec_bonus(video_codec, prof)
    if c_bonus > 0:
        video_sub += c_bonus
        add_reason(+c_bonus, f"Codec video {video_codec.upper()}")

    hdr_bonus = 0
    if has_dv:
        hdr_bonus = _to_int(prof["hdr_bonuses"]["dv_bonus"], 0)
        add_reason(+hdr_bonus, "Dolby Vision")
    elif has_hdr10p:
        hdr_bonus = _to_int(prof["hdr_bonuses"]["hdr10p_bonus"], 0)
        add_reason(+hdr_bonus, "HDR10+")
    elif has_hdr10:
        hdr_bonus = _to_int(prof["hdr_bonuses"]["hdr10_bonus"], 0)
        add_reason(+hdr_bonus, "HDR10")
    video_sub += hdr_bonus

    is_4k_light = False
    release_4k_light_hint = bool(_RELEASE_4K_LIGHT_RE.search(release_ctx or ""))
    low_bitrate_penalty = _to_int(vt.get("penalty_low_bitrate"), 14)
    penalty_4k_light = _to_int(vt.get("penalty_4k_light"), max(0, low_bitrate_penalty // 2))
    threshold_kbps = 0
    if resolution_rank >= 2160:
        threshold_kbps = _to_int(vt.get("bitrate_min_kbps_2160p"), 18000)
    elif resolution_rank >= 1080:
        threshold_kbps = _to_int(vt.get("bitrate_min_kbps_1080p"), 8000)

    # P4.2 : ajuster le seuil selon le genre (animation tolère bitrate bas,
    # action exige plus). Applique le multiplicateur bitrate_leniency.
    if threshold_kbps > 0 and primary_genre:
        try:
            adjusted = _adj_th(threshold_kbps, primary_genre)
            if adjusted != threshold_kbps:
                reasons.append(
                    f"Seuil bitrate ajusté pour genre '{primary_genre}' : {threshold_kbps} → {adjusted} kb/s"
                )
                threshold_kbps = adjusted
        except ImportError:
            pass

    if bitrate_kbps is None:
        video_sub -= 8
        if resolution_rank >= 2160 and release_4k_light_hint and bool(toggles.get("enable_4k_light", True)):
            is_4k_light = True
            add_reason(-4, "4K Light probable (tag release) sans debit mesure")
        add_reason(-8, "Debit video non detecte")
    elif threshold_kbps > 0:
        ratio = float(bitrate_kbps) / float(max(1, threshold_kbps))
        if ratio >= 1.35:
            video_sub += 18
            add_reason(+12, f"Debit excellent pour {resolution_label} ({bitrate_kbps} kb/s >= {threshold_kbps} kb/s)")
        elif ratio >= 1.15:
            video_sub += 14
            add_reason(+10, f"Debit eleve pour {resolution_label} ({bitrate_kbps} kb/s)")
        elif ratio >= 1.0:
            video_sub += 10
            add_reason(+8, f"Debit correct pour {resolution_label} ({bitrate_kbps} kb/s)")
        elif ratio >= 0.85:
            video_sub += 6
            add_reason(+4, f"Debit proche du seuil {resolution_label} ({bitrate_kbps}/{threshold_kbps} kb/s)")
        elif ratio >= 0.70:
            video_sub += 1
            add_reason(0, f"Debit limite pour {resolution_label} ({bitrate_kbps}/{threshold_kbps} kb/s)")
        else:
            if resolution_rank >= 2160 and bool(toggles.get("enable_4k_light", True)):
                is_4k_light = True
                dynamic_penalty = penalty_4k_light
                if ratio < 0.55:
                    dynamic_penalty = max(dynamic_penalty, penalty_4k_light + 3)
                video_sub -= dynamic_penalty
                if release_4k_light_hint:
                    add_reason(-dynamic_penalty, f"4K Light confirme (tag + debit {bitrate_kbps} kb/s)")
                else:
                    add_reason(
                        -dynamic_penalty, f"4K Light: debit faible pour 2160p ({bitrate_kbps}/{threshold_kbps} kb/s)"
                    )
            else:
                dynamic_penalty = low_bitrate_penalty
                if ratio < 0.55:
                    dynamic_penalty = max(dynamic_penalty, low_bitrate_penalty + 4)
                video_sub -= dynamic_penalty
                add_reason(
                    -dynamic_penalty,
                    f"Debit trop faible pour {resolution_label} ({bitrate_kbps}/{threshold_kbps} kb/s)",
                )
        if resolution_rank >= 2160 and ratio >= 1.15:
            video_sub += 4
            add_reason(+4, "UHD propre: debit soutenu pour 2160p")

    if (has_dv or has_hdr10 or has_hdr10p) and (bit_depth > 0 and bit_depth <= 8):
        p_hdr8 = _to_int(vt.get("penalty_hdr_8bit"), 8)
        video_sub -= p_hdr8
        add_reason(-p_hdr8, "HDR detecte avec profondeur 8 bits")

    video_sub = _clamp_0_100(video_sub)

    logger.debug(
        "_score_video: codec=%s res=%sp bitrate=%skbps hdr=%s dv=%s 4k_light=%s sub=%.1f",
        video_codec,
        height,
        bitrate_kbps,
        has_hdr10,
        has_dv,
        is_4k_light,
        video_sub,
    )

    return {
        "sub": video_sub,
        "width": width,
        "height": height,
        "bitrate_kbps": bitrate_kbps,
        "bit_depth": bit_depth,
        "video_codec": video_codec,
        "has_dv": has_dv,
        "has_hdr10p": has_hdr10p,
        "has_hdr10": has_hdr10,
        "resolution_label": resolution_label,
        "resolution_source": resolution_source,
        "is_4k_light": is_4k_light,
        "release_4k_light_hint": release_4k_light_hint,
    }


def _score_audio(
    audio_tracks: List[Dict[str, Any]],
    prof: Dict[str, Any],
    *,
    reasons: List[str],
    factors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    def add_reason(delta: int, label: str) -> None:
        factors.append({"category": "audio", "delta": int(delta), "label": str(label)})
        sign = "+" if delta >= 0 else ""
        reasons.append(f"{sign}{delta} {label}")

    # Fix audit 2026-05-26 (v1.5.6) Vague L (scoring-5) : base audio 10 -> 12.
    # Sur le panel reel, le subscore audio plafonne autour de 28-32 (DTS-HD MA 5.1 +
    # VO) ce qui penalise les 1080p HEVC HDR propres lors de la ponderation
    # (audio = 30% du score). +2 de base ramene les fichiers audio lossless
    # multicanal au niveau attendu sans gonfler les UHD premium qui sont deja
    # clamped a 100.
    audio_sub = 12.0
    best_audio = _best_audio_track(audio_tracks)
    if not best_audio:
        audio_sub -= 25
        add_reason(-16, "Aucune piste audio exploitable")
    else:
        a_codec = str(best_audio.get("codec") or "").lower()
        a_bonus, a_label = _audio_codec_bonus(a_codec, prof)
        audio_sub += a_bonus
        if a_bonus > 0:
            add_reason(+a_bonus, a_label)
        channels = _to_int(best_audio.get("channels"), 0)
        ch_bonus, ch_label = _channels_bonus(channels, prof)
        audio_sub += ch_bonus
        if ch_bonus > 0:
            add_reason(+ch_bonus, ch_label)
        a_bitrate_kbps = _normalize_bitrate_kbps(best_audio.get("bitrate"))
        if a_bitrate_kbps and channels > 0:
            per_channel = float(a_bitrate_kbps) / float(max(1, channels))
            if per_channel >= 650:
                audio_sub += 4
                add_reason(+4, "Debit audio eleve")
            elif per_channel >= 320:
                audio_sub += 2
                add_reason(+2, "Debit audio correct")
            elif per_channel < 120:
                audio_sub -= 3
                add_reason(-3, "Debit audio faible")
        if ("truehd" in a_codec or "atmos" in a_codec or "dts-hd" in a_codec) and channels >= 8:
            audio_sub += 4
            add_reason(+4, "Audio haut de gamme multicanal")

    langs = _extract_languages(audio_tracks)
    if _has_vo(langs):
        vo_bonus = _to_int(prof["languages"]["bonus_vo_present"], 0)
        audio_sub += vo_bonus
        if vo_bonus > 0:
            add_reason(+vo_bonus, "VO detectee")
    else:
        audio_sub -= 6
        add_reason(-6, "Pas de VO detectee")

    if _has_vf(langs):
        vf_bonus = _to_int(prof["languages"]["bonus_vf_present"], 0)
        audio_sub += vf_bonus
        if vf_bonus > 0:
            add_reason(+vf_bonus, "VF detectee")

    audio_sub = _clamp_0_100(audio_sub)

    if best_audio:
        logger.debug(
            "_score_audio: codec=%s channels=%s langs=%s sub=%.1f",
            best_audio.get("codec"),
            best_audio.get("channels"),
            list(langs),
            audio_sub,
        )
    else:
        logger.debug("_score_audio: aucune piste exploitable sub=%.1f", audio_sub)

    return {
        "sub": audio_sub,
        "best_audio": best_audio,
        "langs": langs,
    }


# Constantes scoring sous-titres
_SUBTITLE_ALL_LANGS_BONUS = 6
_SUBTITLE_PARTIAL_LANGS_BONUS = 3
_SUBTITLE_ABSENT_PENALTY = -4
_SUBTITLE_ORPHAN_PENALTY = -2


def _score_extras(
    probe_quality: str,
    toggles: Dict[str, Any],
    *,
    folder_name: str,
    expected_title: str,
    expected_year: int,
    subtitle_info: Optional[Dict[str, Any]] = None,
    reasons: List[str],
    factors: List[Dict[str, Any]],
) -> int:
    def add_reason(delta: int, label: str) -> None:
        factors.append({"category": "extras", "delta": int(delta), "label": str(label)})
        sign = "+" if delta >= 0 else ""
        reasons.append(f"{sign}{delta} {label}")

    extras_sub = 70.0
    if probe_quality == "FULL":
        extras_sub += 20
        add_reason(+6, "Metadonnees techniques completes")
    elif probe_quality == "PARTIAL":
        extras_sub += 4
        add_reason(-3, "Metadonnees techniques partielles")
    else:
        extras_sub -= 18
        add_reason(-10, "Metadonnees techniques indisponibles")

    if toggles.get("include_metadata"):
        if probe_quality == "PARTIAL":
            extras_sub -= 6
            add_reason(-3, "Mode metadata strict: donnees partielles")
        elif probe_quality == "FAILED":
            extras_sub -= 10
            add_reason(-4, "Mode metadata strict: donnees absentes")

    if toggles.get("include_naming"):
        if expected_year and not _folder_has_year(folder_name, expected_year):
            extras_sub -= 20
            add_reason(-8, "Nommage: annee absente du dossier")
        elif expected_year:
            add_reason(+4, "Nommage: annee presente")
        if expected_title and not _title_in_folder(folder_name, expected_title):
            extras_sub -= 10
            add_reason(-4, "Nommage: titre incomplet dans le dossier")
        elif expected_title:
            add_reason(+3, "Nommage: titre coherent")

    # Sous-titres
    if subtitle_info and toggles.get("include_subtitles"):
        sub_count = int(subtitle_info.get("count") or 0)
        sub_langs = subtitle_info.get("languages") or []
        sub_expected = subtitle_info.get("expected_languages") or []
        sub_missing = subtitle_info.get("missing_languages") or []
        sub_orphans = int(subtitle_info.get("orphans") or 0)

        if sub_expected:
            if not sub_missing:
                extras_sub += _SUBTITLE_ALL_LANGS_BONUS
                add_reason(_SUBTITLE_ALL_LANGS_BONUS, f"Sous-titres : langues completes ({','.join(sub_langs)})")
            elif sub_count > 0:
                extras_sub += _SUBTITLE_PARTIAL_LANGS_BONUS
                add_reason(
                    _SUBTITLE_PARTIAL_LANGS_BONUS, f"Sous-titres : partiels ({len(sub_langs)}/{len(sub_expected)})"
                )
            else:
                extras_sub += _SUBTITLE_ABSENT_PENALTY
                add_reason(_SUBTITLE_ABSENT_PENALTY, "Sous-titres : absents")
        elif sub_count > 0:
            extras_sub += _SUBTITLE_PARTIAL_LANGS_BONUS
            add_reason(_SUBTITLE_PARTIAL_LANGS_BONUS, f"Sous-titres : {sub_count} fichier(s)")

        if sub_orphans > 0:
            extras_sub += _SUBTITLE_ORPHAN_PENALTY
            add_reason(_SUBTITLE_ORPHAN_PENALTY, f"Sous-titres orphelins : {sub_orphans}")

    return _clamp_0_100(extras_sub)


def _apply_weights(
    video_sub: int,
    audio_sub: int,
    extras_sub: int,
    weights: Dict[str, Any],
) -> int:
    total_weight = max(1, _to_int(weights["video"], 0) + _to_int(weights["audio"], 0) + _to_int(weights["extras"], 0))
    score_f = (
        video_sub * _to_int(weights["video"], 0)
        + audio_sub * _to_int(weights["audio"], 0)
        + extras_sub * _to_int(weights["extras"], 0)
    ) / float(total_weight)
    return _clamp_0_100(score_f)


def _determine_tier(score: int, tiers: Dict[str, Any]) -> str:
    """Retourne le tier (Platinum / Gold / Silver / Bronze / Reject).

    SCORE-02 (Vague M, M-06) : delegation a tiers_helpers.normalize_tiers pour
    la retro-compat legacy (premium/bon/moyen). Defaults v1.5.7 70/66/55/40.
    """
    seuils = _normalize_tiers_central(tiers)
    s = _to_int(score, 0)
    if s >= seuils["platinum"]:
        return "Platinum"
    if s >= seuils["gold"]:
        return "Gold"
    if s >= seuils["silver"]:
        return "Silver"
    if s >= seuils["bronze"]:
        return "Bronze"
    return "Reject"


# Fix audit 2026-05-26 (v1.5.6) Vague L : ordre des tiers, du meilleur au pire,
# pour pouvoir CAPER un tier a un maximum (on ne descend jamais, on plafonne).
_TIER_ORDER = ["Platinum", "Gold", "Silver", "Bronze", "Reject"]


def _cap_tier(tier: str, max_tier: str) -> str:
    """Plafonne `tier` a `max_tier` (ne remonte jamais un tier vers le haut).

    Fix audit 2026-05-26 (v1.5.6) Vague L (scoring-1) : quand le probe a echoue,
    on ne peut PAS certifier Platinum/Gold sur un simple nom de fichier
    declaratif (non verifie). On cape donc le tier a Silver maximum. Idem pour
    une captation degradee (CAM) qui est plafonnee bien plus bas.
    """
    try:
        cur = _TIER_ORDER.index(tier)
    except ValueError:
        return tier
    try:
        cap = _TIER_ORDER.index(max_tier)
    except ValueError:
        return tier
    # Index plus grand = tier plus bas. On garde le plus bas des deux.
    return _TIER_ORDER[max(cur, cap)]


# Fix audit 2026-05-26 (v1.5.7) hotfix dataclass : normaliseur central.
# Tous les helpers qui peuvent recevoir un NormalizedProbe @dataclass ou
# un dict natif passent par ce filtre pour eviter les branches `else -> {}`
# silencieuses qui faussaient duration_s, edition, tmdb_collection_id, file_size.
def _normalize_probe_arg(x: Any) -> Dict[str, Any]:
    if _is_dc(x) and not isinstance(x, type):
        return _asdict(x)
    if isinstance(x, dict):
        return x
    return {}


def _estimate_file_size(normalized_probe: Any, bitrate_kbps: Optional[int]) -> int:
    """Estime la taille du fichier en octets depuis duration et bitrate."""
    # Fix audit 2026-05-26 (v1.5.7) hotfix dataclass : accepter NormalizedProbe
    # @dataclass natif (cinesort.infra.probe.service.ProbeService) en plus du dict.
    normalized_probe = _normalize_probe_arg(normalized_probe)
    dur = float(normalized_probe.get("duration_s") or 0)
    br = int(bitrate_kbps or 0)
    if dur > 0 and br > 0:
        return int(dur * br * 1000 / 8)  # kbps → bps → bytes
    return 0


_ERA_HERITAGE_YEAR = 1970
_ERA_CLASSIC_YEAR = 1995
_ERA_MODERN_YEAR = 2020
_ERA_HERITAGE_BONUS = 8
_ERA_CLASSIC_BONUS = 4
_ERA_MODERN_PENALTY = -4
_PENALTY_UPSCALE = -8
_PENALTY_REENCODE = -6
_PENALTY_4K_LIGHT = -3
_PENALTY_COMMENTARY_ONLY = -15


def _build_invalid_profile_result(
    profile: Any,
    normalized_probe: Any,
    errs: List[str],
) -> Dict[str, Any]:
    """Construit le resultat retourne quand le profil est invalide."""
    # Fix audit 2026-05-26 (v1.5.7) hotfix dataclass : convertir NormalizedProbe
    # dataclass -> dict avant la branche isinstance, sinon le probe_quality reel
    # (FULL/PARTIAL) etait ecrase en 'FAILED' silencieusement.
    normalized_probe = _normalize_probe_arg(normalized_probe)
    return {
        "score": 0,
        "tier": "Reject",
        "reasons": errs,
        "metrics": {
            "engine_version": "CinemaLux_v1",
            "profile_id": str(profile.get("id") if isinstance(profile, dict) else DEFAULT_PROFILE_ID),
            "profile_version": _to_int(
                profile.get("version") if isinstance(profile, dict) else DEFAULT_PROFILE_VERSION,
                DEFAULT_PROFILE_VERSION,
            ),
            "probe_quality": str(normalized_probe.get("probe_quality")),
            "validation_errors": errs,
        },
    }


def _detect_primary_genre_safe(tmdb_genres: Optional[List[str]]) -> Optional[str]:
    """Detecte le genre primaire TMDb avec import safe (None si module absent)."""
    if not tmdb_genres:
        return None
    try:
        return _detect_pg(tmdb_genres)
    except ImportError:
        return None


def _apply_era_bonuses_helper(
    *,
    film_year: Optional[int],
    height: int,
    video_codec: str,
    video_sub: float,
    factors: List[Dict[str, Any]],
    reasons: List[str],
) -> float:
    """Applique le bonus/malus contextuel d'ere du film (patrimoine, classique, recent).

    Modifie factors et reasons en place ; retourne le video_sub mis a jour.
    """
    if not film_year or film_year <= 0:
        return video_sub
    if film_year <= _ERA_HERITAGE_YEAR and height >= 1080:
        video_sub += _ERA_HERITAGE_BONUS
        factors.append(
            {"category": "video", "delta": _ERA_HERITAGE_BONUS, "label": f"Film patrimoine ({film_year}) en HD"}
        )
        reasons.append(f"+{_ERA_HERITAGE_BONUS} Film patrimoine ({film_year}) en HD")
        logger.debug("scoring: bonus ere +%d (annee=%d, res=%dp)", _ERA_HERITAGE_BONUS, film_year, height)
    elif film_year <= _ERA_CLASSIC_YEAR and height >= 720:
        video_sub += _ERA_CLASSIC_BONUS
        factors.append(
            {"category": "video", "delta": _ERA_CLASSIC_BONUS, "label": f"Film classique ({film_year}) en HD"}
        )
        reasons.append(f"+{_ERA_CLASSIC_BONUS} Film classique ({film_year}) en HD")
        logger.debug("scoring: bonus ere +%d (annee=%d, res=%dp)", _ERA_CLASSIC_BONUS, film_year, height)
    elif film_year >= _ERA_MODERN_YEAR and height <= 1080 and video_codec != "av1":
        video_sub += _ERA_MODERN_PENALTY
        factors.append(
            {
                "category": "video",
                "delta": _ERA_MODERN_PENALTY,
                "label": f"Film recent ({film_year}) en definition standard",
            }
        )
        reasons.append(f"{_ERA_MODERN_PENALTY} Film recent ({film_year}) en definition standard")
        logger.debug("scoring: malus ere %d (annee=%d, res=%dp)", _ERA_MODERN_PENALTY, film_year, height)
    return video_sub


def _apply_encode_warnings_helper(
    *,
    encode_warnings: Optional[List[str]],
    video_sub: float,
    factors: List[Dict[str, Any]],
    reasons: List[str],
) -> float:
    """Applique les penalites perceptuelles selon les encode warnings (upscale, reencode, 4k_light).

    Modifie factors et reasons en place ; retourne le video_sub mis a jour.
    """
    if not encode_warnings:
        return video_sub
    for ew in encode_warnings:
        if ew == "upscale_suspect":
            video_sub += _PENALTY_UPSCALE
            factors.append({"category": "video", "delta": _PENALTY_UPSCALE, "label": "Upscale suspect"})
            reasons.append(f"{_PENALTY_UPSCALE} Upscale suspect")
        elif ew == "reencode_degraded":
            video_sub += _PENALTY_REENCODE
            factors.append({"category": "video", "delta": _PENALTY_REENCODE, "label": "Re-encode degrade"})
            reasons.append(f"{_PENALTY_REENCODE} Re-encode degrade")
        elif ew == "4k_light":
            video_sub += _PENALTY_4K_LIGHT
            factors.append({"category": "video", "delta": _PENALTY_4K_LIGHT, "label": "4K light (streaming)"})
            reasons.append(f"{_PENALTY_4K_LIGHT} 4K light (streaming)")
    return video_sub


def _apply_commentary_penalty_helper(
    *,
    audio_analysis: Optional[Dict[str, Any]],
    audio_sub: float,
    factors: List[Dict[str, Any]],
    reasons: List[str],
) -> float:
    """Applique la penalite commentary-only (piste unique = commentaire).

    Modifie factors et reasons en place ; retourne le audio_sub mis a jour.
    """
    if not audio_analysis:
        return audio_sub
    if int(audio_analysis.get("tracks_count") or 0) == 1 and audio_analysis.get("has_commentary"):
        audio_sub += _PENALTY_COMMENTARY_ONLY
        factors.append({"category": "audio", "delta": _PENALTY_COMMENTARY_ONLY, "label": "Piste unique = commentaire"})
        reasons.append(f"{_PENALTY_COMMENTARY_ONLY} Piste unique = commentaire")
    return audio_sub


def _apply_genre_adjustments_helper(
    *,
    tmdb_genres: Optional[List[str]],
    video: Dict[str, Any],
    audio_analysis: Optional[Dict[str, Any]],
    encode_warnings: Optional[List[str]],
    video_sub: float,
    audio_sub: float,
    extras_sub: float,
    factors: List[Dict[str, Any]],
    reasons: List[str],
) -> Tuple[float, float, float, Optional[str]]:
    """Applique les ajustements genre-aware TMDb.

    Modifie factors et reasons en place ; retourne (video_sub, audio_sub, extras_sub, primary_genre).
    """
    primary_genre: Optional[str] = None
    if not tmdb_genres:
        return video_sub, audio_sub, extras_sub, None
    primary_genre = _detect_pg(tmdb_genres)
    if not primary_genre:
        return video_sub, audio_sub, extras_sub, primary_genre
    height_g = _to_int(video.get("height"), 0)
    codec_g = str(video.get("codec") or "")
    has_hdr_g = bool(video.get("hdr10") or video.get("hdr10_plus") or video.get("hdr_dolby_vision"))
    has_atmos_g = False
    if audio_analysis and isinstance(audio_analysis, dict):
        badge = str(audio_analysis.get("badge_label") or "").lower()
        has_atmos_g = "atmos" in badge or "truehd" in badge
    has_grain_g = bool(encode_warnings) and any("grain" in str(w).lower() for w in encode_warnings)
    _genre_delta, genre_factors = compute_genre_adjustments(
        primary_genre,
        video_codec=codec_g,
        height=height_g,
        has_hdr=has_hdr_g,
        has_atmos=has_atmos_g,
        has_heavy_grain=has_grain_g,
    )
    for gf in genre_factors:
        factors.append(gf)
        cat = str(gf.get("category") or "video")
        delta_val = int(gf.get("delta") or 0)
        if cat == "audio":
            audio_sub += delta_val
        elif cat == "extras":
            extras_sub += delta_val
        else:
            video_sub += delta_val
        reasons.append(f"{'+' if delta_val >= 0 else ''}{delta_val} {gf.get('label')}")
    return video_sub, audio_sub, extras_sub, primary_genre


def _apply_custom_rules_helper(
    *,
    prof: Dict[str, Any],
    score: int,
    tier: str,
    vr: Dict[str, Any],
    best_audio: Dict[str, Any],
    normalized_probe: Dict[str, Any],
    film_year: Optional[int],
    subtitle_info: Optional[Dict[str, Any]],
    encode_warnings: Optional[List[str]],
    factors: List[Dict[str, Any]],
    reasons: List[str],
) -> Tuple[int, str, List[str], List[str]]:
    """Applique les custom rules (G6) sur le score/tier.

    Modifie factors et reasons en place ; retourne (score, tier, custom_flags_added, applied_rule_ids).
    """
    custom_rules = prof.get("custom_rules") or []
    custom_flags_added: List[str] = []
    applied_rule_ids: List[str] = []
    if not custom_rules:
        return score, tier, custom_flags_added, applied_rule_ids
    # Fix audit 2026-05-26 (v1.5.7) hotfix dataclass : normaliser EN TETE pour
    # que edition/duration_s/tmdb_collection_id soient lus correctement meme si
    # le caller passe un NormalizedProbe dataclass (le call site compute_quality_score
    # transmettait la variable brute non convertie, cf bug critique fix).
    normalized_probe = _normalize_probe_arg(normalized_probe)
    try:
        resolution_rank_map = {"2160p": 3, "1080p": 2, "720p": 1, "SD": 0, "480p": 0}
        file_size_bytes = _estimate_file_size(normalized_probe, vr["bitrate_kbps"])
        rule_context = {
            "detected": {
                "video_codec": vr["video_codec"],
                "audio_best_codec": str(best_audio.get("codec") or ""),
                "resolution": vr["resolution_label"],
                "bitrate_kbps": vr["bitrate_kbps"],
                "audio_best_channels": _to_int(best_audio.get("channels"), 0),
                "hdr10": vr["has_hdr10"],
                "hdr10_plus": vr["has_hdr10p"],
                "hdr_dolby_vision": vr["has_dv"],
            },
            "__context__": {
                "year": int(film_year or 0),
                "subtitle_count": int((subtitle_info or {}).get("count") or 0),
                "subtitle_languages": list((subtitle_info or {}).get("languages") or []),
                "warning_flags": list(encode_warnings or []),
                "edition": normalized_probe.get("edition"),
                "duration_s": int(normalized_probe.get("duration_s") or 0),
            },
            "__computed__": {
                "resolution_rank": resolution_rank_map.get(str(vr["resolution_label"]), 0),
                "tier_before": tier,
                "score_before": int(score),
                "file_size_gb": round(file_size_bytes / 1e9, 2) if file_size_bytes else 0.0,
                "tmdb_in_collection": bool(normalized_probe.get("tmdb_collection_id")),
            },
        }
        rule_result = _apply_rules(score, rule_context, custom_rules)
        if rule_result.get("applied_rule_ids"):
            # QW03 (anti-fraude Platinum) : reclamp defensif [0, 100] apres
            # custom_rules. Bien que les actions internes (_act_score_delta,
            # _act_score_mult, _act_force_score, _act_cap_*) appliquent deja
            # _clamp en sortie, on reclamp ici comme defense en profondeur :
            # si une regle custom future, un bug de plugin ou une serialisation
            # corrompue injectait un score > 100, le tier serait Platinum
            # frauduleusement (ex: score=150 -> Platinum certain). Le clamp
            # garantit l invariant score in [0, 100] avant la decision tier.
            score = _clamp_0_100(rule_result["score"])
            reasons.extend(rule_result.get("reasons") or [])
            custom_flags_added = list(rule_result.get("flags_added") or [])
            applied_rule_ids = list(rule_result.get("applied_rule_ids") or [])
            for rid in applied_rule_ids:
                factors.append({"category": "custom", "delta": 0, "label": f"Rule: {rid}"})
            if rule_result.get("force_tier"):
                tier = str(rule_result["force_tier"])
            else:
                tier = _determine_tier(score, prof["tiers"])
    except (TypeError, ValueError, KeyError) as exc:
        logger.warning("custom_rules: pipeline error %s", exc)
    return score, tier, custom_flags_added, applied_rule_ids


def _append_probe_quality_reasons(
    probe: Dict[str, Any],
    factors: List[Dict[str, Any]],
    reasons: List[str],
) -> None:
    """Ajoute les raisons issues du probe (probe_quality_reasons) aux factors/reasons."""
    quality_reasons = probe.get("probe_quality_reasons")
    if isinstance(quality_reasons, list):
        for qr in quality_reasons:
            qtxt = str(qr).strip()
            if qtxt:
                factors.append({"category": "probe", "delta": 0, "label": f"Probe: {qtxt}"})
                reasons.append(f"+0 Probe: {qtxt}")


def _compute_confidence_helper(
    *,
    probe_quality: str,
    vr: Dict[str, Any],
    audio_tracks: List[Dict[str, Any]],
) -> Tuple[int, str, List[str]]:
    """Calcule (value, label, reasons) de la confiance score selon probe + completude metadata."""
    confidence_reasons: List[str] = []
    confidence_value = 58
    if probe_quality == "FULL":
        confidence_value += 24
        confidence_reasons.append("Probe complete (ffprobe/MediaInfo exploitables).")
    elif probe_quality == "PARTIAL":
        confidence_value -= 10
        confidence_reasons.append("Probe partielle (certaines metadonnees manquent).")
    else:
        confidence_value -= 28
        confidence_reasons.append("Probe indisponible: score base sur donnees limitees.")

    resolution_source = vr["resolution_source"]
    if resolution_source == "probe":
        confidence_value += 8
        confidence_reasons.append("Resolution issue des metadonnees mesurees.")
    elif resolution_source == "name_fallback":
        confidence_value -= 10
        confidence_reasons.append("Resolution deduite du nom release (fallback).")
    else:
        confidence_value -= 16
        confidence_reasons.append("Resolution peu fiable.")

    bitrate_kbps = vr["bitrate_kbps"]
    if bitrate_kbps is None:
        confidence_value -= 12
        confidence_reasons.append("Debit video absent.")
    else:
        confidence_value += 4
    if vr["width"] <= 0 or vr["height"] <= 0:
        confidence_value -= 8
    if not vr["video_codec"]:
        confidence_value -= 8
    if not audio_tracks:
        confidence_value -= 8
        confidence_reasons.append("Aucune piste audio detaillee.")
    confidence_value = _clamp_0_100(confidence_value)
    return confidence_value, _confidence_label(confidence_value), confidence_reasons


def _build_quality_metrics_helper(
    *,
    prof: Dict[str, Any],
    probe_quality: str,
    vr: Dict[str, Any],
    best_audio: Dict[str, Any],
    audio_tracks: List[Dict[str, Any]],
    langs: List[str],
    normalized_probe: Dict[str, Any],
    sources: Dict[str, Any],
    toggles: Dict[str, Any],
    confidence_value: int,
    confidence_label: str,
    confidence_reasons: List[str],
    video_sub: float,
    audio_sub: float,
    extras_sub: float,
    custom_flags_added: List[str],
    applied_rule_ids: List[str],
    tmdb_genres: Optional[List[str]],
    primary_genre: Optional[str],
) -> Dict[str, Any]:
    """Construit le dictionnaire metrics retourne dans le QualityScoreResult."""
    # Fix audit 2026-05-26 (v1.5.7) hotfix dataclass : normaliser pour que
    # detected.duration_s et detected.file_size_bytes ne soient pas 0 quand
    # un NormalizedProbe @dataclass est passe (caller compute_quality_score
    # transmettait la variable brute, exposant la UI Bibliotheque a un faux 0).
    normalized_probe = _normalize_probe_arg(normalized_probe)
    weights = prof["weights"]
    vt = prof["video_thresholds"]
    return {
        "engine_version": str(prof.get("engine_version") or "CinemaLux_v1"),
        "profile_id": str(prof.get("id") or DEFAULT_PROFILE_ID),
        "profile_version": _to_int(prof.get("version"), DEFAULT_PROFILE_VERSION),
        "probe_quality": probe_quality,
        "detected": {
            "resolution": vr["resolution_label"],
            "resolution_source": vr["resolution_source"],
            "width": vr["width"],
            "height": vr["height"],
            "bitrate_kbps": vr["bitrate_kbps"],
            "video_codec": vr["video_codec"],
            "bit_depth": vr["bit_depth"],
            "hdr_dolby_vision": vr["has_dv"],
            "hdr10_plus": vr["has_hdr10p"],
            "hdr10": vr["has_hdr10"],
            "audio_tracks_count": len(audio_tracks),
            "audio_best_codec": str(best_audio.get("codec") or ""),
            "audio_best_channels": _to_int(best_audio.get("channels"), 0),
            "languages": langs,
            "duration_s": float(normalized_probe.get("duration_s") or 0),
            "file_size_bytes": _estimate_file_size(normalized_probe, vr["bitrate_kbps"]),
        },
        "weights": copy.deepcopy(weights),
        "thresholds_used": {
            "bitrate_min_kbps_2160p": _to_int(vt.get("bitrate_min_kbps_2160p"), 18000),
            "bitrate_min_kbps_1080p": _to_int(vt.get("bitrate_min_kbps_1080p"), 8000),
            "penalty_low_bitrate": _to_int(vt.get("penalty_low_bitrate"), 14),
            "penalty_4k_light": _to_int(vt.get("penalty_4k_light"), 7),
            "penalty_hdr_8bit": _to_int(vt.get("penalty_hdr_8bit"), 8),
        },
        "flags": {
            "is_4k_light": vr["is_4k_light"],
            "release_4k_light_hint": vr["release_4k_light_hint"],
            "include_metadata": bool(toggles.get("include_metadata")),
            "include_naming": bool(toggles.get("include_naming")),
            "enable_4k_light": bool(toggles.get("enable_4k_light")),
        },
        "sources": copy.deepcopy(sources),
        "score_confidence": {
            "value": confidence_value,
            "label": confidence_label,
            "reasons": confidence_reasons,
        },
        "subscores": {
            "video": video_sub,
            "audio": audio_sub,
            "extras": extras_sub,
        },
        "custom_warning_flags": custom_flags_added,
        "applied_rule_ids": applied_rule_ids,
        # P4.2 : genre TMDb détecté + règles appliquées (pour explain-score)
        "tmdb_genres": list(tmdb_genres or []),
        "primary_genre": primary_genre,
    }


# Fix audit 2026-05-25 (v1.5.5) Vague K : map codec name parser -> codec normalise
# pour alignement avec _codec_bonus() (qui attend "hevc", "h264", "av1", ...).
_NAME_CODEC_TO_PROBE_CODEC = {
    "hevc": "hevc",
    "h264": "h264",
    "av1": "av1",
    "vp9": "vp9",
    "mpeg2": "mpeg2video",
    "xvid": "mpeg4",
}

# Fix audit 2026-05-25 (v1.5.5) Vague K : map codec audio parser -> codec normalise
# pour alignement avec _audio_codec_bonus() (qui matche sur substrings : "truehd",
# "atmos", "dts-hd", "dts", "aac"). On choisit la representation qui s'auto-match.
_NAME_AUDIO_CODEC_TO_PROBE = {
    "truehd": "truehd",
    "atmos": "truehd",  # atmos sans precision -> TrueHD Atmos (cas dominant)
    "dts_x": "dts",
    "dts_hd_ma": "dts-hd ma",
    "dts_hd_hra": "dts-hd hra",
    "dts_hd": "dts-hd",
    "dts": "dts",
    "flac": "flac",
    "pcm": "pcm",
    "eac3": "eac3",
    "ac3": "ac3",
    "aac": "aac",
    "mp3": "mp3",
}


def _channels_str_to_int(channels_str: str) -> int:
    """Convertit '5.1' -> 6, '7.1' -> 8, '2.0' -> 2, '2.1' -> 3."""
    if not channels_str:
        return 0
    txt = channels_str.strip()
    if "." not in txt:
        try:
            return int(txt)
        except ValueError:
            return 0
    try:
        main_str, lfe_str = txt.split(".", 1)
        return max(0, int(main_str)) + max(0, int(lfe_str))
    except (ValueError, TypeError):
        return 0


def _merge_probe_with_name_hints(
    normalized_probe: Dict[str, Any],
    name_info: ReleaseNameInfo,
) -> Tuple[Dict[str, Any], List[str]]:
    """Fusionne le probe avec les hints du nom de release.

    Le probe (ffprobe/MediaInfo) gagne TOUJOURS quand il a une valeur :
    c'est la source de verite la plus fiable. Le nom de release ne sert
    qu'a combler les trous (PARTIAL) ou se substituer (FAILED).

    Retourne (probe_enrichi, liste_des_champs_combles_par_nom).
    """
    # Fix audit 2026-05-26 (v1.5.7) hotfix dataclass : si un caller externe passe
    # un NormalizedProbe @dataclass, on convertit AVANT le check isinstance(dict)
    # pour eviter le wipe-and-replace ({} + remplissage uniquement depuis le nom),
    # signature exacte du bug v1.5.6.
    normalized_probe = _normalize_probe_arg(normalized_probe)
    # Copie defensive pour ne pas muter le dict d'entree (utilise ailleurs).
    enriched = copy.deepcopy(normalized_probe)
    enriched.setdefault("video", {})
    enriched.setdefault("audio_tracks", [])
    enriched.setdefault("sources", {})
    video = enriched["video"] if isinstance(enriched["video"], dict) else {}
    enriched["video"] = video
    sources_video = enriched["sources"].get("video") if isinstance(enriched["sources"], dict) else {}
    if not isinstance(sources_video, dict):
        sources_video = {}
    enriched["sources"]["video"] = sources_video

    filled_from_name: List[str] = []

    # Video dimensions : on NE remplit PAS video.width/height dans le dict probe
    # pour preserver le contrat de _resolution_label() qui distingue "probe"
    # (mesure) vs "name_fallback" (deduit du nom). Le `release_name` passe
    # directement a _score_video. On indique juste filled_from_name pour info.
    if _to_int(video.get("width"), 0) <= 0 and name_info.width_hint > 0:
        filled_from_name.append("width")
    if _to_int(video.get("height"), 0) <= 0 and name_info.height_hint > 0:
        filled_from_name.append("height")

    # Codec video
    if not str(video.get("codec") or "").strip() and name_info.codec_hint:
        video["codec"] = _NAME_CODEC_TO_PROBE_CODEC.get(name_info.codec_hint, name_info.codec_hint)
        sources_video["codec"] = "name_fallback"
        filled_from_name.append("codec")

    # Bit depth
    if _to_int(video.get("bit_depth"), 0) <= 0 and name_info.bit_depth_hint > 0:
        video["bit_depth"] = name_info.bit_depth_hint
        sources_video["bit_depth"] = "name_fallback"
        filled_from_name.append("bit_depth")

    # HDR : on ne touche que si AUCUN flag HDR n'est dispo dans le probe.
    has_any_hdr_probe = bool(
        video.get("hdr_dolby_vision") or video.get("hdr10_plus") or video.get("hdr10") or video.get("hlg")
    )
    if not has_any_hdr_probe and name_info.hdr_hint:
        if name_info.hdr_hint == "dv":
            video["hdr_dolby_vision"] = True
            filled_from_name.append("hdr_dolby_vision")
        elif name_info.hdr_hint == "hdr10_plus":
            video["hdr10_plus"] = True
            filled_from_name.append("hdr10_plus")
        elif name_info.hdr_hint == "hdr10":
            video["hdr10"] = True
            filled_from_name.append("hdr10")
        elif name_info.hdr_hint == "hlg":
            video["hlg"] = True
            filled_from_name.append("hlg")
        sources_video["hdr"] = "name_fallback"

    # Audio : si aucune piste exploitable dans le probe et qu'on a un hint codec,
    # on synthetise une piste virtuelle pour permettre le scoring audio.
    audio_tracks = enriched["audio_tracks"]
    if not audio_tracks and name_info.audio_codec_hint:
        synth_codec = _NAME_AUDIO_CODEC_TO_PROBE.get(name_info.audio_codec_hint, name_info.audio_codec_hint)
        # Si atmos detecte, on enrichit le nom du codec pour que _audio_codec_bonus
        # capture le label "atmos" (matche sur substring).
        if name_info.audio_is_atmos and "atmos" not in synth_codec:
            synth_codec = f"{synth_codec} atmos"
        channels_int = _channels_str_to_int(name_info.audio_channels_hint)
        if channels_int <= 0:
            # Defaut sage : codec lossless multicanal supposes 5.1, sinon 2.0.
            channels_int = 6 if name_info.audio_is_lossless else 2
        synth_track = {
            "codec": synth_codec,
            "channels": channels_int,
            # Pas de bitrate (le scoring le tolere). Pas de language : on perdra
            # le bonus VO/VF mais c'est le tradeoff acceptable d'un fallback.
            "bitrate": 0,
            "language": "",
            "_source": "name_fallback",
        }
        audio_tracks.append(synth_track)
        filled_from_name.append("audio_track_synth")

    return enriched, filled_from_name


def compute_quality_score(
    *,
    normalized_probe: Dict[str, Any],
    profile: Dict[str, Any],
    folder_name: str = "",
    expected_title: str = "",
    expected_year: int = 0,
    release_name: str = "",
    subtitle_info: Optional[Dict[str, Any]] = None,
    film_year: Optional[int] = None,
    encode_warnings: Optional[List[str]] = None,
    audio_analysis: Optional[Dict[str, Any]] = None,
    tmdb_genres: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Orchestrateur scoring CinemaLux : valide, score (video/audio/extras),
    applique bonus/malus contextuels (ere, encode, commentary, genre TMDb,
    custom rules), pondere et determine le tier final.

    Refactor V4-02 (Polish Total v7.7.0) : 369L -> ~80L orchestrateur via
    extraction de 7 helpers prives (_apply_era_bonuses_helper,
    _apply_encode_warnings_helper, _apply_commentary_penalty_helper,
    _apply_genre_adjustments_helper, _apply_custom_rules_helper,
    _compute_confidence_helper, _build_quality_metrics_helper). Compatibilite
    100% : signature publique + valeurs numeriques + tier IDENTIQUES.
    """
    # --- Validation profil ---
    ok, errs, prof = validate_quality_profile(profile)
    if not ok:
        return _build_invalid_profile_result(profile, normalized_probe, errs)

    # --- Setup contexte ---
    # Fix audit 2026-05-26 (v1.5.6) Vague L+ : BUG CRITIQUE DE PROD detecte par
    # test manuel apres Vague L. compute_quality_score traitait normalized_probe
    # comme un Dict UNIQUEMENT. Or `cinesort.infra.probe.service.ProbeService`
    # retourne un NormalizedProbe @dataclass. isinstance(dataclass_instance, dict)
    # vaut False -> probe={} -> probe_quality='FAILED' meme avec un vrai probe
    # FULL -> tier=Silver max sur TOUS les films, scoring lit le nom de fichier
    # uniquement. Le finding Vague L lib-1 (memes cles divergentes en library_
    # support) a ete corrige mais le meme pattern subsistait ici, non couvert par
    # les tests (les tests passent des dicts simules). Conversion dataclass->dict
    # via dataclasses.asdict + acceptation du dict natif si deja converti.
    # M-04 (Vague M) SCORE-DEAD-CODE : import local supprime, _asdict et _is_dc
    # sont deja importes en top-level (L11) et le shadowing local n'apporte rien.
    if _is_dc(normalized_probe) and not isinstance(normalized_probe, type):
        probe = _asdict(normalized_probe)
    elif isinstance(normalized_probe, dict):
        probe = normalized_probe
    else:
        probe = {}
    probe_quality = str(probe.get("probe_quality") or "FAILED")

    # Fix audit 2026-05-25 (v1.5.5) Vague K : enrichir le probe avec les hints
    # du nom de release. Le probe garde la priorite quand il a une valeur ;
    # les hints comblent les trous (PARTIAL) ou se substituent (FAILED).
    name_info = parse_release_name(release_name) if release_name else ReleaseNameInfo()
    probe, name_filled_fields = _merge_probe_with_name_hints(probe, name_info)

    video = probe.get("video") if isinstance(probe.get("video"), dict) else {}
    audio_tracks = probe.get("audio_tracks") if isinstance(probe.get("audio_tracks"), list) else []
    sources = probe.get("sources") if isinstance(probe.get("sources"), dict) else {}
    toggles = prof["toggles"]

    reasons: List[str] = []
    factors: List[Dict[str, Any]] = []

    # Fix audit 2026-05-25 (v1.5.5) Vague K : trace dans les factors quand
    # on a comble des champs depuis le nom de release.
    if name_filled_fields:
        factors.append(
            {
                "category": "probe",
                "delta": 0,
                "label": f"Specs deduites du nom: {', '.join(name_filled_fields)}",
            }
        )
        reasons.append(f"+0 Specs deduites du nom de release: {', '.join(name_filled_fields)}")

    # --- Subscores (3 helpers historiques) ---
    # P4.2 : détecter le genre tôt pour ajuster les seuils de bitrate dans _score_video.
    early_primary_genre = _detect_primary_genre_safe(tmdb_genres)
    vr = _score_video(
        video,
        prof,
        folder_name=folder_name,
        release_name=release_name,
        reasons=reasons,
        factors=factors,
        primary_genre=early_primary_genre,
    )
    video_sub = vr["sub"]

    ar = _score_audio(audio_tracks, prof, reasons=reasons, factors=factors)
    audio_sub = ar["sub"]
    best_audio = ar["best_audio"]
    langs = ar["langs"]

    extras_sub = _score_extras(
        probe_quality,
        toggles,
        folder_name=folder_name,
        expected_title=expected_title,
        expected_year=expected_year,
        subtitle_info=subtitle_info,
        reasons=reasons,
        factors=factors,
    )

    # Fix audit 2026-05-25 (v1.5.5) Vague K : bonus de source (REMUX, BluRay,
    # WEBDL, ...) deduite du nom de release. Cette info est absente du probe.
    if name_info.source_hint:
        source_bonus_map = {
            "remux": (+7, "Source REMUX (nom)"),
            "bluray": (+5, "Source BluRay (nom)"),
            "webdl": (+3, "Source WEB-DL (nom)"),
            "webrip": (+2, "Source WEBRip (nom)"),
            "hdtv": (+1, "Source HDTV (nom)"),
            "dvd": (0, "Source DVD (nom)"),
            "cam": (-10, "Source CAM (nom)"),
        }
        if name_info.source_hint in source_bonus_map:
            src_delta, src_label = source_bonus_map[name_info.source_hint]
            if src_delta != 0:
                video_sub = max(0.0, min(100.0, float(video_sub) + src_delta))
                factors.append({"category": "video", "delta": src_delta, "label": src_label})
                sign = "+" if src_delta >= 0 else ""
                reasons.append(f"{sign}{src_delta} {src_label}")

    # Fix audit 2026-05-26 (v1.5.6) Vague L (scoring-1) : PENALITE CAM/TS/SCREENER
    # forte et INCONDITIONNELLE. Une captation degradee (CAM, TeleSync, Screener)
    # reste de tres mauvaise qualite meme si le nom ment avec des tokens
    # superieurs colles (ex: "X.CAM.2160p.REMUX.DV"). On ecrase les bonus
    # resolution/codec/source en imposant un plancher bas sur les subscores et
    # on memorise le flag pour caper le tier final plus bas.
    cam_detected = bool(name_info.is_cam)
    if cam_detected:
        cam_label = f"Captation degradee ({name_info.cam_token.upper() or 'CAM'}) - qualite reelle tres faible"
        # Plancher dur : peu importe les tokens premium menteurs, une CAM ne
        # peut pas avoir un bon subscore video/audio.
        video_sub = min(float(video_sub), 14.0)
        audio_sub = min(float(audio_sub), 14.0)
        factors.append({"category": "video", "delta": -30, "label": cam_label})
        reasons.append(f"-30 {cam_label}")

    # Fix audit 2026-05-25 (v1.5.5) Vague K : bonus Atmos/DTS:X depuis le nom
    # de release quand le probe ne les a pas detectes (ex: piste TrueHD sans
    # side-data Atmos exposee). On n'ajoute que si l'audio sub n'a pas deja
    # capture ces formats.
    if name_info.audio_is_atmos or name_info.audio_is_dts_x:
        # Verifier qu'on n'a pas deja un bonus atmos via le probe (best_audio)
        best_codec_lower = str(best_audio.get("codec") or "").lower()
        if ("atmos" not in best_codec_lower) and ("dts:x" not in best_codec_lower) and ("dts-x" not in best_codec_lower):
            atmos_bonus = +3
            atmos_label = (
                "Atmos detecte dans le nom" if name_info.audio_is_atmos else "DTS:X detecte dans le nom"
            )
            audio_sub = max(0.0, min(100.0, float(audio_sub) + atmos_bonus))
            factors.append({"category": "audio", "delta": atmos_bonus, "label": atmos_label})
            reasons.append(f"+{atmos_bonus} {atmos_label}")

    # Fix audit 2026-05-25 (v1.5.5) Vague K : quand on s'appuie sur le nom
    # (probe FAILED ou PARTIAL), certaines penalites du scoring V1 sont
    # injustifiees (debit video non mesure, langue audio inconnue, metadata
    # absente) car elles refletent les LIMITES DU PROBE et non la qualite
    # reelle du fichier. On compense ces penalites pour que le score
    # reflete les hints du nom de release.
    if probe_quality == "FAILED" and name_filled_fields:
        # Compensation video : -8 "Debit non detecte" + base trop basse (8.0)
        # par rapport au cas normal ou le bitrate aurait ajoute ~10-18 pts.
        # On compense pour reconstituer un "bitrate correct" equivalent.
        video_sub = min(100.0, float(video_sub) + 28)
        # Compensation audio : la base de 10 ne reflete pas un fichier de
        # qualite. Si l'audio est lossless ET multicanal, on ajoute +32 pour
        # equivalent "TrueHD/DTS-HD MA + 7.1 + debit eleve". Sinon proportionnel.
        if "audio_track_synth" in name_filled_fields:
            if name_info.audio_is_lossless and name_info.audio_channels_hint in {"5.1", "7.1", "5.0", "6.1"}:
                audio_sub = min(100.0, float(audio_sub) + 32)
            elif name_info.audio_is_lossless:
                audio_sub = min(100.0, float(audio_sub) + 22)
            elif name_info.audio_channels_hint in {"5.1", "7.1"}:
                audio_sub = min(100.0, float(audio_sub) + 18)
            else:
                audio_sub = min(100.0, float(audio_sub) + 12)
        # Compensation extras : -18 (-10 metadata indisponibles + -8 extras
        # bonus FULL manquant). On annule entierement car le nom comble
        # une bonne partie des metadata.
        extras_sub = min(100.0, float(extras_sub) + 24)
        factors.append(
            {
                "category": "probe",
                "delta": 0,
                "label": "Compensation penalites probe (donnees du nom)",
            }
        )
        reasons.append("+0 Compensation penalites probe (subscores ajustes)")
        # Penalite d'incertitude residuelle (le nom n'est pas le probe).
        uncertainty_penalty = 5
        video_sub = max(0.0, float(video_sub) - uncertainty_penalty)
        factors.append(
            {"category": "probe", "delta": -uncertainty_penalty, "label": "Incertitude : probe absent"}
        )
        reasons.append(f"-{uncertainty_penalty} Incertitude : score base sur le nom de fichier seul")
    elif probe_quality == "PARTIAL" and name_filled_fields:
        # Compensation partielle : le probe a quand meme apporte qqch.
        if "audio_track_synth" in name_filled_fields:
            audio_sub = min(100.0, float(audio_sub) + 6)
            factors.append(
                {"category": "probe", "delta": 6, "label": "Compensation audio (synthese nom)"}
            )
            reasons.append("+6 Compensation audio (synthese depuis le nom)")
        # Compense le debit non mesure quand on n'a pas de bitrate.
        if not _to_int(video.get("bitrate"), 0):
            video_sub = min(100.0, float(video_sub) + 8)
            factors.append({"category": "probe", "delta": 8, "label": "Compensation debit non probe"})
            reasons.append("+8 Compensation debit video non mesure (probe partiel)")

    # --- Bonus/malus V4 contextuels (ere, encode, commentary) ---
    # Fix audit 2026-05-25 (v1.5.5) Vague K : derive la hauteur effective depuis
    # la resolution label (qui integre deja le fallback nom) pour que les
    # bonus d'ere s'appliquent meme sans probe.
    height = _to_int(video.get("height"), 0)
    if height <= 0 and vr.get("resolution_label"):
        height = _resolution_rank(vr["resolution_label"])
    video_codec_v4 = str(video.get("codec") or "").strip().lower()
    video_sub = _apply_era_bonuses_helper(
        film_year=film_year,
        height=height,
        video_codec=video_codec_v4,
        video_sub=video_sub,
        factors=factors,
        reasons=reasons,
    )
    video_sub = _apply_encode_warnings_helper(
        encode_warnings=encode_warnings,
        video_sub=video_sub,
        factors=factors,
        reasons=reasons,
    )
    audio_sub = _apply_commentary_penalty_helper(
        audio_analysis=audio_analysis,
        audio_sub=audio_sub,
        factors=factors,
        reasons=reasons,
    )

    # --- P4.2 : ajustements genre-aware TMDb ---
    video_sub, audio_sub, extras_sub, primary_genre = _apply_genre_adjustments_helper(
        tmdb_genres=tmdb_genres,
        video=video,
        audio_analysis=audio_analysis,
        encode_warnings=encode_warnings,
        video_sub=video_sub,
        audio_sub=audio_sub,
        extras_sub=extras_sub,
        factors=factors,
        reasons=reasons,
    )

    # --- Score pondere & tier ---
    score = _apply_weights(video_sub, audio_sub, extras_sub, prof["weights"])
    tier = _determine_tier(score, prof["tiers"])

    # --- Custom rules (G6) ---
    # Fix audit 2026-05-26 (v1.5.7) hotfix dataclass : on passe la variable LOCALE
    # 'probe' (deja convertie via _asdict en tete) au lieu de 'normalized_probe'
    # (parametre brut). Le bug critique: les regles custom ciblant edition/
    # duration_s/tmdb_in_collection ne s'appliquaient JAMAIS si caller passait
    # un NormalizedProbe (ex: ProbeService a l'avenir si conversion enlevee).
    score, tier, custom_flags_added, applied_rule_ids = _apply_custom_rules_helper(
        prof=prof,
        score=score,
        tier=tier,
        vr=vr,
        best_audio=best_audio,
        normalized_probe=probe,
        film_year=film_year,
        subtitle_info=subtitle_info,
        encode_warnings=encode_warnings,
        factors=factors,
        reasons=reasons,
    )

    # --- Fix audit 2026-05-26 (v1.5.6) Vague L (scoring-1) : CAP de tier ---
    # Decision senior conservatrice. Applique APRES custom rules pour etre la
    # derniere autorite : aucune regle / aucun bonus de nom ne peut certifier un
    # tier eleve si on n'a pas verifie le fichier (probe FAILED) ou si c'est une
    # captation degradee (CAM).
    if probe_quality == "FAILED":
        capped = _cap_tier(tier, "Silver")
        if capped != tier:
            reasons.append(
                f"Tier plafonne a Silver : probe indisponible, qualite non verifiee "
                f"(tier brut {tier} non certifiable sur le seul nom de fichier)"
            )
            factors.append(
                {"category": "probe", "delta": 0, "label": f"Cap probe FAILED: {tier} -> {capped}"}
            )
            tier = capped
    if cam_detected:
        # Une CAM/TS/Screener est plafonnee a Bronze maximum (jamais Silver+).
        capped = _cap_tier(tier, "Bronze")
        if capped != tier:
            reasons.append(f"Tier plafonne a Bronze : captation degradee ({name_info.cam_token.upper() or 'CAM'})")
            factors.append({"category": "video", "delta": 0, "label": f"Cap CAM: {tier} -> {capped}"})
            tier = capped

    # --- Probe quality reasons ---
    _append_probe_quality_reasons(probe, factors, reasons)

    # --- Confidence ---
    confidence_value, confidence_label, confidence_reasons = _compute_confidence_helper(
        probe_quality=probe_quality,
        vr=vr,
        audio_tracks=audio_tracks,
    )

    # --- Metrics ---
    # Fix audit 2026-05-26 (v1.5.7) hotfix dataclass : passer 'probe' (variable
    # locale deja convertie) au lieu de 'normalized_probe' (parametre brut).
    # Sinon detected.duration_s et detected.file_size_bytes etaient 0 quand le
    # caller transmettait un NormalizedProbe (impact UI Bibliotheque).
    metrics = _build_quality_metrics_helper(
        prof=prof,
        probe_quality=probe_quality,
        vr=vr,
        best_audio=best_audio,
        audio_tracks=audio_tracks,
        langs=langs,
        normalized_probe=probe,
        sources=sources,
        toggles=toggles,
        confidence_value=confidence_value,
        confidence_label=confidence_label,
        confidence_reasons=confidence_reasons,
        video_sub=video_sub,
        audio_sub=audio_sub,
        extras_sub=extras_sub,
        custom_flags_added=custom_flags_added,
        applied_rule_ids=applied_rule_ids,
        tmdb_genres=tmdb_genres,
        primary_genre=primary_genre,
    )

    # P2.1 : explanation enrichie — narrative + weighted_delta + categories + suggestions.
    rich = build_rich_explanation(
        score=int(score),
        tier=tier,
        factors=factors,
        subscores={"video": int(video_sub), "audio": int(audio_sub), "extras": int(extras_sub)},
        weights=prof.get("weights") or {},
        tier_thresholds=prof.get("tiers") or {},
    )
    metrics["score_explanation"] = rich
    logger.debug("scoring: score=%d tier=%s", score, tier)
    return {
        "score": int(score),
        "tier": tier,
        "reasons": reasons,
        "confidence": {"value": confidence_value, "label": confidence_label, "reasons": confidence_reasons},
        "explanation": rich,
        "metrics": metrics,
    }
