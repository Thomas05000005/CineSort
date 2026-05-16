"""QualityFacade : bounded context Quality & Scoring (issue #84 PR 4 — migration complete).

Cf docs/internal/REFACTOR_PLAN_84.md.

21 methodes du bounded context Quality :
    - Profile (8) : get/save/reset/export/import_quality_profile,
                    get_quality_presets, apply/simulate_quality_preset
    - Report & rules (5) : get_quality_report, analyze_quality_batch,
                           save_custom_quality_preset, get_custom_rules_templates,
                           get_custom_rules_catalog
    - Validation rules (1) : validate_custom_rules
    - Perceptual (4) : get_perceptual_report, get_perceptual_details,
                       analyze_perceptual_batch, compare_perceptual
    - Feedback / Calibration (3) : submit_score_feedback, delete_score_feedback,
                                   get_calibration_report

Strategie Strangler Fig + Adapter pattern :
- Les 21 methodes existent EN PARALLELE sur CineSortApi (preserve backward-compat)
- Cette facade delegue simplement vers self._api.X
- Les nouveaux call sites peuvent utiliser api.quality.X(...)
- Les anciens call sites (api.X(...)) continuent de fonctionner
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from cinesort.ui.api.facades._base import _BaseFacade


class QualityFacade(_BaseFacade):
    """Bounded context Quality : profil scoring, rapports, perceptual, feedback."""

    # ---------- Profile (8) ----------

    def get_quality_profile(self) -> Dict[str, Any]:
        """Profil de scoring actif (poids, seuils, toggles).

        Cf CineSortApi.get_quality_profile pour la doc complete.
        """
        return self._api._get_quality_profile_impl()

    def save_quality_profile(self, profile_json: Any) -> Dict[str, Any]:
        """Enregistre un profil de scoring custom (valide, persiste, active).

        Cf CineSortApi.save_quality_profile pour la doc complete.
        """
        return self._api._save_quality_profile_impl(profile_json)

    def reset_quality_profile(self) -> Dict[str, Any]:
        """Reinitialise le profil de scoring aux valeurs par defaut.

        Cf CineSortApi.reset_quality_profile pour la doc complete.
        """
        return self._api._reset_quality_profile_impl()

    def export_quality_profile(self) -> Dict[str, Any]:
        """Exporte le profil de scoring actif en JSON.

        Cf CineSortApi.export_quality_profile pour la doc complete.
        """
        return self._api._export_quality_profile_impl()

    def import_quality_profile(self, profile_json: Any) -> Dict[str, Any]:
        """Importe un profil de scoring depuis JSON (valide, persiste, active).

        Cf CineSortApi.import_quality_profile pour la doc complete.
        """
        return self._api._import_quality_profile_impl(profile_json)

    def get_quality_presets(self) -> Dict[str, Any]:
        """Catalogue des presets de scoring (Remux strict / Equilibre / Light).

        Cf CineSortApi.get_quality_presets pour la doc complete.
        """
        return self._api._get_quality_presets_impl()

    def apply_quality_preset(self, preset_id: str) -> Dict[str, Any]:
        """Applique un preset du catalogue comme profil de scoring actif.

        Cf CineSortApi.apply_quality_preset pour la doc complete.
        """
        return self._api._apply_quality_preset_impl(preset_id)

    def simulate_quality_preset(
        self,
        run_id: str = "latest",
        preset_id: str = "equilibre",
        overrides: Optional[Dict[str, Any]] = None,
        scope: str = "run",
    ) -> Dict[str, Any]:
        """Simule l'application d'un preset qualite sans persister (G5).

        Cf CineSortApi.simulate_quality_preset pour la doc complete.
        """
        return self._api._simulate_quality_preset_impl(
            run_id=run_id, preset_id=preset_id, overrides=overrides, scope=scope
        )

    # ---------- Report & rules (5) ----------

    def get_quality_report(self, run_id: str, row_id: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Rapport de scoring qualite d'un film (score, tier, reasons, metrics).

        Cf CineSortApi.get_quality_report pour la doc complete.
        """
        return self._api._get_quality_report_impl(run_id, row_id, options)

    def analyze_quality_batch(
        self, run_id: str, row_ids: Any, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Analyse qualite batch sur plusieurs films (probe + scoring).

        Cf CineSortApi.analyze_quality_batch pour la doc complete.
        """
        return self._api._analyze_quality_batch_impl(run_id, row_ids, options)

    def save_custom_quality_preset(self, name: str, profile_json: Dict[str, Any]) -> Dict[str, Any]:
        """Persiste un profil qualite custom et l'active (G5).

        Cf CineSortApi.save_custom_quality_preset pour la doc complete.
        """
        return self._api._save_custom_quality_preset_impl(name, profile_json)

    def get_custom_rules_templates(self) -> Dict[str, Any]:
        """3 templates starter de regles custom (G6).

        Cf CineSortApi.get_custom_rules_templates pour la doc complete.
        """
        return self._api._get_custom_rules_templates_impl()

    def get_custom_rules_catalog(self) -> Dict[str, Any]:
        """Fields, operators et actions disponibles pour le builder UI (G6).

        Cf CineSortApi.get_custom_rules_catalog pour la doc complete.
        """
        return self._api._get_custom_rules_catalog_impl()

    # ---------- Validation rules (1) ----------

    def validate_custom_rules(self, rules: Any) -> Dict[str, Any]:
        """Valide une liste de regles custom sans persister (G6).

        Cf CineSortApi.validate_custom_rules pour la doc complete.
        """
        return self._api._validate_custom_rules_impl(rules)

    # ---------- Perceptual (4) ----------

    def get_perceptual_report(
        self, run_id: str, row_id: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Analyse perceptuelle d'un film (a la demande).

        Cf CineSortApi.get_perceptual_report pour la doc complete.
        """
        return self._api._get_perceptual_report_impl(run_id, row_id, options)

    def get_perceptual_details(self, run_id: str, row_id: str) -> Dict[str, Any]:
        """Toutes les metriques perceptuelles persistees (lecture DB).

        Cf CineSortApi.get_perceptual_details pour la doc complete.
        """
        return self._api._get_perceptual_details_impl(run_id, row_id)

    def analyze_perceptual_batch(
        self, run_id: str, row_ids: Any, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Analyse perceptuelle batch sur plusieurs films.

        Cf CineSortApi.analyze_perceptual_batch pour la doc complete.
        """
        return self._api._analyze_perceptual_batch_impl(run_id, row_ids, options)

    def compare_perceptual(
        self, run_id: str, row_id_a: str, row_id_b: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Comparaison perceptuelle profonde entre 2 fichiers.

        Cf CineSortApi.compare_perceptual pour la doc complete.
        """
        return self._api._compare_perceptual_impl(run_id, row_id_a, row_id_b, options)

    def get_perceptual_compare_frames(
        self, run_id: str, row_id_a: str, row_id_b: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Cf #94 : N paires de frames cote-a-cote en PNG base64.

        Cf CineSortApi._get_perceptual_compare_frames_impl pour la doc.
        """
        return self._api._get_perceptual_compare_frames_impl(run_id, row_id_a, row_id_b, options)

    # ---------- Feedback / Calibration (3) ----------

    def submit_score_feedback(
        self,
        run_id: str,
        row_id: str,
        user_tier: str,
        category_focus: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """P4.1 : enregistrer un feedback utilisateur sur le scoring d'un film.

        Cf CineSortApi.submit_score_feedback pour la doc complete.
        """
        return self._api._submit_score_feedback_impl(run_id, row_id, user_tier, category_focus, comment)

    def delete_score_feedback(self, feedback_id: int) -> Dict[str, Any]:
        """P4.1 : supprime un feedback utilisateur (cleanup / correction).

        Cf CineSortApi.delete_score_feedback pour la doc complete.
        """
        return self._api._delete_score_feedback_impl(feedback_id)

    def get_calibration_report(self) -> Dict[str, Any]:
        """P4.1 : agrege tous les feedbacks et propose un ajustement de poids.

        Cf CineSortApi.get_calibration_report pour la doc complete.
        """
        return self._api._get_calibration_report_impl()
