"""Moteur de regles custom pour scoring qualite (G6).

Whitelist stricte : pas d'eval, pas d'importation dynamique.
17 fields, 11 operators, 7 actions. Max 50 regles x 10 conditions par profil.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Limites DoS
MAX_RULES_PER_PROFILE = 50
MAX_CONDITIONS_PER_RULE = 10
MAX_STRING_LEN = 64
MAX_REASON_LEN = 120
MAX_RULES_JSON_BYTES = 8000

# --- Fields whitelist --------------------------------------------------------
# Chaque entree mappe (section, key) dans le contexte {detected, __context__, __computed__}.
FIELD_PATHS: Dict[str, Tuple[str, str]] = {
    "video_codec": ("detected", "video_codec"),
    "audio_codec": ("detected", "audio_best_codec"),
    "resolution": ("detected", "resolution"),
    "resolution_rank": ("__computed__", "resolution_rank"),
    "year": ("__context__", "year"),
    "bitrate_kbps": ("detected", "bitrate_kbps"),
    "audio_channels": ("detected", "audio_best_channels"),
    "has_hdr10": ("detected", "hdr10"),
    "has_hdr10p": ("detected", "hdr10_plus"),
    "has_dv": ("detected", "hdr_dolby_vision"),
    "subtitle_count": ("__context__", "subtitle_count"),
    "subtitle_langs": ("__context__", "subtitle_languages"),
    "warning_flags": ("__context__", "warning_flags"),
    "edition": ("__context__", "edition"),
    "tier_before": ("__computed__", "tier_before"),
    "score_before": ("__computed__", "score_before"),
    "file_size_gb": ("__computed__", "file_size_gb"),
    "duration_s": ("__context__", "duration_s"),
    "tmdb_in_collection": ("__computed__", "tmdb_in_collection"),
}


# --- Operators ---------------------------------------------------------------
def _num(x: Any) -> float:
    try:
        return float(x if x is not None else 0)
    except (TypeError, ValueError):
        return 0.0


def _op_eq(a, v):
    return a == v


def _op_ne(a, v):
    return a != v


def _op_lt(a, v):
    return _num(a) < _num(v)


def _op_le(a, v):
    return _num(a) <= _num(v)


def _op_gt(a, v):
    return _num(a) > _num(v)


def _op_ge(a, v):
    return _num(a) >= _num(v)


def _op_in(a, v):
    if not isinstance(v, list):
        return False
    return a in v


def _op_nin(a, v):
    if not isinstance(v, list):
        return True
    return a not in v


def _op_between(a, v):
    if not (isinstance(v, list) and len(v) == 2):
        return False
    # Normalisation defensive : si l'utilisateur fournit [100, 10] (bornes
    # inversees), on les trie pour matcher l'intention (entre 10 et 100).
    # Avant ce fix, la regle echouait silencieusement sur toutes les valeurs.
    # Cf issue #30 + principle of least surprise (POLS, prompt v3 cat 45).
    lo, hi = sorted([_num(v[0]), _num(v[1])])
    return lo <= _num(a) <= hi


def _op_contains(a, v):
    if isinstance(a, list):
        return v in a
    if isinstance(a, str):
        return str(v) in a
    return False


def _op_ncontains(a, v):
    return not _op_contains(a, v)


OPERATORS = {
    "=": _op_eq,
    "!=": _op_ne,
    "<": _op_lt,
    "<=": _op_le,
    ">": _op_gt,
    ">=": _op_ge,
    "between": _op_between,
    "in": _op_in,
    "not_in": _op_nin,
    "contains": _op_contains,
    "not_contains": _op_ncontains,
}


# --- Actions -----------------------------------------------------------------
# Sentinel pour distinguer "absent/invalide" de "0" dans les conversions numeriques.
_MISSING = object()


def _num_strict(x: Any):
    """Convertit en float, ou retourne _MISSING si non-numerique.

    Contrairement a _num (qui retourne 0.0 silencieusement), permet aux
    appelants de detecter les valeurs invalides. bool est rejete car bool
    est une sous-classe de int en Python et causerait des conversions
    surprenantes (True -> 1.0).
    """
    if x is None or isinstance(x, bool):
        return _MISSING
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x.strip())
        except (TypeError, ValueError):
            return _MISSING
    return _MISSING


def _clamp(x: Any) -> int:
    """Clamp [0, 100] avec arrondi (pas troncature).

    Bug fix mega-hotfix #2 (L130-134): int(0.9) -> 0 perdait l'intention
    utilisateur. round() preserve la valeur la plus proche. Non-numerique
    retourne 0 (comportement historique pour backward compat).
    """
    num = _num_strict(x)
    if num is _MISSING:
        return 0
    try:
        return max(0, min(100, int(round(num))))
    except (TypeError, ValueError, OverflowError):
        return 0


def _act_score_delta(result, value, reason):
    num = _num_strict(value)
    if num is _MISSING:
        return
    # Round pour preserver +0.9 -> +1 plutot que +0.9 -> 0 (mega-hotfix #2)
    delta = int(round(num))
    result["score"] = _clamp(result["score"] + delta)
    if reason:
        sign = "+" if delta >= 0 else ""
        result["reasons"].append(f"{sign}{delta} {reason}")


def _act_score_mult(result, value, reason):
    num = _num_strict(value)
    if num is _MISSING:
        return
    factor = num
    # Round pour eviter truncation (mega-hotfix #2)
    new = int(round(result["score"] * factor))
    result["score"] = _clamp(new)
    if reason:
        result["reasons"].append(f"x{factor} {reason}")


def _act_force_score(result, value, reason):
    # _clamp gere maintenant le rounding et la validation (mega-hotfix #2)
    # Bug fix: refuser silencieusement les valeurs non-numeriques au lieu de
    # forcer le score a 0 (ce qui ferait tomber tout film en Reject sans
    # avertissement). On preserve le score existant et on logge un warning.
    if _num_strict(value) is _MISSING:
        logger.warning("custom_rules: force_score ignored, non-numeric value=%r", value)
        return
    new = _clamp(value)
    result["score"] = new
    if reason:
        result["reasons"].append(f"={new} {reason}")


def _act_force_tier(result, value, reason):
    # Normalisation defensive : seul un tier canonique connu
    # (Platinum/Gold/Silver/Bronze/Reject) est accepte. Une chaine inconnue
    # serait propagee jusqu'au consommateur UI et bypasserait les invariants
    # de _cap_tier (probe FAILED <= Silver, CAM <= Bronze). Import local pour
    # eviter un cycle avec quality_score.
    from .tiers_helpers import normalize_tier_string

    tier = normalize_tier_string(value)
    if tier:
        result["force_tier"] = tier
        if reason:
            result["reasons"].append(f">{tier} {reason}")
    else:
        logger.warning("custom_rules: force_tier ignored, invalid tier=%r", value)


def _act_cap_max(result, value, reason):
    cap = _clamp(value)
    if result["score"] > cap:
        result["score"] = cap
        if reason:
            result["reasons"].append(f"cap<={cap} {reason}")


def _act_cap_min(result, value, reason):
    cap = _clamp(value)
    if result["score"] < cap:
        result["score"] = cap
        if reason:
            result["reasons"].append(f"cap>={cap} {reason}")


def _act_flag(result, value, reason):
    flag = str(value or "").strip()
    if not flag:
        return
    if flag not in result["flags_added"]:
        result["flags_added"].append(flag)
    if reason:
        result["reasons"].append(f"! {reason}")


ACTIONS = {
    "score_delta": _act_score_delta,
    "score_multiplier": _act_score_mult,
    "force_score": _act_force_score,
    "force_tier": _act_force_tier,
    "cap_max": _act_cap_max,
    "cap_min": _act_cap_min,
    "flag_warning": _act_flag,
}


# --- Evaluator ---------------------------------------------------------------
def _get_field_value(field: str, context: Dict[str, Any]) -> Any:
    if field not in FIELD_PATHS:
        return None
    section, key = FIELD_PATHS[field]
    src = context.get(section)
    if not isinstance(src, dict):
        return None
    return src.get(key)


def _eval_condition(cond: Dict[str, Any], context: Dict[str, Any]) -> bool:
    if not isinstance(cond, dict):
        return False
    field = cond.get("field")
    op = cond.get("op")
    if field not in FIELD_PATHS or op not in OPERATORS:
        return False
    actual = _get_field_value(field, context)
    value = cond.get("value")
    try:
        return bool(OPERATORS[op](actual, value))
    except (TypeError, ValueError) as exc:
        logger.debug("custom_rules: eval error field=%s op=%s value=%r err=%s", field, op, value, exc)
        return False


def evaluate_rule(rule: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """True si la regle matche (tous ou au moins un, selon match)."""
    conditions = rule.get("conditions") or []
    if not isinstance(conditions, list) or not conditions:
        return False
    match_mode = str(rule.get("match") or "all").lower()
    reducer = all if match_mode == "all" else any
    return reducer(_eval_condition(c, context) for c in conditions)


# --- Application -------------------------------------------------------------
def apply_custom_rules(
    initial_score: int,
    context: Dict[str, Any],
    rules: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Applique les regles dans l'ordre de priorite (asc).

    Retourne dict {score, flags_added, reasons, applied_rule_ids, force_tier}.
    """
    result: Dict[str, Any] = {
        "score": _clamp(initial_score),
        "flags_added": [],
        "reasons": [],
        "applied_rule_ids": [],
        "force_tier": None,
    }
    if not rules or not isinstance(rules, list):
        return result
    active = [r for r in rules if isinstance(r, dict) and r.get("enabled", True)]

    # Tri stable: priorite numerique en cle primaire, ordre d'apparition en cle
    # secondaire. _num_strict retourne _MISSING pour non-numerique (ex: "abc")
    # -> on tombe alors sur une priorite tres grande pour deprioriser ces
    # regles mal formees (mega-hotfix #1, defense en profondeur si la
    # validation est court-circuitee).
    def _priority_key(r):
        p = _num_strict(r.get("priority"))
        return float("inf") if p is _MISSING else p

    active.sort(key=_priority_key)
    for rule in active:
        try:
            if not evaluate_rule(rule, context):
                continue
        except (TypeError, ValueError, KeyError) as exc:
            logger.warning("custom_rules: evaluate crash rule=%s err=%s", rule.get("id"), exc)
            continue
        action = rule.get("action") or {}
        atype = action.get("type")
        if atype not in ACTIONS:
            continue
        reason = str(action.get("reason") or "")[:MAX_REASON_LEN]
        try:
            ACTIONS[atype](result, action.get("value"), reason)
        except (TypeError, ValueError) as exc:
            logger.warning("custom_rules: action crash rule=%s action=%s err=%s", rule.get("id"), atype, exc)
            continue
        result["applied_rule_ids"].append(str(rule.get("id") or ""))
        logger.debug("custom_rules: matched rule=%s action=%s score=%s", rule.get("id"), atype, result["score"])
    return result


