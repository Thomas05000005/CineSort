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

from cinesort.ui.api import (
    profiles_support_import_export,
    quality_audit_support,
)
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

    def get_perceptual_compare_audio(
        self, run_id: str, row_id_a: str, row_id_b: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Phase 4 doublons : waveform PNG + clip MP3 court cote-a-cote.

        Cf docs/internal/design/refonte_2026_05_17/screens/01-doublons.md
        section 3 "Comparaison audio". Pattern similaire a
        get_perceptual_compare_frames.
        """
        return self._api._get_perceptual_compare_audio_impl(run_id, row_id_a, row_id_b, options)

    def queue_perceptual_analyses(self, pairs: Any, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Phase 4 doublons : queue batch d'analyses perceptuelles en background.

        Args:
            pairs: liste de {run_id, row_a, row_b}.
            options: passe a compare_perceptual.

        Returns:
            {ok, job_id, total}. Polling via get_perceptual_job_status(job_id).
        """
        return self._api._queue_perceptual_analyses_impl(pairs, options)

    def queue_perceptual_batch(
        self, run_id: str, row_ids: Any, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """R5-C : analyse perceptuelle batch SINGLE-film (biblio) en background.

        Returns:
            {ok, job_id, total}. Polling via get_perceptual_job_status(job_id).
        """
        return self._api._queue_perceptual_batch_impl(run_id, row_ids, options)

    def get_perceptual_job_status(self, job_id: str) -> Dict[str, Any]:
        """Phase 4 doublons : statut d'un job perceptuel batch."""
        return self._api._get_perceptual_job_status_impl(job_id)

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

    # ---------- Phase 4 backend-parametres-endpoints (spec 11 §2.9) ----------
    # Alias quality/X(...) -> meme impl que settings/X(...). Spec 11 §7 cite
    # `quality/get_profiles()`, l'orchestration reelle delegue vers profiles_support.

    def get_profiles(self) -> Dict[str, Any]:
        """Liste tous les profils qualite (presets + custom).

        Cf CineSortApi._get_profiles_impl pour la doc complete.
        """
        return self._api._get_profiles_impl()

    def save_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Sauve un profil qualite custom (avec validation tiers + poids).

        Cf CineSortApi._save_profile_impl pour la doc complete.
        """
        return self._api._save_profile_impl(profile)

    def set_active_profile(self, profile_id: str) -> Dict[str, Any]:
        """Active un profil qualite (preset ou custom).

        Cf CineSortApi._set_active_profile_impl pour la doc complete.
        """
        return self._api._set_active_profile_impl(profile_id)

    # ---------- Vue Qualite — Audit (spec 10) ----------

    def get_films_by_tier(self, tier: str, limit: int = 8) -> Dict[str, Any]:
        """Liste les films d'un tier V2 (default top 8 pires Reject par score asc).

        Cf cinesort.ui.api.quality_audit_support.get_films_by_tier.
        """
        return quality_audit_support.get_films_by_tier(self._api, tier=tier, limit=limit)

    def get_history(self, period_days: int = 30) -> Dict[str, Any]:
        """KPIs evolution score V2 + deltas sur N derniers jours.

        Cf cinesort.ui.api.quality_audit_support.get_history.
        """
        return quality_audit_support.get_history(self._api, period_days=period_days)

    def recompute_all_scores(self) -> Dict[str, Any]:
        """Lance le recalcul background du Score V2 pour tous les films.

        Cf cinesort.ui.api.quality_audit_support.recompute_all_scores.
        """
        return quality_audit_support.recompute_all_scores(self._api)

    def get_recompute_job_status(self, job_id: str) -> Dict[str, Any]:
        """Polling du status d'un job de recalcul lance par recompute_all_scores.

        Cf cinesort.ui.api.quality_audit_support.get_recompute_job_status.
        """
        return quality_audit_support.get_recompute_job_status(self._api, job_id=job_id)

    # ---------- Shareable profile exchange (sprint C1 — refactor #84 suite) ----------
    # Distinct de export/import_quality_profile (formats bruts) : le format
    # "shareable" wrap le profil dans un schema avec metadata (name, author,
    # description, exported_at) pour le partage inter-utilisateurs (P4.3).

    def export_shareable_profile(
        self,
        name: str = "",
        author: str = "",
        description: str = "",
    ) -> Dict[str, Any]:
        """P4.3 : exporte le profil qualite actif au format communautaire.

        Cf CineSortApi._export_shareable_profile_impl pour la doc complete.
        """
        return self._api._export_shareable_profile_impl(name=name, author=author, description=description)

    def import_shareable_profile(self, content: str, activate: bool = True) -> Dict[str, Any]:
        """P4.3 : importe un profil depuis un JSON communautaire (avec metadata).

        Cf CineSortApi._import_shareable_profile_impl pour la doc complete.
        """
        return self._api._import_shareable_profile_impl(content, activate=activate)

    # ---------- VP-F (Vague P batch 6) — Recyclarr YAML round-trip ----------
    # Extension de la facade (PAS nouvelle facade, recommandation critique ROADMAP).
    # Cf cinesort/ui/api/profiles_support_import_export.py.

    def export_recyclarr_yaml(self, profile_id: Optional[str] = None) -> Dict[str, Any]:
        """Exporte un profil au format Recyclarr v6+ YAML (round-trip lossless).

        Args:
            profile_id: optionnel - profil specifique (preset ou custom). Si None,
                exporte le profil actif.

        Cf cinesort.ui.api.profiles_support_import_export.export_recyclarr_yaml.
        """
        return profiles_support_import_export.export_recyclarr_yaml(self._api, profile_id=profile_id)

    def import_recyclarr_yaml(self, yaml_text: str, activate: bool = False) -> Dict[str, Any]:
        """Importe un profil depuis YAML Recyclarr, persiste comme custom.

        Args:
            yaml_text: contenu YAML brut.
            activate: si True, active le profil immediatement apres import.

        Cf cinesort.ui.api.profiles_support_import_export.import_recyclarr_yaml.
        """
        return profiles_support_import_export.import_recyclarr_yaml(self._api, yaml_text, activate=activate)

    # ---------- VP-F — Preset TRaSH 2026 embarque (AC-3 : OFF par defaut) ----------

    def get_embedded_presets(self) -> Dict[str, Any]:
        """Retourne le preset TRaSH 2026 + alternatifs (puriste DV, qualite max audio).

        AC-3 : tous DESACTIVES par defaut (enabled_by_default=False). Aucune
        mutation silencieuse au demarrage.

        Cf cinesort.ui.api.profiles_support_import_export.get_embedded_presets.
        """
        return profiles_support_import_export.get_embedded_presets(self._api)

    # ---------- VP-F — upgrade_until_score (AC-5 : default 10000) ----------

    def get_upgrade_until_score(self) -> Dict[str, Any]:
        """Retourne le upgrade_until_score du profil actif (default 10000).

        Cf cinesort.ui.api.profiles_support_import_export.get_upgrade_until_score.
        """
        return profiles_support_import_export.get_upgrade_until_score(self._api)

    def set_upgrade_until_score(self, score: Any) -> Dict[str, Any]:
        """Met a jour le upgrade_until_score du profil actif (borne [0..100000]).

        Cf cinesort.ui.api.profiles_support_import_export.set_upgrade_until_score.
        """
        return profiles_support_import_export.set_upgrade_until_score(self._api, score)

    # ---------- VP-F — Breakdown 5 axes (AC-4 : Source/Codec/HDR/Audio/Group) ----------

    def get_breakdown_5_axes(self) -> Dict[str, Any]:
        """Retourne le breakdown 5 axes du profil actif pour affichage UI.

        Memo `feedback_cinesort_ui_pacotille` : eviter fonctions backend invisibles.

        Cf cinesort.ui.api.profiles_support_import_export.get_breakdown_5_axes.
        """
        return profiles_support_import_export.get_breakdown_5_axes(self._api)
