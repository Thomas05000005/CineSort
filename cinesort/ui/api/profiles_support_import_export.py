"""VP-F (Vague P batch 6) — Quality profiles Import/Export & TRaSH presets.

Trois grandes families d'endpoints :

1. **Recyclarr YAML round-trip** : import/export de profils au format Recyclarr
   v6+ (`quality_profiles` + `custom_formats`). Lossless via lecture/ecriture
   d'un sous-ensemble strict de YAML (scalaires, listes, dicts) - PAS de
   dependance PyYAML (bundle taille = non prioritaire mais inutile ici).

2. **Preset TRaSH 2026 embarque** : `tier_preset_trash_2026.json` charge via
   importlib.resources (PyInstaller-friendly), inclut presets alternatifs
   (puriste DV, qualite max audio). DESACTIVE par defaut (AC-3 fix #4).

3. **Breakdown 5 axes** : Source / Codec / HDR / Audio / Group - structure
   exposable a la fonction d'audit qui affiche dans l'UI le poids effectif
   de chaque dimension (memo `feedback_cinesort_ui_pacotille` : eviter les
   fonctions backend invisibles dans l'UI).

Aucune signature de profiles_support.py existante n'est modifiee - VP-F est
strictement additif (AC-1 backward compat ABSOLUE).
"""

from __future__ import annotations

import contextlib
import copy
import json
import logging
from importlib import resources
from typing import Any, Dict, List, Optional, Tuple

from cinesort.domain import list_quality_presets, quality_profile_from_preset, validate_quality_profile
from cinesort.ui.api import profiles_support_crud as _crud
from cinesort.ui.api._responses import err

logger = logging.getLogger(__name__)


# Limites defensives (memo ROADMAP : protections contre payloads abusifs).
MAX_YAML_BYTES = 256 * 1024  # 256 KB
MAX_PROFILES_PER_IMPORT = 16
MAX_LINE_LENGTH = 4096

# Axes de la hierarchie "Quality Trumps All" exposes dans l'UI.
BREAKDOWN_AXES: Tuple[str, ...] = ("source", "codec", "hdr", "audio", "group")

# Defaut explicite : pas de plafond effectif (10000 = "jamais arreter d'upgrader").
DEFAULT_UPGRADE_UNTIL_SCORE = 10000


# ---------------------------------------------------------------------------
# Minimal YAML reader/writer (Recyclarr-compatible subset).
# ---------------------------------------------------------------------------
# Format supporte (suffisant pour quality_profiles + custom_formats Recyclarr) :
#
#   key: value          # scalar (str|int|float|bool|None)
#   key:                # mapping or sequence (suivant la suite)
#     subkey: value
#     subkey2:
#       - item1
#       - item2
#
# Lossless garanti uniquement pour ce sous-ensemble. Le round-trip restitue
# fidelement la structure si les valeurs sont des dict/list/str/int/float/bool.
# Pas de support : ancres (&), references (*), tags (!type), multilignes |>.