# --- Validation --------------------------------------------------------------
def _truncate_str(val: Any, limit: int = MAX_STRING_LEN) -> str:
    return str(val or "")[:limit]


def _validate_condition(cond: Any, rule_idx: int, cond_idx: int) -> Tuple[bool, List[str], Dict[str, Any]]:
    errs: List[str] = []
    if not isinstance(cond, dict):
        return False, [f"Regle {rule_idx + 1}: condition {cond_idx + 1} invalide (objet attendu)"], {}
    field = cond.get("field")
    op = cond.get("op")
    if field not in FIELD_PATHS:
        errs.append(f"Regle {rule_idx + 1}: field '{field}' inconnu")
    if op not in OPERATORS:
        errs.append(f"Regle {rule_idx + 1}: operateur '{op}' inconnu")
    value = cond.get("value")
    if op in ("between",) and not (isinstance(value, list) and len(value) == 2):
        errs.append(f"Regle {rule_idx + 1}: 'between' attend une liste [min, max]")
    if op in ("in", "not_in") and not isinstance(value, list):
        errs.append(f"Regle {rule_idx + 1}: '{op}' attend une liste")
    if errs:
        return False, errs, {}
    norm = {"field": str(field), "op": str(op), "value": value}
    return True, [], norm


def _validate_action(action: Any, rule_idx: int) -> Tuple[bool, List[str], Dict[str, Any]]:
    errs: List[str] = []
    if not isinstance(action, dict):
        return False, [f"Regle {rule_idx + 1}: action manquante"], {}
    atype = action.get("type")
    if atype not in ACTIONS:
        errs.append(f"Regle {rule_idx + 1}: type d'action '{atype}' inconnu")
        return False, errs, {}
    value = action.get("value")
    # Validation amont pour force_tier : refus du profil si tier inconnu
    # (sinon bypass de _cap_tier downstream, cf invariants probe FAILED/CAM).
    if atype == "force_tier":
        from .tiers_helpers import normalize_tier_string

        canonical = normalize_tier_string(value)
        if not canonical:
            errs.append(
                f"Regle {rule_idx + 1}: force_tier value '{value}' inconnu (attendu Platinum/Gold/Silver/Bronze/Reject)"
            )
            return False, errs, {}
        # Stocke la forme canonique uniquement
        value = canonical
    reason = _truncate_str(action.get("reason"), MAX_REASON_LEN)
    return True, [], {"type": atype, "value": value, "reason": reason}


