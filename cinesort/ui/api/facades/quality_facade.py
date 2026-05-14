"""QualityFacade : bounded context Quality & Scoring (issue #84 PR 1 pilote).

Methodes prevues a terme (20) :
    - Profile (8) : get/save/reset/export/import_quality_profile,
                    get_quality_presets, apply/simulate_quality_preset
    - Report (4) : get_quality_report, analyze_quality_batch,
                   save_custom_quality_preset, get_custom_rules_templates
    - Perceptual (4) : get/analyze_perceptual_*, compare_perceptual
    - Custom rules (4) : get_custom_rules_catalog, validate_custom_rules,
                         get_calibration_report, submit_score_feedback

PR 1 (pilote) : get_quality_profile.
"""

from __future__ import annotations

from typing import Any, Dict

from cinesort.ui.api.facades._base import _BaseFacade


class QualityFacade(_BaseFacade):
    """Bounded context Quality : profil scoring, rapports, perceptual."""

    def get_quality_profile(self) -> Dict[str, Any]:
        """Retourne le profil de scoring actif (poids, seuils, toggles).

        Delegation vers CineSortApi.get_quality_profile (preserve backward-compat).
        """
        return self._api.get_quality_profile()
