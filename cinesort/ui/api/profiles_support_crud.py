"""VP-F (Vague P batch 6) — Quality profiles CRUD (extrait de profiles_support.py).

Decoupe du module monolithique `profiles_support.py` (421 LOC) en 2 sous-modules
thematiques sans regression API :

- `profiles_support_crud.py`  : get_profiles / save_profile / set_active_profile
- `profiles_support_import_export.py` : Recyclarr YAML, preset TRaSH embarque,
                                         upgrade_until_score, breakdown 5 axes.

Le module historique `profiles_support.py` re-exporte tout pour preserver la
backward compat ABSOLUE des call sites (CineSortApi._get_profiles_impl, etc.).

Source de verite presets : `cinesort.domain.quality_score._build_quality_presets_catalog()`.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Tuple

from cinesort.domain import (
    list_quality_presets,
    quality_profile_from_preset,
    validate_quality_profile,
)
from cinesort.domain.custom_rules import validate_rules as _validate_custom_rules
from cinesort.ui.api._responses import err

logger = logging.getLogger(__name__)


# Tolerance sur la somme des poids (UI envoie soit fraction 1.0 soit pourcentages
# 100). On clamp [0.95..1.05] (fraction) ou [95..105] (percent).
_WEIGHT_SUM_TOLERANCE_FRACTION = 0.05  # +/- 5 %
_WEIGHT_SUM_TARGET_FRACTION = 1.0
_WEIGHT_SUM_TARGET_PERCENT = 100.0


def _normalize_tiers_decreasing(tiers: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Verifie que platinum > gold > silver > bronze (strictement decroissant).

    Cf spec 11 §2.9 : "Platinum  : score >= [90] / Gold : score >= [80] / ...".
    Si l'ordre n'est pas respecte, on retourne errors avec messages explicites.
    """
    order = ("platinum", "gold", "silver", "bronze")
    values: List[Tuple[str, float]] = []
    errors: List[str] = []
    for name in order:
        raw = tiers.get(name)
        if raw is None:
            errors.append(f"Tier '{name}' manquant.")
            continue
        try:
            values.append((name, float(raw)))
        except (TypeError, ValueError):
            errors.append(f"Tier '{name}' invalide (nombre attendu, recu {raw!r}).")

    if errors:
        return False, errors

    # Verif strictement decroissant
    for (name_a, v_a), (name_b, v_b) in zip(values, values[1:], strict=False):
        if v_a <= v_b:
            errors.append(f"Seuils non decroissants : {name_a} ({v_a}) doit etre > {name_b} ({v_b}).")
    return (len(errors) == 0), errors


def _normalize_weights_sum(weights: Dict[str, Any]) -> Tuple[bool, List[str], float]:
    """Verifie que la somme des poids tombe dans la tolerance.

    Accepte soit fraction (somme ~1.0) soit pourcentages (somme ~100). Retourne
    (ok, errors, total_normalise) ou total_normalise est en fraction.
    """
    errors: List[str] = []
    if not isinstance(weights, dict) or not weights:
        return False, ["Champ 'weights' manquant ou vide."], 0.0

    total = 0.0
    for key, raw in weights.items():
        try:
            total += float(raw)
        except (TypeError, ValueError):
            errors.append(f"Poids '{key}' invalide (nombre attendu, recu {raw!r}).")

    if errors:
        return False, errors, 0.0

    # Detect format : fraction (~1.0) vs percent (~100)
    if total > 5.0:  # heuristique : si > 5, c'est forcement des pourcentages
        target = _WEIGHT_SUM_TARGET_PERCENT
        tolerance_abs = _WEIGHT_SUM_TARGET_PERCENT * _WEIGHT_SUM_TOLERANCE_FRACTION
        normalized_fraction = total / 100.0
    else:
        target = _WEIGHT_SUM_TARGET_FRACTION
        tolerance_abs = _WEIGHT_SUM_TOLERANCE_FRACTION
        normalized_fraction = total

    if abs(total - target) > tolerance_abs:
        errors.append(f"Somme des poids = {total:.3f}, attendue ~{target:g} (+/- {tolerance_abs:g}).")
        return False, errors, normalized_fraction
    return True, [], normalized_fraction