def _validate_single_rule(rule: Any, idx: int) -> Tuple[bool, List[str], Dict[str, Any]]:
    errs: List[str] = []
    if not isinstance(rule, dict):
        return False, [f"Regle {idx + 1}: objet attendu"], {}
    conditions = rule.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        errs.append(f"Regle {idx + 1}: au moins une condition requise")
    elif len(conditions) > MAX_CONDITIONS_PER_RULE:
        errs.append(f"Regle {idx + 1}: trop de conditions ({len(conditions)} > {MAX_CONDITIONS_PER_RULE})")
    action = rule.get("action")
    norm_conds: List[Dict[str, Any]] = []
    if isinstance(conditions, list):
        for ci, c in enumerate(conditions[:MAX_CONDITIONS_PER_RULE]):
            ok_c, errs_c, norm_c = _validate_condition(c, idx, ci)
            if not ok_c:
                errs.extend(errs_c)
            else:
                norm_conds.append(norm_c)
    ok_a, errs_a, norm_action = _validate_action(action, idx)
    if not ok_a:
        errs.extend(errs_a)
    # Bug fix mega-hotfix #1: priority doit etre numerique. Avant, int(_num(x))
    # transformait silencieusement "abc" en 0 -> ordre de tri imprevisible.
    # Priority absente reste tolere (default 0, backward compat).
    raw_priority = rule.get("priority")
    if raw_priority is None:
        priority_val = 0
    else:
        p_num = _num_strict(raw_priority)
        if p_num is _MISSING:
            errs.append(f"Regle {idx + 1}: priority doit etre numerique (recu {raw_priority!r})")
            priority_val = 0
        else:
            priority_val = int(round(p_num))
    if errs:
        return False, errs, {}
    normalized: Dict[str, Any] = {
        "id": _truncate_str(rule.get("id") or f"rule_{idx}", MAX_STRING_LEN),
        "name": _truncate_str(rule.get("name") or "Regle sans nom", MAX_STRING_LEN),
        "description": _truncate_str(rule.get("description"), MAX_REASON_LEN),
        "enabled": bool(rule.get("enabled", True)),
        "priority": priority_val,
        "conditions": norm_conds,
        "match": "any" if str(rule.get("match") or "all").lower() == "any" else "all",
        "action": norm_action,
    }
    return True, [], normalized


