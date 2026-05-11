from __future__ import annotations

from typing import Any


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