def _build_profile_row(
    profile_json: Dict[str, Any],
    *,
    preset_id: str = "",
    label: str = "",
    description: str = "",
    is_custom: bool = False,
    is_active: bool = False,
) -> Dict[str, Any]:
    """Format de sortie commun pour `get_profiles`."""
    pid = str(profile_json.get("id") or "")
    return {
        "id": pid,
        "preset_id": preset_id,
        "name": label or pid,
        "label": label or pid,
        "description": description,
        "version": int(profile_json.get("version") or 1),
        "is_active": bool(is_active),
        "is_custom": bool(is_custom),
        "tiers": dict(profile_json.get("tiers") or {}),
        "weights": dict(profile_json.get("weights") or {}),
        "toggles": dict(profile_json.get("toggles") or {}),
        "tier_hierarchy": dict(profile_json.get("tier_hierarchy") or {}),
        "upgrade_until_score": int(profile_json.get("upgrade_until_score") or 10000),
        "profile_json": profile_json,
    }


def _read_settings_dict(api: Any) -> Dict[str, Any]:
    """Helper : recupere les settings courants via la facade settings."""
    try:
        return api.settings.get_settings() or {}
    except (AttributeError, OSError, TypeError, ValueError):
        return {}


def _save_settings_dict(api: Any, settings: Dict[str, Any]) -> Dict[str, Any]:
    """Helper : persiste les settings via la facade settings."""
    return api.settings.save_settings(settings)


