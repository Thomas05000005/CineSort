from __future__ import annotations

import re
from typing import Any, Optional


def to_int(value: Any, default: int) -> int:
    """Convert *value* to int, returning *default* on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def to_float(value: Any, default: float) -> float:
    """Convert *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def to_bool(value: Any, default: bool) -> bool:
    """Convert *value* to bool with French/English text support."""
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    txt = str(value).strip().lower()
    if not txt:
        return bool(default)
    if txt in {"1", "true", "yes", "on", "y", "oui"}:
        return True
    if txt in {"0", "false", "no", "off", "n", "non"}:
        return False
    return bool(default)


# --- M-04 Vague M : variantes Optional pour deduplication helpers normalize.py ---
# Les helpers _to_int / _to_float / _to_bitrate_int / _bool_from_text de
# cinesort.infra.probe.normalize partagent la meme logique mais renvoient None
# plutot qu'un default. Centralisation ici pour eliminer la duplication.

# Pre-compiled regex patterns for to_optional_int number parsing (hot loops).
_GROUPED_NUMBER_RE = re.compile(r"(\d{1,3}(?:[ \t,\.]\d{3})+)")
_GROUP_SEP_RE = re.compile(r"[ \t,\.]")
_FIRST_DIGITS_RE = re.compile(r"\d+")
_BITRATE_UNIT_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*(gb/s|gbit/s|gib/s|mb/s|mbit/s|mib/s|kb/s|kbit/s|kib/s)")


def to_optional_float(value: Any) -> Optional[float]:
    """Parse *value* en float, retourne None si vide / invalide.

    Accepte virgule decimale ("1,5" -> 1.5). Pas de fallback default.
    """
    if value is None:
        return None
    s = str(value).strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def to_optional_int(value: Any) -> Optional[int]:
    """Parse *value* en int, retourne None si vide / invalide.

    Accepte les nombres groupes ("3 840", "12,500,000", "12.500.000") et
    extrait la premiere sequence de chiffres en fallback.
    """
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
    s_clean = s.replace(" ", " ").strip()
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


def to_optional_bitrate(value: Any) -> Optional[int]:
    """Parse *value* en bitrate (bits/s), retourne None si vide / invalide.

    Accepte les unites usuelles : Gb/s, Mb/s, Kb/s (binaire et decimal).
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    s = str(value or "").strip().lower().replace(" ", " ")
    if not s:
        return None
    unit_m = _BITRATE_UNIT_RE.search(s)
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
    return to_optional_int(s)


def to_optional_bool(value: Any) -> Optional[bool]:
    """Parse *value* en bool, retourne None si vide / non reconnu."""
    s = str(value or "").strip().lower()
    if not s:
        return None
    if s in {"1", "true", "yes", "oui"}:
        return True
    if s in {"0", "false", "no", "non"}:
        return False
    return None
