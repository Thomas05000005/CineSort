"""SettingsFacade : bounded context Configuration (issue #84 PR 3 — migration complete).

Cf docs/internal/REFACTOR_PLAN_84.md.

6 methodes du bounded context Settings :
    - get_settings : charge la config user (settings.json)
    - save_settings : persiste settings + applique side effects
    - set_locale : change la locale active (fr|en)
    - restart_api_server : reload du serveur REST
    - reset_all_user_data : V3-09 reset complet + backup ZIP
    - get_user_data_size : taille actuelle du user-data (pour Danger Zone UI)

Strategie Strangler Fig + Adapter pattern :
- Les 6 methodes existent EN PARALLELE sur CineSortApi (preserve backward-compat)
- Cette facade delegue simplement vers self._api.X
- Les nouveaux call sites peuvent utiliser api.settings.X(...)
- Les anciens call sites (api.X(...)) continuent de fonctionner
"""

from __future__ import annotations

from typing import Any, Dict

from cinesort.ui.api.facades._base import _BaseFacade


class SettingsFacade(_BaseFacade):
    """Bounded context Settings : config user (profile, integrations, locale)."""

    def get_settings(self) -> Dict[str, Any]:
        """Charge la configuration utilisateur depuis settings.json.

        Cf CineSortApi.get_settings pour la doc complete.
        """
        return self._api._get_settings_impl()

    def save_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Persiste les settings + applique side effects (state_dir, locale, etc).

        Cf CineSortApi.save_settings pour la doc complete.
        """
        return self._api._save_settings_impl(settings)

    def set_locale(self, locale: str) -> Dict[str, Any]:
        """Change la locale active (fr|en) et active immediatement le backend i18n.

        Cf CineSortApi.set_locale pour la doc complete.
        """
        return self._api._set_locale_impl(locale)

    def restart_api_server(self) -> Dict[str, Any]:
        """Arrete et relance le serveur REST avec les settings actuels.

        Cf CineSortApi.restart_api_server pour la doc complete.
        """
        return self._api._restart_api_server_impl()

    def reset_all_user_data(self, confirmation: str = "") -> Dict[str, Any]:
        """V3-09 — Reset toutes les donnees user (avec backup ZIP automatique).

        Cf CineSortApi.reset_all_user_data pour la doc complete.
        """
        return self._api._reset_all_user_data_impl(confirmation)

    def get_user_data_size(self) -> Dict[str, Any]:
        """V3-09 — Taille actuelle du user-data (pour affichage UI Danger Zone).

        Cf CineSortApi.get_user_data_size pour la doc complete.
        """
        return self._api._get_user_data_size_impl()

    # ---------- Phase 4 backend-parametres-endpoints (spec 11 §5 + §2.9) ----------
    def reset_settings(self, scope: str = "all") -> Dict[str, Any]:
        """Reinitialise les settings par categorie (ou tout).

        Cf CineSortApi._reset_settings_impl pour la doc complete.
        """
        return self._api._reset_settings_impl(scope)

    def reset_database(self) -> Dict[str, Any]:
        """Wipe complet de la DB SQLite (films/runs/perceptual/scores) + backup.

        Cf CineSortApi._reset_database_impl pour la doc complete.
        """
        return self._api._reset_database_impl()

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

    # ---------- Server info / QR code (dashboard distant) ----------
    def get_server_info(self) -> Dict[str, Any]:
        """Retourne les infos du serveur REST (IP, port, URL dashboard).

        Cf CineSortApi._get_server_info_impl pour la doc complete.
        """
        return self._api._get_server_info_impl()

    def get_dashboard_qr(self) -> Dict[str, Any]:
        """Retourne un QR code SVG inline pour l'URL du dashboard distant.

        Cf CineSortApi._get_dashboard_qr_impl pour la doc complete.
        """
        return self._api._get_dashboard_qr_impl()

    # ---------- Naming presets & template preview (sprint C1 — refactor #84 suite) ----------

    def get_naming_presets(self) -> Dict[str, Any]:
        """Retourne la liste des presets de renommage disponibles.

        Cf CineSortApi._get_naming_presets_impl pour la doc complete.
        """
        return self._api._get_naming_presets_impl()

    def preview_naming_template(self, template: str = "", sample_row_id: str = "") -> Dict[str, Any]:
        """Preview du resultat d'un template de renommage sur un film exemple.

        Cf CineSortApi._preview_naming_template_impl pour la doc complete.
        """
        return self._api._preview_naming_template_impl(template, sample_row_id)

    # ---------- VO-A UI : Advanced PRAGMA settings (storage profile + EXCLUSIVE) ----------

    def get_advanced_pragma_settings(self) -> Dict[str, Any]:
        """VO-A : retourne l'etat des PRAGMA SQLite avances (profil + locking_mode).

        Endpoint exposant le tri-etat storage_profile (auto/local_ssd/nas_smb)
        et le flag locking_mode_exclusive. Le frontend l'utilise pour pre-remplir
        la section "Avance > Stockage SQLite".

        Cf CineSortApi._get_advanced_pragma_settings_impl pour la doc complete.

        Returns:
            {
                "ok": True,
                "profile_active": str,  # profil effectif
                "profile_override": str,  # choix user
                "available_profiles": [{"v": str, "l": str}, ...],
                "storage_detected": str,
                "locking_mode_exclusive": bool,
            }
        """
        return self._api._get_advanced_pragma_settings_impl()

    def set_advanced_pragma_settings(
        self,
        profile_name: str,
        locking_mode_exclusive: bool = False,
    ) -> Dict[str, Any]:
        """VO-A : applique le profil PRAGMA et persiste dans settings.json.

        IMPORTANT (memoire user actions dangereuses) : la bascule
        locking_mode_exclusive=True est destructive (empeche toute lecture
        concurrente). Le frontend DOIT afficher dangerConfirmModal avec
        countdown 3s avant d'envoyer True ici.

        Backward compat : `locking_mode_exclusive` est keyword-only par defaut
        (False) - les anciens callers qui ne le passent pas continuent de
        fonctionner et conservent l'etat actuel desactive.

        Cf CineSortApi._set_advanced_pragma_settings_impl pour la doc complete.

        Args:
            profile_name: "auto" | "local_ssd" | "nas_smb"
            locking_mode_exclusive: True = activer locking_mode=EXCLUSIVE (defaut False)
        """
        return self._api._set_advanced_pragma_settings_impl(
            profile_name,
            locking_mode_exclusive=locking_mode_exclusive,
        )

    # ---------- VN-C.1 (batch 2) : seuils confidence unifies ----------

    def get_confidence_thresholds(self) -> Dict[str, Any]:
        """Retourne les seuils HIGH/MEDIUM/LOW partages backend+frontend.

        Source unique : cinesort/domain/confidence_thresholds.py
            { "ok": true, "thresholds": { "high": 85, "medium": 60, "low": 0 } }

        Le dashboard consomme cet endpoint au demarrage et cache la valeur
        module-level (web/dashboard/core/api.js -> fetchConfidenceThresholds).
        """
        from cinesort.ui.api.settings_support import get_confidence_thresholds_payload  # noqa: PLC0415
        return get_confidence_thresholds_payload()
