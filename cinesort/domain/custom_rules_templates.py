"""Templates starter pour regles custom (TRaSH-like, Puriste, Casual)."""

from __future__ import annotations

from typing import Any, Dict, List

TEMPLATE_TRASH: List[Dict[str, Any]] = [
    {
        "id": "trash_xvid",
        "name": "Penaliser codecs obsoletes",
        "description": "xvid / divx / wmv / mpeg4 perdent 15 points.",
        "enabled": True,
        "priority": 10,
        "conditions": [
            {"field": "video_codec", "op": "in", "value": ["xvid", "divx", "wmv", "mpeg4"]},
        ],
        "match": "all",
        "action": {"type": "score_delta", "value": -15, "reason": "Codec obsolete"},
    },
    {
        "id": "trash_4k_dv",
        "name": "Bonus 4K Dolby Vision",
        "description": "4K + Dolby Vision gagne 8 points.",
        "enabled": True,
        "priority": 20,
        "conditions": [
            {"field": "resolution_rank", "op": ">=", "value": 3},
            {"field": "has_dv", "op": "=", "value": True},
        ],
        "match": "all",
        "action": {"type": "score_delta", "value": 8, "reason": "Premium 4K HDR Dolby Vision"},
    },
    {
        "id": "trash_hdr10p",
        "name": "Bonus HDR10+",
        "description": "Gain de 5 points pour HDR10+.",
        "enabled": True,
        "priority": 21,
        "conditions": [
            {"field": "has_hdr10p", "op": "=", "value": True},
        ],
        "match": "all",
        "action": {"type": "score_delta", "value": 5, "reason": "HDR10+"},
    },
    {
        "id": "trash_sd_cap",
        "name": "Cap SD a 65",
        "description": "Un fichier SD ne peut pas depasser 65.",
        "enabled": True,
        "priority": 30,
        "conditions": [
            {"field": "resolution_rank", "op": "<=", "value": 0},
        ],
        "match": "all",
        "action": {"type": "cap_max", "value": 65, "reason": "SD plafonne"},
    },
    {
        "id": "trash_patrimoine",
        "name": "Bonus films patrimoine",
        "description": "Pre-1970 : +6 points.",
        "enabled": False,
        "priority": 40,
        "conditions": [
            {"field": "year", "op": "<=", "value": 1970},
        ],
        "match": "all",
        "action": {"type": "score_delta", "value": 6, "reason": "Film patrimoine"},
    },
]

TEMPLATE_PURIST: List[Dict[str, Any]] = [
    {
        "id": "purist_no_xvid",
        "name": "Rejet codecs obsoletes",
        "description": "xvid / divx / mpeg4 / wmv plafonnes a 50.",
        "enabled": True,
        "priority": 1,
        "conditions": [
            {"field": "video_codec", "op": "in", "value": ["xvid", "divx", "mpeg4", "wmv"]},
        ],
        "match": "all",
        "action": {"type": "cap_max", "value": 50, "reason": "Codecs obsoletes plafonnes"},
    },
    {
        "id": "purist_hi_bitrate",
        "name": "Exigence bitrate 1080p HEVC",
        "description": "1080p HEVC < 3000 kbps : -10.",
        "enabled": True,
        "priority": 10,
        "conditions": [
            {"field": "resolution", "op": "=", "value": "1080p"},
            {"field": "video_codec", "op": "=", "value": "hevc"},
            {"field": "bitrate_kbps", "op": "<", "value": 3000},
        ],
        "match": "all",
        "action": {"type": "score_delta", "value": -10, "reason": "Bitrate HEVC 1080p insuffisant"},
    },
    {
        "id": "purist_no_sd",
        "name": "SD toujours Reject",
        "description": "SD force en tier Reject.",
        "enabled": True,
        "priority": 20,
        "conditions": [
            {"field": "resolution_rank", "op": "=", "value": 0},
        ],
        "match": "all",
        "action": {"type": "force_tier", "value": "Reject", "reason": "Puriste : SD = Reject"},
    },
]

TEMPLATE_CASUAL: List[Dict[str, Any]] = [
    {
        "id": "casual_boost_fr",
        "name": "Bonus sous-titres FR",
        "description": "Sous-titres FR : +3.",
        "enabled": True,
        "priority": 10,
        "conditions": [
            {"field": "subtitle_langs", "op": "contains", "value": "fr"},
        ],
        "match": "all",
        "action": {"type": "score_delta", "value": 3, "reason": "Sous-titres FR"},
    },
    {
        "id": "casual_floor",
        "name": "Plancher a 50",
        "description": "Score tolerant : plancher a 50.",
        "enabled": True,
        "priority": 20,
        "conditions": [
            {"field": "audio_codec", "op": "!=", "value": ""},
        ],
        "match": "all",
        "action": {"type": "cap_min", "value": 50, "reason": "Plancher tolerant"},
    },
    {
        "id": "casual_720p_ok",
        "name": "720p acceptable",
        "description": "720p : +3.",
        "enabled": True,
        "priority": 30,
        "conditions": [
            {"field": "resolution", "op": "=", "value": "720p"},
        ],
        "match": "all",
        "action": {"type": "score_delta", "value": 3, "reason": "720p OK"},
    },
]

TEMPLATES: Dict[str, Dict[str, Any]] = {
    "trash_like": {
        "name": "TRaSH-like (equilibre)",
        "description": "Inspire des TRaSH Guides Radarr : penalise les codecs obsoletes, valorise 4K HDR.",
        "rules": TEMPLATE_TRASH,
    },
    "purist": {
        "name": "Puriste",
        "description": "Exigence maximale pour amateurs de qualite : SD force Reject, HEVC 1080p exige.",
        "rules": TEMPLATE_PURIST,
    },
    "casual": {
        "name": "Casual",
        "description": "Tolerant, oriente streaming : plancher 50, bonus VF, 720p OK.",
        "rules": TEMPLATE_CASUAL,
    },
}


def get_template(name: str) -> Dict[str, Any]:
    """Retourne le template par son id, ou dict vide si inconnu."""
    tpl = TEMPLATES.get(str(name or ""))
    if not tpl:
        return {}
    # Copie defensive
    import copy

    return {
        "id": name,
        "name": tpl["name"],
        "description": tpl["description"],
        "rules": copy.deepcopy(tpl["rules"]),
    }


def list_templates() -> list:
    """Retourne les 3 templates pour l'endpoint API."""
    import copy

    return [
        {
            "id": tid,
            "name": tpl["name"],
            "description": tpl["description"],
            "rules": copy.deepcopy(tpl["rules"]),
        }
        for tid, tpl in TEMPLATES.items()
    ]
