"""Phase 4 backend-parametres-endpoints (spec 11 §2.9) — Profils Qualite.

VP-F (Vague P batch 6) : module historique decoupe en 2 sous-modules
thematiques :

- `profiles_support_crud.py`           : get_profiles / save_profile / set_active_profile
- `profiles_support_import_export.py` : Recyclarr YAML, preset TRaSH 2026 embarque,
                                         upgrade_until_score, breakdown 5 axes.

Ce module conserve les memes signatures publiques (`get_profiles`, `save_profile`,
`set_active_profile`) pour preserver la backward compat ABSOLUE des call sites
(CineSortApi._get_profiles_impl, _save_profile_impl, _set_active_profile_impl).

Toute nouvelle fonctionnalite VP-F doit etre ajoutee dans
`profiles_support_import_export.py` et exposee via `quality_facade.py` etendue
(pas de nouvelle facade, recommandation critique ROADMAP).

Source de verite presets : `cinesort.domain.quality_score._build_quality_presets_catalog()`.
"""

from __future__ import annotations

# Re-exports backward compat ABSOLUE (signatures inchangees).
from cinesort.ui.api.profiles_support_crud import (
    _build_profile_row,
    _normalize_tiers_decreasing,
    _normalize_weights_sum,
    _read_settings_dict,
    _save_settings_dict,
    _WEIGHT_SUM_TARGET_FRACTION,
    _WEIGHT_SUM_TARGET_PERCENT,
    _WEIGHT_SUM_TOLERANCE_FRACTION,
    get_profiles,
    save_profile,
    set_active_profile,
)

# VP-F new symbols re-exposed pour faciliter les imports historiques.
from cinesort.ui.api.profiles_support_import_export import (
    BREAKDOWN_AXES,
    DEFAULT_UPGRADE_UNTIL_SCORE,
    MAX_PROFILES_PER_IMPORT,
    MAX_YAML_BYTES,
    export_recyclarr_yaml,
    get_breakdown_5_axes,
    get_embedded_presets,
    get_upgrade_until_score,
    import_recyclarr_yaml,
    set_upgrade_until_score,
    yaml_dump,
    yaml_load,
)

__all__ = [
    # CRUD legacy.
    "BREAKDOWN_AXES",
    "DEFAULT_UPGRADE_UNTIL_SCORE",
    "MAX_PROFILES_PER_IMPORT",
    "MAX_YAML_BYTES",
    "_build_profile_row",
    "_normalize_tiers_decreasing",
    "_normalize_weights_sum",
    "_read_settings_dict",
    "_save_settings_dict",
    "_WEIGHT_SUM_TARGET_FRACTION",
    "_WEIGHT_SUM_TARGET_PERCENT",
    "_WEIGHT_SUM_TOLERANCE_FRACTION",
    "export_recyclarr_yaml",
    "get_breakdown_5_axes",
    "get_embedded_presets",
    "get_profiles",
    "get_upgrade_until_score",
    "import_recyclarr_yaml",
    "save_profile",
    "set_active_profile",
    "set_upgrade_until_score",
    "yaml_dump",
    "yaml_load",
]