def _raw_size_estimate(obj: Any, budget: int) -> int:
    """Estime la taille serialisee sans materialiser le JSON complet.

    Utilise pour bailer tot sur payload adversarial (mega-hotfix #3). Bailout
    des que budget atteint pour eviter de scanner une structure enorme.
    Retourne la consommation au point d'arret (>= budget si depasse).
    """
    used = 0
    stack: List[Any] = [obj]
    while stack and used < budget:
        cur = stack.pop()
        if isinstance(cur, str):
            # encode utf-8 cost approx: 1-4 bytes/char, on prend len(s) + marge
            used += len(cur.encode("utf-8")) + 2  # +2 pour les guillemets
        elif isinstance(cur, bool):
            used += 5  # "true"/"false"
        elif isinstance(cur, (int, float)):
            used += 16  # majorant raisonnable pour repr numerique
        elif cur is None:
            used += 4  # "null"
        elif isinstance(cur, dict):
            used += 2 + len(cur)  # accolades + virgules/colons
            for k, v in cur.items():
                stack.append(k)
                stack.append(v)
                if used >= budget:
                    break
        elif isinstance(cur, list):
            used += 2 + len(cur)  # crochets + virgules
            for v in cur:
                stack.append(v)
                if used >= budget:
                    break
        else:
            # type inconnu : refus en aval par json.dumps, on compte une marge
            used += 32
    return used


def validate_rules(rules: Any) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
    """Valide une liste de regles. Retourne (ok, errors, normalized)."""
    if not isinstance(rules, list):
        return False, ["custom_rules doit etre une liste"], []
    if len(rules) > MAX_RULES_PER_PROFILE:
        return False, [f"Trop de regles ({len(rules)} > {MAX_RULES_PER_PROFILE})"], []
    # Bug fix mega-hotfix #3: check taille brute AVANT json.dumps + AVANT
    # validate_rules per-rule. Une estimation rapide permet de rejeter les
    # payloads adversariaux sans materialiser un JSON gigantesque, et avant de
    # faire tout le travail de normalisation par regle.
    if _raw_size_estimate(rules, MAX_RULES_JSON_BYTES + 1) > MAX_RULES_JSON_BYTES:
        return False, [f"custom_rules depasse {MAX_RULES_JSON_BYTES} octets"], []
    try:
        payload = json.dumps(rules, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return False, [f"custom_rules non serialisable: {exc}"], []
    # Verification stricte post-serialisation (estimation peut sous-evaluer).
    if len(payload.encode("utf-8")) > MAX_RULES_JSON_BYTES:
        return False, [f"custom_rules depasse {MAX_RULES_JSON_BYTES} octets"], []
    errors: List[str] = []
    normalized: List[Dict[str, Any]] = []
    for i, r in enumerate(rules):
        ok, errs, norm = _validate_single_rule(r, i)
        if not ok:
            errors.extend(errs)
        else:
            normalized.append(norm)
    return (len(errors) == 0), errors, normalized