def get_profiles(api: Any) -> Dict[str, Any]:
    """Retourne la liste des profils qualite (presets + custom) avec flag is_active.

    Format reponse :
    {
      "ok": True,
      "profiles": [
        {id, preset_id, name, label, description, version, is_active, is_custom,
         tiers, weights, toggles, tier_hierarchy, upgrade_until_score, profile_json},
        ...
      ],
      "active_profile_id": "...",
    }

    VP-F : tier_hierarchy et upgrade_until_score exposes dans chaque profile_row
    (auparavant uniquement dans profile_json brut). Backward compat ABSOLUE :
    les anciens champs restent presents.
    """
    try:
        settings = _read_settings_dict(api)
        active_id_raw = str(settings.get("active_quality_profile_id") or "").strip()

        # Profile actif persiste en DB (lecture pour fallback active_id)
        try:
            active_payload = api._active_quality_profile_payload()
            db_active_id = str(active_payload.get("profile_id") or "")
        except (AttributeError, OSError, KeyError, TypeError, ValueError):
            db_active_id = ""

        # Si pas d'active_id explicite dans settings, prendre celui du store
        effective_active_id = active_id_raw or db_active_id

        out: List[Dict[str, Any]] = []
        preset_rows = list_quality_presets(include_profiles=True)
        for row in preset_rows:
            profile_json = row.get("profile_json") or {}
            pid = str(profile_json.get("id") or row.get("profile_id") or "")
            preset_id = str(row.get("preset_id") or "")
            # is_active match si effective_active_id == profile_json.id OU
            # == preset_id (l'utilisateur peut avoir stocke l'un ou l'autre).
            is_active = effective_active_id != "" and effective_active_id in (pid, preset_id)
            out.append(
                _build_profile_row(
                    profile_json,
                    preset_id=preset_id,
                    label=str(row.get("label") or ""),
                    description=str(row.get("description") or ""),
                    is_custom=False,
                    is_active=is_active,
                )
            )

        # Custom profiles (stockes dans settings)
        custom_raw = settings.get("custom_quality_profiles") or []
        if isinstance(custom_raw, list):
            for entry in custom_raw:
                if not isinstance(entry, dict):
                    continue
                pid = str(entry.get("id") or "")
                if not pid:
                    continue
                out.append(
                    _build_profile_row(
                        entry,
                        preset_id="",
                        label=str(entry.get("label") or entry.get("name") or pid),
                        description=str(entry.get("description") or "Profil personnalise"),
                        is_custom=True,
                        is_active=(pid == effective_active_id),
                    )
                )

        return {
            "ok": True,
            "profiles": out,
            "active_profile_id": effective_active_id,
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return err(f"get_profiles failed: {exc}", category="runtime", level="error")


def save_profile(api: Any, profile: Any) -> Dict[str, Any]:
    """Sauve un profil qualite custom dans settings.custom_quality_profiles.

    Validation :
    - Profile = dict avec champs requis (id, version, weights, tiers)
    - tiers strictement decroissants : platinum > gold > silver > bronze
    - somme des poids dans tolerance (~1.00 ou ~100)
    - validate_quality_profile (validation backend existante)

    Retourne {ok, profile_id, profile_version}.
    """
    try:
        if not isinstance(profile, dict):
            return err(
                "Profil invalide : objet JSON attendu.",
                category="validation",
                level="warning",
            )

        # 1) Validation tiers decroissants
        tiers = profile.get("tiers") or {}
        if not isinstance(tiers, dict):
            return err(
                "Champ 'tiers' invalide (objet attendu).",
                category="validation",
                level="warning",
            )
        tiers_ok, tier_errs = _normalize_tiers_decreasing(tiers)
        if not tiers_ok:
            return err(
                "Seuils de tier invalides.",
                category="validation",
                level="warning",
                errors=tier_errs,
            )

        # 2) Validation somme des poids
        weights = profile.get("weights") or {}
        weights_ok, weight_errs, _normalized_total = _normalize_weights_sum(weights)
        if not weights_ok:
            return err(
                "Poids invalides.",
                category="validation",
                level="warning",
                errors=weight_errs,
            )

        # 3) Validation backend (cinesort.domain.validate_quality_profile)
        ok_full, full_errs, normalized = validate_quality_profile(profile)
        if not ok_full:
            return err(
                "Profil rejete par la validation backend.",
                category="validation",
                level="warning",
                errors=full_errs,
            )

        profile_id = str(normalized.get("id") or "").strip()
        if not profile_id:
            return err(
                "Champ 'id' du profil manquant.",
                category="validation",
                level="warning",
            )

        # 4) Persistance dans settings.custom_quality_profiles (merge par id)
        settings = _read_settings_dict(api)
        custom = settings.get("custom_quality_profiles") or []
        if not isinstance(custom, list):
            custom = []

        # Replace si meme id, sinon append
        replaced = False
        new_custom = []
        for entry in custom:
            if isinstance(entry, dict) and str(entry.get("id") or "") == profile_id:
                new_custom.append(copy.deepcopy(normalized))
                replaced = True
            else:
                new_custom.append(entry)
        if not replaced:
            new_custom.append(copy.deepcopy(normalized))

        settings["custom_quality_profiles"] = new_custom
        save_result = _save_settings_dict(api, settings)
        if not save_result.get("ok"):
            return err(
                f"Echec persistance settings : {save_result.get('error') or save_result}",
                category="runtime",
                level="error",
            )

        return {
            "ok": True,
            "profile_id": profile_id,
            "profile_version": int(normalized.get("version") or 1),
            "is_custom": True,
            "replaced": replaced,
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return err(f"save_profile failed: {exc}", category="runtime", level="error")


def _ecarter_les_regles_invalides(normalized: Dict[str, Any], pid: str) -> None:
    """Retire du profil les regles custom que `validate_rules` refuse.

    POURQUOI CE CHEMIN, ET PAS LE VALIDATEUR DE PROFIL — c'est mesure, pas
    suppose. `validate_quality_profile` laisse passer `custom_rules` verbatim en
    deleguant par commentaire ; cette delegation n'a pas de point d'application
    garanti. Deux essais de la poser dans le validateur ont chacun ETEINT une
    garde existante :

    - ajouter ses erreurs a `errs` : `compute_quality_score` fait
      `if not ok: return _build_invalid_profile_result(...)`, donc une regle
      inutilisable mettait TOUS les films a 0 (mesure : 0 au lieu de 46), ce qui
      annulait #723 — refuser la VALEUR en preservant le score ;
    - y ecarter les regles : `save_quality_profile` lit `custom_rules` APRES lui,
      donc sa propre verification ne voyait plus rien et son refus de #723
      cessait de fonctionner.

    Ce chemin-ci re-persiste du STOCKE, que personne ne saisit. On ECARTE donc,
    au lieu de refuser l'activation : un profil stocke doit rester activable, et
    une regle inutilisable ne doit ni s'appliquer, ni etre reecrite.
    """
    regles = normalized.get("custom_rules")
    if not isinstance(regles, list) or not regles:
        return
    gardees: List[Dict[str, Any]] = []
    for regle in regles:
        regle_ok, _errs, regle_norm = _validate_custom_rules([regle])
        if regle_ok and regle_norm:
            gardees.extend(regle_norm)
        else:
            logger.warning(
                "set_active_profile: regle custom ecartee (invalide) profil=%s id=%s",
                pid,
                regle.get("id") if isinstance(regle, dict) else None,
            )
    normalized["custom_rules"] = gardees


def set_active_profile(api: Any, profile_id: str) -> Dict[str, Any]:
    """Active un profil qualite (preset OU custom).

    Effets :
    1) settings.active_quality_profile_id = profile_id
    2) Profil charge dans la DB via _save_active_quality_profile (active dans store)

    Retourne {ok, active_profile_id}.
    """
    try:
        pid = str(profile_id or "").strip()
        if not pid:
            return err(
                "profile_id requis.",
                category="validation",
                level="info",
            )

        # 1) Resolution : preset, profile_id (CinemaLux_v1, ...) ou custom
        profile_json = None

        # 1a) Preset par preset_id (ex. "equilibre")
        preset_profile = quality_profile_from_preset(pid)
        if preset_profile is not None:
            profile_json = preset_profile

        # 1b) Preset par profile_id (ex. "CinemaLux_v1", "StreamingOptimal_v1")
        if profile_json is None:
            for row in list_quality_presets(include_profiles=True):
                row_profile = row.get("profile_json") or {}
                if str(row_profile.get("id") or "") == pid:
                    profile_json = copy.deepcopy(row_profile)
                    break

        # 1c) Custom profile stocke dans settings
        settings = _read_settings_dict(api)
        if profile_json is None:
            for entry in settings.get("custom_quality_profiles") or []:
                if isinstance(entry, dict) and str(entry.get("id") or "") == pid:
                    profile_json = copy.deepcopy(entry)
                    break

        if profile_json is None:
            return err(
                f"Profil inconnu : {pid}",
                category="resource",
                level="warning",
            )

        # 2) Validation finale (deja faite a la sauvegarde mais belt and suspenders)
        ok, errs, normalized = validate_quality_profile(profile_json)
        if not ok:
            return err(
                "Profil invalide.",
                category="validation",
                level="warning",
                errors=errs,
            )

        # 2b) Les regles custom : validees ICI aussi, seul chemin qui les
        # re-persistait sans le faire. Cf. `_ecarter_les_regles_invalides`.
        _ecarter_les_regles_invalides(normalized, pid)

        # 3) Persistance settings.active_quality_profile_id
        # On garde l'ancienne valeur pour rollback si la DB echoue ensuite.
        previous_active_id = settings.get("active_quality_profile_id")
        settings["active_quality_profile_id"] = pid
        save_result = _save_settings_dict(api, settings)
        if not save_result.get("ok"):
            return err(
                f"Echec persistance settings : {save_result.get('error') or save_result}",
                category="runtime",
                level="error",
            )

        # 4) Activation dans la DB. Si la DB echoue apres la sauvegarde settings,
        # on rollback settings pour eviter une divergence persistante entre
        # settings.active_quality_profile_id et le profil charge en DB.
        try:
            api._save_active_quality_profile(normalized)
        except (OSError, KeyError, TypeError, ValueError, AttributeError) as db_exc:
            settings["active_quality_profile_id"] = previous_active_id
            try:
                _save_settings_dict(api, settings)
            except (OSError, KeyError, TypeError, ValueError):
                logger.exception("set_active_profile: rollback settings.active_quality_profile_id failed")
            return err(
                f"Echec activation DB (settings rollback effectue) : {db_exc}",
                category="runtime",
                level="error",
            )

        return {
            "ok": True,
            "active_profile_id": pid,
            "profile_version": int(normalized.get("version") or 1),
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return err(f"set_active_profile failed: {exc}", category="runtime", level="error")