def _yaml_format_scalar(value: Any) -> str:
    """Serialise un scalaire en YAML safe (quotes si necessaire)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    # Quote si caracteres ambigus (start with #, :, -, contient ":", "{", "[")
    needs_quote = (
        not s
        or s[0] in "#&*!|>%@`'\""
        or s[0] in "-?:,[]{}"
        or any(c in s for c in [": ", " #", "\n", "\t"])
        or s.lower() in ("null", "true", "false", "yes", "no", "on", "off", "~")
    )
    try:
        # Test si pur numerique => doit etre quote pour rester string
        float(s)
        needs_quote = True
    except (TypeError, ValueError):
        pass
    if needs_quote:
        # Echappement des single-quotes par doublement (style YAML 1.1).
        return "'" + s.replace("'", "''") + "'"
    return s


def _yaml_dump_value(value: Any, indent: int = 0) -> str:
    """Serialise une valeur en YAML (recursif). Retourne la chaine multilignes."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines: List[str] = []
        for k, v in value.items():
            key_str = _yaml_format_scalar(k)
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{key_str}:")
                lines.append(_yaml_dump_value(v, indent + 1))
            else:
                lines.append(f"{pad}{key_str}: {_yaml_dump_value(v, indent + 1)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = []
        for item in value:
            if isinstance(item, (dict, list)) and item:
                # Indent du tiret + contenu
                rendered = _yaml_dump_value(item, indent + 1)
                # Rendu : le premier "- " precede la 1ere paire, le reste indente.
                first, *rest = rendered.split("\n", 1)
                first_clean = first.lstrip()
                lines.append(f"{pad}- {first_clean}")
                if rest:
                    lines.append(rest[0])
            else:
                lines.append(f"{pad}- {_yaml_format_scalar(item)}")
        return "\n".join(lines)
    return _yaml_format_scalar(value)


def yaml_dump(obj: Any) -> str:
    """API publique : serialise un dict/list Python en YAML Recyclarr-compatible."""
    rendered = _yaml_dump_value(obj, indent=0)
    if not rendered.endswith("\n"):
        rendered += "\n"
    return rendered


def _yaml_parse_scalar(raw: str) -> Any:
    """Parse un scalaire YAML (quotes, null, bool, int, float, str)."""
    s = raw.strip()
    if not s:
        return ""
    # Strip comments inline (apres un espace + #)
    if " #" in s:
        s = s.split(" #", 1)[0].rstrip()
    # Quoted string
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        inner = s[1:-1]
        if s[0] == "'":
            inner = inner.replace("''", "'")
        return inner
    low = s.lower()
    if low in ("null", "~", ""):
        return None
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        if "." in s or "e" in low:
            return float(s)
        return int(s)
    except (TypeError, ValueError):
        return s


def _detect_indent(line: str) -> int:
    """Retourne le nombre de chars d'indentation (espaces uniquement)."""
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        else:
            break
    return n


def _yaml_parse_lines(lines: List[str], start: int, base_indent: int) -> Tuple[Any, int]:
    """Parse recursif une suite de lignes YAML a partir de l'indent base.

    Retourne (parsed_value, next_line_idx).
    """
    # Detecter mapping vs sequence en regardant la 1ere ligne non-vide >= base_indent.
    i = start
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    if i >= len(lines):
        return None, i

    first_line = lines[i]
    indent = _detect_indent(first_line)
    if indent < base_indent:
        return None, i

    is_sequence = first_line[indent:].startswith("- ")

    if is_sequence:
        result_list: List[Any] = []
        while i < len(lines):
            line = lines[i]
            if not line.strip() or line.lstrip().startswith("#"):
                i += 1
                continue
            cur_indent = _detect_indent(line)
            if cur_indent < indent:
                break
            if cur_indent > indent:
                # Bloc imbrique d'un item precedent, on l'a deja consomme - skip.
                i += 1
                continue
            stripped = line[cur_indent:]
            if not stripped.startswith("- "):
                break
            inline = stripped[2:].strip()
            if not inline:
                # Item == bloc imbrique sur ligne suivante
                child, next_idx = _yaml_parse_lines(lines, i + 1, indent + 2)
                result_list.append(child)
                i = next_idx
                continue
            if ":" in inline and not (inline.startswith("'") or inline.startswith('"')):
                # Sequence d'items mapping inline ("- key: value")
                # On le traite comme un dict d'une seule cle, puis on aspire les
                # cles suivantes au meme niveau d'indent + 2.
                child_lines: List[str] = []
                # Reinjecter le contenu (sans "- ") avec indent + 2.
                pseudo_indent = " " * (indent + 2)
                child_lines.append(pseudo_indent + inline)
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if not nxt.strip() or nxt.lstrip().startswith("#"):
                        child_lines.append(nxt)
                        j += 1
                        continue
                    nxt_indent = _detect_indent(nxt)
                    if nxt_indent < indent + 2:
                        break
                    child_lines.append(nxt)
                    j += 1
                child, _ = _yaml_parse_lines(child_lines, 0, indent + 2)
                result_list.append(child if child is not None else {})
                i = j
                continue
            # Scalar inline
            result_list.append(_yaml_parse_scalar(inline))
            i += 1
        return result_list, i

    # Mapping
    result_map: Dict[str, Any] = {}
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        cur_indent = _detect_indent(line)
        if cur_indent < indent:
            break
        if cur_indent > indent:
            i += 1
            continue
        stripped = line[cur_indent:]
        if ":" not in stripped:
            break
        key_part, _sep, val_part = stripped.partition(":")
        key = key_part.strip()
        # Unquote la cle si necessaire
        if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
            key = key[1:-1]
        val_str = val_part.strip()
        if val_str:
            # Strip inline comment
            if " #" in val_str:
                val_str = val_str.split(" #", 1)[0].rstrip()
            if val_str in ("{}", "[]"):
                result_map[key] = {} if val_str == "{}" else []
            else:
                result_map[key] = _yaml_parse_scalar(val_str)
            i += 1
        else:
            # Bloc imbrique
            child, next_idx = _yaml_parse_lines(lines, i + 1, indent + 2)
            result_map[key] = child if child is not None else {}
            i = next_idx
    return result_map, i


def yaml_load(text: str) -> Any:
    """API publique : parse un document YAML (subset Recyclarr) -> dict/list Python."""
    if not isinstance(text, str):
        raise TypeError("yaml_load attend une str")
    if len(text.encode("utf-8")) > MAX_YAML_BYTES:
        raise ValueError(f"YAML trop volumineux (> {MAX_YAML_BYTES} octets).")
    # Strip BOM eventuel + normalise les fins de ligne.
    cleaned = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = cleaned.split("\n")
    safe_lines: List[str] = []
    for ln in raw_lines:
        if len(ln) > MAX_LINE_LENGTH:
            raise ValueError(f"Ligne YAML > {MAX_LINE_LENGTH} chars (refusee).")
        # Skip --- (document separator) et ... (end-of-document)
        if ln.strip() in ("---", "..."):
            continue
        safe_lines.append(ln)
    parsed, _ = _yaml_parse_lines(safe_lines, 0, 0)
    return parsed if parsed is not None else {}


# ---------------------------------------------------------------------------
# Recyclarr round-trip : CineSort profile <-> Recyclarr YAML
# ---------------------------------------------------------------------------


def _profile_to_recyclarr_dict(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Convertit un profil CineSort en structure Recyclarr (dict pret a yaml_dump).

    Recyclarr "quality_profile" attend principalement :
      - name (str)
      - upgrade { allowed: bool, until_quality: str, until_score: int }
      - min_format_score (int)
      - quality_sort (str, "top|bottom")
      - qualities (list)

    On encapsule l'ensemble du profile CineSort dans une cle "cinesort_profile"
    pour garantir le round-trip lossless meme si Recyclarr n'utilise pas tous
    les champs (les outils tiers ignorent les cles inconnues, lossless garanti).
    """
    if not isinstance(profile, dict):
        raise TypeError("_profile_to_recyclarr_dict attend un dict.")
    profile_id = str(profile.get("id") or "CineSort_Custom")
    upgrade_until = int(profile.get("upgrade_until_score") or DEFAULT_UPGRADE_UNTIL_SCORE)
    return {
        "quality_profiles": [
            {
                "name": profile_id,
                "upgrade": {
                    "allowed": True,
                    "until_quality": "Bluray-2160p Remux",
                    "until_score": upgrade_until,
                },
                "min_format_score": 0,
                "quality_sort": "top",
                "cinesort_profile": copy.deepcopy(profile),
            }
        ]
    }


def _recyclarr_dict_to_profile(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extrait un profil CineSort depuis une structure Recyclarr decodee.

    Strategie :
    1. Si la cle "cinesort_profile" est presente dans un quality_profile,
       retourner le payload directement (round-trip lossless).
    2. Sinon, construire un profil best-effort a partir des champs Recyclarr
       standards (lossy, mais utilisable comme point de depart).
    """
    if not isinstance(data, dict):
        return None
    profiles = data.get("quality_profiles") or []
    if not isinstance(profiles, list) or not profiles:
        return None

    first = profiles[0]
    if not isinstance(first, dict):
        return None

    cs_profile = first.get("cinesort_profile")
    if isinstance(cs_profile, dict) and cs_profile.get("id"):
        # Lossless restore - on copie pour eviter aliasing avec data parsee.
        restored = copy.deepcopy(cs_profile)
        # Synchronise upgrade_until_score si Recyclarr l'a modifie.
        upgrade = first.get("upgrade") or {}
        if isinstance(upgrade, dict) and "until_score" in upgrade:
            with contextlib.suppress(TypeError, ValueError):
                restored["upgrade_until_score"] = int(upgrade["until_score"])
        return restored

    # Fallback lossy : reconstruction approximative pour Recyclarr "natif".
    name = str(first.get("name") or "Imported_v1")
    upgrade = first.get("upgrade") or {}
    upgrade_until = DEFAULT_UPGRADE_UNTIL_SCORE
    if isinstance(upgrade, dict):
        try:
            upgrade_until = int(upgrade.get("until_score") or DEFAULT_UPGRADE_UNTIL_SCORE)
        except (TypeError, ValueError):
            upgrade_until = DEFAULT_UPGRADE_UNTIL_SCORE

    from cinesort.domain.quality_score import default_quality_profile

    base = default_quality_profile()
    base["id"] = name
    base["upgrade_until_score"] = upgrade_until
    return base


def export_recyclarr_yaml(api: Any, profile_id: Optional[str] = None) -> Dict[str, Any]:
    """Exporte le profil actif (ou le profil specifie) au format Recyclarr YAML.

    Args:
        api: instance CineSortApi.
        profile_id: optionnel - si fourni, exporte ce profil specifique (preset
            ou custom). Sinon le profil actif.

    Retourne {ok, yaml, profile_id, profile_version}.
    """
    try:
        profile_json: Optional[Dict[str, Any]] = None

        if profile_id:
            # Cherche dans presets puis custom.
            preset = quality_profile_from_preset(profile_id)
            if preset is not None:
                profile_json = preset
            if profile_json is None:
                for row in list_quality_presets(include_profiles=True):
                    row_profile = row.get("profile_json") or {}
                    if str(row_profile.get("id") or "") == profile_id:
                        profile_json = copy.deepcopy(row_profile)
                        break
            if profile_json is None:
                settings = _crud._read_settings_dict(api)
                for entry in settings.get("custom_quality_profiles") or []:
                    if isinstance(entry, dict) and str(entry.get("id") or "") == profile_id:
                        profile_json = copy.deepcopy(entry)
                        break
        else:
            payload = api._active_quality_profile_payload()
            profile_json = copy.deepcopy(payload.get("profile_json") or {})

        if not profile_json:
            return err(
                f"Profil introuvable : {profile_id or 'actif'}",
                category="resource",
                level="warning",
            )

        recyclarr_dict = _profile_to_recyclarr_dict(profile_json)
        yaml_text = yaml_dump(recyclarr_dict)

        return {
            "ok": True,
            "yaml": yaml_text,
            "profile_id": str(profile_json.get("id") or ""),
            "profile_version": int(profile_json.get("version") or 1),
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return err(f"export_recyclarr_yaml failed: {exc}", category="runtime", level="error")


def import_recyclarr_yaml(api: Any, yaml_text: str, *, activate: bool = False) -> Dict[str, Any]:
    """Importe un profil depuis YAML Recyclarr, le persiste comme custom profile.

    Args:
        api: instance CineSortApi.
        yaml_text: contenu YAML brut (string).
        activate: si True, active le profil immediatement apres import.

    Retourne {ok, profile_id, profile_version, lossy} ou lossy=True indique
    que le profil n'avait pas la cle cinesort_profile (reconstruction approximative).
    """
    try:
        if not isinstance(yaml_text, str) or not yaml_text.strip():
            return err(
                "YAML invalide : contenu vide.",
                category="validation",
                level="warning",
            )

        try:
            parsed = yaml_load(yaml_text)
        except (TypeError, ValueError) as parse_exc:
            return err(
                f"YAML invalide : {parse_exc}",
                category="validation",
                level="warning",
            )

        if not isinstance(parsed, dict):
            return err(
                "YAML invalide : structure racine attendue (dict).",
                category="validation",
                level="warning",
            )

        # Detect lossy (no cinesort_profile inside) AVANT extraction.
        lossy = True
        profiles = parsed.get("quality_profiles") or []
        if isinstance(profiles, list) and profiles and isinstance(profiles[0], dict):
            if isinstance(profiles[0].get("cinesort_profile"), dict):
                lossy = False
            # Borne defensive.
            if len(profiles) > MAX_PROFILES_PER_IMPORT:
                return err(
                    f"Trop de profils dans le YAML (max {MAX_PROFILES_PER_IMPORT}).",
                    category="validation",
                    level="warning",
                )

        profile_json = _recyclarr_dict_to_profile(parsed)
        if profile_json is None:
            return err(
                "Aucun profil trouve dans le YAML.",
                category="validation",
                level="warning",
            )

        # Validation finale.
        ok, errs, normalized = validate_quality_profile(profile_json)
        if not ok:
            return err(
                "Profil YAML rejete par la validation backend.",
                category="validation",
                level="warning",
                errors=errs,
            )

        # Persistance via le module CRUD (merge par id, replace si existant).
        save_result = _crud.save_profile(api, normalized)
        if not save_result.get("ok"):
            return save_result

        if activate:
            activate_result = _crud.set_active_profile(api, str(normalized.get("id") or ""))
            if not activate_result.get("ok"):
                return activate_result

        return {
            "ok": True,
            "profile_id": str(normalized.get("id") or ""),
            "profile_version": int(normalized.get("version") or 1),
            "lossy": lossy,
            "activated": bool(activate),
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return err(f"import_recyclarr_yaml failed: {exc}", category="runtime", level="error")


# ---------------------------------------------------------------------------
# Preset TRaSH 2026 embarque (AC-3 : DESACTIVE par defaut, fix #4)
# ---------------------------------------------------------------------------


_PRESET_CACHE: Optional[Dict[str, Any]] = None


def _load_trash_preset() -> Dict[str, Any]:
    """Charge tier_preset_trash_2026.json via importlib.resources (cached)."""
    global _PRESET_CACHE
    if _PRESET_CACHE is not None:
        return copy.deepcopy(_PRESET_CACHE)
    try:
        ref = resources.files("cinesort.data.presets").joinpath("tier_preset_trash_2026.json")
        text = ref.read_text(encoding="utf-8")
        _PRESET_CACHE = json.loads(text)
    except (OSError, ModuleNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("Impossible de charger tier_preset_trash_2026.json: %s", exc)
        _PRESET_CACHE = {}
    return copy.deepcopy(_PRESET_CACHE)


def get_embedded_presets(api: Any) -> Dict[str, Any]:  # noqa: ARG001
    """Retourne le preset TRaSH 2026 + alternatifs (puriste DV, qualite max audio).

    AC-3 : tous DESACTIVES par defaut (enabled_by_default=False, tier_hierarchy.enabled=False).
    L'utilisateur doit explicitement activer via l'UI ; le backend ne fait aucune
    mutation silencieuse au demarrage.

    Format reponse :
    {
      "ok": True,
      "presets": [
        {"preset_id": "trash_2026", "label": "...", "description": "...",
         "enabled_by_default": False, "upgrade_until_score": 10000,
         "tier_hierarchy": {...}, "trash_scoring": {...}},
        {"preset_id": "puriste_dv", ...},
        {"preset_id": "qualite_max_audio", ...},
      ],
    }
    """
    try:
        preset = _load_trash_preset()
        if not preset:
            return {"ok": True, "presets": []}

        out: List[Dict[str, Any]] = []

        # Preset principal TRaSH 2026.
        out.append(
            {
                "preset_id": str(preset.get("preset_id") or "trash_2026"),
                "label": str(preset.get("label") or "TRaSH 2026"),
                "description": str(preset.get("description") or ""),
                "enabled_by_default": bool(preset.get("enabled_by_default")),  # FALSE
                "upgrade_until_score": int(preset.get("upgrade_until_score") or DEFAULT_UPGRADE_UNTIL_SCORE),
                "tier_hierarchy": dict(preset.get("tier_hierarchy") or {}),
                "trash_scoring": dict(preset.get("trash_scoring") or {}),
            }
        )

        # Presets alternatifs (puriste DV, qualite max audio).
        alternatives = preset.get("alternative_presets") or {}
        if isinstance(alternatives, dict):
            for alt_id, alt_data in alternatives.items():
                if not isinstance(alt_data, dict):
                    continue
                out.append(
                    {
                        "preset_id": str(alt_id),
                        "label": str(alt_data.get("label") or alt_id),
                        "description": str(alt_data.get("description") or ""),
                        "enabled_by_default": False,  # AC-3 : tous OFF.
                        "upgrade_until_score": int(alt_data.get("upgrade_until_score") or DEFAULT_UPGRADE_UNTIL_SCORE),
                        "tier_hierarchy": dict(alt_data.get("tier_hierarchy") or {}),
                        "trash_scoring": dict(alt_data.get("trash_scoring") or {}),
                    }
                )

        return {"ok": True, "presets": out}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return err(f"get_embedded_presets failed: {exc}", category="runtime", level="error")


# ---------------------------------------------------------------------------
# upgrade_until_score (AC-5 : expose dans l'UI, default 10000)
# ---------------------------------------------------------------------------


def get_upgrade_until_score(api: Any) -> Dict[str, Any]:
    """Retourne le upgrade_until_score du profil actif (default 10000).

    Cf AC-5 : champ exposable via UI pour reduire le bruit decisionnel (au-dessus
    de ce score, l'UI n'affiche plus de recommandation "upgrade").
    """
    try:
        payload = api._active_quality_profile_payload()
        profile_json = payload.get("profile_json") or {}
        score = int(profile_json.get("upgrade_until_score") or DEFAULT_UPGRADE_UNTIL_SCORE)
        return {
            "ok": True,
            "upgrade_until_score": score,
            "profile_id": str(profile_json.get("id") or ""),
        }
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        return err(f"get_upgrade_until_score failed: {exc}", category="runtime", level="error")


def set_upgrade_until_score(api: Any, score: Any) -> Dict[str, Any]:
    """Met a jour le upgrade_until_score du profil actif.

    Borne [0..100000]. Persiste via _save_active_quality_profile (deep copy du
    profile_json + override du champ).
    """
    try:
        try:
            score_int = int(score)
        except (TypeError, ValueError):
            return err(
                f"upgrade_until_score invalide (int attendu, recu {score!r}).",
                category="validation",
                level="warning",
            )
        if score_int < 0 or score_int > 100000:
            return err(
                f"upgrade_until_score hors borne [0..100000] : {score_int}.",
                category="validation",
                level="warning",
            )

        payload = api._active_quality_profile_payload()
        profile_json = copy.deepcopy(payload.get("profile_json") or {})
        profile_json["upgrade_until_score"] = score_int

        ok, errs, normalized = validate_quality_profile(profile_json)
        if not ok:
            return err(
                "Profil rejete apres maj upgrade_until_score.",
                category="validation",
                level="warning",
                errors=errs,
            )
        api._save_active_quality_profile(normalized)
        return {
            "ok": True,
            "upgrade_until_score": score_int,
            "profile_id": str(normalized.get("id") or ""),
        }
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        return err(f"set_upgrade_until_score failed: {exc}", category="runtime", level="error")


# ---------------------------------------------------------------------------
# Breakdown 5 axes (AC-4 : Source / Codec / HDR / Audio / Group affiches dans UI)
# ---------------------------------------------------------------------------


def get_breakdown_5_axes(api: Any) -> Dict[str, Any]:
    """Retourne le breakdown 5 axes du profil actif pour affichage UI.

    Format :
    {
      "ok": True,
      "axes": [
        {"id": "source", "label": "Source", "weight": 1950, "details": {...}},
        {"id": "codec",  "label": "Codec",  "weight": 800,  "details": {...}},
        {"id": "hdr",    "label": "HDR",    "weight": 1200, "details": {...}},
        {"id": "audio",  "label": "Audio",  "weight": 5000, "details": {...}},
        {"id": "group",  "label": "Release group", "weight": 0, "details": {...}},
      ],
      "upgrade_until_score": 10000,
    }

    Le poids retourne est le score maximum theorique de l'axe dans le profil
    actif (utile pour comparer Visuellement l'impact relatif de chaque axe).
    Memo `feedback_cinesort_ui_pacotille` : eviter les fonctions backend invisibles.
    """
    try:
        payload = api._active_quality_profile_payload()
        profile_json = payload.get("profile_json") or {}

        labels = {
            "source": "Source",
            "codec": "Codec",
            "hdr": "HDR",
            "audio": "Audio",
            "group": "Release group",
        }

        axes_out: List[Dict[str, Any]] = []

        # Tente d'utiliser le scoring TRaSH si present (preset embarque).
        preset_data = _load_trash_preset()
        trash_scoring = preset_data.get("trash_scoring") or {}

        # Source : max des valeurs dans trash_scoring.source.
        source_scores = trash_scoring.get("source") or {}
        source_max = max([int(v) for v in source_scores.values() if isinstance(v, (int, float))] or [0])

        # Codec : profile.codec_bonuses (max) ou trash_scoring.codec.
        codec_bonuses = profile_json.get("codec_bonuses") or {}
        codec_max_profile = max([int(v) for v in codec_bonuses.values() if isinstance(v, (int, float))] or [0])
        codec_scores = trash_scoring.get("codec") or {}
        codec_max_trash = max([int(v) for v in codec_scores.values() if isinstance(v, (int, float))] or [0])
        codec_max = max(codec_max_profile, codec_max_trash)

        # HDR : profile.hdr_bonuses ou trash_scoring.hdr.
        hdr_bonuses = profile_json.get("hdr_bonuses") or {}
        hdr_max_profile = max([int(v) for v in hdr_bonuses.values() if isinstance(v, (int, float))] or [0])
        hdr_scores = trash_scoring.get("hdr") or {}
        hdr_max_trash = max([int(v) for v in hdr_scores.values() if isinstance(v, (int, float))] or [0])
        hdr_max = max(hdr_max_profile, hdr_max_trash)

        # Audio : profile.audio_bonuses ou trash_scoring.audio.
        audio_bonuses = profile_json.get("audio_bonuses") or {}
        audio_max_profile = 0
        for v in audio_bonuses.values():
            if isinstance(v, (int, float)):
                audio_max_profile = max(audio_max_profile, int(v))
            elif isinstance(v, dict):
                inner_max = max([int(x) for x in v.values() if isinstance(x, (int, float))] or [0])
                audio_max_profile = max(audio_max_profile, inner_max)
        audio_scores = trash_scoring.get("audio") or {}
        audio_max_trash = max([int(v) for v in audio_scores.values() if isinstance(v, (int, float))] or [0])
        audio_max = max(audio_max_profile, audio_max_trash)

        # Group : pas de champ profile dedie ; utilise tier_hierarchy.group_floors si present.
        group_floors = (profile_json.get("tier_hierarchy") or {}).get("group_floors") or {}
        group_max = 0
        if isinstance(group_floors, dict):
            # Compte le nombre de regles (proxy de poids).
            group_max = len(group_floors)

        weights = {
            "source": source_max,
            "codec": codec_max,
            "hdr": hdr_max,
            "audio": audio_max,
            "group": group_max,
        }

        for axis_id in BREAKDOWN_AXES:
            details_obj: Dict[str, Any] = {}
            if axis_id == "source":
                details_obj = dict(source_scores)
            elif axis_id == "codec":
                details_obj = {"profile_bonuses": dict(codec_bonuses), "trash_scoring": dict(codec_scores)}
            elif axis_id == "hdr":
                details_obj = {"profile_bonuses": dict(hdr_bonuses), "trash_scoring": dict(hdr_scores)}
            elif axis_id == "audio":
                details_obj = {"profile_bonuses": dict(audio_bonuses), "trash_scoring": dict(audio_scores)}
            elif axis_id == "group":
                details_obj = {"group_floors": dict(group_floors)}

            axes_out.append(
                {
                    "id": axis_id,
                    "label": labels[axis_id],
                    "weight": weights[axis_id],
                    "details": details_obj,
                }
            )

        return {
            "ok": True,
            "axes": axes_out,
            "upgrade_until_score": int(profile_json.get("upgrade_until_score") or DEFAULT_UPGRADE_UNTIL_SCORE),
            "profile_id": str(profile_json.get("id") or ""),
        }
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        return err(f"get_breakdown_5_axes failed: {exc}", category="runtime", level="error")
