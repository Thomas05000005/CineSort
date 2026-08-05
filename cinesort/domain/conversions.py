"""Helpers de conversion tolerants — source unique pour tout le depot.

REGLE DE REVUE (grep-able) — sentinelle falsy
=============================================
Ne JAMAIS ecrire ``x or DEFAUT`` (ni ``if x and ...``) quand ``0``, ``0.0``,
``False`` ou ``""`` est une valeur METIER legitime distincte de "absent" :
Python evalue le falsy, pas l'absence, donc la valeur nulle voulue par
l'utilisateur est silencieusement remplacee par le defaut.

Utiliser a la place le helper de ce module, qui ne collapse que ``None`` et
l'invalide :

    to_int(value, default)     # 0 preserve, None/"" -> default
    to_float(value, default)
    to_bool(value, default)
    to_optional_int/float/bool/bitrate(value)   # None si absent

ou un test ``is None`` explicite.

Detection des recidives (le motif dangereux est le defaut NON NUL, car il
signifie qu'un 0 legitime serait ecrase) :

    grep -rnE "\\bor [1-9][0-9]*(\\.[0-9]+)?\\b" cinesort/ --include=*.py | grep -vE "\\bor 0"

Chaque hit doit etre justifie : soit ``0`` est impossible/insignifiant a cet
endroit, soit il faut passer par ``to_int``/``to_float``/``is None``.
Historique de la famille : #440, #611, #639, #698, #785, #791.
"""

from __future__ import annotations

import re
from typing import Any, Optional


def to_int(value: Any, default: int) -> int:
    """Convert *value* to int, returning *default* on failure.

    `OverflowError` fait partie du tuple, et c'est le meme piege que la regle 4
    du CLAUDE.md (`sqlite3.Error` n'herite pas d'`OSError`) : il derive
    d'`ArithmeticError`, PAS de `ValueError`. Le cas est ATTEIGNABLE parce que
    `json.loads` accepte `Infinity` et `NaN` par defaut (extension non
    standard), et que ce helper est nourri de valeurs persistees :

        int(float("nan"))  -> ValueError      (attrape de longue date)
        int(float("inf"))  -> OverflowError   (NON attrape avant ce correctif)

    Sans cette entree, ce helper — 100+ sites d'appel — laissait remonter
    l'exception au lieu de rendre `default`, ce qui contredit frontalement son
    contrat « returning default on failure ».
    """
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
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
            # `round(inf)` leve deja OverflowError, avant meme le `int()`.
            # Meme raison que dans `to_int` : OverflowError derive
            # d'ArithmeticError, pas de ValueError.
            return int(round(value))
        except (TypeError, ValueError, OverflowError):
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
    """Parse *value* en bool, retourne None si vide / non reconnu.

    Gardes de type en tete (comme to_bool / to_optional_int / to_optional_bitrate) :
    ``False`` et ``0`` sont des valeurs mesurees, pas des absences (#785).

    Ou la distinction ``None`` / ``False`` est OBSERVABLE (audit 2026-06-25) :
    ce helper est le delegue de
    ``cinesort.infra.probe._normalize_helpers._bool_from_text``, qui normalise le
    flag ``forced`` des pistes de sous-titres. ``_normalize_ffprobe.py`` arbitre
    ensuite ``bool(forced_tag) if forced_tag is not None else forced_disp`` : un
    tag ``forced`` numerique ``0`` doit rendre ``False`` — refus EXPLICITE, qui
    prime sur le bit de disposition — et non ``None``, qui reviendrait a se
    rabattre sur la disposition comme si le tag etait absent.
    (``_normalize_mediainfo.py``, lui, ecrase ``None`` en ``False`` : la
    distinction y est inerte.)
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # NaN n'est pas une mesure, c'est l'ABSENCE de mesure — or `bool(nan)`
        # vaut True en Python. Sans cette garde, un `forced` a NaN se lisait
        # « piste forcee », et le refus explicite decrit ci-dessus se
        # transformait en affirmation.
        #
        # Le chemin est reel : `json.loads('{"x": NaN}')` fonctionne par defaut
        # en Python, donc un sidecar ou une reponse d'outil externe peut en
        # produire. On rend None — l'appelant retombe alors sur le bit de
        # disposition, exactement comme quand le tag est absent.
        if value != value:  # noqa: PLR0124 - test NaN sans importer math
            return None
        return bool(value)
    s = str(value).strip().lower()
    if not s:
        return None
    if s in {"1", "true", "yes", "oui"}:
        return True
    if s in {"0", "false", "no", "non"}:
        return False
    return None
